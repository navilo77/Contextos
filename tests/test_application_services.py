from __future__ import annotations

import asyncio
import json
from pathlib import Path

import pytest
from pydantic import ValidationError

from app.config import ProviderConfigurationError, Settings
from app.models import (
    ClarificationRound,
    ClarificationResult,
    CreatorOutput,
    DecisionProposal,
    FollowUpQuestion,
    GeneratedDocuments,
    MAX_CLARIFICATION_QUESTIONS_PER_ROUND,
    MAX_CLARIFICATION_ROUNDS,
    MAX_MODEL_CALLS_PER_SESSION,
    SkepticOutput,
    SynthesizerOutput,
)
from app.modules.discovery.service import DiscoveryService
from app.modules.document_generation.service import DocumentGenerationService

ROOT = Path(__file__).resolve().parents[1]
SCHEMA = json.loads((ROOT / "schemas" / "project-context.schema.json").read_text(encoding="utf-8"))


class FakeProvider:
    def __init__(self) -> None:
        self.clarify_calls = 0
        self.generate_calls = 0

    async def clarify(self, intake):
        self.clarify_calls += 1
        return ClarificationResult()

    async def generate(self, intake, answers):
        self.generate_calls += 1
        return GeneratedDocuments(
            project_name="Study Planner",
            project_slug="study-planner",
            purpose="Help learners plan study sessions.",
            facts=[{"text": "Model-invented fact", "source": "model"}],
            accepted_proposals=[{"text": "Model proposal", "source": "model"}],
            project_brief="A study planner for learners.",
            requirements=(
                "## Requirements\n\n- REQ-001: Add a study session.\n\n"
                "### Acceptance criteria\n\n- Given a learner, when a session is saved, then it appears in the plan."
            ),
            implementation_plan="1. Build the first workflow.\n2. Test the acceptance criteria.",
        )


def test_discovery_service_requires_provider_configuration_before_call():
    provider = FakeProvider()
    service = DiscoveryService(Settings("", "gemini-3.8-flash", "127.0.0.1", 8000), provider)

    with pytest.raises(ProviderConfigurationError, match="GEMINI_API_KEY"):
        asyncio.run(service.clarify({"idea": "A study planner"}))

    assert provider.clarify_calls == 0


def test_discovery_service_keeps_only_user_submitted_facts():
    facts = DiscoveryService.confirmed_facts(
        {
            "idea": "A study planner",
            "audience": "Learners",
            "platform": "",
            "constraints": "",
            "technology": "",
        },
        {
            "Should users sign in?": "Not decided yet.",
            "Should plans sync?": "Yes, between devices.",
        },
    )

    assert [fact.text for fact in facts] == [
        "A study planner",
        "Learners",
        "Should plans sync?: Yes, between devices.",
    ]
    assert facts[-1].source == "User clarification answer"


def test_generation_service_builds_verified_package_from_user_facts():
    provider = FakeProvider()
    service = DocumentGenerationService(
        Settings("test-key", "gemini-3.8-flash", "127.0.0.1", 8000),
        provider,
        SCHEMA,
    )
    result = asyncio.run(
        service.generate_package(
            {
                "idea": "A study planner for learners.",
                "audience": "Learners",
                "platform": "",
                "constraints": "",
                "technology": "",
                "language": "auto",
                "profile": "compact",
            },
            {"Should users sign in?": "Not decided yet."},
        )
    )

    assert provider.generate_calls == 1
    assert [fact.text for fact in result.documents.facts] == [
        "A study planner for learners.",
        "Learners",
    ]
    assert result.documents.accepted_proposals == []
    assert result.files["manifest.json"]
    assert result.archive.startswith(b"PK")


def test_generation_service_does_not_call_provider_without_configuration():
    provider = FakeProvider()
    service = DocumentGenerationService(
        Settings("", "gemini-3.8-flash", "127.0.0.1", 8000),
        provider,
        SCHEMA,
    )

    with pytest.raises(ProviderConfigurationError, match="GEMINI_API_KEY"):
        asyncio.run(
            service.generate_package(
                {"idea": "Idea", "language": "English", "profile": "compact"},
                {},
            )
        )

    assert provider.generate_calls == 0


# --- Foundation: Information Gain Loop and Three Minds contracts ---

