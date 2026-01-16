"""
Carrera Status Widget.

Provides UI components for displaying carrera completeness status,
including progress bars, warnings, and summary cards.
"""

import streamlit as st
from sqlmodel import Session
from typing import List

from src.services.carrera_validation import (
    CarreraValidationStatus,
    get_carrera_status,
    get_all_carreras_status,
    get_carreras_incompletas,
    get_carreras_sin_cantidad_definida,
    get_validation_summary,
)


class CarreraStatusWidget:
    """UI components for displaying carrera validation status."""
    
    @staticmethod
    def render_status_badge(status: CarreraValidationStatus) -> None:
        """
        Render a status badge for a carrera.
        
        Args:
            status: CarreraValidationStatus instance
        """
        mensaje = status.get_mensaje_estado()
        nivel = status.nivel_advertencia
        
        if nivel == "success":
            st.success(mensaje)
        elif nivel == "warning":
            st.warning(mensaje)
        else:
            st.error(mensaje)
    
    @staticmethod
    def render_progress_bar(status: CarreraValidationStatus) -> None:
        """
        Render a progress bar showing materia completeness.
        
        Args:
            status: CarreraValidationStatus instance
        """
        if not status.tiene_cantidad_definida:
            st.caption("⚠️ Cantidad de materias no definida")
            return
        
        porcentaje = status.porcentaje_completitud
        
        # Progress bar
        st.progress(porcentaje / 100.0)
        
        # Text below progress bar
        col1, col2 = st.columns(2)
        with col1:
            st.caption(f"{status.materias_asignadas}/{status.cantidad_esperada} materias")
        with col2:
            st.caption(f"{porcentaje:.0f}% completo")
    
    @staticmethod
    def render_status_card(status: CarreraValidationStatus, show_details: bool = True) -> None:
        """
        Render a complete status card for a carrera.
        
        Args:
            status: CarreraValidationStatus instance
            show_details: Whether to show detailed information
        """
        with st.container():
            # Header
            st.markdown(f"### {status.carrera.codigo} - {status.carrera.nombre}")
            
            # Status badge
            CarreraStatusWidget.render_status_badge(status)
            
            # Progress bar
            if status.tiene_cantidad_definida:
                CarreraStatusWidget.render_progress_bar(status)
            
            # Details
            if show_details:
                with st.expander("Ver detalles"):
                    col1, col2 = st.columns(2)
                    
                    with col1:
                        st.write(f"**Título:** {status.carrera.titulo_otorgado}")
                        st.write(f"**Duración:** {status.carrera.duracion_anios} años")
                    
                    with col2:
                        st.write(f"**Materias asignadas:** {status.materias_asignadas}")
                        if status.tiene_cantidad_definida:
                            st.write(f"**Materias esperadas:** {status.cantidad_esperada}")
                            st.write(f"**Materias faltantes:** {status.materias_faltantes}")
    
    @staticmethod
    def render_summary_metrics(session: Session) -> None:
        """
        Render summary metrics for all carreras.
        
        Args:
            session: Database session
        """
        summary = get_validation_summary(session)
        
        col1, col2, col3, col4 = st.columns(4)
        
        with col1:
            st.metric(
                "Total Carreras",
                summary["total_carreras"],
            )
        
        with col2:
            st.metric(
                "Completas",
                summary["carreras_completas"],
                delta=f"{summary['porcentaje_completas']:.0f}%",
                delta_color="normal",
            )
        
        with col3:
            st.metric(
                "Incompletas",
                summary["carreras_incompletas"],
                delta=None if summary["carreras_incompletas"] == 0 else "⚠️",
                delta_color="inverse",
            )
        
        with col4:
            st.metric(
                "Sin Cantidad Definida",
                summary["carreras_sin_cantidad"],
                delta=None if summary["carreras_sin_cantidad"] == 0 else "❌",
                delta_color="inverse",
            )
    
    @staticmethod
    def render_warnings_panel(session: Session) -> None:
        """
        Render a warnings panel showing incomplete carreras.
        
        Args:
            session: Database session
        """
        # Get incomplete carreras
        incompletas = get_carreras_incompletas(session)
        sin_cantidad = get_carreras_sin_cantidad_definida(session)
        
        if not incompletas and not sin_cantidad:
            st.success("✅ Todas las carreras están completas")
            return
        
        st.warning("⚠️ Advertencias de Completitud de Carreras")
        
        # Carreras without cantidad_materias defined
        if sin_cantidad:
            with st.expander(f"❌ Carreras sin cantidad de materias definida ({len(sin_cantidad)})", expanded=True):
                for status in sin_cantidad:
                    st.markdown(f"- **{status.carrera.codigo}**: {status.carrera.nombre} ({status.materias_asignadas} materias asignadas)")
                
                st.info("💡 Defina la cantidad esperada de materias para cada carrera en la página de Carreras.")
        
        # Incomplete carreras
        if incompletas:
            with st.expander(f"⚠️ Carreras incompletas ({len(incompletas)})", expanded=True):
                for status in incompletas:
                    col1, col2 = st.columns([3, 1])
                    
                    with col1:
                        st.markdown(f"**{status.carrera.codigo}**: {status.carrera.nombre}")
                    
                    with col2:
                        st.caption(f"{status.materias_asignadas}/{status.cantidad_esperada}")
                    
                    # Progress bar
                    st.progress(status.porcentaje_completitud / 100.0)
                
                st.info("💡 Asigne las materias faltantes en la página de Materias.")
    
    @staticmethod
    def render_inline_status(session: Session, carrera_codigo: str) -> None:
        """
        Render inline status for a specific carrera (compact view).
        
        Args:
            session: Database session
            carrera_codigo: Carrera codigo
        """
        try:
            status = get_carrera_status(session, carrera_codigo)
            
            if not status.tiene_cantidad_definida:
                st.caption("⚠️ Cantidad no definida")
                return
            
            # Compact progress indicator
            col1, col2 = st.columns([3, 1])
            
            with col1:
                st.progress(status.porcentaje_completitud / 100.0)
            
            with col2:
                st.caption(f"{status.materias_asignadas}/{status.cantidad_esperada}")
            
            # Status icon
            if status.esta_completa:
                st.caption("✅ Completa")
            else:
                st.caption(f"⚠️ Faltan {status.materias_faltantes}")
        
        except Exception as e:
            st.error(f"Error al cargar estado: {str(e)}")
