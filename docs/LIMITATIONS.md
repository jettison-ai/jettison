# Limitations

## Read this first: where Jettison's savings actually land

Measured on 101 real Claude Code sessions (10,696 requests, ~$1,400 of real
spend, prices resolved from provider tables):

| Layer | Share of that bill |
|---|---:|
| Standing context (what Jettison v1 optimizes) | **1.3–2.1%** |
| Re-read waste (exact repeats, supersets, write-readback) | **~0.6%** |
| Everything else — accumulated conversation resident in the window | the rest |

Why: 97.3% of input tokens were **cache reads**, and resident context on a
median request was **185,641 tokens** (mean 297,560, p90 725,876). Standing
context measured 11,055 tokens — **3.7% of an average request**. Cutting 85%
of a 3.7% slice cannot produce a large bill reduction, and the honest cache-
read pricing makes that explicit rather than hiding it behind a token
percentage.

Jettison v1 is therefore worth the most to **MCP-heavy setups** (where the
tool catalog is genuinely large — we measured 98.1% off tool schemas on a real
52-tool setup) and worth little to a vanilla single-repo user with no MCP
servers. `jettison audit` tells you which one you are before you install
anything.

The dominant cost — long sessions accumulating hundreds of thousands of
resident tokens — is addressed by history and eviction management, which is
the deferred Horizon Manager, not by anything shipping in v1.


Stated plainly, in the spirit of Headroom's limitations page. If your setup is
on this list, `jettison audit` will usually tell you before you install
anything else.

- **Small tool lists aren't optimized.** Fewer than 5 tools reaching the wire
  and the registry indirection costs more than it saves; requests pass through
  untouched.
- **Clients with native deferred tool loading see little tool-schema benefit.**
  Claude Code and Codex are shipping native tool search; where the client
  already defers schemas, Jettison steps aside for that surface (and keeps
  `ENABLE_TOOL_SEARCH=true` alive for Claude Code behind a custom base URL).
  Detection is real, not just the min-tools floor: `proxy/native_deferral.py`
  inspects each request for provider-native deferral entries (Anthropic's
  versioned `tool_search_tool_*` server tool types, tool-search function
  names, per-tool `defer_loading` flags), for the small-tools-plus-very-large-
  system shape a deferring client produces, and for an explicit
  `x-jettison-native-deferral` header. On a hit the tool list passes through
  untouched, instruction compilation still runs, and the reason is written to
  the audit record (`native_deferral_reason`).
  Headline savings target MCP-heavy setups on clients *without* native
  deferral — Cline, Cursor, OpenCode, OpenClaw, plain SDK apps.
- **Savings look thin on tool-light, instruction-light setups.** If your agent
  carries 3 tools and a 40-line CLAUDE.md, there isn't much to jettison. The
  audit gives you your own number first; believe it.
- **The verifier v1 is deterministic and structured.** It checks tool
  contracts, numbers, paths, identifiers, critical rules and format
  requirements by extraction + containment. It does not do semantic prose
  entailment yet (that's v2, a small local NLI model). Between those: it
  over-preserves rather than over-cuts.
- **First use of a capability costs extra round-trips.** The
  search → load → call loop adds up to a few model invocations (capped at 4)
  the first time a capability is needed in a session. Loaded capabilities are
  sticky, so this is a first-touch cost. Jettison is a **cost tool, not a
  speed tool**.
- **Streaming buffers when meta-tools are in play.** When our tools are in the
  outbound list, the upstream call is downgraded to non-streaming and the
  response re-synthesized as SSE — first-token latency rises on those turns.
  Turns without our tools stream through untouched.
- **Mixed-turn recovery adds one client round-trip.** If the model calls a
  meta-tool and a client tool in the same turn, the client handles its own
  tool first and our results are patched into its next request.
- **Config-only MCP estimates are estimates.** Servers that can't be launched
  during `audit` get a flat per-server estimate, clearly labeled; run the
  audit where your servers can start for measured numbers.
- **Session identity is heuristic.** Conversations are keyed by model + first
  user message (Headroom's CCR convention). Two identical conversations could
  in principle share state; consequences are limited to which tools are
  preloaded.
- **Dollar figures depend on price tables.** Where LiteLLM pricing can't
  resolve a model, a fallback table is used and figures are labeled
  `estimated`.
