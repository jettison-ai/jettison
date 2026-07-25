"""Instruction & skill compiler.

Compiles CLAUDE.md / AGENTS.md / rules files / SKILL.md prose into a
compact, byte-stable bundle:

- cross-file paragraph dedup (first occurrence wins, later copies drop)
- critical rules preserved VERBATIM — deterministic detection; the
  Commitment Verifier re-checks the result, so classification errors
  fail safe (a rule wrongly judged non-critical still gets verified and
  re-inflated on violation)
- non-critical prose is whitespace-normalized only (v1); an
  instruction-specialized learned compressor is a phase-2 item

The compiled bundle keeps a span map back to the original text so the
verifier can re-inflate any span.
"""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass, field

# A paragraph containing any of these is treated as a critical rule and
# preserved byte-for-byte. Deliberately over-inclusive: false positives
# cost a few tokens; false negatives are caught by the verifier.
_CRITICAL_MARKERS = re.compile(
    r"\b(never|always|must(?:\s+not)?|do not|don't|forbidden|required|"
    r"security|secret|credential|token|password|api.?key|production|deploy|"
    r"delete|drop|irreversible|destructive|approval|permission)\b",
    re.I,
)

_MD_HEADER = re.compile(r"^\s{0,3}#{1,6}\s")


@dataclass
class CompiledSpan:
    source: str  # originating file label
    original: str  # exact original paragraph
    compiled: str  # what goes into context ("" if dropped as duplicate)
    critical: bool
    duplicate_of: str | None = None  # source label of the surviving copy


@dataclass
class CompiledInstructions:
    text: str
    spans: list[CompiledSpan] = field(default_factory=list)
    content_hash: str = ""

    @property
    def dropped_duplicates(self) -> int:
        return sum(1 for s in self.spans if s.duplicate_of)


def _normalize_key(paragraph: str) -> str:
    text = paragraph.lower()
    text = re.sub(r"[#*_`>-]", "", text)
    return re.sub(r"\s+", " ", text).strip()


def _paragraphs(text: str) -> list[str]:
    return [p for p in re.split(r"\n\s*\n", text) if p.strip()]


def compile_instructions(files: list[tuple[str, str]]) -> CompiledInstructions:
    """files: (label, text) in priority order (project files first)."""
    seen: dict[str, str] = {}  # normalized paragraph -> source label
    spans: list[CompiledSpan] = []
    out_parts: list[str] = []

    for label, text in files:
        # Strip YAML frontmatter from skills; its content is metadata for
        # the host, not the model.
        text = re.sub(r"\A---\n.*?\n---\n", "", text, flags=re.S)
        file_parts: list[str] = []
        for para in _paragraphs(text):
            para_stripped = para.strip("\n")
            key = _normalize_key(para_stripped)
            if not key:
                continue
            if _MD_HEADER.match(para_stripped) and len(key) < 60:
                # short headers pass through un-deduped (structural)
                file_parts.append(para_stripped)
                spans.append(
                    CompiledSpan(source=label, original=para_stripped, compiled=para_stripped, critical=False)
                )
                continue
            if key in seen:
                spans.append(
                    CompiledSpan(
                        source=label,
                        original=para_stripped,
                        compiled="",
                        critical=bool(_CRITICAL_MARKERS.search(para_stripped)),
                        duplicate_of=seen[key],
                    )
                )
                continue
            seen[key] = label
            critical = bool(_CRITICAL_MARKERS.search(para_stripped))
            compiled = para_stripped if critical else " ".join(para_stripped.split())
            file_parts.append(compiled)
            spans.append(
                CompiledSpan(source=label, original=para_stripped, compiled=compiled, critical=critical)
            )
        if file_parts:
            out_parts.append("\n\n".join(file_parts))

    text_out = "\n\n".join(out_parts).strip()
    return CompiledInstructions(
        text=text_out,
        spans=spans,
        content_hash=hashlib.sha256(text_out.encode()).hexdigest()[:16],
    )


@dataclass
class SkillSummary:
    name: str
    description: str
    body: str  # full body kept locally for on-demand loading


def summarize_skill(name: str, text: str) -> SkillSummary:
    """Reduce a skill to its one-line index entry; full body stays local.

    Uses frontmatter `description:` when present, else the first sentence
    of the body.
    """
    m = re.search(r"^description:\s*(.+)$", text, re.M)
    if m:
        desc = m.group(1).strip().strip("\"'")
    else:
        body = re.sub(r"\A---\n.*?\n---\n", "", text, flags=re.S)
        body = re.sub(r"^\s{0,3}#{1,6}\s.*$", "", body, flags=re.M).strip()
        first = re.split(r"(?<=[.!?])\s+", " ".join(body.split()))[:1]
        desc = first[0] if first else ""
    return SkillSummary(name=name, description=desc[:160], body=text)
