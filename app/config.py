from __future__ import annotations

import ipaddress
import os
import re
from dataclasses import dataclass
from urllib.parse import urlsplit

from dotenv import load_dotenv

load_dotenv(override=False)

DEFAULT_GEMINI_MODEL = "gemini-3.8-flash"


@dataclass(frozen=True, slots=True)
class Settings:
    gemini_api_key: str
    gemini_model: str
    host: str
    port: int
    frontend_origin: str = "http://127.0.0.1:3000"

    def __post_init__(self) -> None:
        if not 1 <= self.port <= 65535:
            raise ValueError("CONTEXT_OS_PORT must be between 1 and 65535")
        if self.host.lower() == "localhost":
            return
        try:
            is_loopback = ipaddress.ip_address(self.host).is_loopback
        except ValueError as exc:
            raise ValueError("CONTEXT_OS_HOST must be localhost or a loopback IP address") from exc
        if not is_loopback:
            raise ValueError("CONTEXT_OS_HOST must be localhost or a loopback IP address")
        try:
            origin = urlsplit(self.frontend_origin)
            origin_port = origin.port
            origin_host = origin.hostname
        except ValueError as exc:
            raise ValueError("CONTEXT_OS_FRONTEND_ORIGIN must be a loopback HTTP origin") from exc
        if (
            origin.scheme != "http"
            or origin_host is None
            or origin.username is not None
            or origin.password is not None
            or origin.path not in ("", "/")
            or origin.query
            or origin.fragment
            or (origin_port is not None and not 1 <= origin_port <= 65535)
        ):
            raise ValueError("CONTEXT_OS_FRONTEND_ORIGIN must be a loopback HTTP origin")
        if origin_host.lower() != "localhost":
            try:
                frontend_is_loopback = ipaddress.ip_address(origin_host).is_loopback
            except ValueError as exc:
                raise ValueError("CONTEXT_OS_FRONTEND_ORIGIN must use a loopback host") from exc
            if not frontend_is_loopback:
                raise ValueError("CONTEXT_OS_FRONTEND_ORIGIN must use a loopback host")

    @classmethod
    def from_env(cls) -> "Settings":
        try:
            port = int(os.getenv("CONTEXT_OS_PORT", "8000"))
        except ValueError as exc:
            raise ValueError("CONTEXT_OS_PORT must be a valid port number") from exc
        return cls(
            gemini_api_key=os.getenv("GEMINI_API_KEY", ""),
            gemini_model=os.getenv("GEMINI_MODEL", DEFAULT_GEMINI_MODEL),
            host=os.getenv("CONTEXT_OS_HOST", "127.0.0.1"),
            port=port,
            frontend_origin=os.getenv(
                "CONTEXT_OS_FRONTEND_ORIGIN",
                "http://127.0.0.1:3000",
            ),
        )

    def require_provider(self) -> None:
        if not self.gemini_api_key:
            raise ProviderConfigurationError(
                "Gemini API is not configured. Set GEMINI_API_KEY in the local .env file "
                "using a key from Google AI Studio, then restart Context OS."
            )
        if not re.fullmatch(r"[A-Za-z0-9._-]{1,128}", self.gemini_model):
            raise ProviderConfigurationError("GEMINI_MODEL contains invalid characters.")


class ProviderConfigurationError(RuntimeError):
    """Safe, actionable provider configuration error."""
