from __future__ import annotations

import pytest
from sqlalchemy import ForeignKeyConstraint

from app.db.engine import (
    DATABASE_HOST_ENV,
    DATABASE_NAME_ENV,
    DATABASE_PASSWORD_ENV,
    DATABASE_PORT_ENV,
    DATABASE_URL_ENV,
    DATABASE_USER_ENV,
    DatabaseConfigurationError,
    create_database_engine,
    database_url_from_env,
)
from app.db.models import Base


def test_database_url_requires_postgresql_asyncpg(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv(
        DATABASE_URL_ENV,
        "postgresql+asyncpg://context_os:test-only@localhost/context_os",
    )

    url = database_url_from_env()

    assert url.drivername == "postgresql+asyncpg"
    assert url.host == "localhost"
    assert url.database == "context_os"


@pytest.mark.parametrize(
    "value",
    [
        "",
        "not-a-url",
        "sqlite+aiosqlite:///context_os.db",
        "postgresql+asyncpg://localhost/",
    ],
)
def test_database_url_rejects_missing_or_unsupported_configuration(
    monkeypatch: pytest.MonkeyPatch,
    value: str,
) -> None:
    monkeypatch.setenv(DATABASE_URL_ENV, value)

    with pytest.raises(DatabaseConfigurationError):
        database_url_from_env()


def test_database_url_builds_safely_from_separate_connection_settings(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv(DATABASE_URL_ENV, raising=False)
    monkeypatch.setenv(DATABASE_HOST_ENV, "localhost")
    monkeypatch.setenv(DATABASE_PORT_ENV, "5433")
    monkeypatch.setenv(DATABASE_USER_ENV, "context user")
    monkeypatch.setenv(DATABASE_PASSWORD_ENV, "p@ss:/word")
    monkeypatch.setenv(DATABASE_NAME_ENV, "context os")

    url = database_url_from_env()

    assert url.drivername == "postgresql+asyncpg"
    assert url.password == "p@ss:/word"
    assert url.username == "context user"
    assert url.database == "context os"
    assert url.port == 5433


def test_database_component_configuration_must_be_complete(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv(DATABASE_URL_ENV, raising=False)
    for name in (
        DATABASE_HOST_ENV,
        DATABASE_PORT_ENV,
        DATABASE_USER_ENV,
        DATABASE_PASSWORD_ENV,
        DATABASE_NAME_ENV,
    ):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv(DATABASE_HOST_ENV, "localhost")

    with pytest.raises(DatabaseConfigurationError, match="provided together"):
        database_url_from_env()


def test_explicit_engine_url_is_also_validated() -> None:
    with pytest.raises(DatabaseConfigurationError):
        create_database_engine("sqlite+aiosqlite:///not-postgresql.db")


@pytest.mark.parametrize(
    ("table_name", "constraint_name", "column_pairs"),
    [
        (
            "agent_runs",
            "fk_agent_runs_consent",
            [
                ("workspace_id", "workspace_id"),
                ("project_id", "project_id"),
                ("revision_id", "revision_id"),
                ("consent_id", "id"),
            ],
        ),
        (
            "validation_findings",
            "fk_validation_findings_report",
            [
                ("workspace_id", "workspace_id"),
                ("project_id", "project_id"),
                ("revision_id", "revision_id"),
                ("report_id", "id"),
            ],
        ),
        (
            "validation_findings",
            "fk_validation_findings_document",
            [
                ("workspace_id", "workspace_id"),
                ("project_id", "project_id"),
                ("revision_id", "revision_id"),
                ("document_id", "id"),
            ],
        ),
        (
            "validation_findings",
            "fk_validation_findings_requirement",
            [
                ("workspace_id", "workspace_id"),
                ("project_id", "project_id"),
                ("revision_id", "revision_id"),
                ("requirement_id", "id"),
            ],
        ),
        (
            "exports",
            "fk_exports_validation_report",
            [
                ("workspace_id", "workspace_id"),
                ("project_id", "project_id"),
                ("revision_id", "revision_id"),
                ("validation_report_id", "id"),
            ],
        ),
        (
            "export_documents",
            "fk_export_documents_document",
            [
                ("workspace_id", "workspace_id"),
                ("project_id", "project_id"),
                ("revision_id", "revision_id"),
                ("document_id", "id"),
            ],
        ),
        (
            "export_documents",
            "fk_export_documents_export",
            [
                ("workspace_id", "workspace_id"),
                ("project_id", "project_id"),
                ("revision_id", "revision_id"),
                ("export_id", "id"),
            ],
        ),
    ],
)
def test_revision_owned_references_are_revision_scoped(
    table_name: str,
    constraint_name: str,
    column_pairs: list[tuple[str, str]],
) -> None:
    table = Base.metadata.tables[table_name]
    constraint = next(
        candidate
        for candidate in table.foreign_key_constraints
        if isinstance(candidate, ForeignKeyConstraint) and candidate.name == constraint_name
    )
    actual_pairs = [
        (element.parent.name, element.target_fullname.rsplit(".", maxsplit=1)[-1])
        for element in constraint.elements
    ]

    assert actual_pairs == column_pairs
