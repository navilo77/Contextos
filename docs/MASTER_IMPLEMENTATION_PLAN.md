# Context OS — Master Implementation Plan

**Status:** Proposed target architecture; implementation has not started from this plan  
**Audience:** Project owner and the coding agent that will build Context OS  
**Product:** A generic project-context generator. Aura Skincare is reference material only, never a default project or domain assumption.

## 1. Executive summary

Context OS should become a reliable application that takes a person's software idea, asks only the necessary follow-up questions, records what is known versus uncertain, creates a right-sized project documentation package, checks that package, and exports it as a ZIP for a separate coding agent.

The target is a **modular monolith** with one Python backend and clearly bounded business modules, a modern web frontend, PostgreSQL-backed drafts and workflow state, and a bounded LangGraph workflow using LangChain model/provider abstractions. It is not a collection of independently deployed autonomous agents. Specialized responsibilities should initially be deterministic graph nodes and typed generation/review steps inside the one application.

The system must not promise zero errors or guaranteed one-shot application development. It should make errors observable, prevent unsupported facts from becoming requirements, retry bounded failures, report unresolved items, and ask the user whenever an important decision cannot safely be inferred.

## 2. Product boundary and explicit non-goals

### Context OS does

1. Capture and refine a project idea.
2. Maintain provenance for facts, user decisions, assumptions, and unanswered questions.
3. Generate an appropriate project-context/documentation folder from reusable schemas and templates.
4. Run deterministic structural, consistency, security, and completeness validation.
5. Let the user review and correct the draft.
6. Save and resume projects and runs.
7. Export a validated, manifest-backed ZIP for a separate coding agent.

### Context OS does not do in the initial target

- Write or execute the end user's application code.
- Launch or control a coding agent, terminal, browser automation, or deployment.
- Autonomously make business, legal, pricing, medical, security, or architecture decisions.
- Require every generated app to use Context OS's own stack.
- Generate hundreds of documents for a small idea.
- Promise zero defects or that a generated context guarantees correct code.
- Expose a local development instance to the public internet.

Keep application-code generation as a later, separately approved product capability with a new threat model and explicit human controls.

## 3. Current baseline and gaps to close

The current implementation is a useful prototype, not a production-ready agent:

- `app/main.py` mixes routing, HTML rendering, workflow state, and orchestration.
- The UI is hand-built HTML in Python; there is no frontend application or generated API client.
- Sessions live in process memory; restarts lose work and separate workers cannot share it.
- There is no application database, migration system, durable run history, or LangGraph checkpointer.
- Gemini is called directly over `httpx`; there is no LangChain model abstraction or provider capability boundary.
- The workflow is a request/clarification/generation sequence rather than a durable graph with explicit approval and recovery states.
- Project facts have an initial provenance safeguard, but generated claims, requirements, decisions, and documents need end-to-end traceability.
- Validation is an early package-level check, not a comprehensive schema, semantic, cross-reference, and policy pipeline.
- There are tests for the MVP, but no real PostgreSQL, frontend browser, graph-resume, evaluation-set, or end-to-end release gates.
- Existing product/architecture specifications still describe a smaller MVP and must be reconciled with this target before implementation.

Do not delete the working MVP until its valuable behaviors have equivalent tests in the new structure.

## 4. Target architecture

### 4.1 Modular monolith

One backend codebase, one domain model, one release train, and one PostgreSQL database. Modules communicate through Python interfaces/application services rather than calling each other's HTTP endpoints.

Recommended backend modules:

1. **Projects:** project identity, lifecycle, user scope, and versions.
2. **Discovery:** intake answers, clarification questions, fact ledger, decisions, assumptions, and open questions.
3. **Agent runs:** LangGraph creation, status, checkpoints, events, pause/resume, retry limits, and cancellation.
4. **Knowledge and templates:** generic document catalog, versioned template packs, schema catalog, project-type profiles, and source references.
5. **Requirements:** features, functional/non-functional requirements, dependencies, and acceptance criteria.
6. **Architecture:** proposed components, technology choices, rationale, and ADR-like decision records.
7. **Document generation:** typed content generation and rendering to Markdown, JSON, and optional YAML.
8. **Validation:** deterministic validation, cross-document checks, policy checks, review findings, and readiness score.
9. **Artifacts:** immutable document revisions, ZIP construction, manifest/checksums, and downloads.
10. **Provider configuration:** model selection/capabilities and secret-safe provider construction.
11. **Audit and privacy:** user actions, consent records, deletion, retention, and redacted operational events.

