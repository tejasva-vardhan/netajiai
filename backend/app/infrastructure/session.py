"""Database-engine construction for separately deployed workers."""

from __future__ import annotations

from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker


def create_session_factory(database_url: str) -> sessionmaker[Session]:
    """Create a pooled session factory without performing a database query."""

    if not database_url.strip():
        raise ValueError("DATABASE_URL is required")
    engine = create_engine(database_url, pool_pre_ping=True)
    return sessionmaker(bind=engine, expire_on_commit=False)
