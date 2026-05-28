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
        "ALTER TABLE schedule_entries ADD COLUMN tipo_clase VARCHAR DEFAULT NULL",
        "ALTER TABLE horarios ADD COLUMN tipo_clase VARCHAR DEFAULT NULL",
        "ALTER TABLE clases ADD COLUMN tipo_clase VARCHAR DEFAULT NULL",
        "ALTER TABLE materias ADD COLUMN horas_teoria REAL DEFAULT NULL",
        "ALTER TABLE materias ADD COLUMN horas_laboratorio REAL DEFAULT NULL",
        "ALTER TABLE schedule_validations ADD COLUMN dictado_count_at_validation INTEGER NOT NULL DEFAULT 0",
        "ALTER TABLE schedule_validations ADD COLUMN n_conflictos_horarios INTEGER NOT NULL DEFAULT 0",
        "ALTER TABLE schedule_validations ADD COLUMN excluir_virtuales_optativas BOOLEAN NOT NULL DEFAULT 0",
        # B.2.1: el toggle paso a ser solo optativas (las virtuales si cuentan
        # para cobertura/conflictos). La columna nueva convive con la vieja
        # para no perder snapshots historicos; la lectura usa la nueva.
        "ALTER TABLE schedule_validations ADD COLUMN excluir_optativas BOOLEAN NOT NULL DEFAULT 0",
        "ALTER TABLE plan_validations ADD COLUMN excluir_optativas BOOLEAN NOT NULL DEFAULT 0",
        "ALTER TABLE materias ADD COLUMN dicta_recursado BOOLEAN DEFAULT NULL",
        "ALTER TABLE comisiones ADD COLUMN coef_asignacion REAL NOT NULL DEFAULT 1.0",
        "ALTER TABLE planificaciones_cursada ADD COLUMN forecast_metodo_default VARCHAR NOT NULL DEFAULT 'media_movil'",
        "DROP TABLE IF EXISTS inscripcion_forecasts",
    ]
    with eng.connect() as conn:
        for sql in migrations:
            try:
                conn.exec_driver_sql(sql)
                conn.commit()
            except Exception:
                # Column already exists — safe to ignore
                conn.rollback()

    # Data migration: populate horas_teoria/horas_laboratorio from horas_semanales
    with eng.connect() as conn:
        conn.exec_driver_sql(
            "UPDATE materias SET horas_teoria = horas_semanales, horas_laboratorio = 0 "
            "WHERE horas_teoria IS NULL AND horas_semanales IS NOT NULL"
        )
        conn.commit()

    # Data migration: limpiar tipo_clase='teorica' heredado del DEFAULT de la
    # migracion ALTER TABLE. Ninguno fue seteado manualmente; el default correcto
    # ahora es NULL (sin determinar, el LP decide).
    with eng.connect() as conn:
        conn.exec_driver_sql(
            "UPDATE schedule_entries SET tipo_clase = NULL WHERE tipo_clase = 'teorica'"
        )
        conn.exec_driver_sql(
            "UPDATE horarios SET tipo_clase = NULL WHERE tipo_clase = 'teorica'"
        )
        conn.exec_driver_sql(
            "UPDATE clases SET tipo_clase = NULL WHERE tipo_clase = 'teorica'"
        )
        conn.commit()

    # Migration: make schedules.ciclo_id nullable (SQLite requires table recreation)
    _migrate_schedules_nullable_ciclo(eng)


def _migrate_schedules_nullable_ciclo(eng):
    """Recreate schedules table so ciclo_id allows NULL.

    SQLite no soporta ALTER COLUMN.  Verificamos con PRAGMA table_info si
    ciclo_id ya es nullable (notnull == 0).  Si ya lo es, no hacemos nada.
    """
    with eng.connect() as conn:
        rows = conn.exec_driver_sql("PRAGMA table_info(schedules)").fetchall()
        if not rows:
            # Table doesn't exist yet — create_all will handle it
            return

        # PRAGMA table_info columns: (cid, name, type, notnull, dflt_value, pk)
        for row in rows:
            if row[1] == "ciclo_id":
                if row[3] == 0:
                    # Already nullable — nothing to do
                    return
                break
        else:
            # ciclo_id column not found — schema mismatch, skip
            return

        # Recreate table with nullable ciclo_id
        logger.info("Migrating schedules table: making ciclo_id nullable")
        conn.exec_driver_sql("""
            CREATE TABLE schedules_tmp (
                id VARCHAR NOT NULL PRIMARY KEY,
                ciclo_id VARCHAR,
                nombre VARCHAR NOT NULL,
                fecha_upload DATE NOT NULL,
                source_filename VARCHAR NOT NULL DEFAULT '',
                FOREIGN KEY (ciclo_id) REFERENCES ciclos (id)
            )
        """)
        conn.exec_driver_sql("""
            INSERT INTO schedules_tmp (id, ciclo_id, nombre, fecha_upload, source_filename)
            SELECT id, ciclo_id, nombre, fecha_upload, source_filename FROM schedules
        """)
        conn.exec_driver_sql("DROP TABLE schedules")
        conn.exec_driver_sql("ALTER TABLE schedules_tmp RENAME TO schedules")
        conn.exec_driver_sql("CREATE INDEX IF NOT EXISTS ix_schedules_ciclo_id ON schedules (ciclo_id)")
        conn.commit()
        logger.info("Migration complete: schedules.ciclo_id is now nullable")


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
