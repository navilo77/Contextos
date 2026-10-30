from __future__ import annotations

import base64
import hashlib
import json
import secrets
import time
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Any

from sqlalchemy import delete
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.db.models import WebSession

SESSION_TTL_SECONDS = 30 * 60
MAX_PERSISTED_SESSION_BYTES = 16 * 1024 * 1024
_BYTES_MARKER = "__context_os_bytes__"
_MAPPING_MARKER = "__context_os_mapping__"


@dataclass(slots=True)
class Session:
    csrf_token: str = field(default_factory=lambda: secrets.token_urlsafe(32))
    data: dict[str, Any] = field(default_factory=dict)
    expires_at: float = field(default_factory=lambda: time.monotonic() + SESSION_TTL_SECONDS)


class SessionStore:
    """Short-lived process-memory sessions; no user content is written to disk."""

    def __init__(self) -> None:
        self._sessions: dict[str, Session] = {}

    def get_or_create(self, session_id: str | None) -> tuple[str, Session, bool]:
        self._discard_expired()
        if session_id and session_id in self._sessions:
            session = self._sessions[session_id]
            session.expires_at = time.monotonic() + SESSION_TTL_SECONDS
            return session_id, session, False
        new_id = secrets.token_urlsafe(32)
        session = Session()
        self._sessions[new_id] = session
        return new_id, session, True

    def discard(self, session_id: str) -> None:
        self._sessions.pop(session_id, None)

    def _discard_expired(self) -> None:
        now = time.monotonic()
        expired = [key for key, value in self._sessions.items() if value.expires_at <= now]
        for key in expired:
            del self._sessions[key]


class DatabaseSessionStore:
    """Persist short-lived HTML workflow state without storing raw session IDs."""

    def __init__(self, factory: async_sessionmaker[AsyncSession]) -> None:
        self._factory = factory

    async def delete_expired(self) -> None:
        now = datetime.now(timezone.utc)
        async with self._factory() as db, db.begin():
            await db.execute(delete(WebSession).where(WebSession.expires_at <= now))

    async def get_or_create(self, session_id: str | None) -> tuple[str, Session, bool]:
        now = datetime.now(timezone.utc)
        async with self._factory() as db, db.begin():
            await db.execute(delete(WebSession).where(WebSession.expires_at <= now))
            if session_id:
                session_hash = _session_id_hash(session_id)
                record = await db.get(WebSession, session_hash)
                if record is not None and record.expires_at > now:
                    record.expires_at = now + timedelta(seconds=SESSION_TTL_SECONDS)
                    session = Session(
                        csrf_token=record.csrf_token,
                        data=_decode_session_data(record.data),
                    )
                    return session_id, session, False
                if record is not None:
                    await db.delete(record)

            new_id = secrets.token_urlsafe(32)
            session = Session()
            db.add(
                WebSession(
                    session_id_hash=_session_id_hash(new_id),
                    csrf_token=session.csrf_token,
                    data={},
                    expires_at=now + timedelta(seconds=SESSION_TTL_SECONDS),
                )
            )
            return new_id, session, True

    async def save(self, session_id: str, session: Session) -> None:
        now = datetime.now(timezone.utc)
        data = _serialize_session_data(session.data)
        values = {
            "session_id_hash": _session_id_hash(session_id),
            "csrf_token": session.csrf_token,
            "data": data,
            "expires_at": now + timedelta(seconds=SESSION_TTL_SECONDS),
        }
        statement = insert(WebSession).values(**values)
        statement = statement.on_conflict_do_update(
            index_elements=[WebSession.session_id_hash],
            set_={
                "csrf_token": statement.excluded.csrf_token,
                "data": statement.excluded.data,
                "expires_at": statement.excluded.expires_at,
            },
        )
        async with self._factory() as db, db.begin():
            await db.execute(statement)


class SessionPersistenceError(ValueError):
    """Raised when workflow state cannot be represented within the storage contract."""


def _session_id_hash(session_id: str) -> str:
    return hashlib.sha256(session_id.encode("utf-8")).hexdigest()


def _serialize_session_data(data: dict[str, Any]) -> dict[str, Any]:
    encoded = _encode_session_data(data)
    if not isinstance(encoded, dict):
        raise SessionPersistenceError("The workflow state must be a mapping.")
    try:
        payload_size = len(
            json.dumps(
                encoded,
                ensure_ascii=False,
                allow_nan=False,
                separators=(",", ":"),
            ).encode()
        )
    except (TypeError, ValueError) as exc:
        raise SessionPersistenceError("The workflow state cannot be represented safely.") from exc
    if payload_size > MAX_PERSISTED_SESSION_BYTES:
        raise SessionPersistenceError(
            "The workflow state is too large to persist safely. Start a smaller project."
        )
    return encoded


def _encode_session_data(value: Any) -> Any:
    if isinstance(value, bytes):
        return {_BYTES_MARKER: base64.b64encode(value).decode("ascii")}
    if isinstance(value, dict):
        if not all(isinstance(key, str) for key in value):
            raise SessionPersistenceError("The workflow state contains unsupported data.")
        encoded = {key: _encode_session_data(item) for key, item in value.items()}
        if set(encoded) in ({_BYTES_MARKER}, {_MAPPING_MARKER}):
            return {_MAPPING_MARKER: [[key, item] for key, item in encoded.items()]}
        return encoded
    if isinstance(value, list):
        return [_encode_session_data(item) for item in value]
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    raise SessionPersistenceError("The workflow state contains unsupported data.")


def _decode_session_data(value: Any) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise SessionPersistenceError("The stored workflow state is invalid.")

    def decode(item: Any) -> Any:
        if isinstance(item, dict):
            if set(item) == {_MAPPING_MARKER}:
                pairs = item[_MAPPING_MARKER]
                if not isinstance(pairs, list) or not all(
                    isinstance(pair, list) and len(pair) == 2 and isinstance(pair[0], str)
                    for pair in pairs
                ):
                    raise SessionPersistenceError("The stored workflow state is invalid.")
                return {pair[0]: decode(pair[1]) for pair in pairs}
            if set(item) == {_BYTES_MARKER}:
                encoded = item[_BYTES_MARKER]
                if not isinstance(encoded, str):
                    raise SessionPersistenceError("The stored workflow state is invalid.")
                try:
                    return base64.b64decode(encoded, validate=True)
                except ValueError as exc:
                    raise SessionPersistenceError("The stored workflow state is invalid.") from exc
            return {key: decode(child) for key, child in item.items()}
        if isinstance(item, list):
            return [decode(child) for child in item]
        return item

    decoded = decode(value)
    if not isinstance(decoded, dict):
        raise SessionPersistenceError("The stored workflow state is invalid.")
    return decoded
