"""`jettison wrap <client>` — optimize + run an agent client."""

from __future__ import annotations

import click

from jettison.cli import main


@main.command("wrap", context_settings={"ignore_unknown_options": True})
@click.argument("client")
@click.argument("extra_args", nargs=-1, type=click.UNPROCESSED)
@click.option("--port", default=8977, show_default=True, help="Jettison proxy port.")
@click.option("--upstream", default=None, help="Upstream base URL (default: auto-started Headroom proxy, else provider).")
@click.option("--no-headroom", is_flag=True, help="Skip Headroom runtime compression; standing-context optimization only.")
@click.option("--profile", default="balanced", show_default=True, help="Optimization profile (max-savings, balanced, max-quality).")
def wrap_cmd(client: str, extra_args: tuple[str, ...], port: int, upstream: str | None, no_headroom: bool, profile: str) -> None:
    """Optimize + run an agent client (claude, codex, cursor, cline, opencode, openclaw).

    \b
    Examples:
      jettison wrap claude
      jettison wrap openclaw --profile max-savings
    """
    from jettison.adapters import run_wrap

    run_wrap(
        client=client,
        extra_args=list(extra_args),
        port=port,
        upstream=upstream,
        use_headroom=not no_headroom,
        profile=profile,
    )


@main.command("unwrap")
@click.argument("client")
def unwrap_cmd(client: str) -> None:
    """Undo `jettison wrap` for a client."""
    from jettison.adapters import run_unwrap

    run_unwrap(client=client)
