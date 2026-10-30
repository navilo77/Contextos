# Decision 0001: Initial release boundary and data handling

## Status

Chosen defaults for the initial implementation. These defaults are local-only and do not authorize a public deployment.

## Context

The existing prototype is ephemeral and local. The target needs durable projects and resumable generation, while the user wants a robust Context OS that produces project-context packages. Public hosting and autonomous coding-agent execution introduce substantially different security and privacy risks and are not necessary for the initial goal.

## Decisions

1. The initial release is a single-user, local-first application bound to localhost. It has no user accounts, teams, analytics, or public deployment.
2. PostgreSQL is the source of truth for projects, revisions, documents, workflow runs, and checkpoints. Local development uses the repository's documented Docker Compose setup.
3. Project content is retained until the user deletes the project. Deletion removes the project content, documents, runs/checkpoints, and exports. Audit events must not retain idea text or secrets.
4. No backup/restore guarantee is made for the local release. Backup and restore become mandatory before any production/public release.
5. Send user idea/answer content to Google Gemini only after clear disclosure and affirmative consent. Do not fetch URLs from user content or send content to other external services.
6. Initial generated package profiles are compact and detailed. Language defaults to the idea language and can be explicitly selected by the user.
7. Context OS generates documentation and a ZIP only. It does not write or execute the described application, operate a coding agent, run user-provided commands, or deploy.
8. Public/multi-user hosting requires a separate explicit decision, security review, identity/authorization, privacy review, and passing Gate E.

## Consequences

- Durable persistence changes the MVP's no-disk-storage behavior; consent, deletion, and data inventory must be implemented and tested before the persistence phase is complete.
- Local PostgreSQL and Docker are required for the durable target. A clear startup/preflight error is required if they are unavailable; do not silently fall back to ephemeral storage.
- The application must make the localhost-only boundary visible and enforce loopback binding by default.
- All generated output remains user-reviewed, schema-validated, and safe to package; model output is never executable.
- Public exposure remains a blocked release gate, not a deployment option enabled by configuration alone.

## Revisit when

The owner explicitly changes the initial audience, persistence/retention policy, provider, or deployment boundary. Any change requires updates to the product, security, database, API, and acceptance contracts.
