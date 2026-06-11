"""Gestion de Ciclos Lectivos - Creacion de ciclos y dictados."""

import streamlit as st
from datetime import date
from sqlmodel import select
from src.database.connection import get_session, init_db
from sqlmodel import Session
from src.database.models import (
    CicloDB, CicloPlanVersionDB, PlanCarreraVersionDB,
    PlanEstudioDB, CarreraDB, DictadoDB, DictadoCicloDB,
    ScheduleDB, ScheduleEntryDB, PlanificacionCursadaDB,
    ComisionDB, HorarioDB, ClaseDB, MateriaDB,
)
from src.database.crud import ciclo_crud
from src.services.dictado_service import (
    clear_activo_override,
    create_dictados_for_ciclo,
    get_dictados_for_ciclo,
    get_drift_summary,
    get_skipped_materias_for_ciclo,
    recompute_activo_for_ciclo,
    set_activo_manual,
    swap_plan_version_for_ciclo,
    update_dictado,
)
from src.services.crud_services import carrera_service

init_db()


def _delete_ciclo_cascade(session: Session, ciclo_id: str) -> None:
    """Elimina un ciclo y todas sus entidades dependientes en orden."""
    # 1. Planificaciones: clases -> horarios -> comisiones -> planificacion
    plans = session.exec(
        select(PlanificacionCursadaDB).where(PlanificacionCursadaDB.ciclo_id == ciclo_id)
    ).all()
    for plan in plans:
        # Clases
        clases = session.exec(select(ClaseDB).where(ClaseDB.plan_cursada_id == plan.id)).all()
        for c in clases:
            session.delete(c)
        # Comisiones y sus horarios
        comisiones = session.exec(select(ComisionDB).where(ComisionDB.plan_cursada_id == plan.id)).all()
        for com in comisiones:
            horarios = session.exec(select(HorarioDB).where(HorarioDB.comision_id == com.id)).all()
            for h in horarios:
                session.delete(h)
            session.delete(com)
        session.delete(plan)

    # 2. Schedules: entries -> schedule
    schedules = session.exec(select(ScheduleDB).where(ScheduleDB.ciclo_id == ciclo_id)).all()
    for sched in schedules:
        entries = session.exec(select(ScheduleEntryDB).where(ScheduleEntryDB.schedule_id == sched.id)).all()
        for e in entries:
            session.delete(e)
        session.delete(sched)

    # 3. Dictado-ciclo links (no borra los dictados, solo el link)
    dc_links = session.exec(select(DictadoCicloDB).where(DictadoCicloDB.ciclo_id == ciclo_id)).all()
    for link in dc_links:
        session.delete(link)

    # 4. Ciclo-plan version links
    cpv_links = session.exec(select(CicloPlanVersionDB).where(CicloPlanVersionDB.ciclo_id == ciclo_id)).all()
    for link in cpv_links:
        session.delete(link)

    # 5. El ciclo
    ciclo = session.get(CicloDB, ciclo_id)
    if ciclo:
        session.delete(ciclo)

    session.commit()


st.set_page_config(page_title="Ciclos", page_icon="📆", layout="wide")
st.title("📆 Gestion de Ciclos Lectivos")

# =============================================================================
# Ciclo selector (shared across tabs)
# =============================================================================
with next(get_session()) as session:
    ciclos = ciclo_crud.get_all(session, limit=100)

ciclo_ids = [c.id for c in ciclos]
ciclos_map = {c.id: c for c in ciclos}

tab_ciclos, tab_dictados = st.tabs([
    "📋 Ciclos", "📚 Dictados"
])

# =============================================================================
# Tab 1: Ciclos - List + Create + Delete
# =============================================================================
with tab_ciclos:
    st.subheader("Ciclos Registrados")

    if not ciclos:
        st.info("No hay ciclos registrados. Crea uno abajo.")
    else:
        ciclos_data = []
        for c in ciclos:
            ciclos_data.append({
                "ID": c.id,
                "Anio": c.anio,
                "Cuatrimestre": f"{c.numero}C",
                "Inicio": c.fecha_inicio.strftime("%d/%m/%Y"),
                "Fin": c.fecha_fin.strftime("%d/%m/%Y"),
                "Descripcion": c.descripcion,
            })
        st.dataframe(ciclos_data, use_container_width=True, hide_index=True)
        st.caption(f"Total: {len(ciclos_data)} ciclos")

        st.divider()
        st.subheader("Eliminar Ciclo")
        col1, col2 = st.columns([3, 1])
        with col1:
            ciclo_delete = st.selectbox(
                "Seleccionar ciclo a eliminar",
                options=ciclo_ids,
                key="delete_ciclo"
            )
        with col2:
            st.write("")
            st.write("")
            if st.button("Eliminar", type="secondary", key="btn_delete_ciclo"):
                with next(get_session()) as session:
                    try:
                        _delete_ciclo_cascade(session, ciclo_delete)
                        st.success(f"Ciclo {ciclo_delete} eliminado")
                        st.rerun()
                    except Exception as e:
                        st.error(f"Error al eliminar: {e}")

    st.divider()
    st.subheader("Nuevo Ciclo")

    # Get all plan versions for the multi-select (outside form for dynamic content)
    with next(get_session()) as session:
        all_carreras = carrera_service.get_all(session)
        all_versions = []
        for c in all_carreras:
            versions = carrera_service.get_plan_versions(session, c.codigo)
            for v in versions:
                all_versions.append(v)

    version_options = {v.id: f"{v.carrera_codigo} - {v.nombre}" for v in all_versions}
    # Default: latest version per carrera
    latest_by_carrera = {}
    for v in all_versions:
        if v.carrera_codigo not in latest_by_carrera:
            latest_by_carrera[v.carrera_codigo] = v.id
        else:
            # Keep the one with later fecha_creacion
            existing = next(vv for vv in all_versions if vv.id == latest_by_carrera[v.carrera_codigo])
            if v.fecha_creacion >= existing.fecha_creacion:
                latest_by_carrera[v.carrera_codigo] = v.id
    default_version_ids = list(latest_by_carrera.values())

    with st.form("create_ciclo"):
        col1, col2 = st.columns(2)

        with col1:
            anio = st.number_input("Anio", min_value=2020, max_value=2100, value=date.today().year)
            numero = st.selectbox("Cuatrimestre", options=[1, 2], format_func=lambda x: f"{x}C")

        with col2:
            fecha_inicio = st.date_input("Fecha de inicio")
            fecha_fin = st.date_input("Fecha de fin")

        descripcion = st.text_input("Descripcion (opcional)", placeholder="Ej: Cursado regular")

        # Plan version selection
        if version_options:
            selected_versions = st.multiselect(
                "Versiones de plan a asignar",
                options=list(version_options.keys()),
                default=default_version_ids,
                format_func=lambda x: version_options[x],
                help="Seleccione las versiones de plan de estudio que aplican a este ciclo. "
                     "Los dictados se crearan para las materias de estas versiones.",
            )
        else:
            selected_versions = []
            st.warning("No hay versiones de plan disponibles. Cree planes de estudio primero.")

        submitted = st.form_submit_button("Guardar", type="primary")

        if submitted:
            ciclo_id = f"{anio}-{numero}C"

            if fecha_fin <= fecha_inicio:
                st.error("La fecha de fin debe ser posterior a la de inicio")
            elif not selected_versions:
                st.error("Debe seleccionar al menos una version de plan")
            else:
                ciclo = CicloDB(
                    id=ciclo_id,
                    anio=anio,
                    numero=numero,
                    fecha_inicio=fecha_inicio,
                    fecha_fin=fecha_fin,
                    descripcion=descripcion or "",
                )
                try:
                    with next(get_session()) as session:
                        ciclo_crud.create(session, ciclo)
                        # Create CicloPlanVersion links
                        for vid in selected_versions:
                            link = CicloPlanVersionDB(ciclo_id=ciclo_id, plan_version_id=vid)
                            session.add(link)
                        session.commit()
                    st.success(f"Ciclo '{ciclo_id}' creado con {len(selected_versions)} version(es) de plan")
                    st.rerun()
                except Exception as e:
                    st.error(f"Error al crear ciclo: {e}")


