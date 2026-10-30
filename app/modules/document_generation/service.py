from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping

from app.config import Settings
from app.models import GeneratedDocuments
from app.modules.discovery.service import DiscoveryService
from app.ports.ai_provider import AIProvider
from app.services.package_builder import (
    build_package,
    parse_package_profile,
    validate_package,
)


@dataclass(frozen=True, slots=True)
class GeneratedPackage:
    documents: GeneratedDocuments
    files: dict[str, bytes]
    archive: bytes


class DocumentGenerationService:
    def __init__(
        self,
        settings: Settings,
        provider: AIProvider,
        schema: dict[str, Any],
    ) -> None:
        self._settings = settings
        self._provider = provider
        self._schema = schema

    async def generate_package(
        self,
        intake: Mapping[str, str],
        answers: Mapping[str, str],
    ) -> GeneratedPackage:
        self._settings.require_provider()
        generated = await self._provider.generate(dict(intake), dict(answers))
        generated = generated.model_copy(
            update={
                "facts": DiscoveryService.confirmed_facts(intake, answers),
                "accepted_proposals": [],
            }
        )
        language = intake["language"]
        if language.lower() == "auto":
            language = "Follow the language of the idea."
        profile = parse_package_profile(intake["profile"])
        files, archive, _ = build_package(
            generated,
            profile=profile,
            language=language,
            schema=self._schema,
            configured_secrets=(self._settings.gemini_api_key,),
        )
        return GeneratedPackage(
            documents=generated,
            files=files,
            archive=archive,
        )

    def validate_package_files(self, files: dict[str, bytes], profile: str) -> list[str]:
        return validate_package(
            files,
            profile=parse_package_profile(profile),
            schema=self._schema,
            secrets=(self._settings.gemini_api_key,),
        )
