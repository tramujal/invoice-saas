"""Read-only audit CLI: reports customers that already share a normalized
tax_id within the same organization.

Phase UX5 added application-level tax_id duplicate blocking for NEW
customers (see app.customer_duplicates.find_tax_id_duplicate), but never
touches historical data -- a database that already has pre-existing
duplicate tax ids keeps them exactly as they are (see
docs/customer_duplicate_detection.md's "Migration strategy" section for
why no backfill/cleanup runs automatically). This script is the
recommended way for an operator to find out whether any exist, so they
can be reviewed and merged manually (customer merging is explicitly out
of scope for this phase). It never writes to the database.

Usage (from the repo root, same environment the backend runs in):

    python -m app.scripts.find_duplicate_tax_ids
    python -m app.scripts.find_duplicate_tax_ids --organization-id <id>
"""

from __future__ import annotations

import argparse
from collections import defaultdict

from sqlalchemy import select

from app.customer_validation import normalize_tax_id
from app.database import SessionLocal
from app.models import Customer, Organization, init_db


def find_duplicates(db, organization_id: str | None = None) -> dict[str, dict[str, list[Customer]]]:
    """Returns {organization_id: {normalized_tax_id: [Customer, ...]}} for
    every group of 2+ customers in the same organization sharing a
    normalized tax_id. Never compares across organizations."""
    query = select(Customer).where(Customer.tax_id != "")
    if organization_id:
        query = query.where(Customer.organization_id == organization_id)

    by_org: dict[str, dict[str, list[Customer]]] = defaultdict(lambda: defaultdict(list))
    for customer in db.scalars(query).all():
        norm = normalize_tax_id(customer.tax_id)
        if norm:
            by_org[customer.organization_id][norm].append(customer)

    return {
        org_id: {tax_id: customers for tax_id, customers in groups.items() if len(customers) > 1}
        for org_id, groups in by_org.items()
        if any(len(customers) > 1 for customers in groups.values())
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--organization-id",
        default=None,
        help="Limit the audit to a single organization (default: every organization)",
    )
    args = parser.parse_args()

    init_db()
    db = SessionLocal()
    try:
        duplicates = find_duplicates(db, args.organization_id)
        if not duplicates:
            print("No duplicate tax IDs found.")
            return

        total_groups = sum(len(groups) for groups in duplicates.values())
        print(f"Found {total_groups} duplicate tax id group(s) across {len(duplicates)} organization(s):\n")
        for org_id, groups in duplicates.items():
            organization = db.get(Organization, org_id)
            org_label = organization.name if organization else org_id
            print(f"Organization: {org_label} ({org_id})")
            for norm_tax_id, customers in groups.items():
                print(f"  tax_id (normalized) = {norm_tax_id!r}:")
                for customer in customers:
                    print(f"    - {customer.id}  {customer.name!r}  tax_id={customer.tax_id!r}")
            print()
    finally:
        db.close()


if __name__ == "__main__":
    main()
