"""Authentication business logic."""

from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.user import User
from app.models.event import EventRole, EventRoleType
from app.utils.security import (
    get_password_hash,
    verify_password,
    create_access_token,
)


async def create_user(
    db: AsyncSession,
    email: str,
    password: str,
    name: str,
) -> User:
    """Create a new user."""
    # Check if email already exists
    result = await db.execute(select(User).where(User.email == email))
    if result.scalar_one_or_none():
        raise ValueError("Email already registered")

    user = User(
        email=email,
        password_hash=get_password_hash(password),
        name=name,
    )
    db.add(user)
    await db.flush()
    return user


async def authenticate_user(
    db: AsyncSession,
    email: str,
    password: str,
) -> User:
    """Authenticate user with email and password."""
    result = await db.execute(select(User).where(User.email == email))
    user = result.scalar_one_or_none()

    if not user or not verify_password(password, user.password_hash):
        raise ValueError("Invalid email or password")

    return user


def generate_token(user: User) -> str:
    """Generate JWT token for user."""
    return create_access_token(data={"sub": str(user.id), "email": user.email})


async def get_user_roles(
    db: AsyncSession,
    user_id: UUID,
) -> list[EventRole]:
    """Get all event roles for a user."""
    result = await db.execute(
        select(EventRole).where(EventRole.user_id == str(user_id))
    )
    return list(result.scalars().all())