Keep authorization and authentication as a boundary module even when the initial app is single-user. Do not scatter ownership checks through handlers.

### 4.2 Frontend

- Next.js App Router with TypeScript, React, and strict type checking.
- Accessible component system using Tailwind CSS and a small set of reusable form, navigation, progress, alert, and review components. Use a component library only if it reduces implementation/maintenance cost; do not make design dependencies part of generated app requirements.
- Zod for browser form validation; backend Pydantic remains authoritative.
- Generate a typed TypeScript client from FastAPI OpenAPI rather than hand-maintaining duplicate API types.
- TanStack Query for server state and mutations; use server-sent events (SSE) for run progress rather than frequent polling.
- Responsive Bangla and English interface, proper Unicode/font rendering, keyboard access, screen-reader labels, clear loading/error/empty states, and WCAG 2.2 AA-targeted checks.
- Never put Gemini credentials in frontend environment variables or browser storage.

Primary screens:

1. Home and project list (empty state included).
2. New project / idea intake wizard.
3. Clarification questions with answer, unknown, and "ask me later" states.
4. Fact/decision review: confirmed, user-approved proposal, assumption, and unknown shown separately with source references.
5. Project scope and package profile selection.
6. Generation progress with resumable run status.
7. Document workspace with navigation, preview/edit, source trace, and validation findings.
8. Export readiness and ZIP download.
9. Project settings, provider status (never reveal key), export/delete project controls.

### 4.3 Backend and API

- FastAPI, Pydantic v2, asynchronous SQLAlchemy 2.x, async PostgreSQL driver, Alembic migrations.
- Version API routes (`/api/v1/...`) and use consistent response/error models, request IDs, pagination, and idempotency for run creation/resume.
- Keep HTTP handlers thin: authentication/authorization, parsing, invoking application services, and returning response models only.
- OpenAPI is the API contract; add contract tests and generate the frontend client from it.
- Use SSE for ordered, resumable-enough progress events; the durable run state remains retrievable with a normal status endpoint.
- Use a transactional outbox only if reliable background delivery is introduced; do not start with a message broker.

Initial API surface (names can evolve during detailed design):

- `POST /api/v1/projects` — create a project from a validated intake.
- `GET /api/v1/projects` and `GET /api/v1/projects/{project_id}` — list and retrieve.
- `PATCH /api/v1/projects/{project_id}` — edit project answers/settings with revision checks.
- `POST /api/v1/projects/{project_id}/clarifications` — request/record follow-up questions and answers.
- `POST /api/v1/projects/{project_id}/runs` — start or resume a generation/validation workflow idempotently.
- `GET /api/v1/runs/{run_id}` — retrieve state, blocking questions, progress, and errors.
- `GET /api/v1/runs/{run_id}/events` — stream progress using SSE.
- `POST /api/v1/runs/{run_id}/resume` — submit user input/approval for an interrupt.
- `GET /api/v1/projects/{project_id}/documents` and `GET/PATCH .../{document_id}` — review and edit versioned artifacts.
- `POST /api/v1/projects/{project_id}/validate` — run deterministic validations.
- `POST /api/v1/projects/{project_id}/exports` and `GET .../{export_id}` — create/download a validated ZIP.
- `DELETE /api/v1/projects/{project_id}` — delete project content according to retention rules.

Use database transactions around project revision + corresponding run/event updates. Concurrent stale edits must return an explicit conflict, not silently overwrite.

### 4.4 Database and persistence

Use PostgreSQL as the application source of truth. Use SQLAlchemy 2.x models and Alembic for every schema change; never create production tables implicitly at app startup.

Core tables (final normalization is a design-task output):

