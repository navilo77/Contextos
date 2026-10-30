from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, StringConstraints
from typing_extensions import Annotated

SafeText = Annotated[str, StringConstraints(min_length=1, max_length=8000)]


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class FollowUpQuestion(StrictModel):
    question: Annotated[str, StringConstraints(min_length=1, max_length=500)]
    impact: Annotated[str, StringConstraints(min_length=1, max_length=500)]
    blocking: bool


class ClarificationResult(StrictModel):
    questions: list[FollowUpQuestion] = Field(default_factory=list, max_length=6)


class GeneratedQuestion(StrictModel):
    question: SafeText
    impact: SafeText
    blocking: bool


class Statement(StrictModel):
    text: SafeText
    source: Annotated[str, StringConstraints(min_length=1, max_length=300)]


class ProjectIdentity(StrictModel):
    name: Annotated[str, StringConstraints(min_length=1, max_length=120)]
    slug: Annotated[
        str, StringConstraints(min_length=1, max_length=64, pattern=r"^[a-z0-9]+(?:-[a-z0-9]+)*$")
    ]
    purpose: SafeText


class ProjectContext(StrictModel):
    schema_version: Literal["1.0"] = "1.0"
    project: ProjectIdentity
    language: Annotated[str, StringConstraints(min_length=2, max_length=32)]
    profile: Literal["compact", "detailed"]
    facts: list[Statement] = Field(default_factory=list)
    accepted_proposals: list[Statement] = Field(default_factory=list)
    assumptions: list[Statement] = Field(default_factory=list)
    open_questions: list[GeneratedQuestion] = Field(default_factory=list)
    constraints: list[Statement] = Field(default_factory=list)
    exclusions: list[Statement] = Field(default_factory=list)
    documents: list[dict[str, str]] = Field(default_factory=list)


class GeneratedDocuments(StrictModel):
    project_name: Annotated[str, StringConstraints(min_length=1, max_length=120)]
    project_slug: Annotated[
        str, StringConstraints(min_length=1, max_length=64, pattern=r"^[a-z0-9]+(?:-[a-z0-9]+)*$")
    ]
    purpose: SafeText
    intended_users: list[SafeText] = Field(default_factory=list, max_length=20)
    facts: list[Statement] = Field(default_factory=list, max_length=50)
    accepted_proposals: list[Statement] = Field(default_factory=list, max_length=30)
    assumptions: list[Statement] = Field(default_factory=list, max_length=30)
    open_questions: list[GeneratedQuestion] = Field(default_factory=list, max_length=30)
    constraints: list[Statement] = Field(default_factory=list, max_length=30)
    exclusions: list[Statement] = Field(default_factory=list, max_length=30)
    project_brief: SafeText
    requirements: SafeText
    implementation_plan: SafeText
    architecture: str = ""
    data_model: str = ""
    api_contract: str = ""
    security: str = ""
    test_plan: str = ""


# --- Information Gain Loop and Three Minds contracts (Foundation) ---
# These are typed, validated output contracts. They are proposals only: nothing
# here is project truth until an explicit, authorized approval path promotes it.

MAX_CLARIFICATION_ROUNDS = 3
MAX_CLARIFICATION_QUESTIONS_PER_ROUND = 6
MAX_MODEL_CALLS_PER_SESSION = 12


class ClarificationRound(StrictModel):
    """One bounded round of the information gain loop.

    A round is a single model call that returns a small, prioritized set of
    questions. The loop is bounded by MAX_CLARIFICATION_ROUNDS and
    MAX_MODEL_CALLS_PER_SESSION; it never runs unconstrained.
    """

    round_number: Annotated[int, StringConstraints(strict=False)] = Field(
        ge=1, le=MAX_CLARIFICATION_ROUNDS
    )
    questions: list[FollowUpQuestion] = Field(
        default_factory=list, max_length=MAX_CLARIFICATION_QUESTIONS_PER_ROUND
    )
    residual_uncertainty: Annotated[
        str, StringConstraints(min_length=1, max_length=500)
    ] = Field(
        default="No remaining material uncertainty identified.",
        description="What is still unknown after this round, in the user's language.",
    )
    ready_to_draft: bool = Field(
        default=False,
        description="True only when enough reliable information exists to prepare the next document.",
    )


class CreatorOutput(StrictModel):
    """Creator role: generate ideas, options, and possible solutions.

    Output is always a proposal. It never writes project truth.
    """

    options: list[Statement] = Field(default_factory=list, max_length=10)
    open_questions: list[GeneratedQuestion] = Field(default_factory=list, max_length=6)
    rationale: Annotated[str, StringConstraints(min_length=1, max_length=500)]


class SkepticOutput(StrictModel):
    """Skeptic role: identify weaknesses, risks, and unsupported assumptions.

    Findings are critique, not verdicts. They never modify stored decisions.
    """

    findings: list[Statement] = Field(default_factory=list, max_length=10)
    unsupported_claims: list[Statement] = Field(default_factory=list, max_length=10)
    risks: list[Statement] = Field(default_factory=list, max_length=10)


class SynthesizerOutput(StrictModel):
    """Synthesizer role: combine intent, evidence, and critique into recommendations.

    Every recommendation is a *proposal*. It must pass an explicit, authorized
    approval path before it is treated as approved project truth.
    """

    recommendations: list[Statement] = Field(default_factory=list, max_length=10)
    recommended_decision: Annotated[
        str, StringConstraints(min_length=1, max_length=500)
    ] = Field(
        description="The single recommended course of action, stated as a proposal.",
    )
    trade_offs: list[Statement] = Field(default_factory=list, max_length=10)
    unresolved_questions: list[GeneratedQuestion] = Field(default_factory=list, max_length=6)


class DecisionProposal(StrictModel):
    """A proposed decision, distinct from approved project truth.

    status is always 'proposed' when created by this contract. Only an
    explicit, authorized approval action may change it.
    """

    statement: SafeText
    rationale: Annotated[str, StringConstraints(min_length=1, max_length=2_000)]
    status: Literal["proposed"] = "proposed"
    alternatives: list[Statement] = Field(default_factory=list, max_length=5)
    confidence: Annotated[float, StringConstraints(strict=False)] = Field(
        default=0.0, ge=0.0, le=1.0
    )
