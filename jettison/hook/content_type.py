"""Deciding what a tool output actually is, before compressing it.

This is a correctness boundary, not a nicety. Headroom's Kompress is a
prose compressor: fed source code it strips keywords, turning

    from __future__ import annotations

into

    __future__ annotations

which is no longer Python. It reports a 43% "saving" while corrupting
what the agent reads. Headroom itself never makes this mistake — its
ContentRouter dispatches JSON to SmartCrusher, code to CodeCompressor and
only prose to Kompress. We need the same discipline.

The classifier is deliberately biased toward CODE. A false "code" verdict
costs a little compression; a false "prose" verdict corrupts a file the
agent is about to edit. When the signals are ambiguous, it says code.
"""

from __future__ import annotations

import json
import re

CODE_MARKERS = (
    re.compile(r"^\s*(from\s+\S+\s+import|import\s+\w)", re.M),
    re.compile(r"^\s*(async\s+)?def\s+\w+\s*\(", re.M),
    re.compile(r"^\s*class\s+\w+", re.M),
    re.compile(r"^\s*(export\s+)?(async\s+)?function\s+\w+", re.M),
    re.compile(r"^\s*(public|private|protected|static)\s+\w+", re.M),
    re.compile(r"^\s*(func|fn)\s+\w+\s*\(", re.M),
    re.compile(r"^\s*(#include|package\s+\w+|use\s+\w+::)", re.M),
    re.compile(r"[;{}]\s*$", re.M),
)
# Claude Code renders file reads with line-number prefixes. Their presence
# is near-conclusive evidence we are looking at a file, not a log.
NUMBERED_LINE = re.compile(r"^\s*\d+[→\t|]", re.M)


def looks_like_json(text: str) -> bool:
    stripped = text.strip()
    if not stripped or stripped[0] not in "[{":
        return False
    try:
        json.loads(stripped)
        return True
    except (json.JSONDecodeError, ValueError):
        return False


def classify(text: str, tool_name: str = "") -> str:
    """Return "code", "json" or "prose".

    `tool_name` is trusted when it is decisive: a Read result is a file,
    full stop, regardless of what its contents happen to look like.
    """
    if tool_name in {"Read", "read_file", "view", "Edit", "Write"}:
        return "code"
    if not text.strip():
        return "prose"
    if looks_like_json(text):
        return "json"
    if NUMBERED_LINE.search(text):
        return "code"

    hits = sum(1 for pattern in CODE_MARKERS if pattern.search(text))
    if hits >= 2:
        return "code"
    # A single strong structural marker in a short output is still code —
    # a stack trace or a snippet echoed by a build tool.
    if hits == 1 and len(text) < 4000:
        return "code"
    return "prose"


def is_safe_for_prose_compression(text: str, tool_name: str = "") -> bool:
    """Only genuine prose may go to a prose compressor."""
    return classify(text, tool_name) == "prose"
