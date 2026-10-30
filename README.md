# Context OS

Context OS turns an application idea into a structured, coding-agent-ready project context package that can be downloaded as a ZIP.

The current runnable MVP lives in `app/`. It is a local-first web agent that asks clarifying questions, creates project-context documents, validates them, and provides a ZIP download. It does not write the application described by the user or run another coding agent. The proposed future architecture and phased migration are documented in `docs/MASTER_IMPLEMENTATION_PLAN.md`; they are not yet implemented.

For ongoing work, read `docs/IMPLEMENTATION_STATUS.md` first and continue from its next task. The status file records verified checkpoints so an interrupted coding session can resume without treating unfinished work as complete.

The current Python MVP now has explicit boundaries: `app/factory.py` composes dependencies, `app/web/` owns HTTP and HTML, `app/modules/` owns discovery and document-generation workflows, `app/ports/` defines the AI-provider contract, and `app/services/` contains provider/archive infrastructure. `app/main.py` remains the compatible Uvicorn entry point.

## Product boundary

The first version does one job:

1. Collect an app idea and clarify important unknowns.
2. Generate project documents from the confirmed answers.
3. Validate the documents and package them into a downloadable ZIP.

The generated package is intended to help a separate coding agent build the described application. It must not claim that the application itself has been built or tested.

## First-run user experience

1. Start Context OS locally and open its browser interface.
2. Enter the idea, intended users, platform, key features, constraints, and preferred technology if known.
3. Review and answer the agent's short list of blocking questions. Unknown optional details remain explicitly marked as undecided.
4. Choose a compact or detailed package.
5. Review a preview of the project facts, assumptions, and open questions.
6. Generate, validate, and download the ZIP.

The user must be able to correct the generated package by editing answers and generating it again. No external account is required for the local MVP.

## Product principles

- Generic by default: do not assume the project is about Aura, skincare, commerce, or any particular industry.
- Ask instead of inventing: distinguish user-confirmed facts, proposed decisions, assumptions, and unresolved questions.
- Small but useful: generate only the documents needed to start implementation.
- Verifiable: do not offer a ZIP as successful unless required files and safety checks pass.
- Human-controlled: the user chooses whether to accept proposed decisions and when to download.
- Privacy-aware: disclose when idea text will be sent to an external AI provider.

## Source of truth

For the current MVP behavior and safe operation, use:

1. `AGENTS.md` for coding-agent execution instructions.
2. `docs/IMPLEMENTATION_STATUS.md` for the current phase and next verified task.
3. `docs/MASTER_IMPLEMENTATION_PLAN.md` for the proposed target and phase gates.
4. The existing `docs/PRODUCT_SPEC.md`, `docs/GENERATION_CONTRACT.md`, `docs/ARCHITECTURE.md`, `docs/SECURITY_AND_PRIVACY.md`, `docs/TESTING_AND_ACCEPTANCE.md`, and `docs/IMPLEMENTATION_TASKS.md` for current MVP contracts and behavior.

The older product and architecture documents describe the MVP and have not yet been reconciled with the master plan. During Phase 0, document and resolve conflicts before foundation changes; never silently treat a proposed target as implemented behavior.

## Defaults for the MVP

- Local-first web application, bound to localhost by default.
- Python 3.11 or later, FastAPI, and a simple server-rendered interface.
- Direct Google AI Studio Gemini `generateContent` API integration.
- Gemini API credentials supplied through the local `.env`; never committed or included in generated ZIPs.
- No Context OS user accounts, cloud storage, analytics, autonomous code execution, or production deployment. A configured AI provider and its API credentials are required for AI generation.

These are implementation defaults for this product, not requirements imposed on the apps described by users.

## Run Context OS

