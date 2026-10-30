# MVP Architecture

> **Scope note:** This describes the existing prototype, not the target architecture. The modular-monolith target in `MASTER_IMPLEMENTATION_PLAN.md` supersedes these implementation choices during the phased migration.

## 1. Runtime shape

Build a local-first Python web application:

- Python 3.11 or later.
- FastAPI for HTTP routes and request validation.
- Server-rendered templates for the guided browser flow; avoid a separate frontend build system for the MVP.
- Pydantic models for intake and generated content.
- JSON Schema in `schemas/project-context.schema.json` as the contract for exported project context.
- Standard-library `zipfile`, `hashlib`, and `io` for archive generation.
- PyYAML is not required for the MVP output; generated context is JSON and Markdown.

Use a small, explicit dependency set. Do not add LangGraph or a vector database: the MVP workflow is a short, bounded sequence and does not need graph orchestration or retrieval.

## 2. Components

1. **Web flow:** collects input, displays follow-up questions, lets users review and edit answers, and initiates generation.
2. **Intake/clarification service:** converts user input into typed project facts, uncertainty, and prioritized questions. Confirmed fact records are built from submitted form values by the application, not trusted from generated prose.
3. **Gemini provider:** calls Google's native Gemini `models.generateContent` REST endpoint with JSON response mode. The model name is configurable; the API host and path are fixed to Google's HTTPS endpoint.
4. **Generation service:** builds the project-context model and Markdown files from confirmed answers and labeled uncertainty.
5. **Validation service:** checks schema, required content, paths, links, template markers, secret patterns, and manifest hashes.
6. **ZIP service:** packages only validated in-memory files and returns a download response.

Keep business logic outside HTTP handlers. The provider must be replaceable in tests with a deterministic fake.

Current code keeps these responsibilities in separate modules: `app/factory.py` composes runtime dependencies; `app/web/application.py` handles HTTP flow; `app/web/views.py` renders HTML; `app/web/form_data.py` parses bounded forms and validates CSRF; `app/modules/discovery/` and `app/modules/document_generation/` hold application services; `app/ports/ai_provider.py` defines the provider interface; and `app/services/` contains Gemini and package-building adapters.

## 3. Provider configuration

Load configuration from a local `.env` file or environment variables:

- `GEMINI_API_KEY`
- `GEMINI_MODEL` (default `gemini-3.8-flash`)
- `CONTEXT_OS_HOST` (default `127.0.0.1`)
- `CONTEXT_OS_PORT` (default `8000`)

Do not ship a real key or assume a particular vendor. The compatible adapter sends the idea only after the UI has disclosed external processing. Validate required configuration before requesting generation. Do not log request bodies, authorization headers, or generated private content by default.

The checked-in `.env.example` documents the Gemini model default. `.env` is loaded at startup and must remain local; never include it in version control or generated project ZIPs. The API key is sent in Google's `x-goog-api-key` HTTPS request header, not in the URL. The exact provider response format must be validated locally. Treat model output as untrusted data; it cannot choose output paths, execute code, select tools, or bypass validation.

## 4. Request lifecycle

```text
Browser intake
  -> input validation
  -> disclosure/consent
  -> clarification request
  -> user answers and review
  -> structured generation
  -> local schema/content/security checks
  -> ZIP creation and reopen verification
  -> browser download
```

Fail closed at each boundary. Return typed, user-safe errors and keep internal diagnostics free of credentials and unnecessary idea text.

## 5. State and persistence

The MVP does not need a database or user account. Keep work in the active browser session/server-side short-lived session state. Do not promise durable drafts. Avoid storing idea content on disk. If server-side session state is necessary, use an unpredictable session identifier, expire it, and document the local-only threat model.

Do not bind to a public network interface by default. Deployment beyond localhost is outside this MVP and requires a separate security design.

## 6. Suggested project layout

```text
app/
  main.py
  config.py
  models/
  services/
    intake.py
    provider.py
    generation.py
    validation.py
    archive.py
  templates/
  static/
schemas/
tests/
```

The coding agent may adapt this layout to existing repository conventions while preserving component boundaries and product behavior.
