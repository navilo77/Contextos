from __future__ import annotations

import json
from pathlib import Path

from fastapi import FastAPI
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker
from starlette.middleware.cors import CORSMiddleware

from app.config import Settings
from app.db.engine import (
    create_database_engine,
    create_session_factory,
    database_is_configured,
)
from app.modules.discovery.service import DiscoveryService
from app.modules.document_generation.service import DocumentGenerationService
from app.ports.ai_provider import AIProvider
from app.services.provider import GeminiAIStudioProvider
from app.session_store import SessionStore
from app.web.application import create_web_app

SCHEMA_PATH = Path(__file__).resolve().parents[1] / "schemas" / "project-context.schema.json"


def create_app(
    settings: Settings | None = None,
    provider: AIProvider | None = None,
    session_store: SessionStore | None = None,
    database_session_factory: async_sessionmaker[AsyncSession] | None = None,
) -> FastAPI:
    resolved_settings = settings or Settings.from_env()
    resolved_provider = provider or GeminiAIStudioProvider(resolved_settings)
    resolved_sessions = session_store or SessionStore()
    database_engine: AsyncEngine | None = None
    resolved_database_factory = database_session_factory
    if resolved_database_factory is None and database_is_configured():
        database_engine = create_database_engine()
        resolved_database_factory = create_session_factory(database_engine)
    schema = json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))
    discovery_service = DiscoveryService(resolved_settings, resolved_provider)
    generation_service = DocumentGenerationService(
        resolved_settings,
        resolved_provider,
        schema,
    )
    app = create_web_app(
        discovery_service=discovery_service,
        generation_service=generation_service,
        session_store=resolved_sessions,
        database_session_factory=resolved_database_factory,
        database_engine=database_engine,
    )
    app.add_middleware(
        CORSMiddleware,
        allow_origins=[resolved_settings.frontend_origin.rstrip("/")],
        allow_methods=["DELETE", "GET", "PATCH", "POST", "PUT"],
        allow_headers=["Content-Type", "Idempotency-Key"],
    )
    return app
