"""Seed script for DOGFOOD hackathon platform."""

import asyncio
import secrets
from datetime import datetime, timedelta, timezone

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import async_session_factory, init_db
from app.models.user import User
from app.models.event import Event, Track, EventRole, EventStatus, EventRoleType
from app.models.team import Team, TeamMembership, TeamRoleType
from app.models.submission import Submission, SubmissionStatus
from app.models.judging import RubricCriterion, JudgeAssignment, Score
from app.models.voting import Vote, Comment
from app.config import settings
from app.services.fixture_import import (
    checker_plan,
    import_fixtures,
    load_fixtures,
)
from app.services.stable_ids import user_id_for_email
from app.utils.security import create_checker_token, get_password_hash


def print_checker_identities(data: dict) -> None:
    """Print ready-to-paste [auth]/[routes] values for the DOGFOOD checker.

    Everything here is deterministic (stable ids + fixed-expiry tokens), so the
    values are identical on every boot and match the committed .dogfood.toml.
    """
    plan = checker_plan(data)

    def header(email: str) -> str:
        token = create_checker_token(user_id_for_email(email), email)
        return f"Authorization: Bearer {token}"

    print("=== DOGFOOD CHECKER IDENTITIES ===")
    print("[auth]")
    print(f'organizer   = "{header(plan["organizer_email"])}"')
    print(f'judge_a     = "{header(plan["judge_a_email"])}"')
    print(f'judge_b     = "{header(plan["judge_b_email"])}"')
    print(f'participant = "{header(plan["participant_email"])}"')
    print("[routes]")
    print(f'gallery      = "/events/{plan["event_id"]}/submissions"')
    print(f'submit       = "/teams/{plan["probe_team_id"]}/submissions"')
    print(f'judge_scores = "/submissions/{plan["project_id"]}/scores/mine"')
    print(f'peer_scores  = "/submissions/{plan["project_id"]}/scores"')
    print(f'csv_export   = "/events/{plan["event_id"]}/judging/export.csv"')
    print("=== END CHECKER IDENTITIES ===")


async def seed_fixtures() -> None:
    """Load fixtures.json (if present) and print the checker identities."""
    data = load_fixtures(settings.FIXTURES_PATH)
    if data is None:
        print(f"No fixtures file at {settings.FIXTURES_PATH}; skipping fixture import.")
        return
    async with async_session_factory() as db:
        summary = await import_fixtures(db, data)
    if summary is None:
        print("Fixtures already imported, skipping...")
    else:
        print(f"Fixtures imported: {summary}")
    print_checker_identities(data)


async def seed_data():
    """Seed demo data, then the DOGFOOD fixtures."""
    await init_db()
    await seed_demo_data()
    await seed_fixtures()


