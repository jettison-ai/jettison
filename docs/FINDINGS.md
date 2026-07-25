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

## 8. MCP adoption on the reference machine

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

**Jettison + Headroom stacked savings — unmeasured.** Headroom publishes
15–20% on coding agents for tool-output compression. We target the same
outputs and shape the largest ones first, so their marginal contribution
on top of Jettison is smaller than their standalone figure. Adding the
numbers is not valid. Replay the corpus through both to settle it.
