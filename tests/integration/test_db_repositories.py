from __future__ import annotations

import asyncio
import hashlib
import io
import os
import re
import zipfile
from collections.abc import Iterator
from uuid import UUID, uuid4

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import delete, func, select, text
from sqlalchemy.engine import make_url
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.config import Settings
from app.db.engine import create_database_engine, create_session_factory
from app.db.models import (
    AcceptanceCriterion,
    AgentRun,
    AuditEvent,
    ClarificationAnswer,
    ClarificationQuestion,
    Fact,
    FactSource,
    Project,
    ProjectDocument,
    ProjectRevision,
    ProjectRevisionSource,
    ProjectSource,
    ProviderConsent,
    Requirement,
    RunEvent,
    WebSession,
    Workspace,
)
from app.db.repositories import (
    IdempotencyConflictError,
    ProjectNotFoundError,
    RepositoryInputError,
    RevisionConflictError,
    RevisionInput,
    SourceInput,
    canonical_request_hash,
    create_or_get_run,
    create_project,
    create_project_revision,
    get_project,
    get_project_revision,
    list_projects,
)
from app.factory import create_app
from app.models import ClarificationResult, FollowUpQuestion, GeneratedDocuments
from app.services.provider import ProviderError

pytestmark = pytest.mark.skipif(
    os.environ.get("CONTEXT_OS_RUN_POSTGRES_INTEGRATION") != "1"
    or not os.environ.get("CONTEXT_OS_TEST_DATABASE_URL"),
    reason="Opt in with CONTEXT_OS_RUN_POSTGRES_INTEGRATION=1 and a dedicated test database URL.",
)


@pytest.fixture
def session_factory() -> Iterator[async_sessionmaker[AsyncSession]]:
    url = os.environ.get("CONTEXT_OS_TEST_DATABASE_URL")
    if not url:
        pytest.skip("A dedicated PostgreSQL test database is not configured.")
    database_name = make_url(url).database
    if database_name is None or not database_name.endswith("_test"):
        pytest.fail("Integration tests only run against a database whose name ends with '_test'.")
    engine = create_database_engine(url)
    factory = create_session_factory(engine)
    yield factory
    asyncio.run(engine.dispose())


def _revision_input(idea: str) -> RevisionInput:
    return RevisionInput(
        language="English",
        profile="compact",
        intake_snapshot={"idea_summary": idea},
        schema_version="1",
        template_pack_version="1",
    )


def test_project_api_persists_across_app_recreation_and_deletes_safely() -> None:
    async def verify() -> None:
        url = os.environ.get("CONTEXT_OS_TEST_DATABASE_URL")
        if not url:
            pytest.skip("A dedicated PostgreSQL test database is not configured.")
        engine = create_database_engine(url)
        factory = create_session_factory(engine)
        try:
            payload = {
                "name": "Durable project",
                "idea": "A project created through the Context OS API.",
                "audience": "Local developers",
            }
            first_app = create_app(database_session_factory=factory)
            async with AsyncClient(
                transport=ASGITransport(app=first_app),
                base_url="http://test",
            ) as client:
                created = await client.post("/api/v1/projects", json=payload)
                assert created.status_code == 201, created.text
                resource = created.json()["project"]

            second_app = create_app(database_session_factory=factory)
            async with AsyncClient(
                transport=ASGITransport(app=second_app),
                base_url="http://test",
            ) as client:
                fetched = await client.get(f"/api/v1/projects/{resource['id']}")
                assert fetched.status_code == 200
                assert fetched.json()["project"]["id"] == resource["id"]
                assert fetched.json()["project"]["name"] == payload["name"]

                async with factory() as session, session.begin():
                    persisted_idea = await session.scalar(
                        select(ProjectSource.content).where(
                            ProjectSource.project_id == UUID(resource["id"]),
                            ProjectSource.source_kind == "idea",
                        )
                    )
                    assert persisted_idea == payload["idea"]

                listed = await client.get("/api/v1/projects")
                assert listed.status_code == 200
                assert any(item["id"] == resource["id"] for item in listed.json()["items"])

                deleted = await client.delete(f"/api/v1/projects/{resource['id']}")
                assert deleted.status_code == 204
                missing = await client.get(f"/api/v1/projects/{resource['id']}")
                assert missing.status_code == 404

            async with factory() as session, session.begin():
                audit_count = await session.scalar(
                    select(func.count())
                    .select_from(AuditEvent)
                    .where(
                        AuditEvent.subject_id == UUID(resource["id"]),
                        AuditEvent.action_code == "project.deleted",
                    )
                )
                project_count = await session.scalar(
                    select(func.count())
                    .select_from(Project)
                    .where(Project.id == UUID(resource["id"]))
                )
                assert audit_count == 1
                assert project_count == 0
        finally:
            await engine.dispose()

    asyncio.run(verify())


