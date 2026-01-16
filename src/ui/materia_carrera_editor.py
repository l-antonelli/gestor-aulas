"""
Component for managing Materia-Carrera associations with year and semester.

This component provides an editable table interface for managing the many-to-many
relationship between Materia and Carrera, including curriculum placement (year/semester).
"""

import streamlit as st
import pandas as pd
from sqlmodel import Session, select
from typing import List, Dict, Any

from src.services.crud_services import materia_service, carrera_service
from src.database.models import MateriaCarreraLink


class MateriaCarreraEditor:
    """Editor component for Materia-Carrera associations."""
    
    @staticmethod
    def render_associations_editor(
        session: Session,
        materia_codigo: str,
        key: str = "materia_carrera_editor"
    ) -> None:
        """
        Render an editable table for materia-carrera associations.
        
        Args:
            session: Database session
            materia_codigo: The materia's codigo
            key: Unique key for the component
        """
        st.markdown("### 🎓 Carreras Asociadas")
        
        # Get materia to check if it's annual
        materia = materia_service.get(session, materia_codigo)
        is_anual = materia and materia.periodo == "anual"
        
        if is_anual:
            st.info("ℹ️ Esta es una materia **anual**. El cuatrimestre se establece automáticamente en 0 (anual).")
        
        # Get current associations with year/semester info
        associations = MateriaCarreraEditor._get_associations(session, materia_codigo)
        
        if not associations:
            st.info("Esta materia no está asociada a ninguna carrera.")
        else:
            # Create DataFrame for editing
            df = pd.DataFrame(associations)
            
            # For display, convert cuatrimestre 0 to "Anual"
            if is_anual:
                df["cuatrimestre_display"] = "Anual"
            else:
                df["cuatrimestre_display"] = df["cuatrimestre_carrera"]
            
            # Configure column settings
            column_config = {
                "carrera_codigo": st.column_config.TextColumn(
                    "Código Carrera",
                    disabled=True,
                    width="small"
                ),
                "carrera_nombre": st.column_config.TextColumn(
                    "Nombre Carrera",
                    disabled=True,
                    width="medium"
                ),
                "anio_carrera": st.column_config.NumberColumn(
                    "Año",
                    min_value=1,
                    max_value=6,
                    step=1,
                    width="small"
                ),
                "cuatrimestre_display": st.column_config.TextColumn(
                    "Cuatrimestre",
                    disabled=True,
                    width="small"
                ) if is_anual else st.column_config.SelectboxColumn(
                    "Cuatrimestre",
                    options=[1, 2],
                    width="small"
                ),
            }
            
            # Select columns to display
            display_cols = ["carrera_codigo", "carrera_nombre", "anio_carrera", "cuatrimestre_display"]
            
            # Render editable dataframe
            edited_df = st.data_editor(
                df[display_cols],
                column_config=column_config,
                use_container_width=True,
                num_rows="fixed",
                key=f"{key}_table",
                hide_index=True,
            )
            
            # Check for changes (only in editable columns)
            if not df[display_cols].equals(edited_df):
                col1, col2 = st.columns([1, 4])
                with col1:
                    if st.button("💾 Guardar Cambios", key=f"{key}_save"):
                        try:
                            # Restore original cuatrimestre values for saving
                            if is_anual:
                                edited_df["cuatrimestre_carrera"] = 0
                            else:
                                edited_df["cuatrimestre_carrera"] = edited_df["cuatrimestre_display"]
                            
                            # Add carrera_codigo back for saving
                            edited_df["carrera_codigo"] = df["carrera_codigo"]
                            
                            MateriaCarreraEditor._save_changes(
                                session, materia_codigo, edited_df
                            )
                            st.success("✅ Cambios guardados")
                            st.rerun()
                        except Exception as e:
                            st.error(f"❌ Error al guardar: {str(e)}")
                with col2:
                    st.caption("Se detectaron cambios en año o cuatrimestre")
            
            # Delete associations
            st.markdown("#### 🗑️ Desasociar Carrera")
            carreras_to_remove = st.multiselect(
                "Seleccione carreras para desasociar",
                options=[row["carrera_codigo"] for _, row in df.iterrows()],
                format_func=lambda x: f"{x} - {df[df['carrera_codigo']==x]['carrera_nombre'].iloc[0]}",
                key=f"{key}_remove"
            )
            
            if carreras_to_remove:
                if st.button("🗑️ Desasociar Seleccionadas", key=f"{key}_remove_btn"):
                    try:
                        for carrera_codigo in carreras_to_remove:
                            materia_service.remove_carrera(session, materia_codigo, carrera_codigo)
                        st.success(f"✅ {len(carreras_to_remove)} carrera(s) desasociada(s)")
                        st.rerun()
                    except Exception as e:
                        st.error(f"❌ Error: {str(e)}")
        
        # Add new association
        st.markdown("#### ➕ Asociar Nueva Carrera")
        MateriaCarreraEditor._render_add_association(session, materia_codigo, key)
    
    @staticmethod
    def _get_associations(session: Session, materia_codigo: str) -> List[Dict[str, Any]]:
        """Get current associations with carrera details."""
        from src.database.models import CarreraDB
        
        statement = (
            select(
                MateriaCarreraLink.carrera_codigo,
                CarreraDB.nombre,
                MateriaCarreraLink.anio_carrera,
                MateriaCarreraLink.cuatrimestre_carrera
            )
            .join(CarreraDB, MateriaCarreraLink.carrera_codigo == CarreraDB.codigo)
            .where(MateriaCarreraLink.materia_codigo == materia_codigo)
            .order_by(MateriaCarreraLink.anio_carrera, MateriaCarreraLink.cuatrimestre_carrera)
        )
        
        results = session.exec(statement).all()
        
        return [
            {
                "carrera_codigo": carrera_codigo,
                "carrera_nombre": nombre,
                "anio_carrera": anio,
                "cuatrimestre_carrera": cuatri
            }
            for carrera_codigo, nombre, anio, cuatri in results
        ]
    
    @staticmethod
    def _save_changes(session: Session, materia_codigo: str, edited_df: pd.DataFrame) -> None:
        """Save changes to associations."""
        # Update each association
        for _, row in edited_df.iterrows():
            # Delete old link
            statement = select(MateriaCarreraLink).where(
                MateriaCarreraLink.materia_codigo == materia_codigo,
                MateriaCarreraLink.carrera_codigo == row["carrera_codigo"]
            )
            link = session.exec(statement).first()
            
            if link:
                # Update year and semester
                link.anio_carrera = int(row["anio_carrera"])
                link.cuatrimestre_carrera = int(row["cuatrimestre_carrera"])
                session.add(link)
        
        session.commit()
    
    @staticmethod
    def _render_add_association(session: Session, materia_codigo: str, key: str) -> None:
        """Render form to add new association."""
        # Get materia to check if it's annual
        materia = materia_service.get(session, materia_codigo)
        is_anual = materia and materia.periodo == "anual"
        
        # Get available carreras (not already associated)
        all_carreras = carrera_service.get_all(session)
        current_carreras = materia_service.get_carreras(session, materia_codigo)
        current_codigos = {c.codigo for c in current_carreras}
        
        available_carreras = [c for c in all_carreras if c.codigo not in current_codigos]
        
        if not available_carreras:
            st.info("Todas las carreras ya están asociadas a esta materia.")
            return
        
        with st.form(key=f"{key}_add_form"):
            if is_anual:
                col1, col2 = st.columns([3, 1])
            else:
                col1, col2, col3 = st.columns([2, 1, 1])
            
            with col1:
                selected_carrera = st.selectbox(
                    "Carrera",
                    options=[c.codigo for c in available_carreras],
                    format_func=lambda x: f"{x} - {next((c.nombre for c in available_carreras if c.codigo == x), '')}",
                )
            
            with col2:
                anio = st.number_input("Año", min_value=1, max_value=6, value=1, step=1)
            
            # Only show cuatrimestre selector for non-annual materias
            if is_anual:
                cuatrimestre = 0  # 0 for annual materias
                st.caption("Cuatrimestre: Anual (0)")
            else:
                with col3:
                    cuatrimestre = st.selectbox("Cuatrimestre", options=[1, 2])
            
            submitted = st.form_submit_button("➕ Asociar")
            
            if submitted:
                try:
                    materia_service.add_carrera(
                        session, materia_codigo, selected_carrera,
                        anio_carrera=anio,
                        cuatrimestre_carrera=cuatrimestre
                    )
                    st.success(f"✅ Carrera {selected_carrera} asociada")
                    st.rerun()
                except Exception as e:
                    st.error(f"❌ Error: {str(e)}")
