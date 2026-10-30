from __future__ import annotations

import io
import json
import zipfile

import pytest
from fastapi.testclient import TestClient

from app.config import Settings
from app.db.engine import (
    DATABASE_HOST_ENV,
    DATABASE_NAME_ENV,
    DATABASE_PASSWORD_ENV,
    DATABASE_PORT_ENV,
    DATABASE_URL_ENV,
    DATABASE_USER_ENV,
)
from app.main import create_app
from app.models import ClarificationResult, FollowUpQuestion, GeneratedDocuments


class FakeProvider:
    async def clarify(self, intake):
        return ClarificationResult(
            questions=[
                FollowUpQuestion(
                    question="Should users sign in?",
                    impact="This changes account and data requirements.",
                    blocking=False,
                )
            ]
        )

    async def generate(self, intake, answers):
        return GeneratedDocuments(
            project_name="Study Planner",
            project_slug="study-planner",
            purpose="Help learners plan study sessions.",
            intended_users=["Learners"],
            facts=[{"text": "The user selected OAuth login.", "source": "Model invention"}],
            accepted_proposals=[],
            assumptions=[],
            open_questions=[],
            constraints=[],
            exclusions=[],
            project_brief="A focused tool to organize learning sessions.",
            requirements="## Requirements\n\n- REQ-001: A learner can add a study session.\n\n"
            "### Acceptance criteria\n\n- Given a learner, when they save a session, then it appears in their plan.",
            implementation_plan="1. Implement study-session entry.\n2. Verify the acceptance criteria.",
        )


def test_cors_preflight_allows_only_configured_loopback_frontend() -> None:
    settings = Settings("", "gemini-3.8-flash", "127.0.0.1", 8000)
    with TestClient(create_app(settings=settings, provider=FakeProvider())) as client:
        allowed = client.options(
            "/api/v1/projects",
            headers={
                "Origin": "http://127.0.0.1:3000",
                "Access-Control-Request-Method": "POST",
                "Access-Control-Request-Headers": "content-type,idempotency-key",
            },
        )
        assert allowed.status_code == 200
        assert allowed.headers["access-control-allow-origin"] == "http://127.0.0.1:3000"
        assert allowed.headers.get("access-control-allow-credentials") is None

        rejected = client.options(
            "/api/v1/projects",
            headers={
                "Origin": "http://192.168.1.20:3000",
                "Access-Control-Request-Method": "POST",
            },
        )
        assert rejected.status_code == 400
        assert rejected.headers.get("access-control-allow-origin") is None


