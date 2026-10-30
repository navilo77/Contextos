from __future__ import annotations

import asyncio
import logging
import re
import secrets
from collections.abc import Mapping
from contextlib import asynccontextmanager
from typing import AsyncIterator

from fastapi import FastAPI, HTTPException, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse, Response
from sqlalchemy.exc import IntegrityError, OperationalError, ProgrammingError, SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker
from starlette.middleware.base import RequestResponseEndpoint

from app.api.v1.projects import router as projects_router
from app.config import ProviderConfigurationError
from app.models import GeneratedDocuments
from app.modules.discovery.service import DiscoveryService
from app.modules.document_generation.service import DocumentGenerationService
from app.services.package_builder import PackageValidationError, build_verified_archive
from app.services.provider import ProviderError
from app.session_store import (
    DatabaseSessionStore,
    SessionPersistenceError,
    SessionStore,
)
from app.web.form_data import (
    bounded as _bounded,
)
from app.web.form_data import (
    check_csrf as _check_csrf,
)
from app.web.form_data import (
    read_form as _read_form,
)
from app.web.views import (
    MAX_IDEA_CHARS,
)
from app.web.views import (
    error_page as _error_page,
)
from app.web.views import (
    home_content as _home_content,
)
from app.web.views import (
    page as _page,
)
from app.web.views import (
    preview_content as _preview_content,
)
from app.web.views import (
    questions_content as _questions_content,
)

logger = logging.getLogger(__name__)
_ERROR_CODE_PATTERN = re.compile(r"[a-z][a-z0-9_]{0,63}\Z")


def _api_error_response(
    request: Request,
    *,
    status_code: int,
    code: str,
    message: str,
    headers: Mapping[str, str] | None = None,
) -> JSONResponse:
    safe_code = code if _ERROR_CODE_PATTERN.fullmatch(code) else "request_failed"
    request_id = getattr(request.state, "request_id", secrets.token_urlsafe(16))
    response_headers = dict(headers or {})
    response_headers["X-Request-ID"] = request_id
    return JSONResponse(
        status_code=status_code,
        headers=response_headers,
        content={
            "type": f"https://context-os.local/problems/{safe_code.replace('_', '-')}",
            "title": "Request could not be completed",
            "status": status_code,
            "detail": message,
            "code": safe_code,
            "request_id": request_id,
            "errors": [],
        },
    )


