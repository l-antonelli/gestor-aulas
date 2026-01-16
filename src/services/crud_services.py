"""
CRUD Service Layer for Domain Entities.

This module provides a centralized service layer that encapsulates CRUD operations
for domain entities, handling domain-to-database model conversion internally.

ARCHITECTURE:
    This module sits between the UI layer and the persistence layer:
    
    ┌─────────────────────────────────────────────────────┐
    │  CAPA DE PRESENTACIÓN (Streamlit Pages)             │
    │  - Solo lógica de UI                                │
    │  - Importa servicios de este módulo                 │
    └─────────────────────────────────────────────────────┘
                            │
                            ▼
    ┌─────────────────────────────────────────────────────┐
    │  CAPA DE SERVICIOS CRUD (este archivo) ◄─ AQUÍ      │
    │  - Conversión Domain ↔ DB automática                │
    │  - Operaciones cascading                            │
    │  - Manejo de errores                                │
    └─────────────────────────────────────────────────────┘
                            │
                            ▼
    ┌─────────────────────────────────────────────────────┐
    │  CAPA DE PERSISTENCIA (src/database/)               │
    │  - CRUD genérico                                    │
    │  - Modelos SQLModel                                 │
    └─────────────────────────────────────────────────────┘

Requirements: 1.1, 1.3, 1.4, 1.5
"""

from typing import TypeVar, Generic, Type, Optional, List, Tuple, Any, Callable
from pydantic import BaseModel
from sqlmodel import Session

from src.database.crud import CRUDBase
from src.database.converters import to_db, to_domain


# Type variables for generic service
DomainModel = TypeVar("DomainModel", bound=BaseModel)
DBModel = TypeVar("DBModel")


# =============================================================================
# Custom Exceptions
# =============================================================================

class CRUDServiceError(Exception):
    """Base exception for CRUD service errors."""
    pass


class EntityNotFoundError(CRUDServiceError):
    """Raised when an entity is not found in the database."""
    
    def __init__(self, model_name: str, entity_id: str):
        self.model_name = model_name
        self.entity_id = entity_id
        super().__init__(f"{model_name} con ID '{entity_id}' no encontrado")


class DuplicateEntityError(CRUDServiceError):
    """Raised when attempting to create an entity with an existing ID."""
    
    def __init__(self, model_name: str, entity_id: str):
        self.model_name = model_name
        self.entity_id = entity_id
        super().__init__(f"Ya existe un {model_name} con ID '{entity_id}'")


class ValidationError(CRUDServiceError):
    """Raised when entity validation fails."""
    
    def __init__(self, model_name: str, message: str):
        self.model_name = model_name
        super().__init__(f"Error de validación en {model_name}: {message}")


class RelationshipError(CRUDServiceError):
    """Raised when a foreign key references a non-existent entity."""
    
    def __init__(self, model_name: str, fk_field: str, fk_value: str):
        self.model_name = model_name
        self.fk_field = fk_field
        self.fk_value = fk_value
        super().__init__(
            f"La entidad relacionada no existe: {model_name}.{fk_field} = '{fk_value}'"
        )


class CascadingError(CRUDServiceError):
    """Raised when a cascading operation fails."""
    
    def __init__(self, operation: str, parent_model: str, child_model: str, message: str):
        self.operation = operation
        self.parent_model = parent_model
        self.child_model = child_model
        super().__init__(
            f"Error en operación cascading {operation} de {parent_model} → {child_model}: {message}"
        )


# =============================================================================
# Base CRUD Service
# =============================================================================

