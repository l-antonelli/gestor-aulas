"""Gestión de Inscripciones - Refactored to use UI components."""

import streamlit as st
from datetime import date
import uuid
from src.database.connection import get_session, init_db
from src.database.crud import inscripcion_crud, alumno_crud, comision_crud
from src.database.converters import to_domain, to_db
from src.domain.solution.inscripcion import Inscripcion
from src.ui.crud_form_renderer import CRUDFormRenderer

# Initialize database
init_db()

st.set_page_config(page_title="Inscripciones", page_icon="📝", layout="wide")
st.title("📝 Gestión de Inscripciones")

tab_list, tab_create, tab_view = st.tabs(["📋 Listado", "➕ Nueva Inscripción", "👁️ Ver Detalle"])


# CRUD wrapper functions for Inscripcion
def create_inscripcion(instance: Inscripcion, **kwargs) -> Inscripcion:
    """Create a new inscripcion."""
    for session in get_session():
        db_instance = to_db(instance)
        created = inscripcion_crud.create(session, db_instance)
        return to_domain(created)
    return None


def read_inscripcion(entity_id: str, **kwargs) -> Inscripcion:
    """Read an inscripcion by id."""
    for session in get_session():
        db_instance = inscripcion_crud.get(session, entity_id)
        if db_instance:
            return to_domain(db_instance)
    return None


def update_inscripcion(instance: Inscripcion, **kwargs) -> Inscripcion:
    """Update an existing inscripcion."""
    for session in get_session():
        db_instance = to_db(instance)
        updated = inscripcion_crud.update(session, db_instance)
        return to_domain(updated)
    return None


def delete_inscripcion(entity_id: str, **kwargs) -> bool:
    """Delete an inscripcion by id."""
    for session in get_session():
        return inscripcion_crud.delete(session, entity_id)
    return False


with tab_list:
    with next(get_session()) as session:
        inscripciones = inscripcion_crud.get_all(session)
        inscripciones_data = []
        for i in inscripciones:
            alumno = alumno_crud.get(session, i.alumno_legajo)
            comision = comision_crud.get(session, i.comision_id)
            inscripciones_data.append({
                "ID": i.id,
                "Alumno": f"{i.alumno_legajo} - {alumno.nombre if alumno else 'N/A'}",
                "Comisión": i.comision_id,
                "Fecha": i.fecha_inscripcion.isoformat(),
                "Activa": "✅" if i.activa else "❌",
            })
    
    if not inscripciones_data:
        st.info("No hay inscripciones registradas.")
    else:
        st.dataframe(inscripciones_data, use_container_width=True, hide_index=True)
        st.caption(f"Total: {len(inscripciones_data)} inscripciones")
        
        st.divider()
        st.subheader("Eliminar Inscripción")
        col1, col2 = st.columns([3, 1])
        with col1:
            id_delete = st.selectbox(
                "Seleccionar inscripción a eliminar",
                options=[i["ID"] for i in inscripciones_data],
                key="delete_inscripcion"
            )
        with col2:
            st.write("")
            st.write("")
            if st.button("🗑️ Eliminar", type="secondary"):
                if delete_inscripcion(id_delete):
                    st.success(f"Inscripción {id_delete} eliminada")
                    st.rerun()
                else:
                    st.error("Error al eliminar la inscripción")

with tab_create:
    with next(get_session()) as session:
        alumnos = alumno_crud.get_all(session)
        comisiones = comision_crud.get_all(session)
    
    if not alumnos:
        st.warning("Primero debes crear al menos un alumno.")
    elif not comisiones:
        st.warning("Primero debes crear al menos una comisión.")
    else:
        # Custom form for inscripcion with relationship selectors
        with st.form("create_inscripcion"):
            st.subheader("Crear Inscripción")
            
            # Generate unique ID
            inscripcion_id = f"INS-{uuid.uuid4().hex[:8].upper()}"
            st.text_input("ID", value=inscripcion_id, disabled=True, key="inscripcion_id_display")
            
            # Relationship selectors
            alumno_legajo = st.selectbox(
                "Alumno",
                options=[a.legajo for a in alumnos],
                format_func=lambda x: f"{x} - {next((a.nombre for a in alumnos if a.legajo == x), '')}"
            )
            comision_id = st.selectbox(
                "Comisión",
                options=[c.id for c in comisiones]
            )
            fecha = st.date_input("Fecha de inscripción", value=date.today())
            activa = st.checkbox("Activa", value=True)
            
            submitted = st.form_submit_button("💾 Guardar", type="primary")
            
            if submitted:
                try:
                    inscripcion = Inscripcion(
                        id=inscripcion_id,
                        alumno_legajo=alumno_legajo,
                        comision_id=comision_id,
                        fecha_inscripcion=fecha,
                        activa=activa
                    )
                    result = create_inscripcion(inscripcion)
                    if result:
                        CRUDFormRenderer.show_operation_feedback(
                            operation="create",
                            success=True,
                            message=f"Inscripción '{inscripcion_id}' creada exitosamente"
                        )
                        st.rerun()
                except Exception as e:
                    CRUDFormRenderer.show_operation_feedback(
                        operation="create",
                        success=False,
                        message=f"Error al crear inscripción: {e}"
                    )

with tab_view:
    with next(get_session()) as session:
        inscripciones = inscripcion_crud.get_all(session)
    
    if not inscripciones:
        st.info("No hay inscripciones para ver.")
    else:
        id_view = st.selectbox(
            "Seleccionar inscripción",
            options=[i.id for i in inscripciones],
            key="view_inscripcion"
        )
        
        if id_view:
            # Use CRUDFormRenderer for read operation
            CRUDFormRenderer.render_read_form(
                model=Inscripcion,
                entity_id=id_view,
                crud_read_func=read_inscripcion,
                custom_labels={
                    "id": "ID",
                    "alumno_legajo": "Legajo del Alumno",
                    "comision_id": "ID de Comisión",
                    "fecha_inscripcion": "Fecha de Inscripción",
                    "activa": "Activa",
                },
                title=f"Detalle de Inscripción: {id_view}",
            )
