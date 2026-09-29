"""T4+: the audit log is hash-chained, not just append-only by convention (THREAT-MODEL.md R4).

Each row's hash covers its own fields plus the previous row's hash, in strict insertion order
(`seq`, a DB identity column). `audit_service.verify_chain` recomputes every hash to detect a
database operator editing history directly - something "append-only by convention" cannot catch.
"""

import asyncio

import pytest
from sqlalchemy import select

from app.models.audit import AuditLog, GENESIS_HASH
from app.services.audit_service import create_audit_log, verify_chain
from tests.conftest import TestSessionLocal, get_auth_header


@pytest.mark.asyncio
async def test_chain_links_sequential_writes(db_session, test_organizer, test_event):
    a = await create_audit_log(db_session, "test.one", "test", "t1", actor_id=test_organizer.id, event_id=test_event.id)
    b = await create_audit_log(db_session, "test.two", "test", "t2", actor_id=test_organizer.id, event_id=test_event.id)
    c = await create_audit_log(db_session, "test.three", "test", "t3", actor_id=test_organizer.id, event_id=test_event.id)
    await db_session.commit()

    assert a.seq < b.seq < c.seq
    assert b.prev_hash == a.hash and c.prev_hash == b.hash
    assert a.hash and b.hash and c.hash and len({a.hash, b.hash, c.hash}) == 3  # no accidental collisions

    result = await verify_chain(db_session)
    assert result["valid"] is True
    assert result["checked"] >= 3
    assert result["head_hash"] == c.hash and result["head_seq"] == c.seq


@pytest.mark.asyncio
async def test_first_row_ever_chains_onto_the_genesis_hash(db_session, test_organizer, test_event):
    # whatever ran before this test in the same DB may have already written rows; what matters
    # is that *some* row's prev_hash is the genesis hash, i.e. the chain has a real start
    await create_audit_log(db_session, "test.genesis-check", "test", "t1", event_id=test_event.id)
    await db_session.commit()
    first = (await db_session.execute(select(AuditLog).order_by(AuditLog.seq.asc()).limit(1))).scalar_one()
    assert first.prev_hash == GENESIS_HASH


@pytest.mark.asyncio
async def test_verify_chain_detects_an_edited_row(db_session, test_organizer, test_event):
    row = await create_audit_log(db_session, "test.original", "test", "t1", event_id=test_event.id)
    await create_audit_log(db_session, "test.after", "test", "t2", event_id=test_event.id)
    await db_session.commit()

    # a database operator edits history directly - the application never does this
    stored = (await db_session.execute(select(AuditLog).where(AuditLog.id == row.id))).scalar_one()
    stored.action = "test.tampered"
    await db_session.commit()

    result = await verify_chain(db_session)
    assert result["valid"] is False
    assert result["broken"]["seq"] == row.seq
    assert result["broken"]["id"] == row.id
    assert "content" not in result  # the response never carries the tampered row's data


@pytest.mark.asyncio
async def test_verify_chain_detects_a_forged_hash_that_still_points_at_the_right_prev(db_session, test_organizer, test_event):
    """Editing a row's stored `hash` to some other 64-hex value (so it no longer matches its own
    recomputed content) must be caught even though `prev_hash` linkage to the row before it is
    untouched - the per-row content check, not just the linkage check, has to run."""
    row = await create_audit_log(db_session, "test.a", "test", "t1", event_id=test_event.id)
    await db_session.commit()
    stored = (await db_session.execute(select(AuditLog).where(AuditLog.id == row.id))).scalar_one()
    stored.hash = "f" * 64
    await db_session.commit()

    result = await verify_chain(db_session)
    assert result["valid"] is False
    assert result["broken"]["seq"] == row.seq


@pytest.mark.asyncio
async def test_verify_chain_detects_a_deleted_row(db_session, test_organizer, test_event):
    a = await create_audit_log(db_session, "test.a", "test", "t1", event_id=test_event.id)
    b = await create_audit_log(db_session, "test.b", "test", "t2", event_id=test_event.id)
    await db_session.commit()

    await db_session.delete((await db_session.execute(select(AuditLog).where(AuditLog.id == a.id))).scalar_one())
    await db_session.commit()

    result = await verify_chain(db_session)
    assert result["valid"] is False
    assert result["broken"]["seq"] == b.seq  # b's prev_hash now points at a hash nothing produces


@pytest.mark.asyncio
async def test_empty_and_single_row_chains_are_valid(db_session):
    result = await verify_chain(db_session)
    assert result["valid"] is True  # empty (or whatever this test DB already has) is trivially valid


@pytest.mark.asyncio
async def test_concurrent_writers_do_not_fork_the_chain(db_session, test_organizer, test_event):
    """The advisory lock in `create_audit_log` must serialize concurrent appends: without it,
    two transactions could both read the same tip hash and each link a new row onto it,
    producing two rows with the same `prev_hash` instead of one straight line."""
    eid = test_event.id

    async def write(n: int):
        async with TestSessionLocal() as session:
            await create_audit_log(session, f"test.concurrent.{n}", "test", str(n), event_id=eid)
            await session.commit()

    await asyncio.gather(*(write(n) for n in range(12)))

    result = await verify_chain(db_session)
    assert result["valid"] is True, result.get("broken")

    prev_hashes = [
        r.prev_hash
        for r in (await db_session.execute(
            select(AuditLog).where(AuditLog.action.like("test.concurrent.%")).order_by(AuditLog.seq.asc())
        )).scalars().all()
    ]
    assert len(prev_hashes) == len(set(prev_hashes)) == 12  # no two rows share a prev_hash (no fork)


@pytest.mark.asyncio
async def test_verify_endpoint_requires_organizer_or_admin(client, test_organizer, test_user, test_event):
    assert (await client.get("/admin/audit/verify")).status_code == 401
    assert (await client.get("/admin/audit/verify", headers=get_auth_header(test_user))).status_code == 403
    r = await client.get("/admin/audit/verify", headers=get_auth_header(test_organizer))
    assert r.status_code == 200 and "valid" in r.json()


@pytest.mark.asyncio
async def test_verify_endpoint_reports_tampering_without_leaking_content(client, db_session, test_organizer, test_user, test_event):
    h = get_auth_header(test_organizer)
    await client.patch(f"/events/{test_event.id}", json={"tagline": "trigger an audit row"}, headers=h)
    await db_session.commit()
    row = (await db_session.execute(select(AuditLog).order_by(AuditLog.seq.desc()).limit(1))).scalar_one()
    row.extra_data = {**(row.extra_data or {}), "detail": "tampered"}
    await db_session.commit()

    r = await client.get("/admin/audit/verify", headers=h)
    body = r.json()
    assert r.status_code == 200 and body["valid"] is False
    assert body["broken"]["seq"] == row.seq
    blob = str(body)
    assert "tampered" not in blob and row.action not in blob and row.target_id not in blob
