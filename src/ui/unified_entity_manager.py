"""
Unified Entity Manager Module.

Provides a consolidated interface for managing all domain entities through
a single unified interface, supporting CRUD operations for all entity types.
"""

from typing import Any, Callable, Dict, List, Optional, Tuple, Type

import streamlit as st
from pydantic import BaseModel

# Domain models
from src.domain.problem.alumno import Alumno
from src.domain.problem.materia import Materia
from src.domain.problem.comision import Comision
from src.domain.problem.horario_cronograma import HorarioCronograma
from src.domain.problem.aula import Aula
from src.domain.problem.clase import Clase
from src.domain.solution.inscripcion import Inscripcion
from src.domain.solution.asistencia import Asistencia
from src.domain.solution.asignacion_aula import AsignacionAula

# Database models and CRUD operations
from src.database.models import (
    AlumnoDB, MateriaDB, ComisionDB, HorarioCronogramaDB,
    AulaDB, ClaseDB, InscripcionDB, AsistenciaDB, AsignacionAulaDB,
)
from src.database.crud import (
    alumno_crud, materia_crud, comision_crud, horario_crud,
    aula_crud, clase_crud, inscripcion_crud, asistencia_crud, asignacion_crud,
    CRUDBase,
)
from src.database.connection import get_session
from src.database.converters import to_db, to_domain

# UI components
from src.ui.crud_form_renderer import CRUDFormRenderer


class EntityConfig:
    """Configuration for a single entity type."""
    
    def __init__(
        self,
        domain_model: Type[BaseModel],
        db_model: Type,
        crud: CRUDBase,
        id_field: str,
        display_name: str,
        display_name_plural: str,
        icon: str = "📄",
        list_display_fields: List[str] = None,
        exclude_fields: List[str] = None,
    ):
        """
        Initialize entity configuration.
        
        Args:
            domain_model: Pydantic domain model class
            db_model: SQLModel database model class
            crud: CRUD instance for database operations
            id_field: Name of the primary key field
            display_name: Human-readable singular name
            display_name_plural: Human-readable plural name
            icon: Emoji icon for the entity
            list_display_fields: Fields to show in list view
            exclude_fields: Fields to exclude from forms
        """
        self.domain_model = domain_model
        self.db_model = db_model
        self.crud = crud
        self.id_field = id_field
        self.display_name = display_name
        self.display_name_plural = display_name_plural
        self.icon = icon
        self.list_display_fields = list_display_fields or []
        self.exclude_fields = exclude_fields or []


# Entity registry mapping entity names to their configurations
ENTITY_REGISTRY: Dict[str, EntityConfig] = {
    "Alumno": EntityConfig(
        domain_model=Alumno,
        db_model=AlumnoDB,
        crud=alumno_crud,
        id_field="legajo",
        display_name="Alumno",
        display_name_plural="Alumnos",
        icon="🎓",
        list_display_fields=["legajo", "nombre", "email", "dni"],
    ),
    "Materia": EntityConfig(
        domain_model=Materia,
        db_model=MateriaDB,
        crud=materia_crud,
        id_field="codigo",
        display_name="Materia",
        display_name_plural="Materias",
        icon="📚",
        list_display_fields=["codigo", "nombre", "cupo", "horas_semanales"],
    ),
    "Comisión": EntityConfig(
        domain_model=Comision,
        db_model=ComisionDB,
        crud=comision_crud,
        id_field="id",
        display_name="Comisión",
        display_name_plural="Comisiones",
        icon="👥",
        list_display_fields=["id", "materia_codigo", "nombre", "numero", "cupo"],
    ),
    "Aula": EntityConfig(
        domain_model=Aula,
        db_model=AulaDB,
        crud=aula_crud,
        id_field="id",
        display_name="Aula",
        display_name_plural="Aulas",
        icon="🏛️",
        list_display_fields=["id", "sede", "nombre", "capacidad", "tipo"],
    ),
    "HorarioCronograma": EntityConfig(
        domain_model=HorarioCronograma,
        db_model=HorarioCronogramaDB,
        crud=horario_crud,
        id_field="id",
        display_name="Horario",
        display_name_plural="Horarios",
        icon="📅",
        list_display_fields=["id", "dia_semana", "hora_inicio", "hora_fin"],
    ),
    "Clase": EntityConfig(
        domain_model=Clase,
        db_model=ClaseDB,
        crud=clase_crud,
        id_field="id",
        display_name="Clase",
        display_name_plural="Clases",
        icon="📖",
        list_display_fields=["id", "comision_id", "horario_id", "dia"],
    ),
    "Inscripción": EntityConfig(
        domain_model=Inscripcion,
        db_model=InscripcionDB,
        crud=inscripcion_crud,
        id_field="id",
        display_name="Inscripción",
        display_name_plural="Inscripciones",
        icon="📝",
        list_display_fields=["id", "alumno_legajo", "comision_id", "fecha_inscripcion", "activa"],
    ),
    "Asistencia": EntityConfig(
        domain_model=Asistencia,
        db_model=AsistenciaDB,
        crud=asistencia_crud,
        id_field="id",
        display_name="Asistencia",
        display_name_plural="Asistencias",
        icon="✅",
        list_display_fields=["id", "alumno_legajo", "clase_id", "fecha", "presente"],
    ),
    "AsignacionAula": EntityConfig(
        domain_model=AsignacionAula,
        db_model=AsignacionAulaDB,
        crud=asignacion_crud,
        id_field="id",
        display_name="Asignación de Aula",
        display_name_plural="Asignaciones de Aula",
        icon="🔗",
        list_display_fields=["id", "clase_id", "aula_id", "fecha_asignacion", "vigente"],
    ),
}