def create_web_app(
    *,
    discovery_service: DiscoveryService,
    generation_service: DocumentGenerationService,
    session_store: SessionStore,
    database_session_factory: async_sessionmaker[AsyncSession] | None = None,
    database_engine: AsyncEngine | None = None,
) -> FastAPI:
    @asynccontextmanager
    async def lifespan(_: FastAPI) -> AsyncIterator[None]:
        cleanup_task = (
            asyncio.create_task(_cleanup_expired_web_sessions(app.state.persistent_sessions))
            if app.state.persistent_sessions is not None
            else None
        )
        try:
            yield
        finally:
            if cleanup_task is not None:
                cleanup_task.cancel()
                try:
                    await cleanup_task
                except asyncio.CancelledError:
                    pass
            if database_engine is not None:
                await database_engine.dispose()

    app = FastAPI(title="Context OS", docs_url=None, redoc_url=None, lifespan=lifespan)
    app.state.discovery_service = discovery_service
    app.state.generation_service = generation_service
    app.state.sessions = session_store
    app.state.persistent_sessions = (
        DatabaseSessionStore(database_session_factory)
        if database_session_factory is not None
        else None
    )
    app.state.database_session_factory = database_session_factory
    app.include_router(projects_router)

    @app.exception_handler(SQLAlchemyError)
    async def handle_database_error(request: Request, exc: SQLAlchemyError) -> JSONResponse:
        if isinstance(exc, IntegrityError):
            status_code = 409
            code = "database_conflict"
            message = "The project could not be saved because it conflicts with existing data."
        elif isinstance(exc, (OperationalError, ProgrammingError)):
            status_code = 503
            code = "database_unavailable"
            message = (
                "Project storage is unavailable or not migrated. Check PostgreSQL and apply "
                "the documented migrations."
            )
        else:
            status_code = 500
            code = "database_operation_failed"
            message = "Project storage failed. No successful result was recorded."
        logger.error("Database operation failed: %s", type(exc).__name__)
        return _api_error_response(
            request,
            status_code=status_code,
            code=code,
            message=message,
        )

    @app.exception_handler(RequestValidationError)
    async def handle_request_validation_error(
        request: Request,
        __: RequestValidationError,
    ) -> JSONResponse:
        return _api_error_response(
            request,
            status_code=422,
            code="invalid_request",
            message="The request is invalid. Check the documented fields and limits.",
        )

    @app.exception_handler(HTTPException)
    async def handle_http_error(request: Request, exc: HTTPException) -> JSONResponse:
        if isinstance(exc.detail, dict):
            code = str(exc.detail.get("code", "request_failed"))
            message = str(exc.detail.get("message", "The request could not be completed."))
        else:
            code = {
                400: "bad_request",
                404: "not_found",
                409: "conflict",
                422: "invalid_request",
                502: "provider_request_failed",
                503: "service_unavailable",
            }.get(exc.status_code, "request_failed")
            message = str(exc.detail)
        return _api_error_response(
            request,
            status_code=exc.status_code,
            code=code,
            message=message,
            headers=exc.headers,
        )

    @app.exception_handler(Exception)
    async def handle_unexpected_error(request: Request, exc: Exception) -> JSONResponse:
        logger.error("Unhandled request failure: %s", type(exc).__name__)
        return _api_error_response(
            request,
            status_code=500,
            code="internal_error",
            message="An unexpected server error occurred. Use the request ID when reporting it.",
        )

    @app.middleware("http")
    async def local_session(
        request: Request,
        call_next: RequestResponseEndpoint,
    ) -> Response:
        session_id = request.cookies.get("context_os_session")
        request.state.request_id = secrets.token_urlsafe(16)
        persistent_store: DatabaseSessionStore | None = (
            app.state.persistent_sessions if not request.url.path.startswith("/api/v1/") else None
        )
        response: Response
        try:
            if persistent_store is None:
                session_id, session, is_new = app.state.sessions.get_or_create(session_id)
            else:
                session_id, session, is_new = await persistent_store.get_or_create(session_id)
        except SQLAlchemyError as exc:
            logger.error("Could not load persisted workflow state: %s", type(exc).__name__)
            response = _api_error_response(
                request,
                status_code=503,
                code="workflow_storage_unavailable",
                message="The saved workflow could not be loaded. Check PostgreSQL and migrations.",
            )
            response.headers["Cache-Control"] = "no-store"
            response.headers["X-Content-Type-Options"] = "nosniff"
            response.headers["Referrer-Policy"] = "no-referrer"
            response.headers["Content-Security-Policy"] = (
                "default-src 'self'; style-src 'unsafe-inline'; form-action 'self'; "
                "frame-ancestors 'none'; base-uri 'none'"
            )
            return response
        except SessionPersistenceError:
            logger.error("Stored workflow state could not be decoded.")
            response = _api_error_response(
                request,
                status_code=500,
                code="workflow_state_invalid",
                message="The saved workflow state is invalid and could not be loaded.",
            )
            response.headers["Cache-Control"] = "no-store"
            response.headers["X-Content-Type-Options"] = "nosniff"
            response.headers["Referrer-Policy"] = "no-referrer"
            response.headers["Content-Security-Policy"] = (
                "default-src 'self'; style-src 'unsafe-inline'; form-action 'self'; "
                "frame-ancestors 'none'; base-uri 'none'"
            )
            return response
        request.state.session_id = session_id
        request.state.session = session
        response = await call_next(request)
        if persistent_store is not None:
            try:
                await persistent_store.save(session_id, session)
            except SQLAlchemyError as exc:
                logger.error("Could not save persisted workflow state: %s", type(exc).__name__)
                response = _api_error_response(
                    request,
                    status_code=503,
                    code="workflow_storage_unavailable",
                    message=(
                        "The workflow was not saved. Check PostgreSQL and retry the operation."
                    ),
                )
            except SessionPersistenceError:
                logger.error("Workflow state exceeded its safe persistence contract.")
                response = _api_error_response(
                    request,
                    status_code=413,
                    code="workflow_state_too_large",
                    message=(
                        "The workflow state is too large to persist safely. Start a smaller project."
                    ),
                )
        if is_new:
            response.set_cookie(
                "context_os_session",
                session_id,
                max_age=30 * 60,
                httponly=True,
                samesite="strict",
                secure=False,
                path="/",
            )
        response.headers["Cache-Control"] = "no-store"
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["Referrer-Policy"] = "no-referrer"
        response.headers["X-Request-ID"] = request.state.request_id
        response.headers["Content-Security-Policy"] = (
            "default-src 'self'; style-src 'unsafe-inline'; form-action 'self'; "
            "frame-ancestors 'none'; base-uri 'none'"
        )
        return response

    @app.get("/", response_class=HTMLResponse)
    async def home(request: Request) -> HTMLResponse:
        session = request.state.session
        old = session.data.get("intake", {})
        content = _home_content(session.csrf_token, old)
        return _page("Idea তৈরি শুরু করুন", content)

    @app.post("/clarify", response_class=HTMLResponse)
    async def clarify(request: Request) -> HTMLResponse:
        form, error = await _read_form(request)
        if error:
            return _error_page(request, error, status=413)
        session = request.state.session
        problem = _check_csrf(session.csrf_token, form)
        if problem:
            return _error_page(request, problem, status=403)
        idea = form.get("idea", "").strip()
        if not idea:
            return _error_page(request, "তোমার app idea লিখে আবার চেষ্টা করো।")
        if len(idea) > MAX_IDEA_CHARS:
            return _error_page(request, "Idea সর্বোচ্চ ২০,০০০ অক্ষরের হতে পারবে।")
        if form.get("consent") != "yes":
            return _error_page(
                request, "AI provider-এ idea পাঠানোর আগে external-processing সম্মতি প্রয়োজন।"
            )
        intake = {
            "idea": idea,
            "audience": _bounded(form.get("audience", ""), 1000),
            "platform": _bounded(form.get("platform", ""), 500),
            "constraints": _bounded(form.get("constraints", ""), 2000),
            "technology": _bounded(form.get("technology", ""), 500),
            "language": _bounded(form.get("language", "auto"), 80) or "auto",
            "profile": form.get("profile", "compact"),
        }
        if intake["profile"] not in ("compact", "detailed"):
            return _error_page(request, "Package type নির্বাচনটি সঠিক নয়।")
        try:
            result = await app.state.discovery_service.clarify(intake)
        except (ProviderConfigurationError, ProviderError) as exc:
            return _error_page(request, str(exc))
        session.data = {"intake": intake, "questions": [q.model_dump() for q in result.questions]}
        return _page("কয়েকটি বিষয় পরিষ্কার করি", _questions_content(session))

    @app.post("/review", response_class=HTMLResponse)
    async def review(request: Request) -> HTMLResponse:
        form, error = await _read_form(request)
        if error:
            return _error_page(request, error, status=413)
        session = request.state.session
        problem = _check_csrf(session.csrf_token, form)
        if problem:
            return _error_page(request, problem, status=403)
        intake = session.data.get("intake")
        questions = session.data.get("questions")
        if not intake or questions is None:
            return _error_page(request, "এই session-এ idea পাওয়া যায়নি। নতুন করে শুরু করো।", status=400)
        answers: dict[str, str] = {}
        for index, question in enumerate(questions):
            value = _bounded(form.get(f"answer_{index}", ""), 2000)
            unknown = form.get(f"unknown_{index}") == "yes"
            if value and unknown:
                return _error_page(
                    request, "একই প্রশ্নে উত্তর এবং ‘এখনো ঠিক করিনি’—দুটো একসাথে দেওয়া যাবে না।"
                )
            answers[question["question"]] = (
                "Not decided yet." if unknown else value or "Not decided yet."
            )
        try:
            result = await app.state.generation_service.generate_package(intake, answers)
            generated = result.documents
        except ProviderError as exc:
            return _error_page(request, str(exc))
        except PackageValidationError as exc:
            return _error_page(
                request,
                "Package validation পাস করেনি। আবার চেষ্টা করো। সমস্যা: " + "; ".join(exc.errors),
            )
        except ProviderConfigurationError as exc:
            return _error_page(request, str(exc))
        except (ValueError, TypeError, KeyError, OSError):
            return _error_page(request, "Project package তৈরি করা যায়নি। input ঠিক করে আবার চেষ্টা করো।")
        session.data.update(
            {
                "generated": generated.model_dump(mode="json"),
                "answers": answers,
                "package": result.files,
            }
        )
        return _page("ZIP তৈরির আগে দেখে নাও", _preview_content(session))

    @app.post("/download")
    async def download(request: Request) -> Response:
        form, error = await _read_form(request)
        if error:
            return _error_page(request, error, status=413)
        session = request.state.session
        problem = _check_csrf(session.csrf_token, form)
        if problem:
            return _error_page(request, problem, status=403)
        package = session.data.get("package")
        generated_data = session.data.get("generated")
        if not package or not generated_data:
            return _error_page(
                request, "ZIP নেই বা session-এর মেয়াদ শেষ হয়েছে। আবার শুরু করো।", status=400
            )
        if not isinstance(package, dict) or not all(
            isinstance(path, str) and isinstance(content, bytes)
            for path, content in package.items()
        ):
            return _error_page(
                request,
                "সংরক্ষিত package state সঠিক নয়। আবার package তৈরি করো।",
                status=500,
            )
        generated = GeneratedDocuments.model_validate(generated_data)
        try:
            archive = build_verified_archive(generated.project_slug, package)
        except PackageValidationError:
            logger.error("Stored HTML package failed safe ZIP reconstruction.")
            return _error_page(
                request,
                "সংরক্ষিত package যাচাই করা যায়নি। আবার package তৈরি করো।",
                status=500,
            )
        return Response(
            content=archive,
            media_type="application/zip",
            headers={"Content-Disposition": f'attachment; filename="{generated.project_slug}.zip"'},
        )

    @app.post("/edit")
    async def edit(request: Request) -> HTMLResponse:
        form, error = await _read_form(request)
        if error:
            return _error_page(request, error, status=413)
        session = request.state.session
        problem = _check_csrf(session.csrf_token, form)
        if problem:
            return _error_page(request, problem, status=403)
        session.data.pop("package", None)
        session.data.pop("archive", None)
        session.data.pop("generated", None)
        if "intake" not in session.data:
            return _error_page(request, "এই session-এ idea পাওয়া যায়নি। নতুন করে শুরু করো।", status=400)
        return _page("উত্তর সম্পাদনা", _questions_content(session))

    @app.post("/edit-idea", response_class=HTMLResponse)
    async def edit_idea(request: Request) -> HTMLResponse:
        form, error = await _read_form(request)
        if error:
            return _error_page(request, error, status=413)
        session = request.state.session
        problem = _check_csrf(session.csrf_token, form)
        if problem:
            return _error_page(request, problem, status=403)
        session.data.pop("package", None)
        session.data.pop("archive", None)
        session.data.pop("generated", None)
        return _page(
            "Idea সম্পাদনা", _home_content(session.csrf_token, session.data.get("intake", {}))
        )

    @app.post("/reset")
    async def reset(request: Request) -> Response:
        form, error = await _read_form(request)
        if error:
            return _error_page(request, error, status=413)
        session = request.state.session
        problem = _check_csrf(session.csrf_token, form)
        if problem:
            return _error_page(request, problem, status=403)
        session.data.clear()
        session.csrf_token = secrets.token_urlsafe(32)
        return RedirectResponse("/", status_code=303)

    return app


async def _cleanup_expired_web_sessions(store: DatabaseSessionStore) -> None:
    while True:
        try:
            await store.delete_expired()
        except SQLAlchemyError as exc:
            logger.warning("Expired workflow sessions could not be cleaned: %s", type(exc).__name__)
        await asyncio.sleep(60)
