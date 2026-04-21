"""
Populate PostgreSQL with multi-city geography + officer routing for testing.

Run (after DB is up and DATABASE_URL is set):
    py seed.py
"""

from __future__ import annotations

from database import SessionLocal, engine
from models import Base, City, Department, OfficerMapping, State

# (state_name, city_name, slug for dummy email addresses)
TOP_CITIES: list[tuple[str, str, str]] = [
    ("Maharashtra", "Mumbai", "mumbai"),
    ("Delhi", "Delhi", "delhi"),
    ("Karnataka", "Bangalore", "bangalore"),
    ("Madhya Pradesh", "Indore", "indore"),
    ("Madhya Pradesh", "Bhopal", "bhopal"),
    ("Madhya Pradesh", "Shivpuri", "shivpuri"),
    ("Maharashtra", "Pune", "pune"),
    ("Telangana", "Hyderabad", "hyderabad"),
    ("Tamil Nadu", "Chennai", "chennai"),
    ("West Bengal", "Kolkata", "kolkata"),
    ("Pan-India", "General India Helpdesk", "general"),
]

# (display_name, keyword) — same departments in every city for predictable routing tests
DEPARTMENTS: list[tuple[str, str]] = [
    ("Public Works Department (PWD)", "road"),
    ("Jal Vibhag", "water"),
    ("Electricity Board", "electricity"),
    ("Nagar Nigam Sanitation", "sanitation"),
]


def _email_for(keyword: str, slug: str) -> str:
    return f"{keyword}.{slug}@demo.aineta.local"


def seed() -> None:
    Base.metadata.create_all(bind=engine)
    db = SessionLocal()
    try:
        state_by_name: dict[str, State] = {}

        def get_state(name: str) -> State:
            if name not in state_by_name:
                st = db.query(State).filter(State.name == name).first()
                if not st:
                    st = State(name=name)
                    db.add(st)
                    db.flush()
                state_by_name[name] = st
            return state_by_name[name]

        for state_name, city_name, _slug in TOP_CITIES:
            get_state(state_name)

        db.flush()

        for state_name, city_name, slug in TOP_CITIES:
            st = get_state(state_name)
            city = (
                db.query(City)
                .filter(City.name == city_name, City.state_id == st.id)
                .first()
            )
            if not city:
                city = City(name=city_name, state_id=st.id)
                db.add(city)
                db.flush()

            for dept_name, keyword in DEPARTMENTS:
                dept = db.query(Department).filter(Department.keyword == keyword).first()
                if not dept:
                    dept = Department(name=dept_name, keyword=keyword)
                    db.add(dept)
                    db.flush()

                l1 = _email_for(keyword, slug)
                l2 = f"{keyword}.{slug}.l2@demo.aineta.local"
                l3 = f"{keyword}.{slug}.l3@demo.aineta.local"
                existing = (
                    db.query(OfficerMapping)
                    .filter(
                        OfficerMapping.city_id == city.id,
                        OfficerMapping.department_id == dept.id,
                    )
                    .first()
                )
                if existing:
                    existing.level_1_email = l1
                    existing.level_2_email = l2
                    existing.level_3_email = l3
                    db.add(existing)
                else:
                    db.add(
                        OfficerMapping(
                            city_id=city.id,
                            department_id=dept.id,
                            level_1_email=l1,
                            level_2_email=l2,
                            level_3_email=l3,
                        )
                    )

        db.commit()
        print(f"✅ Seed complete: {len(TOP_CITIES)} cities + officer mappings (4 departments each).")
    except Exception as exc:
        db.rollback()
        print(f"❌ Seed failed: {exc}")
        raise
    finally:
        db.close()


if __name__ == "__main__":
    seed()
