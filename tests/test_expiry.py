"""Expired-context elision: only provably dead content is removed."""

from __future__ import annotations

from jettison.horizon.expiry import ExpiryElider

BIG = "def handler(x):\n    return x + 1\n" * 400   # well over the floor


def convo(blocks):
    return {"messages": blocks}


def read_call(cid, path):
    return {"role": "assistant", "content": [
        {"type": "tool_use", "id": cid, "name": "Read", "input": {"file_path": path}}]}


def write_call(cid, path):
    return {"role": "assistant", "content": [
        {"type": "tool_use", "id": cid, "name": "Edit", "input": {"file_path": path}}]}


def result(cid, text):
    return {"role": "user", "content": [
        {"type": "tool_result", "tool_use_id": cid, "content": text}]}


def test_read_superseded_by_later_edit_is_elided():
    """After the agent edits a file, its earlier view is stale — using it
    would be a bug, so removing it cannot cost a re-fetch."""
    body = convo([
        read_call("r1", "/src/a.py"), result("r1", BIG),
        write_call("w1", "/src/a.py"), result("w1", "ok"),
    ])
    s = ExpiryElider().elide(body, "anthropic", expected_turns=60)
    assert s.superseded == 1
    assert "removed" in body["messages"][1]["content"][0]["content"]
    assert s.tokens_freed > 1000


def test_read_with_no_later_edit_is_untouched():
    """Live working memory must never be removed — that is what made
    size-based shaping backfire."""
    body = convo([read_call("r1", "/src/a.py"), result("r1", BIG)])
    s = ExpiryElider().elide(body, "anthropic", expected_turns=60)
    assert s.elided == 0
    assert body["messages"][1]["content"][0]["content"] == BIG


def test_edit_before_read_does_not_expire_the_read():
    """Only a write AFTER the read supersedes it."""
    body = convo([
        write_call("w1", "/src/a.py"), result("w1", "ok"),
        read_call("r1", "/src/a.py"), result("r1", BIG),
    ])
    s = ExpiryElider().elide(body, "anthropic", expected_turns=60)
    assert s.elided == 0


def test_duplicate_read_is_elided_but_first_copy_kept():
    body = convo([
        read_call("r1", "/src/a.py"), result("r1", BIG),
        read_call("r2", "/src/a.py"), result("r2", BIG),
    ])
    s = ExpiryElider().elide(body, "anthropic", expected_turns=60)
    assert s.duplicates == 1
    assert body["messages"][1]["content"][0]["content"] == BIG          # first kept
    assert body["messages"][3]["content"][0]["content"] != BIG          # copy removed


def test_break_even_gate_blocks_short_horizons():
    """Re-caching costs ~12.5x a read, so a late elision must not happen."""
    body = convo([
        read_call("r1", "/src/a.py"), result("r1", BIG),
        write_call("w1", "/src/a.py"), result("w1", "ok"),
    ])
    s = ExpiryElider().elide(body, "anthropic", expected_turns=2)
    assert s.elided == 0
    assert s.skipped_break_even == 1


def test_small_reads_are_never_worth_it():
    body = convo([
        read_call("r1", "/a"), result("r1", "tiny"),
        write_call("w1", "/a"), result("w1", "ok"),
    ])
    assert ExpiryElider().elide(body, "anthropic", expected_turns=60).elided == 0


def test_decision_is_sticky_so_bytes_stop_changing():
    """Cache safety: once elided, the same turn must render identically."""
    e = ExpiryElider()
    b1 = convo([read_call("r1", "/a.py"), result("r1", BIG),
                write_call("w1", "/a.py"), result("w1", "ok")])
    e.elide(b1, "anthropic", expected_turns=60)
    first = b1["messages"][1]["content"][0]["content"]
    # client replays originals; horizon is now short enough to fail the gate
    b2 = convo([read_call("r1", "/a.py"), result("r1", BIG),
                write_call("w1", "/a.py"), result("w1", "ok")])
    e.elide(b2, "anthropic", expected_turns=1)
    assert b2["messages"][1]["content"][0]["content"] == first