- `projects`: UUID, workspace scope, name/slug, lifecycle status, current revision, created/updated timestamps. Project deletion is hard deletion per the initial data-retention decision; do not retain a soft-delete project row.
- `project_revisions`: immutable snapshots of intake and selected project decisions.
- `idea_sources`: raw user-provided text and source metadata, access controlled and retention-limited.
- `facts`: project-scoped statement, provenance/source, confidence/approval status, revision.
- `clarification_questions` and `clarification_answers`: question, impact, blocking status, answer/unknown state, provenance.
- `decisions`: proposed/accepted/rejected/undecided choice, rationale, decider and timestamp.
- `requirements`, `acceptance_criteria`, and `requirement_dependencies`: stable IDs, priority, origin links, status, and dependency edges.
- `document_templates`/`template_pack_versions`: built-in versioned templates and schemas; user content must not modify system instructions.
- `agent_runs`: graph thread/run ID, state, status, attempt counts, timestamps, safe error code, prompt/template/model versions.
- `run_events`: append-only user-safe progress/audit events; no full idea or secret values in general operational logs.
- `project_documents`: immutable revisions, path, type, content, format, checksum, validation status.
- `validation_reports` and `validation_findings`: rule/version, result, severity, affected document/requirement, resolution status.
- `exports`: manifest, checksum, expiry/status and audit metadata; avoid long-term storage of duplicate ZIP bytes unless justified.
- `audit_events`: who did what, when, and on which project; redact content and credentials.

Use LangGraph's PostgreSQL checkpointer for resumable graph state, in a clearly separated checkpoint schema/connection role where practical. Define thread ID mapping and cleanup. Avoid copying all raw user content into every checkpoint; store references/normalized state and apply retention.

Use local PostgreSQL via Docker Compose for development. Do not add Redis for the first durable single-process release. Add Redis only after a measured need for distributed rate limits, multi-worker queues, or shared cache; it must not become the source of truth.

### 4.5 Agent orchestration with LangChain and LangGraph

Use LangGraph for explicit state transitions, checkpoints, pause/resume, bounded retries, and human-in-the-loop. Use LangChain model/provider abstractions (including the Google GenAI integration) for model calls and typed structured output. Pin compatible dependency ranges and lock exact versions after testing.

The initial graph should be a bounded workflow, not an unconstrained tool-using autonomous agent:

```text
START
  -> validate_intake
  -> discover_known_facts_and_gaps
  -> clarify_if_blocking (human interrupt)
  -> classify_project_profile
  -> draft_scope_and_requirements
  -> draft_architecture_and_relevant_docs
  -> cross_document_consistency
  -> deterministic_validation
  -> repair_once_or_mark_blocked (bounded)
  -> user_review_and_approval (human interrupt)
  -> freeze_document_revision
  -> build_and_verify_export
  -> END
```

Graph rules:

- Define a versioned, typed `GraphState`; persist only fields needed to resume and render progress.
- Assign one stable `thread_id` per run; authorize every resume request against its project owner.
- Checkpoint to PostgreSQL before every user interrupt and resume using LangGraph's documented command/interrupt mechanism.
- Every node has typed input/output, explicit timeout, error mapping, and test coverage.
- Separate pure/deterministic validators from model-generated suggestions.
- Never let model output choose a tool, path, URL, SQL query, filesystem location, or executable command.
- Use structured Pydantic output for extraction/generation and validate it locally.
- Limit the number of clarification questions, model calls, token budgets, total run duration, and repair attempts.
- Use idempotent nodes or persisted node outputs so retries do not duplicate revisions/exports.
- A failed/blocked graph never reports `completed` or enables an export.
- User approval is required before freezing/exporting if unresolved blocking questions, policy findings, or material assumptions remain.
- Do not create a separate deployment or unbounded LLM loop for each "specialist." Model domain roles as bounded graph stages until measured complexity warrants subgraphs.

Provider policy:

- Use Google AI Studio Gemini Developer API through `langchain-google-genai` and `ChatGoogleGenerativeAI` (or its documented current equivalent).
- Keep model name, temperature, token/time limits, and provider capabilities configurable.
- Use the exact environment names documented by the selected library; avoid ambiguous duplicate API-key variables.
- `.env` is local-only; `.env.example` contains placeholders only. Ignore and exclude `.env`, keys, test fixtures containing real credentials, and provider traces from all archives.
- Provide deterministic fake model/provider tests and a provider health/configuration screen that never reveals the key.
- External tracing (for example LangSmith) is off by default. Enabling it requires clear data disclosure and explicit configuration because prompts may contain private ideas.

## 5. Project-doc generation system

Context OS should generate a right-sized **project folder**, not a clone of Aura's contents:

### Always include

