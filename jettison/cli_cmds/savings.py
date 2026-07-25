"""`jettison savings` — tokens/dollars avoided, cache-aware. (v1 core in jettison/savings)."""

from __future__ import annotations

import click

from jettison.cli import main


@main.command("savings")
@click.option("--json", "as_json", is_flag=True, help="Emit JSON.")
@click.option("--export", "export_path", type=click.Path(), default=None, help="Write dated JSON/CSV export.")
def savings_cmd(as_json: bool, export_path: str | None) -> None:
    """Show tokens and dollars avoided (cache-aware), fallback rate, before/after."""
    from jettison.savings.report import render_savings

    render_savings(as_json=as_json, export_path=export_path)
