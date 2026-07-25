"""Commitment verification + automatic fallback.

Fail safe, never fail open: any commitment the optimized context no
longer entails triggers restoration of the violated span. Verification
results are cached per (original, optimized) content hash so verifier
latency stays off the hot path (§8.4).
"""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass, field
from typing import Any

from jettison.verifier.commitments import (
    Commitment,
    CommitmentKind,
    extract_text_commitments,
    extract_tool_commitments,
)


@dataclass
class Violation:
    commitment: Commitment
    reason: str


@dataclass
class VerifyResult:
    ok: bool
    commitments_checked: int
    violations: list[Violation] = field(default_factory=list)
    restored_text: str | None = None  # set when fallback re-inflated spans


def _norm(text: str) -> str:
    return re.sub(r"\s+", " ", text).strip().lower()


class TextVerifier:
    """Checks that every commitment extracted from `original` is still
    entailed (v1: normalized containment) by `optimized`. On violation,
    re-inflates the violated span by appending the original paragraph."""

    def __init__(self, cache_size: int = 512) -> None:
        self._cache: dict[str, VerifyResult] = {}
        self._cache_size = cache_size

    def verify_and_repair(self, original: str, optimized: str, source: str = "system") -> VerifyResult:
        key = hashlib.sha256(f"{original}\x00{optimized}".encode()).hexdigest()
        cached = self._cache.get(key)
        if cached is not None:
            return cached

        commitments = extract_text_commitments(original, source=source)
        norm_opt = _norm(optimized)
        violations: list[Violation] = []
        for c in commitments:
            if _norm(c.span) not in norm_opt:
                violations.append(Violation(commitment=c, reason="span not entailed by optimized context"))

        restored: str | None = None
        if violations:
            # Re-inflate: append each violated original span verbatim, in
            # original order, deduplicated.
            missing_spans: list[str] = []
            seen: set[str] = set()
            for v in violations:
                s = v.commitment.span
                if s not in seen:
                    seen.add(s)
                    missing_spans.append(s)
            restored = optimized + "\n\n" + "\n\n".join(missing_spans)

        result = VerifyResult(
            ok=not violations,
            commitments_checked=len(commitments),
            violations=violations,
            restored_text=restored,
        )
        if len(self._cache) >= self._cache_size:
            self._cache.clear()
        self._cache[key] = result
        return result


def verify_tool_registry(
    original_tools: list[dict[str, Any]],
    capability_names: set[str],
    schema_store: dict[str, dict[str, Any]],
    provider: str,
) -> VerifyResult:
    """Every original tool must remain reachable through the registry with
    its calling contract intact (name, required list, param names)."""
    commitments = extract_tool_commitments(original_tools)
    violations: list[Violation] = []
    for c in commitments:
        stored = schema_store.get(c.key)
        if c.key not in capability_names or stored is None:
            violations.append(Violation(commitment=c, reason="tool missing from capability registry"))
            continue
        schema = stored.get("input_schema") or {}
        params = sorted((schema.get("properties") or {}).keys())
        required = sorted(schema.get("required") or [])
        expected = c.span
        actual = f"{c.key} required={required} params={params}"
        if expected != actual:
            violations.append(
                Violation(commitment=c, reason=f"contract drift: expected {expected!r}, got {actual!r}")
            )
    return VerifyResult(ok=not violations, commitments_checked=len(commitments), violations=violations)
