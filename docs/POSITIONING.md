# Where Jettison fits

Three good tools already exist. All three are permissively licensed, and
Jettison composes rather than competes with them.

| | Headroom | Caveman | SWE-Pruner | **Jettison** |
|---|---|---|---|---|
| License | Apache-2.0 | MIT | MIT | Apache-2.0 |
| Delivery | proxy | output style | tool replacement | **client-side** |
| Compress tool outputs | ✅ | — | ✅ | ✅ *(both)* |
| Query-aware pruning | — | — | ✅ | ✅ *(SWE-Pruner)* |
| Reduce agent verbosity | partial | ✅ | — | ✅ *(Caveman)* |
| Tool-schema optimization | — | — | — | ✅ |
| **Tool-call *argument* optimization** | — | — | — | ✅ **only** |
| Cache-safe by construction | partial | ✅ | ✅ | ✅ |
| **Per-request quality verification** | — | — | — | ✅ **only** |
| **Tells you your own number first** | — | — | — | ✅ **only** |
| **Measured on the bill, not the payload** | — | — | — | ✅ **only** |
| **Composes several techniques** | — | — | — | ✅ **only** |

## Why composition is the product

The Elicit review of this literature states the gap plainly: *"No study
compares strategies head-to-head or evaluates their interactions when
combined, leaving practitioners without guidance for composing
multi-layered optimizations."*

Every tool above optimizes one surface. A developer wanting all of them
must install three things, configure three things, and has no way to know
which actually helped. Jettison's job is to measure their setup, install
the right combination, and prove the result on their own bill.

## What we contribute that is genuinely new

1. **Tool-call argument optimization.** Measured at **48.6% of resident
   context cost** — the single largest category, and untouched by any
   prior work, because when an agent writes a file the full text stays in
   the conversation forever (`docs/FINDINGS.md` §2).
2. **Per-request commitment verification.** Nothing is removed if it
   would drop a path, number, identifier, security rule or output-format
   requirement. No other tool offers a preservation guarantee.
3. **`jettison audit`.** Read-only, pre-install, tells a developer where
   their tokens actually go. Most people are wrong about this: skills cost
   ~20 tokens each rather than their file size, and arguments outweigh
   outputs.
4. **Bill-level measurement.** Published savings are share-of-bill from a
   live A/B, never share-of-payload. This is why our numbers are smaller
   than everyone's marketing and match independent replication
   (headroom 2.8%, rtk 0.5%, caveman 0.4% of real spend).
5. **The cache-interaction result.** Lab gains do not survive production
   prompt caching, because cache-write costs 12.5x cache-read. At least
   one study in the review ran with caching *disabled* "for consistency."
   That single fact reconciles 21–54% in papers with 0.4–2.8% in
   production (`docs/FINDINGS.md` §14).

## Delivery: client-side only

Our own live A/B killed the proxy design across four configurations
(−36%, −74%, −196%, −0.2%). A proxy edits the request *after* the client
cached it, so every edit forces a re-cache.

SWE-Pruner and Caveman both work client-side, and both measure positive.
SWE-Pruner replaces `Read` with a pruning tool that takes a
`context_focus_question`, so only relevant lines ever enter the
conversation — the client caches the small version and there is nothing
to mismatch.

**Jettison ships client-side for the same reason.**

## On models

SWE-Pruner publishes a trained neural skimmer
(`ayanami-kitasan/code-pruner`); Headroom publishes Kompress. Under MIT we
can use SWE-Pruner's directly with attribution, and should — training our
own before we have adoption data would be reinventing a working wheel. A
Jettison-authored model belongs in phase 2, aimed at the surface no one
else has trained for: tool-call arguments.

## Attribution

- Headroom (Apache-2.0) — runtime compression, proxy and wrap machinery
- SWE-Pruner (MIT) — query-aware code pruning, ByteDance Research,
  [arXiv:2601.16746](https://arxiv.org/abs/2601.16746)
- Caveman (MIT) — output verbosity reduction

Each retains its own license and notice. Jettison is Apache-2.0.
