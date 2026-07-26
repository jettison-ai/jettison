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


REAL_PAYLOAD_CONTENT = "\n".join(
    ["import os", "import sys", ""]
    + [f"    filler_{i} = {i}" for i in range(200)]
    + ["def retry_handler(attempt):", "    return attempt * 2"]
)


def test_hook_reads_the_real_claude_code_payload_shape():
    """Regression: the payload nests content under tool_response.file.

    Verified against a live hook. Earlier code read a flat `tool_output`
    field that does not exist, so an entire 101-turn session was measured
    with pruning silently disabled.
    """
    from jettison.hook.runner import read_output

    text, start = read_output({
        "tool_name": "Read",
        "tool_response": {"file": {"content": "a\nb", "startLine": 40}},
    })
    assert text == "a\nb"
    assert start == 40


def test_hook_prunes_a_real_shaped_payload(tmp_path):
    t = tmp_path / "t.jsonl"
    t.write_text(json.dumps({"type": "user", "message": {"content": "fix the retry handler"}}) + "\n")
    out = handle({
        "tool_name": "Read",
        "transcript_path": str(t),
        "tool_response": {"file": {"content": REAL_PAYLOAD_CONTENT, "startLine": 1}},
    })
    assert out is not None
    text = out["hookSpecificOutput"]["updatedToolOutput"]
    assert "retry_handler" in text
    assert "lines elided" in text
    assert len(text) < len(REAL_PAYLOAD_CONTENT)


def test_secrets_are_never_pruned_away(tmp_path):
    content = "\n".join(
        [f"    pad_{i} = {i}" for i in range(150)]
        + ["    api_key = os.environ['SERVICE_API_KEY']"]
        + [f"    pad2_{i} = {i}" for i in range(150)]
    )
    t = tmp_path / "t.jsonl"
    t.write_text(json.dumps({"type": "user", "message": {"content": "fix the retry handler"}}) + "\n")
    out = handle({
        "tool_name": "Read", "transcript_path": str(t),
        "tool_response": {"file": {"content": content, "startLine": 1}},
    })
    if out is not None:
        assert "api_key" in out["hookSpecificOutput"]["updatedToolOutput"]


def test_repo_map_is_compact_and_deterministic(tmp_path):
    """The map rides in the cached prefix, so it must be small and stable."""
    from jettison.optimize.repomap import build, scan

    src = tmp_path / "pkg"
    src.mkdir()
    (src / "a.py").write_text(
        'import os\n\nclass Widget:\n    """A widget."""\n    def render(self, x: int) -> str:\n        return str(x)\n\n'
        "def helper(n: int) -> int:\n    return n * 2\n"
    )
    (src / "b.py").write_text("from a import Widget\n\ndef use() -> None:\n    Widget()\n")
    m1 = build(tmp_path)
    assert build(tmp_path) == m1                 # byte-stable
    assert "class Widget" in m1
    assert "def helper(n: int) -> int" in m1     # signature, not body
    assert "return n * 2" not in m1              # bodies excluded
    assert "A widget." in m1                     # one-line docstring kept
    mods = scan(tmp_path)
    assert any(mod.imported_by > 0 for mod in mods)   # import ranking works


def test_repo_map_injection_is_replaceable(tmp_path):
    from jettison.optimize import add_repo_map, remove_repo_map

    (tmp_path / "m.py").write_text("def f():\n    pass\n")
    (tmp_path / "CLAUDE.md").write_text("# Project\n\nhand-written rules\n")
    add_repo_map(tmp_path)
    add_repo_map(tmp_path)                       # regenerate must replace, not append
    text = (tmp_path / "CLAUDE.md").read_text()
    assert text.count("jettison:repomap") == 2   # one open, one close
    assert "hand-written rules" in text
    assert remove_repo_map(tmp_path) is True
    assert "jettison" not in (tmp_path / "CLAUDE.md").read_text()
    assert "hand-written rules" in (tmp_path / "CLAUDE.md").read_text()


def test_importance_weights_match_repomaster():
    """Ported weighting, not invented. Git churn must dominate."""
    from jettison.optimize.importance import WEIGHTS

    assert WEIGHTS["git_history"] == 4.0
    assert WEIGHTS["imports"] == 3.0
    assert WEIGHTS["usage"] == 2.0
    assert WEIGHTS["git_history"] > WEIGHTS["imports"] > WEIGHTS["usage"]


def test_ranking_demotes_tests_and_promotes_core(tmp_path):
    from jettison.optimize.repomap import scan

    (tmp_path / "core.py").write_text(
        "class Engine:\n    def run(self):\n        if True:\n            for i in range(3):\n                pass\n"
    )
    (tmp_path / "test_core.py").write_text("from core import Engine\n\ndef test_x():\n    assert Engine()\n")
    (tmp_path / "app.py").write_text("from core import Engine\n\ndef main():\n    Engine().run()\n")
    ranked = sorted(scan(tmp_path), key=lambda m: -m.rank)
    assert ranked[0].path == "core.py"
    assert ranked[-1].path.startswith("test_")


