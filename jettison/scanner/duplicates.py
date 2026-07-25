"""Cross-file duplicate-instruction detection.

Finds paragraphs that appear (after normalization) in more than one
standing-context file — e.g. the same "always run the linter" rule pasted
into CLAUDE.md, AGENTS.md and .cursorrules. Every copy after the first is
pure waste, billed on every request.
"""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass, field

_MIN_PARAGRAPH_CHARS = 60  # ignore trivial fragments ("## Notes")


@dataclass
class DuplicateGroup:
    snippet: str  # first 120 chars of the canonical paragraph
    sources: list[str] = field(default_factory=list)
    tokens_each: int = 0

    @property
    def wasted_tokens(self) -> int:
        return self.tokens_each * (len(self.sources) - 1)


def _normalize(paragraph: str) -> str:
    text = paragraph.lower()
    text = re.sub(r"[#*_`>-]", "", text)
    text = re.sub(r"\s+", " ", text)
    return text.strip()


def _paragraphs(text: str) -> list[str]:
    return [p.strip() for p in re.split(r"\n\s*\n", text) if p.strip()]


def find_duplicates(
    files: list[tuple[str, str]], count_tokens
) -> list[DuplicateGroup]:
    """files: (source_name, text). count_tokens: str -> int."""
    by_hash: dict[str, DuplicateGroup] = {}
    seen_in_file: dict[str, set[str]] = {}
    for source, text in files:
        for para in _paragraphs(text):
            norm = _normalize(para)
            if len(norm) < _MIN_PARAGRAPH_CHARS:
                continue
            h = hashlib.sha256(norm.encode()).hexdigest()[:16]
            # count a paragraph once per file even if repeated within it
            if h in seen_in_file.setdefault(source, set()):
                continue
            seen_in_file[source].add(h)
            group = by_hash.get(h)
            if group is None:
                by_hash[h] = DuplicateGroup(
                    snippet=para[:120], sources=[source], tokens_each=count_tokens(para)
                )
            else:
                group.sources.append(source)
    dups = [g for g in by_hash.values() if len(g.sources) > 1]
    dups.sort(key=lambda g: g.wasted_tokens, reverse=True)
    return dups
