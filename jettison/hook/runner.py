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

from jettison.hook.prune import prune_read_output
from jettison.verifier.commitments import extract_text_commitments

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
    """Refuse to prune away a path, number, identifier or rule.

    The same gate the proxy used. Tool output is where exact values live,
    and a silently dropped one changes answers.
    """
    for c in extract_text_commitments(original, source="tool_result"):
        if c.span not in pruned:
            return False
    return True


def handle(event: dict[str, Any]) -> dict[str, Any] | None:
    if event.get("tool_name") not in PRUNABLE_TOOLS:
        return None
    output = event.get("tool_output")
    if not isinstance(output, str) or not output.strip():
        return None

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