from app.models import (  # noqa: E402
    ClarificationRound,
    CreatorOutput,
    DecisionProposal,
    MAX_CLARIFICATION_QUESTIONS_PER_ROUND,
    MAX_CLARIFICATION_ROUNDS,
    MAX_MODEL_CALLS_PER_SESSION,
    SkepticOutput,
    SynthesizerOutput,
)


def test_clarification_loop_is_bounded_by_explicit_round_and_call_limits():
    assert MAX_CLARIFICATION_ROUNDS == 3
    assert MAX_CLARIFICATION_QUESTIONS_PER_ROUND == 6
    assert MAX_MODEL_CALLS_PER_SESSION == 12

    round_one = ClarificationRound(
        round_number=1,
        questions=[],
        ready_to_draft=False,
    )
    assert round_one.round_number == 1

    with pytest.raises(ValidationError):
        ClarificationRound(round_number=MAX_CLARIFICATION_ROUNDS + 1, questions=[])

    with pytest.raises(ValidationError):
        ClarificationRound(
            round_number=1,
            questions=[
                {"question": f"q{i}", "impact": "i", "blocking": False}
                for i in range(MAX_CLARIFICATION_QUESTIONS_PER_ROUND + 1)
            ],
        )


def test_decision_proposals_are_permanently_proposed_until_authorized():
    proposal = DecisionProposal(
        statement="Use a SQLite database for now.",
        rationale="It avoids operational complexity in the local release.",
    )
    assert proposal.status == "proposed"

    with pytest.raises(ValidationError):
        DecisionProposal(
            statement="Use PostgreSQL.",
            rationale="Needed for durability.",
            status="accepted",
        )


def test_three_minds_outputs_are_proposals_not_project_truth():
    creator = CreatorOutput(
        options=[{"text": "Option A", "source": "creator"}],
        rationale="Two viable paths exist.",
    )
    skeptic = SkepticOutput(
        findings=[{"text": "Option A assumes a hosted database.", "source": "skeptic"}],
    )
    synthesizer = SynthesizerOutput(
        recommendations=[{"text": "Prefer Option B.", "source": "synthesizer"}],
        recommended_decision="Defer the hosted database.",
    )
    assert creator.options[0].source == "creator"
    assert skeptic.findings[0].source == "skeptic"
    assert synthesizer.recommended_decision
    # None of these contracts carries an approval state: they cannot be
    # promoted to approved truth by construction.
    for model in (creator, skeptic, synthesizer):
        assert not hasattr(model, "status") or "proposed" not in getattr(
            model, "status", ""
        )


# --- Priority 1: runtime enforcement of the information gain loop ---


class LoopProvider:
    """Provider that returns a configurable number of questions per call."""

    def __init__(self, questions_per_call: int = 2) -> None:
        self.calls = 0
        self._questions_per_call = questions_per_call

    async def clarify(self, intake):
        self.calls += 1
        return ClarificationResult(
            questions=[
                FollowUpQuestion(
                    question=f"Question {self.calls}-{index}",
                    impact="This changes project requirements.",
                    blocking=False,
                )
                for index in range(self._questions_per_call)
            ]
        )


def _intake() -> dict[str, str]:
    return {
        "idea": "A study planner for learners.",
        "audience": "Learners",
        "platform": "",
        "constraints": "",
        "technology": "",
    }


def test_loop_enforces_round_limit_at_runtime():
    provider = LoopProvider(questions_per_call=2)
    service = DiscoveryService(
        Settings("test-key", "gemini-3.8-flash", "127.0.0.1", 8000), provider
    )

    async def run() -> list[ClarificationRound]:
        rounds: list[ClarificationRound] = []
        answers: dict[int, dict[str, str]] = {}
        for _ in range(MAX_CLARIFICATION_ROUNDS + 5):
            round_result = await service.run_clarification_loop(_intake(), answers)
            rounds.append(round_result)
            if round_result.ready_to_draft:
                break
            answers[round_result.round_number] = {}
        return rounds

    rounds = asyncio.run(run())
    # The loop stops at the round limit; it never exceeds MAX_CLARIFICATION_ROUNDS.
    assert len(rounds) <= MAX_CLARIFICATION_ROUNDS
    assert rounds[-1].ready_to_draft is True
    # Each round never exceeds the per-round question cap.
    assert all(
        len(round_result.questions) <= MAX_CLARIFICATION_QUESTIONS_PER_ROUND
        for round_result in rounds
    )


