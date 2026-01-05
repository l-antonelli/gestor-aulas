"""
Cascading Operations Module.

Handles cascading creation and deletion of related entities based on
relationship metadata configuration.
"""

from typing import Any, Callable, Dict, List, Optional, Tuple, Type

from pydantic import BaseModel
from sqlmodel import Session

from src.services.relationship_metadata import RelationshipMetadata
from src.services.relationship_registry import RelationshipRegistry


class CascadingOperations:
    """
    Handles cascading creation and deletion of related entities.
    
    This class implements cascading operations based on relationship metadata,
    allowing automatic creation of related entities and proper handling of
    deletion based on configured delete behavior.
    """
    
    @staticmethod
    def create_with_cascading(
        parent_instance: BaseModel,
        parent_crud_func: Callable,
        session: Session,
    ) -> Tuple[BaseModel, List[BaseModel]]:
        """
        Create a parent entity and any cascading related entities.
        
        This method:
        1. Creates the parent entity using the provided CRUD function
        2. Checks for relationships with cascading_create=True
        3. Creates default child entities for those relationships
        4. Returns both the parent and all created children
        
        Args:
            parent_instance: The parent entity to create
            parent_crud_func: CRUD function to create the parent (accepts session, instance)
            session: Database session
            
        Returns:
            Tuple of (created_parent, list_of_created_children)
            
        Example:
            ```python
            materia = Materia(codigo="MAT101", nombre="Cálculo", cupo=30)
            created_materia, children = CascadingOperations.create_with_cascading(
                parent_instance=materia,
                parent_crud_func=materia_crud.create,
                session=session
            )
            # children will contain the auto-created "Comisión Única"
            ```
        """
        # Create the parent entity first
        created_parent = parent_crud_func(session, parent_instance)
        
        # Get the domain model type from the DB model
        parent_model = CascadingOperations._get_domain_model_for_db_model(type(parent_instance))
        if not parent_model:
            # If we can't map to domain model, return early
            return created_parent, []
        
        # Get all relationships for this parent model
        relationships = RelationshipRegistry.get_relationships_for_model(parent_model)
        
        # Track created children
        created_children: List[BaseModel] = []
        
        # Process each relationship with cascading_create enabled
        for relationship in relationships:
            if not relationship.cascading_create:
                continue
            
            try:
                # Create child entity with cascading defaults
                child_instance = CascadingOperations.apply_cascading_defaults(
                    parent_instance=created_parent,
                    child_model=relationship.child_model,
                    defaults=relationship.cascading_create_defaults,
                    foreign_key_field=relationship.foreign_key_field,
                )
                
                # Get CRUD function for child model
                # We need to import the appropriate CRUD function based on the child model
                child_crud_func = CascadingOperations._get_crud_func_for_model(
                    relationship.child_model
                )
                
                if child_crud_func:
                    created_child = child_crud_func(session, child_instance)
                    created_children.append(created_child)
                    
            except Exception as e:
                # Log error but don't fail parent creation
                # This matches requirement 2.5: cascading creation failure should not prevent parent creation
                print(f"Warning: Failed to create cascading child for {relationship.get_child_model_name()}: {e}")
                continue
        
        return created_parent, created_children
    
    @staticmethod
    def apply_cascading_defaults(
        parent_instance: BaseModel,
        child_model: Type[BaseModel],
        defaults: Dict[str, Any],
        foreign_key_field: str,
    ) -> BaseModel:
        """
        Apply cascading creation defaults to a child entity.
        
        This method:
        1. Extracts the parent's primary key value
        2. Merges provided defaults with parent-derived values
        3. Creates a child instance with the merged data
        4. Converts to DB model for persistence
        
        Args:
            parent_instance: The parent entity
            child_model: The child model class (domain model)
            defaults: Default values for the child entity
            foreign_key_field: Field in child that references parent
            
        Returns:
            Child entity instance (DB model) with defaults applied
            
        Example:
            ```python
            comision = CascadingOperations.apply_cascading_defaults(
                parent_instance=materia,
                child_model=Comision,
                defaults={"nombre": "Comisión Única", "numero": 1},
                foreign_key_field="materia_codigo"
            )
            # comision will have materia_codigo set to materia.codigo
            # and nombre="Comisión Única", numero=1
            ```
        """
        from src.database.converters import to_db
        
        # Get parent's primary key value
        parent_pk_value = CascadingOperations._get_primary_key_value(parent_instance)
        
        # Start with defaults
        child_data = dict(defaults)
        
        # Set foreign key to parent's primary key
        child_data[foreign_key_field] = parent_pk_value
        
        # Apply parent-derived defaults
        # For example, if defaults specify to copy a field from parent
        for key, value in defaults.items():
            if isinstance(value, str) and value.startswith("parent."):
                # Extract field name from parent
                parent_field = value.replace("parent.", "")
                if hasattr(parent_instance, parent_field):
                    child_data[key] = getattr(parent_instance, parent_field)
        
        # Handle cupo copying from parent if not specified
        if "cupo" not in child_data and hasattr(parent_instance, "cupo"):
            child_data["cupo"] = parent_instance.cupo
        
        # Generate ID if not provided
        if "id" not in child_data:
            child_data["id"] = CascadingOperations._generate_child_id(
                parent_instance, child_model, child_data
            )
        
        # Create child instance (domain model)
        child_domain_instance = child_model(**child_data)
        
        # Convert to DB model
        child_db_instance = to_db(child_domain_instance)
        
        return child_db_instance
    
    @staticmethod
    def delete_with_cascading(
        parent_id: str,
        parent_model: Type[BaseModel],
        parent_crud_func: Callable,
        session: Session,
    ) -> bool:
        """
        Delete a parent entity and handle related entities based on delete_behavior.
        
        This method implements three delete behaviors:
        - "cascade": Delete parent and all children
        - "restrict": Prevent deletion if children exist
        - "soft_delete": Mark parent as deleted but keep children
        
        Args:
            parent_id: ID of the parent entity to delete
            parent_model: The parent model class
            parent_crud_func: CRUD function to delete the parent (accepts session, id)
            session: Database session
            
        Returns:
            True if deletion was successful, False otherwise
            
        Raises:
            ValueError: If delete_behavior is "restrict" and children exist
            
        Example:
            ```python
            success = CascadingOperations.delete_with_cascading(
                parent_id="MAT101",
                parent_model=Materia,
                parent_crud_func=materia_crud.delete,
                session=session
            )
            ```
        """
        # Get all relationships for this parent model
        relationships = RelationshipRegistry.get_relationships_for_model(parent_model)
        
        # Check delete behavior for each relationship
        for relationship in relationships:
            if relationship.delete_behavior == "restrict":
                # Check if children exist
                children = CascadingOperations._get_children(
                    parent_id=parent_id,
                    relationship=relationship,
                    session=session,
                )
                
                if children:
                    raise ValueError(
                        f"Cannot delete {parent_model.__name__} with ID '{parent_id}': "
                        f"{len(children)} related {relationship.get_child_model_name()} entities exist. "
                        f"Delete behavior is set to 'restrict'."
                    )
            
            elif relationship.delete_behavior == "cascade":
                # Delete all children first
                children = CascadingOperations._get_children(
                    parent_id=parent_id,
                    relationship=relationship,
                    session=session,
                )
                
                child_crud_func = CascadingOperations._get_crud_func_for_model(
                    relationship.child_model
                )
                
                if child_crud_func:
                    for child in children:
                        child_id = CascadingOperations._get_primary_key_value(child)
                        try:
                            child_crud_func(session, child_id)
                        except Exception as e:
                            print(f"Warning: Failed to delete child {child_id}: {e}")
            
            elif relationship.delete_behavior == "soft_delete":
                # Mark parent as deleted but keep children
                # This would require a "deleted" field in the model
                # For now, we'll just skip deletion
                print(f"Soft delete not fully implemented for {parent_model.__name__}")
                return False
        
        # Delete the parent
        return parent_crud_func(session, parent_id)
    
    # Helper methods
    
    @staticmethod
    def _get_primary_key_value(instance: BaseModel) -> Any:
        """
        Extract the primary key value from a model instance.
        
        Tries common primary key field names: id, codigo, legajo.
        """
        for pk_field in ["id", "codigo", "legajo"]:
            if hasattr(instance, pk_field):
                return getattr(instance, pk_field)
        
        # Fallback: try to find a field that looks like a primary key
        if hasattr(instance, "model_fields"):
            for field_name in instance.model_fields.keys():
                if "id" in field_name.lower() or "codigo" in field_name.lower():
                    return getattr(instance, field_name)
        
        raise ValueError(f"Could not determine primary key for {type(instance).__name__}")
    
    @staticmethod
    def _generate_child_id(
        parent_instance: BaseModel,
        child_model: Type[BaseModel],
        child_data: Dict[str, Any],
    ) -> str:
        """
        Generate an ID for a child entity based on parent and child data.
        
        Uses a pattern like: {parent_id}-{child_identifier}
        """
        parent_pk = CascadingOperations._get_primary_key_value(parent_instance)
        
        # Try to use a meaningful identifier from child data
        if "numero" in child_data:
            return f"{parent_pk}-C{child_data['numero']}"
        elif "nombre" in child_data:
            # Use first word of name
            name_part = child_data["nombre"].split()[0][:3].upper()
            return f"{parent_pk}-{name_part}"
        else:
            # Fallback to simple counter
            return f"{parent_pk}-1"
    
    @staticmethod
    def _get_crud_func_for_model(model: Type[BaseModel]) -> Optional[Callable]:
        """
        Get the appropriate CRUD function for a model.
        
        This is a helper to map models to their CRUD functions.
        In a real implementation, this might use a registry or dependency injection.
        """
        from src.database import crud
        
        # Map model names to CRUD functions
        crud_map = {
            "Materia": crud.materia_crud.create,
            "Comision": crud.comision_crud.create,
            "Clase": crud.clase_crud.create,
            "Alumno": crud.alumno_crud.create,
            "Inscripcion": crud.inscripcion_crud.create,
            "Asistencia": crud.asistencia_crud.create,
            "AsignacionAula": crud.asignacion_crud.create,
        }
        
        model_name = model.__name__
        return crud_map.get(model_name)
    
    @staticmethod
    def _get_children(
        parent_id: str,
        relationship: RelationshipMetadata,
        session: Session,
    ) -> List[BaseModel]:
        """
        Get all child entities for a parent.
        
        This queries the database for all children that reference the parent.
        """
        from sqlmodel import select
        
        # Get the database model for the child
        child_db_model = CascadingOperations._get_db_model_for_domain_model(
            relationship.child_model
        )
        
        if not child_db_model:
            return []
        
        # Query for children
        statement = select(child_db_model).where(
            getattr(child_db_model, relationship.foreign_key_field) == parent_id
        )
        
        results = session.exec(statement).all()
        return list(results)
    
    @staticmethod
    def _get_db_model_for_domain_model(domain_model: Type[BaseModel]) -> Optional[Type]:
        """
        Map a domain model to its database model.
        
        This is a helper to convert between domain and database layers.
        """
        from src.database.models import (
            MateriaDB, ComisionDB, ClaseDB, AlumnoDB,
            InscripcionDB, AsistenciaDB, AsignacionAulaDB
        )
        
        db_model_map = {
            "Materia": MateriaDB,
            "Comision": ComisionDB,
            "Clase": ClaseDB,
            "Alumno": AlumnoDB,
            "Inscripcion": InscripcionDB,
            "Asistencia": AsistenciaDB,
            "AsignacionAula": AsignacionAulaDB,
        }
        
        model_name = domain_model.__name__
        return db_model_map.get(model_name)
    
    @staticmethod
    def _get_domain_model_for_db_model(db_model: Type) -> Optional[Type[BaseModel]]:
        """
        Map a database model to its domain model.
        
        This is the reverse of _get_db_model_for_domain_model.
        """
        from src.domain.problem import Materia, Comision, Clase, Alumno
        from src.domain.solution import Inscripcion, Asistencia, AsignacionAula
        
        domain_model_map = {
            "MateriaDB": Materia,
            "ComisionDB": Comision,
            "ClaseDB": Clase,
            "AlumnoDB": Alumno,
            "InscripcionDB": Inscripcion,
            "AsistenciaDB": Asistencia,
            "AsignacionAulaDB": AsignacionAula,
        }
        
        model_name = db_model.__name__
        return domain_model_map.get(model_name)
