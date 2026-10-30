from __future__ import annotations

from typing import Mapping

from app.config import ProviderConfigurationError, Settings
from app.models import (
    ClarificationResult,
    ClarificationRound,
    CreatorOutput,
    DecisionProposal,
    MAX_CLARIFICATION_QUESTIONS_PER_ROUND,
    MAX_CLARIFICATION_ROUNDS,
    MAX_MODEL_CALLS_PER_SESSION,
    SkepticOutput,
    Statement,
    SynthesizerOutput,
)
from app.ports.ai_provider import AIProvider


class DiscoveryService:
    def __init__(self, settings: Settings, provider: AIProvider) -> None:
        self._settings = settings
        self._provider = provider

    async def clarify(self, intake: Mapping[str, str]) -> ClarificationResult:
        self._settings.require_provider()
        return await self._provider.clarify(dict(intake))

    @staticmethod
    def confirmed_facts(
        intake: Mapping[str, str],
        answers: Mapping[str, str],
    ) -> list[Statement]:
        facts = [Statement(text=intake["idea"], source="User-provided idea")]
        for field, source in (
            ("audience", "User-provided audience"),
            ("platform", "User-provided platform"),
            ("constraints", "User-provided constraints"),
            ("technology", "User-provided technology preference"),
        ):
            if intake.get(field):
                facts.append(Statement(text=intake[field], source=source))
        for question, answer in answers.items():
            if answer and answer != "Not decided yet.":
                facts.append(
                    Statement(
                        text=f"{question}: {answer}",
                        source="User clarification answer",
                    )
                )
        return facts

    # --- Priority 1: bounded information gain loop and Three Minds roles ---

    async def run_clarification_loop(
        self,
        intake: Mapping[str, str],
        answers_by_round: Mapping[int, Mapping[str, str]],
    ) -> ClarificationRound:
        """Run one bounded clarification round with explicit budget enforcement.

        This enforces MAX_CLARIFICATION_ROUNDS and MAX_MODEL_CALLS_PER_SESSION
        at runtime, not merely as declared constants. It never runs an
        unbounded number of model calls, and it never treats a proposal as
        approved project truth.

        Safe terminal states:
        - budget_exhausted: the model-call budget was already consumed before
          this round could run. No provider call is made.
        - round_limit_reached: the maximum number of rounds was already used.
        - ready_to_draft: enough reliable information exists to prepare the
          next document.
        - unresolved_uncertainty: material uncertainty remains but the budget
          is not yet exhausted, so the caller may supply answers and continue.
        """
        round_number = len(answers_by_round) + 1
        if round_number > MAX_CLARIFICATION_ROUNDS:
            return ClarificationRound(
                round_number=round_number,
                questions=[],
                residual_uncertainty="The clarification round limit was reached.",
                ready_to_draft=False,
            )
        if round_number > MAX_MODEL_CALLS_PER_SESSION:
            return ClarificationRound(
                round_number=round_number,
                questions=[],
                residual_uncertainty="The model-call budget was exhausted.",
                ready_to_draft=False,
            )

        self._settings.require_provider()
        result = await self._provider.clarify(dict(intake))
        # The provider contract returns a ClarificationResult, which is itself
        # Pydantic-validated. Trim defensively so a provider that returns more
        # questions than the loop allows cannot exceed the bound.
        trimmed_questions = result.questions[:MAX_CLARIFICATION_QUESTIONS_PER_ROUND]
        questions = [
            question
            for question in trimmed_questions
            if question.question and question.impact
        ]

        ready_to_draft = round_number >= MAX_CLARIFICATION_ROUNDS or not questions
        residual = (
            "No remaining material uncertainty identified."
            if ready_to_draft
            else f"{len(questions)} material question(s) remain unresolved."
        )
        return ClarificationRound(
            round_number=round_number,
            questions=questions,
            residual_uncertainty=residual,
            ready_to_draft=ready_to_draft,
        )

    async def creator(self, intake: Mapping[str, str]) -> CreatorOutput:
        """Creator role: generate options and open questions.

        Output is always a proposal. It is never written to project truth.
        """
        payload = self._role_payload(intake, "creator")
        return await self._complete_role(payload, CreatorOutput)

    async def skeptic(self, intake: Mapping[str, str]) -> SkepticOutput:
        """Skeptic role: identify weaknesses and unsupported assumptions.

        Output is critique, never a verdict, and never modifies stored
        decisions.
        """
        payload = self._role_payload(intake, "skeptic")
        return await self._complete_role(payload, SkepticOutput)

    async def synthesizer(self, intake: Mapping[str, str]) -> SynthesizerOutput:
        """Synthesizer role: combine intent and critique into recommendations.

        Every recommendation is a proposal awaiting explicit, authorized
        approval before it is treated as approved project truth.
        """
        payload = self._role_payload(intake, "synthesizer")
        return await self._complete_role(payload, SynthesizerOutput)

    def propose_decision(
        self,
        statement: str,
        rationale: str,
        alternatives: Mapping[str, str] | None = None,
        confidence: float = 0.0,
    ) -> DecisionProposal:
        """Build a decision proposal.

        This only constructs the proposal object. It does not persist it,
        and it can never change an existing decision's state. Persistence and
        any state transition require a separate, authorized path.
        """
        return DecisionProposal(
            statement=statement,
            rationale=rationale,
            alternatives=[
                Statement(text=text, source=source)
                for text, source in (alternatives or {}).items()
            ],
            confidence=confidence,
        )

    def _role_payload(self, intake: Mapping[str, str], role: str) -> Mapping[str, str]:
        return {
            "role": role,
            "idea": intake.get("idea", ""),
            "audience": intake.get("audience", ""),
            "constraints": intake.get("constraints", ""),
            "technology": intake.get("technology", ""),
        }

    async def _complete_role(
        self,
        payload: Mapping[str, str],
        model_type: type,
    ):
        """Call the provider's role method if available, else fail safely.

        The provider interface is extended only when a provider actually
        implements a role. A provider that does not implement a role makes the
        method unavailable rather than fabricating an answer, so malformed or
        missing output is never silently treated as truth.
        """
        self._settings.require_provider()
        method = getattr(self._provider, payload["role"], None)
        if method is None or not callable(method):
            raise ProviderConfigurationError(
                f"The configured AI provider does not support the "
                f"{payload['role']} reasoning role."
            )
        result = await method(dict(payload))
        if not isinstance(result, model_type):
            raise ProviderConfigurationError(
                f"The AI provider returned an invalid {model_type.__name__}."
            )
        return result