def test_project_api_creates_optimistic_revisions_without_duplicating_sources() -> None:
    async def verify() -> None:
        url = os.environ.get("CONTEXT_OS_TEST_DATABASE_URL")
        if not url:
            pytest.skip("A dedicated PostgreSQL test database is not configured.")
        engine = create_database_engine(url)
        factory = create_session_factory(engine)
        try:
            app = create_app(database_session_factory=factory)
            async with AsyncClient(
                transport=ASGITransport(app=app),
                base_url="http://test",
            ) as client:
                created = await client.post(
                    "/api/v1/projects",
                    json={
                        "name": "Revision edit",
                        "idea": "The original idea.",
                        "audience": "Local developers",
                    },
                )
                assert created.status_code == 201, created.text
                project_id = UUID(created.json()["project"]["id"])
                initial_revision_id = UUID(created.json()["revision_id"])

                updated = await client.patch(
                    f"/api/v1/projects/{project_id}",
                    json={
                        "expected_revision": 1,
                        "name": "Updated project name",
                        "idea": "The revised idea.",
                        "language": "Bengali",
                    },
                )
                assert updated.status_code == 200, updated.text
                assert updated.json()["project"]["current_revision"] == 2
                assert updated.json()["project"]["name"] == "Updated project name"
                updated_revision_id = UUID(updated.json()["revision_id"])
                assert updated_revision_id != initial_revision_id

                stale = await client.patch(
                    f"/api/v1/projects/{project_id}",
                    json={"expected_revision": 1, "name": "Stale name"},
                )
                assert stale.status_code == 409
                assert stale.json()["code"] == "revision_conflict"

            async with factory() as session, session.begin():
                revision_count = await session.scalar(
                    select(func.count())
                    .select_from(ProjectRevision)
                    .where(ProjectRevision.project_id == project_id)
                )
                source_count = await session.scalar(
                    select(func.count())
                    .select_from(ProjectSource)
                    .where(ProjectSource.project_id == project_id)
                )
                current_sources = list(
                    (
                        await session.execute(
                            select(ProjectSource.safe_label, ProjectSource.content)
                            .join(
                                ProjectRevisionSource,
                                (ProjectRevisionSource.workspace_id == ProjectSource.workspace_id)
                                & (ProjectRevisionSource.project_id == ProjectSource.project_id)
                                & (ProjectRevisionSource.source_id == ProjectSource.id),
                            )
                            .where(
                                ProjectRevisionSource.project_id == project_id,
                                ProjectRevisionSource.revision_id == updated_revision_id,
                            )
                        )
                    ).all()
                )
                revision = await session.get(ProjectRevision, updated_revision_id)
                assert revision_count == 2
                assert source_count == 3
                assert revision is not None
                assert revision.language == "Bengali"
                assert set(current_sources) == {
                    ("User-provided idea", "The revised idea."),
                    ("Intended audience", "Local developers"),
                }
        finally:
            await engine.dispose()

    asyncio.run(verify())


def test_project_list_supports_opaque_cursor_pages() -> None:
    async def verify() -> None:
        url = os.environ.get("CONTEXT_OS_TEST_DATABASE_URL")
        if not url:
            pytest.skip("A dedicated PostgreSQL test database is not configured.")
        engine = create_database_engine(url)
        factory = create_session_factory(engine)
        app = create_app(database_session_factory=factory)
        created_ids: list[str] = []
        try:
            async with AsyncClient(
                transport=ASGITransport(app=app),
                base_url="http://test",
            ) as client:
                for index in range(3):
                    created = await client.post(
                        "/api/v1/projects",
                        json={
                            "name": f"Cursor pagination {index}",
                            "idea": f"A project for cursor page {index}.",
                        },
                    )
                    assert created.status_code == 201, created.text
                    created_ids.append(created.json()["project"]["id"])

                collected_ids: list[str] = []
                params: dict[str, str | int] = {"limit": 2}
                while True:
                    page = await client.get("/api/v1/projects", params=params)
                    assert page.status_code == 200, page.text
                    body = page.json()
                    collected_ids.extend(item["id"] for item in body["items"])
                    next_cursor = body["next_cursor"]
                    if next_cursor is None:
                        break
                    params = {"limit": 2, "cursor": next_cursor}

                assert set(created_ids).issubset(collected_ids)
                assert len(collected_ids) == len(set(collected_ids))

                invalid_cursor = await client.get(
                    "/api/v1/projects",
                    params={"cursor": "not-a-valid-cursor"},
                )
                assert invalid_cursor.status_code == 422
                assert invalid_cursor.json()["code"] == "invalid_cursor"

                mixed_pagination = await client.get(
                    "/api/v1/projects",
                    params={"cursor": "x", "offset": 1},
                )
                assert mixed_pagination.status_code == 422
                assert mixed_pagination.json()["code"] == "invalid_pagination"

                for project_id in created_ids:
                    deleted = await client.delete(f"/api/v1/projects/{project_id}")
                    assert deleted.status_code == 204
        finally:
            await engine.dispose()

    asyncio.run(verify())


