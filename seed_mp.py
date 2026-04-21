"""
Seed Madhya Pradesh: 5 major cities × 6 departments (incl. catch-all "default") with a full escalation matrix.

Uses the same SQLAlchemy stack as the app (`database` + `models`).
Run (after DATABASE_URL is set and DB is up):

    py seed_mp.py

Officer emails follow the pattern:
  L1: je.<department>.<city>@mp.gov.in
  L2: commissioner.<city>@mp.gov.in
  L3: secy.<department>.mp@gov.in
"""

from __future__ import annotations

from database import SessionLocal, engine
from models import Base, City, Department, OfficerMapping, State

STATE_NAME = "Madhya Pradesh"

# (display name, email slug — lowercase, no spaces)
CITIES: list[tuple[str, str]] = [
    ("Bhopal", "bhopal"),
    ("Indore", "indore"),
    ("Gwalior", "gwalior"),
    ("Jabalpur", "jabalpur"),
    ("Shivpuri", "shivpuri"),
]

# (display name, routing keyword — must match bot / email_service aliases)
DEPARTMENTS: list[tuple[str, str]] = [
    ("Public Works Department (PWD)", "road"),
    ("Jal Vibhag", "water"),
    ("Electricity Board", "electricity"),
    ("Nagar Nigam Sanitation", "sanitation"),
    ("Swasthya Vibhag (Health)", "health"),
    ("General", "default"),
]


def _l1_email(keyword: str, city_slug: str) -> str:
    return f"je.{keyword}.{city_slug}@mp.gov.in"


def _l2_email(city_slug: str) -> str:
    return f"commissioner.{city_slug}@mp.gov.in"


def _l3_email(keyword: str) -> str:
    return f"secy.{keyword}.mp@gov.in"


def main() -> None:
    Base.metadata.create_all(bind=engine)
    db = SessionLocal()
    try:
        st = db.query(State).filter(State.name == STATE_NAME).first()
        if st is None:
            st = State(name=STATE_NAME)
            db.add(st)
            db.flush()

        resolved_cities: list[tuple[City, str]] = []
        for city_name, city_slug in CITIES:
            city = (
                db.query(City)
                .filter(City.name == city_name, City.state_id == st.id)
                .first()
            )
            if city is None:
                city = City(name=city_name, state_id=st.id)
                db.add(city)
                db.flush()
            resolved_cities.append((city, city_slug))

        resolved_depts: list[Department] = []
        for display_name, keyword in DEPARTMENTS:
            dept = db.query(Department).filter(Department.keyword == keyword).first()
            if dept is None:
                dept = Department(name=display_name, keyword=keyword)
                db.add(dept)
                db.flush()
            resolved_depts.append(dept)

        mp_city_ids = [c.id for c, _ in resolved_cities]
        db.query(OfficerMapping).filter(OfficerMapping.city_id.in_(mp_city_ids)).delete(
            synchronize_session=False
        )

        for city, city_slug in resolved_cities:
            for dept in resolved_depts:
                kw = dept.keyword
                db.add(
                    OfficerMapping(
                        city_id=city.id,
                        department_id=dept.id,
                        level_1_email=_l1_email(kw, city_slug),
                        level_2_email=_l2_email(city_slug),
                        level_3_email=_l3_email(kw),
                    )
                )

        db.commit()
        print("✅ MP Master Database Seeded Successfully with Escalation Matrix!")
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()


if __name__ == "__main__":
    main()
