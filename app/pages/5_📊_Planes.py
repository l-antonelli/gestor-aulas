"""Gestion de Planes de Cursada - Hub central de planificacion.

Flujo: Cronograma (schedule) → Validar cobertura → Generar Plan → Clases
"""

import streamlit as st
from sqlmodel import select, func, col
from src.database.connection import get_session, init_db
from src.database.models import (
    PlanificacionCursadaDB, ComisionDB, HorarioDB, ClaseDB, MateriaDB,
    ScheduleDB, ScheduleEntryDB,
    CicloPlanVersionDB, PlanCarreraVersionDB, PlanEstudioDB,
)
from src.database.crud import ciclo_crud
from src.services.schedule_service import (
    create_schedule_from_file,
    get_schedules_for_ciclo,
    get_schedule_entries,
)
from src.services.plan_generation_service import (
    generate_plan_from_schedule,
    activate_plan,
)
from src.services.clase_generation_service import generate_clases_for_plan

init_db()

st.set_page_config(page_title="Planes de Cursada", page_icon="📊", layout="wide")
st.title("📊 Planes de Cursada")

# =============================================================================
# Data loading
# =============================================================================
with next(get_session()) as session:
    ciclos = ciclo_crud.get_all(session, limit=100)

ciclo_ids = [c.id for c in ciclos]
ciclos_map = {c.id: c for c in ciclos}

if not ciclo_ids:
    st.info("No hay ciclos registrados. Crea uno en la pagina de Ciclos.")
    st.stop()

tab_cronogramas, tab_general, tab_detalle, tab_clases = st.tabs([
    "📥 Cronogramas", "📋 Vista General", "🔍 Detalle del Plan", "📅 Clases"
])


# =============================================================================
# Helper: get materias expected for a ciclo (from plan versions)
# =============================================================================
def _get_materias_esperadas(session, ciclo_id: str) -> dict[str, str]:
    """Return {materia_codigo: materia_nombre} for all materias in plan versions of a ciclo."""
    statement = (
        select(MateriaDB.codigo, MateriaDB.nombre)
        .join(PlanEstudioDB, MateriaDB.codigo == PlanEstudioDB.materia_codigo)
        .join(PlanCarreraVersionDB, PlanEstudioDB.plan_version_id == PlanCarreraVersionDB.id)
        .join(CicloPlanVersionDB, PlanCarreraVersionDB.id == CicloPlanVersionDB.plan_version_id)
        .where(CicloPlanVersionDB.ciclo_id == ciclo_id)
        .distinct()
    )
    rows = session.exec(statement).all()
    return {codigo: nombre for codigo, nombre in rows}


