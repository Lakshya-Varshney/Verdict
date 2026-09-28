"""Certificates, signed judge participation records and their public verification (T4)."""

from typing import Optional
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Path, Query, Request, Response, status
from fastapi.responses import HTMLResponse
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user
from app.database import get_db
from app.models.certificate import Certificate
from app.models.event import Event, EventRole, EventRoleType
from app.models.user import User
from app.schemas.api import CertificateOut, SigningKeyOut, VerifyOut, VerifyRequest
from app.services import signing
from app.services.audit_service import create_audit_log
from app.services.certificate_render import render_html, render_pdf, verify_urls
from app.services.certificate_service import CertError, check_record, get_or_issue
from app.utils.fingerprint import client_ip
from app.services.webhook_service import emit as emit_webhook
from app.utils.rate_limit import hit

router = APIRouter(tags=["certificates"])


def _out(cert: Certificate) -> dict:
    p = cert.payload
    web, api = verify_urls(cert.verification_hash)
    return {
        "event_id": p["event"]["id"], "event_name": p["event"]["name"],
        "user_id": p["recipient"]["id"], "user_name": p["recipient"]["name"],
        "kind": p["kind"], "detail": p["detail"], "issued_at": p["issued_at"],
        "verify_hash": cert.verification_hash, "signature": cert.signature,
        "key_id": signing.key_id(), "algorithm": signing.ALGORITHM, "payload": p,
        "verify_url": web, "api_verify_url": api,
    }


async def _limit(request: Request) -> None:
    ok, retry = await hit(f"verify:{client_ip(request)}", 60, 60)
    if not ok:
        raise HTTPException(status_code=status.HTTP_429_TOO_MANY_REQUESTS, detail="Too many verification requests",
                            headers={"Retry-After": str(retry)})


@router.get("/events/{event_id}/certificates/{user_id}", response_model=CertificateOut)
async def get_certificate(
    event_id: UUID,
    user_id: UUID,
    kind: Optional[str] = Query(None, description="participant | judge | winner (default: the best one earned)"),
    format: str = Query("json", pattern="^(json|pdf|html)$", description="json (default), pdf or html (verifiable)"),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Get (issuing on first request) a signed certificate. Yourself, or an organizer/admin for anyone."""
    event = (await db.execute(select(Event).where(Event.id == str(event_id)))).scalar_one_or_none()
    if event is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Event not found")
    actor_id = current_user.id
    if str(user_id) != str(actor_id):
        staff = await db.execute(select(EventRole.id).where(
            EventRole.event_id == str(event_id), EventRole.user_id == str(actor_id),
            EventRole.role.in_([EventRoleType.ORGANIZER, EventRoleType.ADMIN])))
        if staff.first() is None:
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="You can only view your own certificate")
    target = (await db.execute(select(User).where(User.id == str(user_id)))).scalar_one_or_none()
    if target is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found")
    try:
        cert, created = await get_or_issue(db, event, target, kind)
    except CertError as e:
        raise HTTPException(status_code=e.status_code, detail=e.detail)
    if created:
        await create_audit_log(
            db, "certificate.issue", "certificate", cert.id, actor_id=actor_id, event_id=event.id,
            extra_data={"role": "user" if str(user_id) == str(actor_id) else "organizer", "kind": cert.type,
                        "recipient": str(user_id), "verify_hash": cert.verification_hash,
                        "detail": f"issued {cert.type} certificate"},
        )
        await emit_webhook(db, event.id, "certificate.issued",
                           {"kind": cert.type, "recipient_id": str(user_id), "verify_hash": cert.verification_hash})
    if format == "pdf":
        pdf = render_pdf(cert.payload, cert.signature, cert.verification_hash, signing.key_id())
        return Response(pdf, media_type="application/pdf",
                        headers={"Content-Disposition": f'attachment; filename="{cert.type}-certificate-{cert.verification_hash[:8]}.pdf"'})
    if format == "html":
        return HTMLResponse(render_html(cert.payload, cert.signature, cert.verification_hash, signing.key_id(), signing.ALGORITHM))
    return _out(cert)


@router.get("/verify/{code}", response_model=VerifyOut)
async def verify_by_code(
    request: Request,
    code: str = Path(min_length=1, max_length=64, pattern="^[0-9a-fA-F]+$", description="Certificate code (hex)"),
    db: AsyncSession = Depends(get_db),
):
    """Public: verify a certificate by its code. Re-checks the stored document's hash and signature."""
    await _limit(request)
    cert = (await db.execute(select(Certificate).where(Certificate.verification_hash == code.lower()))).scalar_one_or_none()
    if cert is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="No certificate with that code")
    return {"valid": check_record(cert), "issued_by_this_server": True, "certificate": cert.payload,
            "verify_hash": cert.verification_hash, "key_id": signing.key_id(), "algorithm": signing.ALGORITHM}


@router.post("/verify", response_model=VerifyOut)
async def verify_document(body: VerifyRequest, request: Request, db: AsyncSession = Depends(get_db)):
    """Public: verify a certificate you were handed (payload + signature), without trusting our database."""
    await _limit(request)
    valid = signing.verify(body.payload, body.signature)
    code = signing.payload_hash(body.payload)
    known = (await db.execute(select(Certificate.id).where(Certificate.verification_hash == code))).first() is not None
    return {"valid": valid, "issued_by_this_server": known if valid else None,
            "certificate": body.payload if valid else None, "verify_hash": code if valid else None,
            "key_id": signing.key_id(), "algorithm": signing.ALGORITHM}


@router.get("/.well-known/dogfood-signing-key", response_model=SigningKeyOut)
async def signing_key(response: Response):
    """Public: the Ed25519 public key that signs every certificate (verify offline, no secret needed)."""
    response.headers["Cache-Control"] = "public, max-age=3600"
    return {
        "algorithm": signing.ALGORITHM, "key_id": signing.key_id(), "public_key": signing.public_key_b64(),
        "how_to_verify": "Canonicalise the payload (UTF-8 JSON, sorted keys, no whitespace) and check the base64url "
                         "Ed25519 signature with this key: python backend/scripts/verify_certificate.py --key <public_key> cert.json",
    }
