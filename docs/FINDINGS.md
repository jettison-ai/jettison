# Empirical findings

Everything measured, with provenance. Reproduce any row with the script
named beside it (`research/`). Corrections are kept in place rather than
edited away — the retractions are part of the record.

> ## ⚠ READ PART 2 BEFORE QUOTING ANYTHING FROM PART 1
>
> Part 1 is **replay-measured** — our logic applied to recorded traffic.
> Part 2 is a **live A/B** of real Claude Code doing real work, and it
> overturned Part 1's headline. Replays cannot model the cache-write churn
> a rewriter provokes, so they systematically overstate.
>
> **The 8.5% figure in §5 is retracted.** Live measurement of the same
> product: −36% to −196%. Part 1's *descriptive* findings (where tokens go,
> what context is made of) still stand; its *savings projections* do not.

**Reference corpus:** 101 local Claude Code sessions, 10,696 model
requests, ~$1,420 of real spend, on a machine with **zero MCP servers**.

---

## 1. Where the money goes (`01`)

| Billing tier | Tokens | Cost | Share |
|---|---:|---:|---:|
| cache read (~0.1x) | 3,137,714,502 | $941.31 | **66%** |
| cache write (1.25x) | 86,355,710 | $323.83 | 23% |
| output | 10,208,437 | $153.13 | 11% |
| fresh input | 702,142 | $2.11 | 0.1% |

**97.3% of input tokens are cache reads.** Any claim priced at the fresh
input rate overstates dollars by ~10x.

## 2. What resident context is made of (`02`)

Measured in **token-turns** (tokens x turns resident), the only unit that
reflects that content is re-sent every turn:

| Category | Token-turns | Share | Cost |
|---|---:|---:|---:|
| **tool call ARGUMENTS** | 924,116,346 | **48.6%** | $277.23 |
| tool results | 615,273,758 | 32.3% | $184.58 |
| user text | 225,320,472 | 11.8% | $67.60 |
| assistant text | 137,864,754 | 7.2% | $41.36 |

Within tool-call arguments: **Write 42.4%, Edit 25.0%, Bash 21.0%.**
Write averages 1,591 tokens per call across 666 calls.

**This is the central finding.** Tool-call arguments are the largest
category of resident cost, and no prior work targets them: Headroom, RTK
and lean-ctx compress tool *outputs*; Anthropic, OpenAI and Cloudflare
defer tool *schemas*; the literature addresses prompts, history and
KV-cache. Arguments were unclaimed.

Cause: when an agent writes a file, the full file content sits in the
conversation for the remainder of the session — although the write already
landed and the content is on disk.

### Ceiling for any optimizer (`02`)

Shaping tool results at an 80% size cut:

| Threshold | Saving |
|---|---:|
| >20k tokens only | 0.1% of bill |
| >8k | 0.3% |
| **>2k (shipped)** | **7.6%** |
| >500 | 16.4% |
| every result | 25.9% |

Most tool-result cost sits in the 500–8k band, not in giant reads.

## 3. Resident context size (`01`)

| | tokens |
|---|---:|
| median request | **185,641** |
| mean | 297,560 |
| p90 | 725,876 |
| max | 989,304 |

Standing context measured **11,055 tokens = 3.7% of an average request**.

## 4. Shape on arrival vs evict from history (`03`)

| Strategy | Return | Verdict |
|---|---:|---|
| shape tool results on arrival | **6.0%** | shipped |
| evict stale results from history | 2.6% | **not built** |

Cache-write is **12.5x** cache-read, so an eviction must displace 12.5
turns of reads to break even. Across the whole corpus only **17** ever
did. This is why `jettison/horizon/` never mutates history and why the
break-even lives in code (`eviction_break_even_turns`) rather than prose —
if pricing narrows, re-run it.

## 5. Savings as a share of the real bill (`07`) — ⚠ RETRACTED, see Part 2

```
fewer cache reads    $114.57   (381,910,345 token-turns)
fewer cache writes     $6.38   (1,701,392 tokens never cached)
TOTAL                $120.95   =  8.5% of a $1,420 bill
```

