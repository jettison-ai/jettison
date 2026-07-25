"""`jettison optimize` — install the client-side savings stack."""

from __future__ import annotations

from pathlib import Path

import click

from jettison.cli import main


@main.command("optimize")
@click.option("--project", type=click.Path(exists=True, file_okay=False, path_type=Path), default=None)
@click.option("--global", "global_scope", is_flag=True, help="Install for all projects (~/.claude).")
@click.option("--scout", is_flag=True, help="Also install the navigation subagent (measured -34% on authoring work; off by default).")
@click.option("--no-prune", is_flag=True, help="Skip the read-pruning hook.")
def optimize_cmd(project: Path | None, global_scope: bool, scout: bool, no_prune: bool) -> None:
    """Install client-side optimizations for Claude Code.

    \b
    Everything installed here runs INSIDE the client, so the transcript
    itself gets smaller and the client caches the smaller version. A proxy
    cannot do this — see docs/FINDINGS.md.
    """
    from rich.console import Console

    from jettison.optimize import add_delegation_rule, add_repo_map, install_hook, install_scout

    console = Console()
    console.print()

    md, tokens = add_repo_map(project)
    console.print(f"[green]✓[/green] repo map  [dim]{md}[/dim]")
    console.print(f"  [dim]{tokens:,} tokens indexing the whole codebase, so the agent never explores[/dim]")

    if scout:
        p = install_scout(project, global_scope)
        add_delegation_rule(project)
        console.print(f"[green]✓[/green] scout subagent  [dim]{p}[/dim]")
        console.print("  [yellow]note:[/yellow] [dim]measured -34% on authoring work; helps only exploration[/dim]")
    if not no_prune:
        s = install_hook(project, global_scope)
        console.print(f"[green]✓[/green] read-pruning hook  [dim]{s}[/dim]")
        console.print("  [dim]large file reads are trimmed to what your task needs, with line numbers kept[/dim]")

    console.print(
        "\n[bold]Restart Claude Code[/bold] to pick these up, then run "
        "[bold]jettison savings[/bold] after a session.\n"
        "[dim]Undo anything with: jettison unoptimize[/dim]\n"
    )


@main.command("unoptimize")
@click.option("--project", type=click.Path(exists=True, file_okay=False, path_type=Path), default=None)
@click.option("--global", "global_scope", is_flag=True)
def unoptimize_cmd(project: Path | None, global_scope: bool) -> None:
    """Remove everything `jettison optimize` installed."""
    from rich.console import Console

    from jettison.optimize import (
        remove_delegation_rule,
        remove_repo_map,
        uninstall_hook,
        uninstall_scout,
    )

    console = Console()
    console.print(f"repo map removed: {remove_repo_map(project)}")
    console.print(f"scout agent removed: {uninstall_scout(project, global_scope)}")
    console.print(f"delegation rule removed: {remove_delegation_rule(project)}")
    console.print(f"pruning hook removed: {uninstall_hook(project, global_scope)}")
