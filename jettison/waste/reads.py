"""Read-waste analysis over local agent transcripts.

The largest line item in a real coding-agent bill is not the tool
catalog — it is file content that was read once, never changed, and then
re-read into the same conversation. Every copy sits in the context window
and is re-billed on every later turn of the session, so one duplicate read
of a 10k-token file in a 40-turn session costs 400k cached input tokens.

This module measures that from transcripts the agent already wrote, so a
user gets their own number without installing anything into the request
path. It reads only local files, reports only sizes and paths, and
transmits nothing.

Kinds of waste detected:

  exact_repeat   same file read again with byte-identical content
  superset       a later read of the same file contains an earlier one
                 (the earlier copy is now dead weight)
  write_readback the agent wrote a file and then read back what it just wrote

Headroom ships an offline read auditor of its own; this is deliberately
independent so the number survives Headroom being absent, and so the same
detector can drive the runtime de-duplicator in jettison.proxy.read_dedup.
"""

from __future__ import annotations

import hashlib
import json
from collections import defaultdict
from dataclasses import dataclass, field
from pathlib import Path

from jettison.tokens import DEFAULT_MODEL, count_text

CLAUDE_ROOT = Path.home() / ".claude" / "projects"
CODEX_ROOT = Path.home() / ".codex" / "sessions"

READ_TOOLS = {"Read", "read_file", "view", "str_replace_editor"}
WRITE_TOOLS = {"Write", "Edit", "create_file", "str_replace"}


@dataclass
class WasteItem:
    kind: str
    path: str
    session: str
    tokens: int
    detail: str = ""


@dataclass
class ReadWasteReport:
    sessions: int = 0
    read_calls: int = 0
    read_tokens: int = 0
    items: list[WasteItem] = field(default_factory=list)
    token_label: str = "estimated"
    # tokens x turns-remaining: what the waste actually costs once you
    # account for it being resent on every later turn of the session.
    resident_token_turns: int = 0

    @property
    def wasted_tokens(self) -> int:
        return sum(i.tokens for i in self.items)

    def by_kind(self) -> dict[str, tuple[int, int]]:
        agg: dict[str, list[int]] = defaultdict(lambda: [0, 0])
        for i in self.items:
            agg[i.kind][0] += 1
            agg[i.kind][1] += i.tokens
        return {k: (v[0], v[1]) for k, v in sorted(agg.items(), key=lambda kv: -kv[1][1])}

    def top_files(self, n: int = 10) -> list[tuple[str, int]]:
        agg: dict[str, int] = defaultdict(int)
        for i in self.items:
            agg[i.path] += i.tokens
        return sorted(agg.items(), key=lambda kv: -kv[1])[:n]

    def to_dict(self) -> dict:
        return {
            "sessions": self.sessions,
            "read_calls": self.read_calls,
            "read_tokens": self.read_tokens,
            "wasted_tokens": self.wasted_tokens,
            "resident_token_turns": self.resident_token_turns,
            "token_label": self.token_label,
            "by_kind": {k: {"count": c, "tokens": t} for k, (c, t) in self.by_kind().items()},
            "top_files": [{"path": p, "tokens": t} for p, t in self.top_files()],
        }


def _result_text(block: dict) -> str:
    c = block.get("content")
    if isinstance(c, str):
        return c
    if isinstance(c, list):
        return "".join(
            b.get("text", "") for b in c if isinstance(b, dict) and b.get("type") == "text"
        )
    return json.dumps(c or "")


def _iter_records(path: Path):
    try:
        with path.open(errors="replace") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    yield json.loads(line)
                except json.JSONDecodeError:
                    continue
    except OSError:
        return


def analyze_session(path: Path, model: str = DEFAULT_MODEL) -> tuple[list[WasteItem], int, int, int]:
    """Returns (waste items, read calls, read tokens, resident token-turns)."""
    pending: dict[str, tuple[str, dict]] = {}
    # file path -> list of (content hash, text, turn index)
    seen: dict[str, list[tuple[str, str, int]]] = defaultdict(list)
    written: dict[str, int] = {}
    items: list[WasteItem] = []
    calls = read_tokens = resident = 0
    turn = 0
    total_turns = 0

    records = list(_iter_records(path))
    for d in records:
        if d.get("type") == "assistant":
            total_turns += 1

    for d in records:
        msg = d.get("message")
        if not isinstance(msg, dict):
            continue
        if d.get("type") == "assistant":
            turn += 1
            content = msg.get("content")
            if isinstance(content, list):
                for b in content:
                    if isinstance(b, dict) and b.get("type") == "tool_use":
                        name = b.get("name", "")
                        pending[b.get("id")] = (name, b.get("input") or {})
                        if name in WRITE_TOOLS:
                            fp = str((b.get("input") or {}).get("file_path", ""))
                            if fp:
                                written[fp] = turn
        elif d.get("type") == "user":
            content = msg.get("content")
            if not isinstance(content, list):
                continue
            for b in content:
                if not isinstance(b, dict) or b.get("type") != "tool_result":
                    continue
                name, args = pending.get(b.get("tool_use_id"), ("", {}))
                if name not in READ_TOOLS:
                    continue
                fp = str(args.get("file_path") or args.get("path") or "?")
                text = _result_text(b)
                tokens = count_text(text, model).tokens
                calls += 1
                read_tokens += tokens
                h = hashlib.sha256(text.encode(errors="replace")).hexdigest()[:16]

                prior = seen[fp]
                kind = detail = ""
                if any(ph == h for ph, _, _ in prior):
                    kind, detail = "exact_repeat", "byte-identical to an earlier read"
                elif any(pt and pt in text for _, pt, _ in prior):
                    kind, detail = "superset", "earlier read is contained in this one"
                elif fp in written and written[fp] < turn and not prior:
                    kind, detail = "write_readback", "read back content the agent just wrote"

                if kind:
                    items.append(
                        WasteItem(
                            kind=kind, path=fp, session=path.stem, tokens=tokens, detail=detail
                        )
                    )
                    # cost is not one copy: it is resent every remaining turn
                    resident += tokens * max(0, total_turns - turn)
                prior.append((h, text, turn))
    return items, calls, read_tokens, resident


def analyze(
    root: Path | None = None, model: str = DEFAULT_MODEL, max_sessions: int | None = None
) -> ReadWasteReport:
    root = root or CLAUDE_ROOT
    report = ReadWasteReport()
    if not root.exists():
        return report
    paths = sorted(root.rglob("*.jsonl"))
    if max_sessions:
        paths = paths[-max_sessions:]
    for p in paths:
        items, calls, tokens, resident = analyze_session(p, model)
        if calls:
            report.sessions += 1
        report.items += items
        report.read_calls += calls
        report.read_tokens += tokens
        report.resident_token_turns += resident
    return report