- `README.md`: project summary and package instructions.
- `AGENTS.md`: scoped coding-agent instructions that do not override higher-priority instructions or encourage unsafe execution.
- `00-Project/PROJECT_BRIEF.md`: purpose, users, problem, goals, constraints, scope and non-goals.
- `01-Product/REQUIREMENTS.md`: traceable functional/NFR requirements and acceptance criteria.
- `01-Product/USER_FLOWS.md` when relevant.
- `02-Architecture/ARCHITECTURE.md`: component map, boundaries, selected vs undecided technologies, rationale.
- `03-Delivery/IMPLEMENTATION_PLAN.md`: dependencies, ordered milestones and verification steps.
- `04-Quality/TEST_PLAN.md`: acceptance-to-test mapping without fake test commands.
- `context/PROJECT_CONTEXT.json`: schema-validated facts, origins, decisions, assumptions, open questions, selected profile and document registry.
- `context/OPEN_QUESTIONS.md`: unresolved decisions and implementation impact.
- `manifest.json`: schema/template versions, generated time, included files, checksums, omitted topics, and validation results.

### Include conditionally

- `02-Architecture/ADRs/` for meaningful decisions or unresolved alternatives.
- `03-Data/DATA_MODEL.md` and migrations guidance only if data persistence is in scope.
- `04-API/API_CONTRACT.md` and OpenAPI starter only if an API is in scope.
- `05-Security/THREAT_MODEL.md` and `SECURITY_REQUIREMENTS.md` when there is data, identity, payment, AI, external access, or sensitive functionality.
- `06-Operations/DEPLOYMENT.md`, `.env.example`, monitoring/backup instructions when the user requests deployable software.
- `07-Testing/TEST_CASES/` for meaningful multi-step acceptance workflows.
- `integrations/` only for confirmed integrations.
- Templates, YAML/JSON schemas, and traceability matrices only when they help the target coding agent.

Package rules:

- Detect app profile(s) from explicit user choices and facts; support a generic/custom profile. Never infer that every project is e-commerce or AI-based.
- For a multi-domain system, create a small structure reflecting its modules; do not produce empty department folders.
- Preserve language choice and stable identifiers. Record source/provenance for requirements, decisions, and assumptions.
- Store non-applicable topics in the manifest with a reason rather than blank documents.
- Keep templates and generated content separate from Context OS runtime/system prompts.
- Let the user select compact/standard/detailed depth and preview before export.
- Include generated project `.env.example` only with variable names and harmless placeholders; never include Context OS `.env`, API keys, session cookies, DB passwords, prompt internals, local paths, or logs.

## 6. Frontend and product quality

- Replace the inline Python HTML with a maintained frontend; do not build a giant form page.
- Show progress as named workflow stages and distinguish waiting for user, running, failed, blocked, validated, and exported.
- Autosave only through the authorized backend project API, with explicit privacy and delete controls.
- Every screen has loading, empty, retry, validation, and provider/database failure behavior.
- Editing an intake after generation creates a new revision and invalidates affected downstream artifacts instead of mutating history.
- Document editor is initially Markdown-oriented with safe preview; do not render arbitrary raw HTML or remote embeds.
- Accessibility and localization are acceptance criteria, not polish backlog.
- Use design tokens and components; test layout at mobile and desktop widths with browser automation.

## 7. Security, privacy, and operations

### Required safeguards

- Local developer mode binds to loopback by default. Public deployment requires an explicit security phase.
- If exposed beyond localhost, implement real authentication (OIDC or an approved auth service), project-level authorization, secure cookies/CSRF, rate limits, abuse controls, TLS, CORS allow-list, and account deletion before launch.
- Use least-privilege DB roles; parameterized SQL/ORM only; do not allow model-authored SQL.
- Keep API keys in environment/secret manager only. Never return them to the browser or store them in generated project artifacts.
- Treat user idea, document content, uploaded templates, and provider output as untrusted; defend against prompt injection, HTML injection, ZIP path traversal, SSRF, unsafe Markdown, oversized input/output, and ZIP bombs.
- Never fetch arbitrary user/model URLs as part of document generation.
- Validate ZIP file count, path, size, Unicode normalization, content type, checksums, duplicates, and archive reopen. Stream/limit downloads.
- Set request size, output size, concurrency, model call count, timeout, and checkpoint retention limits. Limits should be configurable, not absent.
- Apply retention/deletion to idea text, documents, checkpoints, exports, and audit records. Support user-initiated project deletion.
- Keep audit events content-minimal. Secrets and full idea text must not be in operational logs.
- Do not silently downgrade database/provider/security errors to successful output.

### Operations

