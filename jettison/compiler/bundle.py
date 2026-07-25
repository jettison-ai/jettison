"""Compiled standing-context bundle.

The bundle is the unit the proxy injects as the STABLE PREFIX. It must be
byte-identical across requests for a given input state (cache safety —
docs/CACHE_SAFETY.md): no timestamps, no session ids, no load-order
variation. All maps are sorted; the hash covers the exact serialized
bytes.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from typing import Any

from jettison.compiler.instructions_min import CompiledInstructions, SkillSummary
from jettison.compiler.schema_min import MinifyResult


@dataclass
class CompiledBundle:
    # Compact capability index rendered into the stable prefix.
    capability_index_text: str
    # Compiled instructions (deduped, critical rules verbatim).
    instructions: CompiledInstructions
    # Skill one-liners for the index; bodies stay local.
    skills: list[SkillSummary] = field(default_factory=list)
    # Full minified schemas, keyed by capability name — served on demand
    # at the context tail, never in the prefix.
    schema_store: dict[str, dict[str, Any]] = field(default_factory=dict)
    shared_defs: dict[str, Any] = field(default_factory=dict)
    content_hash: str = ""

    def stable_prefix_text(self) -> str:
        """Exact text injected into the system prompt. Byte-stable."""
        parts = []
        if self.instructions.text:
            parts.append(self.instructions.text)
        if self.capability_index_text:
            parts.append(self.capability_index_text)
        return "\n\n".join(parts)


def build_bundle(
    minified: MinifyResult,
    instructions: CompiledInstructions,
    skills: list[SkillSummary],
    capability_index_text: str,
) -> CompiledBundle:
    schema_store = {t.name: t.to_json() for t in minified.tools}
    bundle = CompiledBundle(
        capability_index_text=capability_index_text,
        instructions=instructions,
        skills=sorted(skills, key=lambda s: s.name),
        schema_store=schema_store,
        shared_defs=minified.shared_defs,
    )
    canonical = json.dumps(
        {
            "prefix": bundle.stable_prefix_text(),
            "schemas": schema_store,
            "$defs": minified.shared_defs,
            "skills": [(s.name, s.description) for s in bundle.skills],
        },
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
    )
    bundle.content_hash = hashlib.sha256(canonical.encode()).hexdigest()[:16]
    return bundle
