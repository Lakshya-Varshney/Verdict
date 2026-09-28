"""Ed25519 signing for certificates and judge participation records.

Public-key signatures (rather than a shared HMAC secret) so that *anyone* can verify a document offline with
only the published public key: `GET /.well-known/dogfood-signing-key`, and `scripts/verify_certificate.py`
does it with nothing but the Python standard library.

What is signed is the **canonical JSON** of the payload: UTF-8, keys sorted, no whitespace. The payload
contains only ints and strings, so every language canonicalises it identically.
"""

import base64
import hashlib
import json
from functools import lru_cache
from typing import Any

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey, Ed25519PublicKey

from app.config import settings

ALGORITHM = "Ed25519"


def b64u(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).rstrip(b"=").decode()


def b64u_decode(text: str) -> bytes:
    return base64.urlsafe_b64decode(text + "=" * (-len(text) % 4))


def canonical(payload: dict[str, Any]) -> bytes:
    return json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")


def payload_hash(payload: dict[str, Any]) -> str:
    """The public verification code of a document: sha256 of its canonical payload."""
    return hashlib.sha256(canonical(payload)).hexdigest()


@lru_cache(maxsize=1)
def _private_key() -> Ed25519PrivateKey:
    secret = settings.CERT_SIGNING_KEY or settings.JWT_SECRET_KEY
    seed = hashlib.sha256(b"dogfood-certificate-signing-v1:" + secret.encode()).digest()
    return Ed25519PrivateKey.from_private_bytes(seed)


def public_key_bytes() -> bytes:
    return _private_key().public_key().public_bytes(
        serialization.Encoding.Raw, serialization.PublicFormat.Raw
    )


def public_key_b64() -> str:
    return b64u(public_key_bytes())


def key_id() -> str:
    """Short stable identifier of the public key (so signatures can name the key that made them)."""
    return hashlib.sha256(public_key_bytes()).hexdigest()[:16]


def sign(payload: dict[str, Any]) -> str:
    return b64u(_private_key().sign(canonical(payload)))


def verify(payload: dict[str, Any], signature: str, public_key: bytes | None = None) -> bool:
    key = Ed25519PublicKey.from_public_bytes(public_key or public_key_bytes())
    try:
        key.verify(b64u_decode(signature), canonical(payload))
        return True
    except (InvalidSignature, ValueError):
        return False
