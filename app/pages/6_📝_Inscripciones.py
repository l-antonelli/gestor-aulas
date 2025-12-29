"""Gestión de Inscripciones."""

import streamlit as st
from datetime import date
from src.database.connection import get_session
from src.database.models import InscripcionDB
from src.database.crud import inscripcion_crud, alumno_crud, comision_crud
import uuid

st.set_page_config(page_title="Inscripciones", page_icon="📝", layout="wide")
st.title("📝 Gestión de Inscripciones")

tab_list, tab_create = st.tabs(["📋 Listado", "➕ Nueva Inscripción"])

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
        
        st.subheader("Eliminar Inscripción")
        id_delete = st.selectbox(
            "Seleccionar inscripción a eliminar",
            options=[i.id for i in inscripciones],
            key="delete_inscripcion"
        )
        if st.button("🗑️ Eliminar", type="secondary"):
            with next(get_session()) as session:
                if inscripcion_crud.delete(session, id_delete):
                    st.success(f"Inscripción {id_delete} eliminada")
                    st.rerun()

with tab_create:
    with next(get_session()) as session:
        alumnos = alumno_crud.get_all(session)
        comisiones = comision_crud.get_all(session)
    
    if not alumnos:
        st.warning("Primero debes crear al menos un alumno.")
    elif not comisiones:
        st.warning("Primero debes crear al menos una comisión.")
    else:
        with st.form("create_inscripcion"):
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
                inscripcion_id = f"INS-{uuid.uuid4().hex[:8].upper()}"
                inscripcion = InscripcionDB(
                    id=inscripcion_id,
                    alumno_legajo=alumno_legajo,
                    comision_id=comision_id,
                    fecha_inscripcion=fecha,
                    activa=activa
                )
                try:
                    with next(get_session()) as session:
                        inscripcion_crud.create(session, inscripcion)
                    st.success(f"Inscripción '{inscripcion_id}' creada exitosamente")
                    st.rerun()
                except Exception as e:
                    st.error(f"Error al crear inscripción: {e}")