class UnifiedEntityManager:
    """Manages all domain entities through a unified interface."""
    
    @staticmethod
    def get_entity_names() -> List[str]:
        """Get list of all registered entity names."""
        return list(ENTITY_REGISTRY.keys())
    
    @staticmethod
    def get_entity_config(entity_type: str) -> Optional[EntityConfig]:
        """Get configuration for an entity type."""
        return ENTITY_REGISTRY.get(entity_type)
    
    @staticmethod
    def render_entity_selector(key: str = "entity_selector") -> str:
        """
        Render dropdown to select entity type.
        
        Args:
            key: Streamlit widget key
            
        Returns:
            Selected entity type name
        """
        entity_options = [
            f"{config.icon} {name}"
            for name, config in ENTITY_REGISTRY.items()
        ]
        
        selected = st.selectbox(
            "Seleccionar tipo de entidad",
            options=entity_options,
            key=key,
        )
        
        # Extract entity name from selection (remove icon)
        if selected:
            # Find the entity name that matches
            for name, config in ENTITY_REGISTRY.items():
                if selected == f"{config.icon} {name}":
                    return name
        
        return list(ENTITY_REGISTRY.keys())[0]
    
    @staticmethod
    def render_entity_list(
        entity_type: str,
        key: str = None,
        on_view: Callable[[str], None] = None,
        on_edit: Callable[[str], None] = None,
        on_delete: Callable[[str], None] = None,
    ) -> List[Any]:
        """
        Render list of entities with view/edit/delete options.
        
        Args:
            entity_type: Type of entity to list
            key: Streamlit widget key prefix
            on_view: Callback when view button is clicked
            on_edit: Callback when edit button is clicked
            on_delete: Callback when delete button is clicked
            
        Returns:
            List of entities
        """
        config = ENTITY_REGISTRY.get(entity_type)
        if not config:
            st.error(f"Tipo de entidad desconocido: {entity_type}")
            return []
        
        key_prefix = key or f"list_{entity_type}"
        
        # Get entities from database
        entities = []
        for session in get_session():
            db_entities = config.crud.get_all(session, limit=1000)
            entities = [to_domain(e) for e in db_entities]
        
        if not entities:
            st.info(f"No hay {config.display_name_plural.lower()} registrados.")
            return []
        
        st.subheader(f"{config.icon} {config.display_name_plural} ({len(entities)})")
        
        # Display entities in a table-like format
        for i, entity in enumerate(entities):
            entity_dict = entity.model_dump()
            entity_id = str(entity_dict.get(config.id_field, i))
            
            with st.container():
                cols = st.columns([3, 1, 1, 1])
                
                # Display key fields
                with cols[0]:
                    display_parts = []
                    for field in config.list_display_fields[:3]:
                        if field in entity_dict:
                            value = entity_dict[field]
                            display_parts.append(f"**{field}**: {value}")
                    st.markdown(" | ".join(display_parts))
                
                # Action buttons
                with cols[1]:
                    if st.button("👁️ Ver", key=f"{key_prefix}_view_{entity_id}"):
                        if on_view:
                            on_view(entity_id)
                        else:
                            st.session_state[f"{key_prefix}_selected_id"] = entity_id
                            st.session_state[f"{key_prefix}_operation"] = "read"
                
                with cols[2]:
                    if st.button("✏️ Editar", key=f"{key_prefix}_edit_{entity_id}"):
                        if on_edit:
                            on_edit(entity_id)
                        else:
                            st.session_state[f"{key_prefix}_selected_id"] = entity_id
                            st.session_state[f"{key_prefix}_operation"] = "update"
                
                with cols[3]:
                    if st.button("🗑️ Eliminar", key=f"{key_prefix}_delete_{entity_id}"):
                        if on_delete:
                            on_delete(entity_id)
                        else:
                            st.session_state[f"{key_prefix}_selected_id"] = entity_id
                            st.session_state[f"{key_prefix}_operation"] = "delete"
                
                st.divider()
        
        return entities
    
    @staticmethod
    def _create_crud_functions(config: EntityConfig) -> Tuple[Callable, Callable, Callable, Callable]:
        """
        Create CRUD wrapper functions for an entity type.
        
        Returns:
            Tuple of (create_func, read_func, update_func, delete_func)
        """
        def create_func(instance: BaseModel, **kwargs) -> BaseModel:
            """Create a new entity."""
            for session in get_session():
                db_instance = to_db(instance)
                created = config.crud.create(session, db_instance)
                return to_domain(created)
            return None
        
        def read_func(entity_id: str, **kwargs) -> Optional[BaseModel]:
            """Read an entity by ID."""
            for session in get_session():
                db_instance = config.crud.get(session, entity_id)
                if db_instance:
                    return to_domain(db_instance)
            return None
        
        def update_func(instance: BaseModel, **kwargs) -> BaseModel:
            """Update an existing entity."""
            for session in get_session():
                db_instance = to_db(instance)
                updated = config.crud.update(session, db_instance)
                return to_domain(updated)
            return None
        
        def delete_func(entity_id: str, **kwargs) -> bool:
            """Delete an entity by ID."""
            for session in get_session():
                return config.crud.delete(session, entity_id)
            return False
        
        return create_func, read_func, update_func, delete_func
    
    @staticmethod
    def render_entity_crud(
        entity_type: str,
        operation: str,
        entity_id: str = None,
        key: str = None,
    ) -> Optional[Any]:
        """
        Render CRUD form for selected entity and operation.
        
        Args:
            entity_type: Type of entity
            operation: One of "create", "read", "update", "delete"
            entity_id: ID of entity (required for read, update, delete)
            key: Streamlit widget key prefix
            
        Returns:
            Result of the operation
        """
        config = ENTITY_REGISTRY.get(entity_type)
        if not config:
            st.error(f"Tipo de entidad desconocido: {entity_type}")
            return None
        
        key_prefix = key or f"crud_{entity_type}"
        
        # Create CRUD wrapper functions
        create_func, read_func, update_func, delete_func = UnifiedEntityManager._create_crud_functions(config)
        
        # Render appropriate form based on operation
        return CRUDFormRenderer.render_crud_form(
            model=config.domain_model,
            crud_create_func=create_func,
            crud_read_func=read_func,
            crud_update_func=update_func,
            crud_delete_func=delete_func,
            entity_id=entity_id,
            operation=operation,
            key=key_prefix,
            exclude_fields=config.exclude_fields,
            id_field=config.id_field,
        )

    @staticmethod
    def render_entity_data_table(
        entity_type: str,
        key: str = None,
    ) -> None:
        """
        Render a dynamic data table displaying all records for the selected entity.
        
        Args:
            entity_type: Type of entity to display
            key: Streamlit widget key prefix
        """
        config = ENTITY_REGISTRY.get(entity_type)
        if not config:
            st.error(f"Tipo de entidad desconocido: {entity_type}")
            return
        
        key_prefix = key or f"data_table_{entity_type}"
        
        # Get entities from database
        entities = []
        for session in get_session():
            db_entities = config.crud.get_all(session, limit=1000)
            entities = [to_domain(e) for e in db_entities]
        
        st.subheader(f"{config.icon} Datos de {config.display_name_plural}")
        
        if not entities:
            st.info(f"No hay {config.display_name_plural.lower()} registrados.")
            return
        
        # Convert entities to list of dicts for dataframe
        data = [entity.model_dump() for entity in entities]
        
        # Display count
        st.caption(f"Total: {len(data)} registros")
        
        # Column configuration for better display
        column_config = {}
        
        # Mark ID field as primary
        if config.id_field:
            column_config[config.id_field] = st.column_config.TextColumn(
                config.id_field.upper(),
                help=f"Identificador único de {config.display_name}",
            )
        
        # Render interactive dataframe
        st.dataframe(
            data,
            use_container_width=True,
            hide_index=True,
            column_config=column_config,
            key=f"{key_prefix}_dataframe",
        )
    
    @staticmethod
    def render_unified_interface(key: str = "unified_manager") -> None:
        """
        Render complete unified entity management interface.
        
        This is the main entry point for the unified entity manager.
        
        Args:
            key: Streamlit widget key prefix
        """
        st.title("🎛️ Gestión Unificada de Entidades")
        
        # Initialize session state
        if f"{key}_entity_type" not in st.session_state:
            st.session_state[f"{key}_entity_type"] = list(ENTITY_REGISTRY.keys())[0]
        if f"{key}_operation" not in st.session_state:
            st.session_state[f"{key}_operation"] = "list"
        if f"{key}_selected_id" not in st.session_state:
            st.session_state[f"{key}_selected_id"] = None
        
        # Entity type selector
        col1, col2 = st.columns([2, 1])
        
        with col1:
            selected_entity = UnifiedEntityManager.render_entity_selector(
                key=f"{key}_selector"
            )
            st.session_state[f"{key}_entity_type"] = selected_entity
        
        with col2:
            config = ENTITY_REGISTRY.get(selected_entity)
            if config:
                if st.button(f"➕ Crear {config.display_name}", key=f"{key}_create_btn"):
                    st.session_state[f"{key}_operation"] = "create"
                    st.session_state[f"{key}_selected_id"] = None
        
        st.divider()
        
        # Get current state
        entity_type = st.session_state[f"{key}_entity_type"]
        operation = st.session_state[f"{key}_operation"]
        selected_id = st.session_state[f"{key}_selected_id"]
        
        # Define callbacks for list actions
        def on_view(entity_id: str):
            st.session_state[f"{key}_selected_id"] = entity_id
            st.session_state[f"{key}_operation"] = "read"
        
        def on_edit(entity_id: str):
            st.session_state[f"{key}_selected_id"] = entity_id
            st.session_state[f"{key}_operation"] = "update"
        
        def on_delete(entity_id: str):
            st.session_state[f"{key}_selected_id"] = entity_id
            st.session_state[f"{key}_operation"] = "delete"
        
        # Render based on current operation
        if operation == "list":
            if UnifiedEntityManager.render_entity_list(
                entity_type=entity_type,
                key=f"{key}_list",
                on_view=on_view,
                on_edit=on_edit,
                on_delete=on_delete,
            ):
                UnifiedEntityManager.render_entity_data_table(
                entity_type=entity_type,
                key=f"{key}_summary_table"
                )
        
        elif operation == "create":
            # Back button
            if st.button("← Volver a la lista", key=f"{key}_back_create"):
                st.session_state[f"{key}_operation"] = "list"
                st.rerun()
            
            result = UnifiedEntityManager.render_entity_crud(
                entity_type=entity_type,
                operation="create",
                key=f"{key}_create",
            )
            
            if result:
                st.session_state[f"{key}_operation"] = "list"
                st.rerun()
        
        elif operation == "read":
            # Back button
            if st.button("← Volver a la lista", key=f"{key}_back_read"):
                st.session_state[f"{key}_operation"] = "list"
                st.rerun()
            
            UnifiedEntityManager.render_entity_crud(
                entity_type=entity_type,
                operation="read",
                entity_id=selected_id,
                key=f"{key}_read",
            )
        
        elif operation == "update":
            # Back button
            if st.button("← Volver a la lista", key=f"{key}_back_update"):
                st.session_state[f"{key}_operation"] = "list"
                st.rerun()
            
            result = UnifiedEntityManager.render_entity_crud(
                entity_type=entity_type,
                operation="update",
                entity_id=selected_id,
                key=f"{key}_update",
            )
            
            if result:
                st.session_state[f"{key}_operation"] = "list"
                st.rerun()
        
        elif operation == "delete":
            # Back button
            if st.button("← Volver a la lista", key=f"{key}_back_delete"):
                st.session_state[f"{key}_operation"] = "list"
                st.rerun()
            
            result = UnifiedEntityManager.render_entity_crud(
                entity_type=entity_type,
                operation="delete",
                entity_id=selected_id,
                key=f"{key}_delete",
            )
            
            if result:
                st.session_state[f"{key}_operation"] = "list"
                st.rerun()
        
        else:
            # Default to list view
            st.session_state[f"{key}_operation"] = "list"
            st.rerun()
