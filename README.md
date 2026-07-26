# Jettison

**Your coding agent re-sends its whole conversation on every turn. Jettison shrinks what it carries.**

```bash
jettison audit       # where your tokens actually go (read-only, 30 seconds)
jettison verify      # measure Jettison on YOUR repo before trusting it
jettison optimize    # install the savings — client-side, fully reversible
```

Measured on real Claude Code sessions: **−10.6% cost, −25% turns, −19% wall
clock**, up to **−42%** on exploration-heavy work.

**And we ship the experiment, not just the number.** `jettison verify` runs
the same paired A/B we use internally against your own repository and tells
you what really happened to your bill — including when the answer is
"nothing." Every other tool in this space advertises 60–95%; independent
replication measures them at 0.4–2.8% of real spend. We would rather you
checked.

> **Honest status:** 6 paired tasks, 2 of them slightly negative, CI still
> spans zero. Directionally positive, not a guarantee. Run `verify`.

## The problem

An agent has no memory between requests, so every turn re-sends the entire
conversation. A file read on turn 3 is re-sent on turns 4, 5, 6 … to the
end. One big read costs you dozens of times over.

That is why coding-agent bills grow non-linearly, and why **97% of what you
pay for is re-reading context you already sent**.

## What Jettison does

Four things, all **inside your client** — no proxy, nothing between you and
the provider:

| | |
|---|---|
| **Repo map** | A ranked structural index of your codebase (~3k tokens) injected into your instructions, so the agent knows where everything lives instead of exploring to find out. Zero extra turns. |
| **Read pruning** | Large file reads are trimmed to the lines your current task needs, with line numbers kept and elided ranges named so the agent can always read more. |
| **Prose compression** | Build logs and command output compressed. Code is never touched — routing is enforced. |
| **Response style** | The agent stops narrating what it is about to do. Output bills at ~50x cached input. |

Everything is reversible with `jettison unoptimize`, and every optimization
is checked by a verifier that refuses to drop a path, number, identifier or
security rule.

## See your own number first

`jettison audit` is read-only and touches nothing. It reads your client's
MCP config, launches each stdio server, speaks real MCP
(`initialize` → `tools/list`), and tokenizes every schema exactly as it
appears in a request — plus skills, instruction files and cross-file
duplicates.

Most people are surprised by what it finds. Two examples measured on real
repositories: **skills cost ~20 tokens each, not their file size** (clients
load them on demand), and **tool-call arguments are 48.6% of resident
context cost** — the largest single category, and one no other tool touches.

## Install

```bash
git clone https://github.com/jettison-ai/jettison && cd jettison
uv pip install -e ".[runtime]"     # or: pip install -e ".[runtime]"
jettison audit
jettison optimize
```

PyPI publishing is pending. `[runtime]` adds the optional prose compressor;
the bare package is enough for `audit`.

## Supported clients

`claude` (full: map + pruning + prose + style) · `codex` · `cursor` ·
`cline` · `opencode` · `openclaw` (map + style; the pruning hook needs
Claude Code's hook API).

```bash
jettison optimize --client codex     # writes to AGENTS.md
jettison optimize --client cursor    # writes to .cursorrules
```

## How it works

```
        your instructions              your tool output
   ┌──────────────────────┐        ┌──────────────────────┐
   │  repo map (ranked)   │        │  read pruning        │
   │  response style      │        │  prose compression   │
   └──────────┬───────────┘        └──────────┬───────────┘
              │                                │
              └────────► your agent ◄──────────┘
                     (unchanged, unproxied)
                              │
                     commitment verifier
                   refuses any unsafe cut
```

Everything is delivered where the client already looks — its instruction
file and a `PostToolUse` hook. Nothing sits between you and the provider.

That is not an aesthetic choice. We built the proxy version first and it
**cost more than it saved**: editing a request after the client has cached
it forces a re-cache at ~12.5x the read price, and four separate proxy
configurations measured between −36% and −196%. The full negative result,
and why published lab numbers do not survive production prompt caching, is
in [docs/FINDINGS.md](docs/FINDINGS.md).

Architecture detail: [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md).
Where Jettison sits against Headroom, SWE-Pruner, RepoMaster and Caveman:
[docs/POSITIONING.md](docs/POSITIONING.md).

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

> Picking this project up? Start with [internal notes](internal notes), then
> [docs/FINDINGS.md](docs/FINDINGS.md).

### What this saves — measured by live A/B

Real Claude Code, real repository (`pallets/click`), six mixed coding
tasks, run twice: once plain, once with `jettison optimize` installed.
Same prompts, alternating order, measured from Claude Code's own billing
telemetry.

| | plain | with Jettison | |
|---|---:|---:|---:|
| **cost** | $1.9615 | **$1.7539** | **−10.6%** |
| **turns** | 63 | **47** | **−25%** |
| **wall clock** | 329s | **267s** | **−19%** |

Best result on a single exploration task: **−42.3% cost, 14 → 5 turns.**

**Honest limits, stated up front:**

- n=6, 95% CI [−6.3%, 23.6%] — **directionally positive, not yet
  statistically significant.** Do not treat 10.6% as a guarantee.
- Savings concentrate in **exploration and comprehension** work (tracing,
  debugging, code review, onboarding). Pure authoring is closer to neutral.
- Every number is Claude Code. Codex and Cursor are supported but
  unmeasured.
- Reproduce it yourself: `research/08_live_ab_test.py`.

The turn and latency reductions are the part users notice immediately.
The dollar figure is real but smaller, because savings land in cached
input tokens which bill at roughly a tenth of fresh input.

### Standing-context reduction (parity harness)

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

On `configs/openclaw-like` (70 skills, ~16.5K-token system prompt): total
28,128 → 18,702 (**−33.5%**). Almost all of it is tools (−94.6%). Two
categories move by **0.0%**, and both are honest results rather than bugs:
the system prompt has no duplicated paragraphs for v1 to drop, and the
skills were already costing only their one-line index entries — Claude Code
and OpenClaw load skill *metadata* and fetch `SKILL.md` on demand, so there
is no skill body in standing context for us to remove. Earlier drafts of
this table counted full skill bodies and reported −41.9%; that baseline was
wrong and the number is corrected here.

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
