# Cache safety

Getting this wrong turns a "token optimizer" into a **dollar pessimizer**.
These rules are enforced in code and are non-negotiable for contributors.

## The economics

- Provider-cached input tokens are ~10x cheaper than fresh input tokens
  (Anthropic cache-read ≈ 0.1x input; cache-write ≈ 1.25x; default TTL ~5
  minutes, 1h extended tier).
- Standing context (schemas, system prompt, rules) is the *most cacheable*
  content an agent sends: identical bytes, every request.
- Headroom deliberately skips standing context **because** stability preserves
  caching. An optimizer that rewrites the prefix differently on every request
  busts the cache and can produce *negative* dollar savings while showing
  positive token savings.

## The rules

1. **Stable prefix is byte-identical.** The compact capability index and
   compiled instructions live in the system prompt and must serialize to the
   same bytes for the same inputs: sorted maps, no timestamps, no session ids,
   no load-order variation, no counters. Every compiled artifact carries a
   content hash; identical input state ⇒ identical hash ⇒ identical bytes.
2. **Dynamic content goes to the context tail only.** Schemas loaded via
   `jettison_load_capabilities` arrive as tool results at the end of the
   conversation — never injected into the prefix.
3. **The tool list grows monotonically per session.** Loading a capability
   adds it to the outbound tools list *sorted by name* and it stays for the
   session: one cache bust per newly loaded tool, then stable. Tools are never
   removed mid-session (removal would bust the cache again for zero benefit).
   Meta-tool definitions are byte-constant, mirroring Headroom's
   `SessionCcrTracker` golden-bytes rule.
4. **Interoperate with Headroom's cache mode, don't fight it.** `wrap` starts
   Headroom in `--mode cache` (prior turns frozen). Jettison mutates only the
   standing context it owns and the newest turn; CacheAligner's volatile-
   content detection stays meaningful because our prefix is stable by
   construction.
5. **Dollar savings are computed cache-aware.** Avoided tokens are priced at
   the tier they would actually have billed at:
   - standing context that was previously a *hit* cached prefix → cache-read
     rate (cheap — honest but small);
   - context that would have missed (first turns, TTL expiry, cache-busting
     clients) → input rate;
   - never price avoided tokens at input rate by default. Raw token deltas
     overstate dollar savings up to ~10x on cache-hit-heavy agents.
   Raw token counts are still reported — they matter for context-window
   relief, latency and model focus — but tokens and dollars are separate
   numbers with separate labels.

## Why this repo can promise it

Determinism is structural, not aspirational: the compiler and index renderer
have no clock, no RNG, no environment-dependent branches; dedup dictionaries
are keyed by content hash rather than discovery order; tests assert identical
hashes across repeated runs. Anything that would vary per request is excluded
from the prefix by construction.
