"""Client-side install/uninstall must be surgical and reversible."""

from __future__ import annotations

import json

from jettison.hook.prune import prune_read_output
from jettison.hook.runner import handle
from jettison.optimize import (
    add_delegation_rule,
    install_hook,
    install_scout,
    is_installed,
    remove_delegation_rule,
    uninstall_hook,
    uninstall_scout,
)

CODE = "\n".join(
    [f"{i:6}→    value_{i} = compute({i})" for i in range(1, 300)]
    + [f"{i:6}→def handle_retry(attempt):" for i in (300,)]
    + [f"{i:6}→    return attempt * 2" for i in (301,)]
)


def test_scout_install_and_remove(tmp_path):
    p = install_scout(tmp_path)
    assert p.exists() and "jettison-scout" in p.read_text()
    assert "model: haiku" in p.read_text()      # exploration must be cheap
    assert uninstall_scout(tmp_path) is True


def test_delegation_rule_is_fenced_and_idempotent(tmp_path):
    (tmp_path / "CLAUDE.md").write_text("# Project\n\nexisting rules\n")
    add_delegation_rule(tmp_path)
    add_delegation_rule(tmp_path)               # twice must not duplicate
    text = (tmp_path / "CLAUDE.md").read_text()
    assert text.count("jettison:scout") == 2    # open + close marker only
    assert "existing rules" in text
    assert remove_delegation_rule(tmp_path) is True
    assert "jettison" not in (tmp_path / "CLAUDE.md").read_text()
    assert "existing rules" in (tmp_path / "CLAUDE.md").read_text()


def test_hook_install_preserves_foreign_settings(tmp_path):
    s = tmp_path / ".claude" / "settings.local.json"
    s.parent.mkdir(parents=True)
    s.write_text(json.dumps({
        "env": {"FOO": "bar"},
        "hooks": {"PostToolUse": [
            {"matcher": "Bash", "hooks": [{"type": "command", "command": "someone-elses-tool"}]}
        ]},
    }))
    install_hook(tmp_path)
    data = json.loads(s.read_text())
    assert data["env"] == {"FOO": "bar"}                       # untouched
    cmds = json.dumps(data["hooks"]["PostToolUse"])
    assert "someone-elses-tool" in cmds and "jettison" in cmds
    assert is_installed(tmp_path)
    assert uninstall_hook(tmp_path) is True
    left = json.dumps(json.loads(s.read_text()))
    assert "someone-elses-tool" in left and "jettison" not in left


def test_hook_refuses_to_clobber_invalid_json(tmp_path):
    s = tmp_path / ".claude" / "settings.local.json"
    s.parent.mkdir(parents=True)
    s.write_text("{ not json")
    try:
        install_hook(tmp_path)
    except RuntimeError as e:
        assert "refusing" in str(e)
    else:
        raise AssertionError("must refuse to overwrite unparseable settings")


def test_prune_keeps_structure_and_marks_gaps():
    r = prune_read_output(CODE, query="fix the retry logic")
    assert r.pruned
    assert "handle_retry" in r.text                    # query-relevant kept
    assert "lines elided" in r.text                    # gap is explicit
    assert "re-read this range" in r.text              # recoverable
    assert r.lines_after < r.lines_before


def test_prune_leaves_small_files_alone():
    small = "\n".join(f"{i:6}→line {i}" for i in range(1, 20))
    assert prune_read_output(small, query="anything").pruned is False


def test_hook_ignores_non_read_tools():
    assert handle({"tool_name": "Bash", "tool_output": CODE}) is None


def test_hook_emits_correct_schema(tmp_path):
    t = tmp_path / "t.jsonl"
    t.write_text(json.dumps({"type": "user", "message": {"content": "fix the retry logic"}}) + "\n")
    out = handle({"tool_name": "Read", "tool_output": CODE, "transcript_path": str(t)})
    assert out is not None
    spec = out["hookSpecificOutput"]
    assert spec["hookEventName"] == "PostToolUse"
    assert len(spec["updatedToolOutput"]) < len(CODE)
