"""
Populate India geography master data (states + major ULB cities) into PostgreSQL.

Why this script:
- LGD and some government APIs may require auth keys / registration.
- This script provides a reliable fallback with a structured India-wide dataset
  (28 states x top 3 cities), while still supporting CSV ingestion.

Run:
    py fetch_lgd_cities.py

Optional CSV mode:
    py fetch_lgd_cities.py --csv path/to/states_cities.csv

Expected CSV headers:
    state,city
"""

from __future__ import annotations

import argparse
import csv
from pathlib import Path

from database import SessionLocal, engine
from models import Base, City, State

# 28 Indian states (excludes UTs), each with 3 major ULB cities.
INDIA_STATE_CITY_DATA: dict[str, list[str]] = {
    "Andhra Pradesh": ["Visakhapatnam", "Vijayawada", "Guntur"],
    "Arunachal Pradesh": ["Itanagar", "Naharlagun", "Pasighat"],
    "Assam": ["Guwahati", "Silchar", "Dibrugarh"],
    "Bihar": ["Patna", "Gaya", "Bhagalpur"],
    "Chhattisgarh": ["Raipur", "Bhilai", "Bilaspur"],
    "Goa": ["Panaji", "Margao", "Mapusa"],
    "Gujarat": ["Ahmedabad", "Surat", "Vadodara"],
    "Haryana": ["Faridabad", "Gurgaon", "Panipat"],
    "Himachal Pradesh": ["Shimla", "Dharamshala", "Solan"],
    "Jharkhand": ["Ranchi", "Jamshedpur", "Dhanbad"],
    "Karnataka": ["Bangalore", "Mysore", "Mangalore"],
    "Kerala": ["Thiruvananthapuram", "Kochi", "Kozhikode"],
    "Madhya Pradesh": ["Bhopal", "Indore", "Jabalpur"],
    "Maharashtra": ["Mumbai", "Pune", "Nagpur"],
    "Manipur": ["Imphal", "Thoubal", "Bishnupur"],
    "Meghalaya": ["Shillong", "Tura", "Jowai"],
    "Mizoram": ["Aizawl", "Lunglei", "Saiha"],
    "Nagaland": ["Kohima", "Dimapur", "Mokokchung"],
    "Odisha": ["Bhubaneswar", "Cuttack", "Rourkela"],
    "Punjab": ["Ludhiana", "Amritsar", "Jalandhar"],
    "Rajasthan": ["Jaipur", "Jodhpur", "Kota"],
    "Sikkim": ["Gangtok", "Namchi", "Gyalshing"],
    "Tamil Nadu": ["Chennai", "Coimbatore", "Madurai"],
    "Telangana": ["Hyderabad", "Warangal", "Nizamabad"],
    "Tripura": ["Agartala", "Udaipur", "Dharmanagar"],
    "Uttar Pradesh": ["Lucknow", "Kanpur", "Varanasi"],
    "Uttarakhand": ["Dehradun", "Haridwar", "Haldwani"],
    "West Bengal": ["Kolkata", "Howrah", "Durgapur"],
}


def _load_pairs_from_csv(path: Path) -> dict[str, list[str]]:
    data: dict[str, list[str]] = {}
    with path.open("r", encoding="utf-8", newline="") as f:
        reader = csv.DictReader(f)
        if not reader.fieldnames:
            raise ValueError("CSV has no headers. Expected headers: state,city")
        headers = {h.strip().lower() for h in reader.fieldnames if h}
        if "state" not in headers or "city" not in headers:
            raise ValueError("CSV must include headers: state,city")

        for row in reader:
            state = (row.get("state") or "").strip()
            city = (row.get("city") or "").strip()
            if not state or not city:
                continue
            data.setdefault(state, [])
            if city not in data[state]:
                data[state].append(city)
    return data


def seed_states_and_cities(data: dict[str, list[str]]) -> tuple[int, int]:
    Base.metadata.create_all(bind=engine)
    db = SessionLocal()
    inserted_states = 0
    inserted_cities = 0
    try:
        existing_states = {s.name: s for s in db.query(State).all()}

        for state_name, cities in data.items():
            st = existing_states.get(state_name)
            if st is None:
                st = State(name=state_name)
                db.add(st)
                db.flush()
                existing_states[state_name] = st
                inserted_states += 1

            existing_city_names = {
                c.name for c in db.query(City).filter(City.state_id == st.id).all()
            }
            for city_name in cities:
                if city_name in existing_city_names:
                    continue
                db.add(City(name=city_name, state_id=st.id))
                inserted_cities += 1
                existing_city_names.add(city_name)

        db.commit()
        return inserted_states, inserted_cities
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()


def main() -> None:
    parser = argparse.ArgumentParser(description="Fetch/seed India state-city master data")
    parser.add_argument(
        "--csv",
        type=str,
        default="",
        help="Optional CSV path with headers: state,city",
    )
    args = parser.parse_args()

    if args.csv:
        csv_path = Path(args.csv)
        if not csv_path.exists():
            raise FileNotFoundError(f"CSV not found: {csv_path}")
        data = _load_pairs_from_csv(csv_path)
        mode = f"CSV ({csv_path})"
    else:
        data = INDIA_STATE_CITY_DATA
        mode = "embedded India dataset (28 states x top 3 cities)"

    states_inserted, cities_inserted = seed_states_and_cities(data)
    print(f"✅ Source: {mode}")
    print(
        f"✅ Successfully inserted {states_inserted} States and {cities_inserted} Cities."
    )


if __name__ == "__main__":
    main()
