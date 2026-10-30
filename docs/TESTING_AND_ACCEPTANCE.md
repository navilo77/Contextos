# Testing and Acceptance

> **Scope note:** These checks cover the current MVP baseline. The target adds database, workflow recovery, frontend, evaluation, and operational gates described in `MASTER_IMPLEMENTATION_PLAN.md`.

## PostgreSQL integration tests

The repository integration suite must run against a dedicated, disposable PostgreSQL database that has been migrated with the current Alembic head. It is intentionally not backed by SQLite or ORM-created test tables: database locks, composite constraints, cascades, and PostgreSQL JSONB/check behavior are part of the contract.

Set `CONTEXT_OS_DATABASE_URL` and `CONTEXT_OS_TEST_DATABASE_URL` to the same test-only `postgresql+asyncpg` URL whose database name ends in `_test`, set `CONTEXT_OS_RUN_POSTGRES_INTEGRATION=1`, migrate it with `uv run alembic upgrade head`, then run `uv run pytest tests/integration`. The opt-in and database-name guard prevent an ambient application URL from triggering destructive test setup. Never point the test URL at a database containing user data. The CI PostgreSQL job provisions an isolated service, migrates from empty, runs `alembic check`, then executes the integration suite.

## Required automated coverage

Use the repository's configured test runner. Cover at least:

### Intake and clarification

- Valid idea is accepted; empty and over-limit input receive clear validation errors.
- Unknown details remain unknown rather than becoming confirmed facts.
- Clarification questions are bounded, prioritized, and editable by the user.
- Provider failure and malformed structured output produce explicit errors.
- Invalid output gets no more than one repair attempt and then fails clearly.

### Generation

- Compact and detailed profiles produce the correct conditional file sets.
- Confirmed facts, accepted proposals, assumptions, and unresolved questions remain distinguishable.
- Generated requirements have stable identifiers and acceptance criteria.
- Non-applicable topics are omitted with a reason rather than emitted as empty templates.
- Output language follows the user's selected language or the idea language default.

### Validation and archive

- JSON Schema validation succeeds for valid context and rejects invalid context.
- Reject path traversal, absolute paths, duplicate paths, and unsafe slugs.
- Detect unresolved template markers, broken internal links, and configured secret values.
- Manifest hashes match file contents.
- ZIP reopens successfully, contains exactly the declared files, and has one project root.
- A failed validation never returns a success-shaped downloadable package.

### Web and privacy

- A user can complete the whole browser flow and download the ZIP.
- The external processing disclosure appears before provider use.
- A fake provider is used in automated tests; tests do not require real credentials or network access.
- API keys and idea content are not exposed in HTML errors or application logs.
- State-changing forms have appropriate CSRF protection.

## Acceptance criteria

The MVP is accepted only when all are true:

1. A new user can start the app using documented local setup instructions.
2. The user can submit an idea, answer/edit clarifying questions, review the summary, and choose a package profile.
3. The user can generate and download a valid package conforming to `GENERATION_CONTRACT.md`.
4. Unconfirmed details are visibly labeled; the generator does not silently invent project facts.
5. Provider configuration and provider errors are explained clearly without leaking credentials.
6. Invalid content or failed safety checks block download and show actionable errors.
7. The archive can be opened and its contents and manifest verified by automated tests.
8. No Aura-specific content or technology is injected into generated projects by default.
9. All focused tests and configured checks pass, and the coding agent reports the exact commands run.

## Manual smoke test

1. Start the app with a mock provider or configured development endpoint.
2. Submit a generic non-commerce idea and leave technology preference unknown.
3. Confirm the UI asks only material questions and shows uncertainty distinctly.
4. Generate both compact and detailed packages.
5. Open each ZIP and inspect paths, manifest, links, and files.
6. Search the output for `Aura`, secrets, placeholders, and unsupported claims.
7. Force a provider/validation error and verify no download is offered as successful.