async def seed_demo_data():
    """Seed the database with the demo event/users (once)."""
    async with async_session_factory() as db:
        # Check if data already exists
        result = await db.execute(select(User).limit(1))
        if result.scalar_one_or_none():
            print("Database already seeded, skipping...")
            return

        print("Seeding database...")

        # Create users
        users = []
        user_data = [
            ("admin@dogfoodhack.com", "Admin User", "admin123"),
            ("organizer@dogfoodhack.com", "Event Organizer", "organizer123"),
            ("judge1@dogfoodhack.com", "Judge One", "judge123"),
            ("judge2@dogfoodhack.com", "Judge Two", "judge123"),
            ("judge3@dogfoodhack.com", "Judge Three", "judge123"),
            ("participant1@dogfoodhack.com", "Alice Participant", "participant123"),
            ("participant2@dogfoodhack.com", "Bob Participant", "participant123"),
            ("participant3@dogfoodhack.com", "Charlie Participant", "participant123"),
            ("participant4@dogfoodhack.com", "Diana Participant", "participant123"),
            ("participant5@dogfoodhack.com", "Eve Participant", "participant123"),
            ("participant6@dogfoodhack.com", "Frank Participant", "participant123"),
        ]

        for email, name, password in user_data:
            user = User(
                id=user_id_for_email(email),
                email=email,
                name=name,
                password_hash=get_password_hash(password),
            )
            db.add(user)
            users.append(user)

        await db.flush()

        # Create event
        now = datetime.now(timezone.utc)
        event = Event(
            organizer_id=users[1].id,  # organizer
            name="DOGFOOD Hackathon 2024",
            slug="dogfood-hackathon-2024",
            description="Build the future of hackathon platforms!",
            start_date=now - timedelta(days=7),
            end_date=now + timedelta(days=7),
            submission_deadline=now + timedelta(days=3),
            judging_opens_at=now + timedelta(days=3),
            judging_closes_at=now + timedelta(days=5),
            voting_opens_at=now + timedelta(days=5),
            voting_closes_at=now + timedelta(days=7),
            status=EventStatus.LIVE,
        )
        db.add(event)
        await db.flush()

        # Create tracks
        tracks = []
        track_names = ["AI/ML", "Web3", "Sustainability", "Open Track"]
        for name in track_names:
            track = Track(
                event_id=event.id,
                name=name,
                description=f"Track for {name} projects",
            )
            db.add(track)
            tracks.append(track)

        await db.flush()

        # Create event roles
        # Admin role
        db.add(EventRole(user_id=users[0].id, event_id=event.id, role=EventRoleType.ADMIN))
        # Organizer role
        db.add(EventRole(user_id=users[1].id, event_id=event.id, role=EventRoleType.ORGANIZER))
        # Judge roles
        for i in range(2, 5):
            db.add(EventRole(user_id=users[i].id, event_id=event.id, role=EventRoleType.JUDGE))
        # Participant roles
        for i in range(5, 11):
            db.add(EventRole(user_id=users[i].id, event_id=event.id, role=EventRoleType.PARTICIPANT))

        await db.flush()

        # Create teams
        teams = []
        team_data = [
            ("AI Wizards", users[5].id, [users[5].id, users[6].id]),
            ("Web3 Warriors", users[7].id, [users[7].id, users[8].id]),
            ("Green Tech", users[9].id, [users[9].id, users[10].id]),
        ]

        for team_name, leader_id, member_ids in team_data:
            team = Team(
                event_id=event.id,
                name=team_name,
                invite_code=secrets.token_hex(16),
            )
            db.add(team)
            await db.flush()

            # Add members
            for idx, member_id in enumerate(member_ids):
                membership = TeamMembership(
                    team_id=team.id,
                    user_id=member_id,
                    role_in_team=TeamRoleType.LEADER if idx == 0 else TeamRoleType.MEMBER,
                )
                db.add(membership)

            teams.append(team)

        await db.flush()

        # Create submissions
        submissions = []
        submission_data = [
            ("AI Health Monitor", "Real-time health tracking with AI", teams[0].id, tracks[0].id),
            ("DeFi Dashboard", "Decentralized finance made simple", teams[1].id, tracks[1].id),
            ("Carbon Tracker", "Track your carbon footprint", teams[2].id, tracks[2].id),
        ]

        for name, tagline, team_id, track_id in submission_data:
            submission = Submission(
                team_id=team_id,
                event_id=event.id,
                track_id=track_id,
                name=name,
                tagline=tagline,
                description_md=f"# {name}\n\nThis is a sample submission for {name}.",
                status=SubmissionStatus.SUBMITTED,
                submitted_at=now - timedelta(days=1),
                tech_tags=["python", "fastapi", "react"],
            )
            db.add(submission)
            submissions.append(submission)

        await db.flush()

        # Create rubric criteria
        criteria = []
        criteria_data = [
            ("Innovation", "How innovative is the solution?", 1.0, 1.0, 10.0),
            ("Technical Excellence", "Quality of implementation", 1.5, 1.0, 10.0),
            ("Impact", "Potential real-world impact", 1.0, 1.0, 10.0),
            ("Presentation", "Quality of demo and documentation", 0.5, 1.0, 10.0),
        ]

        for name, desc, weight, scale_min, scale_max in criteria_data:
            criterion = RubricCriterion(
                event_id=event.id,
                name=name,
                description=desc,
                weight=weight,
                scale_min=scale_min,
                scale_max=scale_max,
            )
            db.add(criterion)
            criteria.append(criterion)

        await db.flush()

        # Create judge assignments
        judges = users[2:5]  # judges
        for judge in judges:
            for submission in submissions:
                assignment = JudgeAssignment(
                    judge_id=judge.id,
                    submission_id=submission.id,
                    status="pending",
                )
                db.add(assignment)

        await db.flush()

        # Create some sample scores
        for judge in judges[:2]:  # Only first 2 judges score
            for submission in submissions[:2]:  # Only first 2 submissions
                for criterion in criteria:
                    score = Score(
                        judge_id=judge.id,
                        submission_id=submission.id,
                        criterion_id=criterion.id,
                        raw_value=7.5,  # Sample score
                        comment="Good work!",
                    )
                    db.add(score)

        # Create some votes
        for submission in submissions:
            for i in range(5):
                vote = Vote(
                    submission_id=submission.id,
                    event_id=submission.event_id,
                    voter_fingerprint=f"fingerprint_{submission.id}_{i}",
                )
                db.add(vote)

        # Create some comments
        for submission in submissions:
            comment = Comment(
                submission_id=submission.id,
                author_id=users[5].id,
                body="Great project! Love the innovation.",
            )
            db.add(comment)

        await db.commit()
        print("Database seeded successfully!")


if __name__ == "__main__":
    asyncio.run(seed_data())