- Docker Compose for local full stack: frontend, API, PostgreSQL, and optional development mail/observability only when needed.
- Health/readiness endpoints check app and DB separately; provider health is an explicit user-triggered check, not a readiness dependency.
- Structured logs with request/run IDs; OpenTelemetry traces/metrics with content redaction and opt-in external export.
- Database backups and restore rehearsal before public/production use.
- CI: format/lint, type-check, unit tests, integration tests against PostgreSQL, frontend tests, browser tests, dependency/security scanning, migration checks, package validation.
- Container image runs non-root; pin base images/dependencies; secret-free build contexts; no debug API/docs in public production unless access-controlled.

## 8. Validation, evaluation, and quality gates

### Deterministic output validation

Before export, verify:

1. Required files and formats match selected profile.
2. Every JSON/YAML file parses and validates against a pinned schema.
3. Every required document section has meaningful content; no unresolved placeholders.
4. Internal links and document IDs are unique/resolvable.
5. Requirement and acceptance criteria IDs are unique; dependencies are valid and acyclic.
6. Facts/requirements/decisions link to a user source, accepted decision, or explicit assumption.
7. Conflicting statements are flagged across scope, architecture, APIs, data, and security.
8. Unsupported claims, generated stack choices without approval, and critical open questions are surfaced.
9. No forbidden secrets, local paths, internal prompts, session state, or Context OS credentials are included.
10. Manifest file list and hashes match exactly; ZIP can be reopened and safely inspected.

### Model quality evaluation

Create a versioned evaluation set spanning:

- Simple and complex ideas.
- Bangla, English, and mixed-language ideas.
- Missing audience/platform/stack details.
- Contradictory inputs and scope changes.
- Prompt injection in idea text.
- Privacy/security-sensitive projects.
- Non-software and out-of-scope requests.
- Very long input, provider errors, rate limits, invalid structured output, and retries.

Score required field coverage, factual provenance, unsupported decision rate, actionable questions, consistency, right-sized document count, Bangla/English quality, and refusal/escalation correctness. Compare model/prompt versions against a baseline before changing defaults. Evaluation is a release gate; it does not replace human review.

### Quantitative initial-release thresholds

- **Deterministic package checks:** 100% of downloadable packages pass schema, required-file, path-containment, link, placeholder, provenance, manifest/hash, and ZIP reopen checks. Any failure blocks export.
- **Secret safety:** zero detected secrets in generated packages, logs, browser errors, or test artifacts. Any match blocks export and release; automated scanning is not represented as exhaustive.
- **Traceability:** 100% of generated requirements, decisions, and factual claims are linked to user input, an accepted user decision, or an explicitly labeled assumption. Zero unsupported high-impact decisions may be silently emitted as confirmed.
- **Workflow safety:** zero false-completed runs in injected provider, database, validation, interruption, and export failure tests. No unapproved shell/tool/URL execution paths.
- **Evaluation corpus:** at least 40 versioned synthetic cases before the first quality release, including at least 10 Bangla/mixed-language cases and 10 security/privacy/prompt-injection cases. Run each case three times for a candidate model/prompt change (120 generations).
- **Quality rubric:** >=90% required-field coverage and >=90% actionable-question/consistency score across the corpus; >=95% correct output-language match; 100% recall of annotated critical blockers; zero fabricated confirmed facts; zero unresolved critical safety findings.
- **Human acceptance:** review at least 10 generated packages from unrelated project domains and both supported languages. Record evaluator, model/prompt version, findings, and disposition.
- **CI versus model evaluation:** deterministic tests run in CI without credentials or network. Live model evaluation is opt-in/release-gated, uses synthetic inputs only, and records spend/runtime; no private user project text is used as an eval case without explicit consent.

### Release gates

- **Gate A — Specification:** target product/schema/API/architecture accepted; contradictions removed.
- **Gate B — Local vertical slice:** user can create/resume one project, answer questions, review generated docs, validate, and export.
- **Gate C — Durable workflow:** PostgreSQL migration, LangGraph checkpoint, pause/resume, worker restart recovery, deletion/retention tests.
- **Gate D — Quality:** CI and evaluation thresholds pass; no unresolved critical validation findings.
- **Gate E — Public deployment:** authentication, authorization, security review, backups/restore, rate limits, monitoring, privacy notice, and incident/rollback plan approved.

No phase is "complete" because code exists. It is complete only when acceptance tests and explicit evidence pass.

## 9. Ordered implementation phases

Each phase is a separate coding-agent milestone. Finish tests and update docs before starting the next. Do not attempt a large unreviewable rewrite.

### Phase 0 — Product decisions and spec reconciliation

