"""Scout: repository navigation on a cheap model.

The dominant cost driver in coding agents is repository-context selection
— agents read whole files with the *same* expensive model that solves the
task, and those reads become the largest slice of the token budget
(Elicit, "Optimizing Coding Agents for Efficiency", 80 papers).

Dedicated navigation architectures fix it decisively: RepoMaster reports
95% token reduction with task-pass rate rising 40.7% -> 62.9%, FastContext
60% reduction at +5.5pp resolution, Hierarchical Context Pruning 50K -> 8K
tokens with accuracy improving. The gains are not merely neutral on
quality; the reviews attribute the improvement to attention dilution —
irrelevant context competes with task-relevant signal.

This ships that pattern as a Claude Code subagent: exploration runs on
Haiku, and the main model receives paths and the specific lines that
matter instead of whole files. It is client-side, so the transcript itself
gets smaller and the client caches the smaller version — the property our
own A/B proved a proxy cannot achieve (docs/FINDINGS.md Part 2).
"""

from __future__ import annotations

import os
from pathlib import Path

AGENT_NAME = "jettison-scout"

# The description is load-bearing: it is what the main model reads when
# deciding whether to delegate, so it has to make delegation the obvious
# choice for exploration while making clear it is NOT for edits.
AGENT_MD = """---
name: jettison-scout
description: >-
  Explores the repository to locate code, on a cheap model. Use this
  INSTEAD of reading files yourself whenever you need to find where
  something lives, understand how a feature works, or gather context
  before editing — e.g. "where is auth handled", "which files touch the
  retry logic", "how does X flow through the codebase". Returns exact file
  paths with line numbers and only the relevant excerpts, never whole
  files. Do not use it to make edits; it is read-only.
tools: Read, Grep, Glob, Bash
model: haiku
---

You are a repository scout. Your job is to find the small set of lines
that answer the question, and return nothing else.

The model that asked you is expensive and its context is the scarce
resource. Every line you return is re-sent on every later turn of its
session, so returning a whole file costs far more than the read you saved.

Method:

1. Locate candidates with Grep and Glob before opening anything. Prefer a
   targeted pattern over reading a file to find out what is in it.
2. Read only the regions you need. Use offset and limit; do not read whole
   files unless the file is genuinely small.
3. Stop as soon as the question is answered. Breadth is not thoroughness.

Return exactly this shape, and nothing else — no preamble, no summary of
what you did, no offers to continue:

## Findings
- `path/to/file.py:120-148` — one line on why this region matters
- `path/to/other.ts:12` — one line

## Relevant code
```python
# path/to/file.py:120-148
<only the lines that matter>
```

## Answer
Two or three sentences maximum, directly answering the question.

Hard limits:
- Never return more than ~200 lines of code in total. If the answer needs
  more than that, return the paths and line ranges and say which regions
  the caller should read itself.
- Never paste a file you did not need to open.
- If you cannot find it, say so in one line and list where you looked.
  A short honest miss is cheaper than a long speculative answer.
"""

DELEGATION_RULE = """
## Context efficiency

Before reading files to explore or orient yourself, delegate to the
`jettison-scout` subagent. It runs on a cheaper model and returns only the
relevant lines, which keeps this conversation small — and everything in
this conversation is re-sent on every later turn.

Read files directly only when you already know the exact file and region
you need, or when you are about to edit them.
"""

MARKER_START = "<!-- jettison:scout -->"
MARKER_END = "<!-- /jettison:scout -->"


def claude_dir(project: Path | None = None, global_scope: bool = False) -> Path:
    if global_scope:
        return Path(os.environ.get("CLAUDE_CONFIG_DIR", Path.home() / ".claude"))
    return (project or Path.cwd()) / ".claude"


def agent_path(project: Path | None = None, global_scope: bool = False) -> Path:
    return claude_dir(project, global_scope) / "agents" / f"{AGENT_NAME}.md"


def install_scout(project: Path | None = None, global_scope: bool = False) -> Path:
    path = agent_path(project, global_scope)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(AGENT_MD)
    return path


def uninstall_scout(project: Path | None = None, global_scope: bool = False) -> bool:
    path = agent_path(project, global_scope)
    if path.exists():
        path.unlink()
        return True
    return False


def add_delegation_rule(project: Path | None = None) -> Path:
    """Add the delegation instruction to CLAUDE.md, fenced so it is removable.

    Without this the subagent exists but is rarely chosen: the main model
    has no reason to prefer delegation over the Read tool it already has.
    """
    md = (project or Path.cwd()) / "CLAUDE.md"
    existing = md.read_text() if md.exists() else ""
    if MARKER_START in existing:
        return md
    block = f"\n{MARKER_START}{DELEGATION_RULE}{MARKER_END}\n"
    md.write_text(existing + block)
    return md


def remove_delegation_rule(project: Path | None = None) -> bool:
    md = (project or Path.cwd()) / "CLAUDE.md"
    if not md.exists():
        return False
    text = md.read_text()
    if MARKER_START not in text:
        return False
    head, _, rest = text.partition(MARKER_START)
    _, _, tail = rest.partition(MARKER_END)
    md.write_text((head.rstrip("\n") + "\n" + tail.lstrip("\n")).strip() + "\n")
    return True
