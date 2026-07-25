"""Per-request audit records: what compressed, what verified, what re-inflated.

Stored locally as JSONL at ~/.jettison/audit/records.jsonl. Surfaces in
the product only as "verified task parity" + the fallback rate; the full
records are the research artifact.
"""

from __future__ import annotations

import json
import os
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path


def audit_dir() -> Path:
    root = Path(os.environ.get("JETTISON_WORKSPACE_DIR", Path.home() / ".jettison"))
    d = root / "audit"
    d.mkdir(parents=True, exist_ok=True)
    return d


def records_path() -> Path:
    return audit_dir() / "records.jsonl"


@dataclass
class AuditRecord:
    request_id: str
    provider: str
    model: str
    tokens_before: int
    tokens_after: int
    commitments_checked: int = 0
    violations: int = 0
    reinflated: bool = False
    meta_calls_resolved: int = 0
    loop_rounds: int = 0
    mixed_turn: bool = False
    rewrote_tools: bool = False
    rewrote_system: bool = False
    violation_kinds: list[str] = field(default_factory=list)
    # Why the tool surface was left to the client (native deferred
    # loading); "" means we owned it. New fields default so records
    # written by older versions still parse.
    native_deferral_reason: str = ""
    heartbeat: bool = False
    ts: float = 0.0

    def write(self) -> None:
        self.ts = time.time()
        try:
            with records_path().open("a") as f:
                f.write(json.dumps(asdict(self), separators=(",", ":")) + "\n")
        except OSError:
            pass  # audit logging must never break the request


def read_records(limit: int = 100_000) -> list[dict]:
    path = records_path()
    if not path.exists():
        return []
    out = []
    try:
        with path.open() as f:
            for line in f:
                line = line.strip()
                if line:
                    try:
                        out.append(json.loads(line))
                    except json.JSONDecodeError:
                        continue
    except OSError:
        return []
    return out[-limit:]


def fallback_rate(records: list[dict]) -> float:
    if not records:
        return 0.0
    return sum(1 for r in records if r.get("reinflated")) / len(records)