def test_clarification_api_requires_consent_and_persists_questions() -> None:
    class StubProvider:
        def __init__(self) -> None:
            self.clarify_calls = 0

        async def clarify(self, intake: dict[str, str]) -> ClarificationResult:
            self.clarify_calls += 1
            assert intake["idea"] == "A project with persisted clarifications."
            assert intake["audience"] == "Local developers"
            return ClarificationResult(
                questions=[
                    FollowUpQuestion(
                        question="Does it need multiple workspaces?",
                        impact="This affects local data isolation.",
                        blocking=True,
                    ),
                    FollowUpQuestion(
                        question="What deployment is preferred?",
                        impact="This may affect hosting and operations.",
                        blocking=False,
                    ),
                ]
            )

        async def generate(self, intake, answers):
            raise AssertionError("Generation is not part of clarification.")

    async def verify() -> None:
        url = os.environ.get("CONTEXT_OS_TEST_DATABASE_URL")
        if not url:
            pytest.skip("A dedicated PostgreSQL test database is not configured.")
        engine = create_database_engine(url)
        factory = create_session_factory(engine)
        provider = StubProvider()
        settings = Settings(
            gemini_api_key="integration-test-key",
            gemini_model="gemini-3.8-flash",
            host="127.0.0.1",
            port=8000,
        )
        try:
            app = create_app(
                settings=settings,
                provider=provider,
                database_session_factory=factory,
            )
            async with AsyncClient(
                transport=ASGITransport(app=app),
                base_url="http://test",
            ) as client:
                created = await client.post(
                    "/api/v1/projects",
                    json={
                        "name": "Clarification persistence",
                        "idea": "A project with persisted clarifications.",
                        "audience": "Local developers",
                    },
                )
                assert created.status_code == 201, created.text
                project_id = created.json()["project"]["id"]

                declined = await client.post(
                    f"/api/v1/projects/{project_id}/clarifications",
                    json={"consent": False},
                )
                assert declined.status_code == 400
                assert declined.json()["code"] == "provider_consent_required"
                assert provider.clarify_calls == 0

                clarified = await client.post(
                    f"/api/v1/projects/{project_id}/clarifications",
                    json={"consent": True},
                )
                assert clarified.status_code == 200, clarified.text
                body = clarified.json()
                assert provider.clarify_calls == 1
                assert len(body["questions"]) == 2
                assert body["questions"][0]["question"] == ("Does it need multiple workspaces?")

                repeated = await client.post(
                    f"/api/v1/projects/{project_id}/clarifications",
                    json={"consent": True},
                )
                assert repeated.status_code == 200
                assert repeated.json()["questions"] == body["questions"]
                assert provider.clarify_calls == 1

                saved = await client.put(
                    f"/api/v1/projects/{project_id}/clarifications/answers",
                    json={
                        "answers": [
                            {
                                "question_id": body["questions"][0]["id"],
                                "answer_state": "answered",
                                "answer": "Separate projects only.",
                            },
                            {
                                "question_id": body["questions"][1]["id"],
                                "answer_state": "unknown",
                            },
                        ]
                    },
                )
                assert saved.status_code == 200, saved.text
                assert saved.json()["questions"][0]["answer"] == "Separate projects only."
                assert saved.json()["questions"][1]["answer_state"] == "unknown"

            resumed_app = create_app(
                settings=settings,
                provider=provider,
                database_session_factory=factory,
            )
            async with AsyncClient(
                transport=ASGITransport(app=resumed_app),
                base_url="http://test",
            ) as client:
                resumed = await client.get(f"/api/v1/projects/{project_id}/clarifications")
                assert resumed.status_code == 200
                assert resumed.json()["questions"][0]["answer"] == "Separate projects only."
                assert resumed.json()["questions"][1]["answer_state"] == "unknown"

            async with factory() as session, session.begin():
                consent = await session.get(ProviderConsent, UUID(body["consent_id"]))
                questions = (
                    (
                        await session.execute(
                            select(ClarificationQuestion).where(
                                ClarificationQuestion.project_id == UUID(project_id)
                            )
                        )
                    )
                    .scalars()
                    .all()
                )
                answer_count = await session.scalar(
                    select(func.count())
                    .select_from(ClarificationAnswer)
                    .where(ClarificationAnswer.project_id == UUID(project_id))
                )
                assert consent is not None
                assert consent.provider_id == "google_gemini"
                assert consent.destination == "generativelanguage.googleapis.com"
                assert consent.disclosure_version == "local-ai-v1"
                assert len(questions) == 2
                assert answer_count == 2
        finally:
            await engine.dispose()

    asyncio.run(verify())


