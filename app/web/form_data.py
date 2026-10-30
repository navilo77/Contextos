from __future__ import annotations

import hmac
from urllib.parse import parse_qs

from fastapi import Request

MAX_FORM_BYTES = 256_000


async def read_form(request: Request) -> tuple[dict[str, str], str | None]:
    content_length = request.headers.get("content-length")
    if content_length and content_length.isdigit() and int(content_length) > MAX_FORM_BYTES:
        return {}, "Form অনেক বড়। ছোট করে আবার চেষ্টা করো।"
    body = await request.body()
    if len(body) > MAX_FORM_BYTES:
        return {}, "Form অনেক বড়। ছোট করে আবার চেষ্টা করো।"
    try:
        parsed = parse_qs(body.decode("utf-8"), keep_blank_values=True, max_num_fields=100)
    except (UnicodeDecodeError, ValueError):
        return {}, "Form পড়া যায়নি। পেজ reload করে আবার চেষ্টা করো।"
    return {key: values[-1] for key, values in parsed.items()}, None


def check_csrf(expected: str, form: dict[str, str]) -> str | None:
    supplied = form.get("csrf_token", "")
    if not supplied or not hmac.compare_digest(expected, supplied):
        return "Session validation মেলেনি। পেজ reload করে আবার চেষ্টা করো।"
    return None


def bounded(value: str, limit: int) -> str:
    return value.strip()[:limit]
