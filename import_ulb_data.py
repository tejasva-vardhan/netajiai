"""
Import Urban Local Bodies (ULB) CSV data into State and City master tables.

Usage:
    python import_ulb_data.py --file ulb_data.csv

CSV notes:
    - Expected columns include variants like:
      "State Name", "State", "ULB Name", "City", etc.
    - This script auto-detects state/city columns using common aliases.
"""

from __future__ import annotations

import argparse
import csv
import re
from pathlib import Path
from typing import Dict, Iterable, Optional, Tuple

from sqlalchemy.dialects.postgresql import insert as pg_insert

from database import SessionLocal, engine
from models import Base, City, State


STATE_ALIASES = {
    "state name",
    "state",
    "state_name",
    "statename",
    "st_name",
}

CITY_ALIASES = {
    "ulb name",
    "ulb",
    "city",
    "city name",
    "town",
    "urban local body",
    "urban local body name",
    "name of ulb",
}


def clean_name(value: str) -> str:
    """Normalize basic name casing and spacing."""
    text = re.sub(r"\s+", " ", (value or "").strip())
    if not text:
        return ""
    # Basic title casing with support for acronyms and delimiters.
    parts = re.split(r"([-/()])", text)
    cleaned = []
    for part in parts:
        if part in {"-", "/", "(", ")"}:
            cleaned.append(part)
            continue
        words = []
        for w in part.split(" "):
            if not w:
                continue
            words.append(w if w.isupper() and len(w) <= 4 else w.capitalize())
        cleaned.append(" ".join(words))
    return "".join(cleaned).strip()


def normalize_header(header: str) -> str:
    return re.sub(r"\s+", " ", (header or "").strip().lower())


def resolve_columns(fieldnames: Iterable[str]) -> Tuple[str, str]:
    state_col: Optional[str] = None
    city_col: Optional[str] = None
    for col in fieldnames:
        key = normalize_header(col)
        if state_col is None and key in STATE_ALIASES:
            state_col = col
        if city_col is None and key in CITY_ALIASES:
            city_col = col
    if not state_col or not city_col:
        available = ", ".join(fieldnames)
        raise ValueError(
            "Could not auto-map columns. "
            f"Need state/city columns; found: {available}"
        )
    return state_col, city_col


def parse_csv(path: Path) -> Tuple[set[str], set[Tuple[str, str]], int]:
    states: set[str] = set()
    state_city_pairs: set[Tuple[str, str]] = set()
    skipped_rows = 0

    with path.open("r", encoding="utf-8-sig", newline="") as f:
        reader = csv.DictReader(f)
        if not reader.fieldnames:
            raise ValueError("CSV header missing.")
        state_col, city_col = resolve_columns(reader.fieldnames)

        for row in reader:
            state_name = clean_name(row.get(state_col, ""))
            city_name = clean_name(row.get(city_col, ""))
            if not state_name or not city_name:
                skipped_rows += 1
                continue
            states.add(state_name)
            state_city_pairs.add((state_name, city_name))

    return states, state_city_pairs, skipped_rows


def main() -> None:
    parser = argparse.ArgumentParser(description="Import ULB CSV into states/cities tables")
    parser.add_argument("--file", required=True, help="Path to ULB CSV file")
    args = parser.parse_args()

    csv_path = Path(args.file)
    if not csv_path.exists():
        raise FileNotFoundError(f"CSV file not found: {csv_path}")

    states, state_city_pairs, skipped_rows = parse_csv(csv_path)
    if not states:
        raise RuntimeError("No valid state/city rows found in CSV.")

    Base.metadata.create_all(bind=engine)
    db = SessionLocal()

    inserted_states = 0
    inserted_cities = 0
    try:
        # Insert states with ON CONFLICT DO NOTHING (State.name is unique).
        for state_name in sorted(states):
            stmt = (
                pg_insert(State)
                .values(name=state_name)
                .on_conflict_do_nothing(index_elements=["name"])
            )
            res = db.execute(stmt)
            if (res.rowcount or 0) > 0:
                inserted_states += 1
        db.flush()

        # Resolve state IDs after inserts.
        state_rows = db.query(State).all()
        state_id_by_name: Dict[str, int] = {s.name: s.id for s in state_rows}

        # Existing city keys to avoid duplicates even when DB lacks unique(city,state) constraint.
        existing_city_keys = {
            (c.state_id, clean_name(c.name))
            for c in db.query(City.id, City.state_id, City.name).all()
        }

        # Insert cities with conflict-safe stmt; plus in-memory key guard for practical dedupe.
        for state_name, city_name in sorted(state_city_pairs):
            state_id = state_id_by_name.get(state_name)
            if not state_id:
                continue
            key = (state_id, city_name)
            if key in existing_city_keys:
                continue

            stmt = pg_insert(City).values(name=city_name, state_id=state_id).on_conflict_do_nothing()
            res = db.execute(stmt)
            if (res.rowcount or 0) > 0:
                inserted_cities += 1
                existing_city_keys.add(key)

        db.commit()
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()

    print(f"✅ Successfully inserted {inserted_states} States and {inserted_cities} Cities.")
    print(
        f"ℹ️ Processed {len(state_city_pairs)} unique state-city pairs from CSV; skipped {skipped_rows} invalid rows."
    )


if __name__ == "__main__":
    main()
