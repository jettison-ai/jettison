# Security Policy

## Reporting a vulnerability

**Do not open a public issue for a security vulnerability.**

Report it privately through GitHub Security Advisories:

> **[Security](https://github.com/jettison-ai/jettison/security) → Advisories →
> Report a vulnerability**
> (direct link: <https://github.com/jettison-ai/jettison/security/advisories/new>)

That opens a private thread visible only to maintainers, and it is the
preferred channel. If you cannot use it, email **saurabh.ssy@gmail.com** with
`SECURITY` in the subject line.

Please include:

- what the vulnerability lets an attacker do, and who the attacker has to be
  (a malicious MCP server? a hostile tool result? someone with local access?);
- the affected component (scanner, compiler, registry, proxy, verifier,
  adapters, CLI) and version or commit;
- reproduction steps, ideally with a minimal fixture config rather than your
  real setup;
- your OS and Python version.

**Please do not include real prompts, message content, API keys or private
tool schemas in a report.** A minimized fixture is more useful and safer for
both of us.

### What to expect

| | Target |
|---|---|
| Acknowledgement | within 3 business days |
| Initial assessment (severity + whether it's in scope) | within 7 days |
| Fix or documented mitigation for confirmed high-severity issues | within 30 days |

Jettison is currently a small project (`0.x`, Development Status: Alpha)
maintained by a single maintainer; these are good-faith targets, not an SLA.

We will credit you in the advisory and the release notes unless you prefer
otherwise. Please give us a reasonable window to ship a fix before public
disclosure. We do not currently run a paid bug bounty.

## Supported versions

| Version | Supported |
|---|---|
| `0.1.x` | Yes — current release line |
| `main` | Yes — fixes land here first |
| anything older | No |

Jettison is pre-1.0: fixes go to the latest minor release line, and there are
no long-term support branches. Upgrade to the latest `0.x` before reporting.

Vulnerabilities in the pinned upstream `headroom-ai` package should be reported
to [Headroom](https://github.com/chopratejas/headroom); tell us too, so we
can move the pin.

## Threat model — what Jettison actually touches

Stated plainly, because the honest answer is "quite a lot":

- **Jettison is a local proxy that sees everything.** When you run
  `jettison wrap`, requests from your agent client are routed through a proxy
  running on your own machine. It sees the full prompt, the full conversation
  history, every tool schema and every tool result — in cleartext, because it
  has to rewrite them.

- **It never transmits your content anywhere.** Content goes exactly one place:
  onward to the provider you were already sending it to (optionally via
  Headroom's local proxy first). There is no Jettison server. There is no
  phone-home. No prompt, message, file path, repository name, tool name or
  schema is sent to us, ever.

- **Telemetry is opt-in and aggregate-only.** It is off by default and behind
  **two** independent switches: `JETTISON_TELEMETRY=1` turns collection on, and
  `JETTISON_TELEMETRY_ENDPOINT` names the collector. There is deliberately no
  default endpoint, so flipping the flag alone still transmits nothing. When
  both are set, one aggregate report per session is sent at shutdown: an
  anonymous install id, aggregate tokens/dollars avoided with their
  measured/estimated label, client type and Jettison version. Never content,
  never paths, never tool names, never identifiers — `jettison/telemetry/`
  enforces a closed payload vocabulary and refuses to send anything outside it.
  The full contract is in [docs/TELEMETRY.md](docs/TELEMETRY.md). A payload key
  that escapes that vocabulary is a vulnerability; report it.

- **`jettison audit` launches locally-configured MCP servers as
  subprocesses.** To measure tool schemas exactly, `audit` reads your client's
  MCP configuration and *starts each stdio server* — running the commands
  already in that config — then speaks MCP (`initialize` → `tools/list`) to it
  and shuts it down. It does not add, modify or invent servers, and it never
  calls a tool; but it does execute what your config says to execute. If you
  do not want that (an untrusted config, a server with side effects at
  startup), use `jettison audit --no-launch`, which produces clearly-labeled
  config-only estimates instead.

- **Local state lives under `~/.jettison/`.** The savings ledger and the
  per-request verifier audit log (`~/.jettison/audit/records.jsonl`) are
  written there so parity claims are checkable. These files describe your own
  requests: treat them as sensitive, and scrub them before attaching anything
  to a public issue.

- **Content that reaches Jettison is untrusted input.** Tool results, MCP
  server responses and instruction files can all be attacker-influenced.
  Parsing bugs, path traversal in scanner file discovery, or anything that lets
  such content escape the data plane and affect execution is in scope.

### In scope

- Anything that causes Jettison to transmit user content to an unintended
  destination.
- Code execution triggered by scanned or proxied content (malicious MCP server
  response, hostile tool result, crafted instruction file).
- Path traversal or arbitrary file reads via scanner/config discovery.
- Leakage of credentials or content into logs, the savings ledger, the audit
  log, `jettison share` output, or error messages.
- Verifier bypasses that let an optimized request drop a security-relevant
  commitment (for example, silently dropping a "never push to production" rule
  from the context).
- Auth headers being forwarded to the wrong upstream, or bypass-header handling
  that leaks credentials.

### Out of scope

- Vulnerabilities in the agent client, the MCP servers you configure, or the
  provider APIs — report those upstream.
- The fact that `audit --no-launch` figures are estimates, or any other
  documented limitation in [docs/LIMITATIONS.md](docs/LIMITATIONS.md).
- Attacks requiring an attacker who already has full local code execution as
  your user (they can read your prompts without Jettison's help).
- Denial of service against your own local proxy.
- Missing hardening on a service you deliberately exposed to a network:
  the proxy is meant to bind to localhost. Exposing it publicly is a
  deployment choice, not a Jettison vulnerability — though we will happily
  take reports of *unsafe defaults*.
