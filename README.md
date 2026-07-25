# Jettison

**Your AI agent is paying for context it never uses.**

One command cuts tokens across MCP tools, agent skills, project instructions, tool outputs and conversation history — locally and across providers.

```bash
jettison audit          # how many tokens is your agent wasting? (30 seconds, read-only)
jettison wrap claude    # optimize + run your agent
jettison savings        # tokens and dollars avoided, cache-aware
jettison share          # a receipt you can paste anywhere
```

## The problem

Every MCP server you add ships its full tool schemas into every single request. Twenty tools is easy to hit. Most turns use one of them. You pay for all of them, every turn, forever.

Skills, `CLAUDE.md`, `AGENTS.md`, `.cursorrules` — same story. Standing context rides along whether the task needs it or not.

Runtime compressors already crush tool *outputs* (Headroom reports 60–95% on JSON-heavy data). But on coding agents they see only 15–20% — because standing context is untouched by design (it has to stay byte-stable for provider caching). That gap is what Jettison closes.

## See your own number first

`jettison audit` scans your actual setup: it reads your client's MCP config, launches each stdio server, speaks real MCP (`initialize` → `tools/list`), and tokenizes every schema exactly as it would appear in a request body. Skills and instruction files too, including duplicated paragraphs across files.

Output looks like this — **numbers below are ILLUSTRATIVE, not benchmarks** (real numbers come from the [parity harness](docs/BENCHMARKS.md), and from running `audit` on your own machine):

```
Your agent carries ~41,300 tokens of standing context into every turn (measured, model=claude-sonnet-4-5)

  #  Category                 Tokens   Items
  1  MCP tool definitions     31,850      47
  2  Skills                    5,400       6
  3  Project instructions      3,200       4
  4  Duplicate context           850       3

Over a 50-turn session that is ≥ 2,065,000 standing-context tokens;
≈ $0.62 at cache-read rates — more when caching misses.

Next: `jettison wrap claude` loads tools on demand and compiles
instructions — with verified answer quality.
```

Every line is labeled `measured` or `estimated`. Servers that can't be launched get a clearly-marked config-only estimate.

## How it works

```
                    ┌──────────────────────────────────────────────┐
   agent client ───►│           JETTISON CONTROL PLANE             │
   (claude, codex,  │                                              │
    cursor, cline,  │  scanner ─► compiler ─► capability registry  │
    opencode,       │                          + meta-tools        │
    openclaw)       │                              │               │
                    │              interception proxy              │
                    │                              │               │
                    │                  commitment verifier         │
                    └──────────────────┬───────────────────────────┘
                                       │
                    ┌──────────────────▼───────────────────────────┐
                    │      HEADROOM CORE (retained, attributed)    │
                    │  SmartCrusher · CodeCompressor · Kompress    │
                    │        CCR · CacheAligner · caching          │
                    └──────────────────┬───────────────────────────┘
                                       │
                              Anthropic / OpenAI / …
```

