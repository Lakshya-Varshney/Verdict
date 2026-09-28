"""Deterministic ids for seeded / imported rows.

Fixture ids are opaque strings (``evt_01``, ``prj_07`` ...) but our primary keys
are UUIDs and our routes take UUID path params. Deriving the UUID with uuid5
means the same fixture id maps to the same row id on every boot and on every
machine, so ``.dogfood.toml`` can hard-code real routes.
"""

import uuid

_NAMESPACE = uuid.uuid5(uuid.NAMESPACE_URL, "https://dogfoodhack.com/spec/fixtures")


def stable_id(kind: str, key: str) -> str:
    """Return a stable UUID string for ``(kind, key)``, e.g. ``("project", "prj_01")``."""
    return str(uuid.uuid5(_NAMESPACE, f"{kind}:{key}"))


def user_id_for_email(email: str) -> str:
    return stable_id("user", email.strip().lower())
