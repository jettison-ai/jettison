"""Output verbosity reduction.

Measured on 101 real Claude Code sessions, agent output costs **$163.64
billed directly plus $42.88 re-billed as input** on later turns — because
everything the agent writes stays in the conversation and is re-sent every
turn. Total $206.53, on a $1,420 bill.

Output is also the most expensive token there is: ~50x the cache-read rate.

This is the one lever with **no re-work risk**. Hiding a file makes the
agent re-read it — that is what made our shaping approaches backfire. The
agent's own chattiness is not working memory; making it terse costs it
nothing to recover, so nothing gets re-fetched.

Technique borrowed from Caveman (MIT), which nudges the model toward terse
output via injected instructions. Reimplemented rather than depended on,
and deliberately gentler than "talk like a caveman": the aim is to remove
narration and restatement, not to damage the prose the user actually
reads. Preambles, summaries of work already visible in the diff, and
restating the question are pure cost — the answer is not.
"""

from __future__ import annotations

from pathlib import Path

MARKER_START = "<!-- jettison:verbosity -->"
MARKER_END = "<!-- /jettison:verbosity -->"

# Levels trade brevity against readability. `balanced` is the default
# because the aggressive setting starts eating explanations users want.
LEVELS = {
    # The shipping default. Measured +10.6% cost on a mixed six-task A/B.
    "balanced": """
## Response style

Answer directly. Skip preamble, restating the question, and summarising
work that is already visible in the diff or tool output.

- Lead with the result, then only the reasoning that changes what the
  reader would do next.
- No "I'll now…", "Let me…", "Great question", or closing offers to help
  further.
- Prose over bullets for explanation; bullets only for genuine lists.
- When you have edited files, say what changed and why in one or two
  sentences — do not reproduce the code you just wrote.
- Do not repeat file contents you have already shown.
""",
    # MEASURED HARMFUL — do not make this the default. In a 7-task live
    # A/B it produced *more* output (27,428 -> 36,332 tokens), +64%
    # cache-write and -20.6% on cost, against +10.6% for `balanced` on the
    # same stack. The aggressive framing appears to push the model into
    # re-planning rather than answering. Kept for experimentation only.
    "terse": """
## Response style

Answer in as few words as carry the meaning. No preamble, no summary of
your own actions, no restating the question, no closing pleasantries.

- State the outcome first. Add reasoning only where its absence would
  mislead.
- Never reproduce code you just wrote or file contents already shown.
- Two sentences is a normal answer. A paragraph is a long one.
- Ask a question only when genuinely blocked.
""",
}
DEFAULT_LEVEL = "balanced"


def block(level: str = DEFAULT_LEVEL) -> str:
    body = LEVELS.get(level, LEVELS[DEFAULT_LEVEL])
    return f"{MARKER_START}{body}{MARKER_END}"


def install(
    project: Path | None = None, level: str = DEFAULT_LEVEL, client: str = "claude"
) -> Path:
    """Inject the style block into CLAUDE.md, replacing any previous one.

    Replacing rather than appending keeps the instructions byte-stable
    across re-runs, which matters because they sit in the cached prefix.
    """
    from jettison.optimize.scout import instruction_path

    md = instruction_path(project, client)
    text = md.read_text() if md.exists() else ""
    if MARKER_START in text:
        head, _, rest = text.partition(MARKER_START)
        _, _, tail = rest.partition(MARKER_END)
        text = head + tail
    md.write_text((text.rstrip("\n") + "\n\n" + block(level) + "\n").lstrip("\n"))
    return md


def uninstall(project: Path | None = None, client: str = "claude") -> bool:
    from jettison.optimize.scout import instruction_path

    md = instruction_path(project, client)
    if not md.exists():
        return False
    text = md.read_text()
    if MARKER_START not in text:
        return False
    head, _, rest = text.partition(MARKER_START)
    _, _, tail = rest.partition(MARKER_END)
    md.write_text((head.rstrip("\n") + "\n" + tail.lstrip("\n")).strip() + "\n")
    return True
