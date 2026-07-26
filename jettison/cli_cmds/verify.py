"""`jettison verify` — measure Jettison on the user's own machine.

Every tool in this space publishes a savings number that does not survive
contact with a real workload. Ours is measured rather than modelled, but it
is still *our* number on *our* repository, and a developer has no reason to
take it on faith.

So the product ships the experiment. `jettison verify` runs the same paired
A/B we use internally — identical prompts, one arm plain, one arm
optimized, alternating order so neither benefits from provider caching —
against whatever repository the user points it at, and reports what
actually happened to their bill.

If it comes out negative on their workload, it says so.
"""

from __future__ import annotations

import json
import shutil
import subprocess
import time
from dataclasses import dataclass
from pathlib import Path

import click

from jettison.cli import main

DEFAULT_TASKS = [
    "Explain how the main entry point of this project works. Name the files and functions involved.",
    "Find where errors are raised or handled in this codebase and summarise the pattern used.",
    "Describe the module with the most dependents and what it is responsible for.",
]


@dataclass
class Run:
    cost: float
    turns: int
    seconds: float
    input_tokens: int
    output_tokens: int
    error: bool


def _usage(payload: dict) -> Run:
    """Session totals from modelUsage.

    The top-level `usage` block reports only the final request while
    `total_cost_usd` covers the session; mixing them silently corrupts the
    comparison (docs/FINDINGS.md §27).
    """
    mu = payload.get("modelUsage") or {}
    cr = cw = fi = out = 0
    for stats in mu.values():
        if isinstance(stats, dict):
            cr += stats.get("cacheReadInputTokens", 0) or 0
            cw += stats.get("cacheCreationInputTokens", 0) or 0
            fi += stats.get("inputTokens", 0) or 0
            out += stats.get("outputTokens", 0) or 0
    return Run(
        cost=payload.get("total_cost_usd", 0.0) or 0.0,
        turns=payload.get("num_turns", 0) or 0,
        seconds=(payload.get("duration_ms", 0) or 0) / 1000,
        input_tokens=cr + cw + fi,
        output_tokens=out,
        error=bool(payload.get("is_error")),
    )


def _run_claude(prompt: str, cwd: Path, model: str) -> Run | None:
    try:
        proc = subprocess.run(
            ["claude", "-p", prompt, "--output-format", "json",
             "--dangerously-skip-permissions", "--model", model],
            cwd=cwd, capture_output=True, text=True, timeout=900, check=False,
        )
        return _usage(json.loads(proc.stdout, strict=False))
    except Exception:
        return None


@main.command("verify")
@click.option("--project", type=click.Path(exists=True, file_okay=False, path_type=Path), default=None)
@click.option("--model", default="sonnet", show_default=True)
@click.option("--tasks", type=int, default=3, show_default=True, help="Task pairs to run.")
def verify_cmd(project: Path | None, model: str, tasks: int) -> None:
    """Run a paired A/B on your own repo and report the real difference.

    \b
    Runs each task twice — once plain, once optimized — alternating which
    goes first. Uses your Claude Code quota. Nothing is written to your
    repository beyond what `jettison optimize` installs, and that is
    removed again at the end.
    """
    from rich.console import Console

    from jettison.optimize import add_repo_map, remove_repo_map, verbosity

    console = Console()
    root = (project or Path.cwd()).resolve()
    if shutil.which("claude") is None:
        raise click.ClickException("`claude` not found on PATH — verify needs Claude Code installed.")

    console.print(
        f"\n[bold]Verifying Jettison on {root.name}[/bold]  "
        f"[dim]{tasks} task pairs, {tasks * 2} agent runs[/dim]\n"
        "[dim]This spends your Claude Code quota. Ctrl-C to stop.[/dim]\n"
    )

    had_map = (root / "CLAUDE.md").exists()
    results: list[tuple[Run, Run]] = []

    for i, prompt in enumerate(DEFAULT_TASKS[:tasks]):
        console.print(f"[dim]task {i + 1}/{tasks}…[/dim]")
        remove_repo_map(root)
        verbosity.uninstall(root)
        plain_first = i % 2 == 0

        def optimized() -> Run | None:
            add_repo_map(root)
            verbosity.install(root)
            return _run_claude(prompt, root, model)

        def plain() -> Run | None:
            remove_repo_map(root)
            verbosity.uninstall(root)
            return _run_claude(prompt, root, model)

        a, b = (plain(), optimized()) if plain_first else ((lambda o: (plain(), o))(optimized())[::-1])
        if a and b and not a.error and not b.error:
            results.append((a, b))

    remove_repo_map(root)
    verbosity.uninstall(root)
    if not had_map and (root / "CLAUDE.md").exists() and not (root / "CLAUDE.md").read_text().strip():
        (root / "CLAUDE.md").unlink()

    if not results:
        console.print("[yellow]No task pair completed cleanly — nothing to report.[/yellow]")
        return

    d_cost = sum(r[0].cost for r in results)
    j_cost = sum(r[1].cost for r in results)
    d_turns = sum(r[0].turns for r in results)
    j_turns = sum(r[1].turns for r in results)
    saved = (d_cost - j_cost) / d_cost * 100 if d_cost else 0.0

    console.print(f"\n[bold]Result on {root.name}[/bold]  [dim]n={len(results)} pairs[/dim]")
    console.print(f"  without jettison  ${d_cost:.4f}   {d_turns} turns")
    console.print(f"  with jettison     ${j_cost:.4f}   {j_turns} turns")
    colour = "green" if saved > 0 else "red"
    console.print(f"  [{colour}]{'saved' if saved > 0 else 'cost extra'}: {abs(saved):.1f}%[/{colour}]\n")

    if saved <= 0:
        console.print(
            "[yellow]Jettison did not help on this workload.[/yellow] That is a real\n"
            "result, not a misconfiguration — savings concentrate in exploration and\n"
            "comprehension work. Please report it: it is more useful to us than a win.\n"
        )
    elif len(results) < 5:
        console.print(
            "[dim]Small sample: a few pairs cannot separate a real effect from the\n"
            "agent's own run-to-run variance. Re-run with --tasks for more confidence.[/dim]\n"
        )
