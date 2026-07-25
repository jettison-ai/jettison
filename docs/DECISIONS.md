# Decisions

Resolutions for the open items in the project hand-off, with the reasoning.
Decisions marked **locked** are settled; the rest carry an explicit revisit
trigger.

## 1. Product name — locked

**Jettison.** PyPI `jettison-ai` (squat `jettison`), npm `jettison-ai`, CLI
`jettison` with alias `jet`, GitHub org `jettison-ai`. Registration is a
manual owner action. "Headroom" is never used in our name or marks; Apache 2.0
grants no trademark rights.

## 2. Python-first, TS SDK later — locked

**Recommendation: Python-first, TypeScript SDK after adoption signal.**

The optimization surface is a *proxy*, not a library. Every supported client
(Claude Code, Codex, Cursor, Cline, OpenCode, OpenClaw) integrates by pointing
a base URL at `127.0.0.1`, which is language-agnostic — a TS user gets 100% of
the value from the Python binary today. Headroom's own npm package is an SDK
only, with no CLI, which tells you where their TS demand actually landed.

Dual-from-day-one would double the surface that must stay byte-identical
(§CACHE_SAFETY): two implementations of the compiler and index renderer must
produce the same bytes or the same user gets different cache behavior from
different install paths. That is a real correctness risk for zero adoption
gain.

**Revisit when:** an embedding partner needs in-process optimization (no
proxy hop), or TS SDK requests exceed ~10% of issues. Port order would be
compiler → registry → verifier, with the Python implementation as the
conformance oracle (identical content hashes on a shared fixture corpus).

## 3. Meta-tool naming and `execute_capability` — locked for v1

Shipped: `jettison_search_capabilities(query)` and
`jettison_load_capabilities(names)`.

The `jettison_` prefix mirrors Headroom's `headroom_retrieve` convention:
collision with a client-owned tool is implausible, and the proxy can claim the
whole namespace when deciding which `tool_use` blocks are its own. Shorter
names (`search_caps`) were rejected — an unprefixed name in a 40-tool catalog
is a real collision risk, and the token cost of the prefix is paid once in the
stable prefix, not per call.

**`execute_capability` ships in v1.1, not v1.** Direct dispatch means the
proxy executes a downstream tool the *client* owns — it would need the
client's MCP connections, credentials and working directory, none of which the
proxy has. The search→load→call flow already captures the token win because
loaded schemas are session-sticky. Revisit if traces show a long tail of
single-use capabilities where the load round-trip dominates.

## 4. Scanner implementation: config introspection *and* proxy tap — locked

**Both, with different jobs.**

- **Config introspection + live MCP stdio handshake** powers `jettison audit`.
  It works *before* anything is installed or wrapped, which is the entire
  point of the viral hook: zero-risk, read-only, no proxy, no API key. It
  gets ground truth by speaking real MCP (`initialize` → `tools/list`), not by
  guessing from config.
- **Proxy tap** powers runtime optimization, where only the bytes the client
  actually sends matter — including tools the client injects that appear in no
  config file, and native-deferral behavior we must detect and step aside for.

Per-client discovery matrix (implemented in `jettison/scanner/`):

| Client | MCP config | Instructions / skills |
|---|---|---|
| claude | `~/.claude.json` (global + per-project), `~/.claude/mcp.json`, `./.mcp.json` | `CLAUDE.md`, `CLAUDE.local.md`, `~/.claude/CLAUDE.md`, `*/skills/*/SKILL.md` |
| codex | `$CODEX_HOME/config.toml`, `./.codex/config.toml` | `AGENTS.md` (project + home) |
| cursor | `~/.cursor/mcp.json`, `./.cursor/mcp.json` | `.cursorrules`, `.cursor/rules/*.mdc`, `AGENTS.md` |
| cline | VS Code globalStorage `cline_mcp_settings.json` | `.clinerules` (file or dir) |
| opencode | `$OPENCODE_CONFIG`, `~/.config/opencode/opencode.json(c)` | `AGENTS.md` (project + home) |
| openclaw | `~/.openclaw/openclaw.json` | workspace `AGENTS.md`/`SOUL.md`/`MEMORY.md`/…, `*/skills/*/SKILL.md` |

## 5. Harness task sets — v1 locked, v2 scoped

**v1 (shipped): hand-authored scripted tasks with deterministic fake-model
policies.** Six scenarios covering tool selection among many, search→load→call,
numeric constraints, security rules, output format, and mixed turns. No model
calls, no API cost, byte-identical across runs — which is exactly what a CI
regression gate needs. A flaky, expensive gate gets disabled within a month.

**v2 (for the paper, needs budget approval before it runs):**

- *Coding*: SWE-bench Lite (300 instances), a fixed seeded subset for
  iteration and the full set for the final table. Report the subset hash so
  the sample is auditable.
- *Tool use*: Berkeley Function Calling Leaderboard (BFCL) for schema-fidelity
  and multi-tool selection, plus τ-bench for multi-turn tool-use with a user
  simulator — τ-bench is the closer analogue to real agent sessions.
- Seeds fixed and published; every run reports model version, date, and
  per-instance results, not just aggregates.

Blocker to state plainly: v2 costs real inference money and must be run with
the holdout protocol to be citable. It is not a prerequisite for launch.

## 6. Verifier commitment taxonomy v1 — locked

Extraction rules as implemented (`jettison/verifier/commitments.py`). The
design bias is deliberate: **over-extract**. A false positive costs a few
tokens of preserved text; a false negative silently changes an answer.

| Kind | Rule | Check |
|---|---|---|
| `tool_contract` | per tool: name + sorted `required` + sorted property names | exact string match of the reconstructed contract against the registry entry |
| `numeric` | number immediately followed by a unit/context word (%, seconds, ms, MB, tokens, retries, …) | normalized containment |
| `path` | filesystem-looking paths with an extension, and http(s) URLs | normalized containment |
| `identifier` | `UPPER_SNAKE_CASE`, error-code shapes (`E[A-Z]{2,}\d*`), version pins (`pkg@1.2.3`) | normalized containment |
| `security_rule` | any paragraph containing a critical marker (never / must / do not / forbidden / secret / credential / api key / production / destructive / approval / …) | whole paragraph must survive verbatim |
| `output_format` | paragraph mentioning respond/reply/output/return *and* a format word (json, yaml, markdown, xml, csv, table, bullet) | whole paragraph must survive |

Violations trigger automatic re-inflation of the original span before the
request leaves the machine, and are logged to
`~/.jettison/audit/records.jsonl`.

**v2:** a small local NLI-style model for prose entailment, replacing
containment for `security_rule` and `output_format` (the two kinds where
paraphrase is legitimate). The extraction interface is already the seam.

## 7. Deferred by design

- **Budget Allocator** (phase 2): `allocate(messages, budget, task_profile)`
  with greedy marginal utility over Headroom's existing relevance scores.
  Pipeline seams exist; no code.
- **Horizon Manager**: deferred until adoption proves long-session cost
  dominates, and because it overlaps Headroom's SharedContext memory — building
  it now would duplicate a subsystem we already inherit.
