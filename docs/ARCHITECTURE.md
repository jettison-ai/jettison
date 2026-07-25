# Architecture

Jettison is a control plane layered in front of Headroom's runtime compression.
All Jettison code lives in isolated modules; Headroom is consumed as a pinned
dependency (`headroom-ai>=0.32,<0.33`), never modified.

```
agent client ──► jettison proxy ──► headroom proxy (optional) ──► provider
                 standing context     runtime compression
                 meta-tool loop       (SmartCrusher, CCR, …)
                 verifier
```

## Modules

### `jettison.scanner` — what does your context cost?

- `scanner/mcp.py` — per-client MCP config discovery (Claude Code
  `~/.claude.json` + `.mcp.json`, Codex `config.toml`, Cursor/Cline/OpenCode/
  OpenClaw locations), then **live stdio introspection**: launches each server,
  speaks JSON-RPC MCP (`initialize` → `notifications/initialized` →
  `tools/list` with pagination), and captures the schemas exactly as a client
  would materialize them. Servers that can't launch fall back to clearly-
  labeled config-only estimates.
- `scanner/instructions.py` — instruction/skill discovery per client
  (CLAUDE.md, AGENTS.md, `.cursorrules`, `.cursor/rules/*.mdc`, `.clinerules`,
  OpenClaw workspace files, `*/skills/*/SKILL.md`).
- `scanner/duplicates.py` — normalized-paragraph hashing across files; every
  copy after the first is counted as waste.
- `scanner/scan.py` + `model.py` — orchestration and the `ScanReport`
  data model. Every item carries a `measured`/`estimated` token label.

### `jettison.compiler` — deterministic minification

No ML anywhere in this module, deliberately. Schemas are exact contracts: a
learned compressor that corrupts one parameter name silently breaks every call
to that tool. Deterministic compilation gets ~70–90% reduction with zero
correctness risk and — critically — **byte-stable output**, which cache safety
requires (see CACHE_SAFETY.md). Headroom draws the same line (SmartCrusher is
deterministic for JSON; ML only for prose).

- `schema_min.py` — three passes:
  1. drop JSON-Schema annotation keys (`$id`, `$schema`, `title`, `examples`,
     …) — lossless w.r.t. the calling contract;
  2. description compression — strip boilerplate openers, keep leading
     sentences, bounded length;
  3. shared-type dedup — identical object/array sub-schemas appearing in ≥2
     tools hoist into a `$defs` dictionary keyed by their own content hash, so
     naming is stable regardless of tool order.
- `instructions_min.py` — cross-file paragraph dedup (first occurrence
  survives); paragraphs matching critical markers (never/always/must/secret/
  production/…) are preserved **verbatim**. Detection is deliberately
  over-inclusive: a false positive costs a few tokens, a false negative is
  caught by the verifier. Skill files reduce to one-line index entries; full
  bodies stay local for on-demand loading.
- `bundle.py` — `CompiledBundle`: the stable-prefix text (compiled
  instructions + capability index), the local schema store, shared `$defs`,
  and a content hash over the exact serialized bytes.

### `jettison.registry` — capability index + meta-tools

- `index.py` — pure-Python BM25 over capability names/descriptions/param
  names (name terms weighted 3x, camelCase/snake_case split). This is the v1
  ranker; a learned ranker trained on agent traces is the planned upgrade and
  this module is its interface seam.
- `store.py` — `CapabilityStore`: full minified schemas and skill bodies,
  out of context. `load()` attaches exactly the `$defs` a schema references.
- `metatools.py` — the two v1 meta-tools:
  - `jettison_search_capabilities(query)` → ranked names + one-line summaries
  - `jettison_load_capabilities(names)` → full schemas / skill bodies
  `execute_capability` (direct dispatch) is deferred to v1.1 — it complicates
  the continuation protocol and the two-tool flow already captures the token
  win. Definitions are serialized with sorted keys; the tool-list bytes must
  never vary between requests.
- `prompt.py` — renders the capability index for the stable prefix: sorted,
  timestamp-free, byte-stable.

### `jettison.proxy` — request rewrite + interception loop

- `rewrite.py` — swaps a full tool catalog (≥5 tools) for
  meta-tools + session-loaded real tools (sorted, grow-only), appends the
  capability index to the system prompt, optionally compiles oversized system
  prompts. Under 5 tools: untouched (not worth the indirection, and a client
  with native deferred loading presents few tools here anyway).
- `interceptor.py` — the loop, modeled on Headroom's `CCRResponseHandler`:
  - round cap (4) against infinite model↔proxy loops;
  - pure meta-tool turns resolve fully inside one client request
    (resolve locally → synthesize `tool_result` → re-invoke model);
  - **mixed turns** (meta-tool + client tool in one response) cannot be
    continued — every `tool_use` needs a matching `tool_result` and we only
    have ours. Unlike CCR we can't pass the turn through unmodified (the
    client has never seen our meta-tools), so we resolve our calls, stash the
    results per call-id, hand the turn to the client, and **patch the client's
    fabricated error `tool_result`s on its next request**;
  - `SessionState` keeps loaded capabilities sticky and grow-only per
    conversation (identified CCR-style: model + first user text hash).
