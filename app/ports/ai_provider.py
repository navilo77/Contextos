from __future__ import annotations

from typing import Mapping, Protocol

from app.models import ClarificationResult, GeneratedDocuments


class AIProvider(Protocol):
    async def clarify(self, intake: Mapping[str, str]) -> ClarificationResult: ...

    async def generate(
        self,
        intake: Mapping[str, str],
        answers: Mapping[str, str],
    ) -> GeneratedDocuments: ...
