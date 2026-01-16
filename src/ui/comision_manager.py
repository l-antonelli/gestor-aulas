"""
Component for managing Comisiones for a Materia.

This component provides an interface for creating, editing, and deleting
comisiones associated with a materia.
"""

import streamlit as st
import pandas as pd
from sqlmodel import Session
from typing import List

from src.services.crud_services import comision_service, materia_service
from src.domain.problem.comision import Comision


class ComisionManager:
    """Manager component for Materia's Comisiones."""
    
    @staticmethod
    def render_comisiones_manager(
        session: Session,
        materia_codigo: str,
        key: str = "comision_manager"
    ) -> None:
        """
        Render comisiones management interface.
        
        Args:
            session: Database session
            materia_codigo: The materia's codigo
            key: Unique key for the component
        """
        st.markdown("### 👥 Comisiones")
        
        # Get comisiones for this materia
        comisiones = comision_service.get_by_materia(session, materia_codigo)
        
        if not comisiones:
            st.info("Esta materia no tiene comisiones creadas.")
        else:
            # Display comisiones in a table
            comisiones_data = [
                {
                    "ID": c.id,
                    "Nombre": c.nombre,
                    "Número": c.numero,
                    "Cupo": c.cupo,
                    "Descripción": c.descripcion or "-"
                }
                for c in comisiones
            ]
            
            df = pd.DataFrame(comisiones_data)
            st.dataframe(df, use_container_width=True, hide_index=True)
            
            # Delete comisiones
            st.markdown("#### 🗑️ Eliminar Comisión")
            comision_to_delete = st.selectbox(
                "Seleccione comisión para eliminar",
                options=[c.id for c in comisiones],
                format_func=lambda x: f"{x} - {next((c.nombre for c in comisiones if c.id == x), '')}",
                key=f"{key}_delete_select"
            )
            
            if st.button("🗑️ Eliminar Comisión", key=f"{key}_delete_btn"):
                try:
                    comision_service.delete(session, comision_to_delete)
                    st.success(f"✅ Comisión {comision_to_delete} eliminada")
                    st.rerun()
                except Exception as e:
                    st.error(f"❌ Error: {str(e)}")
        
        # Add new comision
        st.markdown("#### ➕ Crear Nueva Comisión")
        ComisionManager._render_create_comision(session, materia_codigo, key)
    
    @staticmethod
    def _render_create_comision(session: Session, materia_codigo: str, key: str) -> None:
        """Render form to create new comision."""
        # Get materia to use its cupo as default
        materia = materia_service.get(session, materia_codigo)
        default_cupo = materia.cupo if materia else 30
        
        # Get existing comisiones to suggest next numero
        existing_comisiones = comision_service.get_by_materia(session, materia_codigo)
        next_numero = len(existing_comisiones) + 1
        
        with st.form(key=f"{key}_create_form"):
            col1, col2 = st.columns(2)
            
            with col1:
                nombre = st.text_input(
                    "Nombre",
                    value=f"Comisión {next_numero}",
                    help="Nombre descriptivo de la comisión"
                )
                
                numero = st.number_input(
                    "Número",
                    min_value=1,
                    value=next_numero,
                    step=1,
                    help="Número de comisión"
                )
            
            with col2:
                cupo = st.number_input(
                    "Cupo",
                    min_value=1,
                    value=default_cupo,
                    step=1,
                    help="Cantidad máxima de alumnos"
                )
                
                descripcion = st.text_input(
                    "Descripción (opcional)",
                    help="Información adicional sobre la comisión"
                )
            
            submitted = st.form_submit_button("➕ Crear Comisión", type="primary")
            
            if submitted:
                try:
                    # Generate ID
                    comision_id = f"{materia_codigo}-C{numero}"
                    
                    # Create comision
                    comision = Comision(
                        id=comision_id,
                        materia_codigo=materia_codigo,
                        nombre=nombre,
                        numero=numero,
                        cupo=cupo,
                        descripcion=descripcion if descripcion else ""
                    )
                    
                    created = comision_service.create(session, comision)
                    st.success(f"✅ Comisión {created.id} creada exitosamente")
                    st.rerun()
                except Exception as e:
                    st.error(f"❌ Error al crear comisión: {str(e)}")
