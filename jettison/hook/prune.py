"""Query-aware pruning of file-read output.

Why a hook and not the proxy: a proxy edits the request *after* the client
has built and cached it, so the client keeps replaying originals and every
edit forces a re-cache at 12.5x the read rate. Four proxy configurations
measured -36% to -196% (docs/FINDINGS.md Part 2). A `PostToolUse` hook
rewrites the tool output *before* it enters the transcript, so the client
stores and caches the pruned version and there is nothing to mismatch.

The pruning idea is SWE-Pruner's (MIT, ByteDance, arXiv:2601.16746):
state what you are looking for, keep the lines that serve it, drop the
rest. Their skimmer is a trained model; this is a deterministic
approximation that needs no inference, no GPU and no network — the seam
for swapping in their model is `score_lines`.

Two properties make this safe where size-based shaping was not:

* **Line numbers survive.** Claude Code renders reads as `   12→code`.
  Elided regions become an explicit `… N lines elided …` marker, so the
  agent can see exactly what is missing and re-read that range. It is
  never silently short-changed, which is what caused re-reads before.
* **Structure is always kept.** Imports, class and function signatures,
  decorators and docstring openers are never dropped, so the file's shape
  stays legible even when bodies go.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

# Claude Code read format: optional spaces, line number, arrow, content.
LINE_RE = re.compile(r"^(\s*)(\d+)(→|\t|\|)(.*)$")

# Lines that define the shape of a file. Never dropped.
STRUCTURAL = re.compile(
    r"^\s*(from\s+\S+\s+import|import\s+\S+|"
    r"(async\s+)?def\s+\w+|class\s+\w+|@\w+|"
    r"(export\s+)?(async\s+)?function\s+\w+|"
    r"(export\s+)?(const|let|var)\s+\w+\s*=\s*(async\s*)?\(|"
    r"(export\s+)?(interface|type|enum|struct|impl|trait)\s+\w+|"
    r"func\s+\w+|fn\s+\w+|public\s+|private\s+|protected\s+)"
)

# Never prune below this — the marker overhead is not worth it.
MIN_PRUNABLE_LINES = 120
# Always keep this many lines of context either side of a kept line.
HALO = 2
# Stop pruning once we are keeping at least this fraction; below it the
# output is already lean.
TARGET_KEEP_RATIO = 0.45

_WORD = re.compile(r"[A-Za-z_][A-Za-z0-9_]{2,}")

# Lines carrying an instruction the agent must obey are kept unconditionally.
# Vetoing the whole prune when one appears is the wrong lever — in click's
# types.py a single "must" inside a docstring blocked 615 prunable lines.
# Keeping the line satisfies the same requirement and still prunes the rest.
# Deliberately narrow. The verifier's security regex is tuned for
# *instructions* ("never deploy without approval") and matches ordinary
# docstring prose — "must be", "never" — on almost every page of real
# source. Applied to code it either vetoed every prune or kept the whole
# file. What actually must not vanish from a file read is a literal
# secret, so that is all this matches.
MUST_KEEP = re.compile(
    r"(secret|credential|password|passwd|api[_-]?key|access[_-]?token|"
    r"private[_-]?key|BEGIN [A-Z ]*PRIVATE KEY)",
    re.I,
)


@dataclass
class PruneResult:
    text: str
    lines_before: int
    lines_after: int
    pruned: bool
    reason: str = ""

    @property
    def lines_removed(self) -> int:
        return max(0, self.lines_before - self.lines_after)


def query_terms(query: str) -> set[str]:
    """Identifiers worth matching on, lowercased.

    Short and generic words are dropped: matching on 'the' or 'get' keeps
    everything and prunes nothing.
    """
    stop = {
        "the", "and", "for", "with", "this", "that", "from", "into", "then",
        "please", "file", "code", "line", "lines", "function", "class", "add",
        "make", "use", "using", "what", "where", "which", "does", "how",
    }
    return {w.lower() for w in _WORD.findall(query or "") if w.lower() not in stop}


def score_lines(lines: list[str], terms: set[str]) -> list[bool]:
    """Decide which lines to keep. Seam for a learned skimmer.

    Deterministic by design: the same output and query always prune to the
    same bytes, so a re-read of the same file does not produce a different
    transcript.
    """
    keep = [False] * len(lines)
    for i, raw in enumerate(lines):
        m = LINE_RE.match(raw)
        content = m.group(4) if m else raw
        stripped = content.strip()
        if not stripped:
            continue
        if STRUCTURAL.search(content) or MUST_KEEP.search(content):
            keep[i] = True
            continue
        if terms:
            low = content.lower()
            if any(t in low for t in terms):
                keep[i] = True
    return keep


def _halo(keep: list[bool], radius: int = HALO) -> list[bool]:
    out = list(keep)
    for i, k in enumerate(keep):
        if not k:
            continue
        for j in range(max(0, i - radius), min(len(keep), i + radius + 1)):
            out[j] = True
    return out


def prune_read_output(text: str, query: str = "", min_lines: int = MIN_PRUNABLE_LINES) -> PruneResult:
    lines = text.splitlines()
    n = len(lines)
    if n < min_lines:
        return PruneResult(text, n, n, False, f"under {min_lines}-line floor")

    terms = query_terms(query)
    keep = _halo(score_lines(lines, terms))

    kept = sum(keep)
    if kept >= n * TARGET_KEEP_RATIO:
        return PruneResult(text, n, n, False, "already dense; pruning would not pay")
    if kept == 0:
        return PruneResult(text, n, n, False, "nothing scored as relevant; keeping all")

    out: list[str] = []
    run = 0
    for i, raw in enumerate(lines):
        if keep[i]:
            if run:
                out.append(_gap(run, lines, i))
                run = 0
            out.append(raw)
        else:
            run += 1
    if run:
        out.append(_gap(run, lines, len(lines)))

    pruned_text = "\n".join(out)
    return PruneResult(pruned_text, n, len(out), True, f"kept {kept}/{n} lines")


def _gap(count: int, lines: list[str], end_index: int) -> str:
    """Marker naming the exact line range removed, so it can be re-read."""
    start_idx = end_index - count
    first = _line_no(lines[start_idx]) if start_idx < len(lines) else None
    last = _line_no(lines[end_index - 1]) if end_index - 1 < len(lines) else None
    if first and last:
        return f"… {count} lines elided (lines {first}–{last}) — re-read this range if you need them …"
    return f"… {count} lines elided …"


def _line_no(raw: str) -> str | None:
    m = LINE_RE.match(raw)
    return m.group(2) if m else None