- **P0-T1:** Initial release is local-first, single-user, localhost-only; no account, team features, analytics, public hosting, or autonomous application-code execution. Public/multi-user launch remains a separately approved Phase 9.
- **P0-T2:** Persist user projects and revisions in local PostgreSQL so work survives restart. Retain content until the user deletes the project; deletion must remove project content, documents, workflow/checkpoint state, and exports. Keep audit metadata content-minimal. Do not promise backup-based recovery in the local release.
- **P0-T3:** Send project text to Gemini only after clear disclosure and affirmative user consent. Do not use any other provider or external content service without an explicit product decision.
- **P0-T4:** Keep compact and detailed packages for the first release. Detect the idea's language by default and let the user choose/override it. Add a standard profile only after its document rules and acceptance criteria are specified.
- **P0-T5:** Reconcile older MVP-only documents with this target. Mark old assumptions as historical/MVP behavior instead of deleting useful behavior or allowing it to silently override this plan.
- **P0-T6:** Define stable schemas, state transitions, error contract, and acceptance/evaluation thresholds.
- **P0-T7:** Produce a traceability matrix mapping each product requirement to module, API, database table, graph node, UI screen, and tests.

**Exit:** decisions above are recorded; no unresolved architecture/product conflict changes the foundation; target contracts and traceability are specific enough to build and test.

### Phase 1 — Modular monolith foundation

- **P1-T1:** Inventory existing MVP behavior, dependencies, startup paths, and tests; record a baseline before structural changes.
- **P1-T2:** Enforce local-only loopback host settings and validate core settings at startup.
- **P1-T3:** Establish an application factory/composition boundary while preserving current import/startup compatibility.
- **P1-T4:** Separate HTML rendering and bounded form/CSRF parsing from the web application; preserve escaped output and request limits.
- **P1-T5:** Extract discovery and document-generation orchestration into typed application services behind the provider/package-builder boundaries; keep HTTP routes thin and dependency-injected.
- **P1-T6:** Add pinned/locked dependencies, format/lint/type/test configuration, safe structured logging, request/error conventions, and CI.
- **P1-T7:** Add frontend/shared-contract structure and a bootable accessible Next.js TypeScript shell. Defer OpenAPI client generation until the versioned API is implemented in Phase 3.
- **P1-T8:** Add local Docker Compose for frontend, API, and PostgreSQL with loopback-only service exposure and secret-safe configuration.

**Exit:** empty project shell boots reproducibly; CI passes; secrets are ignored.

### Phase 2 — PostgreSQL persistence

- **P2-T1:** Design and approve the ERD, data ownership, provenance, deletion/retention, transaction boundaries, and migration plan before adding tables.
- **P2-T2:** Implement SQLAlchemy 2.x asynchronous models and explicit Alembic migrations; support local seed-free setup without creating schema at application startup.
- **P2-T3:** Implement project-scoped repositories with workspace ownership filters, optimistic concurrency, idempotency, and transaction boundaries.
- **P2-T4:** Persist projects/revisions, sources, questions/answers, facts/decisions, requirements, documents, runs/events, validation reports, consent, exports, and content-minimal audit metadata; implement deletion and retention.
- **P2-T5:** Integration-test migrations, persistence/restart, concurrency, failure rollback, and project deletion against real PostgreSQL; update CI and the local runbook.

**Exit:** data survives restart; migrations upgrade from empty and previous schema; deletion tests pass.

### Phase 3 — Frontend and typed API

- Build accessible Next.js project wizard, project list, review workspace, progress, document preview/editor, validation, and export screens.
- Define versioned FastAPI request/response models and OpenAPI contract.
- Generate TypeScript client and enforce API contract tests.
- Add browser tests for core happy path, validation errors, editing, privacy, and responsive layouts.

**Exit:** fake-provider full user journey works through UI against PostgreSQL.

### Phase 4 — LangChain/Gemini provider boundary

- Replace direct `httpx` provider prompts with tested LangChain Google GenAI integration, retaining dependency injection for a deterministic fake.
- Set provider model capabilities, structured schemas, output/token/time budgets, redaction, and one bounded repair.
- Add a user-visible Gemini configuration/connection check; never reveal key.
- Verify API key handling and network behavior without logging the key.

**Exit:** provider tests cover valid, malformed, blocked, quota, timeout, and auth responses; no live key required in CI.

### Phase 5 — Durable LangGraph workflow

