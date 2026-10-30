# API and Workflow Contract

**Status:** The broader contract remains the target for phased implementation. Phase 2 now includes PostgreSQL-backed project CRUD, revision editing, cursor pagination, clarification/answer persistence, document generation, review, validation, and ZIP export APIs. The Next.js workspace is connected for the complete current project workflow; the server-rendered workflow has not yet migrated.

## API conventions

- Base path: `/api/v1`; JSON request/response bodies except the SSE progress endpoint and ZIP download.
- OpenAPI generated from FastAPI/Pydantic is authoritative for concrete wire schemas. Generate the frontend client from OpenAPI; do not hand-maintain duplicate TS request types.
- Project revision edits require an expected revision and return `409 revision_conflict` when stale. Operations bound to a current revision persist or verify that revision explicitly.
- Run creation accepts an idempotency key. Repeating the same key for the same project/request returns the existing run; a key reused with a different request returns `409 idempotency_conflict`.
- Paginated list APIs use bounded `limit` and opaque `cursor`; enforce a maximum page size of 100.
- Every response includes/returns a request ID. Do not include raw provider errors, prompts, idea text, stack traces, SQL, or secrets in client error responses.
- All resource IDs are opaque UUIDs. Public deployment auth is out of scope for this API version; the local app binds only to loopback.
- Browser CORS is limited to the configured loopback frontend origin and does not allow credentials. Keep the frontend origin and browser-visible API URL aligned with the loopback ports.

## Initial endpoint responsibilities

| Method and route | Responsibility | Success result |
|---|---|---|
| `POST /api/v1/projects` | Validate intake and create first project revision; require consent before any provider call. | Project resource and current revision |
| `GET /api/v1/projects` | List local user's projects with cursor pagination. | Project summaries |
| `GET /api/v1/projects/{project_id}` | Read project and revision. | Project resource |
| `PATCH /api/v1/projects/{project_id}` | Apply user edits as a new revision using optimistic concurrency. | Updated project and revision |
| `GET /api/v1/projects/{project_id}/workflow` | Resume the current revision's questions/answers, documents, latest validation, and exports. | Workflow snapshot |
| `POST /api/v1/projects/{project_id}/clarifications` | Start discovery or persist user answers/unknowns. | Run reference and/or question list |
| `POST /api/v1/projects/{project_id}/runs` | Start one idempotent workflow. | Run resource |
| `GET /api/v1/runs/{run_id}` | Read durable state, blockers, progress, safe error, and current revision. | Run resource |
| `GET /api/v1/runs/{run_id}/events` | Stream ordered progress events; reconnect using last event ID. | `text/event-stream` |
| `POST /api/v1/runs/{run_id}/resume` | Submit only the answer/approval required by the active interrupt. | Updated run resource |
| `GET /api/v1/projects/{project_id}/documents` | List current immutable document revisions. | Document summaries |
| `GET/PATCH /api/v1/projects/{project_id}/documents/{document_id}` | Read or user-edit a document; edits create a revision and invalidate stale validation/export. | Document revision |
| `POST /api/v1/projects/{project_id}/validate` | Run deterministic checks against a specific revision. | Validation report |
| `POST /api/v1/projects/{project_id}/exports` | Export only a reviewed, validated immutable revision. | Export metadata |
| `GET /api/v1/projects/{project_id}/exports/{export_id}` | Download the verified ZIP. | ZIP bytes |
| `DELETE /api/v1/projects/{project_id}` | Cancel active run and transactionally delete project content and checkpoints. | `204 No Content` |

### Implemented Phase 2 project slice

