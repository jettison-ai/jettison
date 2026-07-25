# Related work

Skeleton seeded from an ~80-source literature review (full APA list lives in
the companion research file); to be expanded into the paper's related-work
section. Jettison's positioning: **provider-independent optimization of the
complete agent context** — schemas + skills + instructions + tool outputs +
history — **with per-request preservation guarantees**.

## 1. Hard (deterministic) compression — mature, productized

Headroom's SmartCrusher (universal JSON), CodeCompressor (AST-aware),
Kompress-v2 (ModernBERT prose, trained on agentic traces), CCR
(compress-cache-retrieve reversibility) and CacheAligner represent the state
of practice for runtime tool-output compression, reporting 60–95% on
JSON-heavy data but 15–20% on coding agents — standing context untouched by
design. RTK and lean-ctx rewrite CLI output only. **Jettison builds above
this layer, not against it**: Headroom is retained; the standing-context gap
is the product.

## 2. Soft / learned compression — complementary, needs model access

Gist tokens and soft-prompt compression achieve high ratios but require
control of model internals, which middleware doesn't have; Deng et al. (2024)
document gist failure modes (silent loss of constraints) that motivate our
verifier design. Cited as complementary; out of scope for a provider-
independent layer.

## 3. KV-cache / serving-layer work — orthogonal

KV-cache compression and reuse (survey and benchmark analysis: Yuan 2024)
optimizes the serving stack below the API boundary. Orthogonal to
request-level context optimization; one paragraph in the paper.

## 4. Agent memory & long-horizon context

OS-style context management (AgentRM, She 2026), orientation caches (PEEK,
Gu 2026), active context compression (Verma 2026), Memori, SimpleMem,
TokenMizer, SWE-Pruner, repo-level empirics (Feng 2026). Partially overlaps
Headroom's SharedContext memory — one reason Jettison's Horizon Manager is
deferred rather than duplicated.

## 5. Tool- and skill-context optimization ← gap #1 (our Standing Context Optimizer)

Deterministic schema compilation (TSCG, Sakizli 2026), tool-context
compression (Xu et al. 2024), SkillReducer (Gao et al. 2026). In products:
OpenAI deferred tool loading (OpenAI API only), Anthropic native tool search
(~85% tool-context reduction claim; Anthropic products only), Cloudflare Code
Mode (Cloudflare ecosystem), MCP official client guidance (guidance, not a
product). **No provider-independent OSS productizes this across clients** —
that is Jettison's registry + meta-tool loop.

## 6. Budget-aware / task-aware allocation ← gap #3 (phase-2 Budget Allocator)

Marginal-information-gain allocation (COMI, Tang 2026), RL-based compression
(TACO-RL, Shandilya 2024), token-budget pool routing (Chen 2026; Liu 2026b),
adaptive context optimization (ACON, Kang 2025). Jettison's pipeline leaves
explicit seams for a per-segment allocator.

## 7. Evaluation & verification ← gaps #2 and #5 (Verifier + Parity Harness)

Formal frameworks for commitment-preserving compression (Trukhina &
Vashkelis 2026), pre-registered production RCTs (Johnson & Lee 2026),
in-the-wild latency/quality characterization (Kummer 2026), middleware
characterization (Jha 2024). **No middleware ships per-request preservation
guarantees with audit artifacts** — Jettison's Commitment Verifier is that
contribution; the Parity Harness is the standardized evaluation the field
lacks.

## The five gaps, summarized

| # | Gap | Jettison answer |
|---|-----|-----------------|
| 1 | Tool-schema & skill compression, provider-independent | Standing Context Optimizer |
| 2 | Verifiable / commitment-preserving compression | Commitment Verifier (silent in product, headline in paper) |
| 3 | Budget-aware allocation | Phase-2 Budget Allocator (seams in place) |
| 4 | Long-horizon context as managed resource | Deferred Horizon Manager |
| 5 | Standardized middleware evaluation | Parity Harness (separate repo, runs against any middleware) |