# =============================================================================
# Tab 2: Dictados - Create, view grouped by carrera, edit activo/virtual
# =============================================================================
with tab_dictados:
    st.subheader("Dictados por Ciclo")
    st.caption(
        "Los **dictados activos** acá son lo que la prevalidación de cronogramas "
        "espera del ciclo. Si una materia del plan **no se va a dictar** este "
        "cuatrimestre, marcala como `Activo=False` y desaparece de las "
        "esperadas. La bandera `Virtual` se hereda de la materia pero se puede "
        "ajustar caso por caso."
    )

    if not ciclo_ids:
        st.info("Crea un ciclo primero en la pestana 'Ciclos'.")
    else:
        sel_ciclo_dict = st.selectbox(
            "Seleccionar Ciclo", options=ciclo_ids, key="sel_ciclo_dictados"
        )

        if sel_ciclo_dict:
            # =========================================================
            # Panel de configuracion (carreras + planes + materias)
            # =========================================================
            with next(get_session()) as session:
                _cfg_versions = list(session.exec(
                    select(PlanCarreraVersionDB)
                    .join(
                        CicloPlanVersionDB,
                        PlanCarreraVersionDB.id == CicloPlanVersionDB.plan_version_id,
                    )
                    .where(CicloPlanVersionDB.ciclo_id == sel_ciclo_dict)
                ).all())
                _cfg_carrera_codes = sorted({v.carrera_codigo for v in _cfg_versions})
                _cfg_carreras = {
                    c.codigo: c for c in (
                        session.get(CarreraDB, cc) for cc in _cfg_carrera_codes
                    ) if c
                }
                _cfg_plan_ids = [v.id for v in _cfg_versions]
                _cfg_pe = list(session.exec(
                    select(PlanEstudioDB).where(
                        PlanEstudioDB.plan_version_id.in_(_cfg_plan_ids)
                    )
                ).all()) if _cfg_plan_ids else []
                _cfg_mat_codes = sorted({pe.materia_codigo for pe in _cfg_pe})
                _cfg_mats = list(session.exec(
                    select(MateriaDB).where(MateriaDB.codigo.in_(_cfg_mat_codes))
                ).all()) if _cfg_mat_codes else []

            if not _cfg_versions:
                st.warning(
                    "Este ciclo no tiene versiones de plan asignadas. "
                    "Los dictados no se pueden crear sin versiones asignadas."
                )
                st.stop()

            # Stats agregadas
            _cfg_n_carreras = len(_cfg_carreras)
            _cfg_n_no_recursado = sum(
                1 for c in _cfg_carreras.values() if not c.dicta_recursado
            )
            _cfg_n_planes = len(_cfg_versions)
            _cfg_n_mats = len(_cfg_mats)
            _cfg_n_optativas = sum(1 for m in _cfg_mats if m.optativa)
            _cfg_n_virtuales = sum(1 for m in _cfg_mats if m.virtual)
            _cfg_n_anuales = sum(1 for m in _cfg_mats if m.periodo == "anual")
            _cfg_n_inactive = sum(1 for m in _cfg_mats if not m.active)
            _cfg_n_override = sum(
                1 for m in _cfg_mats if m.dicta_recursado is not None
            )

            # Resumen compacto de configuración (ediciones por carrera abajo)
            _cfg1, _cfg2, _cfg3, _cfg4, _cfg5 = st.columns(5)
            _cfg1.metric("Carreras", _cfg_n_carreras)
            _cfg2.metric("Planes", _cfg_n_planes)
            _cfg3.metric("Materias", _cfg_n_mats)
            _cfg4.metric("Optativas", _cfg_n_optativas)
            _cfg5.metric("Recursado fijado a mano", _cfg_n_override)
            if _cfg_n_no_recursado:
                st.caption(
                    f"⚠️ {_cfg_n_no_recursado} carrera(s) con "
                    f"`dicta_recursado=False`: las materias exclusivas y del "
                    f"cuatri opuesto se crean como **inactivas** (salvo edición a mano)."
                )
            if _cfg_n_inactive:
                st.caption(
                    f"ℹ️ {_cfg_n_inactive} materia(s) con `active=False` "
                    "(soft-delete) — siguen apareciendo en planes y se crean dictados igual."
                )
            st.caption(
                "Editá `dicta_recursado` (carrera y materia) y la versión del plan "
                "asignada al ciclo desde **dentro de cada expander de carrera** abajo. "
                "Después tocá **🔄 Recalcular** para alinear los dictados con las "
                "reglas actualizadas."
            )

            st.divider()

            # --- Create + Recompute buttons ---
            st.caption(
                "**Crear Dictados** genera todas las materias del plan como "
                "dictados de este ciclo. Las que la regla de `dicta_recursado` "
                "indique no dictar quedan creadas pero **inactivas** — las "
                "podés activar manualmente cuando quieras. Es idempotente. "
                "**Recalcular según reglas** revisa todos los dictados y "
                "ajusta `activo` según las banderas actuales (útil después de "
                "tocar `dicta_recursado` en una carrera)."
            )
            # Drift summary: detecta recompute pendiente, materias sin
            # dictado y dictados huerfanos. Se muestra como un chip al lado
            # del boton Recalcular para que el usuario sepa si hay cambios
            # pendientes despues de tocar configuracion.
            with next(get_session()) as _drift_sess:
                _drift = get_drift_summary(_drift_sess, sel_ciclo_dict)

            _bcol1, _bcol2, _bcol3 = st.columns([1, 1.4, 3])
            with _bcol1:
                _do_create = st.button(
                    "➕ Crear Dictados",
                    type="primary",
                    key="btn_create_dictados",
                )
            with _bcol2:
                _do_recompute = st.button(
                    "🔄 Recalcular según reglas",
                    key="btn_recompute_dictados",
                    help=(
                        "Compara la bandera `activo` de cada dictado contra las "
                        "reglas vigentes y muestra un preview de los cambios."
                    ),
                )
            with _bcol3:
                if _drift.is_clean:
                    st.success("✅ Dictados al día con la configuración.")
                else:
                    _drift_parts = []
                    _n_recompute = (
                        len(_drift.recompute_to_activate)
                        + len(_drift.recompute_to_deactivate)
                    )
                    if _n_recompute > 0:
                        _drift_parts.append(
                            f"🔄 {_n_recompute} a recalcular"
                        )
                    if _drift.missing_materias:
                        _drift_parts.append(
                            f"➕ {len(_drift.missing_materias)} sin dictado"
                        )
                    if _drift.orphan_dictados:
                        _drift_parts.append(
                            f"🗑️ {len(_drift.orphan_dictados)} huérfano(s)"
                        )
                    st.warning(
                        "⚠️ Cambios pendientes: " + " · ".join(_drift_parts)
                    )
                    with st.popover(
                        "Ver detalle", use_container_width=False,
                    ):
                        if _drift.recompute_to_activate:
                            st.markdown(
                                f"**🟢 Pasarán a Activo al recalcular "
                                f"({len(_drift.recompute_to_activate)})**"
                            )
                            for _it in _drift.recompute_to_activate:
                                st.write(
                                    f"- **{_it['materia_codigo']}** — "
                                    f"{_it['materia_nombre']} "
                                    f"({_it['carrera_nombre']})  \n"
                                    f"  _{_it['razon']}_"
                                )
                        if _drift.recompute_to_deactivate:
                            st.markdown(
                                f"**⚪ Pasarán a Inactivo al recalcular "
                                f"({len(_drift.recompute_to_deactivate)})**"
                            )
                            for _it in _drift.recompute_to_deactivate:
                                st.write(
                                    f"- **{_it['materia_codigo']}** — "
                                    f"{_it['materia_nombre']} "
                                    f"({_it['carrera_nombre']})  \n"
                                    f"  _{_it['razon']}_"
                                )
                        if _drift.missing_materias:
                            st.markdown(
                                f"**➕ Materias del plan sin dictado "
                                f"({len(_drift.missing_materias)})**"
                            )
                            st.caption(
                                "Apretá **Crear Dictados** para crearlos."
                            )
                            for _mc, _nm in _drift.missing_materias:
                                st.write(f"- {_mc} — {_nm}")
                        if _drift.orphan_dictados:
                            st.markdown(
                                f"**🗑️ Dictados huérfanos "
                                f"({len(_drift.orphan_dictados)})**"
                            )
                            st.caption(
                                "Materias con dictado pero que ya no están "
                                "en ningún plan asignado al ciclo. Suele "
                                "pasar después de cambiar la versión del plan."
                            )
                            for _mc, _dc in _drift.orphan_dictados:
                                st.write(f"- `{_dc}` ({_mc})")
                            if st.button(
                                "🗑️ Eliminar huérfanos",
                                key="btn_delete_orphans",
                                type="secondary",
                            ):
                                _orphan_codes = [
                                    mc for mc, _ in _drift.orphan_dictados
                                ]
                                with next(get_session()) as _del_s:
                                    _del_n = 0
                                    for _orp_mc in _orphan_codes:
                                        _orp_d = _del_s.exec(
                                            select(DictadoDB)
                                            .where(DictadoDB.materia_codigo == _orp_mc)
                                            .join(
                                                DictadoCicloDB,
                                                DictadoDB.id == DictadoCicloDB.dictado_id,
                                            )
                                            .where(DictadoCicloDB.ciclo_id == sel_ciclo_dict)
                                        ).first()
                                        if _orp_d is None:
                                            continue
                                        # borrar link y dictado
                                        _orp_link = _del_s.get(
                                            DictadoCicloDB,
                                            (_orp_d.id, sel_ciclo_dict),
                                        )
                                        if _orp_link:
                                            _del_s.delete(_orp_link)
                                        _del_s.delete(_orp_d)
                                        _del_n += 1
                                    _del_s.commit()
                                st.toast(f"{_del_n} huérfano(s) eliminado(s).")
                                st.rerun()

            # Guard: si hay cambios pendientes en batch, bloquear las
            # operaciones globales (Crear Dictados, Recalcular según
            # reglas) que pisarían los toggles. El usuario debe aplicar
            # o descartar primero. Leemos un flag persistido por el
            # render anterior porque en este punto del flujo todavía no
            # se cargaron los dictados (se cargan más abajo).
            _has_pending_for_guard = bool(
                st.session_state.get("dict_pending_count", 0) > 0
            )

            if _do_create:
                if _has_pending_for_guard:
                    st.error(
                        "Tenés cambios pendientes sin aplicar. Apretá "
                        "**💾 Aplicar cambios** abajo o **🚫 Descartar** "
                        "antes de crear/recalcular dictados."
                    )
                    _do_create = False
            if _do_recompute and _has_pending_for_guard:
                st.error(
                    "Tenés cambios pendientes sin aplicar. Apretá "
                    "**💾 Aplicar cambios** abajo o **🚫 Descartar** "
                    "antes de crear/recalcular dictados."
                )
                _do_recompute = False

            if _do_create:
                with next(get_session()) as session:
                    result = create_dictados_for_ciclo(session, sel_ciclo_dict)
                if result.errors:
                    for err in result.errors:
                        st.error(err)
                else:
                    msg_parts = []
                    if result.created:
                        _act = result.created - result.created_inactive
                        msg_parts.append(
                            f"{result.created} creados "
                            f"({_act} activos, {result.created_inactive} inactivos)"
                        )
                    if result.linked:
                        msg_parts.append(f"{result.linked} vinculados (anuales)")
                    if result.skipped:
                        msg_parts.append(f"{result.skipped} ya existentes")
                    st.success(f"Dictados: {', '.join(msg_parts)}")
                    # Por las dudas: dictados nuevos no tienen
                    # session_state previo, pero `linked` sí puede
                    # haber tocado dictados anuales existentes.
                    st.session_state["dict_resync_pending"] = True
                    st.rerun()

            # Checkbox "pisar ediciones manuales" debe estar disponible
            # *siempre* antes del botón Recalcular (no condicionado a un
            # estado intermedio).
            _pisar_ovr = st.checkbox(
                "Pisar también las ediciones manuales",
                value=False,
                key=f"recompute_pisar_ovr_{sel_ciclo_dict}",
                help=(
                    "Por default, 'Recalcular según reglas' respeta los "
                    "dictados que fueron editados a mano (los marcados "
                    "con el indicador ✋). Activá esta opción sólo si "
                    "querés descartar todas las ediciones manuales y "
                    "dejar que las reglas vuelvan a decidir el estado "
                    "de cada dictado."
                ),
            )
            if _do_recompute:
                with next(get_session()) as session:
                    preview = recompute_activo_for_ciclo(
                        session, sel_ciclo_dict, apply=False,
                        pisar_overrides=_pisar_ovr,
                    )
                st.session_state["dict_recompute_preview"] = {
                    "ciclo": sel_ciclo_dict,
                    "to_activate": preview.to_activate,
                    "to_deactivate": preview.to_deactivate,
                    "overrides_respetados": preview.overrides_respetados,
                    "unchanged": preview.unchanged,
                    "pisar_overrides": _pisar_ovr,
                }

            # --- Recompute preview UI ---
            _rprev = st.session_state.get("dict_recompute_preview")
            if _rprev and _rprev.get("ciclo") == sel_ciclo_dict:
                _to_act = _rprev["to_activate"]
                _to_deact = _rprev["to_deactivate"]
                _ovr = _rprev.get("overrides_respetados", [])
                _n_changes = len(_to_act) + len(_to_deact)
                if _n_changes == 0 and not _ovr:
                    st.info(
                        f"Todos los dictados ya están alineados con las "
                        f"reglas actuales ({_rprev['unchanged']} sin "
                        f"cambios)."
                    )
                    st.session_state.pop("dict_recompute_preview", None)
                else:
                    with st.container(border=True):
                        _modo_ovr = (
                            "🚨 Modo: pisar ediciones manuales"
                            if _rprev.get("pisar_overrides")
                            else "✋ Modo: respetar ediciones manuales"
                        )
                        st.markdown(
                            f"**Preview de recálculo** — "
                            f"{_n_changes} cambio(s), "
                            f"{_rprev['unchanged']} sin cambio. "
                            f"_{_modo_ovr}_"
                        )

                        def _render_recompute_table(items, key_prefix):
                            import pandas as _pd
                            rows = []
                            for it in items:
                                _aa = it.get("anio_plan")
                                _cc = it.get("cuatrimestre_plan")
                                _ubic = (
                                    f"{_aa}°·{_cc}" if _aa and _cc
                                    else (str(_aa) if _aa else (_cc or "—"))
                                )
                                _ea = "Activo" if it["estado_actual"] else "Inactivo"
                                _en = "Activo" if it["estado_nuevo"] else "Inactivo"
                                _flecha = (
                                    f"{_ea} → {_en}"
                                    if it["estado_actual"] != it["estado_nuevo"]
                                    else _ea
                                )
                                rows.append({
                                    "Materia": (
                                        f"{it['materia_codigo']} — "
                                        f"{it['materia_nombre']}"
                                    ),
                                    "Carrera": it["carrera_nombre"],
                                    "Año/Cuatri": _ubic,
                                    "Cambio": _flecha,
                                    "Razón": it["razon"],
                                    "Editado a mano": (
                                        "✋" if it["tiene_override"] else ""
                                    ),
                                })
                            return _pd.DataFrame(rows)

                        if _to_act:
                            with st.expander(
                                f"🟢 Pasarán a Activo ({len(_to_act)})",
                                expanded=True,
                            ):
                                _df = _render_recompute_table(_to_act, "act")
                                st.dataframe(
                                    _df,
                                    width='stretch',
                                    hide_index=True,
                                )
                        if _to_deact:
                            with st.expander(
                                f"⚪ Pasarán a Inactivo ({len(_to_deact)})",
                                expanded=True,
                            ):
                                _df = _render_recompute_table(_to_deact, "deact")
                                st.dataframe(
                                    _df,
                                    width='stretch',
                                    hide_index=True,
                                )
                        if _ovr:
                            with st.expander(
                                f"✋ Editados a mano (respetados) ({len(_ovr)})",
                                expanded=False,
                            ):
                                st.caption(
                                    "Estos dictados fueron editados a mano "
                                    "desde la grilla: la recalculación los "
                                    "respeta y NO los modifica. Para que "
                                    "vuelvan a alinearse con la regla, "
                                    "apretá 'Quitar edición manual' en la "
                                    "grilla o activá el toggle 'Pisar "
                                    "también las ediciones manuales'."
                                )
                                _df = _render_recompute_table(_ovr, "ovr")
                                st.dataframe(
                                    _df,
                                    width='stretch',
                                    hide_index=True,
                                )
                        _ac1, _ac2, _ = st.columns([1, 1, 3])
                        with _ac1:
                            if st.button(
                                "Aplicar cambios",
                                type="primary",
                                key="btn_apply_recompute",
                                disabled=(_n_changes == 0),
                            ):
                                with next(get_session()) as session:
                                    res = recompute_activo_for_ciclo(
                                        session, sel_ciclo_dict,
                                        apply=True,
                                        pisar_overrides=_rprev.get(
                                            "pisar_overrides", False,
                                        ),
                                    )
                                st.success(
                                    f"{res.n_changes} dictado(s) "
                                    f"actualizado(s)."
                                )
                                st.session_state.pop(
                                    "dict_recompute_preview", None,
                                )
                                st.session_state.pop(
                                    "dict_pending_count", None,
                                )
                                # El recompute mutó DB sin pasar por los
                                # toggles → marcamos resync pendiente
                                # para que el próximo render alinee
                                # session_state con DB. Ver bloque
                                # "Resync de session_state tras
                                # operaciones bulk" más arriba.
                                st.session_state["dict_resync_pending"] = True
                                st.rerun()
                        with _ac2:
                            if st.button(
                                "Cancelar", key="btn_cancel_recompute",
                            ):
                                st.session_state.pop(
                                    "dict_recompute_preview", None,
                                )
                                st.rerun()

            st.divider()

            # --- Build unified per-carrera/per-materia view ---
            with next(get_session()) as session:
                dictados = get_dictados_for_ciclo(session, sel_ciclo_dict)
                plan_version_ids = list(session.exec(
                    select(CicloPlanVersionDB.plan_version_id)
                    .where(CicloPlanVersionDB.ciclo_id == sel_ciclo_dict)
                ).all())

                if not plan_version_ids:
                    st.info("Asigne versiones de plan al ciclo para gestionar dictados.")
                    st.stop()

                # Index dictados por materia
                dict_by_mat: dict[str, DictadoDB] = {d.materia_codigo: d for d in dictados}

                # Plan entries (todas las materias del plan, con anio/cuatri/optativa)
                pe_rows = list(session.exec(
                    select(PlanEstudioDB)
                    .where(PlanEstudioDB.plan_version_id.in_(plan_version_ids))
                ).all())

                # Materias data
                mat_codigos = list({pe.materia_codigo for pe in pe_rows})
                mats = list(session.exec(
                    select(MateriaDB).where(MateriaDB.codigo.in_(mat_codigos))
                ).all()) if mat_codigos else []
                mat_map: dict[str, MateriaDB] = {m.codigo: m for m in mats}

                # Carrera names + objects (necesitamos dicta_recursado tambien)
                carrera_codigos = sorted({pe.carrera_codigo for pe in pe_rows})
                carrera_nombres = {}
                carrera_objs: dict[str, CarreraDB] = {}
                for cc in carrera_codigos:
                    carrera_db = session.get(CarreraDB, cc)
                    if carrera_db:
                        carrera_nombres[cc] = carrera_db.nombre
                        carrera_objs[cc] = carrera_db
                    else:
                        carrera_nombres[cc] = cc

                # Plan versions: cual está asignada (current) y cuales hay
                # disponibles por carrera (para el swap).
                _current_pv_by_carrera: dict[str, str] = {}
                for pv_id in plan_version_ids:
                    _pv = session.get(PlanCarreraVersionDB, pv_id)
                    if _pv:
                        _current_pv_by_carrera[_pv.carrera_codigo] = pv_id
                _available_pvs_by_carrera: dict[str, list[PlanCarreraVersionDB]] = {}
                for cc in carrera_codigos:
                    _avail = list(session.exec(
                        select(PlanCarreraVersionDB)
                        .where(PlanCarreraVersionDB.carrera_codigo == cc)
                        .order_by(PlanCarreraVersionDB.fecha_creacion.desc())
                    ).all())
                    _available_pvs_by_carrera[cc] = _avail

                # Per-carrera index: codigo_carrera -> { materia_codigo -> {pe, dictado, materia, otras_carreras} }
                # otras_carreras indica si la materia aparece en otros planes del ciclo (compartida).
                materia_carreras: dict[str, set[str]] = {}
                for pe in pe_rows:
                    materia_carreras.setdefault(pe.materia_codigo, set()).add(pe.carrera_codigo)

                # Separamos items en dos buckets:
                # - items_by_carrera: SOLO materias exclusivas a la carrera
                #   (las que aparecen en una única carrera del ciclo).
                # - items_comunes_by_mat: materias compartidas (en >=2 carreras),
                #   indexadas por materia_codigo. Una sola entrada por materia
                #   (no por carrera donde aparece). Esto evita duplicar
                #   widgets para el mismo dictado, lo que antes causaba race
                #   conditions con auto-save.
                items_by_carrera: dict[str, list[dict]] = {}
                items_comunes_by_mat: dict[str, dict] = {}
                for pe in pe_rows:
                    mat = mat_map.get(pe.materia_codigo)
                    if not mat:
                        continue
                    d = dict_by_mat.get(pe.materia_codigo)
                    _carreras_de_mat = materia_carreras[pe.materia_codigo]
                    if len(_carreras_de_mat) >= 2:
                        # Compartida: una sola entrada por materia.
                        # Si ya está, mantenemos la primera vista de pe
                        # (solo cambia anio_plan/cuatrimestre_plan
                        # potencialmente — debería ser igual entre carreras
                        # o documentar que tomamos la primera por orden
                        # alfabético de carrera). En la práctica las
                        # comunes tienen mismo anio/cuatri en todos los
                        # planes; si difieren, mostramos la representativa.
                        if pe.materia_codigo not in items_comunes_by_mat:
                            items_comunes_by_mat[pe.materia_codigo] = {
                                "materia": mat,
                                "pe": pe,
                                "dictado": d,
                                "carreras": sorted(_carreras_de_mat),
                            }
                    else:
                        # Exclusiva.
                        items_by_carrera.setdefault(
                            pe.carrera_codigo, [],
                        ).append({
                            "materia": mat,
                            "pe": pe,
                            "dictado": d,
                            "otras": [],
                        })

                # Skipped materias (para razones)
                skipped_list = get_skipped_materias_for_ciclo(session, sel_ciclo_dict)
                skipped_razones = {sm.materia_codigo: sm.razon for sm in skipped_list}

            # =========================================================
            # Resync de session_state tras operaciones bulk
            # =========================================================
            #
            # Streamlit retiene los valores del session_state de cada
            # widget mientras la página vive. Si una operación bulk
            # (Recalcular, Crear Dictados, bulk activate desde
            # Validaciones) modificó `DictadoDB.activo`/`.virtual` en
            # DB sin pasar por el flujo del checkbox, el session_state
            # queda stuck con el valor viejo. El siguiente render del
            # toggle muestra ese valor stuck (Streamlit ignora
            # `value=` cuando hay session_state), divergiendo del
            # badge que sí lee de DB.
            #
            # NO podemos hacer este resync siempre: en un render
            # normal, después de que el usuario toca un toggle,
            # session_state ≠ DB es esperado (el toggle entra al batch
            # de "Cambios pendientes"). Si borráramos session_state
            # ahí, perderíamos el cambio del usuario.
            #
            # Solución: cada operación bulk setea un flag
            # `dict_resync_pending=True` antes del st.rerun(). En el
            # próximo render lo consumimos: re-sincronizamos
            # session_state con DB para todos los toggles del ciclo
            # actual y limpiamos el flag.
            if st.session_state.pop("dict_resync_pending", False):
                _dictado_id_to_db = {d.id: d for d in dictados}
                _materia_to_db = {m.codigo: m for m in mats}
                for _k in list(st.session_state.keys()):
                    if not isinstance(_k, str):
                        continue
                    if _k.startswith("activo_"):
                        _did = _k.rsplit("_", 1)[-1]
                        _d = _dictado_id_to_db.get(_did)
                        if _d is not None:
                            st.session_state[_k] = _d.activo
                    elif _k.startswith("virtual_"):
                        _did = _k.rsplit("_", 1)[-1]
                        _d = _dictado_id_to_db.get(_did)
                        if _d is not None:
                            st.session_state[_k] = _d.virtual
                    elif _k.startswith("rec_mat_"):
                        # rec_mat_{ns}_{carrera}_{materia_codigo}
                        # materia_codigo puede tener underscores; el
                        # split por "_" no es trivial. Inferimos: la
                        # materia_codigo es lo que viene después del
                        # cuarto "_".
                        parts = _k.split("_", 4)
                        if len(parts) >= 5:
                            _mc = parts[4]
                            _m = _materia_to_db.get(_mc)
                            if _m is not None:
                                st.session_state[_k] = (
                                    "Según Carrera"
                                    if _m.dicta_recursado is None
                                    else (
                                        "Sí" if _m.dicta_recursado else "No"
                                    )
                                )

            if not items_by_carrera and not items_comunes_by_mat:
                st.info(
                    "Las versiones de plan asignadas a este ciclo no tienen "
                    "materias cargadas. Cargá los planes de estudio primero."
                )
                st.stop()

            # =========================================================
            # Top stats
            # =========================================================
            _n_total_dict = len(dictados)
            _n_activos = sum(1 for d in dictados if d.activo)
            _n_virtuales = sum(1 for d in dictados if d.virtual and d.activo)
            _n_inactivos = _n_total_dict - _n_activos
            _n_sin_dict = sum(
                1 for items in items_by_carrera.values()
                for it in items if it["dictado"] is None
            )
            # Optativas (a nivel materia, contando una vez)
            _opt_codigos = {
                it["pe"].materia_codigo
                for items in items_by_carrera.values()
                for it in items if it["pe"].optativa
            }

            _ms1, _ms2, _ms3, _ms4 = st.columns(4)
            _ms1.metric("Activos", _n_activos)
            _ms2.metric("Inactivos", _n_inactivos)
            _ms3.metric("Virtuales", _n_virtuales)
            _ms4.metric("Optativas", len(_opt_codigos))
            if _n_sin_dict > 0:
                st.warning(
                    f"⚠️ Hay {_n_sin_dict} materia(s) del plan sin dictado "
                    "creado todavía. Apretá **Crear Dictados** para "
                    "completar el set."
                )
            st.caption(
                "**Esperadas en prevalidación = Activos.** Las inactivas se "
                "excluyen del set de materias esperadas."
            )

            with st.expander(
                "ℹ️ Cómo usar los toggles de cada materia", expanded=False,
            ):
                st.markdown(
                    "Cada fila tiene tres toggles que combinan "
                    "**modalidad efectiva** y **excepciones manuales**:\n\n"
                    "- **🟢/⚪ Activo**: si la materia se dicta en este "
                    "ciclo. Las inactivas se excluyen del set esperado "
                    "en prevalidaciones de cronograma. El indicador "
                    "**✋ editado a mano** aparece cuando vos forzaste "
                    "el valor, y se respeta al volver a apretar "
                    "*Recalcular según reglas* (salvo que actives "
                    "*Pisar ediciones manuales*).\n"
                    "- **Recursado fijado a mano**: override del flag "
                    "`dicta_recursado` de la carrera para esta materia "
                    "(útil cuando una materia particular se ofrece "
                    "como recursado aunque la carrera en general no lo "
                    "haga, o viceversa).\n"
                    "- **🌐 Virtual**: marca el dictado como virtual "
                    "**sólo en este ciclo**. La materia sigue figurando "
                    "en el plan, validaciones de cobertura la cuentan "
                    "como cubierta, pero **no necesita aula** — el LP "
                    "de asignación la ignora. Útil para recursados o "
                    "materias que se dictan por Zoom este cuatrimestre. "
                    "El catálogo de la materia (campo "
                    "`MateriaDB.virtual`) **no** se modifica: si en otro "
                    "ciclo la materia es presencial, su dictado de ese "
                    "ciclo aparecerá presencial por default."
                )

            st.divider()

            # =========================================================
            # Filters
            # =========================================================
            _all_anios = sorted({
                it["pe"].anio_plan
                for items in items_by_carrera.values()
                for it in items if it["pe"].anio_plan is not None
            })
            _all_cuatris = sorted({
                it["pe"].cuatrimestre_plan or "—"
                for items in items_by_carrera.values()
                for it in items
            })

            _fc1, _fc2 = st.columns([3, 2])
            with _fc1:
                _q = st.text_input(
                    "🔎 Buscar (código o nombre de materia)",
                    key="dict_search",
                    placeholder="Ej: MAT, Cálculo, FB1",
                )
            with _fc2:
                _estado = st.multiselect(
                    "Estado",
                    options=["Activo", "Inactivo"],
                    default=["Activo", "Inactivo"],
                    key="dict_estado",
                )

            _fc3, _fc4, _fc5, _fc6 = st.columns([2, 2, 2, 2])
            with _fc3:
                _modal = st.multiselect(
                    "Modalidad",
                    options=["Presencial", "Virtual"],
                    default=["Presencial", "Virtual"],
                    key="dict_modal",
                )
            with _fc4:
                _anios_sel = st.multiselect(
                    "Año del plan",
                    options=_all_anios,
                    default=_all_anios,
                    format_func=lambda a: f"{a}°",
                    key="dict_anio",
                )
            with _fc5:
                _cuatris_sel = st.multiselect(
                    "Cuatri del plan",
                    options=_all_cuatris,
                    default=_all_cuatris,
                    key="dict_cuatri",
                )
            with _fc6:
                _opt_filt = st.selectbox(
                    "Optativas",
                    options=["Incluir", "Solo", "Excluir"],
                    index=0,
                    key="dict_opt",
                )

            # Open/close all
            _bc1, _bc2, _bc3 = st.columns([1, 1, 4])
            with _bc1:
                if st.button("Abrir todos", key="dict_open_all"):
                    st.session_state["dict_force_open"] = True
                    st.rerun()
            with _bc2:
                if st.button("Cerrar todos", key="dict_close_all"):
                    st.session_state["dict_force_open"] = False
                    st.rerun()
            _force_state = st.session_state.get("dict_force_open")

            # =========================================================
            # Detección de cambios pendientes (batch)
            # =========================================================
            #
            # Los toggles Activo/Virtual y el selector Recursado NO
            # commitean al instante. Ese diseño se eligió porque
            # Streamlit interrumpe los reruns en curso cuando el usuario
            # hace clicks rápidos en sucesión, lo que cancelaba commits
            # intermedios y hacía "perder" cambios. Acá detectamos diff
            # entre `session_state` y DB para mostrar un panel de
            # "Cambios pendientes" + botón único de aplicación.
            #
            # Set de prefijos de keys que monitoreamos.
            _BATCH_PREFIXES = ("activo_", "virtual_", "rec_mat_")

            def _detectar_pendientes() -> list[dict]:
                """Inspecciona session_state y devuelve la lista de
                cambios pendientes vs DB.

                Cada item:
                  {tipo: 'activo'|'virtual'|'recursado',
                   dictado_id: str | None (recursado no tiene dictado),
                   materia_codigo: str,
                   nombre: str,
                   actual: bool|None|str,
                   nuevo: bool|None|str,
                   key: str}
                """
                pendientes: list[dict] = []
                for _k in list(st.session_state.keys()):
                    if not isinstance(_k, str):
                        continue
                    if not _k.startswith(_BATCH_PREFIXES):
                        continue
                    # Parseo de la key.
                    # activo_{ns}_{carrera}_{dictado_id}
                    # virtual_{ns}_{carrera}_{dictado_id}
                    # rec_mat_{ns}_{carrera}_{materia_codigo}
                    parts = _k.split("_")
                    if _k.startswith("activo_") and len(parts) >= 4:
                        _did = "_".join(parts[3:])
                        # Recuperar dictado actual del map cargado
                        _dd = next(
                            (
                                d for d in dictados if d.id == _did
                            ),
                            None,
                        )
                        if _dd is None:
                            continue
                        _new = bool(st.session_state[_k])
                        if _new != _dd.activo:
                            pendientes.append({
                                "tipo": "activo",
                                "dictado_id": _did,
                                "materia_codigo": _dd.materia_codigo,
                                "nombre": (
                                    mat_map[_dd.materia_codigo].nombre
                                    if _dd.materia_codigo in mat_map else ""
                                ),
                                "actual": _dd.activo,
                                "nuevo": _new,
                                "key": _k,
                            })
                    elif _k.startswith("virtual_") and len(parts) >= 4:
                        _did = "_".join(parts[3:])
                        _dd = next(
                            (d for d in dictados if d.id == _did), None,
                        )
                        if _dd is None:
                            continue
                        _new = bool(st.session_state[_k])
                        if _new != _dd.virtual:
                            pendientes.append({
                                "tipo": "virtual",
                                "dictado_id": _did,
                                "materia_codigo": _dd.materia_codigo,
                                "nombre": (
                                    mat_map[_dd.materia_codigo].nombre
                                    if _dd.materia_codigo in mat_map else ""
                                ),
                                "actual": _dd.virtual,
                                "nuevo": _new,
                                "key": _k,
                            })
                    elif _k.startswith("rec_mat_") and len(parts) >= 5:
                        _mc = "_".join(parts[4:])
                        _m = mat_map.get(_mc)
                        if _m is None:
                            continue
                        _curr_lbl = (
                            "Según Carrera" if _m.dicta_recursado is None
                            else ("Sí" if _m.dicta_recursado else "No")
                        )
                        _new_lbl = st.session_state[_k]
                        if _new_lbl != _curr_lbl:
                            pendientes.append({
                                "tipo": "recursado",
                                "dictado_id": None,
                                "materia_codigo": _mc,
                                "nombre": _m.nombre,
                                "actual": _curr_lbl,
                                "nuevo": _new_lbl,
                                "key": _k,
                            })
                # Deduplicar por (tipo, dictado_id|materia_codigo) — cuando
                # una misma materia se renderea en múltiples expanders
                # (ej. modo legacy) o en varios scopes (key_ns), nos
                # quedamos con uno solo. La key es la dimensión que
                # discrimina; deduplicamos por (tipo, target_id).
                _seen: set[tuple] = set()
                _dedup: list[dict] = []
                for p in pendientes:
                    _target = p["dictado_id"] or p["materia_codigo"]
                    _id = (p["tipo"], _target)
                    if _id in _seen:
                        continue
                    _seen.add(_id)
                    _dedup.append(p)
                return _dedup

            _pendientes = _detectar_pendientes()
            # Persistir conteo para guard del próximo render (Recalcular
            # / Crear Dictados leen este flag al inicio del flujo).
            st.session_state["dict_pending_count"] = len(_pendientes)
            if _pendientes:
                with st.container(border=True):
                    st.markdown(
                        f"### ⏳ Cambios pendientes ({len(_pendientes)})"
                    )
                    st.caption(
                        "Los toggles **no se aplican al instante**: "
                        "se acumulan acá hasta que apretes "
                        "**💾 Aplicar cambios**. Esto evita que Streamlit "
                        "pierda cambios cuando hacés clicks rápidos "
                        "consecutivos (cada cambio dispararía un rerun "
                        "que interrumpe el commit anterior)."
                    )
                    _rows_pend = []
                    for p in _pendientes:
                        if p["tipo"] == "recursado":
                            _attr_lbl = "Recursado"
                            _act = str(p["actual"])
                            _new = str(p["nuevo"])
                        elif p["tipo"] == "activo":
                            _attr_lbl = "Activo"
                            _act = "Activo" if p["actual"] else "Inactivo"
                            _new = "Activo" if p["nuevo"] else "Inactivo"
                        else:
                            _attr_lbl = "Virtual"
                            _act = "Sí" if p["actual"] else "No"
                            _new = "Sí" if p["nuevo"] else "No"
                        _rows_pend.append({
                            "Materia": (
                                f"{p['materia_codigo']} — {p['nombre']}"
                            ),
                            "Atributo": _attr_lbl,
                            "Actual": _act,
                            "Nuevo": _new,
                        })
                    st.dataframe(
                        _rows_pend,
                        use_container_width=True,
                        hide_index=True,
                    )

                    _ap1, _ap2, _ap3 = st.columns([1.4, 1.4, 4])
                    with _ap1:
                        if st.button(
                            f"💾 Aplicar {len(_pendientes)} cambio(s)",
                            type="primary",
                            key="btn_apply_batch_pending",
                        ):
                            _ok = 0
                            _fail: list[str] = []
                            with next(get_session()) as _ds:
                                for p in _pendientes:
                                    try:
                                        if p["tipo"] == "activo":
                                            set_activo_manual(
                                                _ds, p["dictado_id"],
                                                bool(p["nuevo"]),
                                            )
                                        elif p["tipo"] == "virtual":
                                            update_dictado(
                                                _ds, p["dictado_id"],
                                                virtual=bool(p["nuevo"]),
                                            )
                                        elif p["tipo"] == "recursado":
                                            _new_val = (
                                                None if p["nuevo"] == "Según Carrera"
                                                else (
                                                    True if p["nuevo"] == "Sí"
                                                    else False
                                                )
                                            )
                                            _m_db = _ds.get(
                                                MateriaDB,
                                                p["materia_codigo"],
                                            )
                                            if _m_db is not None:
                                                _m_db.dicta_recursado = _new_val
                                                _ds.add(_m_db)
                                                _ds.commit()
                                        _ok += 1
                                    except Exception as _e:
                                        _fail.append(
                                            f"{p['materia_codigo']} "
                                            f"({p['tipo']}): {_e}"
                                        )
                            # Limpiar las keys aplicadas + marcar resync
                            # para que el próximo render alinee el resto
                            # del session_state (por las dudas) con DB.
                            for p in _pendientes:
                                st.session_state.pop(p["key"], None)
                            st.session_state["dict_resync_pending"] = True
                            if _fail:
                                st.error(
                                    f"{_ok} aplicados, {len(_fail)} con "
                                    "error:\n" + "\n".join(_fail)
                                )
                            else:
                                st.toast(
                                    f"✅ {_ok} cambio(s) aplicados."
                                )
                            st.rerun()
                    with _ap2:
                        if st.button(
                            "🚫 Descartar cambios",
                            key="btn_discard_batch_pending",
                            help=(
                                "Limpia el session_state de los widgets "
                                "modificados, así vuelven a mostrar el "
                                "valor actual de DB."
                            ),
                        ):
                            for p in _pendientes:
                                st.session_state.pop(p["key"], None)
                            st.toast("Cambios descartados.")
                            st.rerun()

            def _matches(item: dict) -> bool:
                pe = item["pe"]
                mat = item["materia"]
                d = item["dictado"]
                # search
                if _q:
                    qn = _q.strip().lower()
                    if qn not in mat.codigo.lower() and qn not in mat.nombre.lower():
                        return False
                # estado: solo aplica filtro si hay dictado.
                # Las "sin dictado" (legacy) se muestran siempre con badge.
                if d is not None:
                    if d.activo and "Activo" not in _estado:
                        return False
                    if not d.activo and "Inactivo" not in _estado:
                        return False
                # modalidad: si hay dictado, prima dictado.virtual; sin dictado, materia.virtual
                _is_virtual = d.virtual if d is not None else mat.virtual
                if _is_virtual and "Virtual" not in _modal:
                    return False
                if not _is_virtual and "Presencial" not in _modal:
                    return False
                # anio
                if pe.anio_plan is not None and pe.anio_plan not in _anios_sel:
                    return False
                # cuatri
                _ck = pe.cuatrimestre_plan or "—"
                if _ck not in _cuatris_sel:
                    return False
                # optativas
                if _opt_filt == "Solo" and not pe.optativa:
                    return False
                if _opt_filt == "Excluir" and pe.optativa:
                    return False
                return True

            # =========================================================
            # Per-carrera expanders
            # =========================================================
            # Auto-save por widget: cada toggle dispara commit + rerun
            # cuando su valor difiere del valor en DB. Funciona porque
            # cada `dictado_id` se renderea **una sola vez** en el run
            # (las exclusivas dentro del expander de su carrera; las
            # comunes en un expander aparte). Eso garantiza que NO hay
            # widgets duplicados leyendo/escribiendo el mismo dictado
            # en el mismo render — lo que antes provocaba race
            # conditions con materias compartidas.

            def _render_item(
                item: dict, carrera_cod: str, *,
                key_ns: str = "exc",
                carreras_label: str | None = None,
            ) -> None:
                """Render one materia row.

                Args:
                    item: dict con materia/pe/dictado/otras.
                    carrera_cod: código de la carrera del expander que
                        está renderando (para keys; para exclusivas es
                        la única carrera; para comunes una representativa).
                    key_ns: namespace de keys de widget. Por default
                        ``"exc"`` (expander por carrera). El expander
                        de comunes pasa ``"com"`` para tener su propio
                        scope.
                    carreras_label: si se pasa, se incluye en la línea
                        de info ("🎓 IA, IM, IS"). Se usa en el expander
                        de comunes; en los expanders por carrera no
                        hace falta porque está implícito.
                """
                mat = item["materia"]
                pe = item["pe"]
                d = item["dictado"]
                # `otras` queda como atributo legacy de items exclusivos
                # (vacío). En items de comunes no existe; usamos
                # `carreras_label` para mostrar las carreras.
                otras = item.get("otras", [])

                col_info, col_meta, col_rec, col_activo, col_virtual = st.columns(
                    [4, 1.6, 1.4, 1, 1]
                )

                # Detectar diff session_state vs DB para mostrar
                # marca de "pendiente" en el badge. Los toggles son
                # batch: NO commitean al instante; sólo escriben a
                # session_state. Streamlit interrumpe reruns cuando el
                # usuario hace clicks rápidos en sucesión, lo que puede
                # cancelar commits intermedios y hacer "perder" cambios.
                # El batch evita eso porque hay una única transacción al
                # apretar "Aplicar cambios" abajo.
                _activo_key = (
                    f"activo_{key_ns}_{carrera_cod}_{d.id}"
                    if d is not None else ""
                )
                _virtual_key = (
                    f"virtual_{key_ns}_{carrera_cod}_{d.id}"
                    if d is not None else ""
                )
                _rec_key = f"rec_mat_{key_ns}_{carrera_cod}_{mat.codigo}"
                _has_pending = False
                if d is not None and _activo_key in st.session_state:
                    if bool(st.session_state[_activo_key]) != d.activo:
                        _has_pending = True
                if d is not None and _virtual_key in st.session_state:
                    if bool(st.session_state[_virtual_key]) != d.virtual:
                        _has_pending = True
                if _rec_key in st.session_state:
                    _curr_lbl = (
                        "Según Carrera" if mat.dicta_recursado is None
                        else ("Sí" if mat.dicta_recursado else "No")
                    )
                    if st.session_state[_rec_key] != _curr_lbl:
                        _has_pending = True

                with col_info:
                    # Estado tag
                    if d is None:
                        _badge = "🔘 Sin dictado"
                    elif d.activo:
                        _badge = "🟢 Activo"
                    else:
                        _badge = "⚪ Inactivo"
                    if d is not None and d.activo_override_manual is not None:
                        _badge += " · ✋ editado a mano"
                    _virt = " · 🌐 virtual" if (
                        (d.virtual if d else mat.virtual)
                    ) else ""
                    _opt = " · 📘 optativa" if pe.optativa else ""
                    _anu = " · 📅 anual" if mat.periodo == "anual" else ""
                    _pend_marker = (
                        " · <span style='color:#f0ad4e'>⏳ pendiente</span>"
                        if _has_pending else ""
                    )
                    st.markdown(
                        f"**{mat.codigo}** — {mat.nombre}  \n"
                        f"<span style='color:#888;font-size:0.85em'>"
                        f"{_badge}{_virt}{_opt}{_anu}{_pend_marker}"
                        f"</span>",
                        unsafe_allow_html=True,
                    )
                    if carreras_label:
                        # Caso comunes: muestro las carreras donde aparece.
                        st.caption(f"🎓 {carreras_label}")
                    else:
                        # Caso exclusivas: la materia no se comparte; las
                        # comunes ya quedan filtradas a su propio expander.
                        if d is None:
                            _sm_razon = skipped_razones.get(mat.codigo, "")
                            if _sm_razon:
                                st.caption(_sm_razon)

                with col_meta:
                    _anio = f"{pe.anio_plan}°" if pe.anio_plan else "—"
                    _cuatri = pe.cuatrimestre_plan or "—"
                    st.caption(
                        f"Año: **{_anio}** · Cuatri: **{_cuatri}**  \n"
                        f"h/sem: {mat.horas_semanales or '—'}"
                    )

                # Override de dicta_recursado por materia (3 estados).
                # Sin commit aquí: el valor queda en session_state[_rec_key]
                # y se aplica desde el botón "Aplicar cambios" abajo.
                with col_rec:
                    _rec_options = ["Según Carrera", "Sí", "No"]
                    _curr_idx = (
                        0 if mat.dicta_recursado is None
                        else (1 if mat.dicta_recursado else 2)
                    )
                    st.selectbox(
                        "Recursado",
                        options=_rec_options,
                        index=_curr_idx,
                        key=_rec_key,
                        label_visibility="visible",
                    )

                if d is not None:
                    with col_activo:
                        st.checkbox(
                            "Activo",
                            value=d.activo,
                            key=_activo_key,
                        )
                        # Botón para limpiar la edición manual y volver
                        # a alinear el dictado con la regla. Mantenemos
                        # commit inmediato porque es una acción puntual
                        # del usuario, no parte del batch.
                        if d.activo_override_manual is not None:
                            if st.button(
                                "Quitar edición manual",
                                key=(
                                    f"clear_ovr_{key_ns}_{carrera_cod}_{d.id}"
                                ),
                            ):
                                with next(get_session()) as _ds:
                                    clear_activo_override(_ds, d.id)
                                st.toast(
                                    f"{mat.codigo}: edición manual "
                                    "descartada"
                                )
                                st.rerun()
                    with col_virtual:
                        st.checkbox(
                            "Virtual",
                            value=d.virtual,
                            key=_virtual_key,
                        )
                else:
                    # Caso raro: materia del plan sin dictado todavia. Suele
                    # pasar solo en estado intermedio (DB pre-migracion).
                    # Apretar "Crear Dictados" arriba completa el set.
                    with col_activo:
                        st.caption("(Sin dictado)")
                    with col_virtual:
                        st.caption("—")

            for carrera_cod in sorted(items_by_carrera.keys()):
                carrera_nombre = carrera_nombres.get(carrera_cod, carrera_cod)
                items = items_by_carrera[carrera_cod]
                # filter
                items_filt = [it for it in items if _matches(it)]
                # Header stats
                n_obl = sum(1 for it in items_filt if not it["pe"].optativa)
                n_opt = sum(1 for it in items_filt if it["pe"].optativa)
                n_act = sum(
                    1 for it in items_filt
                    if it["dictado"] and it["dictado"].activo
                )
                n_inact = sum(
                    1 for it in items_filt
                    if it["dictado"] and not it["dictado"].activo
                )
                n_sd = sum(1 for it in items_filt if it["dictado"] is None)
                _hdr = (
                    f"🎓 {carrera_cod} · {carrera_nombre} — "
                    f"{len(items_filt)} materia(s) "
                    f"(🟢 {n_act} · ⚪ {n_inact} · 🔘 {n_sd})"
                )

                if _force_state is True:
                    _expanded = True
                elif _force_state is False:
                    _expanded = False
                else:
                    _expanded = True
                with st.expander(_hdr, expanded=_expanded):
                    # =================================================
                    # Configuración de la carrera (editable inline)
                    # =================================================
                    _carr = carrera_objs.get(carrera_cod)
                    if _carr is not None:
                        with st.container(border=True):
                            st.markdown("**⚙️ Configuración**")
                            _cc1, _cc2 = st.columns(2)
                            with _cc1:
                                _new_rec = st.toggle(
                                    "Carrera dicta recursado",
                                    value=_carr.dicta_recursado,
                                    key=f"cfg_carr_rec_{carrera_cod}",
                                    help=(
                                        "Si está activo, todas las materias "
                                        "(obligatorias o de cuatri opuesto) se "
                                        "crean activas por defecto. Si está "
                                        "apagado, las del cuatri opuesto a este "
                                        "ciclo se crean inactivas (salvo que "
                                        "la materia tenga marcado un "
                                        "recursado propio que prevalezca)."
                                    ),
                                )
                                if _new_rec != _carr.dicta_recursado:
                                    with next(get_session()) as _ds:
                                        _c_db = _ds.get(CarreraDB, carrera_cod)
                                        if _c_db:
                                            _c_db.dicta_recursado = _new_rec
                                            _ds.add(_c_db)
                                            _ds.commit()
                                    st.toast(
                                        f"{carrera_cod}: dicta_recursado = "
                                        f"{'Sí' if _new_rec else 'No'}. "
                                        "Apretá 🔄 Recalcular arriba para alinear "
                                        "dictados existentes."
                                    )
                                    st.rerun()
                            with _cc2:
                                _avail = _available_pvs_by_carrera.get(carrera_cod, [])
                                _curr_pv_id = _current_pv_by_carrera.get(carrera_cod)
                                if len(_avail) > 1:
                                    _pv_options = {pv.id: pv.nombre for pv in _avail}
                                    _pv_idx = (
                                        list(_pv_options.keys()).index(_curr_pv_id)
                                        if _curr_pv_id in _pv_options else 0
                                    )
                                    _new_pv = st.selectbox(
                                        "Plan asignado al ciclo",
                                        options=list(_pv_options.keys()),
                                        index=_pv_idx,
                                        format_func=lambda x: _pv_options[x],
                                        key=f"cfg_carr_pv_{carrera_cod}",
                                        help=(
                                            "Cambiar la versión del plan asignada "
                                            "a esta carrera en este ciclo. Las "
                                            "materias del plan nuevo pueden diferir; "
                                            "tocá 🔄 Recalcular después para alinear."
                                        ),
                                    )
                                    if _curr_pv_id and _new_pv != _curr_pv_id:
                                        with next(get_session()) as _ds:
                                            _ok = swap_plan_version_for_ciclo(
                                                _ds, sel_ciclo_dict,
                                                carrera_cod, _new_pv,
                                            )
                                        if _ok:
                                            st.toast(
                                                f"Plan de {carrera_cod} cambiado. "
                                                "Apretá 🔄 Recalcular arriba."
                                            )
                                            st.rerun()
                                elif _avail:
                                    st.caption(
                                        f"Plan: **{_avail[0].nombre}** "
                                        "(única versión disponible)"
                                    )
                                else:
                                    st.caption("Sin versiones de plan.")

                    if not items_filt:
                        st.caption("No hay materias que cumplan los filtros.")
                        continue

                    # Split obligatorias / optativas
                    obligatorias = [
                        it for it in items_filt if not it["pe"].optativa
                    ]
                    optativas = [it for it in items_filt if it["pe"].optativa]

                    if obligatorias:
                        if optativas:
                            st.markdown(f"**Obligatorias ({len(obligatorias)})**")
                        # Sort: por anio, cuatri, codigo
                        obligatorias.sort(key=lambda it: (
                            it["pe"].anio_plan or 99,
                            it["pe"].cuatrimestre_plan or "",
                            it["materia"].codigo,
                        ))
                        for it in obligatorias:
                            _render_item(it, carrera_cod)

                    if optativas:
                        if obligatorias:
                            st.markdown(f"**Optativas ({len(optativas)})**")
                        else:
                            st.caption(f"{len(optativas)} optativa(s).")
                        optativas.sort(key=lambda it: (
                            it["pe"].anio_plan or 99,
                            it["materia"].codigo,
                        ))
                        for it in optativas:
                            _render_item(it, carrera_cod)

            # =========================================================
            # Expander de Comunes (materias compartidas entre 2+ carreras)
            # =========================================================
            #
            # Las comunes se renderean una vez sola, con su propio set
            # de filtros (incluye un filtro extra por carrera: si elegís
            # "Industrial" + "Mecánica", se muestran las comunes que
            # pertenecen a *cualquiera* de las dos — lógica OR).
            #
            # Diseño: una sola entrada por materia (no por carrera),
            # garantizando que cada `dictado_id` se renderea una sola
            # vez por run. Esto elimina las race conditions entre
            # widgets duplicados que existían cuando renderábamos la
            # misma materia compartida en cada carrera donde aparecía.
            if items_comunes_by_mat:
                _items_comunes = list(items_comunes_by_mat.values())
                # Filtros base (los del top) + filtro por carrera
                # exclusivo del expander de Comunes.
                _all_carreras_de_comunes = sorted({
                    cc for it in _items_comunes
                    for cc in it["carreras"]
                })
                _carreras_de_comunes_filt = st.multiselect(
                    "Filtrar comunes por carrera (lógica O — pertenece a "
                    "cualquiera de las elegidas)",
                    options=_all_carreras_de_comunes,
                    default=_all_carreras_de_comunes,
                    format_func=lambda cc: (
                        f"{cc} — {carrera_nombres.get(cc, cc)}"
                    ),
                    key="dict_com_carreras_filt",
                    help=(
                        "Sólo muestra materias comunes que pertenecen "
                        "al menos a una de las carreras seleccionadas. "
                        "Combinable con los demás filtros de arriba."
                    ),
                )
                _carr_filt_set = set(_carreras_de_comunes_filt)

                # Aplicamos los filtros generales + el de carrera específico.
                _items_comunes_filt = [
                    it for it in _items_comunes
                    if _matches(it)
                    and (set(it["carreras"]) & _carr_filt_set)
                ]

                # Stats del header del expander
                _n_obl = sum(
                    1 for it in _items_comunes_filt if not it["pe"].optativa
                )
                _n_opt = sum(
                    1 for it in _items_comunes_filt if it["pe"].optativa
                )
                _n_act = sum(
                    1 for it in _items_comunes_filt
                    if it["dictado"] and it["dictado"].activo
                )
                _n_inact = sum(
                    1 for it in _items_comunes_filt
                    if it["dictado"] and not it["dictado"].activo
                )
                _n_sd = sum(
                    1 for it in _items_comunes_filt
                    if it["dictado"] is None
                )
                _hdr_com = (
                    f"🔗 Comunes — {len(_items_comunes_filt)} materia(s) "
                    f"(🟢 {_n_act} · ⚪ {_n_inact} · 🔘 {_n_sd})"
                )
                if _force_state is True:
                    _expanded_com = True
                elif _force_state is False:
                    _expanded_com = False
                else:
                    _expanded_com = True

                with st.expander(_hdr_com, expanded=_expanded_com):
                    st.caption(
                        "Materias compartidas entre dos o más carreras "
                        "del ciclo. Al ser un único `DictadoDB` por "
                        "materia, los toggles aquí afectan a todas las "
                        "carreras donde la materia aparece. "
                        f"Total sin filtrar: {len(_items_comunes)} "
                        f"materia(s) · obligatorias: {_n_obl} · "
                        f"optativas: {_n_opt}."
                    )

                    if not _items_comunes_filt:
                        st.caption(
                            "No hay materias comunes que cumplan los filtros."
                        )
                    else:
                        # Split obligatorias / optativas
                        _obl = [
                            it for it in _items_comunes_filt
                            if not it["pe"].optativa
                        ]
                        _opt = [
                            it for it in _items_comunes_filt
                            if it["pe"].optativa
                        ]

                        if _obl:
                            if _opt:
                                st.markdown(
                                    f"**Obligatorias ({len(_obl)})**"
                                )
                            _obl.sort(key=lambda it: (
                                it["pe"].anio_plan or 99,
                                it["pe"].cuatrimestre_plan or "",
                                it["materia"].codigo,
                            ))
                            for it in _obl:
                                _render_item(
                                    it,
                                    carrera_cod=it["carreras"][0],
                                    key_ns="com",
                                    carreras_label=", ".join(it["carreras"]),
                                )

                        if _opt:
                            if _obl:
                                st.markdown(
                                    f"**Optativas ({len(_opt)})**"
                                )
                            else:
                                st.caption(
                                    f"{len(_opt)} optativa(s)."
                                )
                            _opt.sort(key=lambda it: (
                                it["pe"].anio_plan or 99,
                                it["materia"].codigo,
                            ))
                            for it in _opt:
                                _render_item(
                                    it,
                                    carrera_cod=it["carreras"][0],
                                    key_ns="com",
                                    carreras_label=", ".join(it["carreras"]),
                                )

            # Nota: ya no hay batch save. Los toggles Activo/Virtual
            # se persisten on-change. El toggle Activo además registra
            # un override manual que sobrevive a "Recalcular según
            # reglas" (salvo que se active "Pisar overrides").
