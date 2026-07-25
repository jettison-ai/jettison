"""Data model for standing-context scan reports."""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from enum import Enum


class Category(str, Enum):
    MCP_TOOLS = "mcp_tools"
    SKILLS = "skills"
    INSTRUCTIONS = "instructions"
    DUPLICATES = "duplicates"
    SYSTEM_PROMPT = "system_prompt"

    @property
    def display(self) -> str:
        return {
            Category.MCP_TOOLS: "MCP tool definitions",
            Category.SKILLS: "Skills",
            Category.INSTRUCTIONS: "Project instructions",
            Category.DUPLICATES: "Duplicate context",
            Category.SYSTEM_PROMPT: "System prompt",
        }[self]


@dataclass
class ScanItem:
    """One standing-context artifact (a tool schema, a skill, a rules file)."""

    category: Category
    name: str
    source: str  # file path or "<server>:<tool>" origin
    tokens: int
    token_label: str  # "measured" | "estimated"
    detail: str = ""


@dataclass
class CategoryTotal:
    category: Category
    tokens: int
    item_count: int
    token_label: str


@dataclass
class ScanReport:
    client: str
    project_dir: str
    model: str
    items: list[ScanItem] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    # Servers we could not introspect live (config-only estimates).
    unintrospected_servers: list[str] = field(default_factory=list)

    @property
    def total_tokens(self) -> int:
        return sum(i.tokens for i in self.items)

    @property
    def token_label(self) -> str:
        labels = {i.token_label for i in self.items}
        return "measured" if labels == {"measured"} else "estimated"

    def category_totals(self) -> list[CategoryTotal]:
        by_cat: dict[Category, list[ScanItem]] = {}
        for item in self.items:
            by_cat.setdefault(item.category, []).append(item)
        totals = [
            CategoryTotal(
                category=cat,
                tokens=sum(i.tokens for i in items),
                item_count=len(items),
                token_label=(
                    "measured"
                    if {i.token_label for i in items} == {"measured"}
                    else "estimated"
                ),
            )
            for cat, items in by_cat.items()
        ]
        totals.sort(key=lambda t: t.tokens, reverse=True)
        return totals

    def to_dict(self) -> dict:
        d = asdict(self)
        d["total_tokens"] = self.total_tokens
        d["token_label"] = self.token_label
        d["category_totals"] = [asdict(t) for t in self.category_totals()]
        return d

    def to_json(self) -> str:
        return json.dumps(self.to_dict(), indent=2, default=str)
