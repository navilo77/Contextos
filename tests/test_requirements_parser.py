from __future__ import annotations

import pytest

from app.modules.document_generation.requirements import parse_requirements


def test_parse_requirements_extracts_stable_ids_and_acceptance_criteria() -> None:
    requirements = parse_requirements(
        "## Requirements\n\n"
        "- req-001: A learner can add a study session.\n\n"
        "### Acceptance criteria\n\n"
        "- The session appears in the plan.\n"
        "2. The session can be edited.\n\n"
        "REQ-2_api: A learner can remove a study session.\n"
    )

    assert len(requirements) == 2
    assert requirements[0].key == "REQ-001"
    assert requirements[0].statement == "A learner can add a study session."
    assert requirements[0].acceptance_criteria == (
        "The session appears in the plan.",
        "The session can be edited.",
    )
    assert requirements[1].key == "REQ-2_API"
    assert requirements[1].acceptance_criteria == ()


def test_parse_requirements_rejects_duplicate_ids_case_insensitively() -> None:
    with pytest.raises(ValueError, match="Duplicate requirement identifier"):
        parse_requirements("REQ-001: Add a session.\nreq-001: Remove a session.")


def test_parse_requirements_ignores_malformed_or_unidentified_lines() -> None:
    assert (
        parse_requirements(
            "REQ-001 A missing colon.\n- REQ-: An invalid identifier.\n"
            "- A requirement without an identifier."
        )
        == ()
    )
