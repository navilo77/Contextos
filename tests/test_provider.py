from __future__ import annotations

import asyncio
import json

import httpx
import pytest

from app.config import DEFAULT_GEMINI_MODEL, ProviderConfigurationError, Settings
from app.models import GeneratedDocuments
from app.services.provider import GeminiAIStudioProvider, ProviderError


def test_missing_gemini_key_is_reported():
    settings = Settings("", "gemini-3.8-flash", "127.0.0.1", 8000)
    with pytest.raises(ProviderConfigurationError, match="GEMINI_API_KEY"):
        settings.require_provider()


def test_gemini_defaults_load_from_local_dotenv():
    settings = Settings.from_env()
    assert settings.gemini_model == DEFAULT_GEMINI_MODEL
    assert isinstance(settings.gemini_api_key, str)


def test_invalid_gemini_model_name_is_rejected():
    settings = Settings("key", "../model", "127.0.0.1", 8000)
    with pytest.raises(ProviderConfigurationError, match="GEMINI_MODEL"):
        settings.require_provider()


@pytest.mark.parametrize("host", ["0.0.0.0", "192.168.1.20", "context-os.example"])
def test_settings_reject_non_loopback_hosts(host):
    with pytest.raises(ValueError, match="loopback"):
        Settings("", "gemini-3.8-flash", host, 8000)


@pytest.mark.parametrize("host", ["127.0.0.1", "::1", "localhost"])
def test_settings_allow_loopback_hosts(host):
    settings = Settings("", "gemini-3.8-flash", host, 8000)
    assert settings.host == host


@pytest.mark.parametrize(
    "origin",
    [
        "http://192.168.1.20:3000",
        "https://127.0.0.1:3000",
        "http://127.0.0.1:3000/path",
        "http://user@127.0.0.1:3000",
    ],
)
def test_settings_reject_non_loopback_frontend_origins(origin):
    with pytest.raises(ValueError, match="CONTEXT_OS_FRONTEND_ORIGIN"):
        Settings("", "gemini-3.8-flash", "127.0.0.1", 8000, origin)


def test_settings_reject_invalid_port():
    with pytest.raises(ValueError, match="CONTEXT_OS_PORT"):
        Settings("", "gemini-3.8-flash", "127.0.0.1", 65536)


def test_gemini_ai_studio_rest_request_uses_native_endpoint_and_json_mode():
    observed = {}

    def handler(request: httpx.Request) -> httpx.Response:
        observed["url"] = str(request.url)
        observed["api_key"] = request.headers.get("x-goog-api-key")
        observed["body"] = json.loads(request.content)
        return httpx.Response(
            200,
            json={
                "candidates": [
                    {
                        "content": {
                            "parts": [
                                {
                                    "text": '{"questions":[{"question":"Who uses it?",'
                                    '"impact":"Changes scope.","blocking":false}]}'
                                }
                            ]
                        }
                    }
                ]
            },
        )

    transport = httpx.MockTransport(handler)
    provider = GeminiAIStudioProvider(
        Settings("test-api-key", "gemini-3.8-flash", "127.0.0.1", 8000),
        transport=transport,
    )
    result = asyncio.run(provider.clarify({"idea": "A study planner"}))

    assert observed["url"] == (
        "https://generativelanguage.googleapis.com/v1beta/models/gemini-3.8-flash:generateContent"
    )
    assert observed["api_key"] == "test-api-key"
    assert observed["body"]["generationConfig"]["responseMimeType"] == "application/json"
    assert result.questions[0].question == "Who uses it?"


def test_gemini_timeout_error_explains_network_troubleshooting():
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ReadTimeout("test timeout", request=request)

    provider = GeminiAIStudioProvider(
        Settings("test-api-key", "gemini-3.8-flash", "127.0.0.1", 8000),
        transport=httpx.MockTransport(handler),
    )
    with pytest.raises(ProviderError, match="internet/VPN/proxy/firewall"):
        asyncio.run(provider.clarify({"idea": "test"}))


@pytest.mark.parametrize(
    ("status", "message"),
    [
        (401, "API key যাচাই হয়নি"),
        (403, "অনুমোদিত হয়নি"),
        (404, "model পাওয়া যায়নি"),
        (429, "quota"),
    ],
)
def test_gemini_http_errors_explain_common_fixes(status, message):
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            status,
            json={"error": {"message": "private provider diagnostic"}},
        )

    provider = GeminiAIStudioProvider(
        Settings("test-api-key", "gemini-3.8-flash", "127.0.0.1", 8000),
        transport=httpx.MockTransport(handler),
    )
    with pytest.raises(ProviderError, match=message) as error:
        asyncio.run(provider.clarify({"idea": "test"}))
    assert "private provider diagnostic" not in str(error.value)


def test_invalid_structured_output_gets_only_one_repair_attempt(monkeypatch):
    settings = Settings("key", "gemini-3.8-flash", "127.0.0.1", 8000)
    provider = GeminiAIStudioProvider(settings)
    calls = []
    valid = {
        "project_name": "Study Planner",
        "project_slug": "study-planner",
        "purpose": "Help learners plan.",
        "project_brief": "A planning app.",
        "requirements": "REQ-001: Add a plan. Acceptance criteria: it is saved.",
        "implementation_plan": "1. Build and test.",
    }

    async def fake_complete(system, payload):
        calls.append(payload)
        return {"project_name": "Invalid"} if len(calls) == 1 else valid

    monkeypatch.setattr(provider, "_complete", fake_complete)
    result = asyncio.run(provider.generate({"idea": "Study planner"}, {}))
    assert isinstance(result, GeneratedDocuments)
    assert len(calls) == 2
    assert "invalid_previous_output" in calls[1]


def test_still_invalid_repair_fails_explicitly(monkeypatch):
    settings = Settings("key", "gemini-3.8-flash", "127.0.0.1", 8000)
    provider = GeminiAIStudioProvider(settings)
    calls = 0

    async def fake_complete(system, payload):
        nonlocal calls
        calls += 1
        return {"project_name": "Still invalid"}

    monkeypatch.setattr(provider, "_complete", fake_complete)

    async def generate():
        return await provider.generate({"idea": "Study planner"}, {})

    with pytest.raises(ProviderError, match="incomplete project documents"):
        asyncio.run(generate())
    assert calls == 2
