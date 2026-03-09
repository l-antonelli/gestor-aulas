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

        # Check entity exists
        existing = self.crud.get(session, entity_id)
        if existing is None:
            raise EntityNotFoundError(self._get_model_name(), entity_id)

        # Get all relationships for this model
        relationships = RelationshipRegistry.get_relationships_for_model(self.domain_model)

        # Process each relationship
        for relationship in relationships:
            # Query for related records (handles both 1:N and M:N)
            children = CascadingOperations._get_children(
                parent_id=entity_id,
                relationship=relationship,
                session=session,
            )

            if relationship.delete_behavior == "restrict":
                if children:
                    child_label = (
                        f"{relationship.link_table} entries"
                        if relationship.is_many_to_many
                        else f"{relationship.child_model.__name__} entities"
                    )
                    raise ValueError(
                        f"Cannot delete {self._get_model_name()} with ID '{entity_id}': "
                        f"{len(children)} related {child_label} exist. "
                        f"Delete behavior is set to 'restrict'."
                    )

            elif relationship.delete_behavior == "cascade":
                for child in children:
                    session.delete(child)
                session.commit()

        # Delete the parent (uses self.delete() so subclass overrides apply)
        return self.delete(session, entity_id)

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
from src.domain.problem.aula import Aula
from src.domain.problem.horario import Horario
from src.domain.problem.carrera import Carrera

# Import DB models
from src.database.models import (
    MateriaDB, ComisionDB, AulaDB,
    HorarioDB, CarreraDB
)