- Implement versioned graph state and the nodes/edges in Section 4.5.
- Add PostgreSQL checkpointer, run/thread mapping, interrupt/Command resume, state migration policy, and checkpoint cleanup.
- Add event streaming, idempotency, bounded retries, cancellation, failure recovery, and user approval interrupt.
- Test pause/resume across process restart and duplicate API requests.

**Exit:** each run resumes correctly after an approval pause or worker restart; no run can falsely complete.

### Phase 6 — Generic documentation catalog and generator

- Create versioned generic schemas/template packs, app profiles, source/provenance model, and conditional document rules.
- Build document rendering and optional format exporters as deterministic services.
- Let AI draft typed sections; deterministic code owns filenames, IDs, manifests, paths, and inclusion rules.
- Provide compact/standard/detailed packages and Bangla/English output.
- Use Aura solely as an optional test fixture demonstrating a domain-specific project pack; it is never injected into new projects by default.

**Exit:** diverse ideas create right-sized folders with traceable, self-consistent content.

### Phase 7 — Validation and evaluation

- Build validators and finding-resolution workflow described in Section 8.
- Add adversarial ZIP/path/secret/prompt-injection tests and fuzz bounded parsers.
- Establish and version evaluation dataset, baseline, scorecard, and release thresholds.
- Review generated packages manually across representative project types and languages.

**Exit:** no critical validation/evaluation failures; all package properties have automated evidence.

### Phase 8 — Reliable export and local operations

- Generate manifest and checksums from immutable document revision.
- Validate every file before export; make export idempotent and safe to retry.
- Add Docker Compose startup/migration/health guidance, backup/restore procedure, operational dashboards/log redaction, and user documentation.

**Exit:** clean-machine setup, workflow recovery, export verification, and documented restore rehearsal all pass.

### Phase 9 — Optional public/multi-user launch

Only if explicitly approved:

- Add identity/authentication, tenant/project isolation, quotas/rate limits, data export/deletion, consent/versioning, privacy/legal review, secure secret management, and abuse reporting.
- Add production deployment, TLS, managed PostgreSQL, backups, alerting, incident response, and rollback.
- Complete independent security review and production-readiness checklist.

**Exit:** explicit owner approval after the security and operational gates.

## 10. Repository target layout

```text
Context-OS/
  frontend/                  # Next.js App Router, TypeScript, UI tests
  backend/
    app/
      api/v1/                # Routes and API dependency wiring only
      core/                  # Settings, security primitives, errors, logging
      modules/
        projects/
        discovery/
        requirements/
        architecture/
        agent_runs/
        templates/
        document_generation/
        validation/
        artifacts/
        providers/
        audit/
      db/                    # SQLAlchemy engine, session, migrations config
    migrations/              # Alembic revisions
    tests/
  contracts/                 # OpenAPI snapshots and shared JSON Schemas
  template-packs/
    generic/
    profiles/                # Generic profile overlays, never hard-coded one industry
  evals/                     # Versioned sanitized evaluation cases and scorecards
  infra/
    docker/
    compose/
  docs/
    product/
    architecture/
    data/
    api/
    security/
    operations/
    testing/
    decisions/
  scripts/                   # Safe setup/test/export utilities; no hidden production actions
  .env.example
  docker-compose.yml
```

The implementation may adjust exact names, but module ownership and one-way dependencies must remain documented. Generated app packages use their own user-appropriate folder structure and do not copy this repository layout blindly.

## 11. Dependency direction and design rules

```text
Frontend -> Versioned HTTP API -> Application services -> Domain modules
                                             |              |
                                             v              v
                                      LangGraph workflow   Repositories
                                             |              |
                                             v              v
                                        Provider ports   PostgreSQL
```

- Domain modules do not import API handlers, frontend code, or provider-specific packages.
- Model/provider and database implementations sit behind interfaces at infrastructure boundaries.
- Cross-module writes go through application services and explicit transactions.
- The graph orchestrates application services; domain logic does not depend on LangGraph.
- The renderer consumes validated domain/project models; it does not query the database or call an LLM.
- The ZIP exporter accepts an immutable validated document revision; it does not run generation or access project secrets.
- No shared "misc utils" dumping ground; place code in the owning module.

## 12. Completion checklist for every coding-agent task

The coding agent must:

1. Read approved product/architecture and task acceptance criteria.
2. Inspect existing code and preserve user changes.
3. Identify affected modules, schema/API changes, and dependency order.
4. Implement a bounded vertical slice, not unrelated refactors.
5. Add/update tests for success, failure, security, and persistence paths.
6. Run format, lint, type, focused unit/integration/browser tests relevant to the slice.
7. Report exact commands and pass/fail results; never infer that unrun tests pass.
8. Update API/schema/ADR/runbook/project-state documents when behavior changes.
9. Report open questions, assumptions, migration/rollback notes, and remaining risks.
10. Stop and ask the owner before public deployment, destructive data changes, spending/billing changes, or any task blocked by contradictory requirements.

An agent cannot guarantee "no mistakes." Context OS earns trust by making unsupported claims and uncertainty visible, validating outputs mechanically, testing failure modes, and requiring human approval where automation is unsafe.

## 13. Technology decision summary

| Area | Proposed target | Why | Revisit when |
|---|---|---|---|
| Frontend | Next.js App Router + TypeScript | Mature React routing, server/client component model, accessible responsive UI | Local-only deployment constraints make a simpler client app clearly better |
| API | FastAPI + Pydantic v2 | Existing Python base, typed API, OpenAPI generation, good LangChain/LangGraph ecosystem | A measured performance/operational requirement demands another runtime |
| Agent workflow | LangGraph + typed state + PostgreSQL checkpointer | Explicit durable state, resumable runs, human interrupts and recovery | A workflow no longer benefits from graph state or LangGraph maintenance outweighs value |
| Model layer | LangChain `ChatGoogleGenerativeAI` integration for Gemini AI Studio | Provider abstraction and structured model interface, native Google integration | Evaluations or cost/privacy needs favor another approved provider |
| Application DB | PostgreSQL + SQLAlchemy 2.x async + Alembic | Durable project history, transactions, JSON support, portable relational constraints | A concrete deployment/platform constraint calls for managed alternative |
| Cache/queue | None initially; add Redis only from measured need | Avoid infrastructure without benefit; PostgreSQL is source of truth | Multi-worker coordination, shared rate limits, or queued jobs are introduced |
| Packaging | In-memory/temp-safe ZIP with manifest/checksums | No need to store duplicate archive bytes | Package sizes require managed object storage with expiry and access control |
| Deployment | Docker Compose for local dev; production target decided in Phase 0/9 | Reproducible local services without premature cloud commitment | Owner selects a public launch target |

Version policy: verify official supported versions when each phase starts, select mutually compatible versions, lock exact dependency resolutions, and test upgrade paths. Do not blindly chase "latest" on an unreviewed branch.

## 14. Definition of "ready"

Context OS is ready for its intended local project-context-generation use only when:

- All Gate A-D criteria pass.
- A clean-machine install/start path is documented and exercised.
- A project can be created, resumed, edited, and deleted through the UI.
- Workflow pauses for missing material facts and resumes correctly.
- Every emitted requirement and decision has visible provenance or is labeled an assumption.
- A representative set of unrelated project types and Bangla/English ideas generate valid right-sized project folders.
- Validation findings are actionable and blocking failures prevent export.
- The ZIP is deterministic apart from explicit generation metadata, safe to open, and has a verified manifest.
- No Context OS secrets or Aura defaults leak into output.
- Test/evaluation results, limitations, and known failure modes are reported.

Public deployment readiness additionally requires Gate E. Passing local tests is not authorization to expose the app publicly.

## 15. Official references consulted

These are architectural evidence, not a substitute for checking current versions during implementation:

- LangGraph persistence/checkpointer and short-term versus long-term memory: https://docs.langchain.com/oss/python/langgraph/persistence
- LangGraph human-in-the-loop interrupts and durable resume: https://docs.langchain.com/oss/python/langgraph/interrupts
- LangChain model interfaces and structured output: https://docs.langchain.com/oss/python/langchain/models
- LangChain structured output strategies, including provider-native modes: https://docs.langchain.com/oss/python/langchain/structured-output
- LangChain Google Generative AI integration, Google AI Studio API-key setup, and current SDK migration information: https://docs.langchain.com/oss/python/integrations/chat/google_generative_ai
- FastAPI SQL database guidance and PostgreSQL as a production database option: https://fastapi.tiangolo.com/tutorial/sql-databases/
- Next.js App Router and server/client component model: https://nextjs.org/docs/app
- SQLAlchemy 2.x documentation: https://docs.sqlalchemy.org/en/20/
- Alembic migrations documentation: https://alembic.sqlalchemy.org/en/latest/
- Google Gemini API GenerateContent REST API: https://ai.google.dev/api/generate-content