def test_git_scoring_degrades_without_git(tmp_path):
    """A non-git directory must score 0 on churn, not explode."""
    from jettison.optimize.importance import git_commit_counts

    assert git_commit_counts(tmp_path) == {}


def test_verbosity_block_is_replaceable(tmp_path):
    from jettison.optimize import verbosity

    (tmp_path / "CLAUDE.md").write_text("# Rules\n\nkeep me\n")
    verbosity.install(tmp_path, "balanced")
    verbosity.install(tmp_path, "terse")          # switching level replaces
    text = (tmp_path / "CLAUDE.md").read_text()
    assert text.count("jettison:verbosity") == 2
    assert "as few words as carry the meaning" in text
    assert "keep me" in text
    assert verbosity.uninstall(tmp_path) is True
    assert "jettison" not in (tmp_path / "CLAUDE.md").read_text()
    assert "keep me" in (tmp_path / "CLAUDE.md").read_text()


# --- content-type routing: the guardrail that stops code being corrupted ---

PY_CODE = "from __future__ import annotations\n\nimport os\n\n\ndef handler(x):\n    return x + 1\n"
LOG_TEXT = (
    "Build started at 10:32. Resolving dependencies from the registry. "
    "Warning: the configuration file was not found in the expected location, "
    "falling back to defaults. Compilation finished with 3 warnings. " * 12
)


def test_python_code_is_classified_as_code():
    from jettison.hook.content_type import classify

    assert classify(PY_CODE) == "code"


def test_numbered_read_output_is_code():
    from jettison.hook.content_type import classify

    assert classify("     1→hello\n     2→world\n") == "code"


def test_read_tool_output_is_always_code_regardless_of_content():
    """A file is a file even if it happens to read like prose."""
    from jettison.hook.content_type import classify

    assert classify("just some english sentences here.", tool_name="Read") == "code"


def test_json_is_detected():
    from jettison.hook.content_type import classify

    assert classify('{"a": 1, "b": [2, 3]}') == "json"


def test_build_log_is_prose():
    from jettison.hook.content_type import classify

    assert classify(LOG_TEXT, tool_name="Bash") == "prose"


def test_prose_compressor_refuses_code():
    """The bug this prevents: Kompress turns
    'from __future__ import annotations' into '__future__ annotations'."""
    from jettison.hook.prose import compress_prose

    r = compress_prose(PY_CODE * 40, tool_name="Bash")
    assert r.compressed is False
    assert "code" in r.reason
    assert r.text == PY_CODE * 40          # returned untouched


def test_prose_compressor_fails_open_without_kompress(monkeypatch):
    import jettison.hook.prose as prose

    monkeypatch.setattr(prose, "_compressor", None)
    monkeypatch.setattr(prose, "_unavailable", True)
    r = prose.compress_prose(LOG_TEXT, tool_name="Bash")
    assert r.compressed is False
    assert r.text == LOG_TEXT


def test_hook_routes_bash_to_prose_not_pruner(monkeypatch):
    """Bash output must never reach the line pruner — it has no line
    numbers, so an elision there would not be recoverable."""
    import jettison.hook.runner as runner
    from jettison.hook.prose import ProseResult

    seen = {}

    def fake_prose(text, tool_name=""):
        seen["tool"] = tool_name
        return ProseResult(text, False, "stub")

    def fail_prune(*a, **k):
        raise AssertionError("Bash output must not reach the line pruner")

    monkeypatch.setattr(runner, "compress_prose", fake_prose)
    monkeypatch.setattr(runner, "prune_read_output", fail_prune)
    runner.handle({"tool_name": "Bash", "tool_response": {"file": {"content": LOG_TEXT}}})
    assert seen["tool"] == "Bash"


def test_optimize_targets_the_right_file_per_client(tmp_path):
    """Repo map and output style are plain markdown, so they work in any
    client that loads project instructions — not just Claude Code."""
    from jettison.optimize import add_repo_map, verbosity
    from jettison.optimize.scout import instruction_path

    (tmp_path / "m.py").write_text("def f():\n    pass\n")
    for client, filename in (
        ("claude", "CLAUDE.md"),
        ("codex", "AGENTS.md"),
        ("cursor", ".cursorrules"),
        ("cline", ".clinerules"),
    ):
        assert instruction_path(tmp_path, client).name == filename
        md, _ = add_repo_map(tmp_path, client=client)
        verbosity.install(tmp_path, client=client)
        assert md.name == filename
        text = md.read_text()
        assert "jettison:repomap" in text and "jettison:verbosity" in text


def test_uninstall_is_client_specific(tmp_path):
    from jettison.optimize import add_repo_map, remove_repo_map

    (tmp_path / "m.py").write_text("def f():\n    pass\n")
    add_repo_map(tmp_path, client="codex")
    assert remove_repo_map(tmp_path, client="claude") is False
    assert remove_repo_map(tmp_path, client="codex") is True
