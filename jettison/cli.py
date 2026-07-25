"""Jettison CLI root. Commands: audit, wrap, unwrap, savings, share."""

from __future__ import annotations

import click

from jettison._version import __version__

CLI_CONTEXT_SETTINGS = {"help_option_names": ["--help", "-h"]}


@click.group(context_settings=CLI_CONTEXT_SETTINGS)
@click.version_option(__version__, "--version", "-v", prog_name="jettison")
def main() -> None:
    """Jettison — dump the context your agent never uses.

    \b
    One command cuts tokens across MCP tools, agent skills, project
    instructions, tool outputs and conversation history — with verified
    answer quality.

    \b
    Examples:
      jettison audit                 # how many tokens is your agent wasting?
      jettison wrap claude           # optimize + run Claude Code
      jettison savings               # tokens/dollars avoided so far
      jettison share                 # shareable savings receipt
    """


def _register_commands() -> None:
    from jettison.cli_cmds import audit, savings, share, wrap  # noqa: F401


_register_commands()


if __name__ == "__main__":
    main()
