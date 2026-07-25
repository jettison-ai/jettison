# Benchmarks — methodology

This page contains **no numbers**. Every number Jettison publishes (README,
launch posts, talks) comes exclusively from the
[jettison-parity](../../jettison-parity) harness run on disclosed configs, and
is labeled `measured` or `estimated`. Illustrative figures in docs are always
marked as such and never presented as benchmarks.

## The four families

1. **Standing-context benchmark** — deterministic and fully reproducible:
   fixed real-shape configs (an MCP-heavy Claude Code setup; an OpenClaw-like
   setup with ~70 skills and a fat system prompt; Cursor rules files) are
   measured for tokens-per-turn before and after Jettison's compiler +
   registry, per category (tools / skills / instructions / duplicates).
   No model calls, no variance.
2. **Task-parity benchmark** — identical task sets executed optimized vs
   unoptimized with scripted deterministic model policies: task completion,
   correct tool selection, critical-fact retention (commitment extraction +
   containment), retry counts. Any completion drop or lost critical fact is a
   regression and fails CI.
3. **End-to-end session cost** — simulated N-turn (default 50) sessions billed
   at real provider prices with cache-read / input / cache-write tiers modeled
   under both cache-hit and cache-miss regimes. The reported dollar number is
   **after** cache effects; raw tokens are reported separately.
4. **Holdout RCT** — deterministic arm assignment by conversation-key hash
   (Headroom's `output_savings_policy` protocol); treatment/control deltas
   with 95% normal-approximation CIs. Ships with a seeded synthetic generator
   so the pipeline runs out of the box; synthetic output is labeled
   *"synthetic demonstration — not evidence"* and is never published as a
   result. Production RCT protocol follows Johnson & Lee (2026); we report the
   Kummer (2026) triad: latency overhead, rate adherence, answer quality.

## Baselines

- no-compression (identity)
- vanilla Headroom (runtime compression only)
- Kompress-only (ML prose compression only)

## Rules

- `measured` = counted with a real tokenizer / resolved provider pricing on
  actual payloads. `estimated` = calibrated estimators or fallback price
  tables. Mixed aggregates take the weaker label.
- Configs are published in the harness repo; anyone can rerun.
- The harness CLI (`parity run --middleware <name>`) works against any
  middleware implementing the adapter protocol (or any HTTP compression
  endpoint), so third parties can verify our numbers or benchmark their own.
- Latency overhead is reported alongside savings; compression that erases its
  own dollar win through latency is called out, not hidden.

## Reproduction

```
cd jettison-parity
pip install -e .
parity run --family all --middleware jettison --config configs/mcp-heavy
parity run --family all --middleware none   --config configs/mcp-heavy   # baseline
```
