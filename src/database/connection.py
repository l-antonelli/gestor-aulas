"""Database connection and session management."""

from sqlmodel import SQLModel, Session, create_engine
from typing import Generator
import os

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


def init_db():
    """Initialize database tables. Call once at app startup."""
    SQLModel.metadata.create_all(engine)


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
