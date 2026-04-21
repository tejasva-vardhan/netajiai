from __future__ import annotations

import os
from typing import Generator

from dotenv import load_dotenv
from sqlalchemy import create_engine, inspect, text
from sqlalchemy.exc import ProgrammingError
from sqlalchemy.orm import sessionmaker, DeclarativeBase, Session


load_dotenv(override=True)


class Base(DeclarativeBase):
    """Base class for all SQLAlchemy models."""


def get_database_url() -> str:
    """
    Fetch the PostgreSQL connection URL from the environment.

    Production (e.g. Render managed Postgres): set DATABASE_URL to the provider URL,
    typically including TLS (e.g. `?sslmode=require`). Never commit real URLs.
    """
    db_url = os.getenv("DATABASE_URL")
    if not db_url:
        raise RuntimeError(
            "DATABASE_URL is not set. Please configure it in your environment."
        )
    # Normalize common PostgreSQL URL variants
    # e.g. "postgres://..." -> "postgresql+psycopg://..."
    if db_url.startswith("postgres://"):
        db_url = "postgresql+psycopg://" + db_url[len("postgres://") :]
    elif db_url.startswith("postgresql://") and "+psycopg" not in db_url:
        db_url = "postgresql+psycopg://" + db_url[len("postgresql://") :]
    elif db_url.startswith("postgresql+psycopg2://"):
        db_url = "postgresql+psycopg://" + db_url[len("postgresql+psycopg2://") :]

    return db_url


DATABASE_URL = get_database_url()

engine = create_engine(
    DATABASE_URL,
    pool_pre_ping=True,
)


