"""Standing-context scan orchestrator (the engine behind `jettison audit`).

Read-only: enumerates MCP tool schemas (live introspection where
possible), skills and instruction files for a client, tokenizes each item
as it would appear in a request body, and reports per-category waste.
"""

from __future__ import annotations

import concurrent.futures
import json
from pathlib import Path

from jettison.scanner import duplicates as dup_mod
from jettison.scanner import instructions as instr_mod
from jettison.scanner import mcp as mcp_mod
from jettison.scanner.model import Category, ScanItem, ScanReport
from jettison.tokens import DEFAULT_MODEL, count_text

SUPPORTED_CLIENTS = sorted(mcp_mod.DISCOVERERS.keys())


def scan(
    client: str = "claude",
    project_dir: Path | None = None,
    model: str = DEFAULT_MODEL,
    launch_servers: bool = True,
    introspect_timeout: float = mcp_mod.INTROSPECT_TIMEOUT_S,
) -> ScanReport:
    if client not in mcp_mod.DISCOVERERS:
        raise ValueError(f"unknown client {client!r}; supported: {SUPPORTED_CLIENTS}")
    project_dir = (project_dir or Path.cwd()).resolve()
    report = ScanReport(client=client, project_dir=str(project_dir), model=model)

    _scan_mcp(report, client, project_dir, launch_servers, introspect_timeout, model)
    _scan_instructions(report, client, project_dir, model)
    return report


def _scan_mcp(
    report: ScanReport,
    client: str,
    project_dir: Path,
    launch_servers: bool,
    timeout: float,
    model: str,
) -> None:
    specs = mcp_mod.DISCOVERERS[client](project_dir)
    launchable = [s for s in specs if s.transport == "stdio" and launch_servers]
    for spec in specs:
        if spec not in launchable:
            _add_unintrospected(report, spec)

    # Introspect concurrently: most real servers are `npx`/`uvx` launched and
    # spend their first several seconds resolving a package, so serial
    # scanning costs sum-of-cold-starts and pushes honest setups past any
    # sane timeout. Results are re-ordered to match `specs` so the report
    # stays deterministic regardless of which server answers first.
    results: dict[str, list[mcp_mod.MCPTool] | Exception] = {}
    if launchable:
        with concurrent.futures.ThreadPoolExecutor(max_workers=min(8, len(launchable))) as pool:
            futures = {
                pool.submit(mcp_mod.introspect_stdio_server, spec, timeout): spec
                for spec in launchable
            }
            for future in concurrent.futures.as_completed(futures):
                spec = futures[future]
                try:
                    results[spec.name] = future.result()
                except mcp_mod.MCPIntrospectionError as e:
                    results[spec.name] = e

    for spec in launchable:
        outcome = results.get(spec.name)
        if isinstance(outcome, Exception) or outcome is None:
            report.warnings.append(
                f"could not introspect MCP server '{spec.name}': {outcome or 'no result'}"
            )
            _add_unintrospected(report, spec)
            continue
        for tool in outcome:
            payload = json.dumps(tool.context_json(), separators=(",", ":"), ensure_ascii=False)
            tc = count_text(payload, model)
            report.items.append(
                ScanItem(
                    category=Category.MCP_TOOLS,
                    name=f"{tool.server}:{tool.name}",
                    source=spec.source,
                    tokens=tc.tokens + mcp_mod.PER_TOOL_FRAMING_TOKENS,
                    token_label=tc.label,
                    detail=tool.description[:80],
                )
            )


def _add_unintrospected(report: ScanReport, spec: mcp_mod.MCPServerSpec) -> None:
    report.unintrospected_servers.append(spec.name)
    report.items.append(
        ScanItem(
            category=Category.MCP_TOOLS,
            name=f"{spec.name} (not introspected)",
            source=spec.source,
            tokens=mcp_mod.ESTIMATED_TOKENS_PER_UNKNOWN_SERVER,
            token_label="estimated",
            detail="config-only estimate; rerun with server launchable for a measured number",
        )
    )


def _scan_instructions(
    report: ScanReport, client: str, project_dir: Path, model: str
) -> None:
    files = instr_mod.DISCOVERERS[client](project_dir)
    metadata_only = client in instr_mod.METADATA_ONLY_SKILL_CLIENTS
    for f in files:
        if f.kind == "skill" and metadata_only:
            # These clients already list skills as one name+description line
            # and read the body only when the skill is invoked, so the body
            # is NOT standing context. Counting it would inflate the bill by
            # 10-100x per skill and claim credit for work the client already
            # does. Charge the index line, and only that.
            from jettison.compiler import summarize_skill

            summary = summarize_skill(f.name.split(":")[-1], f.text)
            line = f"- {summary.name}: {summary.description}"
            tc = count_text(line, model)
            detail = "index line only; body loaded on demand by this client"
        else:
            tc = count_text(f.text, model)
            detail = ""
        report.items.append(
            ScanItem(
                category=Category.SKILLS if f.kind == "skill" else Category.INSTRUCTIONS,
                name=f.name,
                source=str(f.path),
                tokens=tc.tokens,
                token_label=tc.label,
                detail=detail,
            )
        )

    # Duplicate detection covers instruction files only: skill bodies that
    # never enter standing context cannot waste standing-context tokens.
    dups = dup_mod.find_duplicates(
        [(f.name, f.text) for f in files if f.kind != "skill" or not metadata_only],
        lambda text: count_text(text, model).tokens,
    )
    for g in dups:
        report.items.append(
            ScanItem(
                category=Category.DUPLICATES,
                name=f"repeated in {len(g.sources)} files",
                source=", ".join(g.sources),
                tokens=g.wasted_tokens,
                token_label="estimated",
                detail=g.snippet,
            )
        )
