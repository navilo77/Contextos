from __future__ import annotations

import hashlib
import io
import json
import re
import zipfile
from datetime import datetime, timezone
from pathlib import PurePosixPath
from typing import Any, Literal

import jsonschema

from app.models import GeneratedDocuments, ProjectContext, ProjectIdentity

PackageProfile = Literal["compact", "detailed"]

MARKER_PATTERN = re.compile(
    r"\{\{[^{}]+\}\}|\[(?:TODO|TBD|PLACEHOLDER)\]|^\s*(?:TODO|TBD)\s*:",
    re.MULTILINE,
)
SECRET_PATTERNS = (
    re.compile(r"(?i)\bsk-[A-Za-z0-9_-]{20,}\b"),
    re.compile(r"(?i)\bBearer\s+[A-Za-z0-9._~+/=-]{16,}"),
    re.compile(r"-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----"),
    re.compile(r"(?i)\b(?:api[_-]?key|password|secret)\s*[:=]\s*['\"][^'\"]{8,}['\"]"),
)
LINK_PATTERN = re.compile(r"\[[^\]]*\]\(([^)]+)\)")
REQUIRED_PATHS = {
    "compact": {
        "README.md",
        "AGENTS.md",
        "context/project-context.json",
        "context/OPEN_QUESTIONS.md",
        "00-project/PROJECT_BRIEF.md",
        "01-product/REQUIREMENTS.md",
        "01-product/IMPLEMENTATION_PLAN.md",
        "manifest.json",
    },
    "detailed": {
        "README.md",
        "AGENTS.md",
        "context/project-context.json",
        "context/OPEN_QUESTIONS.md",
        "00-project/PROJECT_BRIEF.md",
        "01-product/REQUIREMENTS.md",
        "01-product/IMPLEMENTATION_PLAN.md",
        "02-technical/ARCHITECTURE.md",
        "02-technical/SECURITY.md",
        "03-quality/TEST_PLAN.md",
        "manifest.json",
    },
}


class PackageValidationError(ValueError):
    def __init__(self, errors: list[str]) -> None:
        self.errors = errors
        super().__init__("; ".join(errors))


def build_package(
    generated: GeneratedDocuments,
    *,
    profile: str,
    language: str,
    schema: dict[str, Any],
    configured_secrets: tuple[str, ...] = (),
) -> tuple[dict[str, bytes], bytes, list[str]]:
    profile = parse_package_profile(profile)
    context, documents, omitted = _make_documents(generated, profile, language)
    context_bytes = json.dumps(
        context.model_dump(mode="json"), ensure_ascii=False, indent=2
    ).encode("utf-8")
    documents["context/project-context.json"] = context_bytes
    documents["README.md"] = b""
    documents["AGENTS.md"] = _markdown(
        "# Coding Agent Instructions\n\n"
        "This folder contains project context, not a complete application. Read the project brief "
        "and requirements before implementation. Preserve confirmed constraints; keep proposals, "
        "assumptions, and open questions distinct. Implement in small, verifiable steps, add relevant "
        "tests, and report the exact checks run. Ask before irreversible or security-sensitive actions. "
        "Do not claim completion if checks fail or were not run. Follow all higher-priority instructions.\n"
    )
    links = "\n".join(f"- [{path}]({path})" for path in sorted(documents))
    documents["README.md"] = _markdown(
        f"# {generated.project_name}\n\n"
        f"{generated.purpose}\n\n"
        f"## Intended users\n\n{_bullets(generated.intended_users)}\n\n"
        "## First-release goal\n\nSee [project brief](00-project/PROJECT_BRIEF.md) and "
        "[requirements](01-product/REQUIREMENTS.md).\n\n"
        "## Use with a coding agent\n\nOpen this folder as project context. Read `AGENTS.md`, "
        "then the project brief, requirements, and implementation plan before changing code. "
        "This ZIP is a specification package, not application code.\n\n"
        "## Package files\n\n" + links + "\n- [manifest.json](manifest.json)\n"
    )
    docs_list = [
        {"path": path, "reason": "Included in this generated project-context package."}
        for path in sorted(documents)
        if path != "manifest.json"
    ]
    context = context.model_copy(update={"documents": docs_list})
    documents["context/project-context.json"] = json.dumps(
        context.model_dump(mode="json"), ensure_ascii=False, indent=2
    ).encode("utf-8")

    errors = validate_package(
        documents,
        profile=profile,
        schema=schema,
        secrets=configured_secrets,
        check_manifest=False,
    )
    if errors:
        raise PackageValidationError(errors)

    manifest = {
        "format_version": "1.0",
        "generator": {"name": "Context OS", "version": "0.1.0"},
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "project_slug": generated.project_slug,
        "profile": profile,
        "language": language,
        "files": [
            {"path": path, "sha256": hashlib.sha256(content).hexdigest()}
            for path, content in sorted(documents.items())
        ],
        "omitted_topics": [{"topic": topic, "reason": reason} for topic, reason in omitted],
        "validation": {
            "checks": [
                "required_files",
                "project_context_schema",
                "safe_paths",
                "internal_links",
                "template_markers",
                "credential_patterns",
                "manifest_hashes",
                "zip_reopen",
            ],
            "passed": True,
            "secret_scan_limit": "Pattern checks are not exhaustive; inspect this ZIP before use.",
        },
    }
    documents["manifest.json"] = json.dumps(manifest, ensure_ascii=False, indent=2).encode("utf-8")
    errors = validate_package(documents, profile=profile, schema=schema, secrets=configured_secrets)
    if errors:
        raise PackageValidationError(errors)
    archive = _zip_package(generated.project_slug, documents)
    _verify_archive(archive, generated.project_slug, documents)
    return documents, archive, []