def apply_schema_patches() -> None:
    """
    Add columns missing from DBs created before models gained those fields.
    SQLAlchemy create_all() does not ALTER existing tables.
    """
    insp = inspect(engine)
    dialect = engine.dialect.name
    if dialect not in ("postgresql", "sqlite"):
        return

    tables = insp.get_table_names()
    if "complaints" not in tables or "cities" not in tables:
        return

    col_names = {c["name"] for c in insp.get_columns("complaints")}

    with engine.begin() as conn:
        if "city_id" not in col_names:
            if dialect == "postgresql":
                conn.execute(
                    text("ALTER TABLE complaints ADD COLUMN city_id INTEGER NULL")
                )
                try:
                    conn.execute(
                        text(
                            "ALTER TABLE complaints ADD CONSTRAINT complaints_city_id_fkey "
                            "FOREIGN KEY (city_id) REFERENCES cities(id) ON DELETE SET NULL"
                        )
                    )
                except ProgrammingError as exc:
                    msg = str(exc.orig) if getattr(exc, "orig", None) else str(exc)
                    if "already exists" not in msg.lower():
                        raise
                conn.execute(
                    text(
                        "CREATE INDEX IF NOT EXISTS ix_complaints_city_id ON complaints (city_id)"
                    )
                )
            else:
                conn.execute(
                    text(
                        "ALTER TABLE complaints ADD COLUMN city_id INTEGER "
                        "REFERENCES cities(id) ON DELETE SET NULL"
                    )
                )

        # Refresh column set if we added city_id
        if "latitude" not in col_names:
            typ = "DOUBLE PRECISION" if dialect == "postgresql" else "REAL"
            conn.execute(text(f"ALTER TABLE complaints ADD COLUMN latitude {typ} NULL"))

        if "longitude" not in col_names:
            typ = "DOUBLE PRECISION" if dialect == "postgresql" else "REAL"
            conn.execute(text(f"ALTER TABLE complaints ADD COLUMN longitude {typ} NULL"))

        if "severity" not in col_names:
            conn.execute(
                text(
                    "ALTER TABLE complaints ADD COLUMN severity VARCHAR(50) NOT NULL DEFAULT 'normal'"
                )
            )
        if "escalation_level" not in col_names:
            conn.execute(
                text(
                    "ALTER TABLE complaints ADD COLUMN escalation_level INTEGER NOT NULL DEFAULT 1"
                )
            )
        # Guest complaints support: allow NULL user_id.
        try:
            if dialect == "postgresql":
                conn.execute(text("ALTER TABLE complaints ALTER COLUMN user_id DROP NOT NULL"))
        except Exception:
            pass

    if "users" in tables:
        user_cols = {c["name"] for c in insp.get_columns("users")}
        with engine.begin() as conn:
            if "email" not in user_cols:
                conn.execute(text("ALTER TABLE users ADD COLUMN email VARCHAR(255) NULL"))
            if "created_at" not in user_cols:
                if dialect == "postgresql":
                    conn.execute(
                        text(
                            "ALTER TABLE users ADD COLUMN created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()"
                        )
                    )
                else:
                    conn.execute(
                        text(
                            "ALTER TABLE users ADD COLUMN created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP"
                        )
                    )
            if dialect == "postgresql":
                conn.execute(
                    text("CREATE UNIQUE INDEX IF NOT EXISTS ix_users_email ON users (email)")
                )
                # Legacy compatibility: allow null user_id for new email-first users.
                try:
                    conn.execute(text("ALTER TABLE users ALTER COLUMN user_id DROP NOT NULL"))
                except Exception:
                    pass

    if "officer_mappings" in tables:
        om_cols = {c["name"] for c in insp.get_columns("officer_mappings")}
        with engine.begin() as conn:
            if "level_1_email" not in om_cols:
                conn.execute(
                    text("ALTER TABLE officer_mappings ADD COLUMN level_1_email VARCHAR(255) NULL")
                )
            if "level_2_email" not in om_cols:
                conn.execute(
                    text("ALTER TABLE officer_mappings ADD COLUMN level_2_email VARCHAR(255) NULL")
                )
            if "level_3_email" not in om_cols:
                conn.execute(
                    text("ALTER TABLE officer_mappings ADD COLUMN level_3_email VARCHAR(255) NULL")
                )
            if "official_email" in om_cols:
                conn.execute(
                    text(
                        "UPDATE officer_mappings SET level_1_email = official_email "
                        "WHERE level_1_email IS NULL AND official_email IS NOT NULL"
                    )
                )
                if dialect == "postgresql":
                    conn.execute(text("ALTER TABLE officer_mappings DROP COLUMN official_email"))
                elif dialect == "sqlite":
                    try:
                        conn.execute(text("ALTER TABLE officer_mappings DROP COLUMN official_email"))
                    except Exception:
                        pass

    if "otp_codes" in tables:
        otp_cols = {c["name"] for c in insp.get_columns("otp_codes")}
        with engine.begin() as conn:
            # Legacy compatibility: old schema stored plain-text `otp` as NOT NULL.
            # New flow stores only `otp_hash`, so `otp` must be nullable when present.
            if "otp" in otp_cols and dialect == "postgresql":
                try:
                    conn.execute(text("ALTER TABLE otp_codes ALTER COLUMN otp DROP NOT NULL"))
                except Exception:
                    pass
            if "otp_hash" not in otp_cols:
                conn.execute(text("ALTER TABLE otp_codes ADD COLUMN otp_hash VARCHAR(255) NULL"))
            if "attempts" not in otp_cols:
                conn.execute(
                    text("ALTER TABLE otp_codes ADD COLUMN attempts INTEGER NOT NULL DEFAULT 0")
                )
            if "created_at" not in otp_cols:
                if dialect == "postgresql":
                    conn.execute(
                        text(
                            "ALTER TABLE otp_codes ADD COLUMN created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()"
                        )
                    )
                else:
                    conn.execute(
                        text(
                            "ALTER TABLE otp_codes ADD COLUMN created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP"
                        )
                    )
            if dialect == "postgresql":
                conn.execute(
                    text(
                        "CREATE INDEX IF NOT EXISTS ix_otp_codes_email_created_at "
                        "ON otp_codes (email, created_at)"
                    )
                )


SessionLocal = sessionmaker(
    bind=engine,
    autocommit=False,
    autoflush=False,
    class_=Session,
)


def get_db() -> Generator[Session, None, None]:
    """
    FastAPI dependency that provides a database session and
    ensures it is closed after the request is handled.
    """
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()

