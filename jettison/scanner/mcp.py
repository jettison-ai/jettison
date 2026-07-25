"""MCP server discovery and live schema introspection.

Discovery reads each client's MCP registration files (launch specs only —
name/command/args/env). Introspection then speaks minimal MCP over stdio
(JSON-RPC: ``initialize`` → ``tools/list``) to fetch the *actual* tool
schemas the client would materialize into model context. Headroom's
mcp_registry stops at launch specs; the schema fetch is Jettison's.

Introspection is read-only with respect to the servers (a tools/list
round-trip) but does launch the server process; ``--no-launch`` audits
from config alone with estimated sizes.
"""

from __future__ import annotations

import json
import os
import selectors
import subprocess
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

try:  # Python 3.11+
    import tomllib
except ImportError:  # pragma: no cover
    tomllib = None  # type: ignore[assignment]

MCP_PROTOCOL_VERSION = "2025-06-18"
# Generous by design: most real servers launch through `npx`/`uvx`, which
# resolves (and sometimes downloads) a package before the process even
# starts speaking MCP. A tight timeout silently degrades those servers to
# config-only estimates, which is the difference between a measured audit
# and a useless one. Scanning is concurrent, so this is wall-clock-cheap.
INTROSPECT_TIMEOUT_S = 90.0

# Per-tool overhead the host adds around each schema when materializing it
# into context (name prefixing, framing). Conservative flat estimate.
PER_TOOL_FRAMING_TOKENS = 15
# Config-only fallback when a server can't be launched: median observed
# schema cost per MCP tool across public servers; labeled estimated.
ESTIMATED_TOKENS_PER_UNKNOWN_SERVER = 2500


@dataclass
class MCPServerSpec:
    name: str
    command: str
    args: list[str] = field(default_factory=list)
    env: dict[str, str] = field(default_factory=dict)
    transport: str = "stdio"  # "stdio" | "http" | "sse"
    url: str = ""
    source: str = ""  # config file it came from


@dataclass
class MCPTool:
    server: str
    name: str
    description: str
    input_schema: dict[str, Any]

    def context_json(self) -> dict[str, Any]:
        """The tool definition as it would appear in a request body."""
        return {
            "name": f"mcp__{self.server}__{self.name}",
            "description": self.description,
            "input_schema": self.input_schema,
        }


# ---------------------------------------------------------------------------
# Config discovery
# ---------------------------------------------------------------------------


def _load_json(path: Path) -> dict:
    try:
        return json.loads(path.read_text())
    except Exception:
        return {}


def _specs_from_mcpservers_map(servers: dict, source: Path) -> list[MCPServerSpec]:
    specs = []
    for name, entry in (servers or {}).items():
        if not isinstance(entry, dict):
            continue
        transport = entry.get("type") or entry.get("transport") or "stdio"
        specs.append(
            MCPServerSpec(
                name=name,
                command=entry.get("command", ""),
                args=list(entry.get("args", []) or []),
                env={k: str(v) for k, v in (entry.get("env") or {}).items()},
                transport="http" if transport in ("http", "sse", "streamable-http") else "stdio",
                url=entry.get("url", ""),
                source=str(source),
            )
        )
    return specs


def discover_claude_code(project_dir: Path) -> list[MCPServerSpec]:
    """Claude Code: ~/.claude.json (global + per-project), ./.mcp.json."""
    specs: list[MCPServerSpec] = []
    claude_json = Path.home() / ".claude.json"
    if claude_json.exists():
        data = _load_json(claude_json)
        specs += _specs_from_mcpservers_map(data.get("mcpServers", {}), claude_json)
        projects = data.get("projects", {})
        proj = projects.get(str(project_dir)) or {}
        specs += _specs_from_mcpservers_map(proj.get("mcpServers", {}), claude_json)
    legacy = Path.home() / ".claude" / "mcp.json"
    if legacy.exists():
        specs += _specs_from_mcpservers_map(_load_json(legacy).get("mcpServers", {}), legacy)
    project_mcp = project_dir / ".mcp.json"
    if project_mcp.exists():
        specs += _specs_from_mcpservers_map(_load_json(project_mcp).get("mcpServers", {}), project_mcp)
    return _dedupe(specs)


