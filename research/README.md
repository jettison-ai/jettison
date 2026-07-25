# Research scripts

Every number Jettison publishes was produced by one of these. They read
**local agent transcripts** (`~/.claude/projects/**/*.jsonl`) read-only,
print aggregates only, and transmit nothing. Run them against your own
machine to reproduce or refute any claim we make.

```bash
.venv/bin/python research/01_billing_and_composition.py
```

| Script | Answers | Headline result on the reference corpus |
|---|---|---|
| `01_billing_and_composition.py` | Where do tokens go, by billing tier and content kind? | 97.3% of input tokens are cache reads |
| `02_resident_ceiling.py` | What is resident context made of, and what is the ceiling for any optimizer? | tool-call **args 48.6%**, results 32.3%; ceiling ~26% of resident cost |
| `03_shape_vs_evict.py` | Shape on arrival, or evict from history? | shape 6.0% vs evict 2.6% → never evict |
| `04_addressable_share.py` | How much of spend can the standing-context layer touch? | 1.3–2.1% |
| `05_real_repo_demo.py <repo>` | Compiler + registry on a real repo with live MCP introspection | OpenMC: 52 tools, standing 17,941 → 6,903 |
| `06_real_proxy_e2e.py <repo>` | The full proxy loop against real schemas | 11,196 → 1,848 tokens on the wire |
| `07_total_bill_savings.py` | **The headline: savings as a share of the real bill** | **8.5%** |

## The reference corpus

101 local Claude Code sessions, 10,696 model requests, ~$1,420 of real
spend, on a machine with **zero MCP servers configured** — i.e. the
mainstream case, not a favourable one.

## Rules for using these numbers

1. **Savings are a share of the total bill**, never of a slice. Reporting
   "21.9% of resident cost" as a product claim is how a 8.5% product gets
   sold as a 20% one. `07` is the script that settles it.
2. Prices come from provider tables via `jettison.pricing`; token counts
   from transcripts are `estimated` (chars/4) unless a tokenizer ran.
3. Any claim in the README, docs, or a paper must name the script that
   produced it.
