"""FastAPI dependencies for authentication and authorization."""

from typing import Optional
from uuid import UUID

from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.models.user import User
from app.models.event import EventRole, EventRoleType
from app.utils.security import decode_access_token

security = HTTPBearer(auto_error=False, scheme_name="BearerAuth")


async def get_current_user(
    credentials: Optional[HTTPAuthorizationCredentials] = Depends(security),
    db: AsyncSession = Depends(get_db),
) -> User:
    """Extract and validate current user from JWT token."""
    if not credentials:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Not authenticated",
            headers={"WWW-Authenticate": "Bearer"},
        )

    payload = decode_access_token(credentials.credentials)
    if not payload:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or expired token",
            headers={"WWW-Authenticate": "Bearer"},
        )

    user_id = payload.get("sub")
    if not user_id:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid token payload",
        )

    result = await db.execute(select(User).where(User.id == user_id))
    user = result.scalar_one_or_none()

    if not user:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="User not found",
        )

    return user


async def get_current_user_optional(
    credentials: Optional[HTTPAuthorizationCredentials] = Depends(security),
    db: AsyncSession = Depends(get_db),
) -> Optional[User]:
    """Extract current user if authenticated, None otherwise."""
    if not credentials:
        return None

    try:
        payload = decode_access_token(credentials.credentials)
        if not payload:
            return None

        user_id = payload.get("sub")
        if not user_id:
            return None

        result = await db.execute(select(User).where(User.id == user_id))
        return result.scalar_one_or_none()
    except Exception:
        return None


async def is_global_admin(db: AsyncSession, user_id) -> bool:
    """Site admin = holds the ADMIN role in any event (the role every permission check accepts everywhere)."""
    row = await db.execute(select(EventRole.id).where(EventRole.user_id == str(user_id), EventRole.role == EventRoleType.ADMIN))
    return row.first() is not None


async def hide_draft_event(db: AsyncSession, event_id, user: Optional[User]) -> None:
    """404 for a *draft* event unless the caller organizes it (or is an admin). Unknown ids are left to the route."""
    from app.models.event import Event, EventStatus

    row = (await db.execute(select(Event.status).where(Event.id == str(event_id)))).first()
    if row is None or row[0] != EventStatus.DRAFT:
        return
    if user is not None:
        if await is_global_admin(db, user.id):
            return
        staff = await db.execute(select(EventRole.id).where(
            EventRole.event_id == str(event_id), EventRole.user_id == str(user.id),
            EventRole.role.in_([EventRoleType.ORGANIZER, EventRoleType.ADMIN])))
        if staff.first() is not None:
            return
    raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Event not found")


def require_role(allowed: list[str]):
    """
    Factory for role-checking dependency that uses event_id from route path.

    Returns a dependency that checks if the current user has one of the allowed roles
    for the given event. Admin role is always allowed.
    """
    async def role_checker(
        event_id: UUID,
        current_user: User = Depends(get_current_user),
        db: AsyncSession = Depends(get_db),
    ) -> User:
        admin_check = await db.execute(
            select(EventRole).where(
                EventRole.user_id == current_user.id,
                EventRole.role == EventRoleType.ADMIN,
            )
        )
        if admin_check.first():
            return current_user

        # A user may hold several roles in one event (e.g. judge + participant).
        result = await db.execute(
            select(EventRole).where(
                EventRole.user_id == current_user.id,
                EventRole.event_id == str(event_id),
            )
        )
        held = {r.role.value for r in result.scalars().all()}

        if not held.intersection(allowed):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"Required role: {allowed}",
            )

        return current_user

    return role_checker


def require_submission_role(allowed: list[str]):
    """
    Like ``require_role`` but for routes keyed by ``submission_id``.

    The role is checked against the event that owns the submission, so being a
    judge/organizer of event A grants nothing on event B's submissions.
    Global admin is always allowed.
    """
    async def submission_role_checker(
        submission_id: UUID,
        current_user: User = Depends(get_current_user),
        db: AsyncSession = Depends(get_db),
    ) -> User:
        from app.models.submission import Submission

        admin_check = await db.execute(
            select(EventRole).where(
                EventRole.user_id == current_user.id,
                EventRole.role == EventRoleType.ADMIN,
            )
        )
        if admin_check.first():
            return current_user

        sub = await db.execute(
            select(Submission.event_id).where(Submission.id == str(submission_id))
        )
        event_id = sub.scalar_one_or_none()
        if event_id is None:
            # Same answer as "not allowed" so ids can't be probed.
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"Required role: {allowed}",
            )

        result = await db.execute(
            select(EventRole).where(
                EventRole.user_id == current_user.id,
                EventRole.event_id == event_id,
            )
        )
        held = {r.role.value for r in result.scalars().all()}
        if not held.intersection(allowed):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"Required role: {allowed}",
            )
        return current_user

    return submission_role_checker


def require_role_global(allowed: list[str]):
    """
    Factory for role-checking dependency WITHOUT event_id.

    For routes that don't have event_id in the path (e.g., /admin/audit, /teams/{id}/submissions).
    Checks global admin role OR if user has any event role of the allowed type.
    """
    async def global_role_checker(
        current_user: User = Depends(get_current_user),
        db: AsyncSession = Depends(get_db),
    ) -> User:
        admin_check = await db.execute(
            select(EventRole).where(
                EventRole.user_id == current_user.id,
                EventRole.role == EventRoleType.ADMIN,
            )
        )
        if admin_check.first():
            return current_user

        if not allowed:
            return current_user

        role_check = await db.execute(
            select(EventRole).where(
                EventRole.user_id == current_user.id,
                EventRole.role.in_([EventRoleType(r) for r in allowed]),
            )
        )
        if role_check.first():
            return current_user

        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=f"Required role: {allowed}",
        )

    return global_role_checker


async def require_auth(
    current_user: User = Depends(get_current_user),
) -> User:
    """Simple authentication requirement (any authenticated user)."""
    return current_user
