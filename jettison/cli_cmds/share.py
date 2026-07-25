"""`jettison share` — shareable savings receipt/badge."""

from __future__ import annotations

import click

from jettison.cli import main


@main.command("share")
@click.option("--markdown", "as_md", is_flag=True, help="Emit a Markdown badge snippet.")
def share_cmd(as_md: bool) -> None:
    """Generate a shareable savings receipt ("This repo saved N tokens this week")."""
    from jettison.savings.share import render_share

    render_share(as_md=as_md)
