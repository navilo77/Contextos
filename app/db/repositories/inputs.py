from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True, slots=True)
class RevisionInput:
    language: str
    profile: str
    intake_snapshot: dict[str, Any]
    schema_version: str
    template_pack_version: str


@dataclass(frozen=True, slots=True)
class SourceInput:
    source_kind: str
    content: str
    source_role: str
    safe_label: str | None = None
