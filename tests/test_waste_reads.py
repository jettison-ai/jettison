"""Read-waste detector tests."""

from __future__ import annotations

import json

from jettison.waste import analyze_session


def transcript(tmp_path, records):
    p = tmp_path / "session.jsonl"
    p.write_text("\n".join(json.dumps(r) for r in records))
    return p


def assistant_read(call_id, path):
    return {
        "type": "assistant",
        "message": {"content": [{"type": "tool_use", "id": call_id, "name": "Read",
                                 "input": {"file_path": path}}]},
    }


def result(call_id, text):
    return {
        "type": "user",
        "message": {"content": [{"type": "tool_result", "tool_use_id": call_id, "content": text}]},
    }


BODY = "def frobnicate():\n    return 42\n" * 40


def test_exact_repeat_is_waste(tmp_path):
    p = transcript(tmp_path, [
        assistant_read("a", "/src/x.py"), result("a", BODY),
        assistant_read("b", "/src/x.py"), result("b", BODY),
    ])
    items, calls, tokens, resident = analyze_session(p)
    assert calls == 2
    assert [i.kind for i in items] == ["exact_repeat"]
    assert items[0].tokens > 0


def test_changed_file_reread_is_not_waste(tmp_path):
    """A re-read after the file legitimately changed is correct behavior."""
    p = transcript(tmp_path, [
        assistant_read("a", "/src/x.py"), result("a", BODY),
        assistant_read("b", "/src/x.py"), result("b", BODY.replace("42", "43")),
    ])
    items, _, _, _ = analyze_session(p)
    assert items == []


def test_superset_read_flags_the_dead_earlier_copy(tmp_path):
    p = transcript(tmp_path, [
        assistant_read("a", "/src/x.py"), result("a", BODY),
        assistant_read("b", "/src/x.py"), result("b", BODY + "\n# more content appended\n" * 20),
    ])
    items, _, _, _ = analyze_session(p)
    assert [i.kind for i in items] == ["superset"]


def test_write_readback_detected(tmp_path):
    p = transcript(tmp_path, [
        {"type": "assistant", "message": {"content": [
            {"type": "tool_use", "id": "w", "name": "Write", "input": {"file_path": "/src/new.py"}}]}},
        result("w", "ok"),
        assistant_read("r", "/src/new.py"), result("r", BODY),
    ])
    items, _, _, _ = analyze_session(p)
    assert [i.kind for i in items] == ["write_readback"]


def test_resident_cost_counts_remaining_turns(tmp_path):
    """Waste is re-billed every later turn, so cost scales with turns left."""
    records = [assistant_read("a", "/src/x.py"), result("a", BODY),
               assistant_read("b", "/src/x.py"), result("b", BODY)]
    records += [{"type": "assistant", "message": {"content": [{"type": "text", "text": "..."}]}}] * 5
    p = transcript(tmp_path, records)
    items, _, _, resident = analyze_session(p)
    assert resident > items[0].tokens  # multiplied by remaining turns


def test_empty_transcript_is_safe(tmp_path):
    p = transcript(tmp_path, [{"type": "system", "message": {}}])
    assert analyze_session(p) == ([], 0, 0, 0)
