"""Per-client wrap adapters.

Two shapes, mirroring Headroom's wrap machinery (see NOTICE):
- launch adapters: set env (base URLs) and exec the client binary
- watcher adapters: GUI clients read config from a settings UI; we print
  exact setup lines and keep the proxy in the foreground

Native-feature step-aside (§ CACHE_SAFETY/LIMITATIONS): Claude Code with
a custom ANTHROPIC_BASE_URL stops deferring MCP schemas unless
ENABLE_TOOL_SEARCH=true is set (upstream issue #746) — we always set it,
so Claude Code's native deferred loading keeps working and Jettison only
optimizes what the client actually sends. The per-request
min_tools_to_optimize floor handles the rest.
"""

from __future__ import annotations

import os
import shutil
import subprocess
from dataclasses import dataclass, field


@dataclass
class ClientAdapter:
    name: str
    binary: str | None  # None => watcher-only
    env_vars: dict[str, str] = field(default_factory=dict)  # {VAR: "{proxy_url}"}
    setup_lines: list[str] = field(default_factory=list)
    notes: str = ""

    def available(self) -> bool:
        return self.binary is None or shutil.which(self.binary) is not None

    def build_env(self, proxy_url: str) -> dict[str, str]:
        env = dict(os.environ)
        for var, template in self.env_vars.items():
            env[var] = template.format(proxy_url=proxy_url)
        return env

    def launch(self, proxy_url: str, extra_args: list[str]) -> int:
        assert self.binary is not None
        env = self.build_env(proxy_url)
        return subprocess.call([self.binary, *extra_args], env=env)

    def print_setup(self, proxy_url: str) -> None:
        print(f"\nJettison proxy running for {self.name} at {proxy_url}")
        for line in self.setup_lines:
            print("  " + line.format(proxy_url=proxy_url))
        if self.notes:
            print(f"\n  note: {self.notes}")
        print("\nPress Ctrl+C to stop.\n")


ADAPTERS: dict[str, ClientAdapter] = {
    "claude": ClientAdapter(
        name="claude",
        binary="claude",
        env_vars={
            "ANTHROPIC_BASE_URL": "{proxy_url}",
            # Keep Claude Code's native deferred tool loading alive behind a
            # custom base URL (upstream #746) — we optimize only what's sent.
            "ENABLE_TOOL_SEARCH": "true",
        },
    ),
    "codex": ClientAdapter(
        name="codex",
        binary="codex",
        env_vars={"OPENAI_BASE_URL": "{proxy_url}/v1"},
    ),
    "opencode": ClientAdapter(
        name="opencode",
        binary="opencode",
        env_vars={
            "ANTHROPIC_BASE_URL": "{proxy_url}",
            "OPENAI_BASE_URL": "{proxy_url}/v1",
        },
    ),
    "cursor": ClientAdapter(
        name="cursor",
        binary=None,
        setup_lines=[
            "Cursor Settings -> Models -> override OpenAI Base URL: {proxy_url}/v1",
            "(keep your existing API key)",
        ],
        notes="Cursor is UI-configured; Jettison stays running as a proxy.",
    ),
    "cline": ClientAdapter(
        name="cline",
        binary=None,
        setup_lines=[
            "Cline settings -> API provider -> Anthropic -> Custom base URL: {proxy_url}",
            "or OpenAI-compatible -> Base URL: {proxy_url}/v1",
        ],
        notes="Cline is UI-configured; Jettison stays running as a proxy.",
    ),
    "openclaw": ClientAdapter(
        name="openclaw",
        binary=None,
        setup_lines=[
            'openclaw config set models.anthropic.baseUrl "{proxy_url}"',
            "openclaw gateway restart",
        ],
        notes=(
            "heartbeat profile: Jettison's stable prefix is byte-identical per "
            "request, so OpenClaw's cache-warming heartbeats keep hitting the "
            "provider prefix cache; heartbeat turns carry the compact registry "
            "instead of the full schema catalog."
        ),
    ),
}
