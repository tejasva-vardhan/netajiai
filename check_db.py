import os

from sqlalchemy import create_engine, inspect

try:
    # Optional, in case python-dotenv is available
    from dotenv import load_dotenv

    # Force .env values to override any existing environment variables
    load_dotenv(override=True)
except Exception:
    # If dotenv isn't installed, we just rely on existing environment vars
    pass


def main() -> None:
    db_url = os.getenv("DATABASE_URL")
    if not db_url:
        print("ERROR: DATABASE_URL is not set in environment or .env file.")
        return

    # Normalize common shorthand URLs for SQLAlchemy
    # e.g. Heroku-style "postgres://..." -> "postgresql+psycopg://..."
    if db_url.startswith("postgres://"):
        db_url = db_url.replace("postgres://", "postgresql+psycopg://", 1)

    print(f"Using DATABASE_URL: {db_url}")
    print("-" * 60)

    engine = create_engine(db_url)
    inspector = inspect(engine)

    # 1. List all tables
    tables = inspector.get_table_names()
    print("Existing tables:")
    for name in tables:
        print(f"  - {name}")

    print("-" * 60)

    # Helper to print columns for a specific table
    def print_table_columns(table_name: str) -> None:
        if table_name not in tables:
            print(f"Table '{table_name}' does NOT exist.")
            print()
            return

        print(f"Columns for table '{table_name}':")
        columns = inspector.get_columns(table_name)
        for col in columns:
            col_name = col.get("name")
            col_type = col.get("type")
            print(f"  - {col_name}: {col_type}")
        print()

    # 2. Users table schema
    print_table_columns("users")

    # 3. Complaints table schema
    print_table_columns("complaints")


if __name__ == "__main__":
    main()

