from __future__ import annotations

import asyncio
from uuid import uuid4

import pytest
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.db.models import Workspace
from app.db.repositories import (
    ActiveTransactionRequiredError,
    RepositoryInputError,
    canonical_request_hash,
    create_or_get_run,
    get_project,
    list_projects,
)


def test_canonical_request_hash_is_order_independent() -> None:
    first = canonical_request_hash({"profile": "compact", "intake": {"idea": "Planner"}})
    reordered = canonical_request_hash({"intake": {"idea": "Planner"}, "profile": "compact"})

    assert first == reordered
    assert len(first) == 64


@pytest.mark.parametrize(
    "payload",
    [
        {"value": float("nan")},
        {"value": object()},
        {"value": "x" * 1_000_001},
    ],
)
def test_canonical_request_hash_rejects_non_json_or_unbounded_payload(
    payload: dict[str, object],
) -> None:
    with pytest.raises(RepositoryInputError):
        canonical_request_hash(payload)


def test_repository_requires_an_explicit_transaction() -> None:
    async def verify() -> None:
        engine = create_async_engine(
            "postgresql+asyncpg://context_os:test-only@127.0.0.1/context_os"
        )
        try:
            factory = async_sessionmaker(engine)
            async with factory() as session:
                with pytest.raises(ActiveTransactionRequiredError):
                    await get_project(
                        session,
                        workspace_id=uuid4(),
                        project_id=uuid4(),
                    )
            async with factory() as session:
                session.add(Workspace(mode="local"))
                with pytest.raises(ActiveTransactionRequiredError):
                    await get_project(
                        session,
                        workspace_id=uuid4(),
                        project_id=uuid4(),
                    )
        finally:
            await engine.dispose()

    asyncio.run(verify())


def test_run_repository_rejects_an_overlong_idempotency_key_before_io() -> None:
    async def verify() -> None:
        engine = create_async_engine(
            "postgresql+asyncpg://context_os:test-only@127.0.0.1/context_os"
        )
        try:
            factory = async_sessionmaker(engine)
            async with factory() as session, session.begin():
                with pytest.raises(RepositoryInputError, match="Idempotency key"):
                    await create_or_get_run(
                        session,
                        workspace_id=uuid4(),
                        project_id=uuid4(),
                        revision_id=uuid4(),
                        idempotency_key="x" * 129,
                        request_hash="a" * 64,
                        prompt_version="prompt-v1",
                        template_pack_version="templates-v1",
                    )
        finally:
            await engine.dispose()

    asyncio.run(verify())


def test_project_repository_rejects_unbounded_pagination_before_io() -> None:
    async def verify() -> None:
        engine = create_async_engine(
            "postgresql+asyncpg://context_os:test-only@127.0.0.1/context_os"
        )
        try:
            factory = async_sessionmaker(engine)
            async with factory() as session, session.begin():
                with pytest.raises(RepositoryInputError, match="Limit must be"):
                    await list_projects(session, workspace_id=uuid4(), limit=101)
        finally:
            await engine.dispose()

    asyncio.run(verify())
