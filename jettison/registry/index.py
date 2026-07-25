"""BM25 search over capabilities (pure Python, no dependencies).

v1 ranking, mirroring Headroom's BM25 fallback tier. A learned ranker
trained on agent traces is the phase-2 upgrade (Jettison's
Kompress-equivalent); this module is its interface seam.
"""

from __future__ import annotations

import math
import re
from dataclasses import dataclass

_TOKEN = re.compile(r"[a-z0-9]+")


def _terms(text: str) -> list[str]:
    # split camelCase and snake_case before lowercasing
    text = re.sub(r"(?<=[a-z0-9])(?=[A-Z])", " ", text)
    text = text.replace("_", " ").replace("-", " ")
    return _TOKEN.findall(text.lower())


@dataclass
class SearchHit:
    name: str
    score: float
    summary: str


class BM25Index:
    K1 = 1.5
    B = 0.75

    def __init__(self) -> None:
        self._docs: dict[str, list[str]] = {}
        self._summaries: dict[str, str] = {}
        self._df: dict[str, int] = {}
        self._avgdl = 0.0

    def add(self, name: str, text: str, summary: str) -> None:
        terms = _terms(name) * 3 + _terms(text)  # weight the name
        self._docs[name] = terms
        self._summaries[name] = summary

    def finalize(self) -> None:
        self._df = {}
        for terms in self._docs.values():
            for t in set(terms):
                self._df[t] = self._df.get(t, 0) + 1
        total = sum(len(t) for t in self._docs.values())
        self._avgdl = total / len(self._docs) if self._docs else 0.0

    def search(self, query: str, limit: int = 8) -> list[SearchHit]:
        q_terms = _terms(query)
        n = len(self._docs)
        if not n or not q_terms:
            return []
        hits = []
        for name, doc in self._docs.items():
            dl = len(doc) or 1
            score = 0.0
            for qt in q_terms:
                tf = doc.count(qt)
                if not tf:
                    continue
                df = self._df.get(qt, 0)
                idf = math.log(1 + (n - df + 0.5) / (df + 0.5))
                score += idf * tf * (self.K1 + 1) / (
                    tf + self.K1 * (1 - self.B + self.B * dl / self._avgdl)
                )
            if score > 0:
                hits.append(SearchHit(name=name, score=score, summary=self._summaries[name]))
        hits.sort(key=lambda h: (-h.score, h.name))
        return hits[:limit]