def test_generate_api_persists_validated_documents_and_replays_idempotently() -> None:
    class StubProvider:
        def __init__(self) -> None:
            self.generate_calls = 0

        async def clarify(self, intake: dict[str, str]) -> ClarificationResult:
            return ClarificationResult()

        async def generate(self, intake, answers) -> GeneratedDocuments:
            self.generate_calls += 1
            assert intake["idea"] == "A study planner for learners."
            return GeneratedDocuments(
                project_name="Study Planner",
                project_slug="study-planner",
                purpose="Help learners plan study sessions.",
                intended_users=["Learners"],
                facts=[],
                accepted_proposals=[],
                assumptions=[
                    {"text": "Learners prefer short sessions.", "source": "Model proposal"}
                ],
                open_questions=[],
                constraints=[],
                exclusions=[],
                project_brief="A focused tool to organize learning sessions.",
                requirements=(
                    "## Requirements\n\n"
                    "- REQ-001: A learner can add a study session.\n\n"
                    "### Acceptance criteria\n\n"
                    "- Given a learner, when they save a session, then it appears in their plan."
                ),
                implementation_plan=(
                    "1. Implement study-session entry.\n2. Verify the acceptance criteria."
                ),
            )

    async def verify() -> None:
        url = os.environ.get("CONTEXT_OS_TEST_DATABASE_URL")
        if not url:
            pytest.skip("A dedicated PostgreSQL test database is not configured.")
        engine = create_database_engine(url)
        factory = create_session_factory(engine)
        provider = StubProvider()
        settings = Settings(
            gemini_api_key="integration-test-key",
            gemini_model="gemini-3.8-flash",
            host="127.0.0.1",
            port=8000,
        )
        try:
            app = create_app(
                settings=settings,
                provider=provider,
                database_session_factory=factory,
            )
            async with AsyncClient(
                transport=ASGITransport(app=app),
                base_url="http://test",
            ) as client:
                created = await client.post(
                    "/api/v1/projects",
                    json={
                        "name": "Study Planner",
                        "idea": "A study planner for learners.",
                    },
                )
                assert created.status_code == 201, created.text
                project_id = created.json()["project"]["id"]
                headers = {"Idempotency-Key": "persistent-generation-0001"}

                generated = await client.post(
                    f"/api/v1/projects/{project_id}/generate",
                    json={"consent": True},
                    headers=headers,
                )
                assert generated.status_code == 200, generated.text
                generation = generated.json()
                assert generation["status"] == "awaiting_user"
                assert len(generation["documents"]) >= 8
                assert provider.generate_calls == 1
                workflow = await client.get(f"/api/v1/projects/{project_id}/workflow")
                assert workflow.status_code == 200, workflow.text
                assert len(workflow.json()["documents"]) == len(generation["documents"])
                assert workflow.json()["validation"] is None
                assert workflow.json()["clarification"]["consent_id"] is not None

                replayed = await client.post(
                    f"/api/v1/projects/{project_id}/generate",
                    json={"consent": True},
                    headers=headers,
                )
                assert replayed.status_code == 200
                assert replayed.json() == generation
                assert provider.generate_calls == 1

                listed = await client.get(f"/api/v1/projects/{project_id}/documents")
                assert listed.status_code == 200
                assert len(listed.json()) == len(generation["documents"])
                unapproved = await client.post(
                    f"/api/v1/projects/{project_id}/validate",
                    json={
                        "approved": False,
                        "document_ids": [item["id"] for item in listed.json()],
                    },
                )
                assert unapproved.status_code == 400
                partial_review = await client.post(
                    f"/api/v1/projects/{project_id}/validate",
                    json={"approved": True, "document_ids": [listed.json()[0]["id"]]},
                )
                assert partial_review.status_code == 409
                document_id = listed.json()[0]["id"]
                document = await client.get(
                    f"/api/v1/projects/{project_id}/documents/{document_id}"
                )
                assert document.status_code == 200
                assert document.json()["content"]
                assert document.json()["sha256"] == listed.json()[0]["sha256"]

                validation = await client.post(
                    f"/api/v1/projects/{project_id}/validate",
                    json={
                        "approved": True,
                        "document_ids": [item["id"] for item in listed.json()],
                    },
                )
                assert validation.status_code == 200, validation.text
                report = validation.json()
                assert report["status"] == "passed"
                assert report["checked_document_count"] == len(listed.json())
                workflow = await client.get(f"/api/v1/projects/{project_id}/workflow")
                assert workflow.json()["validation"]["id"] == report["id"]
                assert workflow.json()["validation"]["finding_count"] == 0

                created_export = await client.post(
                    f"/api/v1/projects/{project_id}/exports",
                    json={
                        "validation_report_id": report["id"],
                        "confirm": True,
                    },
                )
                assert created_export.status_code == 200, created_export.text
                export = created_export.json()
                assert export["status"] == "ready"
                workflow = await client.get(f"/api/v1/projects/{project_id}/workflow")
                assert workflow.json()["exports"][0]["id"] == export["id"]

                downloaded = await client.get(export["download_path"])
                assert downloaded.status_code == 200
                assert downloaded.headers["content-type"] == "application/zip"
                assert hashlib.sha256(downloaded.content).hexdigest() == export["zip_sha256"]
                with zipfile.ZipFile(io.BytesIO(downloaded.content)) as archive:
                    assert len(archive.namelist()) == len(listed.json())
                    assert all(entry.startswith("study-planner/") for entry in archive.namelist())

                repeated_export = await client.post(
                    f"/api/v1/projects/{project_id}/exports",
                    json={
                        "validation_report_id": report["id"],
                        "confirm": True,
                    },
                )
                assert repeated_export.json()["id"] == export["id"]

            async with factory() as session, session.begin():
                run = await session.get(AgentRun, UUID(generation["run_id"]))
                document_count = await session.scalar(
                    select(func.count())
                    .select_from(ProjectDocument)
                    .where(ProjectDocument.project_id == UUID(project_id))
                )
                event_count = await session.scalar(
                    select(func.count())
                    .select_from(RunEvent)
                    .where(RunEvent.run_id == UUID(generation["run_id"]))
                )
                facts = list(
                    (await session.execute(select(Fact).where(Fact.project_id == UUID(project_id))))
                    .scalars()
                    .all()
                )
                fact_source_count = await session.scalar(
                    select(func.count())
                    .select_from(FactSource)
                    .where(FactSource.project_id == UUID(project_id))
                )
                requirements = list(
                    (
                        await session.execute(
                            select(Requirement).where(Requirement.project_id == UUID(project_id))
                        )
                    )
                    .scalars()
                    .all()
                )
                criteria_count = await session.scalar(
                    select(func.count())
                    .select_from(AcceptanceCriterion)
                    .where(AcceptanceCriterion.project_id == UUID(project_id))
                )
                assert run is not None
                assert run.status == "completed"
                assert document_count == len(generation["documents"])
                assert event_count == 5
                assert {fact.classification for fact in facts} == {
                    "confirmed_fact",
                    "assumption",
                }
                assert any(fact.approval_status == "unconfirmed" for fact in facts)
                assert fact_source_count == 1
                assert len(requirements) == 1
                assert requirements[0].requirement_key == "REQ-001"
                assert criteria_count == 1

            resumed_app = create_app(
                settings=settings,
                provider=provider,
                database_session_factory=factory,
            )
            async with AsyncClient(
                transport=ASGITransport(app=resumed_app),
                base_url="http://test",
            ) as client:
                deleted = await client.delete(f"/api/v1/projects/{project_id}")
                assert deleted.status_code == 204
                missing_documents = await client.get(f"/api/v1/projects/{project_id}/documents")
                assert missing_documents.status_code == 404

            async with factory() as session, session.begin():
                run_count = await session.scalar(
                    select(func.count())
                    .select_from(AgentRun)
                    .where(AgentRun.id == UUID(generation["run_id"]))
                )
                remaining_documents = await session.scalar(
                    select(func.count())
                    .select_from(ProjectDocument)
                    .where(ProjectDocument.project_id == UUID(project_id))
                )
                remaining_events = await session.scalar(
                    select(func.count())
                    .select_from(RunEvent)
                    .where(RunEvent.run_id == UUID(generation["run_id"]))
                )
                deletion_audit = await session.scalar(
                    select(func.count())
                    .select_from(AuditEvent)
                    .where(
                        AuditEvent.subject_id == UUID(project_id),
                        AuditEvent.action_code == "project.deleted",
                    )
                )
                assert run_count == 0
                assert remaining_documents == 0
                assert remaining_events == 0
                assert deletion_audit == 1
        finally:
            await engine.dispose()

    asyncio.run(verify())