class BaseCRUDService(Generic[DomainModel, DBModel]):
    """
    Base class for CRUD services that handle domain model operations.
    
    This service layer:
    - Accepts and returns domain models (Pydantic)
    - Handles conversion to/from database models internally
    - Provides error handling with descriptive exceptions
    - Supports cascading operations
    
    Type Parameters:
        DomainModel: The Pydantic domain model class
        DBModel: The SQLModel database model class
    
    Example:
        ```python
        class MateriaService(BaseCRUDService[Materia, MateriaDB]):
            def __init__(self):
                super().__init__(
                    domain_model=Materia,
                    db_model=MateriaDB,
                    crud=materia_crud,
                    id_field="codigo"
                )
        ```
    """
    
    def __init__(
        self,
        domain_model: Type[DomainModel],
        db_model: Type[DBModel],
        crud: CRUDBase[DBModel],
        id_field: str = "id",
    ):
        """
        Initialize the CRUD service.
        
        Args:
            domain_model: The domain model class (Pydantic)
            db_model: The database model class (SQLModel)
            crud: The CRUD instance for database operations
            id_field: The name of the primary key field
        """
        self.domain_model = domain_model
        self.db_model = db_model
        self.crud = crud
        self.id_field = id_field
    
    def _get_entity_id(self, instance: DomainModel) -> str:
        """Extract the entity ID from a domain model instance."""
        return getattr(instance, self.id_field)
    
    def _get_model_name(self) -> str:
        """Get the human-readable model name."""
        return self.domain_model.__name__
    
    # =========================================================================
    # Core CRUD Operations
    # =========================================================================
    
    def create(self, session: Session, instance: DomainModel) -> DomainModel:
        """
        Create a new entity in the database.
        
        Args:
            session: Database session
            instance: Domain model instance to create
            
        Returns:
            The created domain model instance
            
        Raises:
            DuplicateEntityError: If an entity with the same ID already exists
            ValidationError: If the entity fails validation
        """
        entity_id = self._get_entity_id(instance)
        
        # Check for duplicate
        existing = self.crud.get(session, entity_id)
        if existing is not None:
            raise DuplicateEntityError(self._get_model_name(), entity_id)
        
        try:
            # Convert domain to DB model
            db_instance = to_db(instance)
            
            # Create in database
            created_db = self.crud.create(session, db_instance)
            
            # Convert back to domain model
            return to_domain(created_db)
            
        except Exception as e:
            if "validation" in str(e).lower():
                raise ValidationError(self._get_model_name(), str(e))
            raise
    
    def get(self, session: Session, entity_id: str) -> Optional[DomainModel]:
        """
        Get an entity by its ID.
        
        Args:
            session: Database session
            entity_id: The entity's primary key value
            
        Returns:
            The domain model instance if found, None otherwise
        """
        db_instance = self.crud.get(session, entity_id)
        if db_instance is None:
            return None
        return to_domain(db_instance)
    
    def get_or_raise(self, session: Session, entity_id: str) -> DomainModel:
        """
        Get an entity by its ID, raising an error if not found.
        
        Args:
            session: Database session
            entity_id: The entity's primary key value
            
        Returns:
            The domain model instance
            
        Raises:
            EntityNotFoundError: If the entity is not found
        """
        result = self.get(session, entity_id)
        if result is None:
            raise EntityNotFoundError(self._get_model_name(), entity_id)
        return result
    
    def get_all(self, session: Session, skip: int = 0, limit: int = 100) -> List[DomainModel]:
        """
        Get all entities with pagination.
        
        Args:
            session: Database session
            skip: Number of records to skip
            limit: Maximum number of records to return
            
        Returns:
            List of domain model instances
        """
        db_instances = self.crud.get_all(session, skip=skip, limit=limit)
        return [to_domain(db) for db in db_instances]
    
    def update(self, session: Session, instance: DomainModel) -> DomainModel:
        """
        Update an existing entity.
        
        Args:
            session: Database session
            instance: Domain model instance with updated values
            
        Returns:
            The updated domain model instance
            
        Raises:
            EntityNotFoundError: If the entity doesn't exist
            ValidationError: If the entity fails validation
        """
        entity_id = self._get_entity_id(instance)
        
        # Check entity exists and get the existing DB instance
        existing = self.crud.get(session, entity_id)
        if existing is None:
            raise EntityNotFoundError(self._get_model_name(), entity_id)
        
        try:
            # Update existing DB instance with new values from domain model
            instance_dict = instance.model_dump()
            for key, value in instance_dict.items():
                if hasattr(existing, key):
                    setattr(existing, key, value)
            
            # Commit the changes
            session.add(existing)
            session.commit()
            session.refresh(existing)
            
            # Convert back to domain model
            return to_domain(existing)
            
        except Exception as e:
            if "validation" in str(e).lower():
                raise ValidationError(self._get_model_name(), str(e))
            raise
    
    def delete(self, session: Session, entity_id: str) -> bool:
        """
        Delete an entity by its ID.
        
        Args:
            session: Database session
            entity_id: The entity's primary key value
            
        Returns:
            True if the entity was deleted, False if it didn't exist
        """
        return self.crud.delete(session, entity_id)
    
    def delete_or_raise(self, session: Session, entity_id: str) -> bool:
        """
        Delete an entity by its ID, raising an error if not found.
        
        Args:
            session: Database session
            entity_id: The entity's primary key value
            
        Returns:
            True if deleted successfully
            
        Raises:
            EntityNotFoundError: If the entity is not found
        """
        existing = self.crud.get(session, entity_id)
        if existing is None:
            raise EntityNotFoundError(self._get_model_name(), entity_id)
        return self.crud.delete(session, entity_id)


    # =========================================================================
    # Cascading Operations
    # =========================================================================
    
    def create_with_cascading(
        self, 
        session: Session, 
        instance: DomainModel
    ) -> Tuple[DomainModel, List[Any]]:
        """
        Create an entity with cascading child creation.
        
        This method:
        1. Creates the parent entity
        2. Checks for relationships with cascading_create=True
        3. Creates default child entities for those relationships
        
        Args:
            session: Database session
            instance: Domain model instance to create
            
        Returns:
            Tuple of (created_parent, list_of_created_children)
            
        Raises:
            DuplicateEntityError: If an entity with the same ID already exists
            CascadingError: If cascading child creation fails (parent still created)
        """
        from src.services.cascading_operations import CascadingOperations
        
        entity_id = self._get_entity_id(instance)
        
        # Check for duplicate
        existing = self.crud.get(session, entity_id)
        if existing is not None:
            raise DuplicateEntityError(self._get_model_name(), entity_id)
        
        try:
            # Convert domain to DB model
            db_instance = to_db(instance)
            
            # Use cascading operations
            created_db, children_db = CascadingOperations.create_with_cascading(
                parent_instance=db_instance,
                parent_crud_func=self.crud.create,
                session=session,
            )
            
            # Convert back to domain models
            created_domain = to_domain(created_db)
            children_domain = [to_domain(child) for child in children_db]
            
            return created_domain, children_domain
            
        except DuplicateEntityError:
            raise
        except Exception as e:
            raise CascadingError(
                operation="create",
                parent_model=self._get_model_name(),
                child_model="children",
                message=str(e)
            )
    
    def delete_with_cascading(self, session: Session, entity_id: str) -> bool:
        """
        Delete an entity with cascading deletion of children.
        
        This method handles deletion based on relationship delete_behavior:
        - "cascade": Delete parent and all children
        - "restrict": Prevent deletion if children exist
        - "soft_delete": Mark as deleted but keep children
        
        Args:
            session: Database session
            entity_id: The entity's primary key value
            
        Returns:
            True if deletion was successful
            
        Raises:
            EntityNotFoundError: If the entity doesn't exist
            ValueError: If delete_behavior is "restrict" and children exist
        """
        from src.services.relationship_registry import RelationshipRegistry
        from src.services.cascading_operations import CascadingOperations
        from sqlmodel import select
        
        # Check entity exists
        existing = self.crud.get(session, entity_id)
        if existing is None:
            raise EntityNotFoundError(self._get_model_name(), entity_id)
        
        # Get all relationships for this model
        relationships = RelationshipRegistry.get_relationships_for_model(self.domain_model)
        
        # Process each relationship
        for relationship in relationships:
            # Get DB model for child
            child_db_model = CascadingOperations._get_db_model_for_domain_model(
                relationship.child_model
            )
            if not child_db_model:
                continue
            
            # Query for children
            statement = select(child_db_model).where(
                getattr(child_db_model, relationship.foreign_key_field) == entity_id
            )
            children = list(session.exec(statement).all())
            
            if relationship.delete_behavior == "restrict":
                if children:
                    raise ValueError(
                        f"Cannot delete {self._get_model_name()} with ID '{entity_id}': "
                        f"{len(children)} related {relationship.child_model.__name__} entities exist. "
                        f"Delete behavior is set to 'restrict'."
                    )
            
            elif relationship.delete_behavior == "cascade":
                # Delete all children first
                for child in children:
                    session.delete(child)
                session.commit()
        
        # Delete the parent
        return self.crud.delete(session, entity_id)
    
    def get_children(
        self, 
        session: Session, 
        parent_id: str, 
        child_model: Type[BaseModel]
    ) -> List[Any]:
        """
        Get all child entities for a parent.
        
        Args:
            session: Database session
            parent_id: The parent entity's ID
            child_model: The child model class
            
        Returns:
            List of child domain model instances
        """
        from src.services.relationship_registry import RelationshipRegistry
        from sqlmodel import select
        from src.services.cascading_operations import CascadingOperations
        
        # Get relationship metadata
        relationships = RelationshipRegistry.get_relationships_for_model(self.domain_model)
        
        for rel in relationships:
            if rel.child_model == child_model:
                # Get DB model for child
                child_db_model = CascadingOperations._get_db_model_for_domain_model(child_model)
                if not child_db_model:
                    return []
                
                # Query children
                statement = select(child_db_model).where(
                    getattr(child_db_model, rel.foreign_key_field) == parent_id
                )
                results = session.exec(statement).all()
                
                # Convert to domain models
                return [to_domain(r) for r in results]
        
        return []



