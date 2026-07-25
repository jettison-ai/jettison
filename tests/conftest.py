"""Shared fixtures.

The demo project's `.mcp.json` has to name the fake MCP server by a path
the OS can actually exec. A path committed to the repo can't do that on
every machine, so the checked-in config carries a repo-relative path
(correct when the CLI is run from the repo root, which is how the docs
and CI invoke it) and this fixture materializes a copy with the path
resolved for the running checkout — so the tests pass from any working
directory and on any runner.
"""

from __future__ import annotations

import json
import shutil
from pathlib import Path

import pytest

FIXTURES = Path(__file__).parent / "fixtures"
FAKE_SERVER = FIXTURES / "fake_mcp_server.py"


@pytest.fixture
def demo_project(tmp_path: Path) -> Path:
    project = tmp_path / "demo_project"
    shutil.copytree(FIXTURES / "demo_project", project)
    config_path = project / ".mcp.json"
    config = json.loads(config_path.read_text())
    for server in config["mcpServers"].values():
        server["args"] = [str(FAKE_SERVER.resolve())]
    config_path.write_text(json.dumps(config, indent=2))
    return project
