"""Capability store: the local, full-fidelity side of the registry.

Holds every minified schema and skill body out of context. The model
sees only the compact index (stable prefix) plus whatever it explicitly
loads (context tail).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from jettison.compiler.bundle import CompiledBundle
from jettison.registry.index import BM25Index, SearchHit


@dataclass
class CapabilityStore:
    bundle: CompiledBundle
    _index: BM25Index = field(default_factory=BM25Index)

    def __post_init__(self) -> None:
        for name, schema in self.bundle.schema_store.items():
            desc = schema.get("description", "")
            self._index.add(name, f"{desc} {self._param_names(schema)}", desc[:120])
        for skill in self.bundle.skills:
            self._index.add(f"skill:{skill.name}", f"{skill.description} {skill.body[:500]}", skill.description)
        self._index.finalize()

    @staticmethod
    def _param_names(schema: dict[str, Any]) -> str:
        props = (schema.get("input_schema") or {}).get("properties") or {}
        return " ".join(props.keys())

    def search(self, query: str, limit: int = 8) -> list[SearchHit]:
        return self._index.search(query, limit=limit)

    def load(self, names: list[str]) -> tuple[list[dict[str, Any]], list[str]]:
        """Return (full definitions, missing names) for the requested capabilities."""
        found: list[dict[str, Any]] = []
        missing: list[str] = []
        for name in names:
            if name.startswith("skill:"):
                skill = next((s for s in self.bundle.skills if s.name == name[6:]), None)
                if skill:
                    found.append({"skill": skill.name, "content": skill.body})
                else:
                    missing.append(name)
            elif name in self.bundle.schema_store:
                schema = dict(self.bundle.schema_store[name])
                refs = self._refs_used(schema)
                if refs:
                    schema["$defs"] = {r: self.bundle.shared_defs[r] for r in sorted(refs)}
                found.append(schema)
            else:
                missing.append(name)
        return found, missing

    def _refs_used(self, node: Any, acc: set[str] | None = None) -> set[str]:
        acc = acc if acc is not None else set()
        if isinstance(node, dict):
            ref = node.get("$ref", "")
            if isinstance(ref, str) and ref.startswith("#/$defs/"):
                acc.add(ref.split("/")[-1])
            for v in node.values():
                self._refs_used(v, acc)
        elif isinstance(node, list):
            for v in node:
                self._refs_used(v, acc)
        return acc

    @property
    def capability_names(self) -> list[str]:
        return sorted(self.bundle.schema_store.keys()) + [f"skill:{s.name}" for s in self.bundle.skills]