# =============================================================================
# Entity-Specific Service Classes
# =============================================================================

# Import domain models
from src.domain.problem.materia import Materia
from src.domain.problem.comision import Comision
from src.domain.problem.clase import Clase
from src.domain.problem.alumno import Alumno
from src.domain.problem.aula import Aula
from src.domain.problem.horario_cronograma import HorarioCronograma
from src.domain.problem.carrera import Carrera

# Import DB models
from src.database.models import (
    MateriaDB, ComisionDB, ClaseDB, AlumnoDB, AulaDB, 
    HorarioCronogramaDB, CarreraDB
)

# Import CRUD instances
from src.database.crud import (
    materia_crud, comision_crud, clase_crud, alumno_crud,
    aula_crud, horario_crud, carrera_crud
)


class MateriaService(BaseCRUDService[Materia, MateriaDB]):
    """
    CRUD service for Materia entities.
    
    Provides domain-level operations for academic subjects,
    including cascading creation of default Comisión and carrera relationships.
    """
    
    def __init__(self):
        super().__init__(
            domain_model=Materia,
            db_model=MateriaDB,
            crud=materia_crud,
            id_field="codigo"
        )
    
    def get_comisiones(self, session: Session, materia_codigo: str) -> List[Comision]:
        """Get all comisiones for a materia."""
        return self.get_children(session, materia_codigo, Comision)
    
    def get_carreras(self, session: Session, materia_codigo: str) -> List[Carrera]:
        """
        Get all carreras associated with a materia.
        
        This method queries the many-to-many relationship between
        Materia and Carrera through the MateriaCarreraLink table.
        
        Args:
            session: Database session
            materia_codigo: The materia's codigo
            
        Returns:
            List of Carrera domain model instances associated with the materia
        """
        from sqlmodel import select
        from src.database.models import MateriaCarreraLink
        
        # Query carreras through the link table
        statement = (
            select(CarreraDB)
            .join(MateriaCarreraLink, CarreraDB.codigo == MateriaCarreraLink.carrera_codigo)
            .where(MateriaCarreraLink.materia_codigo == materia_codigo)
        )
        results = session.exec(statement).all()
        return [to_domain(r) for r in results]
    
    def set_carreras(self, session: Session, materia_codigo: str, carrera_codigos: List[str]) -> bool:
        """
        Set the carreras associated with a materia, replacing any existing associations.
        
        Args:
            session: Database session
            materia_codigo: The materia's codigo
            carrera_codigos: List of carrera codigos to associate
            
        Returns:
            True if successful
            
        Raises:
            EntityNotFoundError: If materia or any carrera doesn't exist
            ValidationError: If no carreras are provided (business rule)
        """
        from src.database.models import MateriaCarreraLink
        from src.database.crud import carrera_crud
        from sqlmodel import select
        
        # Validate that at least one carrera is provided
        if not carrera_codigos:
            raise ValidationError("Materia", "Debe asignar al menos una carrera a la materia")
        
        # Verify materia exists
        materia = self.crud.get(session, materia_codigo)
        if materia is None:
            raise EntityNotFoundError("Materia", materia_codigo)
        
        # Verify all carreras exist
        for carrera_codigo in carrera_codigos:
            carrera = carrera_crud.get(session, carrera_codigo)
            if carrera is None:
                raise EntityNotFoundError("Carrera", carrera_codigo)
        
        # Remove existing associations
        existing_links = session.exec(
            select(MateriaCarreraLink).where(
                MateriaCarreraLink.materia_codigo == materia_codigo
            )
        ).all()
        
        for link in existing_links:
            session.delete(link)
        
        # Create new associations with default values
        for carrera_codigo in carrera_codigos:
            link = MateriaCarreraLink(
                materia_codigo=materia_codigo,
                carrera_codigo=carrera_codigo,
                anio_carrera=1,
                cuatrimestre_carrera=1
            )
            session.add(link)
        
        session.commit()
        return True
    
    def add_carrera(
        self, 
        session: Session, 
        materia_codigo: str, 
        carrera_codigo: str,
        anio_carrera: int = 1,
        cuatrimestre_carrera: int = 1
    ) -> bool:
        """
        Associate a carrera with a materia, specifying year and semester.
        
        Args:
            session: Database session
            materia_codigo: The materia's codigo
            carrera_codigo: The carrera's codigo
            anio_carrera: Year in the curriculum (1-6)
            cuatrimestre_carrera: Semester (1 or 2)
            
        Returns:
            True if the association was created, False if it already exists
            
        Raises:
            EntityNotFoundError: If materia or carrera doesn't exist
        """
        from src.database.models import MateriaCarreraLink
        from src.database.crud import carrera_crud
        from sqlmodel import select
        
        # Verify materia exists
        materia = self.crud.get(session, materia_codigo)
        if materia is None:
            raise EntityNotFoundError("Materia", materia_codigo)
        
        # Verify carrera exists
        carrera = carrera_crud.get(session, carrera_codigo)
        if carrera is None:
            raise EntityNotFoundError("Carrera", carrera_codigo)
        
        # Check if link already exists
        existing = session.exec(
            select(MateriaCarreraLink).where(
                MateriaCarreraLink.materia_codigo == materia_codigo,
                MateriaCarreraLink.carrera_codigo == carrera_codigo
            )
        ).first()
        
        if existing:
            return False
        
        # Create the link with year and semester
        link = MateriaCarreraLink(
            materia_codigo=materia_codigo,
            carrera_codigo=carrera_codigo,
            anio_carrera=anio_carrera,
            cuatrimestre_carrera=cuatrimestre_carrera
        )
        session.add(link)
        session.commit()
        return True
    
    def remove_carrera(self, session: Session, materia_codigo: str, carrera_codigo: str) -> bool:
        """
        Remove the association between a materia and a carrera.
        
        Args:
            session: Database session
            materia_codigo: The materia's codigo
            carrera_codigo: The carrera's codigo
            
        Returns:
            True if the association was removed, False if it didn't exist
        """
        from src.database.models import MateriaCarreraLink
        from sqlmodel import select
        
        # Find the link
        link = session.exec(
            select(MateriaCarreraLink).where(
                MateriaCarreraLink.materia_codigo == materia_codigo,
                MateriaCarreraLink.carrera_codigo == carrera_codigo
            )
        ).first()
        
        if link is None:
            return False
        
        session.delete(link)
        session.commit()
        return True


