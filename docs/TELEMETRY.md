# Telemetry

**Off by default. Opt-in only. Disclosed here in full.**

> Status: implemented in `jettison/telemetry/`, against this page as the
> contract. It stays inert unless you set **both** `JETTISON_TELEMETRY=1` and
> `JETTISON_TELEMETRY_ENDPOINT=<url>` — there is no default endpoint, so
> flipping the flag alone still transmits nothing. When it is on, `jettison
> wrap` prints the disclosure notice and sends **one aggregate report per
> session**, at shutdown, on a background thread.

## What would be collected (with `JETTISON_TELEMETRY=1`)

- an anonymous install counter (random UUID, no linkage to any identity)
- aggregate tokens avoided and estimated dollars avoided (totals only, with
  the `measured`/`estimated` label of the price table they came from)
- client type (e.g. "claude", "openclaw") and Jettison version

## What is never collected

- prompts, messages, or any request/response content
- file paths, repository names, project names
- tool names or schemas
- API keys, user identifiers, email addresses, IP-based profiles

## Methodology for published aggregates

Any publicly shared aggregate ("Jettison users avoided N tokens this month")
will state: the collection window, the number of reporting installs, that
figures are opt-in (and therefore a lower bound with self-selection bias), and
the measured/estimated label composition. Aggregates are never broken down in
ways that could identify an individual install.

## The local-only alternative

Everything telemetry would report — and much more — is available locally:

```
jettison savings                # dashboard
jettison savings --export savings.json   # dated JSON export
jettison savings --export savings.csv    # dated CSV export
```

Exports are yours; adopter case studies are built from *user-shared* exports,
never from telemetry.