# =============================================================================
# Tab 1: Cronogramas (Schedules)
# =============================================================================
with tab_cronogramas:
    st.subheader("Cronogramas")
    st.caption("Carga un archivo CSV/Excel con los horarios. "
               "Luego valida la cobertura y genera un plan de cursada.")

    sel_ciclo_crono = st.selectbox(
        "Seleccionar Ciclo", options=ciclo_ids, key="planes_sel_ciclo_crono"
    )

    if sel_ciclo_crono:
        # --- Existing schedules ---
        with next(get_session()) as session:
            schedules = get_schedules_for_ciclo(session, sel_ciclo_crono)

        if schedules:
            st.markdown(f"**{len(schedules)} cronograma(s) cargado(s):**")

            for s in schedules:
                with st.expander(f"{s.nombre} — {s.source_filename} ({s.fecha_upload})"):
                    with next(get_session()) as session:
                        entries = get_schedule_entries(session, s.id)

                        # Build materia name lookup
                        mat_codigos = list({e.codigo_materia for e in entries})
                        mat_map: dict[str, str] = {}
                        if mat_codigos:
                            mats = session.exec(
                                select(MateriaDB).where(col(MateriaDB.codigo).in_(mat_codigos))
                            ).all()
                            mat_map = {m.codigo: m.nombre for m in mats}

                    if entries:
                        entry_data = [{
                            "Materia": f"{mat_map.get(e.codigo_materia, '?')} ({e.codigo_materia})",
                            "Dia": e.dia,
                            "Inicio": e.hora_inicio.strftime("%H:%M"),
                            "Fin": e.hora_fin.strftime("%H:%M"),
                        } for e in entries]
                        st.dataframe(entry_data, use_container_width=True, hide_index=True)
                        st.caption(f"{len(entries)} entradas")
                    else:
                        st.caption("Sin entradas")

                    # --- Coverage validation ---
                    st.divider()
                    st.markdown("**Validacion de cobertura**")
                    with next(get_session()) as session:
                        esperadas = _get_materias_esperadas(session, sel_ciclo_crono)

                    if not esperadas:
                        st.warning("El ciclo no tiene versiones de plan de estudio asignadas. "
                                   "No se puede validar cobertura.")
                    else:
                        materias_en_schedule = {e.codigo_materia for e in entries}
                        cubiertas = materias_en_schedule & set(esperadas.keys())
                        faltantes = set(esperadas.keys()) - materias_en_schedule
                        extra = materias_en_schedule - set(esperadas.keys())

                        vc1, vc2, vc3 = st.columns(3)
                        vc1.metric("Cubiertas", f"{len(cubiertas)}/{len(esperadas)}")
                        vc2.metric("Faltantes", len(faltantes))
                        vc3.metric("Extra", len(extra))

                        if faltantes:
                            with st.expander(f"Materias faltantes ({len(faltantes)})", expanded=True):
                                for cod in sorted(faltantes):
                                    st.write(f"- **{esperadas[cod]}** ({cod})")

                        if extra:
                            with st.expander(f"Materias no esperadas ({len(extra)})"):
                                for cod in sorted(extra):
                                    nombre = mat_map.get(cod, "?")
                                    st.write(f"- **{nombre}** ({cod})")

                    # --- Generate plan from this schedule ---
                    st.divider()
                    st.markdown("**Generar plan desde este cronograma**")
                    plan_nombre = st.text_input(
                        "Nombre del plan",
                        value=f"Plan {sel_ciclo_crono}",
                        key=f"plan_nombre_{s.id}"
                    )
                    if st.button("Generar Plan", type="primary", key=f"btn_gen_plan_{s.id}"):
                        with next(get_session()) as session:
                            result = generate_plan_from_schedule(
                                session, s.id, plan_nombre, sel_ciclo_crono
                            )
                        if result.errors:
                            for err in result.errors:
                                st.error(err)
                        if result.comision_flags:
                            st.info("Notas sobre derivacion de comisiones:")
                            for flag in result.comision_flags:
                                st.text(f"  - {flag}")
                        if result.plan:
                            st.success(
                                f"Plan '{plan_nombre}' generado: "
                                f"{result.comisiones_created} comisiones, "
                                f"{result.horarios_created} horarios"
                            )
                            st.rerun()

        else:
            st.info("No hay cronogramas para este ciclo.")

        # --- Upload new schedule ---
        st.divider()
        st.markdown("**Cargar nuevo cronograma**")
        nombre_sched = st.text_input(
            "Nombre del cronograma",
            value=f"Horarios {sel_ciclo_crono}",
            key="crono_nombre"
        )
        uploaded_file = st.file_uploader(
            "Archivo CSV o Excel",
            type=["csv", "xlsx", "xls"],
            key="crono_file_upload"
        )

        if uploaded_file is not None:
            if st.button("Cargar Cronograma", type="primary", key="btn_upload_crono"):
                with next(get_session()) as session:
                    result = create_schedule_from_file(
                        session, sel_ciclo_crono, nombre_sched, uploaded_file
                    )
                if result.errors:
                    st.warning("Errores durante la carga:")
                    for err in result.errors:
                        st.text(f"  - {err}")
                if result.warnings:
                    for w in result.warnings:
                        st.info(w)
                if result.schedule:
                    st.success(
                        f"Cronograma '{nombre_sched}' cargado con "
                        f"{result.entries_created} entradas"
                    )
                    st.rerun()


