# Empirical findings

Everything measured, with provenance. Reproduce any row with the script
named beside it (`research/`). Corrections are kept in place rather than
edited away — the retractions are part of the record.

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

## 5. Headline: savings as a share of the real bill (`07`)

```
fewer cache reads    $114.57   (381,910,345 token-turns)
fewer cache writes     $6.38   (1,701,392 tokens never cached)
TOTAL                $120.95   =  8.5% of a $1,420 bill
```

**8.5%, with zero MCP servers configured.** Output tokens (11% of the
bill) are untouched — Jettison never shortens answers.

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
