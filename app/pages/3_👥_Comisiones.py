"""Gestion de Comisiones - Vista de solo lectura con edicion de cupo.

Las comisiones se crean automaticamente al generar planes de cursada.
"""

import streamlit as st
from sqlmodel import select
from src.database.connection import get_session, init_db
from src.database.models import ComisionDB, PlanificacionCursadaDB
from src.database.crud import comision_crud, materia_crud

init_db()

st.set_page_config(page_title="Comisiones", page_icon="👥", layout="wide")
st.title("👥 Comisiones")
st.caption("Las comisiones se crean automaticamente al generar un plan de cursada en la pagina de Ciclos.")

with next(get_session()) as session:
    comisiones = comision_crud.get_all(session, limit=500)

    if not comisiones:
        st.info("No hay comisiones. Se crearan automaticamente al generar un plan de cursada.")
    else:
        # Group by plan_cursada_id
        by_plan: dict[str | None, list] = {}
        for c in comisiones:
            by_plan.setdefault(c.plan_cursada_id, []).append(c)

        for plan_id, plan_coms in by_plan.items():
            if plan_id:
                plan = session.get(PlanificacionCursadaDB, plan_id)
                plan_label = f"Plan: {plan.nombre}" if plan else f"Plan: {plan_id}"
                status = " [ACTIVO]" if plan and plan.activo else ""
            else:
                plan_label = "Sin plan asignado (legacy)"
                status = ""

            st.subheader(f"{plan_label}{status}")

            # Group by materia within plan
            by_materia: dict[str, list] = {}
            for c in plan_coms:
                by_materia.setdefault(c.materia_codigo, []).append(c)

            for materia_codigo, coms in sorted(by_materia.items()):
                materia = materia_crud.get(session, materia_codigo)
                label = f"{materia.nombre} ({materia_codigo})" if materia else materia_codigo

                with st.expander(f"{label} - {len(coms)} comision(es)", expanded=False):
                    for com in sorted(coms, key=lambda c: c.numero):
                        col1, col2, col3 = st.columns([2, 1, 1])

                        with col1:
                            key_display = f" | Key: {com.comision_key}" if com.comision_key else ""
                            st.write(f"**{com.nombre}** (#{com.numero}){key_display}")
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
                                if st.button("Guardar", key=f"save_cupo_{com.id}"):
                                    db_com = session.get(ComisionDB, com.id)
                                    if db_com:
                                        db_com.cupo = new_cupo
                                        session.add(db_com)
                                        session.commit()
                                        st.success(f"Cupo actualizado a {new_cupo}")
                                        st.rerun()
