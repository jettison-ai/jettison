"""Jettison — dump the context your agent never uses.

One command cuts tokens across MCP tools, agent skills, project
instructions, tool outputs and conversation history — locally and across
providers — with a silent quality verifier that restores content whenever
optimization could hurt answers.

Built using components derived from Headroom under Apache 2.0
(https://github.com/headroomlabs-ai/headroom). See NOTICE.
"""

from jettison._version import __version__

__all__ = ["__version__"]
