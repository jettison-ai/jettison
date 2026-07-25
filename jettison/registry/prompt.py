"""Compact capability-index rendering for the stable prefix.

Byte-stable: capabilities sorted by name, no timestamps, no counts that
drift. This text is part of the cached prefix — any variation busts the
provider prefix cache and costs real money.
"""

from __future__ import annotations

from jettison.compiler.instructions_min import SkillSummary


def render_capability_index(
    tool_names_with_summaries: list[tuple[str, str]],
    skills: list[SkillSummary],
) -> str:
    lines = [
        "## Capability registry",
        "",
        "Full tool schemas are not preloaded. To use a capability below,",
        "first call jettison_load_capabilities with its name (or find one",
        "with jettison_search_capabilities). Loaded schemas arrive as tool",
        "results.",
        "",
    ]
    if tool_names_with_summaries:
        lines.append("Tools:")
        for name, summary in sorted(tool_names_with_summaries):
            entry = f"- {name}"
            if summary:
                entry += f": {summary}"
            lines.append(entry)
    if skills:
        lines.append("")
        lines.append("Skills (load as skill:<name>):")
        for s in sorted(skills, key=lambda x: x.name):
            entry = f"- {s.name}"
            if s.description:
                entry += f": {s.description}"
            lines.append(entry)
    return "\n".join(lines)
