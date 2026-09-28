"""Request guard: hostile-input defenses that must hold before any route code runs.

Pure ASGI (not BaseHTTPMiddleware) so the body can be inspected and then replayed to the app untouched.

  * **NUL characters** (raw, JSON-escaped `\\u0000`, or `%00` in the URL) are rejected with 422: PostgreSQL cannot
    store them, so without this any free-text field would be a 500.
  * **Body size cap**: 2 MB for ordinary requests, 50 MB for `/events/{id}/import`; anything larger is a 413 without
    the app ever buffering it (declared Content-Length is checked first, streamed bodies are counted).
"""

import json
import re
from typing import Awaitable, Callable

MAX_BODY_BYTES = 2 * 1024 * 1024
MAX_IMPORT_BYTES = 50 * 1024 * 1024
_IMPORT_PATH = re.compile(r"^/events/[^/]+/import/?$")
_JSON_NUL = re.compile(rb"\\u0000", re.IGNORECASE)


def _limit_for(path: str) -> int:
    return MAX_IMPORT_BYTES if _IMPORT_PATH.match(path) else MAX_BODY_BYTES


async def _reject(send, status: int, detail: str) -> None:
    body = json.dumps({"detail": detail}).encode()
    await send({"type": "http.response.start", "status": status,
                "headers": [(b"content-type", b"application/json"), (b"content-length", str(len(body)).encode())]})
    await send({"type": "http.response.body", "body": body})


class RequestGuardMiddleware:
    def __init__(self, app: Callable[..., Awaitable[None]]):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            return await self.app(scope, receive, send)

        downstream = send

        async def send_with_headers(message):
            if message["type"] == "http.response.start":
                names = {k.lower() for k, _ in message.get("headers", [])}
                extra = [(b"x-content-type-options", b"nosniff"), (b"referrer-policy", b"no-referrer")]
                message = {**message, "headers": list(message.get("headers", [])) + [h for h in extra if h[0] not in names]}
            await downstream(message)

        send = send_with_headers

        raw_target = scope.get("raw_path", b"") + b"?" + scope.get("query_string", b"")
        if b"%00" in raw_target.lower() or b"\x00" in raw_target:
            return await _reject(send, 422, "NUL characters are not allowed")

        limit = _limit_for(scope.get("path", ""))
        declared = dict(scope.get("headers", [])).get(b"content-length")
        try:
            if declared is not None and int(declared) > limit:
                return await _reject(send, 413, f"Request body too large (limit {limit // (1024 * 1024)} MB)")
        except ValueError:
            return await _reject(send, 400, "Invalid Content-Length")

        if scope["method"] in ("GET", "HEAD", "OPTIONS", "DELETE") and declared in (None, b"0"):
            return await self.app(scope, receive, send)

        chunks: list[bytes] = []
        size = 0
        while True:
            message = await receive()
            if message["type"] == "http.disconnect":
                return
            chunk = message.get("body", b"")
            size += len(chunk)
            if size > limit:
                return await _reject(send, 413, f"Request body too large (limit {limit // (1024 * 1024)} MB)")
            chunks.append(chunk)
            if not message.get("more_body", False):
                break
        body = b"".join(chunks)
        if b"\x00" in body or _JSON_NUL.search(body):
            return await _reject(send, 422, "NUL characters are not allowed")

        replayed = False

        async def replay():
            nonlocal replayed
            if not replayed:
                replayed = True
                return {"type": "http.request", "body": body, "more_body": False}
            return await receive()  # after the body: disconnect notifications

        await self.app(scope, replay, send)
