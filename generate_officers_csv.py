"""
Generate a dummy pan-India escalation matrix CSV from all cities in the database.

Requires DATABASE_URL in .env (PostgreSQL).

Usage:
    python generate_officers_csv.py
"""

from __future__ import annotations

import csv
import re
from pathlib import Path

from database import SessionLocal
from models import City, State

OUTPUT_FILE = Path(__file__).resolve().parent / "pan_india_officers.csv"

DEPARTMENTS = [
    "sanitation",
    "water",
    "pwd",
    "electricity",
    "encroachment",
    "horticulture",
    "health",
    "revenue",
]

HEADERS = [
    "State",
    "City",
    "Department",
    "L1_Role",
    "L1_Email",
    "L2_Role",
    "L2_Email",
    "L3_Role",
    "L3_Email",
]


def email_slug(value: str) -> str:
    """Lowercase; strip spaces and non-alphanumeric characters for email local parts."""
    text = (value or "").lower()
    slug = re.sub(r"[^a-z0-9]", "", text)
    return slug or "unknown"


def dept_title(dept: str) -> str:
    """Human-readable department fragment for role strings."""
    if dept == "pwd":
        return "PWD"
    return dept.replace("_", " ").title()


def main() -> None:
    db = SessionLocal()
    try:
        pairs = (
            db.query(City, State)
            .join(State, City.state_id == State.id)
            .order_by(State.name, City.name)
            .all()
        )
    finally:
        db.close()

    rows_written = 0
    with OUTPUT_FILE.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=HEADERS)
        writer.writeheader()

        for city, state in pairs:
            state_display = state.name
            city_display = city.name
            state_s = email_slug(state.name)
            city_s = email_slug(city.name)

            l2_role = "Municipal Commissioner"
            l2_email = f"commissioner.{city_s}@{state_s}.gov.in"

            for dept in DEPARTMENTS:
                d = dept_title(dept)
                dept_s = email_slug(dept)

                l1_role = f"Junior Engineer - {d}"
                l1_email = f"je.{dept_s}.{city_s}@{state_s}.gov.in"
                l3_role = f"Principal Secretary - {d}"
                l3_email = f"secy.{dept_s}@{state_s}.gov.in"

                writer.writerow(
                    {
                        "State": state_display,
                        "City": city_display,
                        "Department": dept,
                        "L1_Role": l1_role,
                        "L1_Email": l1_email,
                        "L2_Role": l2_role,
                        "L2_Email": l2_email,
                        "L3_Role": l3_role,
                        "L3_Email": l3_email,
                    }
                )
                rows_written += 1

    print(
        f"Success: wrote {rows_written} rows to {OUTPUT_FILE.name} "
        f"({len(pairs)} cities × {len(DEPARTMENTS)} departments)."
    )


if __name__ == "__main__":
    main()
