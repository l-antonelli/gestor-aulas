"""Database connection and session management."""

from sqlmodel import SQLModel, Session, create_engine
from typing import Generator
import os
import logging

logger = logging.getLogger(__name__)

# Default to local SQLite file in data directory
DATABASE_URL = os.getenv("DATABASE_URL", "sqlite:///data/database.db")

# Create engine with SQLite-specific settings
engine = create_engine(
    DATABASE_URL,
    echo=False,  # Set to True for SQL debugging
    connect_args={"check_same_thread": False}  # Needed for SQLite + Streamlit
)


def get_engine():
    """Get the database engine instance."""
    return engine


def _run_migrations(eng):
    """Run ALTER TABLE migrations for columns added after initial schema creation.

    SQLModel.metadata.create_all() only creates new tables; it does NOT add
    columns to existing tables.  This function handles that gap for SQLite.
    Each migration is idempotent — it silently skips if the column already exists.
    """
    migrations = [
        "ALTER TABLE carreras ADD COLUMN dicta_recursado BOOLEAN DEFAULT 1",
        "ALTER TABLE materias ADD COLUMN virtual BOOLEAN DEFAULT 0",
        "ALTER TABLE dictados ADD COLUMN virtual BOOLEAN DEFAULT 0",
    ]
    with eng.connect() as conn:
        for sql in migrations:
            try:
                conn.exec_driver_sql(sql)
                conn.commit()
            except Exception:
                # Column already exists — safe to ignore
                conn.rollback()


def init_db():
    """Initialize database tables. Call once at app startup."""
    SQLModel.metadata.create_all(engine)
    _run_migrations(engine)


def get_session() -> Generator[Session, None, None]:
    """
    Get a database session.
    
    Usage:
        with get_session() as session:
            # do stuff with session
    
    Or as a generator for dependency injection:
        for session in get_session():
            # do stuff
    """
    with Session(engine) as session:
        yield session
