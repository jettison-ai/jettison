# What `jettison optimize` installs, and why

Two things, both **inside** Claude Code rather than in front of it.

## 1. Scout — repository navigation on a cheap model

`.claude/agents/jettison-scout.md`, pinned to `haiku`, plus a fenced
delegation rule in `CLAUDE.md`.

The Elicit review of 80 papers names repository-context selection **the
dominant cost driver**: agents read whole files using the same expensive
model that solves the task. Dedicated navigation architectures fix it and
*improve* success — RepoMaster 95% token reduction with pass rate
40.7% → 62.9%, FastContext 60% at +5.5pp, Hierarchical Context Pruning
50K → 8K with accuracy up. The reviews attribute the quality gain to
attention dilution: irrelevant context competes with task-relevant signal.

Observed on the first live A/B task:

| | tool calls |
|---|---|
| plain Claude Code | 5 Bash + 5 Read + 1 Write = 11 |
| with scout | **1 scout** + 2 Read + 1 Write = 4 |

## 2. Prune — trim large reads to what the task needs

A `PostToolUse` hook on `Read`. Claude Code's
`hookSpecificOutput.updatedToolOutput` **replaces what enters the
transcript**, so the client stores and caches the pruned version.

Pruning follows SWE-Pruner's idea (MIT, arXiv:2601.16746): state what you
are looking for, keep the lines that serve it. Ours is deterministic — no
model, no GPU, no network — with `score_lines` as the seam for their
trained skimmer.

Safety properties that matter:

- **Line numbers survive.** Elided regions become
  `… 40 lines elided (lines 120–159) — re-read this range …`, so the agent
  can see and recover exactly what is missing. Silent shortening is what
  caused re-reads in our failed proxy design.
- **Structure is never dropped** — imports, signatures, decorators.
- **Commitments are verified.** If pruning would drop a path, number,
  identifier or rule, the output passes through untouched.
- **Fails open.** Any error prints nothing and exits 0.

## Why client-side and not a proxy

A proxy edits the request *after* the client built and cached it, so the
client keeps replaying originals and every edit forces a re-cache — and
cache-write costs **12.5x** cache-read. We measured four proxy
configurations at −36%, −74%, −196% and −0.2% (`docs/FINDINGS.md` Part 2).

A hook changes what the client itself stores. First live A/B task:
cache-write went **down** (20,700 → 6,526) instead of up, and cost fell
27.7%.

## Uninstall

```bash
jettison unoptimize
```

Removes the agent file, the fenced `CLAUDE.md` block and only the
Jettison hook entry. Foreign hooks and existing instructions are left
untouched, and an unparseable `settings.json` is refused rather than
overwritten.
