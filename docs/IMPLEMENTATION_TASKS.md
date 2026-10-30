# Suggested Implementation Tasks

> **Scope note:** These tasks describe the original MVP and are retained as a behavioral regression checklist. The target implementation sequence is in `MASTER_IMPLEMENTATION_PLAN.md`.

Implement as small vertical slices. Each task is complete only when its behavior is tested.

## 1. Application shell

- Add install and run instructions, environment configuration, and a localhost-only FastAPI entry point.
- Add a basic landing/intake form with input bounds and safe error handling.
- Verify the app starts without an AI key and clearly explains the missing configuration when generation is requested.

## 2. Typed project context and provider boundary

- Implement Pydantic request/context models aligned with `schemas/project-context.schema.json`.
- Implement the native Gemini `models.generateContent` REST adapter using the AI Studio API key and JSON response mode.
- Add deterministic fake-provider tests.
- Validate provider responses and bound response size/time.

## 3. Clarification and review

- Generate bounded, prioritized follow-up questions.
- Let the user answer, mark unknown, or accept a labeled proposal.
- Show an editable review summary with facts, accepted proposals, assumptions, and unresolved questions.
- Do not persist drafts across sessions unless the security/privacy requirements are updated and approved.

## 4. Document generation

- Build compact and detailed file sets from the reviewed project context.
- Generate all required package documents and conditional technical documents.
- Keep project facts traceable to input, accepted proposals, or labeled assumptions.
- Add focused content-generation tests using the fake provider.

## 5. Validation and archive

- Implement schema/content/path/link/placeholder/secret checks from `GENERATION_CONTRACT.md`.
- Build the ZIP in memory from a fixed package representation.
- Add manifest hashes and reopen/verify the archive before download.
- Add adversarial tests for path traversal, malformed output, secrets, and partial package failures.

## 6. End-to-end verification

- Complete the browser flow and test download for both profiles.
- Run the full test suite and configured lint/type checks.
- Update the README with exact installation, configuration, start, and troubleshooting commands.
- Report known limitations, especially that the MVP creates context packages but does not build apps or launch coding agents.

Do not add future integrations to the MVP just because they appear useful. Keep each task within the product boundary.
