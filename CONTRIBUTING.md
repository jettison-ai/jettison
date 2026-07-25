# Contributing to Jettison

Jettison cuts tokens an agent never uses, without changing its answers and
without breaking provider caching. Almost every rule below exists because one
of those three properties is easy to break by accident and expensive to notice
later.

Read [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) once before your first
change; it maps the modules to what they actually do.

---

## Dev setup

Python **3.10+** is supported; development happens on **3.13**. CI runs the
full matrix (3.10, 3.11, 3.12, 3.13) on Ubuntu.

With [uv](https://docs.astral.sh/uv/) (recommended):

```bash
git clone https://github.com/jettison-ai/jettison
cd jettison
uv venv --python 3.13
source .venv/bin/activate
uv pip install -e ".[runtime,dev]"
```

With stdlib venv + pip:

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip
python -m pip install -e ".[runtime,dev]"
```

What the extras mean:

| Extra | Contents | When you need it |
|---|---|---|
| *(none)* | `click`, `rich`, `tiktoken` | `jettison audit` only. Token counts fall back to a chars/4 estimator and are labeled `estimated`. |
| `[runtime]` | `headroom-ai` (pinned `>=0.32,<0.33`), `fastapi`, `uvicorn`, `httpx` | The proxy, `wrap`, and Headroom-backed token counting. |
| `[dev]` | `pytest`, `pytest-asyncio` | Running the tests. |
| `[docs]` | `mkdocs`, `mkdocs-material` | Building the docs site (`mkdocs serve`). |
| `[all]` | `jettison-ai[runtime]` | Convenience alias. |

**Contributors want `[runtime,dev]`.** `tests/test_proxy_e2e.py` imports
`httpx` and builds the FastAPI app at module import, so the suite does not
collect without `[runtime]`.

Headroom's minor version is pinned deliberately — upstream moves fast and its
compression stack is retained unmodified. Bumping the pin is its own PR, with
the parity harness rerun against the new version.

## Running things

```bash
python -m pytest -q                  # full suite: offline, no network, ~1s
python -m pytest tests/test_verifier.py -q
python -m pytest -q -k cache         # by keyword

jettison --version
jettison audit --help
jettison audit --project tests/fixtures/demo_project --json   # the CI sanity check
```

`asyncio_mode = "auto"` is set in `pyproject.toml`, so async tests need no
decorator.

The test suite must stay **offline and deterministic**. The proxy end-to-end
test drives a scripted fake provider; add new integration tests the same way.
A test that needs the network, an API key, or a real MCP server will not be
merged.

## The non-negotiables

These are not style preferences. A PR that breaks one of them is wrong even if
every test passes.

### 1. The stable prefix is byte-stable

Provider cache reads cost roughly a tenth of fresh input. Standing context is
the most cacheable thing an agent sends. An optimizer whose prefix changes
between requests saves tokens on paper and *loses money in reality*.

So: the capability index, the compiled instructions, and the meta-tool
definitions must serialize to **identical bytes for identical inputs**. Sorted
maps, no timestamps, no session ids, no counters, no dependence on file
discovery order or set iteration order. Every compiled artifact carries a
content hash; same input state must produce the same hash.

Dynamic content goes to the **tail** of the context only — schemas fetched by
`jettison_load_capabilities` arrive as tool results, never injected into the
prefix. The outbound tool list only ever *grows* within a session, sorted by
name: one cache bust per newly loaded tool, then stable again. Never remove a
tool mid-session.

Full reasoning and the enforcement rules: [docs/CACHE_SAFETY.md](docs/CACHE_SAFETY.md).

### 2. Determinism — no clock, no RNG in anything touching request bytes

The compiler, the index renderer and the registry have no clocks, no random
number generators and no environment-dependent branches. Dedup dictionaries are
keyed by content hash, not discovery order. If you genuinely need randomness
(sampling, RCT arm assignment), derive it from an explicit seed or a content
hash and document it.

Practical consequence: `dict` ordering, `set` iteration, `os.walk` order and
`glob` order are all things you must sort before they can influence output.

### 3. Every published number is labeled `measured` or `estimated`

`measured` means an exact tokenizer or a resolved provider price produced it.
`estimated` means a calibrated estimator or a fallback table did. Labels
propagate **pessimistically**: any aggregate containing an estimated component
is itself `estimated`.

This applies to code (`TokenCount.label`, `report.token_label`), to CLI output,
to docs, and to anything you put in a PR description. Illustrative figures —
like the sample output in the README — must be explicitly marked as
illustrative and never presented as benchmarks.

### 4. Benchmark numbers come from the parity harness. Only.

Any number that describes how well Jettison performs comes from
[jettison-parity](https://github.com/jettison-ai/jettison-parity), run on a
**named, disclosed config**, with the config's content hash reported alongside
it. Not from a local one-off, not from `jettison audit` on your own laptop,
not from a vibes-based estimate.

```bash
git clone https://github.com/jettison-ai/jettison-parity
cd jettison-parity
pip install -e .                     # needs this jettison checkout importable
parity run --family all --config configs/mcp-heavy
parity run --family parity --middleware none --config configs/mcp-heavy   # baseline arm
```

The task-parity family exits nonzero on any regression — a completion drop, a
wrong tool, a lost required parameter, or a lost critical fact. The `parity`
workflow enforces this on PRs. Methodology: [docs/BENCHMARKS.md](docs/BENCHMARKS.md).

### 5. Answer parity is the product

Cutting context is easy; cutting it without changing answers is the whole
point. The Commitment Verifier extracts what the original context commits to —
tool names and required parameters, numbers with units, file paths,
identifiers, hard rules, output-format requirements — and restores the original
span whenever the optimized version would drop one.

If you add an optimization, you must also answer: *what commitment could this
drop, and does the verifier catch it?* When in doubt, over-preserve. A tool
list that fails verification is sent untouched, by design.

### 6. Apache-2.0 and the obligations toward Headroom

Jettison is Apache-2.0 and is a loosely-coupled fork/extension of
[Headroom](https://github.com/headroomlabs-ai/headroom), also Apache-2.0.
Contributions are accepted under Apache-2.0; by opening a PR you confirm you
have the right to contribute the code under that license.

Concretely, when your change involves Headroom-derived code:

- **Keep the notices.** Retain the original copyright, license and attribution
  notices in any file derived from Headroom (Apache-2.0 §4(a), §4(c)).
- **Mark modifications.** If you modify derived code, say so prominently in the
  file (§4(b)).
- **Update [NOTICE](NOTICE).** It lists which components are retained from
  Headroom and which modules are original to this repo. New derived components
  go in it; new original modules go in the original-modules list.
- **Prefer depending over copying.** The `headroom-ai` package is a pinned
  dependency precisely so its compression stack runs unmodified. Vendoring
  Headroom source into this repo needs a reason.
- **No trademark claim.** "Headroom" is a mark of its owners. Do not imply
  affiliation, endorsement or sponsorship in code, docs or UI strings.

The same applies to any other third-party code: compatible license, attributed
in `NOTICE`, headers intact.

### 7. Nothing leaves the machine

Jettison sees full prompts and tool schemas. It transmits none of it. The only
outbound path that is not "onward to your provider" is telemetry, which is
opt-in, aggregate-only, and behind two switches (`JETTISON_TELEMETRY=1` **and**
`JETTISON_TELEMETRY_ENDPOINT`, with no default endpoint).

`jettison/telemetry/` is written as a **closed vocabulary**: `PAYLOAD_FIELDS`
is the complete set of keys that may leave the machine, `build_payload` is pure
so the exact bytes are assertable without a network, and `maybe_send` refuses
any payload carrying a key outside the set. If you touch that module: add the
field to `docs/TELEMETRY.md` first — that page is the binding contract — then
to `PAYLOAD_FIELDS`, then add a test asserting the exact payload. A PR that
adds an outbound call carrying prompts, paths, tool names, project names or
user identifiers will be rejected.

## New client adapters

Client adapters live in **`jettison/adapters/`** (`clients.py` for the adapter
table, `runner.py` for the launch/watch machinery). Currently supported:
`claude`, `codex`, `cursor`, `cline`, `opencode`, `openclaw`.

There are two shapes:

- **Launch adapters** — the client is a binary. Set the base-URL env vars and
  exec it (`ClientAdapter(name=..., binary="claude", env_vars={...})`).
- **Watcher adapters** — the client is a GUI that reads its config from a
  settings UI. `binary=None`, and `setup_lines` prints the exact lines the user
  must paste while the proxy stays in the foreground.

To add one:

1. Add a `ClientAdapter` entry to `ADAPTERS` in `jettison/adapters/clients.py`.
2. Add config discovery for the client to `jettison/scanner` so
   `jettison audit -c <client>` finds its MCP config, skills and instruction
   files. `SUPPORTED_CLIENTS` derives from the discoverer table — do not
   hardcode a second list.
3. Add a test with a fixture config directory. Do not test against a real
   installation.
4. Note any **native deferred tool loading** the client has. Where a client
   already defers schemas, Jettison must step aside for that surface rather
   than double-optimize — this is a correctness requirement, not a nicety (see
   the `ENABLE_TOOL_SEARCH` handling for Claude Code, and
   [docs/LIMITATIONS.md](docs/LIMITATIONS.md)).
5. Update the supported-clients list in `README.md` and the client dropdown in
   `.github/ISSUE_TEMPLATE/bug_report.yml`.

## Pull requests

- Branch from `main`, keep the PR focused, write a real description.
- Fill in the PR checklist honestly — reviewers read it as claims, not ritual.
- CI must be green: the 3.10–3.13 matrix, the bare-install job, and the CLI
  sanity checks. The `parity` workflow must show no task-parity regressions.
- Commits: imperative subject lines, explain *why* in the body when it isn't
  obvious.
- New dependencies need justification. The bare package deliberately has three.

## Reporting bugs and vulnerabilities

Bugs: use the issue forms. Include `jettison audit` output and whether the
problem survives `x-jettison-bypass: true` — that single header separates
"Jettison broke it" from "it was already broken".

Security vulnerabilities: **never in a public issue.** See
[SECURITY.md](SECURITY.md).

## Code of Conduct

This project follows the [Contributor Covenant](CODE_OF_CONDUCT.md).
