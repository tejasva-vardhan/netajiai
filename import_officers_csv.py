"""
Import pan-India officer escalation data from CSV into `departments` and `officer_mappings`.

The database stores L1–L3 emails only (roles in the CSV are ignored for persistence;
the routing engine uses `email_service` + `OfficerMapping`).

Requires DATABASE_URL (PostgreSQL) and the CSV produced by `generate_officers_csv.py`.

Usage:
    python import_officers_csv.py --file pan_india_officers.csv
"""

from __future__ import annotations

import argparse
import csv
import sys
from pathlib import Path
from typing import Dict, Set, Tuple

from sqlalchemy.dialects.postgresql import insert as pg_insert

from database import SessionLocal, engine
from models import Base, City, Department, OfficerMapping, State


EXPECTED_HEADERS = [
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


def dept_display_name(keyword: str) -> str:
    kw = keyword.strip().lower()
    if kw == "pwd":
        return "PWD"
    return kw.replace("_", " ").title()


def load_city_index(db) -> Dict[Tuple[str, str], int]:
    """Map (state_name, city_name) -> city_id."""
    rows = (
        db.query(City.id, City.name, State.name)
        .join(State, City.state_id == State.id)
        .all()
    )
    return {(state_name, city_name): cid for cid, city_name, state_name in rows}


def ensure_department(db, keyword: str) -> Department:
    kw = keyword.strip().lower()
    dept = db.query(Department).filter(Department.keyword == kw).first()
    if dept is None:
        dept = Department(name=dept_display_name(kw), keyword=kw)
        db.add(dept)
        db.flush()
    return dept


def upsert_officer_mapping(
    db,
    city_id: int,
    department_id: int,
    level_1_email: str,
    level_2_email: str,
    level_3_email: str,
) -> None:
    stmt = pg_insert(OfficerMapping).values(
        city_id=city_id,
        department_id=department_id,
        level_1_email=level_1_email or None,
        level_2_email=level_2_email or None,
        level_3_email=level_3_email or None,
    )
    stmt = stmt.on_conflict_do_update(
        constraint="uq_city_department",
        set_={
            "level_1_email": stmt.excluded.level_1_email,
            "level_2_email": stmt.excluded.level_2_email,
            "level_3_email": stmt.excluded.level_3_email,
        },
    )
    db.execute(stmt)


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Import officer escalation CSV into departments and officer_mappings",
    )
    parser.add_argument(
        "--file",
        default="pan_india_officers.csv",
        help="Path to CSV (default: pan_india_officers.csv)",
    )
    args = parser.parse_args()

    csv_path = Path(args.file)
    if not csv_path.is_file():
        raise FileNotFoundError(f"CSV file not found: {csv_path.resolve()}")

    Base.metadata.create_all(bind=engine)
    db = SessionLocal()

    rows_processed = 0
    rows_skipped = 0
    cities_touched: Set[int] = set()

    try:
        city_index = load_city_index(db)

        with csv_path.open(newline="", encoding="utf-8") as f:
            reader = csv.DictReader(f)
            if not reader.fieldnames:
                raise ValueError("CSV has no header row.")
            headers = {h.strip() for h in reader.fieldnames}
            missing = [h for h in EXPECTED_HEADERS if h not in headers]
            if missing:
                raise ValueError(
                    f"CSV missing required columns: {missing}. Found: {list(reader.fieldnames)}"
                )

            for row in reader:
                state_name = (row.get("State") or "").strip()
                city_name = (row.get("City") or "").strip()
                dept_key = (row.get("Department") or "").strip().lower()
                l1 = (row.get("L1_Email") or "").strip()
                l2 = (row.get("L2_Email") or "").strip()
                l3 = (row.get("L3_Email") or "").strip()

                if not state_name or not city_name or not dept_key:
                    rows_skipped += 1
                    continue

                city_id = city_index.get((state_name, city_name))
                if city_id is None:
                    rows_skipped += 1
                    continue

                dept = ensure_department(db, dept_key)
                upsert_officer_mapping(db, city_id, dept.id, l1, l2, l3)
                cities_touched.add(city_id)
                rows_processed += 1

        db.commit()
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()

    if hasattr(sys.stdout, "reconfigure"):
        try:
            sys.stdout.reconfigure(encoding="utf-8")
        except Exception:
            pass

    n_cities = len(cities_touched)
    print(
        f"✅ Successfully injected {rows_processed} officer mappings "
        f"across {n_cities} cities."
    )
    if rows_skipped:
        print(f"ℹ️ Skipped {rows_skipped} rows (missing fields or unknown state/city).")


if __name__ == "__main__":
    main()
