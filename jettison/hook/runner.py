"""PostToolUse hook entry point.

Contract (Claude Code): read the event JSON on stdin, print
``{"hookSpecificOutput": {"hookEventName": "PostToolUse",
"updatedToolOutput": ...}}`` and exit 0. The printed output is what enters
the transcript, so this is where a saving becomes permanent — the client
caches the pruned version and re-sends that on every later turn.

Fails open, always. Any error, any surprise, any missing field prints
nothing and exits 0, which leaves the original output untouched. A hook
that crashes must never cost the user their session.
"""

from __future__ import annotations

import json
import sys
from typing import Any

from jettison.hook.prune import MUST_KEEP, prune_read_output

# Tools whose output is worth pruning. Bash is excluded: its output is
# frequently a command's only result and has no line-number scaffolding to
# make an elision recoverable.
PRUNABLE_TOOLS = {"Read", "read_file", "view"}


def last_user_text(transcript_path: str) -> str:
    """The most recent user message, used as the pruning query.

    This is what makes pruning task-aware rather than generic: the lines
    that survive are the ones serving what the user actually asked for.
    """
    try:
        with open(transcript_path, errors="replace") as f:
            lines = f.readlines()
    except OSError:
        return ""
    for raw in reversed(lines[-400:]):
        try:
            d = json.loads(raw)
        except json.JSONDecodeError:
            continue
        if d.get("type") != "user":
            continue
        content = (d.get("message") or {}).get("content")
        if isinstance(content, str) and content.strip():
            return content[:2000]
        if isinstance(content, list):
            for b in content:
                if isinstance(b, dict) and b.get("type") == "text" and b.get("text", "").strip():
                    return b["text"][:2000]
    return ""


def preserves_commitments(original: str, pruned: str) -> bool:
    """Every line that must never vanish is still present.

    A dropped line of code is recoverable — the marker names its line range
    and the agent can read it again — so the bar here is not "nothing was
    removed" but "nothing irrecoverable was removed". Checking against the
    same MUST_KEEP rule the pruner uses keeps the two self-consistent;
    using the verifier's instruction-tuned regex instead rejected every
    prune, because "must be" appears in ordinary docstrings.
    """
    missing = [ln for ln in original.splitlines() if MUST_KEEP.search(ln)]
    pruned_lines = set(pruned.splitlines())
    return all(ln in pruned_lines for ln in missing)


def read_output(event: dict[str, Any]) -> tuple[str, int]:
    """Pull the file text out of a PostToolUse payload.

    Verified against a live Claude Code hook rather than documentation:
    a Read event arrives as
    ``tool_response.file.{content, startLine, numLines, totalLines}``,
    with the content carrying NO line-number prefixes. Earlier code read a
    flat ``tool_output`` field, found nothing, and silently pruned nothing
    for an entire 101-turn session. Accept every shape and return the
    starting line so numbering can be reconstructed.
    """
    resp = event.get("tool_response")
    if isinstance(resp, dict):
        f = resp.get("file")
        if isinstance(f, dict) and isinstance(f.get("content"), str):
            return f["content"], int(f.get("startLine", 1) or 1)
        if isinstance(resp.get("content"), str):
            return resp["content"], 1
    if isinstance(resp, str):
        return resp, 1
    out = event.get("tool_output")
    return (out, 1) if isinstance(out, str) else ("", 1)


def number_lines(text: str, start: int) -> str:
    """Render as Claude Code displays reads, so elisions cite real numbers."""
    return "\n".join(f"{start + i:6}\u2192{line}" for i, line in enumerate(text.splitlines()))


def handle(event: dict[str, Any]) -> dict[str, Any] | None:
    if event.get("tool_name") not in PRUNABLE_TOOLS:
        return None
    raw, start_line = read_output(event)
    if not raw.strip():
        return None
    output = number_lines(raw, start_line)

    query = last_user_text(str(event.get("transcript_path", "")))
    result = prune_read_output(output, query)
    if not result.pruned:
        return None
    if not preserves_commitments(output, result.text):
        return None

    return {
        "hookSpecificOutput": {
            "hookEventName": "PostToolUse",
            "updatedToolOutput": result.text,
        }
    }


def main() -> int:
    try:
        event = json.loads(sys.stdin.read() or "{}")
        if not isinstance(event, dict):
            return 0
        out = handle(event)
        if out is not None:
            sys.stdout.write(json.dumps(out))
    except Exception:
        # Fail open: original output stands.
        return 0
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
