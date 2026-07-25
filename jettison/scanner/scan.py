"""Standing-context scan orchestrator (the engine behind `jettison audit`).

Read-only: enumerates MCP tool schemas (live introspection where
possible), skills and instruction files for a client, tokenizes each item
as it would appear in a request body, and reports per-category waste.
"""

from __future__ import annotations

import json
from pathlib import Path

from jettison.scanner import duplicates as dup_mod
from jettison.scanner import instructions as instr_mod
from jettison.scanner import mcp as mcp_mod
from jettison.scanner.model import Category, ScanItem, ScanReport
from jettison.tokens import DEFAULT_MODEL, count_text

SUPPORTED_CLIENTS = sorted(mcp_mod.DISCOVERERS.keys())


def scan(
    client: str = "claude",
    project_dir: Path | None = None,
    model: str = DEFAULT_MODEL,
    launch_servers: bool = True,
    introspect_timeout: float = mcp_mod.INTROSPECT_TIMEOUT_S,
) -> ScanReport:
    if client not in mcp_mod.DISCOVERERS:
        raise ValueError(f"unknown client {client!r}; supported: {SUPPORTED_CLIENTS}")
    project_dir = (project_dir or Path.cwd()).resolve()
    report = ScanReport(client=client, project_dir=str(project_dir), model=model)

    _scan_mcp(report, client, project_dir, launch_servers, introspect_timeout, model)
    _scan_instructions(report, client, project_dir, model)
    return report


def _scan_mcp(
    report: ScanReport,
    client: str,
    project_dir: Path,
    launch_servers: bool,
    timeout: float,
    model: str,
) -> None:
    specs = mcp_mod.DISCOVERERS[client](project_dir)
    for spec in specs:
        if spec.transport != "stdio" or not launch_servers:
            _add_unintrospected(report, spec)
            continue
        try:
            tools = mcp_mod.introspect_stdio_server(spec, timeout=timeout)
        except mcp_mod.MCPIntrospectionError as e:
            report.warnings.append(f"could not introspect MCP server '{spec.name}': {e}")
            _add_unintrospected(report, spec)
            continue
        for tool in tools:
            payload = json.dumps(tool.context_json(), separators=(",", ":"), ensure_ascii=False)
            tc = count_text(payload, model)
            report.items.append(
                ScanItem(
                    category=Category.MCP_TOOLS,
                    name=f"{tool.server}:{tool.name}",
                    source=spec.source,
                    tokens=tc.tokens + mcp_mod.PER_TOOL_FRAMING_TOKENS,
                    token_label=tc.label,
                    detail=tool.description[:80],
                )
            )


def _add_unintrospected(report: ScanReport, spec: mcp_mod.MCPServerSpec) -> None:
    report.unintrospected_servers.append(spec.name)
    report.items.append(
        ScanItem(
            category=Category.MCP_TOOLS,
            name=f"{spec.name} (not introspected)",
            source=spec.source,
            tokens=mcp_mod.ESTIMATED_TOKENS_PER_UNKNOWN_SERVER,
            token_label="estimated",
            detail="config-only estimate; rerun with server launchable for a measured number",
        )
    )


def _scan_instructions(
    report: ScanReport, client: str, project_dir: Path, model: str
) -> None:
    files = instr_mod.DISCOVERERS[client](project_dir)
    for f in files:
        tc = count_text(f.text, model)
        report.items.append(
            ScanItem(
                category=Category.SKILLS if f.kind == "skill" else Category.INSTRUCTIONS,
                name=f.name,
                source=str(f.path),
                tokens=tc.tokens,
                token_label=tc.label,
            )
        )

    dups = dup_mod.find_duplicates(
        [(f.name, f.text) for f in files],
        lambda text: count_text(text, model).tokens,
    )
    for g in dups:
        report.items.append(
            ScanItem(
                category=Category.DUPLICATES,
                name=f"repeated in {len(g.sources)} files",
                source=", ".join(g.sources),
                tokens=g.wasted_tokens,
                token_label="estimated",
                detail=g.snippet,
            )
        )