class ComisionService(BaseCRUDService[Comision, ComisionDB]):
    """
    CRUD service for Comision entities.
    
    Provides domain-level operations for subject divisions/sections.
    """
    
    def __init__(self):
        super().__init__(
            domain_model=Comision,
            db_model=ComisionDB,
            crud=comision_crud,
            id_field="id"
        )
    
    def get_clases(self, session: Session, comision_id: str) -> List[Clase]:
        """Get all clases for a comision."""
        return self.get_children(session, comision_id, Clase)
    
    def get_by_materia(self, session: Session, materia_codigo: str) -> List[Comision]:
        """Get all comisiones for a specific materia."""
        from sqlmodel import select
        
        statement = select(ComisionDB).where(
            ComisionDB.materia_codigo == materia_codigo
        )
        results = session.exec(statement).all()
        return [to_domain(r) for r in results]


class ClaseService(BaseCRUDService[Clase, ClaseDB]):
    """
    CRUD service for Clase entities.
    
    Provides domain-level operations for class instances.
    """
    
    def __init__(self):
        super().__init__(
            domain_model=Clase,
            db_model=ClaseDB,
            crud=clase_crud,
            id_field="id"
        )
    
    def get_by_comision(self, session: Session, comision_id: str) -> List[Clase]:
        """Get all clases for a specific comision."""
        from sqlmodel import select
        
        statement = select(ClaseDB).where(
            ClaseDB.comision_id == comision_id
        )
        results = session.exec(statement).all()
        return [to_domain(r) for r in results]


