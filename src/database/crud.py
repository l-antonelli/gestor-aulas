"""
CRUD operations for database models.

Provides simple create, read, update, delete operations for all entities.
"""

from sqlmodel import Session, select
from typing import TypeVar, Generic, Type, Optional
from src.database.models import (
    AlumnoDB, MateriaDB, ComisionDB, HorarioCronogramaDB,
    AulaDB, ClaseDB, InscripcionDB, AsistenciaDB, AsignacionAulaDB,
    ConfiguracionHoraria
)

T = TypeVar("T")


class CRUDBase(Generic[T]):
    """Base class for CRUD operations."""
    
    def __init__(self, model: Type[T]):
        self.model = model
    
    def get(self, session: Session, id: str) -> Optional[T]:
        """Get a single record by ID."""
        return session.get(self.model, id)
    
    def get_all(self, session: Session, skip: int = 0, limit: int = 100) -> list[T]:
        """Get all records with pagination."""
        statement = select(self.model).offset(skip).limit(limit)
        return list(session.exec(statement).all())
    
    def create(self, session: Session, obj: T) -> T:
        """Create a new record."""
        session.add(obj)
        session.commit()
        session.refresh(obj)
        return obj
    
    def update(self, session: Session, obj: T) -> T:
        """Update an existing record."""
        session.add(obj)
        session.commit()
        session.refresh(obj)
        return obj
    
    def delete(self, session: Session, id: str) -> bool:
        """Delete a record by ID."""
        obj = session.get(self.model, id)
        if obj:
            session.delete(obj)
            session.commit()
            return True
        return False


# Instantiate CRUD objects for each model
alumno_crud = CRUDBase[AlumnoDB](AlumnoDB)
materia_crud = CRUDBase[MateriaDB](MateriaDB)
comision_crud = CRUDBase[ComisionDB](ComisionDB)
horario_crud = CRUDBase[HorarioCronogramaDB](HorarioCronogramaDB)
aula_crud = CRUDBase[AulaDB](AulaDB)
clase_crud = CRUDBase[ClaseDB](ClaseDB)
inscripcion_crud = CRUDBase[InscripcionDB](InscripcionDB)
asistencia_crud = CRUDBase[AsistenciaDB](AsistenciaDB)
asignacion_crud = CRUDBase[AsignacionAulaDB](AsignacionAulaDB)


def get_or_create_config(session: Session) -> ConfiguracionHoraria:
    """Get the singleton configuration, creating default if not exists."""
    config = session.get(ConfiguracionHoraria, 1)
    if not config:
        config = ConfiguracionHoraria(id=1)
        session.add(config)
        session.commit()
        session.refresh(config)
    return config


def update_config(session: Session, config: ConfiguracionHoraria) -> ConfiguracionHoraria:
    """Update the configuration."""
    config.id = 1  # Ensure singleton
    session.add(config)
    session.commit()
    session.refresh(config)
    return config
