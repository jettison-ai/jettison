# Changelog

Notable changes per release. Corrections to published numbers are listed
here too — a retraction is a change worth announcing.

## 0.1.1 — 2026-07-26

First public release. `0.1.0` was tagged while both repositories were still
private and is superseded; it carries a bug that makes the hook
non-reversible on a normal install.

### Fixed

- **`jettison unoptimize` silently left the `PostToolUse` hook installed.**
  The hook command is written as the console-script path when
  `jettison-hook` is on `PATH` and as `-m jettison.hook.runner` otherwise,
  but recognition matched only the dotted module name. On a normal `pip
  install` — the shape real users get — `is_installed()` reported the hook
  as absent and `uninstall_hook()` removed nothing. Both command shapes are
  now pinned by tests that patch the command directly rather than depending
  on the test runner's `PATH`.
- Corrected the Headroom repository URL throughout (`chopratejas/headroom`;
  the previously referenced path does not exist).

### Changed

- **Headline claim reframed around what reproduces.** Published numbers are
  now 20–25% fewer turns, 19–27% faster and 21–33% fewer tokens, each
  reproduced across four separate live A/B runs. **Dollar savings are no
  longer published as a claim**: measured cost effects ranged from +10.6% to
  +2.4% with confidence intervals spanning zero, because the savings land in
  cached input tokens that bill at roughly a tenth of fresh input.
- Documentation now separates the client-side path that ships from the
  modules retained only so the proxy negative result stays reproducible.

### Added

- `jettison verify` — runs the same paired A/B we use internally against the
  user's own repository and reports the real difference, including when that
  difference is negative.
- Coexistence detection for Headroom, Caveman and swe-pruner. If Caveman is
  installed, Jettison skips its own response-style block; two sets of style
  instructions cost tokens and can contradict each other. Nothing disables
  or edits another tool's configuration.
- Repo map and importance ranking (technique from RepoMaster, MIT) and
  query-aware read pruning (technique from SWE-Pruner, MIT,
  arXiv:2601.16746). Reimplemented, credited in [NOTICE](NOTICE).

### Known limitations

- Every published number is Claude Code. Codex and Cursor are supported but
  unmeasured.
- Savings concentrate in exploration and comprehension work. Pure authoring
  is closer to neutral.
- The live A/B is n=6 with a wide confidence interval. It is directionally
  positive, not statistically significant. See [docs/LIMITATIONS.md](docs/LIMITATIONS.md).

## 0.1.0 — superseded

Tagged while the repositories were private. Not recommended; see the
reversibility bug above.
