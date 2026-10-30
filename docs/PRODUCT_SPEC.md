# Product Specification

> **Scope note:** This is the current MVP behavior baseline. The future target and migration decisions are in `MASTER_IMPLEMENTATION_PLAN.md`; this document must not be used to silently override that plan.

## 1. Product

**Name:** Context OS  
**Purpose:** Help a person turn an application idea into a clear, consistent, coding-agent-ready project context ZIP.

Context OS generates a starting specification for an application. It does not generate or verify the application code in this MVP.

## 2. Target user and problem

The target user has an application idea but may not know how to translate it into requirements, technical decisions, or instructions that a coding agent can use. They need a guided process that asks for missing information, records uncertainty honestly, and produces a reusable project package.

## 3. User outcome

After one guided session, the user can download a ZIP that:

- Explains the app's purpose, users, scope, and important constraints.
- States measurable behavior and acceptance criteria for the first release.
- Gives a coding agent enough context to start implementation without assuming the package itself is executable software.
- Separates confirmed facts from proposed choices, assumptions, and open questions.
- Is small, readable, and valid rather than a large set of repetitive documents.

## 4. MVP workflow

### 4.1 Idea intake

Collect, at minimum:

- Idea in the user's own words.
- Intended user or audience, if known.
- Main problem to solve and desired outcome.
- Essential features or workflows.
- Target platform, if known.
- Constraints or exclusions, if known.
- Technology preference, if known.

Allow unknown answers. Do not force the user to select a technology stack or invent a business model.

### 4.2 Clarification

Analyze the idea and propose a short, prioritized set of questions. Ask questions only when their answers materially change the project scope, safety, or useful first-release plan. Clearly identify optional questions.

The user can answer or mark a detail unknown. The MVP does not present AI-proposed technical or business decisions for acceptance. Never silently promote a model suggestion into a user-confirmed fact.

### 4.3 Review

Before document generation, show an editable summary containing:

- Confirmed facts.
- Accepted proposals (empty in the MVP because it does not offer a proposal-acceptance control).
- Assumptions.
- Open questions and their impact.
- Selected package detail level.

The user must be able to return to the answers and revise them.

### 4.4 Generate and download

Generate the package defined in `GENERATION_CONTRACT.md`. Validate it before enabling download. Show validation results and the generated file list. On a blocking validation error, explain the problem and do not offer a success-shaped or partial ZIP.

## 5. Package detail levels

- **Compact:** project brief, requirements and acceptance criteria, implementation plan, open questions, and coding-agent instructions. Architecture, data, API, security, or test details appear only when relevant.
- **Detailed:** includes the compact content plus relevant architecture, data, API, security, and test documents.

Do not pad a package with empty sections. If a topic does not apply or cannot yet be decided, state that and why in the brief or open-questions document.

## 6. Quality requirements for generated content

- Use plain, direct language. The user may choose a language; default to the language of the idea.
- Avoid unsupported claims, fake measurements, invented integrations, and unexplained technical jargon.
- Make requirements testable where possible.
- Identify dependencies and risks when they affect implementation.
- Keep implementation scope appropriate for a first version.
- Avoid domain-specific assumptions. Industry-specific content must come from the user's idea or confirmed answers.

## 7. Error and retry behavior

- Missing AI configuration: explain how to configure it; do not silently use canned AI output.
- Provider/network error: show a safe, actionable error without exposing credentials or raw sensitive request data.
- Invalid model output: validate, request at most one structured repair, then stop with a useful error if still invalid.
- Invalid or unsafe package path/content: reject package generation and explain the failed check.
- User cancellation or browser refresh: do not claim the work was saved. The MVP may keep session data in browser/session memory only.

## 8. Out of scope

- Writing, editing, building, or testing the application described by the idea.
- Launching or controlling a coding agent.
- Git operations, commits, pull requests, or deployments.
- Accounts, teams, shared projects, cloud persistence, billing, and analytics.
- Automatic access to a user's source repository or local files.
- Domain-specific templates that assume Aura Skincare or any other one business.
- Guaranteeing that a separate coding agent will implement the specification correctly.

## 9. MVP success criteria

The MVP is useful when a user can enter an idea, resolve or explicitly preserve important unknowns, review the summary, download a valid ZIP, and give that ZIP to a separate coding agent as project context.
