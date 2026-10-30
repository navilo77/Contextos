# Generation and ZIP Contract

> **Scope note:** This is the current MVP export contract. Preserve its safety properties during migration; target profiles and schemas are finalized through `MASTER_IMPLEMENTATION_PLAN.md` and Phase 0.

This document defines the content and validation rules for every Context OS output package.

## 1. Output layout

The ZIP has one sanitized project-slug folder at its root:

```text
<project-slug>/
  README.md
  AGENTS.md
  context/
    project-context.json
    OPEN_QUESTIONS.md
  00-project/
    PROJECT_BRIEF.md
  01-product/
    REQUIREMENTS.md
    IMPLEMENTATION_PLAN.md
  02-technical/
    ARCHITECTURE.md              # Detailed profile or technically relevant
    DATA_MODEL.md                # Only when persistent data is in scope
    API_CONTRACT.md              # Only when an API is in scope
    SECURITY.md                  # Detailed profile or sensitive functionality
  03-quality/
    TEST_PLAN.md                 # Detailed profile; compact profile includes acceptance checks in REQUIREMENTS.md
  manifest.json
```

Only files required for the selected profile and project are included. The manifest lists included files and explicitly omitted optional topics with a short reason. Do not create blank files merely to satisfy the example tree.

## 2. Required content

### `README.md`

- Project name and one-paragraph purpose.
- Intended users and first-release goal.
- How to use this package with a separate coding agent.
- Link/list of package files.
- Clear statement that this package is a specification, not application code.

### `AGENTS.md`

Instructions scoped to the described project:

- Read the project brief and requirements before coding.
- Preserve confirmed constraints and distinguish unresolved decisions.
- Implement in small, verifiable steps.
- Add and run relevant tests.
- Do not claim completion when checks fail or were not run.
- Ask before irreversible, security-sensitive, or explicitly approval-gated actions.

Do not instruct an agent to ignore its system/developer instructions, reveal secrets, execute untrusted commands, or bypass safety checks.

### `context/project-context.json`

Must validate against `schemas/project-context.schema.json`. It records:

- Project identity and selected language/profile.
- User-confirmed facts.
- Accepted proposals (empty unless the product explicitly records user acceptance; the MVP does not currently offer that control).
- Assumptions.
- Open questions and impact.
- Constraints and exclusions.
- Generated document paths.
- Generator name and schema version.

Each fact/proposal/assumption should retain its origin or status. Do not merge uncertain details into confirmed facts.

### `00-project/PROJECT_BRIEF.md`

Purpose, users, problem, desired outcome, first-release scope, non-goals, constraints, and key decisions.

### `01-product/REQUIREMENTS.md`

Prioritized functional and non-functional requirements with stable local identifiers, user-visible behavior, and testable acceptance criteria. Avoid requirements that cannot be traced to an idea, a confirmed answer, or a clearly labeled accepted proposal.

### `01-product/IMPLEMENTATION_PLAN.md`

Small ordered milestones or tasks, dependencies, and completion checks. Do not include fake effort estimates or dates.

### `context/OPEN_QUESTIONS.md`

Unresolved decisions, why each matters, safe defaults if any, and whether it blocks implementation. An empty list is stated plainly.

### Conditional technical documents

- Architecture: main components, chosen or undecided stack, boundaries, and rationale.
- Data model: entities, ownership, retention, and sensitive fields, when relevant.
- API contract: operations, input/output shapes, auth expectations, and error behavior, when an API is in scope.
- Security: threat-relevant data, access boundaries, secret handling, and approval points, when detailed or sensitive functionality is in scope.
- Test plan: requirements-to-test mapping and expected verification commands only if known; never invent commands for a future codebase.

Each conditional document must distinguish decisions from suggestions and mark undecided details.

## 3. Manifest

`manifest.json` includes:

- `format_version`.
- `generator` name and version.
- `generated_at` in UTC ISO-8601.
- `project_slug`.
- `profile` (`compact` or `detailed`).
- `language`.
- `files`: relative path and SHA-256 for each generated file except the manifest itself.
- `omitted_topics`: topic and reason.
- `validation`: checks performed and their result.

Do not put API keys, access tokens, passwords, private prompts, raw provider request headers, or unrelated local paths in the manifest.

## 4. Validation before download

Block download unless all applicable checks pass:

1. Required files for the selected profile are present and non-empty.
2. `project-context.json` parses and validates against the schema.
3. Every manifest file path is relative, normalized, unique, and contained under the project root.
4. No path contains `..`, drive prefixes, absolute roots, control characters, or unsafe archive names.
5. Every internal Markdown link to a package file resolves.
6. No unresolved template tokens remain (for example, `{{...}}`, `[TODO]`, or `TBD`).
7. No credential-like values or configured secret values are included.
8. Manifest hashes match generated file bytes.
9. ZIP can be reopened and its entries match the manifest.

Secret scanning is a safety check, not a guarantee that every secret can be detected. Explain this limitation in the UI.

## 5. ZIP safety

- Create the archive only from the fixed in-memory package representation.
- Never use a user- or model-supplied filename as an unchecked filesystem path.
- Normalize project slugs and all output paths.
- Do not include the idea transcript, provider credentials, local machine paths, application logs, or hidden configuration unless represented as intentional project content.
- Do not fetch or embed arbitrary URLs or binaries during generation.
- Return a clear error if validation or archive creation fails.