# Import CRUD instances
from src.database.crud import (
    materia_crud, comision_crud,
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
        Get all carreras associated with a materia (any version, deduplicated).
        """
        from sqlmodel import select
        from src.database.models import PlanEstudioDB

        statement = (
            select(CarreraDB)
            .join(PlanEstudioDB, CarreraDB.codigo == PlanEstudioDB.carrera_codigo)
            .where(PlanEstudioDB.materia_codigo == materia_codigo)
            .distinct()
        )
        results = session.exec(statement).all()
        return [to_domain(r) for r in results]

    def set_carreras(
        self, session: Session, materia_codigo: str, carrera_codigos: List[str],
        plan_version_id: str,
    ) -> bool:
        """
        Set the carreras associated with a materia in a specific plan version,
        replacing any existing associations for that version.
        """
        from src.database.models import PlanEstudioDB
        from src.database.crud import carrera_crud
        from sqlmodel import select

        if not carrera_codigos:
            raise ValidationError("Materia", "Debe asignar al menos una carrera a la materia")

        materia = self.crud.get(session, materia_codigo)
        if materia is None:
            raise EntityNotFoundError("Materia", materia_codigo)

        for carrera_codigo in carrera_codigos:
            carrera = carrera_crud.get(session, carrera_codigo)
            if carrera is None:
                raise EntityNotFoundError("Carrera", carrera_codigo)

        # Remove existing associations for this version
        existing_links = session.exec(
            select(PlanEstudioDB).where(
                PlanEstudioDB.materia_codigo == materia_codigo,
                PlanEstudioDB.plan_version_id == plan_version_id,
            )
        ).all()

        for link in existing_links:
            session.delete(link)

        for carrera_codigo in carrera_codigos:
            link = PlanEstudioDB(
                plan_version_id=plan_version_id,
                materia_codigo=materia_codigo,
                carrera_codigo=carrera_codigo,
                anio_plan=1,
                cuatrimestre_plan="1C",
            )
            session.add(link)

        session.commit()
        return True

    def add_carrera(
        self,
        session: Session,
        materia_codigo: str,
        carrera_codigo: str,
        plan_version_id: str,
        anio_plan: int = 1,
        cuatrimestre_plan: str = "1C",
    ) -> bool:
        """
        Associate a carrera with a materia in a specific plan version.
        """
        from src.database.models import PlanEstudioDB
        from src.database.crud import carrera_crud
        from sqlmodel import select

        materia = self.crud.get(session, materia_codigo)
        if materia is None:
            raise EntityNotFoundError("Materia", materia_codigo)

        carrera = carrera_crud.get(session, carrera_codigo)
        if carrera is None:
            raise EntityNotFoundError("Carrera", carrera_codigo)

        existing = session.exec(
            select(PlanEstudioDB).where(
                PlanEstudioDB.materia_codigo == materia_codigo,
                PlanEstudioDB.carrera_codigo == carrera_codigo,
                PlanEstudioDB.plan_version_id == plan_version_id,
            )
        ).first()

        if existing:
            return False

        link = PlanEstudioDB(
            plan_version_id=plan_version_id,
            materia_codigo=materia_codigo,
            carrera_codigo=carrera_codigo,
            anio_plan=anio_plan,
            cuatrimestre_plan=cuatrimestre_plan,
        )
        session.add(link)
        session.commit()
        return True

    def remove_carrera(
        self, session: Session, materia_codigo: str, carrera_codigo: str,
        plan_version_id: str,
    ) -> bool:
        """
        Remove the association between a materia and a carrera in a specific plan version.
        """
        from src.database.models import PlanEstudioDB
        from sqlmodel import select

        link = session.exec(
            select(PlanEstudioDB).where(
                PlanEstudioDB.materia_codigo == materia_codigo,
                PlanEstudioDB.carrera_codigo == carrera_codigo,
                PlanEstudioDB.plan_version_id == plan_version_id,
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
    
    def get_horarios(self, session: Session, comision_id: str) -> List[Horario]:
        """Get all horarios for a comision."""
        return self.get_children(session, comision_id, Horario)
    
    def get_by_materia(self, session: Session, materia_codigo: str) -> List[Comision]:
        """Get all comisiones for a specific materia."""
        from sqlmodel import select
        
        statement = select(ComisionDB).where(
            ComisionDB.materia_codigo == materia_codigo
        )
        results = session.exec(statement).all()
        return [to_domain(r) for r in results]


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


class HorarioService(BaseCRUDService[Horario, HorarioDB]):
    """
    CRUD service for Horario entities.

    Provides domain-level operations for schedule entries
    (comision + day + time range).
    """

    def __init__(self):
        super().__init__(
            domain_model=Horario,
            db_model=HorarioDB,
            crud=horario_crud,
            id_field="id"
        )

    def get_by_comision(self, session: Session, comision_id: str) -> List[Horario]:
        """Get all horarios for a specific comision."""
        from sqlmodel import select

        statement = select(HorarioDB).where(
            HorarioDB.comision_id == comision_id
        )
        results = session.exec(statement).all()
        return [to_domain(r) for r in results]

    def get_by_materia(self, session: Session, codigo_materia: str) -> List[Horario]:
        """Get all horarios for a specific materia."""
        from sqlmodel import select

        statement = select(HorarioDB).where(
            HorarioDB.codigo_materia == codigo_materia
        )
        results = session.exec(statement).all()
        return [to_domain(r) for r in results]


class CarreraService(BaseCRUDService[Carrera, CarreraDB]):
    """
    CRUD service for Carrera entities.

    Provides domain-level operations for university degree programs,
    including retrieval of associated Materias with plan version support.
    """

    def __init__(self):
        super().__init__(
            domain_model=Carrera,
            db_model=CarreraDB,
            crud=carrera_crud,
            id_field="codigo"
        )

    def delete(self, session: Session, entity_id: str) -> bool:
        """Delete a carrera, blocking if plan versions exist."""
        from sqlmodel import select
        from src.database.models import PlanCarreraVersionDB

        versions = list(session.exec(
            select(PlanCarreraVersionDB).where(
                PlanCarreraVersionDB.carrera_codigo == entity_id
            )
        ).all())

        if versions:
            raise ValueError(
                f"Cannot delete Carrera '{entity_id}': "
                f"{len(versions)} plan version(s) exist. "
                f"Delete plan versions first."
            )

        return super().delete(session, entity_id)

    def get_plan_versions(self, session: Session, carrera_codigo: str) -> list:
        """Get all plan versions for a carrera, ordered by fecha_creacion."""
        from sqlmodel import select
        from src.database.models import PlanCarreraVersionDB

        statement = (
            select(PlanCarreraVersionDB)
            .where(PlanCarreraVersionDB.carrera_codigo == carrera_codigo)
            .order_by(PlanCarreraVersionDB.fecha_creacion)
        )
        return list(session.exec(statement).all())

    def get_latest_plan_version(self, session: Session, carrera_codigo: str):
        """Get the most recent plan version for a carrera, or None."""
        from sqlmodel import select
        from src.database.models import PlanCarreraVersionDB

        statement = (
            select(PlanCarreraVersionDB)
            .where(PlanCarreraVersionDB.carrera_codigo == carrera_codigo)
            .order_by(PlanCarreraVersionDB.fecha_creacion.desc())
        )
        return session.exec(statement).first()

    def create_plan_version(
        self,
        session: Session,
        carrera_codigo: str,
        nombre: str,
        descripcion: str = "",
        copy_from_version_id: Optional[str] = None,
    ):
        """
        Create a new plan version for a carrera.
        Optionally copies entries from an existing version.

        Returns:
            The created PlanCarreraVersionDB instance.
        """
        import uuid as uuid_mod
        from datetime import date as date_type
        from src.database.models import PlanCarreraVersionDB, PlanEstudioDB
        from sqlmodel import select

        # Verify carrera exists
        carrera = self.crud.get(session, carrera_codigo)
        if carrera is None:
            raise EntityNotFoundError("Carrera", carrera_codigo)

        version_id = str(uuid_mod.uuid4())
        version = PlanCarreraVersionDB(
            id=version_id,
            carrera_codigo=carrera_codigo,
            nombre=nombre,
            descripcion=descripcion,
            fecha_creacion=date_type.today(),
        )
        session.add(version)
        session.flush()

        # Copy entries from source version if specified
        if copy_from_version_id:
            entries = session.exec(
                select(PlanEstudioDB)
                .where(PlanEstudioDB.plan_version_id == copy_from_version_id)
            ).all()

            for entry in entries:
                new_entry = PlanEstudioDB(
                    plan_version_id=version_id,
                    materia_codigo=entry.materia_codigo,
                    carrera_codigo=entry.carrera_codigo,
                    anio_plan=entry.anio_plan,
                    cuatrimestre_plan=entry.cuatrimestre_plan,
                    correlativas=entry.correlativas,
                )
                session.add(new_entry)

        session.commit()
        session.refresh(version)
        return version

    def update_plan_version(
        self,
        session: Session,
        plan_version_id: str,
        nombre: Optional[str] = None,
        descripcion: Optional[str] = None,
    ):
        """Update name/description of a plan version."""
        from src.database.models import PlanCarreraVersionDB

        version = session.get(PlanCarreraVersionDB, plan_version_id)
        if version is None:
            raise EntityNotFoundError("PlanCarreraVersion", plan_version_id)

        if nombre is not None:
            version.nombre = nombre
        if descripcion is not None:
            version.descripcion = descripcion

        session.add(version)
        session.commit()
        session.refresh(version)
        return version

    def get_materias(
        self, session: Session, carrera_codigo: str,
        plan_version_id: Optional[str] = None,
    ) -> List[Materia]:
        """
        Get all materias associated with a carrera.
        If plan_version_id is provided, filters by that version.
        Otherwise returns materias from any version (deduplicated).
        """
        from sqlmodel import select
        from src.database.models import PlanEstudioDB

        statement = (
            select(MateriaDB)
            .join(PlanEstudioDB, MateriaDB.codigo == PlanEstudioDB.materia_codigo)
            .where(PlanEstudioDB.carrera_codigo == carrera_codigo)
        )

        if plan_version_id:
            statement = statement.where(PlanEstudioDB.plan_version_id == plan_version_id)
        else:
            statement = statement.distinct()

        results = session.exec(statement).all()
        return [to_domain(r) for r in results]

    def add_materia(
        self,
        session: Session,
        carrera_codigo: str,
        materia_codigo: str,
        plan_version_id: str,
        anio_plan: int = 1,
        cuatrimestre_plan: str = "1C",
    ) -> bool:
        """
        Associate a materia with a carrera in a specific plan version.

        Returns:
            True if the association was created, False if it already exists
        """
        from src.database.models import PlanEstudioDB
        from src.database.crud import materia_crud
        from sqlmodel import select

        # Verify carrera exists
        carrera = self.crud.get(session, carrera_codigo)
        if carrera is None:
            raise EntityNotFoundError("Carrera", carrera_codigo)

        # Verify materia exists
        materia = materia_crud.get(session, materia_codigo)
        if materia is None:
            raise EntityNotFoundError("Materia", materia_codigo)

        # Check if link already exists for this version
        existing = session.exec(
            select(PlanEstudioDB).where(
                PlanEstudioDB.carrera_codigo == carrera_codigo,
                PlanEstudioDB.materia_codigo == materia_codigo,
                PlanEstudioDB.plan_version_id == plan_version_id,
            )
        ).first()

        if existing:
            return False

        link = PlanEstudioDB(
            plan_version_id=plan_version_id,
            carrera_codigo=carrera_codigo,
            materia_codigo=materia_codigo,
            anio_plan=anio_plan,
            cuatrimestre_plan=cuatrimestre_plan,
        )
        session.add(link)
        session.commit()
        return True

    def remove_materia(
        self, session: Session, carrera_codigo: str, materia_codigo: str,
        plan_version_id: str,
    ) -> bool:
        """
        Remove the association between a materia and a carrera in a specific plan version.
        """
        from src.database.models import PlanEstudioDB
        from sqlmodel import select

        link = session.exec(
            select(PlanEstudioDB).where(
                PlanEstudioDB.carrera_codigo == carrera_codigo,
                PlanEstudioDB.materia_codigo == materia_codigo,
                PlanEstudioDB.plan_version_id == plan_version_id,
            )
        ).first()

        if link is None:
            return False

        session.delete(link)
        session.commit()
        return True

    def get_children_count(
        self, session: Session, carrera_codigo: str,
        plan_version_id: Optional[str] = None,
    ) -> int:
        """Get the count of materias associated with a carrera (optionally filtered by version)."""
        from sqlmodel import select, func
        from src.database.models import PlanEstudioDB

        statement = select(func.count()).where(
            PlanEstudioDB.carrera_codigo == carrera_codigo
        )
        if plan_version_id:
            statement = statement.where(PlanEstudioDB.plan_version_id == plan_version_id)
        return session.exec(statement).one()

    def get_materias_by_year_and_semester(
        self,
        session: Session,
        carrera_codigo: str,
        anio: int,
        plan_version_id: Optional[str] = None,
        cuatrimestre: Optional[str] = None,
    ) -> List[Tuple[Materia, int, str]]:
        """
        Get materias for a carrera filtered by year and optionally semester/version.
        """
        from sqlmodel import select
        from src.database.models import PlanEstudioDB

        statement = (
            select(MateriaDB, PlanEstudioDB.anio_plan, PlanEstudioDB.cuatrimestre_plan)
            .join(PlanEstudioDB, MateriaDB.codigo == PlanEstudioDB.materia_codigo)
            .where(
                PlanEstudioDB.carrera_codigo == carrera_codigo,
                PlanEstudioDB.anio_plan == anio,
            )
        )

        if plan_version_id:
            statement = statement.where(PlanEstudioDB.plan_version_id == plan_version_id)

        if cuatrimestre is not None:
            statement = statement.where(PlanEstudioDB.cuatrimestre_plan == cuatrimestre)

        results = session.exec(statement).all()
        return [(to_domain(materia_db), anio, cuatri) for materia_db, anio, cuatri in results]


# =============================================================================
# Service Instances (Singletons)
# =============================================================================

# Pre-instantiated services for convenience
materia_service = MateriaService()
comision_service = ComisionService()
aula_service = AulaService()
horario_service = HorarioService()
carrera_service = CarreraService()