def discover_codex(project_dir: Path) -> list[MCPServerSpec]:
    """Codex: [mcp_servers.*] tables in config.toml."""
    specs: list[MCPServerSpec] = []
    if tomllib is None:
        return specs
    codex_home = Path(os.environ.get("CODEX_HOME", Path.home() / ".codex"))
    for cfg in (codex_home / "config.toml", project_dir / ".codex" / "config.toml"):
        if not cfg.exists():
            continue
        try:
            data = tomllib.loads(cfg.read_text())
        except Exception:
            continue
        for name, entry in (data.get("mcp_servers") or {}).items():
            if not isinstance(entry, dict):
                continue
            specs.append(
                MCPServerSpec(
                    name=name,
                    command=entry.get("command", ""),
                    args=list(entry.get("args", []) or []),
                    env={k: str(v) for k, v in (entry.get("env") or {}).items()},
                    source=str(cfg),
                )
            )
    return _dedupe(specs)


def discover_cursor(project_dir: Path) -> list[MCPServerSpec]:
    specs: list[MCPServerSpec] = []
    for cfg in (Path.home() / ".cursor" / "mcp.json", project_dir / ".cursor" / "mcp.json"):
        if cfg.exists():
            specs += _specs_from_mcpservers_map(_load_json(cfg).get("mcpServers", {}), cfg)
    return _dedupe(specs)


def discover_cline(project_dir: Path) -> list[MCPServerSpec]:
    candidates = [
        Path.home()
        / "Library/Application Support/Code/User/globalStorage/saoudrizwan.claude-dev/settings/cline_mcp_settings.json",
        Path.home() / ".config/Code/User/globalStorage/saoudrizwan.claude-dev/settings/cline_mcp_settings.json",
    ]
    specs: list[MCPServerSpec] = []
    for cfg in candidates:
        if cfg.exists():
            specs += _specs_from_mcpservers_map(_load_json(cfg).get("mcpServers", {}), cfg)
    return _dedupe(specs)


def discover_opencode(project_dir: Path) -> list[MCPServerSpec]:
    cfg_env = os.environ.get("OPENCODE_CONFIG")
    candidates = [Path(cfg_env)] if cfg_env else []
    candidates += [
        Path.home() / ".config/opencode/opencode.json",
        Path.home() / ".config/opencode/opencode.jsonc",
        project_dir / "opencode.json",
    ]
    specs: list[MCPServerSpec] = []
    for cfg in candidates:
        if cfg and cfg.exists():
            data = _load_json(cfg)
            mcp = data.get("mcp", {})
            for name, entry in mcp.items():
                if not isinstance(entry, dict):
                    continue
                cmd = entry.get("command", [])
                if isinstance(cmd, list) and cmd:
                    command, args = cmd[0], cmd[1:]
                else:
                    command, args = str(cmd), []
                specs.append(
                    MCPServerSpec(
                        name=name,
                        command=command,
                        args=args,
                        env={k: str(v) for k, v in (entry.get("environment") or {}).items()},
                        transport="http" if entry.get("type") == "remote" else "stdio",
                        url=entry.get("url", ""),
                        source=str(cfg),
                    )
                )
    return _dedupe(specs)


def discover_openclaw(project_dir: Path) -> list[MCPServerSpec]:
    cfg = Path.home() / ".openclaw" / "openclaw.json"
    if not cfg.exists():
        return []
    data = _load_json(cfg)
    servers = data.get("mcpServers", {}) or (data.get("mcp") or {}).get("servers", {})
    return _dedupe(_specs_from_mcpservers_map(servers, cfg))


