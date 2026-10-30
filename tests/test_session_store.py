from __future__ import annotations

import pytest

from app.session_store import (
    MAX_PERSISTED_SESSION_BYTES,
    SessionPersistenceError,
    _decode_session_data,
    _encode_session_data,
    _serialize_session_data,
)


def test_session_payload_round_trips_bytes_and_reserved_mapping_keys() -> None:
    payload = {
        "package": {"README.md": b"Context OS"},
        "__context_os_bytes__": "ordinary user data",
        "__context_os_mapping__": "also ordinary user data",
        "nested": [{"value": b"\x00\xff"}],
    }

    assert _decode_session_data(_encode_session_data(payload)) == payload


def test_session_payload_rejects_non_string_mapping_keys() -> None:
    with pytest.raises(SessionPersistenceError, match="unsupported"):
        _encode_session_data({1: "not a JSON object key"})


def test_persisted_session_payload_has_a_bounded_size() -> None:
    with pytest.raises(SessionPersistenceError, match="too large"):
        _serialize_session_data({"content": b"x" * MAX_PERSISTED_SESSION_BYTES})