def test_html_workflow_session_survives_app_recreation(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    class StubProvider:
        async def clarify(self, intake: dict[str, str]) -> ClarificationResult:
            return ClarificationResult(
                questions=[
                    FollowUpQuestion(
                        question="Should this planner support reminders?",
                        impact="This affects the first-release scope.",
                        blocking=False,
                    )
                ]
            )

        async def generate(self, intake, answers) -> GeneratedDocuments:
            return GeneratedDocuments(
                project_name="Durable Planner",
                project_slug="durable-planner",
                purpose="Help people plan useful work.",
                intended_users=["Local users"],
                facts=[],
                accepted_proposals=[],
                assumptions=[],
                open_questions=[],
                constraints=[],
                exclusions=[],
                project_brief="A small planning tool.",
                requirements=(
                    "## Requirements\n\n"
                    "- REQ-001: A user can create a task.\n\n"
                    "### Acceptance criteria\n\n"
                    "- Given a user, when a task is saved, then it appears in the list."
                ),
                implementation_plan="1. Create a task form.",
            )

    async def verify() -> None:
        provider = StubProvider()
        settings = Settings("", "gemini-3.8-flash", "127.0.0.1", 8000)
        first_app = create_app(
            settings=settings,
            provider=provider,
            database_session_factory=session_factory,
        )
        async with AsyncClient(
            transport=ASGITransport(app=first_app),
            base_url="http://test",
        ) as first_client:
            home = await first_client.get("/")
            csrf_match = re.search(r'name="csrf_token" value="([^"]+)"', home.text)
            assert csrf_match
            clarification = await first_client.post(
                "/clarify",
                data={
                    "csrf_token": csrf_match.group(1),
                    "idea": "A durable local planner",
                    "profile": "compact",
                    "consent": "yes",
                },
            )
            assert clarification.status_code == 200
            assert "Should this planner support reminders?" in clarification.text
            session_id = first_client.cookies.get("context_os_session")
            assert session_id
            csrf_match = re.search(
                r'name="csrf_token" value="([^"]+)"',
                clarification.text,
            )
            assert csrf_match
            csrf_token = csrf_match.group(1)

        second_app = create_app(
            settings=settings,
            provider=provider,
            database_session_factory=session_factory,
        )
        async with AsyncClient(
            transport=ASGITransport(app=second_app),
            base_url="http://test",
            cookies={"context_os_session": session_id},
        ) as second_client:
            home_after_restart = await second_client.get("/")
            assert "A durable local planner" in home_after_restart.text
            review = await second_client.post(
                "/review",
                data={"csrf_token": csrf_token, "unknown_0": "yes"},
            )
            assert review.status_code == 200
            assert "Durable Planner" in review.text
            csrf_match = re.search(r'name="csrf_token" value="([^"]+)"', review.text)
            assert csrf_match
            csrf_token = csrf_match.group(1)

        third_app = create_app(
            settings=settings,
            provider=provider,
            database_session_factory=session_factory,
        )
        async with AsyncClient(
            transport=ASGITransport(app=third_app),
            base_url="http://test",
            cookies={"context_os_session": session_id},
        ) as third_client:
            download = await third_client.post("/download", data={"csrf_token": csrf_token})
            assert download.status_code == 200
            assert download.headers["content-type"] == "application/zip"
            assert download.content[:2] == b"PK"

        async with session_factory() as session, session.begin():
            await session.execute(
                delete(WebSession).where(
                    WebSession.session_id_hash == hashlib.sha256(session_id.encode()).hexdigest()
                )
            )

    asyncio.run(verify())


def test_generate_api_records_provider_failure_without_partial_documents() -> None:
    class FailingProvider:
        async def clarify(self, intake: dict[str, str]) -> ClarificationResult:
            return ClarificationResult()

        async def generate(self, intake, answers) -> GeneratedDocuments:
            raise ProviderError("Safe test provider failure.")

    async def verify() -> None:
        url = os.environ.get("CONTEXT_OS_TEST_DATABASE_URL")
        if not url:
            pytest.skip("A dedicated PostgreSQL test database is not configured.")
        engine = create_database_engine(url)
        factory = create_session_factory(engine)
        settings = Settings(
            gemini_api_key="integration-test-key",
            gemini_model="gemini-3.8-flash",
            host="127.0.0.1",
            port=8000,
        )
        try:
            app = create_app(
                settings=settings,
                provider=FailingProvider(),
                database_session_factory=factory,
            )
            async with AsyncClient(
                transport=ASGITransport(app=app),
                base_url="http://test",
            ) as client:
                created = await client.post(
                    "/api/v1/projects",
                    json={
                        "name": "Failed generation",
                        "idea": "A project whose provider call will fail.",
                    },
                )
                project_id = created.json()["project"]["id"]
                failed = await client.post(
                    f"/api/v1/projects/{project_id}/generate",
                    json={"consent": True},
                    headers={"Idempotency-Key": "failed-generation-0001"},
                )
                assert failed.status_code == 502
                assert failed.json()["code"] == "provider_request_failed"
                assert "Safe test provider failure" not in failed.text

            async with factory() as session, session.begin():
                run = (
                    await session.execute(
                        select(AgentRun).where(AgentRun.project_id == UUID(project_id))
                    )
                ).scalar_one()
                document_count = await session.scalar(
                    select(func.count())
                    .select_from(ProjectDocument)
                    .where(ProjectDocument.project_id == UUID(project_id))
                )
                event_count = await session.scalar(
                    select(func.count()).select_from(RunEvent).where(RunEvent.run_id == run.id)
                )
                assert run.status == "failed"
                assert run.safe_error_code == "provider_request_failed"
                assert run.retryable is True
                assert document_count == 0
                assert event_count == 3
        finally:
            await engine.dispose()

    asyncio.run(verify())


def test_generate_api_rejects_duplicate_requirements_without_partial_persistence() -> None:
    class InvalidRequirementsProvider:
        async def clarify(self, intake: dict[str, str]) -> ClarificationResult:
            return ClarificationResult()

        async def generate(self, intake, answers) -> GeneratedDocuments:
            return GeneratedDocuments(
                project_name="Duplicate Requirements",
                project_slug="duplicate-requirements",
                purpose="Test that invalid requirement IDs do not publish partial data.",
                project_brief="A test project.",
                requirements="REQ-001: Add a session.\nREQ-001: Remove a session.",
                implementation_plan="1. Add the test.",
            )

    async def verify() -> None:
        url = os.environ.get("CONTEXT_OS_TEST_DATABASE_URL")
        if not url:
            pytest.skip("A dedicated PostgreSQL test database is not configured.")
        engine = create_database_engine(url)
        factory = create_session_factory(engine)
        settings = Settings(
            gemini_api_key="integration-test-key",
            gemini_model="gemini-3.8-flash",
            host="127.0.0.1",
            port=8000,
        )
        try:
            app = create_app(
                settings=settings,
                provider=InvalidRequirementsProvider(),
                database_session_factory=factory,
            )
            async with AsyncClient(
                transport=ASGITransport(app=app),
                base_url="http://test",
            ) as client:
                created = await client.post(
                    "/api/v1/projects",
                    json={
                        "name": "Duplicate Requirements",
                        "idea": "A project with duplicate generated requirement IDs.",
                    },
                )
                project_id = created.json()["project"]["id"]
                failed = await client.post(
                    f"/api/v1/projects/{project_id}/generate",
                    json={"consent": True},
                    headers={"Idempotency-Key": "duplicate-requirements-0001"},
                )
                assert failed.status_code == 422
                assert failed.json()["code"] == "requirements_structure_invalid"

            async with factory() as session, session.begin():
                run = (
                    await session.execute(
                        select(AgentRun).where(AgentRun.project_id == UUID(project_id))
                    )
                ).scalar_one()
                document_count = await session.scalar(
                    select(func.count())
                    .select_from(ProjectDocument)
                    .where(ProjectDocument.project_id == UUID(project_id))
                )
                requirement_count = await session.scalar(
                    select(func.count())
                    .select_from(Requirement)
                    .where(Requirement.project_id == UUID(project_id))
                )
                assert run.status == "failed"
                assert run.safe_error_code == "requirements_structure_invalid"
                assert document_count == 0
                assert requirement_count == 0
        finally:
            await engine.dispose()

    asyncio.run(verify())


def test_project_api_reports_when_database_schema_is_not_migrated() -> None:
    async def verify() -> None:
        url = os.environ.get("CONTEXT_OS_TEST_DATABASE_URL")
        if not url:
            pytest.skip("A dedicated PostgreSQL test database is not configured.")
        schema = f"ctx_os_unmigrated_{uuid4().hex}"
        admin_engine = create_database_engine(url)
        try:
            async with admin_engine.begin() as connection:
                await connection.execute(text(f'CREATE SCHEMA "{schema}"'))
            request_engine = create_async_engine(
                url,
                connect_args={"server_settings": {"search_path": schema}},
            )
            try:
                app = create_app(database_session_factory=create_session_factory(request_engine))
                async with AsyncClient(
                    transport=ASGITransport(app=app),
                    base_url="http://test",
                ) as client:
                    response = await client.get("/api/v1/projects")
                assert response.status_code == 503
                assert response.json()["code"] == "database_unavailable"
                assert "migrations" in response.json()["detail"]
            finally:
                await request_engine.dispose()
        finally:
            async with admin_engine.begin() as connection:
                await connection.execute(text(f'DROP SCHEMA "{schema}"'))
            await admin_engine.dispose()

    asyncio.run(verify())


def _source(idea: str) -> SourceInput:
    return SourceInput(
        source_kind="idea",
        content=idea,
        source_role="idea",
        safe_label="Original idea",
    )


async def _workspace_id(factory: async_sessionmaker[AsyncSession]) -> UUID:
    async with factory() as session, session.begin():
        workspace = (
            await session.execute(select(Workspace).where(Workspace.mode == "local"))
        ).scalar_one()
        return workspace.id


async def _create_project(
    factory: async_sessionmaker[AsyncSession],
    workspace_id: UUID,
) -> tuple[UUID, UUID]:
    async with factory() as session, session.begin():
        project, revision = await create_project(
            session,
            workspace_id=workspace_id,
            name="Repository test",
            slug=f"repo-test-{uuid4().hex}",
            revision=_revision_input("Initial idea"),
            sources=[_source("Initial idea")],
        )
        return project.id, revision.id


async def _delete_project(
    factory: async_sessionmaker[AsyncSession],
    workspace_id: UUID,
    project_id: UUID,
) -> None:
    async with factory() as session, session.begin():
        await session.execute(
            delete(Project).where(
                Project.workspace_id == workspace_id,
                Project.id == project_id,
            )
        )


async def _revision_count(
    factory: async_sessionmaker[AsyncSession],
    project_id: UUID,
) -> int:
    async with factory() as session, session.begin():
        return int(
            (
                await session.execute(
                    select(func.count())
                    .select_from(ProjectRevision)
                    .where(ProjectRevision.project_id == project_id)
                )
            ).scalar_one()
        )


async def _run_count(
    factory: async_sessionmaker[AsyncSession],
    project_id: UUID,
) -> int:
    async with factory() as session, session.begin():
        return int(
            (
                await session.execute(
                    select(func.count())
                    .select_from(AgentRun)
                    .where(AgentRun.project_id == project_id)
                )
            ).scalar_one()
        )


def test_project_reads_and_revision_sources_are_workspace_scoped(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    async def verify() -> None:
        workspace_id = await _workspace_id(session_factory)
        project_id, revision_id = await _create_project(session_factory, workspace_id)
        try:
            async with session_factory() as session, session.begin():
                assert (
                    await get_project(session, workspace_id=uuid4(), project_id=project_id) is None
                )
                assert (
                    await get_project(session, workspace_id=workspace_id, project_id=uuid4())
                    is None
                )
                assert (
                    await get_project_revision(
                        session,
                        workspace_id=uuid4(),
                        project_id=project_id,
                        revision_id=revision_id,
                    )
                    is None
                )
                assert (
                    await get_project_revision(
                        session,
                        workspace_id=workspace_id,
                        project_id=uuid4(),
                        revision_id=revision_id,
                    )
                    is None
                )
                projects = await list_projects(session, workspace_id=workspace_id, limit=100)
                assert any(project.id == project_id for project in projects)
            async with session_factory() as session, session.begin():
                link_count = (
                    await session.execute(
                        select(func.count())
                        .select_from(ProjectRevisionSource)
                        .where(
                            ProjectRevisionSource.workspace_id == workspace_id,
                            ProjectRevisionSource.project_id == project_id,
                            ProjectRevisionSource.revision_id == revision_id,
                        )
                    )
                ).scalar_one()
                assert link_count == 1
        finally:
            await _delete_project(session_factory, workspace_id, project_id)

    asyncio.run(verify())


def test_run_creation_rejects_wrong_workspace_and_stale_revision(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    async def verify() -> None:
        workspace_id = await _workspace_id(session_factory)
        project_id, original_revision_id = await _create_project(session_factory, workspace_id)
        request_hash = canonical_request_hash({"action": "generate"})
        try:
            with pytest.raises(ProjectNotFoundError):
                async with session_factory() as session, session.begin():
                    await create_or_get_run(
                        session,
                        workspace_id=uuid4(),
                        project_id=project_id,
                        revision_id=original_revision_id,
                        idempotency_key="wrong-workspace",
                        request_hash=request_hash,
                        prompt_version="prompt-v1",
                        template_pack_version="templates-v1",
                    )

            async with session_factory() as session, session.begin():
                await create_project_revision(
                    session,
                    workspace_id=workspace_id,
                    project_id=project_id,
                    expected_revision=1,
                    revision=_revision_input("Current revision"),
                )
            with pytest.raises(RevisionConflictError) as stale_revision:
                async with session_factory() as session, session.begin():
                    await create_or_get_run(
                        session,
                        workspace_id=workspace_id,
                        project_id=project_id,
                        revision_id=original_revision_id,
                        idempotency_key="stale-revision",
                        request_hash=request_hash,
                        prompt_version="prompt-v1",
                        template_pack_version="templates-v1",
                    )
            assert stale_revision.value.actual_revision == 2
            assert await _run_count(session_factory, project_id) == 0
        finally:
            await _delete_project(session_factory, workspace_id, project_id)

    asyncio.run(verify())


@pytest.mark.parametrize(
    ("idempotency_key", "request_hash"),
    [
        ("", "a" * 64),
        ("valid-key", "z" * 64),
    ],
)
def test_database_constraints_reject_malformed_idempotency_metadata(
    session_factory: async_sessionmaker[AsyncSession],
    idempotency_key: str,
    request_hash: str,
) -> None:
    async def verify() -> None:
        workspace_id = await _workspace_id(session_factory)
        project_id, revision_id = await _create_project(session_factory, workspace_id)
        try:
            with pytest.raises(IntegrityError):
                async with session_factory() as session, session.begin():
                    session.add(
                        AgentRun(
                            workspace_id=workspace_id,
                            project_id=project_id,
                            revision_id=revision_id,
                            idempotency_key=idempotency_key,
                            request_hash=request_hash,
                            prompt_version="prompt-v1",
                            template_pack_version="templates-v1",
                        )
                    )
                    await session.flush()
        finally:
            await _delete_project(session_factory, workspace_id, project_id)

    asyncio.run(verify())


def test_revision_conflict_is_atomic_and_failed_write_rolls_back(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    async def verify() -> None:
        workspace_id = await _workspace_id(session_factory)
        project_id, _ = await _create_project(session_factory, workspace_id)
        try:
            async with session_factory() as session, session.begin():
                revision = await create_project_revision(
                    session,
                    workspace_id=workspace_id,
                    project_id=project_id,
                    expected_revision=1,
                    revision=_revision_input("Revised idea"),
                    sources=[_source("Revised idea")],
                )
                assert revision.revision_number == 2

            with pytest.raises(RevisionConflictError) as conflict:
                async with session_factory() as session, session.begin():
                    await create_project_revision(
                        session,
                        workspace_id=workspace_id,
                        project_id=project_id,
                        expected_revision=1,
                        revision=_revision_input("Stale idea"),
                    )
            assert conflict.value.actual_revision == 2
            assert await _revision_count(session_factory, project_id) == 2

            with pytest.raises(RepositoryInputError, match="Source content"):
                async with session_factory() as session, session.begin():
                    await create_project_revision(
                        session,
                        workspace_id=workspace_id,
                        project_id=project_id,
                        expected_revision=2,
                        revision=_revision_input("Should not be written"),
                        sources=[_source("x" * 20_001)],
                    )
            assert await _revision_count(session_factory, project_id) == 2

            with pytest.raises(RuntimeError, match="simulate downstream failure"):
                async with session_factory() as session, session.begin():
                    await create_project_revision(
                        session,
                        workspace_id=workspace_id,
                        project_id=project_id,
                        expected_revision=2,
                        revision=_revision_input("Transaction rollback"),
                    )
                    raise RuntimeError("simulate downstream failure")
            assert await _revision_count(session_factory, project_id) == 2
        finally:
            await _delete_project(session_factory, workspace_id, project_id)

    asyncio.run(verify())


def test_concurrent_revision_writes_accept_only_one_expected_revision(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    async def verify() -> None:
        workspace_id = await _workspace_id(session_factory)
        project_id, _ = await _create_project(session_factory, workspace_id)

        async def revise(idea: str) -> object:
            try:
                async with session_factory() as session, session.begin():
                    result = await create_project_revision(
                        session,
                        workspace_id=workspace_id,
                        project_id=project_id,
                        expected_revision=1,
                        revision=_revision_input(idea),
                    )
                    return result
            except RevisionConflictError as exc:
                return exc

        try:
            outcomes = await asyncio.gather(revise("Concurrent A"), revise("Concurrent B"))
            assert sum(isinstance(outcome, RevisionConflictError) for outcome in outcomes) == 1
            assert sum(isinstance(outcome, ProjectRevision) for outcome in outcomes) == 1
            assert await _revision_count(session_factory, project_id) == 2
        finally:
            await _delete_project(session_factory, workspace_id, project_id)

    asyncio.run(verify())


def test_run_idempotency_replay_conflict_and_concurrent_retry(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    async def verify() -> None:
        workspace_id = await _workspace_id(session_factory)
        project_id, revision_id = await _create_project(session_factory, workspace_id)
        request_hash = canonical_request_hash({"action": "generate", "profile": "compact"})

        async def create_run(key: str, digest: str = request_hash) -> tuple[UUID, bool]:
            async with session_factory() as session, session.begin():
                run, created = await create_or_get_run(
                    session,
                    workspace_id=workspace_id,
                    project_id=project_id,
                    revision_id=revision_id,
                    idempotency_key=key,
                    request_hash=digest,
                    prompt_version="prompt-v1",
                    template_pack_version="templates-v1",
                )
                return run.id, created

        try:
            first_id, created = await create_run("stable-key")
            replay_id, replayed = await create_run("stable-key")
            assert created is True
            assert replayed is False
            assert replay_id == first_id

            with pytest.raises(IdempotencyConflictError):
                await create_run("stable-key", "f" * 64)

            concurrent = await asyncio.gather(
                create_run("parallel-key"),
                create_run("parallel-key"),
            )
            assert len({run_id for run_id, _ in concurrent}) == 1
            assert sum(was_created for _, was_created in concurrent) == 1
            assert await _run_count(session_factory, project_id) == 2
        finally:
            await _delete_project(session_factory, workspace_id, project_id)
