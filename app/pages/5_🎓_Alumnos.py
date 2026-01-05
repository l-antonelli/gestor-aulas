"""Gestión de Alumnos - Refactored to use UI components."""

import streamlit as st
from src.database.connection import get_session, init_db
from src.database.crud import alumno_crud
from src.database.converters import to_domain, to_db
from src.domain.problem.alumno import Alumno
from src.ui.crud_form_renderer import CRUDFormRenderer

# Initialize database
init_db()

st.set_page_config(page_title="Alumnos", page_icon="🎓", layout="wide")
st.title("🎓 Gestión de Alumnos")

tab_list, tab_create, tab_edit = st.tabs(["📋 Listado", "➕ Nuevo Alumno", "✏️ Editar"])


# CRUD wrapper functions for Alumno
def create_alumno(instance: Alumno, **kwargs) -> Alumno:
    """Create a new alumno."""
    for session in get_session():
        db_instance = to_db(instance)
        created = alumno_crud.create(session, db_instance)
        return to_domain(created)
    return None


def read_alumno(entity_id: str, **kwargs) -> Alumno:
    """Read an alumno by legajo."""
    for session in get_session():
        db_instance = alumno_crud.get(session, entity_id)
        if db_instance:
            return to_domain(db_instance)
    return None


def update_alumno(instance: Alumno, **kwargs) -> Alumno:
    """Update an existing alumno."""
    for session in get_session():
        db_instance = to_db(instance)
        updated = alumno_crud.update(session, db_instance)
        return to_domain(updated)
    return None


def delete_alumno(entity_id: str, **kwargs) -> bool:
    """Delete an alumno by legajo."""
    for session in get_session():
        return alumno_crud.delete(session, entity_id)
    return False


with tab_list:
    with next(get_session()) as session:
        alumnos = alumno_crud.get_all(session)
    
    if not alumnos:
        st.info("No hay alumnos registrados.")
    else:
        data = [
            {
                "Legajo": a.legajo,
                "Nombre": a.nombre,
                "Email": a.email,
                "DNI": a.dni,
            }
            for a in alumnos
        ]
        st.dataframe(data, use_container_width=True, hide_index=True)
        st.caption(f"Total: {len(data)} alumnos")
        
        st.divider()
        st.subheader("Eliminar Alumno")
        col1, col2 = st.columns([3, 1])
        with col1:
            legajo_delete = st.selectbox(
                "Seleccionar alumno a eliminar",
                options=[a.legajo for a in alumnos],
                format_func=lambda x: f"{x} - {next((a.nombre for a in alumnos if a.legajo == x), '')}",
                key="delete_alumno"
            )
        with col2:
            st.write("")
            st.write("")
            if st.button("🗑️ Eliminar", type="secondary"):
                if delete_alumno(legajo_delete):
                    st.success(f"Alumno {legajo_delete} eliminado")
                    st.rerun()
                else:
                    st.error("Error al eliminar el alumno")

with tab_create:
    # Use CRUDFormRenderer for create operation
    result = CRUDFormRenderer.render_create_form(
        model=Alumno,
        crud_create_func=create_alumno,
        key="create_alumno",
        custom_labels={
            "legajo": "Legajo",
            "nombre": "Nombre completo",
            "email": "Email",
            "dni": "DNI",
        },
        submit_label="💾 Guardar",
        success_message="Alumno creado exitosamente",
    )
    
    if result:
        st.rerun()

with tab_edit:
    with next(get_session()) as session:
        alumnos = alumno_crud.get_all(session)
    
    if not alumnos:
        st.info("No hay alumnos para editar.")
    else:
        legajo_edit = st.selectbox(
            "Seleccionar alumno a editar",
            options=[a.legajo for a in alumnos],
            format_func=lambda x: f"{x} - {next((a.nombre for a in alumnos if a.legajo == x), '')}",
            key="edit_alumno_select"
        )
        
        if legajo_edit:
            # Use CRUDFormRenderer for update operation
            result = CRUDFormRenderer.render_update_form(
                model=Alumno,
                entity_id=legajo_edit,
                crud_read_func=read_alumno,
                crud_update_func=update_alumno,
                key=f"update_alumno_{legajo_edit}",
                id_field="legajo",
                custom_labels={
                    "legajo": "Legajo",
                    "nombre": "Nombre completo",
                    "email": "Email",
                    "dni": "DNI",
                },
                submit_label="💾 Guardar Cambios",
                success_message="Alumno actualizado exitosamente",
            )
            
            if result:
                st.rerun()
