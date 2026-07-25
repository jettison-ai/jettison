"""Instruction-file and skill discovery per client.

Finds every prose artifact that rides along in the standing context:
project instruction files (CLAUDE.md / AGENTS.md / rules), user-level
instruction files, and skill definitions. Read-only.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path


@dataclass
class InstructionFile:
    kind: str  # "instructions" | "skill"
    name: str
    path: Path
    text: str


def _read(path: Path) -> str:
    try:
        return path.read_text(errors="replace")
    except OSError:
        return ""


def _collect(paths: list[tuple[str, str, Path]]) -> list[InstructionFile]:
    out = []
    for kind, name, p in paths:
        if p.is_file():
            text = _read(p)
            if text.strip():
                out.append(InstructionFile(kind=kind, name=name, path=p, text=text))
    return out


def _skills_from_dir(skills_dir: Path, label: str) -> list[tuple[str, str, Path]]:
    """Skill layout: <skills_dir>/<name>/SKILL.md (Claude Code & OpenClaw)."""
    found = []
    if skills_dir.is_dir():
        for child in sorted(skills_dir.iterdir()):
            skill_md = child / "SKILL.md"
            if skill_md.is_file():
                found.append(("skill", f"{label}:{child.name}", skill_md))
    return found


def discover_claude(project_dir: Path) -> list[InstructionFile]:
    paths: list[tuple[str, str, Path]] = [
        ("instructions", "CLAUDE.md (project)", project_dir / "CLAUDE.md"),
        ("instructions", "CLAUDE.local.md", project_dir / "CLAUDE.local.md"),
        ("instructions", ".claude/CLAUDE.md", project_dir / ".claude" / "CLAUDE.md"),
        ("instructions", "CLAUDE.md (user)", Path.home() / ".claude" / "CLAUDE.md"),
        # AGENTS.md is the cross-tool convention and Claude Code loads it too.
        # Real repos lean on it hard — openmc-dev/openmc's CLAUDE.md is a
        # 3-line pointer at a 17KB AGENTS.md — so omitting it under-reports
        # the bill by more than the file it replaces.
        ("instructions", "AGENTS.md (project)", project_dir / "AGENTS.md"),
    ]
    paths += _skills_from_dir(project_dir / ".claude" / "skills", "project")
    paths += _skills_from_dir(Path.home() / ".claude" / "skills", "user")
    return _collect(paths)


def discover_codex(project_dir: Path) -> list[InstructionFile]:
    import os

    codex_home = Path(os.environ.get("CODEX_HOME", Path.home() / ".codex"))
    return _collect(
        [
            ("instructions", "AGENTS.md (project)", project_dir / "AGENTS.md"),
            ("instructions", "AGENTS.md (user)", codex_home / "AGENTS.md"),
        ]
    )


def discover_cursor(project_dir: Path) -> list[InstructionFile]:
    paths: list[tuple[str, str, Path]] = [
        ("instructions", ".cursorrules", project_dir / ".cursorrules"),
        ("instructions", "AGENTS.md (project)", project_dir / "AGENTS.md"),
    ]
    rules_dir = project_dir / ".cursor" / "rules"
    if rules_dir.is_dir():
        for f in sorted(rules_dir.glob("*.mdc")):
            paths.append(("instructions", f".cursor/rules/{f.name}", f))
        for f in sorted(rules_dir.glob("*.md")):
            paths.append(("instructions", f".cursor/rules/{f.name}", f))
    return _collect(paths)


def discover_cline(project_dir: Path) -> list[InstructionFile]:
    paths: list[tuple[str, str, Path]] = [
        ("instructions", ".clinerules", project_dir / ".clinerules"),
    ]
    rules_dir = project_dir / ".clinerules"
    if rules_dir.is_dir():
        paths = [
            ("instructions", f".clinerules/{f.name}", f) for f in sorted(rules_dir.glob("*.md"))
        ]
    return _collect(paths)


def discover_opencode(project_dir: Path) -> list[InstructionFile]:
    return _collect(
        [
            ("instructions", "AGENTS.md (project)", project_dir / "AGENTS.md"),
            ("instructions", "AGENTS.md (user)", Path.home() / ".config" / "opencode" / "AGENTS.md"),
        ]
    )


def discover_openclaw(project_dir: Path) -> list[InstructionFile]:
    ws = Path.home() / ".openclaw" / "workspace"
    paths: list[tuple[str, str, Path]] = []
    for name in ("AGENTS.md", "SOUL.md", "IDENTITY.md", "USER.md", "TOOLS.md", "MEMORY.md", "HEARTBEAT.md"):
        paths.append(("instructions", f"workspace/{name}", ws / name))
    paths += _skills_from_dir(ws / "skills", "workspace")
    paths += _skills_from_dir(Path.home() / ".openclaw" / "skills", "user")
    return _collect(paths)


DISCOVERERS = {
    "claude": discover_claude,
    "codex": discover_codex,
    "cursor": discover_cursor,
    "cline": discover_cline,
    "opencode": discover_opencode,
    "openclaw": discover_openclaw,
}
