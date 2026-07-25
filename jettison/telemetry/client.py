"""Opt-in telemetry — exactly what docs/TELEMETRY.md promises, nothing more.

That page is the binding contract, so this module is written as a closed
vocabulary: ``PAYLOAD_FIELDS`` is the entire set of keys that can leave
the machine, ``build_payload`` is pure so the exact bytes are assertable
without a network, and ``maybe_send`` refuses any payload carrying a key
outside the set. Prompts, paths, tool names, project names and user
identifiers have no code path in here — there is nothing to redact
because nothing is ever read.

Two independent switches, both off by default:
- ``JETTISON_TELEMETRY=1`` turns collection on;
- ``JETTISON_TELEMETRY_ENDPOINT`` names the collector. There is
  deliberately no default endpoint, so flipping the flag without
  configuring a destination still sends nothing.

Sending happens on a daemon thread with a short timeout and swallows
every exception. Telemetry may never slow, block or break a request —
the local ledger (`jettison savings`) is the real reporting surface and
telemetry is a strictly worse copy of it.
"""

from __future__ import annotations

import logging
import os
import threading
import uuid
from pathlib import Path
from typing import Any

from jettison._version import __version__

logger = logging.getLogger(__name__)

ENABLE_ENV = "JETTISON_TELEMETRY"
ENDPOINT_ENV = "JETTISON_TELEMETRY_ENDPOINT"

SCHEMA_VERSION = 1
SEND_TIMEOUT_S = 3.0

PAYLOAD_FIELDS = frozenset(
    {
        "v",
        "install_id",
        "client",
        "jettison_version",
        "tokens_avoided",
        "dollars_avoided",
        "dollars_label",
    }
)

# The client label reaches us from wrap config; the contract promises a
# client *type*, so anything unrecognized collapses to "other" rather
# than travelling as a free-form string. Listed here rather than imported
# from jettison.adapters: that package imports the runner, which imports
# this module.
KNOWN_CLIENTS = frozenset({"claude", "cline", "codex", "cursor", "opencode", "openclaw"})


def is_enabled() -> bool:
    return os.environ.get(ENABLE_ENV, "").strip() == "1"


def endpoint() -> str:
    return os.environ.get(ENDPOINT_ENV, "").strip()


def install_id_path() -> Path:
    root = Path(os.environ.get("JETTISON_WORKSPACE_DIR", Path.home() / ".jettison"))
    return root / "install_id"


def install_id() -> str:
    """A random UUID, generated once and persisted.

    Never derived from hostname, username, MAC, project path or anything
    else about the machine — it is a counter, not an identity. Generation
    is the one place randomness is allowed: it happens once, off the
    request path, and never influences request bytes.
    """
    path = install_id_path()
    try:
        existing = path.read_text().strip()
        if existing:
            return existing
    except OSError:
        pass
    fresh = str(uuid.uuid4())
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(fresh + "\n")
    except OSError:
        pass
    return fresh


def build_payload(
    *,
    install: str,
    client: str,
    tokens_avoided: int,
    dollars_avoided: float,
    dollars_label: str = "estimated",
) -> dict[str, Any]:
    """The exact dict that would be sent. Pure: no I/O, no clock, no RNG.

    ``dollars_label`` carries the measured/estimated composition the
    contract requires published aggregates to state; it describes the
    price table, not the user.
    """
    return {
        "v": SCHEMA_VERSION,
        "install_id": install,
        "client": client if client in KNOWN_CLIENTS else "other",
        "jettison_version": __version__,
        "tokens_avoided": max(0, int(tokens_avoided)),
        "dollars_avoided": round(max(0.0, float(dollars_avoided)), 4),
        "dollars_label": dollars_label if dollars_label in ("measured", "estimated") else "estimated",
    }


def maybe_send(payload: dict[str, Any]) -> threading.Thread | None:
    """Post `payload` on a background daemon thread.

    Returns the thread so callers (and tests) can join deterministically;
    ``None`` means nothing was sent — telemetry disabled, no endpoint
    configured, or a payload carrying a field outside ``PAYLOAD_FIELDS``
    (fail closed: an unknown key is a contract violation, not a warning).
    """
    if not is_enabled():
        return None
    url = endpoint()
    if not url:
        return None
    unknown = set(payload) - PAYLOAD_FIELDS
    if unknown:
        logger.debug("telemetry payload carried undisclosed fields %s; not sending", sorted(unknown))
        return None
    thread = threading.Thread(
        target=_post, args=(url, dict(payload)), daemon=True, name="jettison-telemetry"
    )
    thread.start()
    return thread


def _post(url: str, payload: dict[str, Any]) -> None:
    try:
        import httpx

        httpx.post(url, json=payload, timeout=SEND_TIMEOUT_S)
    except Exception:  # a telemetry failure is never the user's problem
        logger.debug("telemetry send failed", exc_info=True)


def disclosure_notice() -> str:
    """First-run disclosure text, printed when telemetry is switched on."""
    return (
        "telemetry: ON (JETTISON_TELEMETRY=1) — one aggregate report per session:\n"
        "  anonymous install id, tokens avoided, estimated dollars avoided,\n"
        "  client type, jettison version. Never prompts, paths, tool names or\n"
        "  identifiers. Unset JETTISON_TELEMETRY to turn it off; full contract\n"
        "  in docs/TELEMETRY.md. Everything reported is already local: "
        "`jettison savings`."
    )
