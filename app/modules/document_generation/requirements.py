from __future__ import annotations

import re
from dataclasses import dataclass, field

_REQUIREMENT_LINE = re.compile(
    r"^\s*(?:#{1,6}\s*)?[-*]?\s*(REQ-[A-Z0-9][A-Z0-9._-]{0,27})\s*:\s*(\S.*?)\s*$",
    re.IGNORECASE,
)
_LIST_ITEM = re.compile(r"^\s*(?:[-*]\s+|\d+[.)]\s+)(\S.*?)\s*$")


@dataclass(frozen=True, slots=True)
class RequirementDraft:
    key: str
    statement: str
    acceptance_criteria: tuple[str, ...] = ()


@dataclass(slots=True)
class _MutableRequirement:
    key: str
    statement: str
    acceptance_criteria: list[str] = field(default_factory=list)


def parse_requirements(markdown: str) -> tuple[RequirementDraft, ...]:
    requirements: list[_MutableRequirement] = []
    by_key: dict[str, _MutableRequirement] = {}
    current: _MutableRequirement | None = None
    in_acceptance_criteria = False

    for line in markdown.splitlines():
        match = _REQUIREMENT_LINE.match(line)
        if match:
            key = match.group(1).upper()
            normalized_key = key.casefold()
            if normalized_key in by_key:
                raise ValueError(f"Duplicate requirement identifier: {key}")
            current = _MutableRequirement(key=key, statement=match.group(2).strip())
            requirements.append(current)
            by_key[normalized_key] = current
            in_acceptance_criteria = False
            continue

        heading = re.match(r"^\s*#{1,6}\s+(.+?)\s*#*\s*$", line)
        if heading:
            in_acceptance_criteria = "acceptance criteria" in heading.group(1).casefold()
            continue

        if in_acceptance_criteria and current is not None:
            criterion = _LIST_ITEM.match(line)
            if criterion:
                current.acceptance_criteria.append(criterion.group(1).strip())

    return tuple(
        RequirementDraft(
            key=requirement.key,
            statement=requirement.statement,
            acceptance_criteria=tuple(requirement.acceptance_criteria),
        )
        for requirement in requirements
    )
