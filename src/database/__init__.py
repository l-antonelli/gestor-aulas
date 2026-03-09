"""Database module for SQLModel entities and connection management."""

from src.database.connection import get_engine, get_session, init_db
from src.database.models import (
    ConfiguracionHoraria,
    PlanEstudioDB,
    CorrelativaDB,
    DictadoCicloDB,
    CicloDB,
    DictadoDB,
    CarreraDB,
    MateriaDB,
    ComisionDB,
    HorarioDB,
    AulaDB,
    ScheduleDB,
    ScheduleEntryDB,
    PlanificacionCursadaDB,
    ClaseDB,
)
from src.database.converters import to_db, to_domain, to_db_list, to_domain_list

__all__ = [
    # Connection
    "get_engine",
    "get_session",
    "init_db",
    # Config
    "ConfiguracionHoraria",
    # Link tables
    "PlanEstudioDB",
    "CorrelativaDB",
    "DictadoCicloDB",
    # Temporal models
    "CicloDB",
    "DictadoDB",
    # Problem domain
    "CarreraDB",
    "MateriaDB",
    "ComisionDB",
    "HorarioDB",
    "AulaDB",
    # Schedule & Planning
    "ScheduleDB",
    "ScheduleEntryDB",
    "PlanificacionCursadaDB",
    "ClaseDB",
    # Converters
    "to_db",
    "to_domain",
    "to_db_list",
    "to_domain_list",
]
