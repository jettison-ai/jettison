#!/usr/bin/env python3
"""Minimal MCP stdio server used by tests and demos.

Serves a configurable number of tools (JETTISON_FAKE_TOOLS, default 12)
with deliberately verbose schemas, mimicking real-world MCP servers.
"""

import json
import os
import sys

N_TOOLS = int(os.environ.get("JETTISON_FAKE_TOOLS", "12"))

LONG_DESC = (
    "This tool allows you to perform the operation described by its name. "
    "It should be used whenever the user asks for anything related to this "
    "functionality. Please note that this tool may take some time to execute "
    "depending on the size of the input. Always check the result for errors "
    "before proceeding. Example usage: call this tool with the appropriate "
    "arguments as described in the schema below. "
)


def make_tool(i: int) -> dict:
    return {
        "name": f"demo_operation_{i}",
        "description": LONG_DESC * 2 + f"This is operation number {i}.",
        "inputSchema": {
            "$schema": "http://json-schema.org/draft-07/schema#",
            "type": "object",
            "title": f"DemoOperation{i}Input",
            "properties": {
                "query": {
                    "type": "string",
                    "title": "Query",
                    "description": "The query string to use for this operation. This should be a plain-text description of what you want to do.",
                },
                "max_results": {
                    "type": "integer",
                    "title": "Max Results",
                    "description": "The maximum number of results to return from this operation. Defaults to 10 if not specified.",
                    "default": 10,
                    "minimum": 1,
                    "maximum": 100,
                },
                "filters": {
                    "type": "object",
                    "title": "Filters",
                    "description": "Optional filters to apply to the results of this operation.",
                    "properties": {
                        "created_after": {
                            "type": "string",
                            "format": "date-time",
                            "description": "Only include results created after this ISO-8601 timestamp.",
                        },
                        "created_before": {
                            "type": "string",
                            "format": "date-time",
                            "description": "Only include results created before this ISO-8601 timestamp.",
                        },
                        "tags": {
                            "type": "array",
                            "items": {"type": "string"},
                            "description": "Only include results carrying every one of these tags.",
                        },
                    },
                },
            },
            "required": ["query"],
        },
    }


TOOLS = [make_tool(i) for i in range(N_TOOLS)]


def main() -> None:
    for line in sys.stdin:
        line = line.strip()
        if not line:
            continue
        try:
            msg = json.loads(line)
        except json.JSONDecodeError:
            continue
        method = msg.get("method")
        msg_id = msg.get("id")
        if method == "initialize":
            reply = {
                "jsonrpc": "2.0",
                "id": msg_id,
                "result": {
                    "protocolVersion": msg.get("params", {}).get("protocolVersion", "2025-06-18"),
                    "capabilities": {"tools": {}},
                    "serverInfo": {"name": "fake-mcp", "version": "1.0.0"},
                },
            }
        elif method == "tools/list":
            reply = {"jsonrpc": "2.0", "id": msg_id, "result": {"tools": TOOLS}}
        elif msg_id is None:
            continue  # notification
        else:
            reply = {
                "jsonrpc": "2.0",
                "id": msg_id,
                "error": {"code": -32601, "message": f"method not found: {method}"},
            }
        sys.stdout.write(json.dumps(reply) + "\n")
        sys.stdout.flush()


if __name__ == "__main__":
    main()