- `POST /api/v1/projects` validates bounded intake and atomically stores a project, its first revision, and user-provided source records. It does not call an AI provider.
- `GET /api/v1/projects` lists projects in the local workspace with a bounded `limit` and returns a `next_cursor` when more results exist. Offset pagination remains supported for compatibility.
- `GET /api/v1/projects/{project_id}` returns the project and its current revision ID.
- `PATCH /api/v1/projects/{project_id}` requires `expected_revision`; supplied intake/name/language/profile changes create a new immutable revision. Unchanged source records are linked to the new revision instead of duplicated; changed values append new source records, and empty optional intake fields remove that source from the current revision. A stale revision returns `409 revision_conflict`. The update makes no provider call and starts with no inherited clarification questions/answers.
- Project cursors are versioned, URL-safe opaque tokens bound to the last row's update timestamp and ID. Invalid cursors and mixing a cursor with a non-zero offset return safe `422` errors. Pages are workspace-scoped and capped at 100 projects.
- `POST /api/v1/projects/{project_id}/clarifications` requires affirmative `{"consent": true}` before sending the stored idea/intake to Google Gemini, then persists the disclosure version and revision-scoped questions. Repeated requests return the persisted question set instead of making another provider call.
- `GET /api/v1/projects/{project_id}/clarifications` resumes the current revision's stored questions and latest answers after app recreation.
- `PUT /api/v1/projects/{project_id}/clarifications/answers` saves bounded answer/unknown/deferred states. Answer text is stored only as a project source and linked to its revision and question; changing an answer appends a new answer record.
- `POST /api/v1/projects/{project_id}/generate` requires affirmative provider consent and an `Idempotency-Key`, generates and validates the package, then stores immutable document contents, hashes, a durable run, and content-minimal run events. Normalized facts, assumptions, constraints, exclusions, requirements, and acceptance criteria are committed atomically with the documents. Confirmed facts link to project sources only when the source mapping is exact; generated assumptions remain unconfirmed. At least one uniquely identified `REQ-*` requirement is required. The run remains `awaiting_user` for review; ZIP bytes are not persisted.
- `GET /api/v1/projects/{project_id}/documents` lists the current revision's generated documents; `GET /api/v1/projects/{project_id}/documents/{document_id}` returns one project-scoped document body.
- `GET /api/v1/projects/{project_id}/workflow` returns the current revision's clarification questions and latest answers, document summaries, latest validation report/counts, and up to 50 recent export resources. It allows the workspace to restore durable progress after navigation or application restart.
- `POST /api/v1/projects/{project_id}/validate` requires explicit approval of the complete current document set, rechecks package integrity, and stores an immutable report and safe findings.
- `POST /api/v1/projects/{project_id}/exports` requires explicit confirmation and a passed report, reconstructs and verifies a ZIP in memory, and stores only export metadata and document links.
- `GET /api/v1/projects/{project_id}/exports/{export_id}` reconstructs the archive from immutable documents and rechecks document, package, and ZIP hashes before download. ZIP bytes are never stored.
- `DELETE /api/v1/projects/{project_id}` hard-deletes project-linked data and writes a content-minimal `project.deleted` audit event.
- PostgreSQL connection settings are optional for backward-compatible HTML-only demonstrations. With PostgreSQL configured, the legacy HTML workflow persists its short-lived session state in `web_sessions`; cookie IDs are hashed at rest, rows expire after 30 minutes and are periodically deleted, and the session payload is capped at 16 MiB. ZIP bytes are reconstructed for download and are not kept in session state. Without PostgreSQL, the HTML-only session remains process-local. When project API routes are used without a configured database, or before migrations are applied, the API returns an explicit non-success error; it never falls back to memory.
- The generator does not create user-approved decisions: provider output is deliberately prevented from marking model suggestions as accepted, and a user decision-review workflow is not implemented. The Next.js UI supports clarification, answer persistence, generation, full-document review, validation, and export. Remaining gaps include user decision approval and reliable requirement-source provenance. These gaps remain before claiming full product/contract completion.

Every project-scoped operation verifies that the requested resource belongs to that project. Unknown IDs return `404` without revealing unrelated local data. The local single-user boundary does not remove the need for these ownership checks; they prevent accidental cross-project writes and ease future isolation.

## Error response

Every non-2xx JSON response uses the shape validated by `schemas/api-error.schema.json`:

```json
{
  "type": "https://context-os.local/problems/revision-conflict",
  "title": "Project revision conflict",
  "status": 409,
  "detail": "Reload the project and apply your changes to the latest revision.",
  "code": "revision_conflict",
  "request_id": "opaque-request-id",
  "errors": []
}
```

`detail` is safe for the user. Field errors may identify invalid field paths but must not echo submitted values. `request_id` correlates redacted logs. Error `code` is stable for clients; title/detail may be localized. A server error never implies partial success.

## Durable run states and transitions

The stable state contract is in `schemas/run-state.schema.json`. Allowed statuses:

- Non-terminal: `queued`, `running`, `awaiting_user`, `blocked`.
- Terminal: `completed`, `failed`, `cancelled`.

Allowed lifecycle:

```text
queued -> running
running -> awaiting_user | blocked | completed | failed | cancelled
awaiting_user -> running | blocked | cancelled
blocked -> running (only after a recorded user correction/approved decision) | cancelled
```

- `completed` requires a frozen document revision and successful export verification.
- `blocked` means a safe user action or a corrected input is required; it is not success.
- `failed` includes a safe error code and a retryability flag. Retry is a new/replayed idempotent action, never an implicit infinite loop.
- `cancelled` is terminal; a new run is required to continue.
- A run may enter `awaiting_user` only with a persisted interrupt kind and a typed prompt/reference.
- User resume is accepted only for an `awaiting_user` run and the matching interrupt. Duplicate resume requests are idempotent.
- Retry/repair budgets are explicit and finite. Validation repair is at most once per document-generation run.
- Persist the state transition and run event transactionally; graph checkpoint and thread ID must correlate to the same project/run.

## Persistence invariants

- Project deletion removes all project-linked revisions, source text, facts, answers, decisions, requirements, documents, runs/events, checkpoints, validation reports, and exports. The database transaction must not leave accessible orphan content.
- Operational/audit records may retain only non-content metadata needed for safety and diagnostics; never retain raw idea text, answers, generated documents, API keys, or provider headers.
- Store explicit consent version/time and provider destination with the relevant run; do not treat an old consent as consent for a newly added provider.
- An export references one immutable document revision and its validation report. Any content edit invalidates its readiness; do not export a changed document under a stale report.
- Use foreign keys, uniqueness constraints, and transactions as the integrity boundary; ORM validation alone is insufficient.

## Contract change process

Before implementing a contract change, update this document, OpenAPI/schema artifacts, database migration design, traceability matrix, and acceptance tests together. Mark compatibility impact and migration/rollback behavior in the implementation status.
