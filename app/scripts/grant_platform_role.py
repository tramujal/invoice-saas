"""One-off CLI for bootstrapping platform administrator access.

Platform roles can't be granted through the API -- there's no one with
platform.roles.manage to call it yet on a fresh install. Run this
directly against the database instead, analogous to Django's
createsuperuser.

Usage (from the repo root, same environment the backend runs in):

    python -m app.scripts.grant_platform_role someone@example.com
    python -m app.scripts.grant_platform_role someone@example.com --revoke
"""

from __future__ import annotations

import argparse
import sys

from sqlalchemy import select

from app.database import SessionLocal
from app.models import User, init_db
from app.platform_permissions import PlatformRole


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("email", help="Email of the user to grant/revoke platform admin access")
    parser.add_argument(
        "--revoke",
        action="store_true",
        help="Revoke platform admin access instead of granting it",
    )
    args = parser.parse_args()

    init_db()
    db = SessionLocal()
    try:
        user = db.scalar(select(User).where(User.email == args.email))
        if user is None:
            print(f"No user found with email {args.email!r}.", file=sys.stderr)
            sys.exit(1)

        if args.revoke:
            user.platform_role = None
            db.commit()
            print(f"Revoked platform admin access from {args.email}.")
        else:
            user.platform_role = PlatformRole.super_admin.value
            db.commit()
            print(f"Granted platform admin access ({PlatformRole.super_admin.value}) to {args.email}.")
    finally:
        db.close()


if __name__ == "__main__":
    main()
