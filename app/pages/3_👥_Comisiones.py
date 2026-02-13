"""Gestion de Comisiones - Vista de solo lectura con edicion de cupo.

Las comisiones se crean automaticamente al cargar horarios.
"""

import streamlit as st
from src.database.connection import get_session, init_db
from src.database.models import ComisionDB
from src.database.crud import comision_crud, materia_crud

init_db()

st.set_page_config(page_title="Comisiones", page_icon="👥", layout="wide")
st.title("👥 Comisiones")
st.caption("Las comisiones se crean automaticamente al cargar horarios en la pagina de Horarios.")

with next(get_session()) as session:
    comisiones = comision_crud.get_all(session)
    materias = materia_crud.get_all(session)

    if not comisiones:
        st.info("No hay comisiones. Se crearan automaticamente al cargar horarios.")
    else:
        # Group by materia
        by_materia: dict[str, list] = {}
        for c in comisiones:
            by_materia.setdefault(c.materia_codigo, []).append(c)

        for materia_codigo, coms in sorted(by_materia.items()):
            materia = materia_crud.get(session, materia_codigo)
            label = f"{materia.nombre} ({materia_codigo})" if materia else materia_codigo

            with st.expander(f"📚 {label} - {len(coms)} comision(es)", expanded=False):
                for com in sorted(coms, key=lambda c: c.numero):
                    col1, col2, col3 = st.columns([2, 1, 1])

                    with col1:
                        st.write(f"**{com.nombre}** (#{com.numero})")
                        st.caption(f"ID: {com.id}")

                    with col2:
                        new_cupo = st.number_input(
                            "Cupo",
                            value=com.cupo,
                            min_value=1,
                            key=f"cupo_{com.id}",
                            label_visibility="collapsed"
                        )

                    with col3:
                        if new_cupo != com.cupo:
                            if st.button("💾 Guardar", key=f"save_cupo_{com.id}"):
                                db_com = session.get(ComisionDB, com.id)
                                if db_com:
                                    db_com.cupo = new_cupo
                                    session.add(db_com)
                                    session.commit()
                                    st.success(f"Cupo actualizado a {new_cupo}")
                                    st.rerun()
