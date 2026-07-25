"""Repo map: give the agent the structure up front so it never explores.

Why this and not the scout. Scout delegates exploration to a cheap model,
which costs a round-trip every time it fires — measured at −34% on feature
work, where there is little to explore and the delegation is pure
overhead. A repo map costs **zero turns**: it is generated once, injected
into the instructions the client already sends, and therefore rides in the
cached prefix. The agent starts already knowing where things live.

That is the part of RepoMaster (MIT) that actually produces its 95%: a
pre-built structural index the agent navigates instead of reading files.
Their implementation adds a dependency graph with centrality and git-history
ranking across ~6.5k lines; this is the small deterministic core of the
same idea — every module, its classes and its function signatures, ranked
by a cheap importance proxy and truncated to a token budget.

Deterministic by construction: files are walked in sorted order and the
ranking is a pure function of the tree, so the same repo always produces
byte-identical output. That matters because this text lands in the cached
prefix.
"""

from __future__ import annotations

import ast
from dataclasses import dataclass, field
from pathlib import Path

from jettison.optimize.importance import (
    Signals,
    ceilings_for,
    complexity_score,
    git_commit_counts,
    score,
    semantic_score,
)

SKIP_DIRS = {
    ".git", ".venv", "venv", "node_modules", "__pycache__", "dist", "build",
    ".mypy_cache", ".pytest_cache", ".ruff_cache", "site-packages", ".tox",
}
# Budget for the whole map. It sits in every request, so it must stay small
# relative to what it saves — a few thousand tokens against the tens of
# thousands an exploration phase burns.
DEFAULT_MAX_TOKENS = 3_000
CHARS_PER_TOKEN = 4


@dataclass
class Symbol:
    kind: str          # "class" | "def"
    name: str
    signature: str
    lineno: int
    doc: str = ""


@dataclass
class Module:
    path: str
    symbols: list[Symbol] = field(default_factory=list)
    lines: int = 0
    imported_by: int = 0
    complexity: int = 0
    commits: int = 0
    rank: float = 0.0

    def signals(self) -> Signals:
        return Signals(
            imports=self.imported_by,
            usage=len(self.symbols),
            complexity=self.complexity,
            commits=self.commits,
            semantic=semantic_score(self.path),
        )


def _signature(node: ast.AST) -> str:
    if isinstance(node, ast.ClassDef):
        bases = ", ".join(ast.unparse(b) for b in node.bases) if node.bases else ""
        return f"class {node.name}({bases})" if bases else f"class {node.name}"
    if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
        try:
            args = ast.unparse(node.args)
        except Exception:
            args = "..."
        prefix = "async def" if isinstance(node, ast.AsyncFunctionDef) else "def"
        ret = f" -> {ast.unparse(node.returns)}" if node.returns else ""
        return f"{prefix} {node.name}({args}){ret}"
    return ""


def parse_module(path: Path, root: Path) -> Module | None:
    try:
        source = path.read_text(errors="replace")
        tree = ast.parse(source)
    except (OSError, SyntaxError, ValueError):
        return None
    mod = Module(
        path=str(path.relative_to(root)),
        lines=source.count("\n") + 1,
        complexity=complexity_score(tree),
    )
    for node in tree.body:
        if isinstance(node, (ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)):
            doc = (ast.get_docstring(node) or "").strip().split("\n")[0][:80]
            kind = "class" if isinstance(node, ast.ClassDef) else "def"
            mod.symbols.append(Symbol(kind, node.name, _signature(node), node.lineno, doc))
            if isinstance(node, ast.ClassDef):
                for sub in node.body:
                    if isinstance(sub, (ast.FunctionDef, ast.AsyncFunctionDef)) and not sub.name.startswith("_"):
                        mod.symbols.append(
                            Symbol("method", f"{node.name}.{sub.name}", "  " + _signature(sub), sub.lineno)
                        )
    return mod


def scan(root: Path) -> list[Module]:
    modules: list[Module] = []
    names: dict[str, Module] = {}
    for path in sorted(root.rglob("*.py")):
        if any(part in SKIP_DIRS for part in path.parts):
            continue
        mod = parse_module(path, root)
        if mod and mod.symbols:
            modules.append(mod)
            names[path.stem] = mod

    # Count inbound imports as the importance proxy.
    for path in sorted(root.rglob("*.py")):
        if any(part in SKIP_DIRS for part in path.parts):
            continue
        try:
            tree = ast.parse(path.read_text(errors="replace"))
        except (OSError, SyntaxError, ValueError):
            continue
        for node in ast.walk(tree):
            target = None
            if isinstance(node, ast.ImportFrom) and node.module:
                target = node.module.split(".")[-1]
            elif isinstance(node, ast.Import):
                target = node.names[0].name.split(".")[-1] if node.names else None
            if target and target in names:
                names[target].imported_by += 1

    # Git churn, then the weighted rank. Done after the full walk because
    # every signal is normalized against this repo's own maximum.
    commits = git_commit_counts(root)
    for mod in modules:
        mod.commits = commits.get(mod.path, 0)
    ceilings = ceilings_for([m.signals() for m in modules])
    for mod in modules:
        mod.rank = score(mod.signals(), ceilings)
    return modules


def render(modules: list[Module], max_tokens: int = DEFAULT_MAX_TOKENS) -> str:
    budget = max_tokens * CHARS_PER_TOKEN
    ranked = sorted(modules, key=lambda m: (-m.rank, m.path))
    out = [
        "Structure of this repository, so you do not need to explore it.",
        "Line numbers are exact — read a specific range instead of a whole file.",
        "",
    ]
    used = sum(len(x) for x in out)
    for mod in ranked:
        block = [f"{mod.path}  ({mod.lines} lines)"]
        for s in mod.symbols:
            block.append(f"  {s.lineno:>5}  {s.signature}" + (f"  # {s.doc}" if s.doc else ""))
        text = "\n".join(block)
        if used + len(text) > budget:
            remaining = len(ranked) - ranked.index(mod)
            out.append(f"\n… {remaining} lower-ranked modules omitted; grep for anything not listed …")
            break
        out.append(text)
        used += len(text)
    return "\n".join(out)


def build(root: Path | None = None, max_tokens: int = DEFAULT_MAX_TOKENS) -> str:
    return render(scan(root or Path.cwd()), max_tokens)
