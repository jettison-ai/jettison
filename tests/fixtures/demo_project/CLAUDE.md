# Project instructions

This project is a demo web application built with TypeScript and React.

Always run the full lint suite with `npm run lint` before committing any changes, and fix every warning it reports rather than suppressing it.

Use conventional commit messages (feat:, fix:, chore:) for every commit you create in this repository.

When editing database migration files, never modify an existing migration; always create a new migration file with the next sequence number.

## Code style

Prefer functional components with hooks over class components. Keep components under 200 lines. Extract shared logic into custom hooks in src/hooks.

All API calls must go through the client in src/api/client.ts, never raw fetch. Timeouts default to 30 seconds and must be configurable per call site.
