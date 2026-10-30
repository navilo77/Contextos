# Context OS Coding-Agent Instructions

## Mission

Build Context OS as a reliable, generic project-context generator following the approved target architecture and milestones in `docs/MASTER_IMPLEMENTATION_PLAN.md`.

Context OS helps a user turn an app idea into reviewed, validated project documentation and a ZIP for a separate coding agent. It does not build the user's application or execute generated code in the initial target. Aura Skincare is reference material only and must never become a default project or hidden domain assumption.

Treat Context OS as a real-world engineering tool, not a demo. Prefer complete, observable, recoverable behavior, strict data ownership, explicit failures, safe migrations, and test evidence over a success-shaped mock or a superficial implementation. Keep the approved local-first product boundary; do not claim production readiness or zero defects without evidence.

## Mandatory reading order

Before any code change:

1. Read `README.md`.
2. Read `docs/IMPLEMENTATION_STATUS.md` to determine the last verified checkpoint and next task.
3. Read the relevant sections of `docs/MASTER_IMPLEMENTATION_PLAN.md`.
4. Read the current product/security/generation/test documents that the task affects.
5. Inspect the existing code, tests, workspace state, and dependency configuration.

The master plan defines the proposed target. The current implementation is a working MVP and must not be deleted until each behavior has been replaced and tested.

## Work and recovery protocol

- Implement one vertical slice or one explicitly bounded task at a time.
- Before editing, state the task ID, scope, expected files, risks, and acceptance checks in `docs/IMPLEMENTATION_STATUS.md`.
- After each verified task, update that status file with completed task IDs, files/decisions changed, exact commands and results, unresolved issues, and the next task ID.
- A new coding-agent session must resume from the first incomplete task recorded there. Do not repeat completed tasks unless a failed regression requires it.
- If interrupted, stop at a safe boundary, preserve all work, update the status with what was in progress and the exact next action, and do not claim the task passed.
- Never infer success from a plan, tool start, or partial output. Run the required checks and record their exact results.
- Test each changed layer at its real boundary. Database behavior involving PostgreSQL locking, constraints, or migrations must be exercised against PostgreSQL; mocks and skipped integration tests are not evidence that those acceptance checks passed.
- If no git repository exists, do not claim a commit or use destructive git commands. If one exists, inspect status and preserve user changes. Commit/checkpoint only when the owner or repository workflow permits it.

## Use of other agents

- Use other agents only for genuinely independent, bounded work such as reviewing an architecture proposal, checking an isolated test matrix, or examining a specific integration.
- Do not delegate a single continuous trace or have agents concurrently edit the same files or shared database/API contracts.
- Give each agent exact scope, expected output, and a stop condition. Wait for requested results; integrate them yourself, verify claims against primary sources/code, run tests, and record the conclusion.
- Agent suggestions are not evidence of correctness. The main coding agent remains responsible for implementation, integration, and final verification.

## Safety and correctness

- Never put secrets in source, logs, browser output, docs, generated files, test artifacts, or ZIPs.
- Treat user content, documents, templates, and model output as untrusted data.
- Never execute model-generated code, shell commands, SQL, or arbitrary URLs.
- Preserve provenance: confirmed facts, accepted user choices, assumptions, and unanswered questions remain separate.
- Prefer deterministic validation for schemas, paths, links, IDs, dependency graphs, manifests, and archive safety.
- Bound model calls, repairs, retries, input/output sizes, and runtime. Fail visibly and safely.
- Require human input/approval for material unknowns, sensitive decisions, destructive changes, secret handling, and public deployment.
- Do not promise zero bugs. Reduce risk with tests, review gates, recovery paths, and explicit limitations.
- Do not expose a local development server publicly.

## Phase gates

- Follow the phases and exit criteria in `docs/MASTER_IMPLEMENTATION_PLAN.md`.
- Phase 0 specification reconciliation must be complete before changing the foundation architecture.
- Do not silently skip a phase, widen scope, upgrade dependencies, or change the model/provider stack without documenting the decision and verification.
- Update product, architecture, API, schema, security, testing, and operational documentation when implementation changes those contracts.
- Do not implement future public/multi-user deployment until the owner explicitly approves its phase and security requirements.

## Completion report

For each task, report:

1. Implemented behavior and affected modules.
2. Exact tests/checks run and their results.
3. Database/API/schema migration impacts and rollback notes, if any.
4. Known limitations, failures, and open decisions.
5. The next task/checkpoint in `docs/IMPLEMENTATION_STATUS.md`.
