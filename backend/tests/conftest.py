"""Test configuration and fixtures."""

import asyncio
import os
from typing import AsyncGenerator

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.database import Base, get_db
from app.main import app
from app.models.user import User
from app.models.event import Event, EventRole, EventRoleType, EventStatus
from app.models.team import Team, TeamMembership, TeamRoleType
from app.models.submission import Submission, SubmissionStatus
from app.models.judging import RubricCriterion, JudgeAssignment
from app.utils.security import get_password_hash, create_access_token


TEST_DATABASE_URL = os.environ.get(
    "TEST_DATABASE_URL",
    "sqlite+aiosqlite:///./test.db",
)

_engine_kwargs = {"echo": False}
if TEST_DATABASE_URL.startswith("postgresql"):
    from sqlalchemy.pool import NullPool
    _engine_kwargs["connect_args"] = {"ssl": False}
    _engine_kwargs["poolclass"] = NullPool

engine = create_async_engine(TEST_DATABASE_URL, **_engine_kwargs)
TestSessionLocal = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)


@pytest.fixture(scope="session")
def event_loop():
    loop = asyncio.get_event_loop_policy().new_event_loop()
    yield loop
    loop.close()


@pytest.fixture(autouse=True)
def _reset_rate_limiter():
    from app.utils.rate_limit import rate_limiter

    rate_limiter.reset()
    yield


@pytest_asyncio.fixture(autouse=True)
async def setup_database():
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    yield
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)


@pytest_asyncio.fixture
async def db_session() -> AsyncGenerator[AsyncSession, None]:
    async with TestSessionLocal() as session:
        yield session
        await session.rollback()


@pytest_asyncio.fixture
async def client(db_session: AsyncSession) -> AsyncGenerator[AsyncClient, None]:
    async def override_get_db():
        yield db_session

    app.dependency_overrides[get_db] = override_get_db

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac

    app.dependency_overrides.clear()


@pytest_asyncio.fixture
async def test_user(db_session: AsyncSession) -> User:
    user = User(
        email="test@example.com",
        name="Test User",
        password_hash=get_password_hash("testpassword123"),
    )
    db_session.add(user)
    await db_session.commit()
    await db_session.refresh(user)
    return user


@pytest_asyncio.fixture
async def test_organizer(db_session: AsyncSession) -> User:
    user = User(
        email="organizer@example.com",
        name="Test Organizer",
        password_hash=get_password_hash("organizer123"),
    )
    db_session.add(user)
    await db_session.commit()
    await db_session.refresh(user)
    return user


@pytest_asyncio.fixture
async def test_judge(db_session: AsyncSession) -> User:
    user = User(
        email="judge@example.com",
        name="Test Judge",
        password_hash=get_password_hash("judge123"),
    )
    db_session.add(user)
    await db_session.commit()
    await db_session.refresh(user)
    return user


@pytest_asyncio.fixture
async def test_event(db_session: AsyncSession, test_organizer: User, test_user: User, test_judge: User) -> Event:
    event = Event(
        organizer_id=test_organizer.id,
        name="Test Hackathon",
        slug="test-hackathon",
        description="A test event",
        status=EventStatus.LIVE,
    )
    db_session.add(event)
    await db_session.commit()
    await db_session.refresh(event)

    roles = [
        EventRole(user_id=test_organizer.id, event_id=event.id, role=EventRoleType.ORGANIZER),
        EventRole(user_id=test_user.id, event_id=event.id, role=EventRoleType.PARTICIPANT),
        EventRole(user_id=test_judge.id, event_id=event.id, role=EventRoleType.JUDGE),
    ]
    db_session.add_all(roles)
    await db_session.commit()

    return event


@pytest_asyncio.fixture
async def test_team(db_session: AsyncSession, test_event: Event, test_user: User) -> Team:
    team = Team(
        event_id=test_event.id,
        name="Test Team",
        invite_code="testinvite123",
    )
    db_session.add(team)
    await db_session.commit()
    await db_session.refresh(team)

    membership = TeamMembership(
        team_id=team.id,
        user_id=test_user.id,
        role_in_team=TeamRoleType.LEADER,
    )
    db_session.add(membership)
    await db_session.commit()

    return team


@pytest_asyncio.fixture
async def test_submission(db_session: AsyncSession, test_team: Team, test_event: Event) -> Submission:
    submission = Submission(
        team_id=test_team.id,
        event_id=test_event.id,
        name="Test Submission",
        tagline="A test submission",
        status=SubmissionStatus.SUBMITTED,
    )
    db_session.add(submission)
    await db_session.commit()
    await db_session.refresh(submission)
    return submission


def get_auth_header(user: User) -> dict:
    token = create_access_token({"sub": str(user.id), "email": user.email})
    return {"Authorization": f"Bearer {token}"}
