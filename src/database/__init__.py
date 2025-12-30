"""Database module for SQLModel entities and connection management."""

from src.database.connection import get_engine, get_session, init_db
from src.database.models import (
    ConfiguracionHoraria,
    MateriaCarreraLink,
    ComisionProfesorLink,
    CicloDB,
    DictadoDB,
    CarreraDB,
    ProfesorDB,
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
    # Connection
    "get_engine",
    "get_session", 
    "init_db",
    # Config
    "ConfiguracionHoraria",
    # Link tables
    "MateriaCarreraLink",
    "ComisionProfesorLink",
    # Temporal models
    "CicloDB",
    "DictadoDB",
    # Problem domain
    "CarreraDB",
    "ProfesorDB",
    "AlumnoDB",
    "MateriaDB",
    "ComisionDB",
    "HorarioCronogramaDB",
    "AulaDB",
    "ClaseDB",
    # Solution domain
    "InscripcionDB",
    "AsistenciaDB",
    "AsignacionAulaDB",
    # Converters
    "to_db",
    "to_domain",
    "to_db_list",
    "to_domain_list",
]
