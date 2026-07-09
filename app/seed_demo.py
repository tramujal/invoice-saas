"""Create one demo user, organization, and membership (idempotent)."""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.database import SessionLocal
from app.models import Organization, OrganizationMember, User, init_db

DEMO_USER_ID = "11111111-1111-1111-1111-111111111111"
DEMO_ORG_ID = "22222222-2222-2222-2222-222222222222"
DEMO_USER_EMAIL = "demo@example.com"
DEMO_ORG_NAME = "Demo Organization"


def seed(session: Session) -> None:
    user = session.get(User, DEMO_USER_ID)
    if user is None:
        session.add(User(id=DEMO_USER_ID, email=DEMO_USER_EMAIL))

    org = session.get(Organization, DEMO_ORG_ID)
    if org is None:
        session.add(Organization(id=DEMO_ORG_ID, name=DEMO_ORG_NAME))

    session.flush()

    member = session.scalar(
        select(OrganizationMember).where(
            OrganizationMember.user_id == DEMO_USER_ID,
            OrganizationMember.organization_id == DEMO_ORG_ID,
        )
    )
    if member is None:
        session.add(
            OrganizationMember(
                user_id=DEMO_USER_ID,
                organization_id=DEMO_ORG_ID,
            )
        )

    session.commit()


def main() -> None:
    init_db()
    db = SessionLocal()
    try:
        seed(db)
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()
    print(f"Seed OK. user_id={DEMO_USER_ID} org_id={DEMO_ORG_ID}")


if __name__ == "__main__":
    main()
