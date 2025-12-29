"""Database module for SQLModel entities and connection management."""

from src.database.connection import get_engine, get_session, init_db
from src.database.models import (
    ConfiguracionHoraria,
    AlumnoDB,
    MateriaDB,
    ComisionDB,
    HorarioCronogramaDB,
    AulaDB,
    ClaseDB,
    InscripcionDB,
    AsistenciaDB,
    AsignacionAulaDB,
)
from src.database.converters import to_db, to_domain, to_db_list, to_domain_list

__all__ = [
    "get_engine",
    "get_session", 
    "init_db",
    "AlumnoDB",
    "MateriaDB",
    "ComisionDB",
    "HorarioCronogramaDB",
    "AulaDB",
    "ClaseDB",
    "InscripcionDB",
    "AsistenciaDB",
    "AsignacionAulaDB",
]