def parse_package_profile(profile: str) -> PackageProfile:
    if profile == "compact":
        return "compact"
    if profile == "detailed":
        return "detailed"
    raise PackageValidationError(["Unknown package profile"])


def build_verified_archive(slug: str, documents: dict[str, bytes]) -> bytes:
    if not re.fullmatch(r"[a-z0-9]+(?:-[a-z0-9]+)*", slug):
        raise PackageValidationError(["Project slug is not safe for ZIP packaging"])
    archive = _zip_package(slug, documents)
    _verify_archive(archive, slug, documents)
    return archive


def validate_package(
    documents: dict[str, bytes],
    *,
    profile: str,
    schema: dict[str, Any],
    secrets: tuple[str, ...] = (),
    check_manifest: bool = True,
) -> list[str]:
    errors: list[str] = []
    for path in REQUIRED_PATHS[profile]:
        if path == "manifest.json" and not check_manifest:
            continue
        if path not in documents or not documents[path].strip():
            errors.append(f"Required file missing or empty: {path}")
    seen: set[str] = set()
    for path, content in documents.items():
        pure = PurePosixPath(path)
        if pure.is_absolute() or ".." in pure.parts or "\\" in path or ":" in path or path in seen:
            errors.append(f"Unsafe or duplicate package path: {path}")
        seen.add(path)
        try:
            text = content.decode("utf-8")
        except UnicodeDecodeError:
            errors.append(f"Package file is not UTF-8 text: {path}")
            continue
        if MARKER_PATTERN.search(text):
            errors.append(f"Unresolved template marker found: {path}")
        if any(pattern.search(text) for pattern in SECRET_PATTERNS) or any(
            secret and secret in text for secret in secrets
        ):
            errors.append(f"Possible credential found: {path}")
        for target in LINK_PATTERN.findall(text):
            if "://" in target or target.startswith(("mailto:", "#")):
                continue
            normalized_target = target.split("#", 1)[0]
            if (
                normalized_target
                and normalized_target not in documents
                and not (not check_manifest and normalized_target == "manifest.json")
            ):
                errors.append(f"Broken internal link in {path}: {target}")
    if "context/project-context.json" in documents:
        try:
            context = json.loads(documents["context/project-context.json"])
            jsonschema.validate(context, schema)
        except (json.JSONDecodeError, jsonschema.ValidationError, jsonschema.SchemaError):
            errors.append("Project context does not validate against the JSON Schema")
    if check_manifest and "manifest.json" in documents:
        try:
            manifest = json.loads(documents["manifest.json"])
            listed_files = manifest["files"]
            entries = {item["path"]: item["sha256"] for item in listed_files}
            if len(entries) != len(listed_files):
                errors.append("Manifest contains duplicate file paths")
            if set(entries) != set(documents) - {"manifest.json"}:
                errors.append("Manifest file list does not match generated package files")
            for path, digest in entries.items():
                pure = PurePosixPath(path)
                if pure.is_absolute() or ".." in pure.parts or "\\" in path or ":" in path:
                    errors.append(f"Unsafe manifest file path: {path}")
                    continue
                if path not in documents or hashlib.sha256(documents[path]).hexdigest() != digest:
                    errors.append(f"Manifest hash mismatch: {path}")
        except (json.JSONDecodeError, KeyError, TypeError):
            errors.append("Manifest is malformed")
    return errors


