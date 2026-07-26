<div align="center">

<picture>
  <source media="(prefers-color-scheme: dark)" srcset="docs/assets/jettison-wordmark-dark.png">
  <img src="docs/assets/jettison-wordmark-light.png" alt="Jettison" width="420">
</picture>

**Your coding agent re-sends its whole conversation on every turn.
Jettison shrinks what it carries.**

**20–25% fewer turns · 19–27% faster · 21–33% fewer tokens**

repo map · read pruning · prose compression · client-side · local-first

[![CI](https://github.com/jettison-ai/jettison/actions/workflows/ci.yml/badge.svg)](https://github.com/jettison-ai/jettison/actions/workflows/ci.yml)
[![tests](https://img.shields.io/badge/tests-124%20passing-brightgreen)](https://github.com/jettison-ai/jettison/actions/workflows/ci.yml)
[![License](https://img.shields.io/badge/license-Apache%202.0-blue)](LICENSE)
[![Python](https://img.shields.io/badge/python-3.10%2B-blue)](pyproject.toml)

[Install](#install) · [Proof](#what-this-saves--measured-by-live-ab) · [Verify it yourself](#see-your-own-number-first) · [Findings](docs/FINDINGS.md) · [Limitations](docs/LIMITATIONS.md)

</div>

---

```bash
jettison audit       # where your tokens actually go (read-only, 30 seconds)
jettison verify      # measure Jettison on YOUR repo before trusting it
jettison optimize    # install the savings — client-side, fully reversible
```

Measured by live A/B on real Claude Code sessions against a real repository:

| | |
|---|---|
| **20–25% fewer turns** | the agent reaches the answer in fewer steps |
| **19–27% faster** | wall clock, end to end |
| **21–33% fewer input tokens** | more room before you hit the context ceiling |
| **~27% less output** | |
| **cost: roughly neutral** | see below — we are not going to overclaim this |

**On dollars, plainly:** across four separate A/B runs the cost effect
ranged from +10.6% to +2.4%, with confidence intervals spanning zero.
Token, turn and latency reductions reproduce every time; **dollar savings
do not.** The reason is that the savings land in *cached* input tokens,
which bill at roughly a tenth of fresh input — the money is not where the
tokens are.

If you are on a Max or Pro subscription, tokens are your real constraint
and this is a straight win. If you are on API billing and expecting a
smaller invoice, run `jettison verify` first and decide for yourself.

Every other tool in this space advertises 60–95%; independent replication
measures them at 0.4–2.8% of real spend. We would rather hand you the
measuring stick than a number.

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

Then `jettison verify` runs a paired A/B on your own repository — identical
prompts, one arm plain, one arm optimized, alternating order — and reports
what actually happened to your bill. **If it comes out negative on your
workload, it says so.** That is the point.

## Install

```bash
git clone https://github.com/jettison-ai/jettison && cd jettison
uv pip install -e ".[runtime]"     # or: pip install -e ".[runtime]"
jettison audit
jettison optimize
```

PyPI publishing is pending. `[runtime]` adds the optional prose compressor;
the bare package is enough for `audit`. Requires Python 3.10+.

## Supported clients

`claude` (full: map + pruning + prose + style) · `codex` · `cursor` ·
`cline` · `opencode` · `openclaw` (map + style; the pruning hook needs
Claude Code's hook API).

```bash
jettison optimize --client codex     # writes to AGENTS.md
jettison optimize --client cursor    # writes to .cursorrules
```

Every published number is Claude Code. The other clients are supported but
unmeasured — `jettison verify` is how you find out on yours.

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

## Cutting context without changing answers

Cutting context is easy. Cutting it without changing answers is the product.

The Commitment Verifier extracts the facts your original context commits to
— tool names and required parameters, numbers with their units, file paths,
identifiers, hard rules ("never push to production"), output-format
requirements — and checks the optimized context still carries every one. Any
miss and the original span is restored automatically.

- Runs on every optimization. Silent. Zero configuration.
- Fail-safe by construction: anything that fails verification is left untouched.
- Every run writes a local audit line (`~/.jettison/audit/records.jsonl`) so
  the parity claim is checkable, not vibes.

## What this saves — measured by live A/B

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

- n=6, 95% CI [−6.3%, 23.6%] — **directionally positive, not statistically
  significant.** Do not treat 10.6% as a guarantee.
- Savings concentrate in **exploration and comprehension** work (tracing,
  debugging, code review, onboarding). Pure authoring is closer to neutral.
- Every number is Claude Code. Codex and Cursor are supported but unmeasured.
- Reproduce it yourself: `research/08_live_ab_test.py`.

The turn and latency reductions are the part users notice immediately.
The dollar figure is real but smaller, because savings land in cached
input tokens which bill at roughly a tenth of fresh input.

### Standing-context reduction (parity harness)

Generated by the open [parity harness](https://github.com/jettison-ai/jettison-parity)
on disclosed fixture configs. These are the only numbers we publish; anyone
can rerun them.

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
the system prompt has no duplicated paragraphs to drop, and the skills were
already costing only their one-line index entries — Claude Code and OpenClaw
load skill *metadata* and fetch `SKILL.md` on demand, so there is no skill
body in standing context to remove. Earlier drafts of this table counted
full skill bodies and reported −41.9%; that baseline was wrong and the
number is corrected here.

**Task parity** — 6 scenarios (tool selection among many, search→load→call,
numeric constraint, security rule, output format, mixed turn): **zero
regressions**. Completion, correct tool selection, correct parameters and
critical-fact retention are identical in both arms (18/18 extracted
commitments retained). Request tokens across the suite: 114,904 → 52,028
(−54.7%).

**50-turn session cost** — prices `measured` (LiteLLM), token counts
`estimated`:

| Regime | Baseline | Optimized | Saved |
|---|---:|---:|---:|
| cache-hit | $0.8619 | $0.7298 | −15.3% |
| cache-miss | $2.0985 | $1.0247 | −51.2% |

The cache-hit row is the number to quote if you only quote one. Standing
context that was already a warm cached prefix bills at ~0.1x, so cutting it
saves fewer dollars than tokens — that gap is exactly why
[dollar accounting here is cache-aware](docs/CACHE_SAFETY.md).

**Holdout RCT** — the harness ships a seeded synthetic generator so the
pipeline runs out of the box. Its output is labeled *"synthetic
demonstration — not evidence"* and is not a result.

Reproduce:

```bash
cd jettison-parity && pip install -e .
parity run --family all --config configs/mcp-heavy
parity run --family standing --config configs/openclaw-like
```

Methodology and honest-measurement rules: [docs/BENCHMARKS.md](docs/BENCHMARKS.md).

## Works alongside what you already run

Jettison detects [Headroom](https://github.com/chopratejas/headroom),
[Caveman](https://github.com/JuliusBrussee/caveman) and swe-pruner and
composes with them rather than competing:

| | layer |
|---|---|
| **Headroom** | runtime compression of tool outputs (proxy) |
| **Caveman** | response verbosity |
| **Jettison** | repository structure, read pruning, measurement |

If Caveman is already installed, Jettison skips its own style block — two
sets of style instructions cost tokens and can contradict each other.
Nothing here disables another tool or edits its configuration.

**Built using components derived from
[Headroom](https://github.com/chopratejas/headroom) under Apache 2.0**, with
techniques ported from [SWE-Pruner](https://arxiv.org/abs/2601.16746) (MIT),
RepoMaster (MIT) and [Caveman](https://github.com/JuliusBrussee/caveman)
(MIT). See [NOTICE](NOTICE).

## Docs

- [Findings](docs/FINDINGS.md) — everything measured, including what failed
- [Architecture](docs/ARCHITECTURE.md) — module by module, from the actual code
- [Cache safety](docs/CACHE_SAFETY.md) — why byte-stability is a hard rule
- [Limitations](docs/LIMITATIONS.md) — what Jettison won't help with
- [Benchmarks](docs/BENCHMARKS.md) — methodology; every number traces to the harness
- [Positioning](docs/POSITIONING.md) — where this sits against related tools
- [Related work](docs/RELATED_WORK.md) — where this sits in the literature
- [Telemetry](docs/TELEMETRY.md) — opt-in only; off by default

## License

Apache-2.0. See [LICENSE](LICENSE) and [NOTICE](NOTICE).
