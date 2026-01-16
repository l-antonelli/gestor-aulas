"""
Specialized form renderer for Materia entities with carrera relationship handling.

This module provides custom form rendering for Materia entities that includes
many-to-many carrera selection and validation.
"""

from typing import Any, Dict, List, Optional

import streamlit as st
from sqlmodel import Session

from src.domain.problem.materia import Materia
from src.ui.form_input_renderer import FormInputRenderer
from src.ui.many_to_many_selector import ManyToManySelector
from src.services.crud_services import materia_service


class MateriaFormRenderer:
    """Specialized form renderer for Materia entities."""

    @staticmethod
    def render_materia_create_form(
        session: Session,
        key: str = None,
        exclude_fields: List[str] = None,
        custom_labels: Dict[str, str] = None,
    ) -> Optional[Dict[str, Any]]:
        """
        Render create form for Materia with carrera selection.
        
        Args:
            session: Database session
            key: Streamlit form key
            exclude_fields: Fields to exclude from form
            custom_labels: Custom labels for fields
            
        Returns:
            Dictionary with form data including selected carreras, or None if not submitted
        """
        form_key = key or "create_materia_form"
        
        with st.form(key=form_key):
            st.subheader("Crear Materia")
            
            # Render standard materia fields (excluding carreras)
            all_exclude = list(exclude_fields or [])
            
            form_data = FormInputRenderer.render_form_input(
                model=Materia,
                key=f"{form_key}_input",
                exclude_fields=all_exclude,
                custom_labels=custom_labels,
            )
            
            # Add carrera selection
            st.markdown("### Asignación de Carreras")
            selected_carreras = ManyToManySelector.render_carrera_selector_for_materia(
                session=session,
                key=f"{form_key}_carreras",
            )
            
            submitted = st.form_submit_button("Crear Materia")
            
            if submitted:
                # Validate form data
                is_valid, errors = FormInputRenderer.validate_form_data(form_data, Materia)
                
                # Validate carrera selection
                if not selected_carreras:
                    if "carreras" not in errors:
                        errors["carreras"] = []
                    errors["carreras"].append("Debe seleccionar al menos una carrera")
                    is_valid = False
                
                if not is_valid:
                    FormInputRenderer.display_validation_errors(errors)
                    return None
                
                # Add carreras to form data
                form_data["carreras"] = selected_carreras
                return form_data
        
        return None
    
    @staticmethod
    def render_materia_update_form(
        materia_codigo: str,
        session: Session,
        key: str = None,
        exclude_fields: List[str] = None,
        custom_labels: Dict[str, str] = None,
    ) -> Optional[Dict[str, Any]]:
        """
        Render update form for Materia with carrera selection.
        
        Args:
            materia_codigo: The materia codigo to update
            session: Database session
            key: Streamlit form key
            exclude_fields: Fields to exclude from form
            custom_labels: Custom labels for fields
            
        Returns:
            Dictionary with form data including selected carreras, or None if not submitted
        """
        form_key = key or f"update_materia_{materia_codigo}_form"
        
        # Get existing materia
        try:
            existing_materia = materia_service.get(session, materia_codigo)
            if existing_materia is None:
                st.error(f"Materia con código '{materia_codigo}' no encontrada")
                return None
        except Exception as e:
            st.error(f"Error al cargar materia: {str(e)}")
            return None
        
        # Get current carreras
        try:
            current_carreras = materia_service.get_carreras(session, materia_codigo)
            current_carrera_codigos = [c.codigo for c in current_carreras]
        except Exception as e:
            st.error(f"Error al cargar carreras: {str(e)}")
            current_carrera_codigos = []
        
        # Extract default values from existing materia
        if hasattr(existing_materia, "model_dump"):
            default_values = existing_materia.model_dump()
        else:
            default_values = dict(existing_materia)
        
        # Determine fields to exclude (including codigo field)
        all_exclude = list(exclude_fields or [])
        if "codigo" not in all_exclude:
            all_exclude.append("codigo")
        
        with st.form(key=form_key):
            st.subheader("Editar Materia")
            
            # Show codigo as read-only
            st.text_input(
                "Código",
                value=materia_codigo,
                disabled=True,
                key=f"{form_key}_codigo_display",
            )
            
            # Render standard materia fields
            form_data = FormInputRenderer.render_form_input(
                model=Materia,
                key=f"{form_key}_input",
                exclude_fields=all_exclude,
                custom_labels=custom_labels,
                default_values=default_values,
            )
            
            # Add carrera selection
            st.markdown("### Asignación de Carreras")
            selected_carreras = ManyToManySelector.render_carrera_selector_for_materia(
                session=session,
                current_carrera_codigos=current_carrera_codigos,
                key=f"{form_key}_carreras",
            )
            
            submitted = st.form_submit_button("Actualizar Materia")
            
            if submitted:
                # Add back the codigo field
                form_data["codigo"] = materia_codigo
                
                # Validate form data
                is_valid, errors = FormInputRenderer.validate_form_data(form_data, Materia)
                
                # Validate carrera selection
                if not selected_carreras:
                    if "carreras" not in errors:
                        errors["carreras"] = []
                    errors["carreras"].append("Debe seleccionar al menos una carrera")
                    is_valid = False
                
                if not is_valid:
                    FormInputRenderer.display_validation_errors(errors)
                    return None
                
                # Add carreras to form data
                form_data["carreras"] = selected_carreras
                return form_data
        
        return None
    
    @staticmethod
    def create_materia_with_carreras(
        form_data: Dict[str, Any],
        session: Session,
    ) -> Optional[Materia]:
        """
        Create a materia with carrera associations.
        
        Args:
            form_data: Form data including carreras
            session: Database session
            
        Returns:
            Created Materia instance or None if failed
        """
        try:
            # Extract carreras from form data
            carrera_codigos = form_data.pop("carreras", [])
            
            # Create materia instance
            materia = Materia(**form_data)
            
            # Create materia in database
            created_materia = materia_service.create(session, materia)
            
            # Set carrera associations
            if carrera_codigos:
                materia_service.set_carreras(session, created_materia.codigo, carrera_codigos)
            
            return created_materia
            
        except Exception as e:
            st.error(f"Error al crear materia: {str(e)}")
            return None
    
    @staticmethod
    def update_materia_with_carreras(
        form_data: Dict[str, Any],
        session: Session,
    ) -> Optional[Materia]:
        """
        Update a materia with carrera associations.
        
        Args:
            form_data: Form data including carreras
            session: Database session
            
        Returns:
            Updated Materia instance or None if failed
        """
        try:
            # Extract carreras from form data
            carrera_codigos = form_data.pop("carreras", [])
            materia_codigo = form_data["codigo"]
            
            # Create materia instance
            materia = Materia(**form_data)
            
            # Update materia in database
            updated_materia = materia_service.update(session, materia)
            
            # Update carrera associations
            if carrera_codigos:
                materia_service.set_carreras(session, materia_codigo, carrera_codigos)
            
            return updated_materia
            
        except Exception as e:
            st.error(f"Error al actualizar materia: {str(e)}")
            return None