"""
CRUD operations for database models.

Este módulo implementa el patrón Repository usando Generics de Python.
Proporciona operaciones CRUD (Create, Read, Update, Delete) reutilizables
para todas las entidades de la base de datos.
"""

from sqlmodel import Session, select
from typing import TypeVar, Generic, Type, Optional
from src.database.models import (
    MateriaDB, ComisionDB, HorarioCronogramaDB,
    AulaDB, ClaseDB, AsignacionAulaDB,
    ConfiguracionHoraria, CarreraDB, CicloDB, DictadoDB
)

T = TypeVar("T")


class CRUDBase(Generic[T]):
    """
    Clase base genérica para operaciones CRUD.
    
    Implementa el patrón Repository, proporcionando una interfaz uniforme
    para acceder a cualquier entidad de la base de datos.
    """
    
    def __init__(self, model: Type[T]):
        """Inicializa el CRUD con un modelo específico."""
        self.model = model
    
    def get(self, session: Session, id: str) -> Optional[T]:
        """Obtiene un registro por su ID."""
        return session.get(self.model, id)
    
    def get_all(self, session: Session, skip: int = 0, limit: int = 100) -> list[T]:
        """Obtiene todos los registros con paginación."""
        statement = select(self.model).offset(skip).limit(limit)
        return list(session.exec(statement).all())
    
    def create(self, session: Session, obj: T) -> T:
        """Crea un nuevo registro en la BD."""
        session.add(obj)
        session.commit()
        session.refresh(obj)
        return obj
    
    def update(self, session: Session, obj: T) -> T:
        """Actualiza un registro existente en la BD."""
        session.add(obj)
        session.commit()
        session.refresh(obj)
        return obj
    
    def delete(self, session: Session, id: str) -> bool:
        """Elimina un registro de la BD."""
        obj = session.get(self.model, id)
        if obj:
            session.delete(obj)
            session.commit()
            return True
        return False


# ============================================================================
# INSTANCIAS DE CRUD PARA CADA MODELO
# ============================================================================

# Instancia CRUD para Materias
materia_crud = CRUDBase[MateriaDB](MateriaDB)

# Instancia CRUD para Comisiones
comision_crud = CRUDBase[ComisionDB](ComisionDB)

# Instancia CRUD para Horarios
horario_crud = CRUDBase[HorarioCronogramaDB](HorarioCronogramaDB)

# Instancia CRUD para Aulas
aula_crud = CRUDBase[AulaDB](AulaDB)

# Instancia CRUD para Clases
clase_crud = CRUDBase[ClaseDB](ClaseDB)

# Instancia CRUD para Asignaciones de Aulas
asignacion_crud = CRUDBase[AsignacionAulaDB](AsignacionAulaDB)

# Instancia CRUD para Carreras
carrera_crud = CRUDBase[CarreraDB](CarreraDB)

# Instancia CRUD para Ciclos
ciclo_crud = CRUDBase[CicloDB](CicloDB)

# Instancia CRUD para Dictados
dictado_crud = CRUDBase[DictadoDB](DictadoDB)


# ============================================================================
# FUNCIONES AUXILIARES ESPECIALIZADAS
# ============================================================================

def create_materia_with_comision(session: Session, materia: MateriaDB) -> tuple[MateriaDB, ComisionDB]:
    """
    Crea una materia con su comisión por defecto.
    """
    session.add(materia)
    session.commit()
    session.refresh(materia)
    
    # Create default comision
    comision = ComisionDB(
        id=f"{materia.codigo}-C1",
        materia_codigo=materia.codigo,
        nombre="Comisión Única",
        numero=1,
        cupo=materia.cupo,
        descripcion="Comisión creada automáticamente"
    )
    session.add(comision)
    session.commit()
    session.refresh(comision)
    
    return materia, comision


def get_or_create_config(session: Session) -> ConfiguracionHoraria:
    """
    Obtiene la configuración singleton, creando la por defecto si no existe.
    """
    config = session.get(ConfiguracionHoraria, 1)
    if not config:
        config = ConfiguracionHoraria(id=1)
        session.add(config)
        session.commit()
        session.refresh(config)
    return config


def update_config(session: Session, config: ConfiguracionHoraria) -> ConfiguracionHoraria:
    """
    Actualiza la configuración del sistema.
    """
    config.id = 1  # Ensure singleton
    session.add(config)
    session.commit()
    session.refresh(config)
    return config
