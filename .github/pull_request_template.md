<!--
Thanks for contributing to Jettison. Keep the PR focused; the checklist below
is the same set of rules CONTRIBUTING.md describes, in review form.
-->

## What this changes

<!-- One paragraph. What did you change and why? -->

Closes #

## How it was verified

<!-- Commands you actually ran, with results. "Tests pass" is not a result. -->

```
python -m pytest -q
jettison audit --project tests/fixtures/demo_project --json | head
```

## Checklist

**Correctness**

- [ ] `python -m pytest -q` passes locally (install with `pip install -e ".[runtime,dev]"`).
- [ ] New behaviour has a test. Bug fixes have a test that fails without the fix.
- [ ] Public behaviour changes are reflected in `docs/` (`ARCHITECTURE.md`, `LIMITATIONS.md`, `CACHE_SAFETY.md` as applicable).

**Cache safety** — see [docs/CACHE_SAFETY.md](../blob/main/docs/CACHE_SAFETY.md)

- [ ] The stable prefix (capability index + compiled instructions + meta-tool
      definitions) still serializes to identical bytes for identical inputs.
- [ ] Nothing request-varying (timestamps, session ids, counters, load order,
      set iteration order) entered the prefix.
- [ ] Dynamic content, if any, goes to the context tail only.
- [ ] The outbound tool list still only grows within a session, sorted by name.

**Determinism**

- [ ] No clock, no RNG, no environment-dependent branch in any code path that
      affects request bytes. Seeds, where randomness is unavoidable, are explicit.

**Answer parity**

- [ ] The verifier still restores original content when an optimization could
      drop a commitment (tool contracts, numbers + units, paths, identifiers,
      hard rules, output-format requirements).
- [ ] Nothing here can make a request drop a fact the original context committed to.

**Measurement honesty**

- [ ] Every number this PR introduces or changes carries a `measured` or
      `estimated` label, and aggregates take the weaker label.
- [ ] Any benchmark number quoted in the PR, docs, or code comments comes from
      the `jettison-parity` harness on a named config — not from a local
      one-off, not from `audit` output on the author's own machine.
- [ ] The `parity` workflow shows no task-parity regressions (or the regression
      is explained and justified below).

**Licensing** — see [NOTICE](../blob/main/NOTICE)

- [ ] Any code derived from [Headroom](https://github.com/headroomlabs-ai/headroom)
      (or any other Apache-2.0 project) is attributed in `NOTICE`, retains its
      copyright and license headers, and modifications are marked.
- [ ] No code copied in from an incompatible license.
- [ ] I have the right to contribute this under Apache-2.0.

**Privacy**

- [ ] No prompt, message, tool schema, file path or repo name is transmitted anywhere.
- [ ] If `jettison/telemetry/` changed: `docs/TELEMETRY.md` was updated first,
      the new key is in `PAYLOAD_FIELDS`, a test asserts the exact payload, and
      it is still opt-in (`JETTISON_TELEMETRY` + `JETTISON_TELEMETRY_ENDPOINT`,
      no default endpoint) and aggregate-only.

## Notes for the reviewer

<!-- Trade-offs, things you're unsure about, follow-up work. -->
