"""`jettison audit` — standalone standing-context waste scanner.

Read-only. Tells you how many tokens your agent pays for on every single
turn before it has done anything, broken down by category.
"""

from __future__ import annotations

from pathlib import Path

import click

from jettison.cli import main
from jettison.pricing import cache_aware_savings, get_price


@main.command("audit")
@click.option(
    "--client",
    "-c",
    default="claude",
    show_default=True,
    help="Agent client to audit (claude, codex, cursor, cline, opencode, openclaw).",
)
@click.option(
    "--project",
    "-p",
    type=click.Path(exists=True, file_okay=False, path_type=Path),
    default=None,
    help="Project directory (default: cwd).",
)
@click.option("--model", default="claude-sonnet-4-5", show_default=True, help="Model for token counting/pricing.")
@click.option(
    "--no-launch",
    is_flag=True,
    help="Do not launch MCP servers for live schema introspection (config-only estimates).",
)
@click.option(
    "--timeout",
    default=None,
    type=float,
    help="Seconds to wait per MCP server (default: 90 — npx/uvx servers are slow to start).",
)
@click.option(
    "--reads/--no-reads",
    default=True,
    show_default=True,
    help="Also analyze local session transcripts for re-read waste.",
)
@click.option("--json", "as_json", is_flag=True, help="Emit the full report as JSON.")
@click.option("--top", default=10, show_default=True, help="Show the N most expensive items per category.")
def audit_cmd(
    client: str,
    project: Path | None,
    model: str,
    no_launch: bool,
    timeout: float | None,
    reads: bool,
    as_json: bool,
    top: int,
) -> None:
    """Scan your agent's standing context and report per-turn token waste.

    \b
    Examples:
      jettison audit                       # audit Claude Code in this repo
      jettison audit -c openclaw           # audit an OpenClaw install
      jettison audit --json > report.json  # machine-readable output
    """
    from jettison.scanner import SUPPORTED_CLIENTS, scan
    from jettison.scanner.mcp import INTROSPECT_TIMEOUT_S

    if client not in SUPPORTED_CLIENTS:
        raise click.ClickException(f"unknown client {client!r}. Supported: {', '.join(SUPPORTED_CLIENTS)}")

    report = scan(
        client=client,
        project_dir=project,
        model=model,
        launch_servers=not no_launch,
        introspect_timeout=timeout if timeout is not None else INTROSPECT_TIMEOUT_S,
    )

    read_report = None
    if reads and client in ("claude", "codex"):
        from jettison.waste import analyze

        read_report = analyze(model=model)

    if as_json:
        import json as _json

        payload = report.to_dict()
        if read_report is not None:
            payload["read_waste"] = read_report.to_dict()
        click.echo(_json.dumps(payload, indent=2, default=str))
        return

    _render(report, model, top)
    if read_report is not None and read_report.read_calls:
        _render_reads(read_report, model)


def _render(report, model: str, top: int) -> None:
    from rich.console import Console
    from rich.table import Table

    console = Console()
    totals = report.category_totals()
    total = report.total_tokens
    label = report.token_label

    if not report.items:
        console.print(
            f"[green]No standing context found for client '{report.client}' in {report.project_dir}.[/green]\n"
            "Either this setup is already lean, or the client's config lives elsewhere "
            "(try --project or another --client)."
        )
        return

    console.print()
    console.print(
        f"[bold]Your agent carries ~[red]{total:,}[/red] tokens of standing context "
        f"into every turn[/bold] [dim]({label}, model={model})[/dim]\n"
    )

    t = Table(show_header=True, header_style="bold")
    t.add_column("#", justify="right", width=3)
    t.add_column("Category")
    t.add_column("Tokens", justify="right")
    t.add_column("Items", justify="right")
    for i, ct in enumerate(totals, 1):
        t.add_row(str(i), ct.category.display, f"{ct.tokens:,}", str(ct.item_count))
    console.print(t)

    # Rough per-session dollar framing: standing context is re-billed every
    # turn; at cache-read rates when caching works, at input rates when it
    # does not. Show the cache-read (best-case) figure to stay honest.
    price = get_price(model)
    per_50_turns = cache_aware_savings(model, cache_read_tokens_avoided=total * 50)
    console.print(
        f"\n[dim]Over a 50-turn session that is ≥ {total * 50:,} standing-context tokens; "
        f"≈ ${per_50_turns.dollars:.2f} at cache-read rates ({price.label} pricing) — "
        f"more when caching misses.[/dim]"
    )

    for ct in totals:
        items = sorted(
            (i for i in report.items if i.category == ct.category),
            key=lambda i: i.tokens,
            reverse=True,
        )[:top]
        console.print(f"\n[bold]{ct.category.display}[/bold]")
        dt = Table(show_header=False, box=None, pad_edge=False)
        dt.add_column("name", overflow="fold", max_width=48)
        dt.add_column("tokens", justify="right")
        dt.add_column("label", style="dim")
        for item in items:
            dt.add_row(item.name, f"{item.tokens:,}", item.token_label)
        console.print(dt)

    if report.unintrospected_servers:
        console.print(
            f"\n[yellow]Not introspected live:[/yellow] {', '.join(report.unintrospected_servers)} "
            "[dim](config-only estimates)[/dim]"
        )
    for w in report.warnings:
        console.print(f"[yellow]warning:[/yellow] {w}")

    console.print(
        "\n[bold]Next:[/bold] `jettison wrap "
        f"{report.client}` loads tools on demand and compiles instructions — "
        "with verified answer quality.\n"
    )


def _render_reads(r, model: str) -> None:
    """Re-read waste from local transcripts.

    Reported separately from standing context because it is a different
    kind of cost: a wasted read is billed once when it lands and then
    again on every later turn it stays resident, so the honest figure is
    token-turns, not tokens.
    """
    from rich.console import Console

    from jettison.pricing import cache_aware_savings

    console = Console()
    kinds = r.by_kind()
    if not kinds:
        console.print(
            f"\n[bold]Re-read waste[/bold] [dim]({r.sessions} local sessions, "
            f"{r.read_calls:,} reads)[/dim]: [green]none found[/green]\n"
        )
        return

    cost = cache_aware_savings(model, cache_read_tokens_avoided=r.resident_token_turns)
    console.print(
        f"\n[bold]Re-read waste[/bold] [dim]({r.sessions} local sessions, "
        f"{r.read_calls:,} reads, {r.read_tokens:,} tokens read)[/dim]"
    )
    for kind, (count, tokens) in kinds.items():
        console.print(f"  {kind:16} {count:>5} occurrences   {tokens:>10,} tokens")
    console.print(
        f"  [dim]resident cost {r.resident_token_turns:,} token-turns "
        f"≈ ${cost.dollars:.2f} at cache-read rates ({cost.label})[/dim]\n"
    )
