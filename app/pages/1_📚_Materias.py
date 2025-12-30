"""Gestión de Materias."""

import streamlit as st
from src.database.connection import get_session
from src.database.models import MateriaDB
from src.database.crud import materia_crud, comision_crud, carrera_crud, create_materia_with_comision

st.set_page_config(page_title="Materias", page_icon="📚", layout="wide")
st.title("📚 Gestión de Materias")

tab_list, tab_create = st.tabs(["📋 Listado", "➕ Nueva Materia"])

with tab_list:
    with next(get_session()) as session:
        materias = materia_crud.get_all(session, limit=500)
        # Count comisiones per materia
        materias_data = []
        for m in materias:
            comisiones = [c for c in comision_crud.get_all(session, limit=500) if c.materia_codigo == m.codigo]
            materias_data.append({
                "Código": m.codigo,
                "Nombre": m.nombre,
                "Período": m.periodo,
                "Año": m.anio_carrera,
                "Cuatri": m.cuatrimestre_carrera,
                "Cupo": m.cupo,
                "Hs/Sem": m.horas_semanales,
                "Comisiones": len(comisiones),
            })
    
    if not materias_data:
        st.info("No hay materias registradas. Crea una en la pestaña 'Nueva Materia'.")
    else:
        st.dataframe(materias_data, use_container_width=True, hide_index=True)
        st.caption(f"Total: {len(materias_data)} materias")
        
        # Delete section
        st.divider()
        st.subheader("Eliminar Materia")
        col1, col2 = st.columns([3, 1])
        with col1:
            codigo_delete = st.selectbox(
                "Seleccionar materia a eliminar",
                options=[m.codigo for m in materias],
                key="delete_materia"
            )
        with col2:
            st.write("")
            st.write("")
            if st.button("🗑️ Eliminar", type="secondary"):
                with next(get_session()) as session:
                    if materia_crud.delete(session, codigo_delete):
                        st.success(f"Materia {codigo_delete} eliminada")
                        st.rerun()

with tab_create:
    st.info("Al crear una materia se genera automáticamente una 'Comisión Única' que luego podés editar o agregar más.")
    
    with next(get_session()) as session:
        carreras = carrera_crud.get_all(session, limit=100)
    
    with st.form("create_materia"):
        col1, col2 = st.columns(2)
        
        with col1:
            codigo = st.text_input("Código", placeholder="MAT101")
            nombre = st.text_input("Nombre", placeholder="Análisis Matemático I")
            periodo = st.selectbox("Período", options=["cuatrimestral", "anual"])
        
        with col2:
            cupo = st.number_input("Cupo máximo", min_value=1, value=100)
            horas = st.number_input("Horas semanales", min_value=1, value=6)
            anio_carrera = st.number_input("Año en carrera", min_value=1, max_value=6, value=1)
            cuatrimestre_carrera = st.selectbox("Cuatrimestre sugerido", options=[1, 2])
        
        # Optional: associate with carreras
        if carreras:
            carreras_sel = st.multiselect(
                "Carreras (opcional)",
                options=[c.codigo for c in carreras],
                format_func=lambda x: next((c.nombre for c in carreras if c.codigo == x), x)
            )
        else:
            carreras_sel = []
            st.caption("No hay carreras registradas aún.")
        
        submitted = st.form_submit_button("💾 Guardar", type="primary")
        
        if submitted:
            if not codigo or not nombre:
                st.error("Código y nombre son obligatorios")
            else:
                materia = MateriaDB(
                    codigo=codigo,
                    nombre=nombre,
                    cupo=cupo,
                    horas_semanales=horas,
                    periodo=periodo,
                    anio_carrera=anio_carrera,
                    cuatrimestre_carrera=cuatrimestre_carrera
                )
                try:
                    with next(get_session()) as session:
                        materia, comision = create_materia_with_comision(session, materia)
                    st.success(f"Materia '{nombre}' creada con comisión '{comision.nombre}'")
                    st.rerun()
                except Exception as e:
                    st.error(f"Error al crear materia: {e}")
