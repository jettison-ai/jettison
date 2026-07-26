"""`jettison optimize` — install the client-side savings stack."""

from __future__ import annotations

from pathlib import Path

import click

from jettison.cli import main


@main.command("optimize")
@click.option("--project", type=click.Path(exists=True, file_okay=False, path_type=Path), default=None)
@click.option("--global", "global_scope", is_flag=True, help="Install for all projects (~/.claude).")
@click.option("--client", "-c", default="claude", show_default=True,
              type=click.Choice(["claude", "codex", "cursor", "cline", "opencode", "openclaw"]),
              help="Which agent client to optimize. Non-Claude clients get the repo map and\noutput style; the read-pruning hook is Claude Code only.")
@click.option("--scout", is_flag=True, help="Also install the navigation subagent (measured -34% on authoring work; off by default).")
@click.option("--no-prune", is_flag=True, help="Skip the read-pruning hook.")
@click.option("--no-terse", is_flag=True, help="Skip output-verbosity reduction.")
@click.option("--terse-level", type=click.Choice(["balanced", "terse"]), default="balanced",
              show_default=True, help="Response style. 'terse' measured WORSE (-20.6% cost); experimental only.")
def optimize_cmd(
    project: Path | None,
    global_scope: bool,
    client: str,
    scout: bool,
    no_prune: bool,
    no_terse: bool,
    terse_level: str,
) -> None:
    """Install client-side optimizations for Claude Code.

    \b
    Everything installed here runs INSIDE the client, so the transcript
    itself gets smaller and the client caches the smaller version. A proxy
    cannot do this — see docs/FINDINGS.md.
    """
    from rich.console import Console

    from jettison.optimize import (
        add_delegation_rule,
        add_repo_map,
        install_hook,
        install_scout,
        verbosity,
    )

    console = Console()
    console.print()

    md, tokens = add_repo_map(project, client=client)
    console.print(f"[green]✓[/green] repo map  [dim]{md}[/dim]")
    console.print(f"  [dim]{tokens:,} tokens indexing the whole codebase, so the agent never explores[/dim]")

    if not no_terse:
        md = verbosity.install(project, terse_level, client=client)
        console.print(f"[green]✓[/green] output style ({terse_level})  [dim]{md}[/dim]")
        console.print("  [dim]output is billed ~50x cache-read and re-sent every later turn[/dim]")

    if scout:
        p = install_scout(project, global_scope)
        add_delegation_rule(project)
        console.print(f"[green]✓[/green] scout subagent  [dim]{p}[/dim]")
        console.print("  [yellow]note:[/yellow] [dim]measured -34% on authoring work; helps only exploration[/dim]")
    if not no_prune and client == "claude":
        s = install_hook(project, global_scope)
        console.print(f"[green]✓[/green] read-pruning hook  [dim]{s}[/dim]")
        console.print("  [dim]large file reads trimmed to what the task needs; logs compressed as prose[/dim]")
    elif not no_prune:
        console.print(f"[dim]—[/dim] read-pruning hook skipped: {client} has no hook API")

    console.print(
        "\n[bold]Restart Claude Code[/bold] to pick these up.\n"
    )
    # Say plainly how strong the evidence is. A user who installs this
    # believing it is guaranteed and then sees a worse bill is a user we
    # lied to — and the measurements do not support a guarantee yet.
    console.print(
        "[yellow]Evidence status:[/yellow] measured at [bold]-10.6% cost, -25% turns[/bold]\n"
        "over 6 paired tasks on a real repo, but [bold]2 of those 6 came out\n"
        "slightly negative[/bold] and the confidence interval still spans zero.\n"
        "Savings concentrate in exploration and comprehension work; pure\n"
        "authoring is closer to neutral.\n\n"
        "[bold]Do not take our word for it:[/bold] run [bold]jettison verify[/bold] to\n"
        "measure it on your own repository. If it comes out negative there,\n"
        "please tell us — that is more useful than a win.\n\n"
        "[dim]Undo everything with: jettison unoptimize[/dim]\n"
    )


@main.command("unoptimize")
@click.option("--project", type=click.Path(exists=True, file_okay=False, path_type=Path), default=None)
@click.option("--global", "global_scope", is_flag=True)
@click.option("--client", "-c", default="claude", show_default=True)
def unoptimize_cmd(project: Path | None, global_scope: bool, client: str) -> None:
    """Remove everything `jettison optimize` installed."""
    from rich.console import Console

    from jettison.optimize import (
        remove_delegation_rule,
        remove_repo_map,
        uninstall_hook,
        uninstall_scout,
        verbosity,
    )

    console = Console()
    console.print(f"repo map removed: {remove_repo_map(project, client)}")
    console.print(f"output style removed: {verbosity.uninstall(project, client)}")
    console.print(f"scout agent removed: {uninstall_scout(project, global_scope)}")
    console.print(f"delegation rule removed: {remove_delegation_rule(project)}")
    console.print(f"pruning hook removed: {uninstall_hook(project, global_scope)}")