DISCOVERERS = {
    "claude": discover_claude_code,
    "codex": discover_codex,
    "cursor": discover_cursor,
    "cline": discover_cline,
    "opencode": discover_opencode,
    "openclaw": discover_openclaw,
}


def _dedupe(specs: list[MCPServerSpec]) -> list[MCPServerSpec]:
    seen: dict[str, MCPServerSpec] = {}
    for s in specs:
        seen.setdefault(s.name, s)
    return list(seen.values())


# ---------------------------------------------------------------------------
# Live stdio introspection (initialize -> tools/list)
# ---------------------------------------------------------------------------


class MCPIntrospectionError(Exception):
    pass


def _rpc(msg_id: int, method: str, params: dict | None = None) -> bytes:
    body: dict[str, Any] = {"jsonrpc": "2.0", "id": msg_id, "method": method}
    if params is not None:
        body["params"] = params
    return (json.dumps(body) + "\n").encode()


def introspect_stdio_server(
    spec: MCPServerSpec, timeout: float = INTROSPECT_TIMEOUT_S
) -> list[MCPTool]:
    """Launch the server, run the MCP handshake, fetch tools/list, terminate."""
    if not spec.command:
        raise MCPIntrospectionError(f"{spec.name}: no command configured")
    env = {**os.environ, **spec.env}
    try:
        proc = subprocess.Popen(
            [spec.command, *spec.args],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            env=env,
        )
    except OSError as e:
        raise MCPIntrospectionError(f"{spec.name}: launch failed: {e}") from e

    try:
        deadline = time.monotonic() + timeout
        assert proc.stdin and proc.stdout
        proc.stdin.write(
            _rpc(
                1,
                "initialize",
                {
                    "protocolVersion": MCP_PROTOCOL_VERSION,
                    "capabilities": {},
                    "clientInfo": {"name": "jettison-audit", "version": "0.1.0"},
                },
            )
        )
        proc.stdin.flush()
        _read_response(proc, 1, deadline)
        proc.stdin.write(b'{"jsonrpc":"2.0","method":"notifications/initialized"}\n')
        proc.stdin.flush()

        tools: list[MCPTool] = []
        cursor: str | None = None
        msg_id = 2
        while True:
            params = {"cursor": cursor} if cursor else {}
            proc.stdin.write(_rpc(msg_id, "tools/list", params))
            proc.stdin.flush()
            result = _read_response(proc, msg_id, deadline)
            for t in result.get("tools", []):
                tools.append(
                    MCPTool(
                        server=spec.name,
                        name=t.get("name", ""),
                        description=t.get("description", "") or "",
                        input_schema=t.get("inputSchema", {}) or {},
                    )
                )
            cursor = result.get("nextCursor")
            msg_id += 1
            if not cursor:
                return tools
    finally:
        proc.terminate()
        try:
            proc.wait(timeout=2)
        except subprocess.TimeoutExpired:
            proc.kill()


def _read_response(proc: subprocess.Popen, want_id: int, deadline: float) -> dict:
    """Read newline-delimited JSON-RPC until the response for want_id."""
    sel = selectors.DefaultSelector()
    assert proc.stdout
    sel.register(proc.stdout, selectors.EVENT_READ)
    buf = b""
    while True:
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            raise MCPIntrospectionError("timeout waiting for MCP response")
        if not sel.select(timeout=min(remaining, 0.5)):
            if proc.poll() is not None:
                raise MCPIntrospectionError("server exited during handshake")
            continue
        chunk = os.read(proc.stdout.fileno(), 65536)
        if not chunk:
            raise MCPIntrospectionError("server closed stdout")
        buf += chunk
        while b"\n" in buf:
            line, buf = buf.split(b"\n", 1)
            line = line.strip()
            if not line:
                continue
            try:
                msg = json.loads(line)
            except json.JSONDecodeError:
                continue  # non-protocol noise on stdout
            if msg.get("id") == want_id:
                if "error" in msg:
                    raise MCPIntrospectionError(str(msg["error"]))
                return msg.get("result", {})