def _make_documents(
    generated: GeneratedDocuments, profile: PackageProfile, language: str
) -> tuple[ProjectContext, dict[str, bytes], list[tuple[str, str]]]:
    documents: dict[str, bytes] = {}
    omitted: list[tuple[str, str]] = []
    question_lines = [
        f"- **{item.question}** — {item.impact} (blocking: {'yes' if item.blocking else 'no'})"
        for item in generated.open_questions
    ]
    documents["context/OPEN_QUESTIONS.md"] = _markdown(
        "# Open Questions\n\n"
        + ("\n".join(question_lines) if question_lines else "No open questions.")
    )
    documents["00-project/PROJECT_BRIEF.md"] = _markdown(
        f"# {generated.project_name} — Project Brief\n\n"
        f"## Purpose\n\n{generated.purpose}\n\n"
        f"## Intended users\n\n{_bullets(generated.intended_users)}\n\n"
        f"## Project brief\n\n{generated.project_brief}\n\n"
        f"## Constraints\n\n{_statements(generated.constraints)}\n\n"
        f"## Exclusions\n\n{_statements(generated.exclusions)}\n\n"
        f"## Assumptions\n\n{_statements(generated.assumptions)}\n\n"
        f"## Accepted proposals\n\n{_statements(generated.accepted_proposals)}\n"
    )
    documents["01-product/REQUIREMENTS.md"] = _markdown(
        f"# Requirements\n\n{generated.requirements}"
    )
    documents["01-product/IMPLEMENTATION_PLAN.md"] = _markdown(
        f"# Implementation Plan\n\n{generated.implementation_plan}"
    )

    technical = {
        "architecture": ("02-technical/ARCHITECTURE.md", generated.architecture),
        "data_model": ("02-technical/DATA_MODEL.md", generated.data_model),
        "api_contract": ("02-technical/API_CONTRACT.md", generated.api_contract),
        "security": ("02-technical/SECURITY.md", generated.security),
        "test_plan": ("03-quality/TEST_PLAN.md", generated.test_plan),
    }
    for topic, (path, content) in technical.items():
        include = bool(content.strip())
        if topic in ("architecture", "security", "test_plan") and profile == "detailed":
            include = True
        if include:
            default_content = {
                "architecture": "Technical choices are undecided unless explicitly stated in this document.",
                "security": "Identify sensitive data, access boundaries, and approval needs during implementation. No project-specific security facts were provided.",
                "test_plan": "Derive automated tests from the acceptance criteria. No repository-specific test command has been confirmed.",
            }.get(topic, "")
            documents[path] = _markdown(
                f"# {topic.replace('_', ' ').title()}\n\n{content.strip() or default_content}"
            )
        else:
            omitted.append((topic, "Not provided or not relevant to the confirmed idea/profile."))

    fact_statements = list(generated.facts)
    context = ProjectContext(
        project=ProjectIdentity(
            name=generated.project_name,
            slug=generated.project_slug,
            purpose=generated.purpose,
        ),
        language=language,
        profile=profile,
        facts=fact_statements,
        accepted_proposals=generated.accepted_proposals,
        assumptions=generated.assumptions,
        open_questions=generated.open_questions,
        constraints=generated.constraints,
        exclusions=generated.exclusions,
        documents=[
            {"path": path, "reason": "Included in this generated package."} for path in documents
        ],
    )
    return context, documents, omitted


def _zip_package(slug: str, documents: dict[str, bytes]) -> bytes:
    output = io.BytesIO()
    with zipfile.ZipFile(output, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        for path, content in sorted(documents.items()):
            archive.writestr(f"{slug}/{path}", content)
    return output.getvalue()


def _verify_archive(archive_bytes: bytes, slug: str, documents: dict[str, bytes]) -> None:
    try:
        with zipfile.ZipFile(io.BytesIO(archive_bytes)) as archive:
            expected = {f"{slug}/{path}" for path in documents}
            actual = set(archive.namelist())
            if actual != expected:
                raise PackageValidationError(["ZIP entries do not match generated package files"])
            bad_file = archive.testzip()
            if bad_file:
                raise PackageValidationError([f"ZIP integrity check failed: {bad_file}"])
    except zipfile.BadZipFile as exc:
        raise PackageValidationError(["Generated ZIP could not be reopened"]) from exc


def _markdown(text: str) -> bytes:
    return (text.rstrip() + "\n").encode("utf-8")


def _bullets(items: list[str]) -> str:
    return "\n".join(f"- {item}" for item in items) if items else "Not specified."


def _statements(items: list[Any]) -> str:
    return (
        "\n".join(f"- {item.text} _(source: {item.source})_" for item in items)
        if items
        else "None specified."
    )
