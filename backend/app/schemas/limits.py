"""Input size limits, one place.

Every free-text field a client can send is bounded, so hostile input gets a clean 422 instead of a database
error (a 500) or an unbounded row. The numbers match the column sizes (VARCHAR(255) / (500)) or are generous
but finite for TEXT columns.
"""

from typing import Annotated, Any

from pydantic import AfterValidator, EmailStr, Field

Str255 = Annotated[str, Field(max_length=255)]          # names, slugs (VARCHAR(255))
Str500 = Annotated[str, Field(max_length=500)]          # taglines, URLs (VARCHAR(500))
Str2000 = Annotated[str, Field(max_length=2000)]        # short descriptions
Text20k = Annotated[str, Field(max_length=20_000)]      # event descriptions
Markdown50k = Annotated[str, Field(max_length=50_000)]  # project write-ups
Email254 = Annotated[EmailStr, Field(max_length=254)]
Password = Annotated[str, Field(min_length=8, max_length=128)]  # new passwords
LoginPassword = Annotated[str, Field(max_length=128)]   # sign-in: any length up to the cap (a short guess is a 401, not a 422)

MAX_JSON_ANSWERS_BYTES = 20_000


def http_url(value: str) -> str:
    """Only http(s) links may be stored: `javascript:` / `data:` URLs would become clickable script in any client."""
    from urllib.parse import urlparse

    value = value.strip()
    if not value:
        return value  # the UI sends "" for "not set"
    p = urlparse(value)
    if p.scheme not in ("http", "https") or not p.netloc:
        raise ValueError("must be an http:// or https:// URL")
    return value


Url500 = Annotated[str, Field(max_length=500), AfterValidator(http_url)]


def _small_json(value: dict[str, Any]) -> dict[str, Any]:
    import json

    if len(json.dumps(value, ensure_ascii=False, default=str)) > MAX_JSON_ANSWERS_BYTES:
        raise ValueError(f"custom_answers is too large (limit {MAX_JSON_ANSWERS_BYTES} bytes of JSON)")
    return value


CustomAnswers = Annotated[dict[str, Any], AfterValidator(_small_json)]
Urls20 = Annotated[list[Str500], Field(max_length=20)]                                     # gallery images
Tags30 = Annotated[list[Annotated[str, Field(max_length=50)]], Field(max_length=30)]        # tech tags
