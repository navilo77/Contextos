from __future__ import annotations

import io
import json
import zipfile
from pathlib import Path

import pytest
from pydantic import ValidationError

from app.models import GeneratedDocuments
from app.services.package_builder import PackageValidationError, build_package

ROOT = Path(__file__).resolve().parents[1]
SCHEMA = json.loads((ROOT / "schemas" / "project-context.schema.json").read_text(encoding="utf-8"))


def sample_generated(**overrides) -> GeneratedDocuments:
    values = {
        "project_name": "Study Planner",
        "project_slug": "study-planner",
        "purpose": "Help learners organize study sessions.",
        "intended_users": ["Learners"],
        "facts": [{"text": "The user wants a study planning app.", "source": "Idea input"}],
        "accepted_proposals": [],
        "assumptions": [{"text": "The first version is a web app.", "source": "Accepted answer"}],
        "open_questions": [
            {
                "question": "Should plans sync across devices?",
                "impact": "Changes storage needs.",
                "blocking": False,
            }
        ],
        "constraints": [],
        "exclusions": [],
        "project_brief": "Create a simple study planner.",
        "requirements": "## Functional\n\n- REQ-001: A learner can create a study plan.\n\n"
        "### Acceptance criteria\n\n- Given a learner, when they save a plan, then it is shown in their plan list.",
        "implementation_plan": "1. Define the first-release flow.\n2. Implement it and add tests.",
    }
    values.update(overrides)
    return GeneratedDocuments.model_validate(values)


def test_compact_package_is_valid_and_reopens():
    documents, archive_bytes, errors = build_package(
        sample_generated(), profile="compact", language="English", schema=SCHEMA
    )
    assert errors == []
    assert "02-technical/ARCHITECTURE.md" not in documents
    assert "manifest.json" in documents
    readme = documents["README.md"].decode("utf-8")
    assert "[AGENTS.md](AGENTS.md)" in readme
    assert "[manifest.json](manifest.json)" in readme
    manifest = json.loads(documents["manifest.json"])
    assert manifest["validation"]["passed"] is True
    context = json.loads(documents["context/project-context.json"])
    assert {item["path"] for item in context["documents"]} == set(documents) - {"manifest.json"}
    with zipfile.ZipFile(io.BytesIO(archive_bytes)) as archive:
        assert archive.testzip() is None
        assert "study-planner/README.md" in archive.namelist()
        assert len(archive.namelist()) == len(documents)


def test_detailed_package_adds_relevant_technical_documents():
    documents, _, _ = build_package(
        sample_generated(), profile="detailed", language="English", schema=SCHEMA
    )
    assert "02-technical/ARCHITECTURE.md" in documents
    assert "02-technical/SECURITY.md" in documents
    assert "03-quality/TEST_PLAN.md" in documents


def test_model_cannot_choose_an_unsafe_project_slug():
    with pytest.raises(ValidationError):
        sample_generated(project_slug="../outside")


def test_configured_secret_blocks_package():
    generated = sample_generated(
        project_brief="The API key is 'context-secret-12345' and must not be shared."
    )
    with pytest.raises(PackageValidationError, match="Possible credential"):
        build_package(
            generated,
            profile="compact",
            language="English",
            schema=SCHEMA,
            configured_secrets=("context-secret-12345",),
        )


def test_unresolved_template_marker_blocks_package():
    generated = sample_generated(project_brief="## Summary\n\n[TBD]")
    with pytest.raises(PackageValidationError, match="Unresolved template marker"):
        build_package(generated, profile="compact", language="English", schema=SCHEMA)


def test_user_supplied_markdown_links_must_resolve():
    generated = sample_generated(requirements="See [missing file](internal-secret.md).")
    with pytest.raises(PackageValidationError, match="Broken internal link"):
        build_package(generated, profile="compact", language="English", schema=SCHEMA)