Requirements: Python 3.11 or later and a Gemini API key from [Google AI Studio](https://aistudio.google.com/apikey). Context OS calls Google's native Gemini `generateContent` REST API.

Run these commands from inside the `Context-OS` folder (the folder containing `pyproject.toml`), not its parent folder:

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -e ".[dev]"
python -m uvicorn app.main:app --host 127.0.0.1 --port 8000
```

If the virtual environment is in the parent `CONTEXTOS` folder, activate it from `Context-OS` with `..\.venv\Scripts\Activate.ps1` instead of creating a new one here. Then install and run the application using the remaining commands above.

Open `http://127.0.0.1:8000`. Run tests with `python -m pytest`.

## Run the Next.js frontend shell

The frontend is a separate, accessible Next.js App Router workspace. From the `Context-OS` folder:

```powershell
Push-Location frontend
npm ci
$env:NEXT_TELEMETRY_DISABLED = "1"
npm run dev
Pop-Location
```

Open `http://127.0.0.1:3000`. The workspace creates and lists projects, collects explicit Gemini consent, saves clarification answers, generates documents, displays full document content for human review, validates the reviewed package, and creates/downloads a verified ZIP through the local PostgreSQL API. Reopening a project restores its current questions, documents, validation report, and exports. To verify the frontend, run `npm run format:check`, `npm run lint`, `npx tsc --noEmit`, and `npm run build` from `frontend`. Biome handles formatting/linting, TypeScript checks types, and the npm lockfile pins the dependency graph.

## Run the local Docker Compose stack

Requirements: Docker Desktop (or Docker Engine with the Compose plugin). Create `.env` from `.env.example` only if you do not already have one; otherwise, add a non-empty local `POSTGRES_PASSWORD` to the existing `.env` without replacing its Gemini settings. Keep `.env` private and never commit or share it.

From the `Context-OS` folder:

```powershell
docker compose up -d db
docker compose build api
docker compose run --rm api alembic upgrade head
docker compose up --build -d
docker compose ps
```

Open the frontend at `http://127.0.0.1:3000` and the current Python MVP at `http://127.0.0.1:8000`. PostgreSQL is available to local database tools at `127.0.0.1:5432`. All published ports bind to loopback only. If you change ports in `.env`, update `CONTEXT_OS_FRONTEND_ORIGIN` and `NEXT_PUBLIC_CONTEXT_OS_API_URL` to match, then rebuild the frontend image.

The Next.js workspace connects to the API for the complete current project workflow. The `/api/v1/projects` API persists project intake, revisions, sources, consented clarification questions/answers, normalized generated facts and requirements, acceptance criteria, generated document contents, and generation run metadata in PostgreSQL. `GET /api/v1/projects/{project_id}/workflow` restores the current revision's questions, answers, documents, latest validation report, and export metadata. Project edits use `PATCH` with an expected revision, preserve unchanged source records, and return a conflict for stale edits. Confirmed facts link to exact input sources; generated assumptions remain unconfirmed. Generation is idempotent when retried with the same `Idempotency-Key`. After reviewing and approving all documents, the API validates the current package and can create a ZIP export; only document contents and export metadata are persisted, while ZIPs are reconstructed and integrity-checked on demand. These API operations require migrations to be applied first. Migrations are deliberately an explicit operator action and are never run automatically at application startup. When PostgreSQL is configured, legacy server-rendered HTML sessions are also persisted in `web_sessions` and survive app restarts; session rows expire after 30 minutes and are cleaned up periodically. Without PostgreSQL, that backward-compatible HTML flow remains process-local. HTML sessions store only temporary workflow state, do not persist ZIP bytes, and are not a substitute for canonical project records. Stop the stack with `docker compose down`. `docker compose down -v` also deletes the local PostgreSQL volume and its contents.

For a reproducible development setup, install [uv](https://docs.astral.sh/uv/) and run from `Context-OS`:

```powershell
uv sync --extra dev
uv run ruff format --check app tests
uv run ruff check app tests
uv run mypy
uv run pytest
```

`uv.lock` pins the resolved Python dependency graph. The GitHub Actions workflow runs the same checks on Linux and Windows.

The local `.env.example` sets the Gemini model. If you do not already have a `.env`, copy the example, then paste your Google AI Studio key after `GEMINI_API_KEY=`:

```powershell
Copy-Item .env.example .env
notepad .env
```

Do not add quotes around the key or share/commit `.env`. It is excluded from Git and generated ZIPs. Restart Context OS after changing `.env`. The model can be changed with `GEMINI_MODEL` if needed. Context OS binds to localhost by default and rejects non-loopback host settings. Do not expose it publicly without a separate security review.

### PostgreSQL repository integration tests

Repository integration tests require a dedicated PostgreSQL database; they do not create or drop schemas automatically and must never target a database containing user data. Set both `CONTEXT_OS_DATABASE_URL` and `CONTEXT_OS_TEST_DATABASE_URL` to a test-only `postgresql+asyncpg` URL whose database name ends in `_test`, set `CONTEXT_OS_RUN_POSTGRES_INTEGRATION=1`, apply `uv run alembic upgrade head`, then run `uv run pytest tests/integration`. The explicit opt-in and database-name guard prevent an ambient application URL from triggering integration-test writes. The CI job provisions an isolated PostgreSQL service, applies migrations from an empty database, checks ORM/migration parity, and runs these tests.

The user idea is sent to the configured provider only after the user accepts the disclosure. Session data stays in process memory and expires after 30 minutes; restarting the app clears it. The app does not persist idea text to disk. Provider credentials are required for AI generation; the landing page and tests can run without credentials.

An idea can contain up to 20,000 characters. The limit prevents excessively large provider requests while allowing long descriptions.

Gemini requests use a 90-second timeout. If you see a timeout, first confirm that Google AI Studio works with the configured key/model and that your network, VPN, proxy, or firewall allows HTTPS POST requests to `generativelanguage.googleapis.com`. The API key itself is never printed in errors.

## Run the coding-agent task

Open this folder as the coding-agent workspace and ask the agent to follow `AGENTS.md`. The coding agent should implement the MVP, run the required checks, and report any unmet acceptance criteria. Do not treat this specification package as proof that implementation or tests have already passed.

## Example output package

The generated ZIP contains a top-level project folder and a manifest. Its exact rules are in `docs/GENERATION_CONTRACT.md`. Aura-specific source material must never be copied into a generated project unless a user explicitly supplies it as part of that project.