**8.5%, with zero MCP servers configured.** Output tokens (11% of the
bill) are untouched — Jettison never shortens answers.

> **RETRACTED.** This is a replay estimate. The live A/B (Part 2 §11) of
> this exact product measured −36% to −196%, because a replay prices the
> content that is present and never the re-caching a rewriter causes.
> Kept here as the record of how the error was made.

### By scenario (% of total bill)

| Setup | Horizon | + Standing ctx | Total |
|---|---:|---:|---:|
| No MCP (measured) | 8.5% | 0% | **~8.5%** |
| +3 servers (~30 tools) | 8.5% | ~2.3% | ~11% |
| +6 servers (~52 tools, measured) | 8.5% | ~3.4% | ~12% |
| +20 servers (150+ tools) | 8.5% | ~9.8% | ~18% |
| Short sessions / cold cache | higher | 10x more valuable | 25–40% |

## 6. Standing context on real repos (`05`, `06`)

**openmc-dev/openmc** (1,068★), 6 MCP servers, **52 tools live-introspected**:

- standing context 17,941 → 6,903 tokens/turn (61.5%)
- MCP schemas alone 11,104 → 214 (**98.1%**)
- through the real proxy: 11,196 → 1,848 on the wire (83.5%)
- all 52 tool contracts preserved; bundle hash byte-stable across runs

**Nexus-Mods/Vortex** (1,436★): 3 skills cost **147** tokens, not the
10,343 first reported — see correction 3.

## 7. Re-read waste (`jettison/waste/`)

85 sessions, 1,206 reads, 1,593,406 tokens read:
write_readback 87 occurrences / 57,214 tokens; superset 6 / 13,996;
exact_repeat 48 / 3,480. Resident cost 29.8M token-turns ≈ **$8.94**
(~0.6% of bill).

## 8. Skills cost almost nothing (measured)

Skills are widely adopted, so the question comes up: 10 skill invocations
across the corpus, total resident cost **$0.01**, none large enough to
shape.

Two separate things get confused here:

- **Skills listed in the system prompt** cost ~20 tokens each, because
  Claude Code and OpenClaw emit one `name: description` line and read
  `SKILL.md` only on invocation. 70 skills ≈ 1,400 tokens, not 70 x 5,000.
  There is nothing here for us to save, and claiming otherwise double-counts
  work the client already does — see correction 3.
- **An invoked skill's body** does enter context and stay resident. The
  Horizon Manager shapes it like any other tool result once it exceeds the
  ~2,000-token floor. On this corpus the skills used were small, so nothing
  triggered; a team running 5–10k-token skills early in long sessions would
  see real savings.

Framing that holds up: skills are cheap, but the file reads and writes a
skill *triggers* are exactly where our shaping applies.

## 9. Competitive baseline — independent third-party replay

Headroom's README claims **"60–95% fewer tokens (for JSON data), 15-20%
fewer tokens (for coding agents)"**; press coverage and the project site
carry 80–95%. Those are token ratios on individual payloads.