def test_project_api_reports_when_database_is_not_configured(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    for name in (
        DATABASE_URL_ENV,
        DATABASE_HOST_ENV,
        DATABASE_PORT_ENV,
        DATABASE_USER_ENV,
        DATABASE_PASSWORD_ENV,
        DATABASE_NAME_ENV,
    ):
        monkeypatch.delenv(name, raising=False)

    settings = Settings(
        gemini_api_key="test-key-not-a-secret",
        gemini_model="gemini-3.8-flash",
        host="127.0.0.1",
        port=8000,
    )
    with TestClient(create_app(settings=settings, provider=FakeProvider())) as client:
        response = client.get("/api/v1/projects")
        invalid_request = client.post(
            "/api/v1/projects",
            json={"idea": "private text that should not be echoed"},
        )

    assert response.status_code == 503
    assert response.json()["code"] == "database_unavailable"
    assert invalid_request.status_code == 422
    assert invalid_request.json()["code"] == "invalid_request"
    assert invalid_request.json()["request_id"] == invalid_request.headers["x-request-id"]
    assert "private text that should not be echoed" not in invalid_request.text


def csrf_from(response) -> str:
    import re

    match = re.search(r'name="csrf_token" value="([^"]+)"', response.text)
    assert match
    return match.group(1)


def test_idea_to_download_flow_and_explicit_privacy_consent():
    settings = Settings(
        gemini_api_key="test-key-not-a-secret",
        gemini_model="gemini-3.8-flash",
        host="127.0.0.1",
        port=8000,
    )
    client = TestClient(create_app(settings=settings, provider=FakeProvider()))
    page = client.get("/")
    assert page.status_code == 200
    token = csrf_from(page)
    no_consent = client.post(
        "/clarify",
        data={"csrf_token": token, "idea": "A study planner", "profile": "compact"},
    )
    assert "external-processing সম্মতি প্রয়োজন" in no_consent.text
    assert "test-key-not-a-secret" not in no_consent.text

    clarification = client.post(
        "/clarify",
        data={
            "csrf_token": token,
            "idea": "A study planner for learners",
            "audience": "Learners",
            "profile": "compact",
            "language": "English",
            "consent": "yes",
        },
    )
    assert clarification.status_code == 200
    assert "Should users sign in?" in clarification.text
    review = client.post(
        "/review",
        data={
            "csrf_token": csrf_from(clarification),
            "unknown_0": "yes",
        },
    )
    assert review.status_code == 200
    assert "ZIP download" in review.text
    assert "Study Planner" in review.text
    assert "নিশ্চিত তথ্য" in review.text
    assert "অনুমান" in review.text
    assert "Model invention" not in review.text
    assert "The user selected OAuth login" not in review.text
    download = client.post("/download", data={"csrf_token": csrf_from(review)})
    assert download.status_code == 200
    assert download.headers["content-type"] == "application/zip"
    assert download.content[:2] == b"PK"
    with zipfile.ZipFile(io.BytesIO(download.content)) as archive:
        context_file = next(
            name for name in archive.namelist() if name.endswith("context/project-context.json")
        )
        context = json.loads(archive.read(context_file))
        assert context["facts"] == [
            {"text": "A study planner for learners", "source": "User-provided idea"},
            {"text": "Learners", "source": "User-provided audience"},
        ]


def test_user_can_edit_answers_after_review():
    settings = Settings("test-key", "gemini-3.8-flash", "127.0.0.1", 8000)
    client = TestClient(create_app(settings=settings, provider=FakeProvider()))
    home = client.get("/")
    clarification = client.post(
        "/clarify",
        data={
            "csrf_token": csrf_from(home),
            "idea": "Study planner",
            "profile": "compact",
            "consent": "yes",
        },
    )
    questions = client.post(
        "/review",
        data={"csrf_token": csrf_from(clarification), "answer_0": "Yes, use accounts"},
    )
    assert questions.status_code == 200
    edit = client.post("/edit", data={"csrf_token": csrf_from(questions)})
    assert edit.status_code == 200
    assert "Yes, use accounts" in edit.text


def test_missing_provider_is_reported_without_sending_idea():
    class MustNotRunProvider:
        async def clarify(self, intake):
            raise AssertionError("provider must not be called")

        async def generate(self, intake, answers):
            raise AssertionError("provider must not be called")

    settings = Settings("", "gemini-3.8-flash", "127.0.0.1", 8000)
    client = TestClient(create_app(settings=settings, provider=MustNotRunProvider()))
    page = client.get("/")
    result = client.post(
        "/clarify",
        data={
            "csrf_token": csrf_from(page),
            "idea": "Private idea text",
            "profile": "compact",
            "consent": "yes",
        },
    )
    assert "GEMINI_API_KEY" in result.text
    assert "Private idea text" not in result.text


def test_idea_over_8000_characters_is_accepted_within_new_limit():
    settings = Settings("test-key", "gemini-3.8-flash", "127.0.0.1", 8000)
    client = TestClient(create_app(settings=settings, provider=FakeProvider()))
    page = client.get("/")
    result = client.post(
        "/clarify",
        data={
            "csrf_token": csrf_from(page),
            "idea": "Study planner " * 700,
            "profile": "compact",
            "consent": "yes",
        },
    )
    assert result.status_code == 200
    assert "Should users sign in?" in result.text
    assert "২০,০০০ অক্ষরের" not in result.text


def test_idea_over_20000_characters_is_rejected_with_correct_limit():
    settings = Settings("test-key", "gemini-3.8-flash", "127.0.0.1", 8000)
    client = TestClient(create_app(settings=settings, provider=FakeProvider()))
    page = client.get("/")
    result = client.post(
        "/clarify",
        data={
            "csrf_token": csrf_from(page),
            "idea": "A" * 20_001,
            "profile": "compact",
            "consent": "yes",
        },
    )
    assert result.status_code == 400
    assert "২০,০০০ অক্ষরের" in result.text


def test_invalid_csrf_is_rejected():
    settings = Settings("", "gemini-3.8-flash", "127.0.0.1", 8000)
    client = TestClient(create_app(settings=settings, provider=FakeProvider()))
    result = client.post(
        "/clarify", data={"csrf_token": "forged", "idea": "Idea", "consent": "yes"}
    )
    assert result.status_code == 403


def test_restored_idea_is_html_escaped():
    settings = Settings("test-key", "gemini-3.8-flash", "127.0.0.1", 8000)
    client = TestClient(create_app(settings=settings, provider=FakeProvider()))
    home = client.get("/")
    clarification = client.post(
        "/clarify",
        data={
            "csrf_token": csrf_from(home),
            "idea": "<script>alert(1)</script>",
            "profile": "compact",
            "consent": "yes",
        },
    )
    restored_form = client.post("/edit-idea", data={"csrf_token": csrf_from(clarification)})
    assert "&lt;script&gt;alert(1)&lt;/script&gt;" in restored_form.text
    assert '<textarea id="idea" name="idea"' in restored_form.text
    assert "<script>alert(1)</script>" not in restored_form.text