# =============================================================================
# Tab 2: Vista General
# =============================================================================
with tab_general:
    st.subheader("Vista General de Planes")

    sel_ciclo_general = st.selectbox(
        "Seleccionar Ciclo", options=ciclo_ids, key="planes_sel_ciclo_general"
    )

    if sel_ciclo_general:
        with next(get_session()) as session:
            planes = session.exec(
                select(PlanificacionCursadaDB)
                .where(PlanificacionCursadaDB.ciclo_id == sel_ciclo_general)
            ).all()

        if not planes:
            st.info("No hay planes para este ciclo. Carga un cronograma y genera uno desde la pestana Cronogramas.")
        else:
            for plan in planes:
                status_badge = "🟢 ACTIVO" if plan.activo else "⚪ inactivo"

                with st.container(border=True):
                    col_info, col_metrics, col_actions = st.columns([3, 4, 2])

                    with col_info:
                        st.markdown(f"### {plan.nombre}")
                        st.markdown(f"**Estado:** {status_badge}")
                        st.caption(plan.descripcion or "Sin descripcion")
                        st.caption(f"Schedule: {plan.schedule_id or 'N/A'}")

                    with col_metrics:
                        with next(get_session()) as session:
                            n_comisiones = session.exec(
                                select(func.count(ComisionDB.id))
                                .where(ComisionDB.plan_cursada_id == plan.id)
                            ).one()
                            n_materias = session.exec(
                                select(func.count(func.distinct(ComisionDB.materia_codigo)))
                                .where(ComisionDB.plan_cursada_id == plan.id)
                            ).one()
                            n_horarios = session.exec(
                                select(func.count(HorarioDB.id))
                                .join(ComisionDB, HorarioDB.comision_id == ComisionDB.id)
                                .where(ComisionDB.plan_cursada_id == plan.id)
                            ).one()
                            n_clases = session.exec(
                                select(func.count(ClaseDB.id))
                                .where(ClaseDB.plan_cursada_id == plan.id)
                            ).one()

                        m1, m2, m3, m4 = st.columns(4)
                        m1.metric("Materias", n_materias)
                        m2.metric("Comisiones", n_comisiones)
                        m3.metric("Horarios", n_horarios)
                        m4.metric("Clases", n_clases)

                    with col_actions:
                        if not plan.activo:
                            if st.button("Activar", key=f"gen_activate_{plan.id}"):
                                with next(get_session()) as session:
                                    activate_plan(session, plan.id)
                                st.success(f"Plan '{plan.nombre}' activado")
                                st.rerun()

                        if st.button("Eliminar", key=f"gen_delete_{plan.id}", type="secondary"):
                            with next(get_session()) as session:
                                # Delete in FK order: clases → horarios → comisiones → plan
                                clases = session.exec(
                                    select(ClaseDB).where(ClaseDB.plan_cursada_id == plan.id)
                                ).all()
                                for c in clases:
                                    session.delete(c)

                                comisiones = session.exec(
                                    select(ComisionDB).where(ComisionDB.plan_cursada_id == plan.id)
                                ).all()
                                for com in comisiones:
                                    horarios = session.exec(
                                        select(HorarioDB).where(HorarioDB.comision_id == com.id)
                                    ).all()
                                    for h in horarios:
                                        session.delete(h)
                                    session.delete(com)

                                db_plan = session.get(PlanificacionCursadaDB, plan.id)
                                if db_plan:
                                    session.delete(db_plan)
                                session.commit()
                            st.success(f"Plan '{plan.nombre}' eliminado")
                            st.rerun()

            st.caption(f"Total: {len(planes)} plan(es) para {sel_ciclo_general}")