An independent analyst replayed **500 Claude Code sessions (614M tokens,
$926.31 of spend)** and measured share-of-bill instead
([codepointer](https://codepointer.substack.com/p/cutting-llm-token-costs-with-rtk)):

| Tool | Claimed | Actual share of spend |
|---|---|---:|
| rtk | 60–99% | 0.5% |
| **headroom** | 60–95% | **2.8%** |
| caveman | "halve prose" | 0.4% |
| all three combined | — | **3.7%** |
| **Jettison** (our replay, §5) | — | **8.5%** |

That analysis attributes the claimed-vs-actual gap to the same three causes
found here independently: the denominator (per-payload vs per-bill),
workload mismatch (headroom "activated on 45% of payloads" at a median 25%
reduction), and pricing structure (cache-create and output receive no
compression; savings land in cache-read at a tenth the rate).

**Comparison caveat, state it every time:** the analyst applied Headroom's
*published rates* to recorded traffic; we applied our *actual shaping
logic* to recorded traffic. Both are replay estimates on different corpora,
not a live head-to-head. Describe it as "replay-measured," never as
"benchmarked against."

The structural reason for the gap is finding 2: prior tools compress tool
outputs, which fire on a minority of payloads. Tool-call arguments are the
larger category and were untouched.

## 10. MCP adoption on the reference machine

**0 MCP servers configured across 26 projects.** Real repos that commit
`.mcp.json` (Vortex, OpenMC, Khan/wonder-blocks, nuxt.com,
apache/skywalking-banyandb) declare **1–3 servers**, not 20. The
MCP-heavy segment is real but is not the mainstream case.

---

# Corrections

Kept deliberately. Each was caught by building a stricter measurement
before building the feature it would have justified.

### 1. "21.9% savings" → 8.5%
21.9% was a share of *resident content cost*, a slice of the bill. Against
the real four-tier total it is **8.5%**. Script `07` exists to prevent a
repeat.

### 2. "2.55M tokens of duplicate reads" → 74,690
The first pass counted any repeat read of a path, including re-reads of
files that had legitimately **changed** — correct agent behaviour, not
waste. The strict detector finds 74,690 tokens. 34x smaller. This is why
the runtime de-duplicator was **not** built.

### 3. Skill bodies counted as standing context → 70x overclaim
Claude Code and OpenClaw list skills as a single name+description line and
read `SKILL.md` on demand. Counting full bodies reported Vortex's skills
as 10,343 tokens; the real standing cost is **147**. Fixed in
`scanner/instructions.py` (`METADATA_ONLY_SKILL_CLIENTS`). The published
openclaw-like benchmark was corrected from −41.9% to **−33.5%**.

### 4. "Tool results are 79.3% of content / 33% addressable" — withdrawn
Produced by a crude char-based parser and not reproducible with a stricter
one. Superseded by finding 2, which uses token-turns.

### 5. Scanner defects found by dogfooding
- 15s serial MCP introspection timeout silently degraded npx/uvx servers —
  the common case — to config-only estimates. Now concurrent, 90s default.
- `AGENTS.md` was ignored for Claude Code. openmc's CLAUDE.md is a 3-line
  pointer at a 17KB AGENTS.md, so the audit under-reported by ~5K tokens.

---

# Open measurement

1. **Jettison + Headroom stacked savings — unmeasured.** Headroom publishes
   15–20% on coding agents (independently replay-measured at 2.8% of spend,
   §9). We target the same tool outputs and shape the largest ones first, so
   their marginal contribution on top of Jettison is smaller than either
   figure. **Adding the numbers is not valid.** Replay this corpus through
   both to settle it.
2. **One-method, one-corpus comparison.** §9 compares two replay estimates
   run on different corpora by different people. Running the codepointer
   methodology against our corpus — and ours against theirs — would produce
   a genuinely like-for-like number. This is the single highest-value
   measurement left and is roughly a day of work.
3. **Codex and Cursor transcripts unmeasured.** Argument shaping should
   transfer unchanged (both write files the same way), but every number in
   this document comes from Claude Code sessions. Say "expected to
   transfer," not "measured," until `~/.codex/sessions` is replayed.

---

# Part 2 — Live A/B on real Claude Code sessions (the decisive evidence)

Everything in Part 1 was **replay**: applying our logic to recorded
traffic. Part 2 ran real Claude Code doing real coding work on a real
repo (pallets/click), identical tasks, direct vs through Jettison,
alternating arm order, measured from Claude Code's own
`--output-format json` telemetry. Analyzer: `research/08_live_ab_test.py`.

**This overturned Part 1's headline. The replay-measured 8.5% does not
survive contact with production prompt caching.**

## 11. Four configurations, four losses

| Configuration | Cost vs direct | Token change | Cause |
|---|---:|---:|---|
| tool registry + horizon | **−36%** | −27% input | cache-write 60,805 → 114,156 |
| horizon shaping only | **−74%** | +109% input | agent re-fetched; turns 48 → 63 |
| inline tool minification | **−196%** | −14% input | cache-write 5,165 → 63,196 |
| expired-content elision | **−0.2%** | small | re-cache cost exceeded savings |

## 12. Root cause: the cache-write tax

Cache-write costs **12.5x** cache-read. A proxy edits the request *after*
the client has built and cached it, so the client keeps replaying the
original bytes and every edit forces a re-cache. **We save cheap tokens
and pay expensive ones.**

Inline minification is the cleanest demonstration: it cut cache-read 30%
and its output is provably byte-stable (identical hash over three
identical requests, verified against a capture server) — and it *still*
lost, because cache-write went 12x.

## 13. Root cause: induced re-work

Size-based shaping made the agent do **31% more turns** (48 → 63). On one
task it did 3 Reads where the direct arm did 1.

Context in an active coding agent is **working memory, not dead weight**.
Hide a file and the agent re-reads it. The token-turns model in
`horizon/economics.py` prices content *sitting there*; it cannot see the
cost of the agent *going to get it back*. That is a flaw in the premise,
not the code, and only live agents could expose it.

## 14. Why the literature reports 21–54% and we measure ~0

The Elicit review (`~/Downloads/Elicit - Cost-Efficient Coding Agents`)
reports AgentDiet at 39.9–59.7% input reduction / 21.1–35.9% cost, and
SWE-Pruner at 23–54% with success rates *improving*.

The review also records that a key study ran with **prompt caching
disabled "for consistency, limiting real-world applicability."** With
caching off, removing 40% of input saves 40%. With caching on, removing it
triggers a re-cache at 12.5x. **The lab gains do not transfer because the
lab turned off the mechanism that defeats them.**

This is consistent with every independent production measurement:
headroom 2.8%, rtk 0.5%, caveman 0.4% of real spend.

## 15. The architecture that does work: client-side, not proxy

The two tools that measure positive in production are **both client-side**:
RTK is a binary registered as Claude Code shell hooks; caveman is an
output-style config the client owns.

A hook edits content **before** it enters the client's conversation, so
the client caches its own smaller content and there is nothing to
mismatch. No cache-write tax. Worst case ≈ break-even.

**Unresolved for the hook path:** induced re-work (finding 13) does *not*
go away — trimming a read can still make the agent re-read. Must be A/B'd.
And note RTK/caveman deliver only 0.4–0.5%, so do not assume a hook is
automatically large.

## 16. Bugs only live traffic found

All fixed, all with regression tests:

1. A parameter *named* `description` was deleted from tool schemas (the
   annotation drop-list applied inside `properties`). 8 of Claude Code's
   37 tools were affected; every call to them would have been malformed.
   The registry verifier caught it and disabled optimization — silently.
2. Thinking blocks lost their `signature` in SSE re-synthesis → API 400
   `each thinking block must contain thinking`, one request *after* the
   cause, only with extended thinking on.
3. Shaping applied to the newest turn only, while the client replays
   originals → prefix mismatch every turn.
4. The retrieve tool was appended on first shaping, mid-session → tools
   sit at the front of the cached prefix, so the whole cache invalidated.

Also: two proxies bound to one port and the **old config silently served
an entire A/B run**. Always print and verify the live config before
trusting a measurement.

---

# Corrections to Part 1

- **"8.5% of the real bill" is retracted for the proxy.** It was
  replay-measured and replays cannot model cache-write churn. Live A/B on
  the same product measured −36% to −196%.
- The token-turns economic model is valid for *pricing residency* and
  invalid for *predicting savings*, because it omits induced re-work.
- Do not quote any savings number for Jettison until it is produced by
  `research/08_live_ab_test.py` on a live A/B.

# What is safe to ship today

`jettison audit` only. Read-only, outside the request path, cannot cost
anyone anything, and its findings are genuinely counter-intuitive
(skills cost ~20 tokens each, not their file size; tool-call arguments
are 48.6% of resident cost).

---

# Part 3 — Client-side works (the first positive result)

Same method as Part 2 — real Claude Code, real repo (`pallets/click`),
identical tasks, alternating arm order, measured from Claude Code's own
`--output-format json` telemetry. The only change is **where** the
optimization lives: inside the client instead of in front of it.

## 17. Six paired coding tasks

| Task | Type | Cost saved | Input tokens saved |
|---|---|---:|---:|
| 0 | exploration | **+27.7%** | 73.6% |
| 2 | exploration | **+23.8%** | 79.1% |
| 3 | exploration | **+20.9%** | 40.4% |
| 5 | exploration | −1.3% | 72.5% |
| 4 | pure write | −2.0% | −1.3% |
| 1 | pure write | −6.3% | −12.4% |
| **TOTAL** | | **+15.1%** | **52.5%** |

$2.2270 → $1.8905 on identical work. Mean 10.5%, sd 15.2,
95% CI [−1.7%, 22.7%], n=6.

| Aggregate | direct | jettison | |
|---|---:|---:|---:|
| cache_read | 3,292,362 | 1,569,503 | **−52%** |
| cache_write | 138,835 | 59,367 | **−57%** |
| output tokens | 27,052 | 13,957 | **−48%** |
| turns | 82 | 39 | **−52%** |
| wall clock | 368s | 194s | **−47%** |

**Cache-write went down 57%.** In Part 2 it rose every time and that is
what destroyed the proxy. Reversing its direction is the single clearest
evidence that client-side delivery is the correct architecture.

## 18. The mechanism, verified

Task 0, tool calls actually made:

| | calls |
|---|---|
| plain Claude Code | 5 Bash + 5 Read + 1 Write = **11** |
| with Jettison | **1 scout** + 2 Read + 1 Write = **4** |

The expensive model delegated exploration once instead of making ten
exploratory calls itself. This is the RepoMaster pattern reproduced on
Claude Code.

## 19. Where it helps and where it does not

Exploration-heavy tasks: +20.9% to +27.7%. Pure authoring: −2.0% to
−6.3%, because delegation has a floor cost and there is nothing to
explore. The sign was predicted by the mechanism in 5 of 6 tasks.

Scout guidance now tells the model to skip delegation on pure-authoring
work.

## 20. Subagent spend is counted — and it matters

Claude Code's `total_cost_usd` **includes the subagent's tokens**, so
scout's Haiku spend counts against us. That is why task 5 shows 72.5%
fewer input tokens but −1.3% cost: work moved from Sonnet to Haiku rather
than disappearing.

**Scout efficiency therefore converts directly into dollars.** A verbose
scout eats its own saving. This is the highest-leverage tuning target.

## 21. Honest limits

- n=6, and the CI touches zero. Directionally strong, not yet formally
  significant. More pairs is cheap now that the harness works.
- Tasks ran 4–12 turns. Real sessions run 50–125 turns with a median
  185,641 tokens resident (§3), so short tasks **under-represent** an
  optimizer whose whole mechanism is compounding. A sustained
  single-feature run is the better test.
- Claude Code only. Codex and Cursor are unmeasured.

## What can be claimed today

> ~15% cheaper and ~50% faster on real coding work; around 25% on
> exploration-heavy tasks and roughly break-even on pure authoring;
> 52% fewer input tokens overall.

Never a flat percentage without the task-type split: a write-heavy user
who is promised 15% will measure zero and say so publicly.

---

# Part 4 — The composition (client-side stack)

Repo map + read pruning + verbosity, installed by `jettison optimize`.
Real Claude Code both arms on `pallets/click`, six mixed tasks
(3 exploration, 2 authoring, 1 mixed), alternating arm order.

## 22. Result

| Task | Type | Cost saved | Tokens saved |
|---|---|---:|---:|
| 0 | exploration | **+42.3%** | 78.2% |
| 3 | authoring | **+16.8%** | 19.7% |
| 1 | exploration | +4.5% | 23.9% |
| 4 | authoring | +0.6% | 26.4% |
| 2 | exploration | −2.3% | 28.4% |
| 5 | mixed | −9.8% | −8.3% |
| **TOTAL** | | **+10.6%** | **+33.1%** |

$1.9615 → $1.7539. Mean 8.7%, sd 18.7, **95% CI [−6.3%, 23.6%], n=6** —
directionally positive, **not yet publishable**.

| Aggregate | direct | jettison | |
|---|---:|---:|---:|
| cache_read | 2,716,363 | 1,755,131 | −35% |
| cache_write | 132,955 | 151,235 | +14% |
| output | 23,229 | 21,312 | −8% |
| turns | 63 | 47 | **−25%** |
| wall clock | 329s | 267s | **−19%** |

## 23. The cache-write increase is the map, and it pays 4.2x

+18,280 cache-write tokens across 6 sessions. The repo map is 2,676
tokens x 6 sessions = 16,056 of that; the remainder is noise. It costs
**$0.0685** to cache and buys **$0.2884** of avoided reads — a **4.2x**
return. Not the proxy failure mode returning; the price of the index,
correctly paid once per session.

## 24. Token savings are ~3x the dollar savings, again

33.1% of tokens, 10.6% of dollars. Savings land in cache-read tokens,
which bill at ~a tenth of fresh input. **Never quote the token number as
a cost number.**

## 25. The repo map rescues authoring, which scout could not

Task 3 (add a function plus tests) returned **+16.8%**. Every previous
authoring measurement was −2% to −6%, because scout's delegation
round-trip is pure overhead when there is nothing to explore. A
zero-turn index has no such floor: the agent knows where `_utils.py` is
without hunting for it. This is why scout is now opt-in and probably
obsolete.

## 26. Verbosity is underperforming its promise

Output fell only **8%**, against Caveman's claimed 40–65%. Either the
`balanced` style is too gentle or the model is not honouring it. Output
bills at ~50x cache-read, so this is the cheapest remaining upside —
try the `terse` level and measure.

## What can be claimed after Part 4

> ~10% cheaper, ~33% fewer tokens, ~25% fewer turns and ~19% faster on
> mixed coding work; best on exploration (up to 42%), roughly neutral on
> some tasks.

Still with a CI spanning zero. Tighten it before publishing anything.

---

# Part 5 — A measurement bug, and what survived it

## 27. `usage` is the last request; `modelUsage` is the session

Claude Code's `--output-format json` reports **two different scopes**:

```
usage.cache_read_input_tokens    -> the FINAL request only
modelUsage.cacheReadInputTokens  -> the whole session
total_cost_usd                   -> the whole session
```

`research/08_live_ab_test.py` read the first while comparing against the
third — last-request tokens against session cost. On short sessions the
two coincide, which is why it survived several runs undetected. It
surfaced only when a task reported **89% fewer tokens alongside a 40%
cost increase**, which cannot both be true.

**Cost figures were never affected** — `total_cost_usd` was correct
throughout. Token figures on long sessions were.

| Run | Cost (unchanged) | Tokens: reported → corrected |
|---|---:|---|
| Scout batch | +15.1% | 52.5% → **−14.7%** |
| Composition, balanced | +10.6% | 33.1% → 33.1% (short sessions; unaffected) |
| Composition, terse | −20.6% | 19.5% → **0.7%** |

Lesson for the record: **a savings claim and its denominator must come
from the same scope.** This is the second time the same class of error
appeared — the first was quoting share-of-payload as share-of-bill.

## 28. Terse verbosity is harmful; balanced is the shipping default

Seven paired tasks with `terse`:

| | direct | jettison (terse) |
|---|---:|---:|
| cost | $2.3248 | **$2.8045 (−20.6%)** |
| cache_write | 136,237 | **223,155 (+64%)** |
| output | 27,428 | **36,332 (+32%)** |
| turns | 79 | 61 |

Terse produced **more** output, not less. The aggressive framing appears
to push the model into re-planning instead of answering. `balanced`
returned +10.6% on the same stack, so it stays the default and `terse` is
retained for experimentation only, labelled in the CLI.

## 29. Best measured configuration (V1)

Repo map + read pruning + prose compression + balanced verbosity:

| | direct | jettison |
|---|---:|---:|
| cost | $1.9615 | **$1.7539 (+10.6%)** |
| turns | 63 | **47 (−25%)** |
| wall clock | 329s | **267s (−19%)** |

n=6 mixed tasks, 95% CI [−6.3%, 23.6%]. Directionally positive, CI still
spans zero. **Best on exploration (+42.3% on one task), roughly neutral on
some authoring.**