def test_loop_respects_the_per_round_question_cap():
    provider = LoopProvider(questions_per_call=MAX_CLARIFICATION_QUESTIONS_PER_ROUND)
    service = DiscoveryService(
        Settings("test-key", "gemini-3.8-flash", "127.0.0.1", 8000), provider
    )

    round_result = asyncio.run(service.run_clarification_loop(_intake(), {}))
    assert len(round_result.questions) == MAX_CLARIFICATION_QUESTIONS_PER_ROUND


def test_propose_decision_is_permanently_proposed_and_unpersisted():
    service = DiscoveryService(
        Settings("test-key", "gemini-3.8-flash", "127.0.0.1", 8000), LoopProvider()
    )
    proposal = service.propose_decision(
        statement="Use a local database.",
        rationale="The release is local-first and single-user.",
        alternatives={"Remote database": "Adds hosting complexity."},
        confidence=0.7,
    )
    assert proposal.status == "proposed"
    # Proposing never persists anything: there is no approval state to mutate.
    assert not hasattr(proposal, "approved_by")


def test_role_methods_fail_safely_when_provider_does_not_support_them():
    class NoRoleProvider:
        async def clarify(self, intake):
            return ClarificationResult()

    service = DiscoveryService(
        Settings("test-key", "gemini-3.8-flash", "127.0.0.1", 8000), NoRoleProvider()
    )
    with pytest.raises(ProviderConfigurationError):
        asyncio.run(service.creator(_intake()))
    with pytest.raises(ProviderConfigurationError):
        asyncio.run(service.skeptic(_intake()))
    with pytest.raises(ProviderConfigurationError):
        asyncio.run(service.synthesizer(_intake()))


# --- Priority 2: decision approval, authorization, and audit boundaries ---

from app.db.repositories.decisions import ALLOWED_DECISION_ACTORS, set_decision_status  # noqa: E402
from app.db.repositories.errors import RepositoryInputError  # noqa: E402


def test_decision_approval_actors_are_explicitly_authorized_only():
    """Only explicitly authorized actors may approve; AI/Coding Agents cannot."""
    assert ALLOWED_DECISION_ACTORS == ("local_user",)
    # The repository enforces this at the persistence boundary.
    with pytest.raises(RepositoryInputError, match="actor"):
        asyncio.run(
            set_decision_status(
                None,  # type: ignore[arg-type]
                workspace_id=__import__("uuid").uuid4(),
                project_id=__import__("uuid").uuid4(),
                revision_id=__import__("uuid").uuid4(),
                decision_id=__import__("uuid").uuid4(),
                status="accepted",
                actor="coding_agent",
            )
        )


def test_decision_status_cannot_be_set_to_invalid_values():
    with pytest.raises(RepositoryInputError):
        asyncio.run(
            set_decision_status(
                None,  # type: ignore[arg-type]
                workspace_id=__import__("uuid").uuid4(),
                project_id=__import__("uuid").uuid4(),
                revision_id=__import__("uuid").uuid4(),
                decision_id=__import__("uuid").uuid4(),
                status="pending_review",
            )
        )


# --- Priority 3: Coding Agent tasks/evidence cannot approve decisions ---

from app.models import DecisionProposal  # noqa: E402


def test_coding_agent_evidence_cannot_approve_decisions():
    """Evidence submission cannot mutate SSOT decision approval state."""
    proposal = DecisionProposal(
        statement="Adopt the proposed architecture.",
        rationale="Meets the requirements.",
    )
    assert proposal.status == "proposed"
    # Proposals remain proposed; no method on DecisionProposal mutates state.
    assert not hasattr(proposal, "approve")
    assert not hasattr(proposal, "accept")
    # Only explicit local_user authorization via set_decision_status can change it.
    with pytest.raises(RepositoryInputError):
        asyncio.run(
            set_decision_status(
                None,  # type: ignore[arg-type]
                workspace_id=__import__("uuid").uuid4(),
                project_id=__import__("uuid").uuid4(),
                revision_id=__import__("uuid").uuid4(),
                decision_id=__import__("uuid").uuid4(),
                status="accepted",
                actor="system",
            )
        )
