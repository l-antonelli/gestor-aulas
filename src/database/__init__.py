"""Database module for SQLModel entities and connection management."""

from src.database.connection import get_engine, get_session, init_db
from src.database.models import (
    ConfiguracionHoraria,
    MateriaCarreraLink,
    CicloDB,
    DictadoDB,
    CarreraDB,
    MateriaDB,
    ComisionDB,
    HorarioCronogramaDB,
    AulaDB,
    ClaseDB,
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
    # Temporal models
    "CicloDB",
    "DictadoDB",
    # Problem domain
    "CarreraDB",
    "MateriaDB",
    "ComisionDB",
    "HorarioCronogramaDB",
    "AulaDB",
    "ClaseDB",
    # Solution domain
    "AsignacionAulaDB",
    # Converters
    "to_db",
    "to_domain",
    "to_db_list",
    "to_domain_list",
]
