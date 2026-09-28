"""Voter identity helpers: client IP, signed session cookie, fingerprints, seeded ordering."""

import hashlib
import hmac
import secrets
from typing import Optional, Sequence, TypeVar

from fastapi import Request

from app.config import settings

SESSION_COOKIE = "voter_session"
SESSION_MAX_AGE = 30 * 24 * 3600
T = TypeVar("T")


def sha(raw: str) -> str:
    return hashlib.sha256(raw.encode()).hexdigest()


def client_ip(request: Request) -> str:
    """Best-effort client IP. Honors the first X-Forwarded-For hop when TRUST_PROXY_HEADERS is set."""
    if settings.TRUST_PROXY_HEADERS:
        fwd = request.headers.get("x-forwarded-for")
        if fwd:
            return fwd.split(",")[0].strip()
    return request.client.host if request.client else "unknown"


def _sig(session_id: str) -> str:
    return hmac.new(settings.JWT_SECRET_KEY.encode(), session_id.encode(), hashlib.sha256).hexdigest()[:24]


def sign_session(session_id: str) -> str:
    return f"{session_id}.{_sig(session_id)}"


def read_session(cookie_value: Optional[str]) -> Optional[str]:
    """Return the session id if the cookie carries a valid signature, else None."""
    if not cookie_value or "." not in cookie_value:
        return None
    sid, sig = cookie_value.rsplit(".", 1)
    return sid if hmac.compare_digest(sig, _sig(sid)) else None


def new_session_id() -> str:
    return secrets.token_hex(16)


def generate_voter_fingerprint(
    ip_address: str,
    session_id: Optional[str] = None,
    user_agent: Optional[str] = None,
) -> str:
    """Legacy IP/session/UA fingerprint (kept for compatibility)."""
    if session_id:
        raw = f"{ip_address}:{session_id}"
    elif user_agent:
        raw = f"{ip_address}:{user_agent}"
    else:
        raw = ip_address
    return sha(raw)


def seeded_order(items: Sequence[T], seed: str, key=lambda x: x.id) -> list[T]:
    """Deterministic per-seed shuffle: same seed -> same order, different seeds -> different orders."""
    return sorted(items, key=lambda it: sha(f"{seed}:{key(it)}"))