- `native_deferral.py` — the real §8.3 tool step-aside: provider-native
  deferral entries (Anthropic's versioned `tool_search_tool_*` types,
  tool-search function names, per-tool `defer_loading`), the small-tools +
  very-large-system shape, or an explicit `x-jettison-native-deferral` header.
  A hit leaves the tool list untouched, still compiles instructions, and
  records the reason in the audit record.
- `heartbeat.py` — OpenClaw cache-warming pings (~5–55 min) are full API
  calls carrying the whole standing context. Detection is precision-first
  (templated final message *plus* a machine-shaped turn, or an explicit
  marker). The transform keeps `tools`, `system` and everything up to the
  last cache breakpoint byte-identical — stripping the warmed prefix would
  warm a *different* entry and pessimize dollars — and drops only the
  uncached conversation tail. Enabled for the `openclaw` client.
- `formats.py` — provider normalization (Anthropic `tool_use` blocks vs
  OpenAI `tool_calls`) and SSE re-synthesis.
- `server.py` — FastAPI app: `POST /v1/messages`, `POST /v1/chat/completions`,
  generic passthrough, `x-jettison-bypass` header. Streaming follows
  Headroom's stream-downgrade pattern: when our meta-tools are in the outbound
  tool list, the upstream call is forced to `stream:false`, the loop resolves
  buffered, and the final response is re-synthesized as SSE for the client.
  `BundleCache` memoizes one `CapabilityStore` per unique tool-list hash and
  runs registry verification at build time; a tool list that fails
  verification is never optimized (fail safe).

### `jettison.verifier` — silent quality gate

- `commitments.py` — deterministic extraction, six kinds:
  `tool_contract` (name + required list + param names), `numeric` (value with
  unit context), `path` (files/URLs), `identifier` (UPPER_SNAKE, error codes,
  version pins), `security_rule` (critical-marker paragraphs),
  `output_format`. Prose entailment via a small local NLI model is v2; the
  extraction interface is its seam.
- `check.py` — `TextVerifier.verify_and_repair`: every commitment from the
  original must be entailed (v1: normalized containment) by the optimized
  text; violations re-inflate the original spans. Results cached per
  (original, optimized) content hash to keep verifier latency off the hot
  path. `verify_tool_registry` proves every original tool remains reachable
  with its contract intact before a registry is ever used.
- `audit_record.py` — per-request JSONL (`~/.jettison/audit/records.jsonl`):
  what compressed, what was checked, what re-inflated, loop stats. Surfaces in
  the product only as the parity line + fallback rate.

### `jettison.savings` / `jettison.pricing` — honest accounting

Append-only JSONL ledger (cost frozen at write time, Headroom convention).
Dollars are computed **cache-aware**: avoided tokens are priced at the tier
they would have billed at — standing context that was a stable cached prefix
prices at cache-read (~10x cheaper than input), not input. `jettison savings`
composes Jettison's standing-context ledger with Headroom's runtime-compression
ledger when present.

### `jettison.telemetry` — opt-in, closed vocabulary

Off unless `JETTISON_TELEMETRY=1` *and* `JETTISON_TELEMETRY_ENDPOINT` are both
set (no default endpoint). `PAYLOAD_FIELDS` is the entire set of keys that can
leave the machine, `build_payload` is pure so the exact bytes are testable
offline, and `maybe_send` fails closed on any undisclosed key, posts from a
daemon thread with a short timeout and swallows every exception. `wrap` sends
one aggregate per session — the ledger delta between start and shutdown — so no
per-request path exists. Contract: docs/TELEMETRY.md.

### `jettison.adapters` — client integration

Launch adapters (claude/codex/opencode) set base-URL env vars and exec the
client; watcher adapters (cursor/cline/openclaw) print exact setup lines and
keep the proxy foreground. `wrap` auto-starts Headroom's proxy in `cache` mode
underneath when installed. For Claude Code, `ENABLE_TOOL_SEARCH=true` is always
set so the client's native deferred loading keeps working behind a custom base
URL (upstream issue #746) — Jettison optimizes only what actually reaches the
wire.

### `jettison.horizon` — resident-context management

The layer that addresses the largest measured cost: content that lands in a
conversation once and is then re-billed on every later turn.

- `economics.py` — the decision arithmetic, kept executable rather than
  documented: a result's true cost is `tokens x remaining_turns` at the
  cache-read rate, so an 8k-token read at turn 3 of a 50-turn session is
  worth ~40x more to shape than the same read at turn 49.
  `eviction_break_even_turns()` encodes why history is never mutated —
  cache-write is ~12.5x cache-read, so an eviction must displace 12.5 turns
  of reads to pay for itself.
- `manager.py` — `HorizonManager.shape_newest_turn()` replaces oversized
  tool results in the final message with a head/tail excerpt plus a
  retrieval marker. Newest-turn-only is the cache-safety rule, not a
  simplification: that turn is not in any provider cache yet.
  Originals are held locally and returned by the `jettison_retrieve_content`
  meta-tool, resolved through the same interception loop as the capability
  meta-tools. Every shaping decision is checked against the Commitment
  Verifier first; a placeholder that would drop a path, number, identifier
  or rule is rejected and the result passes through untouched.

Measured by replaying 101 real sessions: shaping-on-arrival returns ~6.0% of
the input bill, versus 2.6% for history eviction, which is why only the
former is implemented.
