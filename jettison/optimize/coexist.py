"""Detecting other optimizers, and staying out of their way.

Headroom and Caveman have real users. Asking those users to switch is both
rude and wrong — the three tools address different layers and compose
cleanly:

    Headroom   runtime compression of tool outputs (proxy)
    Caveman    response verbosity (instruction injection)
    Jettison   repository structure, read pruning, measurement

The only genuine conflict is the response-style block: if Caveman has
already installed one, a second set of style instructions is at best
redundant and at worst contradictory, and contradictory instructions cost
tokens while degrading output. So we detect it and skip ours.

Nothing here disables another tool or edits its configuration.
"""

from __future__ import annotations

import json
import os
import shutil
from dataclasses import dataclass
from pathlib import Path


@dataclass
class Detected:
    headroom: bool = False
    caveman: bool = False
    swe_pruner: bool = False

    @property
    def any(self) -> bool:
        return self.headroom or self.caveman or self.swe_pruner


def _claude_settings(project: Path | None = None) -> list[Path]:
    home = Path(os.environ.get("CLAUDE_CONFIG_DIR", Path.home() / ".claude"))
    paths = [home / "settings.json"]
    if project:
        paths += [project / ".claude" / "settings.json", project / ".claude" / "settings.local.json"]
    return [p for p in paths if p.exists()]


def detect(project: Path | None = None) -> Detected:
    found = Detected()
    root = project or Path.cwd()

    if shutil.which("headroom"):
        found.headroom = True
    try:
        import headroom  # noqa: F401

        found.headroom = True
    except Exception:
        pass
    try:
        import swe_pruner  # noqa: F401

        found.swe_pruner = True
    except Exception:
        pass

    # Caveman registers hooks and leaves an activity marker.
    home = Path(os.environ.get("CLAUDE_CONFIG_DIR", Path.home() / ".claude"))
    if (home / ".caveman-active").exists():
        found.caveman = True
    for path in _claude_settings(root):
        try:
            if "caveman" in json.dumps(json.loads(path.read_text())).lower():
                found.caveman = True
        except Exception:
            continue
    for name in ("CLAUDE.md", "AGENTS.md"):
        f = root / name
        if f.exists():
            try:
                if "caveman" in f.read_text().lower():
                    found.caveman = True
            except OSError:
                pass
    return found


def notes(found: Detected) -> list[str]:
    """Human-readable notes on how Jettison composes with what is present."""
    out: list[str] = []
    if found.headroom:
        out.append(
            "Headroom detected — it compresses tool outputs at the proxy. "
            "Jettison adds the layer it does not have: repository structure. "
            "They compose; nothing is disabled."
        )
    if found.caveman:
        out.append(
            "Caveman detected — it already governs response style, so "
            "Jettison is skipping its own style block. Two sets of style "
            "instructions cost tokens and can contradict each other."
        )
    if found.swe_pruner:
        out.append(
            "swe-pruner detected — its trained skimmer can replace Jettison's "
            "deterministic line scorer where a GPU is available."
        )
    return out


def should_skip_verbosity(project: Path | None = None) -> bool:
    return detect(project).caveman