# =============================================================================
# Tab 3: Detalle del Plan
# =============================================================================
with tab_detalle:
    st.subheader("Detalle del Plan")

    sel_ciclo_detalle = st.selectbox(
        "Seleccionar Ciclo", options=ciclo_ids, key="planes_sel_ciclo_detalle"
    )

    if sel_ciclo_detalle:
        with next(get_session()) as session:
            planes_detalle = session.exec(
                select(PlanificacionCursadaDB)
                .where(PlanificacionCursadaDB.ciclo_id == sel_ciclo_detalle)
            ).all()

        if not planes_detalle:
            st.info("No hay planes para este ciclo.")
        else:
            plan_options = {p.id: f"{p.nombre} {'[ACTIVO]' if p.activo else ''}" for p in planes_detalle}
            sel_plan_id = st.selectbox(
                "Seleccionar Plan",
                options=list(plan_options.keys()),
                format_func=lambda x: plan_options[x],
                key="planes_sel_plan_detalle"
            )

            if sel_plan_id:
                sel_plan = next(p for p in planes_detalle if p.id == sel_plan_id)

                # --- Editable metadata ---
                st.markdown("#### Metadata")
                with st.form(f"edit_plan_{sel_plan_id}"):
                    nuevo_nombre = st.text_input("Nombre", value=sel_plan.nombre)
                    nueva_desc = st.text_area("Descripcion", value=sel_plan.descripcion or "")
                    save_meta = st.form_submit_button("Guardar", type="primary")

                    if save_meta:
                        with next(get_session()) as session:
                            db_plan = session.get(PlanificacionCursadaDB, sel_plan_id)
                            if db_plan:
                                db_plan.nombre = nuevo_nombre
                                db_plan.descripcion = nueva_desc
                                session.add(db_plan)
                                session.commit()
                                st.success("Metadata actualizada")
                                st.rerun()

                st.divider()

                # --- Statistics panel ---
                st.markdown("#### Estadisticas")
                with next(get_session()) as session:
                    n_materias = session.exec(
                        select(func.count(func.distinct(ComisionDB.materia_codigo)))
                        .where(ComisionDB.plan_cursada_id == sel_plan_id)
                    ).one()
                    n_comisiones = session.exec(
                        select(func.count(ComisionDB.id))
                        .where(ComisionDB.plan_cursada_id == sel_plan_id)
                    ).one()
                    n_horarios = session.exec(
                        select(func.count(HorarioDB.id))
                        .join(ComisionDB, HorarioDB.comision_id == ComisionDB.id)
                        .where(ComisionDB.plan_cursada_id == sel_plan_id)
                    ).one()
                    n_clases = session.exec(
                        select(func.count(ClaseDB.id))
                        .where(ClaseDB.plan_cursada_id == sel_plan_id)
                    ).one()
                    n_clases_con_aula = session.exec(
                        select(func.count(ClaseDB.id))
                        .where(ClaseDB.plan_cursada_id == sel_plan_id)
                        .where(ClaseDB.aula_id.is_not(None))  # type: ignore[union-attr]
                    ).one()

                s1, s2, s3, s4, s5 = st.columns(5)
                s1.metric("Materias", n_materias)
                s2.metric("Comisiones", n_comisiones)
                s3.metric("Horarios", n_horarios)
                s4.metric("Clases", n_clases)
                s5.metric("Con Aula", n_clases_con_aula)

                st.divider()

                # --- Breakdown by materia ---
                st.markdown("#### Desglose por Materia")
                with next(get_session()) as session:
                    comisiones = session.exec(
                        select(ComisionDB)
                        .where(ComisionDB.plan_cursada_id == sel_plan_id)
                        .order_by(ComisionDB.materia_codigo, ComisionDB.numero)
                    ).all()

                    # Group by materia
                    by_materia: dict[str, list[ComisionDB]] = {}
                    for c in comisiones:
                        by_materia.setdefault(c.materia_codigo, []).append(c)

                    # Get materia names
                    materia_codigos = list(by_materia.keys())
                    materias_map: dict[str, str] = {}
                    if materia_codigos:
                        materias = session.exec(
                            select(MateriaDB).where(col(MateriaDB.codigo).in_(materia_codigos))
                        ).all()
                        materias_map = {m.codigo: m.nombre for m in materias}

                    # Load horarios for all comisiones in one query
                    comision_ids = [c.id for c in comisiones]
                    all_horarios: list[HorarioDB] = []
                    if comision_ids:
                        all_horarios = session.exec(
                            select(HorarioDB).where(col(HorarioDB.comision_id).in_(comision_ids))
                        ).all()
                    horarios_by_comision: dict[str, list[HorarioDB]] = {}
                    for h in all_horarios:
                        horarios_by_comision.setdefault(h.comision_id, []).append(h)

                if not by_materia:
                    st.info("Este plan no tiene comisiones.")
                else:
                    for mat_codigo in sorted(by_materia.keys()):
                        mat_coms = by_materia[mat_codigo]
                        mat_nombre = materias_map.get(mat_codigo, mat_codigo)
                        label = f"{mat_nombre} ({mat_codigo}) - {len(mat_coms)} comision(es)"

                        with st.expander(label, expanded=False):
                            for com in mat_coms:
                                st.markdown(f"**{com.nombre}** (#{com.numero}) — Cupo: {com.cupo}")

                                com_horarios = horarios_by_comision.get(com.id, [])
                                if com_horarios:
                                    horario_data = [{
                                        "Dia": h.dia,
                                        "Inicio": h.hora_inicio.strftime("%H:%M"),
                                        "Fin": h.hora_fin.strftime("%H:%M"),
                                    } for h in sorted(com_horarios, key=lambda h: (h.dia, h.hora_inicio))]
                                    st.dataframe(horario_data, use_container_width=True, hide_index=True)
                                else:
                                    st.caption("Sin horarios")

                                if com != mat_coms[-1]:
                                    st.divider()


