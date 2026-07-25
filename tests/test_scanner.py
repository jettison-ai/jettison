"""Scanner tests against the fixture project + fake MCP server."""

from __future__ import annotations

from pathlib import Path

from jettison.scanner import Category, scan
from jettison.scanner.duplicates import find_duplicates
from jettison.scanner.mcp import discover_claude_code

FIXTURE = Path(__file__).parent / "fixtures" / "demo_project"


def test_discover_claude_finds_project_mcp():
    specs = discover_claude_code(FIXTURE)
    names = {s.name for s in specs}
    assert {"demo-tools", "search-service"} <= names


def test_live_scan_measures_tools_and_instructions():
    report = scan(client="claude", project_dir=FIXTURE)
    cats = {t.category: t for t in report.category_totals()}
    assert cats[Category.MCP_TOOLS].item_count == 20  # 12 + 8 tools
    assert cats[Category.MCP_TOOLS].tokens > 5000
    assert Category.SKILLS in cats and cats[Category.SKILLS].item_count == 2
    assert Category.INSTRUCTIONS in cats
    assert not report.unintrospected_servers
    d = report.to_dict()
    assert d["total_tokens"] == report.total_tokens


def test_no_launch_gives_estimates():
    report = scan(client="claude", project_dir=FIXTURE, launch_servers=False)
    assert set(report.unintrospected_servers) == {"demo-tools", "search-service"}
    mcp_items = [i for i in report.items if i.category == Category.MCP_TOOLS]
    assert all(i.token_label == "estimated" for i in mcp_items)


def test_duplicate_detection():
    para = "Always run the full lint suite before committing any changes, and fix every warning."
    files = [("a", f"{para}\n\nunique one that is long enough to pass the filter"), ("b", para)]
    dups = find_duplicates(files, lambda t: len(t) // 4)
    assert len(dups) == 1
    assert set(dups[0].sources) == {"a", "b"}
    assert dups[0].wasted_tokens > 0