class AlumnoService(BaseCRUDService[Alumno, AlumnoDB]):
    """
    CRUD service for Alumno entities.
    
    Provides domain-level operations for students.
    """
    
    def __init__(self):
        super().__init__(
            domain_model=Alumno,
            db_model=AlumnoDB,
            crud=alumno_crud,
            id_field="legajo"
        )


class AulaService(BaseCRUDService[Aula, AulaDB]):
    """
    CRUD service for Aula entities.
    
    Provides domain-level operations for classrooms.
    """
    
    def __init__(self):
        super().__init__(
            domain_model=Aula,
            db_model=AulaDB,
            crud=aula_crud,
            id_field="id"
        )


class HorarioService(BaseCRUDService[HorarioCronograma, HorarioCronogramaDB]):
    """
    CRUD service for HorarioCronograma entities.
    
    Provides domain-level operations for schedule time slots.
    """
    
    def __init__(self):
        super().__init__(
            domain_model=HorarioCronograma,
            db_model=HorarioCronogramaDB,
            crud=horario_crud,
            id_field="id"
        )


class CarreraService(BaseCRUDService[Carrera, CarreraDB]):
    """
    CRUD service for Carrera entities.
    
    Provides domain-level operations for university degree programs,
    including retrieval of associated Materias.
    """
    
    def __init__(self):
        super().__init__(
            domain_model=Carrera,
            db_model=CarreraDB,
            crud=carrera_crud,
            id_field="codigo"
        )
    
    def get_materias(self, session: Session, carrera_codigo: str) -> List[Materia]:
        """
        Get all materias associated with a carrera.
        
        This method queries the many-to-many relationship between
        Carrera and Materia through the MateriaCarreraLink table.
        
        Args:
            session: Database session
            carrera_codigo: The carrera's codigo
            
        Returns:
            List of Materia domain model instances associated with the carrera
        """
        from sqlmodel import select
        from src.database.models import MateriaCarreraLink
        
        # Query materias through the link table
        statement = (
            select(MateriaDB)
            .join(MateriaCarreraLink, MateriaDB.codigo == MateriaCarreraLink.materia_codigo)
            .where(MateriaCarreraLink.carrera_codigo == carrera_codigo)
        )
        results = session.exec(statement).all()
        return [to_domain(r) for r in results]
    
    def add_materia(
        self, 
        session: Session, 
        carrera_codigo: str, 
        materia_codigo: str,
        anio_carrera: int = 1,
        cuatrimestre_carrera: int = 1
    ) -> bool:
        """
        Associate a materia with a carrera, specifying year and semester.
        
        Args:
            session: Database session
            carrera_codigo: The carrera's codigo
            materia_codigo: The materia's codigo
            anio_carrera: Year in the curriculum (1-6)
            cuatrimestre_carrera: Semester (1 or 2)
            
        Returns:
            True if the association was created, False if it already exists
            
        Raises:
            EntityNotFoundError: If carrera or materia doesn't exist
        """
        from src.database.models import MateriaCarreraLink
        from src.database.crud import materia_crud
        
        # Verify carrera exists
        carrera = self.crud.get(session, carrera_codigo)
        if carrera is None:
            raise EntityNotFoundError("Carrera", carrera_codigo)
        
        # Verify materia exists
        materia = materia_crud.get(session, materia_codigo)
        if materia is None:
            raise EntityNotFoundError("Materia", materia_codigo)
        
        # Check if link already exists
        from sqlmodel import select
        existing = session.exec(
            select(MateriaCarreraLink).where(
                MateriaCarreraLink.carrera_codigo == carrera_codigo,
                MateriaCarreraLink.materia_codigo == materia_codigo
            )
        ).first()
        
        if existing:
            return False
        
        # Create the link with year and semester
        link = MateriaCarreraLink(
            carrera_codigo=carrera_codigo,
            materia_codigo=materia_codigo,
            anio_carrera=anio_carrera,
            cuatrimestre_carrera=cuatrimestre_carrera
        )
        session.add(link)
        session.commit()
        return True
    
    def remove_materia(self, session: Session, carrera_codigo: str, materia_codigo: str) -> bool:
        """
        Remove the association between a materia and a carrera.
        
        Args:
            session: Database session
            carrera_codigo: The carrera's codigo
            materia_codigo: The materia's codigo
            
        Returns:
            True if the association was removed, False if it didn't exist
        """
        from src.database.models import MateriaCarreraLink
        from sqlmodel import select
        
        # Find the link
        link = session.exec(
            select(MateriaCarreraLink).where(
                MateriaCarreraLink.carrera_codigo == carrera_codigo,
                MateriaCarreraLink.materia_codigo == materia_codigo
            )
        ).first()
        
        if link is None:
            return False
        
        session.delete(link)
        session.commit()
        return True
    
    def get_children_count(self, session: Session, carrera_codigo: str) -> int:
        """
        Get the count of materias associated with a carrera.
        
        Args:
            session: Database session
            carrera_codigo: The carrera's codigo
            
        Returns:
            Number of materias associated with the carrera
        """
        from sqlmodel import select, func
        from src.database.models import MateriaCarreraLink
        
        statement = select(func.count()).where(
            MateriaCarreraLink.carrera_codigo == carrera_codigo
        )
        return session.exec(statement).one()
    
    def get_materias_by_year_and_semester(
        self, 
        session: Session, 
        carrera_codigo: str, 
        anio: int,
        cuatrimestre: Optional[int] = None
    ) -> List[Tuple[Materia, int, int]]:
        """
        Get materias for a carrera filtered by year and optionally semester.
        
        Args:
            session: Database session
            carrera_codigo: The carrera's codigo
            anio: Year in the curriculum (1-6)
            cuatrimestre: Optional semester filter (1 or 2)
            
        Returns:
            List of tuples (Materia, anio_carrera, cuatrimestre_carrera)
        """
        from sqlmodel import select
        from src.database.models import MateriaCarreraLink
        
        # Build query
        statement = (
            select(MateriaDB, MateriaCarreraLink.anio_carrera, MateriaCarreraLink.cuatrimestre_carrera)
            .join(MateriaCarreraLink, MateriaDB.codigo == MateriaCarreraLink.materia_codigo)
            .where(
                MateriaCarreraLink.carrera_codigo == carrera_codigo,
                MateriaCarreraLink.anio_carrera == anio
            )
        )
        
        # Add semester filter if provided
        if cuatrimestre is not None:
            statement = statement.where(MateriaCarreraLink.cuatrimestre_carrera == cuatrimestre)
        
        results = session.exec(statement).all()
        return [(to_domain(materia_db), anio, cuatri) for materia_db, anio, cuatri in results]


# =============================================================================
# Service Instances (Singletons)
# =============================================================================

# Pre-instantiated services for convenience
materia_service = MateriaService()
comision_service = ComisionService()
clase_service = ClaseService()
alumno_service = AlumnoService()
aula_service = AulaService()
horario_service = HorarioService()
carrera_service = CarreraService()
