# Agent guidance

Always run the full lint suite with `npm run lint` before committing any changes, and fix every warning it reports rather than suppressing it.

Use conventional commit messages (feat:, fix:, chore:) for every commit you create in this repository.

The staging deployment happens automatically when main is green; never deploy to production without an approval from the release manager.

All API calls must go through the client in src/api/client.ts, never raw fetch. Timeouts default to 30 seconds and must be configurable per call site.
