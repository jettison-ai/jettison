"""End-to-end Jettison demo against a real repo and real public MCP servers.

Introspects live, compiles, builds the capability registry, then drives the
full interception loop with a scripted model so the parity claim is checked
on real schemas rather than fixtures.
"""

import json
import sys
from pathlib import Path

from jettison.compiler import build_bundle, compile_instructions, minify_tools, summarize_skill
from jettison.registry import CapabilityStore, render_capability_index
from jettison.registry.metatools import LOAD_TOOL, SEARCH_TOOL, resolve_meta_call
from jettison.scanner import instructions as instr_mod
from jettison.scanner import mcp as mcp_mod
from jettison.tokens import count_text
from jettison.verifier import extract_text_commitments, verify_tool_registry

project = Path(sys.argv[1]).resolve()

# ---- 1. live introspection of the real configured servers ----
specs = mcp_mod.discover_claude_code(project)
tools, per_server = [], {}
import concurrent.futures as cf

with cf.ThreadPoolExecutor(max_workers=8) as ex:
    futs = {
        ex.submit(mcp_mod.introspect_stdio_server, s, 120): s
        for s in specs
        if s.transport == "stdio"
    }
    for f in cf.as_completed(futs):
        s = futs[f]
        try:
            got = f.result()
            per_server[s.name] = len(got)
            tools += [
                {
                    "name": f"mcp__{t.server}__{t.name}",
                    "description": t.description,
                    "input_schema": t.input_schema,
                }
                for t in got
            ]
        except mcp_mod.MCPIntrospectionError as e:
            per_server[s.name] = f"FAILED ({e})"

tools.sort(key=lambda t: t["name"])
print(f"\n{'='*70}\nREAL REPO: {project.name}   ({len(tools)} tools live-introspected)\n{'='*70}")
for name, n in sorted(per_server.items()):
    print(f"  {name:22} {n} tools")

# ---- 2. the real instruction + skill files ----
files = instr_mod.discover_claude(project)
instr_files = [(f.name, f.text) for f in files if f.kind == "instructions"]
skills = [summarize_skill(f.name.split(":")[-1], f.text) for f in files if f.kind == "skill"]

tools_before = count_text(json.dumps(tools, separators=(",", ":"))).tokens
instr_before = sum(count_text(t).tokens for _, t in instr_files)
skills_before = sum(count_text(s.body).tokens for s in skills)

# ---- 3. compile + build the registry ----
minified = minify_tools(tools)
compiled = compile_instructions(instr_files)
index_text = render_capability_index([(t.name, t.description[:80]) for t in minified.tools], skills)
bundle = build_bundle(minified, compiled, skills, index_text)
store = CapabilityStore(bundle)

index_after = count_text(index_text).tokens
instr_after = count_text(compiled.text).tokens
# Meta-tools are the only tool bytes on the wire until something is loaded.
from jettison.registry import anthropic_tool_defs

meta_after = count_text(json.dumps(anthropic_tool_defs(), separators=(",", ":"))).tokens

before = tools_before + instr_before + skills_before
after = index_after + instr_after + meta_after
print(f"\n{'—'*70}\nSTANDING CONTEXT PER TURN\n{'—'*70}")
print(f"  {'category':24} {'before':>9} {'after':>9} {'saved':>8}")
print(f"  {'MCP tool schemas':24} {tools_before:>9,} {meta_after:>9,} {100*(1-meta_after/tools_before):>7.1f}%")
print(f"  {'skills':24} {skills_before:>9,} {'—':>9} {'':>8}")
print(f"  {'instructions':24} {instr_before:>9,} {instr_after:>9,} "
      f"{100*(1-instr_after/instr_before) if instr_before else 0:>7.1f}%")
print(f"  {'capability index (new)':24} {0:>9,} {index_after:>9,}")
print(f"  {'TOTAL':24} {before:>9,} {after:>9,} {100*(1-after/before):>7.1f}%")

# ---- 4. verification on the real schemas ----
check = verify_tool_registry(tools, set(store.capability_names), bundle.schema_store, "anthropic")
print(f"\nVERIFIER: {check.commitments_checked} tool contracts checked on real schemas — "
      f"{'ALL PRESERVED' if check.ok else f'{len(check.violations)} VIOLATIONS'}")
commitments = []
for _, text in instr_files:
    commitments += extract_text_commitments(text)
print(f"          {len(commitments)} instruction commitments extracted "
      f"({len({c.kind for c in commitments})} kinds)")

# ---- 5. determinism (cache safety) ----
b2 = build_bundle(minify_tools(tools), compile_instructions(instr_files), skills, index_text)
print(f"BYTE-STABLE: bundle hash {bundle.content_hash} == {b2.content_hash} "
      f"-> {bundle.content_hash == b2.content_hash}")

# ---- 6. does search actually find the right real tool? ----
print(f"\n{'—'*70}\nCAPABILITY SEARCH ON REAL SCHEMAS\n{'—'*70}")
for q in ["take a screenshot of a web page", "search documentation for a library",
          "read a file from disk", "think step by step about a hard problem"]:
    hits = json.loads(resolve_meta_call(store, SEARCH_TOOL, {"query": q}))["results"][:2]
    print(f"  {q!r}\n      -> {', '.join(h['name'] for h in hits) or 'no match'}")

loaded = json.loads(resolve_meta_call(store, LOAD_TOOL, {"names": [tools[0]["name"]]}))
print(f"\n  load({tools[0]['name']}) -> full schema returned: "
      f"{loaded['loaded'][0]['name'] == tools[0]['name']}")
