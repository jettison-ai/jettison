"""Opt-in telemetry tests: the contract in docs/TELEMETRY.md, asserted.

Off by default, no default endpoint, a closed payload vocabulary, and a
send path that can never raise into a request.
"""

from __future__ import annotations

import uuid

import pytest

from jettison import telemetry
from jettison._version import __version__
from jettison.adapters.runner import send_session_telemetry
from jettison.savings import ledger
from jettison.telemetry import client as telemetry_client

FORBIDDEN_SUBSTRINGS = ("prompt", "message", "path", "project", "repo", "tool", "user", "email", "key")


@pytest.fixture(autouse=True)
def workspace(tmp_path, monkeypatch):
    monkeypatch.setenv("JETTISON_WORKSPACE_DIR", str(tmp_path))
    monkeypatch.delenv(telemetry.ENABLE_ENV, raising=False)
    monkeypatch.delenv(telemetry.ENDPOINT_ENV, raising=False)
    return tmp_path


@pytest.fixture
def no_network(monkeypatch):
    """Any attempt to post is a test failure unless the test says otherwise."""
    sent: list[tuple[str, dict]] = []

    def _post(url, payload):
        sent.append((url, payload))

    monkeypatch.setattr(telemetry_client, "_post", _post)
    return sent


def payload() -> dict:
    return telemetry.build_payload(
        install="11111111-2222-3333-4444-555555555555",
        client="openclaw",
        tokens_avoided=9000,
        dollars_avoided=0.1234,
    )


def test_disabled_by_default_even_with_endpoint(no_network, monkeypatch):
    monkeypatch.setenv(telemetry.ENDPOINT_ENV, "http://collector.invalid/t")
    assert not telemetry.is_enabled()
    assert telemetry.maybe_send(payload()) is None
    assert no_network == []


def test_no_network_when_endpoint_unset(no_network, monkeypatch):
    monkeypatch.setenv(telemetry.ENABLE_ENV, "1")
    assert telemetry.is_enabled()
    assert telemetry.maybe_send(payload()) is None
    assert no_network == []


def test_payload_carries_only_disclosed_fields():
    p = payload()
    assert set(p) == set(telemetry.PAYLOAD_FIELDS)
    assert p == {
        "v": 1,
        "install_id": "11111111-2222-3333-4444-555555555555",
        "client": "openclaw",
        "jettison_version": __version__,
        "tokens_avoided": 9000,
        "dollars_avoided": 0.1234,
        "dollars_label": "estimated",
    }
    # No key or value smells like content, identity or filesystem.
    for key, value in p.items():
        if key in ("install_id", "v", "jettison_version", "client"):
            continue
        assert not isinstance(value, str) or "/" not in value
    for field in telemetry.PAYLOAD_FIELDS:
        if field == "install_id":
            continue
        assert not any(bad in field for bad in FORBIDDEN_SUBSTRINGS)


def test_payload_is_pure_and_deterministic():
    assert payload() == payload()


def test_unknown_client_label_collapses_to_other():
    p = telemetry.build_payload(
        install="i", client="/Users/someone/bin/my-secret-agent", tokens_avoided=1, dollars_avoided=0.0
    )
    assert p["client"] == "other"


def test_undisclosed_field_fails_closed(no_network, monkeypatch):
    monkeypatch.setenv(telemetry.ENABLE_ENV, "1")
    monkeypatch.setenv(telemetry.ENDPOINT_ENV, "http://collector.invalid/t")
    assert telemetry.maybe_send({**payload(), "prompt": "hello"}) is None
    assert no_network == []


def test_install_id_is_random_persisted_and_stable(workspace):
    first = telemetry.install_id()
    uuid.UUID(first)  # a real random UUID, not derived from the machine
    assert telemetry.install_id() == first
    assert telemetry.install_id_path().read_text().strip() == first
    assert first not in str(workspace)


def test_install_id_differs_per_install(monkeypatch, tmp_path):
    monkeypatch.setenv("JETTISON_WORKSPACE_DIR", str(tmp_path / "a"))
    a = telemetry.install_id()
    monkeypatch.setenv("JETTISON_WORKSPACE_DIR", str(tmp_path / "b"))
    assert telemetry.install_id() != a


def test_send_posts_exactly_the_payload(no_network, monkeypatch):
    monkeypatch.setenv(telemetry.ENABLE_ENV, "1")
    monkeypatch.setenv(telemetry.ENDPOINT_ENV, "http://collector.invalid/t")
    thread = telemetry.maybe_send(payload())
    assert thread is not None
    thread.join(timeout=5)
    assert no_network == [("http://collector.invalid/t", payload())]


def test_send_never_propagates_exceptions(monkeypatch):
    monkeypatch.setenv(telemetry.ENABLE_ENV, "1")
    monkeypatch.setenv(telemetry.ENDPOINT_ENV, "http://collector.invalid/t")

    def boom(url, json, timeout):
        raise RuntimeError("collector on fire")

    import httpx

    monkeypatch.setattr(httpx, "post", boom)
    thread = telemetry.maybe_send(payload())
    assert thread is not None
    thread.join(timeout=5)
    assert not thread.is_alive()


def test_disclosure_notice_states_the_contract():
    text = telemetry.disclosure_notice()
    assert telemetry.ENABLE_ENV in text
    assert "docs/TELEMETRY.md" in text
    assert "install id" in text


def test_wrap_session_sends_one_aggregate_delta(no_network, monkeypatch):
    monkeypatch.setenv(telemetry.ENABLE_ENV, "1")
    monkeypatch.setenv(telemetry.ENDPOINT_ENV, "http://collector.invalid/t")
    ledger.record_event(tokens_before=5_000, tokens_after=1_000, model="claude-sonnet-4-5", client="openclaw")
    baseline = ledger.aggregate()
    ledger.record_event(tokens_before=20_000, tokens_after=5_000, model="claude-sonnet-4-5", client="openclaw")

    send_session_telemetry("openclaw", baseline)
    assert len(no_network) == 1
    _, sent = no_network[0]
    assert sent["tokens_avoided"] == 15_000  # this session only, not lifetime
    assert sent["client"] == "openclaw"
    assert sent["dollars_avoided"] > 0


def test_wrap_session_sends_nothing_when_disabled(no_network):
    ledger.record_event(tokens_before=5_000, tokens_after=1_000, model="claude-sonnet-4-5")
    send_session_telemetry("openclaw", ledger.Aggregate())
    assert no_network == []
