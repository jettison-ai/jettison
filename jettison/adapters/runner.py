"""Wrap runtime: start (optional) Headroom proxy -> Jettison proxy -> client.

Chain: client -> jettison (standing context, meta-tools, verifier)
              -> headroom proxy (runtime compression)  [if installed]
              -> provider
"""

from __future__ import annotations

import atexit
import shutil
import subprocess
import threading
import time
from pathlib import Path

import click

from jettison import telemetry
from jettison.adapters.clients import ADAPTERS
from jettison.savings import ledger

HEADROOM_PORT = 8787
DEFAULT_ANTHROPIC = "https://api.anthropic.com"
DEFAULT_OPENAI = "https://api.openai.com"


def _start_headroom(port: int) -> subprocess.Popen | None:
    if shutil.which("headroom") is None:
        return None
    try:
        proc = subprocess.Popen(
            ["headroom", "proxy", "--port", str(port), "--mode", "cache"],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
    except OSError:
        return None
    atexit.register(proc.terminate)
    time.sleep(1.5)  # give it a beat to bind
    if proc.poll() is not None:
        return None
    return proc


def _discover_skills(client: str, project_dir: Path):
    from jettison.compiler import summarize_skill
    from jettison.scanner import instructions as instr_mod

    discoverer = instr_mod.DISCOVERERS.get(client)
    if not discoverer:
        return []
    return [
        summarize_skill(f.name.split(":")[-1], f.text)
        for f in discoverer(project_dir)
        if f.kind == "skill"
    ]


def send_session_telemetry(client: str, baseline: ledger.Aggregate) -> None:
    """One aggregate report per wrap session, opt-in only (docs/TELEMETRY.md).

    The whole report is the ledger delta between wrap start and shutdown:
    there is no per-request telemetry path, so nothing about individual
    requests exists to leak. The join is bounded because a daemon thread
    would otherwise be killed by interpreter exit before it sends.
    """
    if not telemetry.is_enabled():
        return
    after = ledger.aggregate()
    tokens = after.tokens_saved - baseline.tokens_saved
    if tokens <= 0:
        return
    thread = telemetry.maybe_send(
        telemetry.build_payload(
            install=telemetry.install_id(),
            client=client,
            tokens_avoided=tokens,
            dollars_avoided=after.cost_usd - baseline.cost_usd,
        )
    )
    if thread is not None:
        thread.join(timeout=telemetry.SEND_TIMEOUT_S)


def run_wrap(
    client: str,
    extra_args: list[str],
    port: int,
    upstream: str | None,
    use_headroom: bool,
    profile: str,
) -> None:
    adapter = ADAPTERS.get(client)
    if adapter is None:
        raise click.ClickException(f"unknown client {client!r}. Supported: {', '.join(sorted(ADAPTERS))}")
    if not adapter.available():
        raise click.ClickException(f"'{adapter.binary}' not found on PATH — is {client} installed?")

    from jettison.proxy.server import JettisonProxyConfig, create_app

    headroom_proc = None
    if upstream:
        anthropic_up = openai_up = upstream
    elif use_headroom:
        headroom_proc = _start_headroom(HEADROOM_PORT)
        if headroom_proc is not None:
            anthropic_up = openai_up = f"http://127.0.0.1:{HEADROOM_PORT}"
            click.echo(f"headroom proxy (runtime compression) on :{HEADROOM_PORT}")
        else:
            anthropic_up, openai_up = DEFAULT_ANTHROPIC, DEFAULT_OPENAI
            click.echo("headroom not found — running without runtime compression")
    else:
        anthropic_up, openai_up = DEFAULT_ANTHROPIC, DEFAULT_OPENAI

    config = JettisonProxyConfig(
        anthropic_upstream=anthropic_up,
        openai_upstream=openai_up,
        client_label=client,
        optimize_system=(profile != "max-quality"),
        min_tools_to_optimize=3 if profile == "max-savings" else 5,
        skills=_discover_skills(client, Path.cwd()),
        # Only OpenClaw is known to send cache-warming heartbeats; other
        # clients would only inherit the misfire risk.
        heartbeat_profile=(client == "openclaw"),
    )

    if telemetry.is_enabled():
        click.echo(telemetry.disclosure_notice())
    telemetry_baseline = ledger.aggregate()

    import uvicorn

    server = uvicorn.Server(
        uvicorn.Config(create_app(config), host="127.0.0.1", port=port, log_level="warning")
    )
    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()
    deadline = time.time() + 10
    while not server.started and time.time() < deadline:
        time.sleep(0.05)
    if not server.started:
        raise click.ClickException("jettison proxy failed to start")

    proxy_url = f"http://127.0.0.1:{port}"
    click.echo(f"jettison proxy (standing context + verifier) on :{port}")

    try:
        if adapter.binary is not None:
            code = adapter.launch(proxy_url, extra_args)
            raise SystemExit(code)
        adapter.print_setup(proxy_url)
        while True:
            time.sleep(3600)
    except KeyboardInterrupt:
        pass
    finally:
        server.should_exit = True
        if headroom_proc is not None:
            headroom_proc.terminate()
        send_session_telemetry(client, telemetry_baseline)


def run_unwrap(client: str) -> None:
    adapter = ADAPTERS.get(client)
    if adapter is None:
        raise click.ClickException(f"unknown client {client!r}")
    # Jettison wrap is process-scoped (env vars die with the process); the
    # only durable thing to undo is a headroom wrap the user may also have.
    click.echo(
        f"jettison wrap for {client} is process-scoped — nothing durable to undo.\n"
        f"If you also ran `headroom wrap {client}`, undo it with `headroom unwrap {client}`."
    )
