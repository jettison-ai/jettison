"""Register the pruning hook in Claude Code's settings.

`PostToolUse` with `hookSpecificOutput.updatedToolOutput` replaces what
enters the transcript, so the client stores and caches the pruned version
and re-sends *that* on every later turn. This is the property our live A/B
showed a proxy cannot have: a proxy edits the request after the client has
cached it, so the client keeps replaying originals and every edit costs a
re-cache at 12.5x the read rate.

Edits are marker-scoped: only entries whose command mentions
`jettison.hook` are added or removed, so an uninstall never disturbs hooks
someone else installed.
"""

from __future__ import annotations

import json
import os
import shutil
import sys
from pathlib import Path
from typing import Any

HOOK_MARKER = "jettison.hook"
PRUNE_MATCHER = "Read"


def settings_path(project: Path | None = None, global_scope: bool = False) -> Path:
    if global_scope:
        base = Path(os.environ.get("CLAUDE_CONFIG_DIR", Path.home() / ".claude"))
        return base / "settings.json"
    return (project or Path.cwd()) / ".claude" / "settings.local.json"


def hook_command() -> str:
    """Prefer the installed console script; fall back to the interpreter.

    A bare `jettison` may not be on PATH inside the agent's environment, so
    the interpreter form is quoted and absolute.
    """
    exe = shutil.which("jettison-hook")
    if exe:
        return f'"{exe}"'
    return f'"{sys.executable}" -m {HOOK_MARKER}.runner'


def _load(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    try:
        data = json.loads(path.read_text())
        return data if isinstance(data, dict) else {}
    except json.JSONDecodeError as e:
        raise RuntimeError(f"{path} is not valid JSON; refusing to overwrite it ({e})") from e


def install_hook(project: Path | None = None, global_scope: bool = False) -> Path:
    path = settings_path(project, global_scope)
    path.parent.mkdir(parents=True, exist_ok=True)
    settings = _load(path)

    hooks = settings.setdefault("hooks", {})
    entries = hooks.setdefault("PostToolUse", [])
    entries = [e for e in entries if HOOK_MARKER not in json.dumps(e)]
    entries.append(
        {
            "matcher": PRUNE_MATCHER,
            "hooks": [{"type": "command", "command": hook_command(), "timeout": 20}],
        }
    )
    hooks["PostToolUse"] = entries
    path.write_text(json.dumps(settings, indent=2) + "\n")
    return path


def uninstall_hook(project: Path | None = None, global_scope: bool = False) -> bool:
    path = settings_path(project, global_scope)
    if not path.exists():
        return False
    settings = _load(path)
    entries = (settings.get("hooks") or {}).get("PostToolUse")
    if not isinstance(entries, list):
        return False
    kept = [e for e in entries if HOOK_MARKER not in json.dumps(e)]
    if len(kept) == len(entries):
        return False
    settings["hooks"]["PostToolUse"] = kept
    if not kept:
        settings["hooks"].pop("PostToolUse")
    if not settings.get("hooks"):
        settings.pop("hooks", None)
    path.write_text(json.dumps(settings, indent=2) + "\n")
    return True


def is_installed(project: Path | None = None, global_scope: bool = False) -> bool:
    path = settings_path(project, global_scope)
    if not path.exists():
        return False
    return HOOK_MARKER in path.read_text()