# =============================================================================
# Tab 4: Clases
# =============================================================================
with tab_clases:
    st.subheader("Clases del Plan")

    sel_ciclo_clases = st.selectbox(
        "Seleccionar Ciclo", options=ciclo_ids, key="planes_sel_ciclo_clases"
    )

    if sel_ciclo_clases:
        with next(get_session()) as session:
            planes_clases = session.exec(
                select(PlanificacionCursadaDB)
                .where(PlanificacionCursadaDB.ciclo_id == sel_ciclo_clases)
            ).all()

        if not planes_clases:
            st.info("No hay planes para este ciclo.")
        else:
            plan_options_clases = {p.id: f"{p.nombre} {'[ACTIVO]' if p.activo else ''}" for p in planes_clases}
            sel_plan_clases_id = st.selectbox(
                "Seleccionar Plan",
                options=list(plan_options_clases.keys()),
                format_func=lambda x: plan_options_clases[x],
                key="planes_sel_plan_clases"
            )

            if sel_plan_clases_id:
                with next(get_session()) as session:
                    n_clases_total = session.exec(
                        select(func.count(ClaseDB.id))
                        .where(ClaseDB.plan_cursada_id == sel_plan_clases_id)
                    ).one()

                if n_clases_total == 0:
                    st.info("Este plan no tiene clases generadas.")
                    if st.button("Generar Clases", type="primary", key="btn_generar_clases"):
                        with next(get_session()) as session:
                            result = generate_clases_for_plan(session, sel_plan_clases_id)

                        if result.errors:
                            for err in result.errors:
                                st.error(err)
                        else:
                            st.success(f"{result.clases_created} clases generadas")
                            st.rerun()
                else:
                    # Summary metrics
                    with next(get_session()) as session:
                        n_ejecutadas = session.exec(
                            select(func.count(ClaseDB.id))
                            .where(ClaseDB.plan_cursada_id == sel_plan_clases_id)
                            .where(ClaseDB.executed == True)  # noqa: E712
                        ).one()
                        n_con_aula = session.exec(
                            select(func.count(ClaseDB.id))
                            .where(ClaseDB.plan_cursada_id == sel_plan_clases_id)
                            .where(ClaseDB.aula_id.is_not(None))  # type: ignore[union-attr]
                        ).one()

                    n_pendientes = n_clases_total - n_ejecutadas

                    c1, c2, c3, c4 = st.columns(4)
                    c1.metric("Total", n_clases_total)
                    c2.metric("Ejecutadas", n_ejecutadas)
                    c3.metric("Pendientes", n_pendientes)
                    c4.metric("Con Aula", n_con_aula)

                    st.divider()

                    # Filterable table
                    with next(get_session()) as session:
                        clases = session.exec(
                            select(ClaseDB)
                            .where(ClaseDB.plan_cursada_id == sel_plan_clases_id)
                            .order_by(ClaseDB.fecha, ClaseDB.hora_inicio)
                        ).all()

                        # Build lookup for comision → materia
                        comision_ids = list({c.comision_id for c in clases})
                        com_materia_map: dict[str, str] = {}
                        com_nombre_map: dict[str, str] = {}
                        if comision_ids:
                            coms = session.exec(
                                select(ComisionDB).where(col(ComisionDB.id).in_(comision_ids))
                            ).all()
                            for com in coms:
                                com_materia_map[com.id] = com.materia_codigo
                                com_nombre_map[com.id] = com.nombre

                    # Filter controls
                    col_f1, col_f2 = st.columns(2)
                    materias_en_clases = sorted(set(com_materia_map.values()))
                    with col_f1:
                        filtro_materia = st.selectbox(
                            "Filtrar por Materia",
                            options=["Todas"] + materias_en_clases,
                            key="clases_filtro_materia"
                        )
                    with col_f2:
                        filtro_estado = st.selectbox(
                            "Filtrar por Estado",
                            options=["Todos", "Ejecutadas", "Pendientes"],
                            key="clases_filtro_estado"
                        )

                    # Apply filters
                    filtered = clases
                    if filtro_materia != "Todas":
                        filtered = [c for c in filtered if com_materia_map.get(c.comision_id) == filtro_materia]
                    if filtro_estado == "Ejecutadas":
                        filtered = [c for c in filtered if c.executed]
                    elif filtro_estado == "Pendientes":
                        filtered = [c for c in filtered if not c.executed]

                    if filtered:
                        clases_data = [{
                            "Fecha": c.fecha.strftime("%d/%m/%Y"),
                            "Dia": c.fecha.strftime("%A"),
                            "Inicio": c.hora_inicio.strftime("%H:%M"),
                            "Fin": c.hora_fin.strftime("%H:%M"),
                            "Materia": com_materia_map.get(c.comision_id, "?"),
                            "Comision": com_nombre_map.get(c.comision_id, "?"),
                            "Ejecutada": "Si" if c.executed else "No",
                            "Aula": c.aula_id or "-",
                        } for c in filtered]
                        st.dataframe(clases_data, use_container_width=True, hide_index=True)
                        st.caption(f"Mostrando {len(filtered)} de {n_clases_total} clases")
                    else:
                        st.info("No hay clases que coincidan con los filtros.")