1. **Scanner** discovers your standing context: MCP configs per client, live schema introspection over stdio, skills, instruction files, cross-file duplicates.
2. **Compiler** deterministically minifies it: JSON-Schema annotation stripping, description compression, shared-type `$defs` dedup, instruction dedup with critical rules kept verbatim. Byte-stable output — no ML, no drift.
3. **Capability registry** replaces the full tool catalog with a compact index plus two meta-tools: `jettison_search_capabilities` (BM25-ranked) and `jettison_load_capabilities` (full schemas on demand). Loaded tools stick for the session.
4. **Interception proxy** sits in front of your provider (and optionally in front of Headroom's proxy). It rewrites requests, resolves meta-tool calls locally, and re-invokes the model — your client only ever sees tools it owns.
5. **Verifier** silently checks every optimization and restores the original content whenever cutting it could change an answer. You never configure it. It just runs.

Full details in [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md).

## Install

```bash
pip install jettison-ai        # note: package publishing pending
```

Until it lands on PyPI, install from source:

```bash
git clone https://github.com/jettison-ai/jettison
cd jettison
uv pip install -e ".[all]"     # or: pip install -e ".[all]"
```

`[all]` pulls in the runtime stack (Headroom core, FastAPI proxy). The bare package is enough for `jettison audit`.

## Supported clients

`claude` (Claude Code) · `codex` · `cursor` · `cline` · `opencode` · `openclaw`

One honest note: some clients are shipping native deferred tool loading. Jettison detects setups where the client already defers schemas and steps aside — tiny tool lists (fewer than 5 tools reaching the wire) are never rewritten. Headline savings target MCP-heavy setups on clients **without** native deferred loading, which today is most of them. `jettison audit` tells you which one you are before you change anything.

## Saved tokens with verified task parity

Cutting context is easy. Cutting context without changing answers is the product.

Jettison's Commitment Verifier extracts the facts your original context commits to — tool names and required parameters, numbers with their units, file paths, identifiers, hard rules ("never push to production"), output-format requirements — and checks that the optimized context still carries every one of them. Any miss and the original span is restored automatically, before the request leaves your machine.

- Runs on every optimized request. Silent. Zero configuration.
- Fail-safe by construction: a tool list that fails verification is sent untouched.
- Target fallback rate: **under 2–3%** of requests. `jettison savings` shows yours.
- Every request writes a local audit line (`~/.jettison/audit/records.jsonl`) so the parity claim is checkable, not vibes.

## Benchmarks

Generated by the open [parity harness](https://github.com/jettison-ai/jettison-parity) on disclosed fixture
configs. These are the only numbers we publish; anyone can rerun them.

**Standing context per turn** — `configs/mcp-heavy` (20 MCP tools, 3 skills,
CLAUDE.md + AGENTS.md with overlap), model `claude-sonnet-4-5`, token counts
`estimated`:

| Category | Before | After | Saved |
|---|---:|---:|---:|
| MCP tool definitions | 7,896 | 912 | **−88.4%** |
| Skills | 574 | 94 | −83.6% |
| Project instructions | 930 | 661 | −28.9% |
| **Total** | **9,400** | **1,667** | **−82.3%** |

On `configs/openclaw-like` (70 skills, ~14.5K-token system prompt): total
32,229 → 18,728 (**−41.9%**); tools −94.6%, skills −71.6%, instructions
**0.0%** — that last one is the honest result, not a bug: v1 only dedupes and
normalizes prose, and that prompt has no duplicated paragraphs to drop.

**Task parity** — 6 scenarios (tool selection among many, search→load→call,
numeric constraint, security rule, output format, mixed turn):
**zero regressions**. Completion, correct tool selection, correct parameters
and critical-fact retention are identical in the baseline and optimized arms
(e.g. 18/18 extracted commitments retained in both). Request tokens across the
suite: 114,904 → 52,028 (−54.7%).

**50-turn session cost** — prices `measured` (LiteLLM), token counts
`estimated`:

| Regime | Baseline | Optimized | Saved |
|---|---:|---:|---:|
| cache-hit | $0.8619 | $0.7298 | −15.3% |
| cache-miss | $2.0985 | $1.0247 | −51.2% |

The cache-hit row is the number to quote if you only quote one. Standing
context that was already a warm cached prefix bills at ~0.1x, so cutting it
saves fewer dollars than tokens — that gap is exactly why
[dollar accounting here is cache-aware](docs/CACHE_SAFETY.md) and why raw
token deltas are not presented as savings.

**Holdout RCT** — the harness ships a seeded synthetic generator so the
pipeline runs out of the box. Its output is labeled *"synthetic demonstration
— not evidence"* and is not a result. Production RCT numbers land here after
real deployments.

Reproduce:

```bash
cd jettison-parity && pip install -e .
parity run --family all --config configs/mcp-heavy
parity run --family standing --config configs/openclaw-like
```

Methodology and honest-measurement rules: [docs/BENCHMARKS.md](docs/BENCHMARKS.md).

## Relationship to Headroom

Jettison is a loosely-coupled fork/extension of [Headroom](https://github.com/headroomlabs-ai/headroom). Headroom's runtime compression (SmartCrusher, CodeCompressor, Kompress, CCR, CacheAligner) is excellent and is retained here unmodified via the pinned `headroom-ai` package. Jettison adds the layer Headroom deliberately skips — standing context — plus the verifier, and composes both savings streams in one ledger.

**Built using components derived from [Headroom](https://github.com/headroomlabs-ai/headroom) under Apache 2.0.** See [NOTICE](NOTICE).

## Docs

- [Architecture](docs/ARCHITECTURE.md) — module-by-module, from the actual code
- [Cache safety](docs/CACHE_SAFETY.md) — why byte-stability is a hard rule and how dollars are really counted
- [Limitations](docs/LIMITATIONS.md) — what Jettison won't help with, stated plainly
- [Benchmarks](docs/BENCHMARKS.md) — methodology; every published number traces to the parity harness
- [Related work](docs/RELATED_WORK.md) — where this sits in the literature
- [Telemetry](docs/TELEMETRY.md) — opt-in only; off by default
- [Decisions](docs/DECISIONS.md) — why the design is the way it is, and what's deferred

---

Jettison: the first one-command optimizer that reduces tokens everywhere an AI agent spends them — before the task, during tool use, and across the session — while automatically falling back whenever optimization could hurt quality.

## License

Apache-2.0. See [LICENSE](LICENSE) and [NOTICE](NOTICE).
