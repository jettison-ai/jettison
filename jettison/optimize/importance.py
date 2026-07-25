"""Ranking which parts of a repository matter.

A repo map has to fit in a few thousand tokens, so the ordering decides
what the agent knows about. Naive size or alphabetical ordering wastes the
budget on generated files and test fixtures.

The scoring model follows RepoMaster's (MIT) importance analysis — same
signals, same relative weights — reimplemented here rather than taken as a
dependency, so Jettison keeps a stdlib-only footprint:

    git_history  4.0   what the team actually changes
    imports      3.0   how many modules depend on this one
    usage        2.0   how often its symbols are referenced
    complexity   1.0   branching density
    semantic     0.5   name signals (core, main, api, cli …)

Git history carries the most weight, which is the interesting part of
their design: recency and churn predict what an agent will need better
than structure alone. A file nobody has touched in two years is rarely the
one you are working on.

Everything degrades gracefully — a repo with no git history simply scores
0 on that axis rather than failing.
"""

from __future__ import annotations

import ast
import subprocess
from dataclasses import dataclass
from pathlib import Path

WEIGHTS = {
    "git_history": 4.0,
    "imports": 3.0,
    "usage": 2.0,
    "complexity": 1.0,
    "semantic": 0.5,
}
MAX_SCORE = 10.0

# Names that signal a module is central to how the project works.
_SEMANTIC_HINTS = (
    "core", "main", "api", "app", "cli", "server", "client", "model",
    "handler", "router", "service", "engine", "manager", "config",
)
# Names that signal the opposite. Scored down so they do not crowd out
# real code in a limited budget.
_SEMANTIC_PENALTIES = ("test", "conftest", "fixture", "mock", "example", "sample", "migration")

_BRANCH_NODES = (ast.If, ast.For, ast.While, ast.Try, ast.With, ast.ExceptHandler, ast.BoolOp)


@dataclass
class Signals:
    imports: int = 0
    usage: int = 0
    complexity: int = 0
    commits: int = 0
    semantic: float = 0.0


def semantic_score(path: str) -> float:
    low = path.lower()
    if any(p in low for p in _SEMANTIC_PENALTIES):
        return -1.0
    return 1.0 if any(h in low for h in _SEMANTIC_HINTS) else 0.0


def complexity_score(tree: ast.AST) -> int:
    """Branch count as a cheap proxy for cyclomatic complexity."""
    return sum(1 for node in ast.walk(tree) if isinstance(node, _BRANCH_NODES))


def git_commit_counts(root: Path, since: str = "6.months") -> dict[str, int]:
    """Commits per file in the recent past.

    Recency is the point: `--since` keeps this measuring what the team is
    working on now rather than what was churned years ago. Returns empty on
    any failure, so non-git directories and missing git both degrade to a
    zero contribution instead of an error.
    """
    try:
        out = subprocess.run(
            ["git", "log", f"--since={since}", "--name-only", "--pretty=format:"],
            cwd=root, capture_output=True, text=True, timeout=20, check=False,
        )
    except (OSError, subprocess.SubprocessError):
        return {}
    if out.returncode != 0:
        return {}
    counts: dict[str, int] = {}
    for line in out.stdout.splitlines():
        line = line.strip()
        if line:
            counts[line] = counts.get(line, 0) + 1
    return counts


def _norm(value: float, ceiling: float) -> float:
    return min(value / ceiling, 1.0) if ceiling > 0 else 0.0


def score(signals: Signals, ceilings: dict[str, float]) -> float:
    """Weighted sum, each signal normalized against the repo's own maximum.

    Normalizing per-repo rather than against absolutes keeps the ranking
    meaningful in both a 20-file project and a 2,000-file one.
    """
    total = (
        _norm(signals.commits, ceilings.get("commits", 1)) * WEIGHTS["git_history"]
        + _norm(signals.imports, ceilings.get("imports", 1)) * WEIGHTS["imports"]
        + _norm(signals.usage, ceilings.get("usage", 1)) * WEIGHTS["usage"]
        + _norm(signals.complexity, ceilings.get("complexity", 1)) * WEIGHTS["complexity"]
        + signals.semantic * WEIGHTS["semantic"]
    )
    return max(0.0, min(total, MAX_SCORE))


def ceilings_for(all_signals: list[Signals]) -> dict[str, float]:
    if not all_signals:
        return {}
    return {
        "commits": max((s.commits for s in all_signals), default=1) or 1,
        "imports": max((s.imports for s in all_signals), default=1) or 1,
        "usage": max((s.usage for s in all_signals), default=1) or 1,
        "complexity": max((s.complexity for s in all_signals), default=1) or 1,
    }
