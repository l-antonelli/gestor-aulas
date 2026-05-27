"""Gestion de Planes de Cursada - Hub central de planificacion.

Flujo: Cronograma (schedule) → Validar cobertura → Generar Plan → Clases
"""

import uuid
import streamlit as st
import pandas as pd
from collections import Counter
from datetime import time, timedelta
from sqlmodel import select, func, col
from src.database.connection import get_session, init_db
from src.database.models import (
    PlanificacionCursadaDB, ComisionDB, HorarioDB, ClaseDB, MateriaDB,
    ScheduleDB, ScheduleEntryDB,
    CicloPlanVersionDB, PlanCarreraVersionDB, PlanEstudioDB,
    CarreraDB, ConfiguracionHoraria, MateriaLaboratorioDB,
)
from src.database.crud import ciclo_crud, materia_crud, get_or_create_config, update_config
from src.services.plan_generation_service import (
    generate_plan_from_schedule,
    generate_plan_from_preview,
    preview_plan_from_schedule,
    activate_plan,
    generate_time_slots,
    build_timetable_grid,
    apply_horario_edits,
    MateriaPreview,
    EntryPreview,
    SchedulePreviewResult,
)
from src.services.clase_generation_service import generate_clases_for_plan
from src.services.validations import (
    validar_conflictos_horarios_plan,
    validar_cobertura_plan,
    identificar_virtuales_plan,
)
from src.ui.calendar_render import render_timetable_calendar
from src.domain.types import DIAS_SEMANA

init_db()


def _fmt_hours(h: float) -> str:
    """Format hours: '18h' if integer, '17.5h' otherwise."""
    return f"{h:g}h"


def _parse_minutes(val) -> int | None:
    """Parse a time value to total minutes. Handles time objects and 'HH:MM' strings."""
    if hasattr(val, "hour"):
        return val.hour * 60 + val.minute
    if isinstance(val, str) and ":" in val:
        parts = val.split(":")
        try:
            return int(parts[0]) * 60 + int(parts[1])
        except ValueError:
            return None
    return None


def _time_str(val) -> str:
    """Convert a time value to 'HH:MM' string."""
    if hasattr(val, "strftime"):
        return val.strftime("%H:%M")
    if isinstance(val, str):
        return val[:5]
    return str(val)


_BASE_TIME_OPTIONS = [
    f"{h:02d}:{m:02d}" for h in range(7, 24) for m in (0, 15, 30, 45)
]


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

tab_generar, tab_general, tab_detalle, tab_grilla, tab_clases, tab_config = st.tabs([
    "📥 Generar Plan",
    "📋 Vista General", "🔍 Detalle del Plan",
    "📋 Grilla Horaria", "📅 Clases", "⚙️ Configuración",
])


# =============================================================================
# Helper: faltantes por carrera (legacy, ya no usado en esta pagina)
# =============================================================================
def _get_faltantes_por_carrera(
    session, ciclo_id: str, materias_en_schedule: set[str],
) -> list[dict]:
    """Return enriched faltantes grouped by carrera with plan info and reasons.

    NOTA: La fuente de verdad para faltantes ahora es
    `src/services/cronograma_validation_service.py::_get_faltantes_por_carrera`,
    que toma como base los dictados activos del ciclo. Este helper queda
    sin uso aca (la pestaña Validacion se movio a Cronogramas) pero se
    deja por si algun consumidor externo lo importaba.
    """
    ciclo = ciclo_crud.get(session, ciclo_id)
    if not ciclo:
        return []
    cuatri_ciclo = f"{ciclo.numero}C"  # "1C" or "2C"

    # Get plan versions linked to this ciclo
    cpv_rows = session.exec(
        select(CicloPlanVersionDB).where(CicloPlanVersionDB.ciclo_id == ciclo_id)
    ).all()

    result = []
    for cpv in cpv_rows:
        pv = session.get(PlanCarreraVersionDB, cpv.plan_version_id)
        if not pv:
            continue
        carrera = session.get(CarreraDB, pv.carrera_codigo)
        if not carrera:
            continue

        # Get all plan_estudio entries for this plan version
        pe_rows = session.exec(
            select(PlanEstudioDB)
            .where(PlanEstudioDB.plan_version_id == pv.id)
            .order_by(PlanEstudioDB.anio_plan, PlanEstudioDB.cuatrimestre_plan)
        ).all()

        # Filter to missing materias only
        faltantes_pe = [
            pe for pe in pe_rows
            if pe.materia_codigo not in materias_en_schedule
        ]
        if not faltantes_pe:
            continue

        # Batch load materia info
        falt_codigos = list({pe.materia_codigo for pe in faltantes_pe})
        mats_db = session.exec(
            select(MateriaDB).where(col(MateriaDB.codigo).in_(falt_codigos))
        ).all()
        mat_map = {m.codigo: m for m in mats_db}

        materias_faltantes = []
        for pe in faltantes_pe:
            mat = mat_map.get(pe.materia_codigo)
            if not mat:
                continue

            cuatri = pe.cuatrimestre_plan
            if cuatri and cuatri == cuatri_ciclo:
                razon = f"Materia del {cuatri_ciclo}, sin horarios"
            elif cuatri and cuatri.lower() == "anual":
                razon = "Materia anual, se espera en ambos cuatrimestres"
            elif cuatri:
                if carrera.dicta_recursado:
                    razon = f"Es de {cuatri}, incluida por recursado"
                else:
                    razon = f"Es de {cuatri} (carrera no dicta recursado)"
            else:
                razon = "Sin cuatrimestre asignado en el plan"

            materias_faltantes.append({
                "codigo": mat.codigo,
                "nombre": mat.nombre,
                "anio_plan": pe.anio_plan,
                "cuatrimestre_plan": pe.cuatrimestre_plan,
                "optativa": pe.optativa,
                "periodo": mat.periodo,
                "horas_semanales": mat.horas_semanales,
                "virtual": mat.virtual,
                "razon": razon,
            })

        if materias_faltantes:
            result.append({
                "carrera_codigo": carrera.codigo,
                "carrera_nombre": carrera.nombre,
                "plan_version_nombre": pv.nombre,
                "dicta_recursado": carrera.dicta_recursado,
                "materias": materias_faltantes,
            })

    result.sort(key=lambda x: x["carrera_codigo"])
    return result



# =============================================================================
# Helper: render del editor de Plan (reutilizable desde Detalle y desde wizard)
# =============================================================================
def _render_plan_editor(
    sel_plan_id: str, planes_detalle: list, key_ns: str = "detalle",
) -> None:
    """Renderiza el editor completo del plan: metadata, validaciones,
    filtros, factibilidad teoria/lab, comisiones, horarios, coef y forecast.

    Reutilizable desde el tab Detalle (con selector externo) y desde el
    paso 2 del wizard de Generar Plan (con plan_id ya conocido).

    Args:
        sel_plan_id: id del plan a editar.
        planes_detalle: lista de PlanificacionCursadaDB que contiene al
            menos el plan en cuestion (se busca por id).
        key_ns: namespace para las keys de session_state que NO incluyen
            el plan_id. Default "detalle"; el wizard pasa "wizard" para
            evitar colisiones si ambas pestañas se renderean en el mismo run.
    """
    sel_plan = next(p for p in planes_detalle if p.id == sel_plan_id)
    sel_ciclo_detalle = sel_plan.ciclo_id
    
    # --- Editable metadata ---
    st.markdown("#### Metadata")
    with st.form(f"edit_plan_{key_ns}_{sel_plan_id}"):
        nuevo_nombre = st.text_input("Nombre", value=sel_plan.nombre)
        nueva_desc = st.text_area("Descripcion", value=sel_plan.descripcion or "")
    
        # Selector de método de forecast default del plan
        from src.services.forecast_service import (
            METODO_LABELS as _PM_LABELS,
            METODOS_DISPONIBLES as _PM_AVAIL,
        )
        _curr_metodo = sel_plan.forecast_metodo_default or "media_movil"
        _curr_idx = (
            _PM_AVAIL.index(_curr_metodo)
            if _curr_metodo in _PM_AVAIL else 0
        )
        nuevo_metodo = st.selectbox(
            "Método de forecast (default del plan)",
            options=list(_PM_AVAIL),
            index=_curr_idx,
            format_func=lambda m: _PM_LABELS.get(m, m),
            help=(
                "Método aplicado por defecto a todas las materias "
                "del plan al calcular inscriptos esperados. "
                "Editable por materia más abajo (override)."
            ),
        )
        save_meta = st.form_submit_button("Guardar", type="primary")
    
        if save_meta:
            with next(get_session()) as session:
                db_plan = session.get(PlanificacionCursadaDB, sel_plan_id)
                if db_plan:
                    db_plan.nombre = nuevo_nombre
                    db_plan.descripcion = nueva_desc
                    db_plan.forecast_metodo_default = nuevo_metodo
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
    
    # --- Validations panel ---
    st.markdown("#### Validaciones")
    
    has_blocker = False
    
    if st.button("Validar plan", key=f"{key_ns}_btn_validate_{sel_plan_id}"):
        with next(get_session()) as session:
            v_conflicts = validar_conflictos_horarios_plan(session, sel_plan_id)
            v_coverage = validar_cobertura_plan(session, sel_plan_id, sel_ciclo_detalle)
            v_virtual = identificar_virtuales_plan(session, sel_plan_id)
    
        st.session_state[f"validation_results_{sel_plan_id}"] = {
            "conflicts": v_conflicts,
            "coverage": v_coverage,
            "virtual": v_virtual,
        }
    
    # Display stored results
    vr_key = f"validation_results_{sel_plan_id}"
    if vr_key in st.session_state:
        vr = st.session_state[vr_key]
    
        # BLOCKER: Conflictos de horarios
        v_conflicts = vr["conflicts"]
        if not v_conflicts.valid:
            has_blocker = True
            st.error(f"BLOQUEANTE: {v_conflicts.message}")
            with st.expander("Detalles de conflictos", expanded=False):
                for d in v_conflicts.details:
                    st.text(f"  - {d}")
        else:
            st.success(v_conflicts.message)
    
        # WARNING: Cobertura
        v_coverage = vr["coverage"]
        if not v_coverage.valid:
            st.warning(f"ADVERTENCIA: {v_coverage.message}")
            with st.expander("Materias sin cobertura", expanded=False):
                for d in v_coverage.details:
                    st.text(f"  - {d}")
        else:
            st.success(v_coverage.message)
    
        # INFO: Virtuales
        v_virtual = vr["virtual"]
        if v_virtual.details:
            st.info(f"INFO: {v_virtual.message}")
            with st.expander("Materias virtuales", expanded=False):
                for d in v_virtual.details:
                    st.text(f"  - {d}")
        else:
            st.info(v_virtual.message)
    
        # Activation gate
        if has_blocker:
            st.error(
                "No se puede activar el plan: hay conflictos bloqueantes. "
                "Resuelva los conflictos y vuelva a validar."
            )
        elif not sel_plan.activo:
            if st.button(
                "Activar plan",
                type="primary",
                key=f"{key_ns}_btn_activate_validated_{sel_plan_id}",
            ):
                with next(get_session()) as session:
                    activate_plan(session, sel_plan_id)
                st.success(f"Plan '{sel_plan.nombre}' activado")
                st.rerun()
    
    st.divider()
    
    # --- Filters ---
    st.markdown("#### Filtros")
    with next(get_session()) as session:
        # Get carreras linked to this ciclo's plan versions
        plan_version_ids = session.exec(
            select(CicloPlanVersionDB.plan_version_id)
            .where(CicloPlanVersionDB.ciclo_id == sel_ciclo_detalle)
        ).all()
    
        carreras_in_ciclo = []
        if plan_version_ids:
            carreras_in_ciclo = session.exec(
                select(CarreraDB)
                .join(PlanCarreraVersionDB, CarreraDB.codigo == PlanCarreraVersionDB.carrera_codigo)
                .where(PlanCarreraVersionDB.id.in_(plan_version_ids))
                .distinct()
            ).all()
    
    col_f1, col_f2, col_f3 = st.columns(3)
    with col_f1:
        carrera_options = [f"{c.codigo} - {c.nombre}" for c in carreras_in_ciclo]
        filtro_carrera = st.selectbox(
            "Carrera", options=carrera_options,
            index=None, placeholder="Seleccionar carrera...",
            key=f"{key_ns}_filtro_carrera",
        )
    with col_f2:
        filtro_anio = st.selectbox(
            "Año", options=[1, 2, 3, 4, 5, 6],
            index=None, placeholder="Seleccionar año...",
            key=f"{key_ns}_filtro_anio",
        )
    with col_f3:
        filtro_cuatri = st.selectbox(
            "Cuatrimestre",
            options=["1C", "2C", "Anual"],
            index=None, placeholder="Seleccionar cuatrimestre...",
            key=f"{key_ns}_filtro_cuatri",
        )
    
    # Determine which materia_codigos pass the filter
    # Require all 3 filters to show materias (avoid loading everything)
    _all_filters_set = (
        filtro_carrera is not None
        and filtro_anio is not None
        and filtro_cuatri is not None
    )
    filtered_materia_codigos: set[str] | None = None
    if _all_filters_set:
        with next(get_session()) as session:
            query = (
                select(PlanEstudioDB.materia_codigo)
                .where(PlanEstudioDB.plan_version_id.in_(plan_version_ids))
            )
            carrera_cod = filtro_carrera.split(" - ")[0]
            query = query.where(PlanEstudioDB.carrera_codigo == carrera_cod)
            query = query.where(PlanEstudioDB.anio_plan == int(filtro_anio))
            if filtro_cuatri == "Anual":
                query = query.where(PlanEstudioDB.cuatrimestre_plan.in_(["Anual", "anual"]))
            else:
                query = query.where(PlanEstudioDB.cuatrimestre_plan == filtro_cuatri)
            filtered_materia_codigos = set(session.exec(query.distinct()).all())
    
    st.divider()
    
    # --- Breakdown by materia (editable) ---
    st.markdown("#### Desglose por Materia")
    
    if not _all_filters_set:
        st.caption(
            "Seleccioná Carrera, Año y Cuatrimestre para ver "
            "las materias del plan."
        )
        filtered_materia_codigos = set()  # empty → nothing shown
    
    with next(get_session()) as session:
        # Load config for time slot generation
        config = get_or_create_config(session)
        time_slots = generate_time_slots(config)
    
    with next(get_session()) as session:
        comisiones = list(session.exec(
            select(ComisionDB)
            .where(ComisionDB.plan_cursada_id == sel_plan_id)
            .order_by(ComisionDB.materia_codigo, ComisionDB.numero)
        ).all())
    
        # Group by materia
        by_materia: dict[str, list[ComisionDB]] = {}
        for c in comisiones:
            by_materia.setdefault(c.materia_codigo, []).append(c)
    
        # Get materia names + full objects (para mostrar datos del catálogo)
        materia_codigos = list(by_materia.keys())
        materias_map: dict[str, str] = {}
        materias_in_plan: list[MateriaDB] = []
        if materia_codigos:
            materias_in_plan = list(session.exec(
                select(MateriaDB).where(col(MateriaDB.codigo).in_(materia_codigos))
            ).all())
            materias_map = {m.codigo: m.nombre for m in materias_in_plan}
    
        # Load horarios for all comisiones in one query
        comision_ids = [c.id for c in comisiones]
        all_horarios: list[HorarioDB] = []
        if comision_ids:
            all_horarios = list(session.exec(
                select(HorarioDB).where(col(HorarioDB.comision_id).in_(comision_ids))
            ).all())
        horarios_by_comision: dict[str, list[HorarioDB]] = {}
        for h in all_horarios:
            horarios_by_comision.setdefault(h.comision_id, []).append(h)
    
    # Apply filter
    display_materias = sorted(by_materia.keys())
    if filtered_materia_codigos is not None:
        display_materias = [m for m in display_materias if m in filtered_materia_codigos]
    
    if not display_materias:
        st.info("No hay materias que coincidan con los filtros.")
    else:
        dias_list = sorted(DIAS_SEMANA, key=lambda d: [
            "Lunes", "Martes", "Miércoles", "Jueves", "Viernes", "Sábado"
        ].index(d))
    
        # Pre-cómputo: factibilidad de partición teoría/lab para
        # todo el plan. Lo usamos para el resumen arriba y los
        # flags inline por comisión.
        from src.services.validations import (
            validar_factibilidad_particion_horas as _val_part,
        )
        with next(get_session()) as _part_sess:
            _part_res = _val_part(
                _part_sess, plan_cursada_id=sel_plan_id,
            )
        # Parseo: extraer comisiones infactibles de _part_res.details
        # Formato del details: "{materia} C{numero}: ..." según validations.py
        _infactibles_set: set[tuple[str, int]] = set()
        for _det in _part_res.details or []:
            # Buscar "MATXXX C1:" al inicio
            try:
                _hdr = _det.split(":", 1)[0].strip()
                _parts = _hdr.split()
                if len(_parts) >= 2 and _parts[1].startswith("C"):
                    _mc = _parts[0]
                    _cn = int(_parts[1][1:])
                    _infactibles_set.add((_mc, _cn))
            except (ValueError, IndexError):
                pass
    
        # Resumen general de factibilidad teoría/lab
        if not _part_res.valid:
            with st.container(border=True):
                st.markdown(
                    f"⚠️ **Partición teoría/lab: {_part_res.message}**"
                )
                st.caption(
                    "Para cada comisión con horas_laboratorio > 0, "
                    "las clases deben poder dividirse en subconjuntos "
                    "que sumen `horas_teoria` y `horas_laboratorio`. "
                    "Las comisiones afectadas tienen un ⚠️ inline abajo."
                )
                with st.expander(
                    f"Detalle de comisiones infactibles ({len(_part_res.details or [])})",
                    expanded=False,
                ):
                    for _det in _part_res.details or []:
                        st.markdown(f"- {_det}")
        else:
            st.success(
                f"✅ Partición teoría/lab: {_part_res.message}"
            )
    
        for mat_codigo in display_materias:
            mat_coms = by_materia[mat_codigo]
            mat_nombre = materias_map.get(mat_codigo, mat_codigo)
            label = f"{mat_nombre} ({mat_codigo}) - {len(mat_coms)} comision(es)"
            # Flag inline en header si hay alguna comisión infactible
            if any(
                (mat_codigo, c.numero) in _infactibles_set
                for c in mat_coms
            ):
                label = f"⚠️ {label}"
    
            with st.expander(label, expanded=False):
                # --- Datos del catálogo (read-only) ---
                _mat_db_obj = next(
                    (m for m in materias_in_plan if m.codigo == mat_codigo),
                    None,
                )
                if _mat_db_obj is not None:
                    _cat1, _cat2, _cat3, _cat4 = st.columns(4)
                    _cat1.markdown(
                        f"**hs/sem**: {_mat_db_obj.horas_semanales or '—'}"
                    )
                    _cat2.markdown(
                        f"**hs teoría**: {_mat_db_obj.horas_teoria or '—'}"
                    )
                    _cat3.markdown(
                        f"**hs lab**: {_mat_db_obj.horas_laboratorio or '—'}"
                    )
                    _cat4.markdown(
                        f"**período**: {_mat_db_obj.periodo}"
                    )
                    st.caption(
                        "Datos del catálogo (read-only). Para "
                        "modificarlos, ir a **📚 Materias**."
                    )
    
                # --- Bulk horario editor (data_editor) ---
                _de_dia_ord = {
                    "Lunes": 0, "Martes": 1, "Miércoles": 2,
                    "Jueves": 3, "Viernes": 4, "Sábado": 5,
                }
                _de_rows = []
                for _de_com in mat_coms:
                    for _de_h in horarios_by_comision.get(_de_com.id, []):
                        _de_rows.append({
                            "_hid": _de_h.id,
                            "Día": _de_h.dia,
                            "Inicio": _de_h.hora_inicio,
                            "Fin": _de_h.hora_fin,
                            "Comisión": _de_com.nombre,
                            "Tipo": _de_h.tipo_clase or "sin determinar",
                        })
    
                _de_df = (
                    pd.DataFrame(_de_rows)
                    if _de_rows
                    else pd.DataFrame(
                        columns=["_hid", "Día", "Inicio", "Fin", "Comisión", "Tipo"]
                    )
                )
                if not _de_df.empty:
                    _de_df["_sk"] = _de_df["Día"].map(_de_dia_ord).fillna(9)
                    _de_df = (
                        _de_df.sort_values(["Comisión", "_sk", "Inicio"])
                        .drop(columns="_sk")
                        .reset_index(drop=True)
                    )
    
                _com_name_options = [c.nombre for c in mat_coms]
                _de_edited = st.data_editor(
                    _de_df,
                    column_config={
                        "_hid": None,
                        "Día": st.column_config.SelectboxColumn(
                            "Día",
                            options=list(_de_dia_ord.keys()),
                            required=True,
                            width="medium",
                        ),
                        "Inicio": st.column_config.TimeColumn(
                            "Inicio", format="HH:mm",
                            required=True, width="small",
                            step=timedelta(minutes=15),
                        ),
                        "Fin": st.column_config.TimeColumn(
                            "Fin", format="HH:mm",
                            required=True, width="small",
                            step=timedelta(minutes=15),
                        ),
                        "Comisión": st.column_config.SelectboxColumn(
                            "Comisión",
                            options=_com_name_options,
                            required=True,
                            width="medium",
                        ),
                        "Tipo": st.column_config.SelectboxColumn(
                            "Tipo",
                            options=["sin determinar", "teorica", "laboratorio"],
                            default="sin determinar",
                            width="small",
                        ),
                    },
                    num_rows="dynamic",
                    use_container_width=True,
                    hide_index=True,
                    key=f"{key_ns}_de_horarios_{sel_plan_id}_{mat_codigo}",
                )
    
                # Detect changes
                _de_orig_cmp = _de_df[["Día", "Inicio", "Fin", "Comisión", "Tipo"]].reset_index(drop=True)
                _de_edit_cmp = _de_edited[["Día", "Inicio", "Fin", "Comisión", "Tipo"]].reset_index(drop=True)
                _de_has_changes = (
                    len(_de_orig_cmp) != len(_de_edit_cmp)
                    or not _de_orig_cmp.equals(_de_edit_cmp)
                )
    
                if _de_has_changes:
                    if st.button(
                        "💾 Guardar cambios de horarios",
                        key=f"{key_ns}_de_save_{sel_plan_id}_{mat_codigo}",
                        type="primary",
                    ):
                        # Build edited rows for apply_horario_edits
                        _com_name_to_num = {c.nombre: c.numero for c in mat_coms}
                        _de_valid = _de_edited.dropna(subset=["Día", "Inicio", "Fin"])
                        _de_edit_rows = []
                        for _idx, _row in _de_valid.iterrows():
                            _hid_v = (
                                _row["_hid"]
                                if pd.notna(_row.get("_hid"))
                                else f"new_{_idx}"
                            )
                            _com_num = _com_name_to_num.get(
                                _row["Comisión"],
                                mat_coms[0].numero,
                            )
                            _de_edit_rows.append({
                                "horario_id": _hid_v,
                                "comision_numero": _com_num,
                                "dia": _row["Día"],
                                "hora_inicio": _row["Inicio"],
                                "hora_fin": _row["Fin"],
                                "tipo_clase": None if (_row.get("Tipo") or "sin determinar") == "sin determinar" else str(_row["Tipo"]),
                            })
    
                        with next(get_session()) as session:
                            _u, _c, _d = apply_horario_edits(
                                session, sel_plan_id,
                                mat_codigo, _de_edit_rows,
                            )
                        st.toast(
                            f"Horarios actualizados: {_u} modificados, "
                            f"{_c} agregados, {_d} eliminados"
                        )
                        st.rerun()
    
                st.divider()
    
                # --- Coef sums + forecast info para esta materia ---
                from src.services.plan_generation_service import (
                    normalize_coef_asignacion as _norm_coef,
                    update_comision_coef as _upd_coef,
                    get_inscriptos_esperados_por_comision as _get_esperados,
                )
                from src.services.forecast_service import (
                    METODO_LABELS as _M_LABELS,
                    METODOS_DISPONIBLES as _M_AVAIL,
                    get_forecast_for_materia as _get_fc,
                    get_metodo_override as _get_ov,
                    resolve_metodo as _resolve_metodo,
                    set_metodo_override as _set_ov,
                )
    
                _coef_sum = sum(c.coef_asignacion for c in mat_coms)
                _coef_ok = abs(_coef_sum - 1.0) < 0.01
                _coef_color = "🟢" if _coef_ok else "🟡"
    
                # Forecast en cuatri del ciclo o anual (segun materia)
                _ciclo_obj = next(
                    (c for c in ciclos if c.id == sel_plan.ciclo_id),
                    None,
                )
                _cuatri_ciclo = (
                    f"{_ciclo_obj.numero}C" if _ciclo_obj else "?"
                )
    
                with next(get_session()) as _fc_sess:
                    _fc_cuatri_res = _get_fc(
                        _fc_sess, sel_plan_id, mat_codigo, _cuatri_ciclo,
                    )
                    _fc_anual_res = _get_fc(
                        _fc_sess, sel_plan_id, mat_codigo, "Anual",
                    )
                    _esperados_map = _get_esperados(
                        _fc_sess, sel_plan_id,
                    )
                    # Override actual (si existe) — buscamos en el cuatri
                    # que aplica para esta materia
                    _ov_cuatri = (
                        "Anual" if _fc_anual_res else _cuatri_ciclo
                    )
                    _ov_actual = _get_ov(
                        _fc_sess, sel_plan_id, mat_codigo, _ov_cuatri,
                    )
    
                _fc_used = (
                    _fc_anual_res if _fc_anual_res is not None
                    else _fc_cuatri_res
                )
    
                _info_c1, _info_c2, _info_c3 = st.columns([2, 3, 1])
                _info_c1.markdown(
                    f"**Coef total:** {_coef_color} {_coef_sum:.2f} "
                    f"(debe ser ~1.0)"
                )
                if _fc_used is not None:
                    _src = "Anual" if _fc_anual_res else _cuatri_ciclo
                    _info_c2.markdown(
                        f"**Forecast {_src}:** {_fc_used.valor:.0f} "
                        f"·  método: {_M_LABELS.get(_fc_used.metodo, _fc_used.metodo)}"
                        f"{' (override)' if _ov_actual else ' (default plan)'}"
                    )
                else:
                    _info_c2.markdown(
                        "**Forecast:** — *(sin serie histórica en Inscriptos)*"
                    )
                with _info_c3:
                    if not _coef_ok and st.button(
                        "Normalizar",
                        key=f"{key_ns}_norm_coef_{sel_plan_id}_{mat_codigo}",
                        help="Reasigna coef uniformemente (1/n)",
                    ):
                        with next(get_session()) as _norm_s:
                            _norm_coef(
                                _norm_s, sel_plan_id, mat_codigo,
                            )
                        st.toast("Coef normalizados.")
                        st.rerun()
    
                # Override del metodo de forecast (3 estados)
                if _fc_used is not None:
                    _ov_options = ["Default plan"] + [
                        _M_LABELS[m] for m in _M_AVAIL
                    ]
                    _ov_keys: list[str | None] = [None] + list(_M_AVAIL)
                    _ov_idx = 0
                    if _ov_actual in _M_AVAIL:
                        _ov_idx = _ov_keys.index(_ov_actual)
                    _ov_choice = st.selectbox(
                        "Método de forecast (override)",
                        options=list(range(len(_ov_keys))),
                        format_func=lambda i: _ov_options[i],
                        index=_ov_idx,
                        key=f"{key_ns}_fc_ov_{sel_plan_id}_{mat_codigo}",
                        help=(
                            "Override del método de forecast para "
                            "esta materia. 'Default plan' usa el "
                            "método configurado a nivel plan."
                        ),
                    )
                    _ov_new = _ov_keys[_ov_choice]
                    if _ov_new != _ov_actual:
                        with next(get_session()) as _ov_s:
                            _set_ov(
                                _ov_s, sel_plan_id, mat_codigo,
                                _ov_cuatri, _ov_new,
                            )
                        st.rerun()
    
                for com in mat_coms:
                    _com_flag = (
                        " ⚠️ partición teoría/lab infactible"
                        if (mat_codigo, com.numero) in _infactibles_set
                        else ""
                    )
                    st.markdown(
                        f"##### {com.nombre} (#{com.numero}){_com_flag}"
                    )
    
                    # --- Editable comision fields ---
                    col_name, col_cupo, col_coef, col_esp, col_del = st.columns([3, 1.5, 1.5, 1.2, 0.6])
                    with col_name:
                        new_name = st.text_input(
                            "Nombre", value=com.nombre,
                            key=f"{key_ns}_com_name_{com.id}",
                            label_visibility="collapsed",
                        )
                    with col_cupo:
                        new_cupo = st.number_input(
                            "Cupo", value=max(com.cupo, 1), min_value=1,
                            key=f"{key_ns}_com_cupo_{com.id}",
                        )
                    with col_coef:
                        new_coef = st.number_input(
                            "Coef",
                            value=float(com.coef_asignacion),
                            min_value=0.0, max_value=1.0,
                            step=0.05, format="%.2f",
                            key=f"{key_ns}_com_coef_{com.id}",
                            help=(
                                "Fracción de inscriptos esperados que "
                                "se asignan a esta comisión. La suma "
                                "por materia debe ser ≈1.0."
                            ),
                        )
                    with col_esp:
                        if com.id in _esperados_map:
                            st.metric(
                                "Esperados",
                                f"{_esperados_map[com.id]:.0f}",
                                label_visibility="visible",
                            )
                        else:
                            st.caption("Esperados: —")
                    with col_del:
                        st.write("")
                        if st.button("🗑️", key=f"{key_ns}_del_com_{com.id}", help="Eliminar comision"):
                            with next(get_session()) as session:
                                # Delete horarios first, then comision
                                hs = session.exec(
                                    select(HorarioDB).where(HorarioDB.comision_id == com.id)
                                ).all()
                                for h in hs:
                                    session.delete(h)
                                db_com = session.get(ComisionDB, com.id)
                                if db_com:
                                    session.delete(db_com)
                                session.commit()
                            st.success(f"Comision '{com.nombre}' eliminada")
                            st.rerun()
    
                    # Persist coef change immediately (no extra button)
                    if abs(new_coef - com.coef_asignacion) > 1e-9:
                        with next(get_session()) as _coef_s:
                            _upd_coef(_coef_s, com.id, new_coef)
                        st.rerun()
    
                    # Save comision changes if modified (name/cupo)
                    if new_name != com.nombre or new_cupo != com.cupo:
                        if st.button("💾 Guardar comision", key=f"{key_ns}_save_com_{com.id}"):
                            with next(get_session()) as session:
                                db_com = session.get(ComisionDB, com.id)
                                if db_com:
                                    db_com.nombre = new_name
                                    db_com.cupo = new_cupo
                                    session.add(db_com)
                                    session.commit()
                            st.success("Comision actualizada")
                            st.rerun()
    
                    # --- Horarios ---
                    com_horarios = horarios_by_comision.get(com.id, [])
                    if com_horarios:
                        for h in sorted(com_horarios, key=lambda x: (x.dia, x.hora_inicio)):
                            col_h_info, col_h_del = st.columns([5, 1])
                            with col_h_info:
                                st.text(
                                    f"  {h.dia} "
                                    f"{h.hora_inicio.strftime('%H:%M')}-"
                                    f"{h.hora_fin.strftime('%H:%M')}"
                                )
                            with col_h_del:
                                if st.button("✕", key=f"{key_ns}_del_h_{h.id}", help="Eliminar horario"):
                                    with next(get_session()) as session:
                                        db_h = session.get(HorarioDB, h.id)
                                        if db_h:
                                            session.delete(db_h)
                                            session.commit()
                                    st.success("Horario eliminado")
                                    st.rerun()
                    else:
                        st.caption("Sin horarios")
    
                    # --- Add horario form ---
                    with st.popover("➕ Agregar horario"):
                        add_dia = st.selectbox(
                            "Dia", options=dias_list,
                            key=f"{key_ns}_add_h_dia_{com.id}",
                        )
    
                        # Build time options from config slots
                        time_options = sorted(
                            {s for slot in time_slots for s in slot}
                        )
                        time_labels = {t: t.strftime("%H:%M") for t in time_options}
    
                        add_inicio = st.selectbox(
                            "Hora inicio",
                            options=time_options,
                            format_func=lambda t: time_labels[t],
                            key=f"{key_ns}_add_h_ini_{com.id}",
                        )
                        add_fin = st.selectbox(
                            "Hora fin",
                            options=time_options,
                            format_func=lambda t: time_labels[t],
                            index=min(1, len(time_options) - 1),
                            key=f"{key_ns}_add_h_fin_{com.id}",
                        )
    
                        if st.button("Agregar", key=f"{key_ns}_btn_add_h_{com.id}", type="primary"):
                            if add_fin <= add_inicio:
                                st.error("La hora de fin debe ser posterior a la de inicio")
                            else:
                                with next(get_session()) as session:
                                    new_h = HorarioDB(
                                        id=str(uuid.uuid4()),
                                        comision_id=com.id,
                                        codigo_materia=mat_codigo,
                                        dia=add_dia,
                                        hora_inicio=add_inicio,
                                        hora_fin=add_fin,
                                    )
                                    session.add(new_h)
                                    session.commit()
                                st.success("Horario agregado")
                                st.rerun()
    
                    if com != mat_coms[-1]:
                        st.divider()
    
                # --- Add comision button ---
                st.divider()
                if st.button(f"➕ Agregar comision", key=f"{key_ns}_add_com_{mat_codigo}"):
                    with next(get_session()) as session:
                        # Determine next numero
                        max_num = max(c.numero for c in mat_coms) if mat_coms else 0
                        new_numero = max_num + 1
                        mat_db = session.get(MateriaDB, mat_codigo)
                        cupo_default = mat_db.cupo if mat_db and mat_db.cupo else 30
    
                        new_com = ComisionDB(
                            id=str(uuid.uuid4()),
                            materia_codigo=mat_codigo,
                            plan_cursada_id=sel_plan_id,
                            comision_key=f"{mat_codigo}-{new_numero:03d}",
                            nombre=f"Comision {new_numero}",
                            numero=new_numero,
                            cupo=cupo_default,
                        )
                        session.add(new_com)
                        session.commit()
                    st.success(f"Comision {new_numero} agregada")
                    st.rerun()


# =============================================================================
# Tab 1: Generar Plan (wizard simplificado de 2 pasos)
# =============================================================================
#
# Filosofia:
# - Paso 1: Seleccion (ciclo + cronograma validado + metadata) y crear el plan
#           inmediatamente como borrador (activo=False).
# - Paso 2: Edicion del plan recien creado, embebiendo el editor del tab
#           "Detalle del Plan". El usuario hace los ajustes que quiera.
#           Cancelar = borra el plan en cascada. Confirmar = sale del modo
#           wizard y redirige al tab Detalle con el plan preseleccionado.
#
# Future work: hoy los datos de catalogo (horas_semanales, horas_teoria,
# horas_laboratorio) se muestran read-only en Detalle. Si quisieramos
# permitir overrides por plan sin tocar el catalogo, agregar una tabla
# `PlanMateriaConfigDB(plan_id, materia_codigo, horas_semanales,
# horas_teoria, horas_laboratorio)` consultada cuando el plan los necesita.


def _wizard_reset() -> None:
    """Limpia las keys del wizard."""
    for k in list(st.session_state.keys()):
        if isinstance(k, str) and k.startswith("wizard_"):
            del st.session_state[k]


with tab_generar:
    st.subheader("Generar Plan de Cursada")

    _wizard_plan_id = st.session_state.get("wizard_plan_id")

    # ----- Paso 1: Seleccion + crear borrador -----
    if _wizard_plan_id is None:
        st.markdown("### Paso 1: Seleccionar cronograma y crear borrador")
        st.caption(
            "Solo se pueden usar cronogramas **validados y vigentes** "
            "(sin cambios desde la última validación). Al continuar, se "
            "crea un plan **borrador** (inactivo) con las comisiones y "
            "horarios derivados. En el paso siguiente lo podés editar "
            "libremente sin afectar al cronograma ni al catálogo."
        )

        sel_ciclo_w = st.selectbox(
            "Ciclo",
            options=ciclo_ids,
            key="wizard_sel_ciclo",
        )

        from src.services.cronograma_validation_service import (
            get_latest_validation,
            is_validation_stale,
        )
        from src.services.schedule_service import get_schedules_for_ciclo

        with next(get_session()) as _ws:
            _w_scheds = get_schedules_for_ciclo(_ws, sel_ciclo_w)
            _w_sched_status: dict[str, dict] = {}
            for s in _w_scheds:
                _val = get_latest_validation(_ws, s.id, sel_ciclo_w)
                _stale = (
                    is_validation_stale(_ws, _val) if _val is not None else False
                )
                if _val is None:
                    _badge, _ok = "⚪ Sin validar", False
                elif _stale:
                    _badge, _ok = "🟡 Validado pero desactualizado", False
                else:
                    _badge, _ok = "🟢 Validado y vigente", True
                _w_sched_status[s.id] = {
                    "schedule": s, "badge": _badge, "ok": _ok,
                }

        if not _w_scheds:
            st.info(
                "No hay cronogramas cargados para este ciclo. "
                "Cargá uno desde **📅 Cronogramas**."
            )
        else:
            _w_valid_ids = [
                sid for sid, s in _w_sched_status.items() if s["ok"]
            ]
            if not _w_valid_ids:
                st.warning(
                    "Ningún cronograma del ciclo está validado y vigente. "
                    "Andá a **📅 Cronogramas → ✅ Validar** para habilitar uno."
                )
                for sid, s in _w_sched_status.items():
                    st.markdown(
                        f"- {s['badge']} — **{s['schedule'].nombre}**"
                    )
            else:
                _sel_sched_w = st.selectbox(
                    "Cronograma (solo validados y vigentes)",
                    options=_w_valid_ids,
                    format_func=lambda sid: (
                        f"{_w_sched_status[sid]['badge']} — "
                        f"{_w_sched_status[sid]['schedule'].nombre}"
                    ),
                    key="wizard_sel_sched",
                )

                _no_validos = [
                    (sid, s) for sid, s in _w_sched_status.items()
                    if not s["ok"]
                ]
                if _no_validos:
                    with st.expander(
                        f"Cronogramas no disponibles ({len(_no_validos)})",
                        expanded=False,
                    ):
                        for sid, s in _no_validos:
                            st.markdown(
                                f"- {s['badge']} — **{s['schedule'].nombre}**"
                            )

                st.divider()
                st.markdown("**Datos del plan**")
                _w_nombre = st.text_input(
                    "Nombre del plan",
                    value=f"Plan {sel_ciclo_w} ({_w_sched_status[_sel_sched_w]['schedule'].nombre})",
                    key="wizard_nombre_input",
                )
                _w_descripcion = st.text_area(
                    "Descripción (opcional)",
                    value="",
                    key="wizard_descripcion_input",
                    height=80,
                )

                from src.services.forecast_service import (
                    METODOS_DISPONIBLES as _W_METODOS,
                    METODO_LABELS as _W_M_LABELS,
                )
                _w_metodo = st.selectbox(
                    "Método de forecast por defecto",
                    options=list(_W_METODOS),
                    index=0,
                    format_func=lambda m: _W_M_LABELS.get(m, m),
                    key="wizard_metodo_input",
                    help=(
                        "Se aplica a todas las materias del plan al calcular "
                        "inscriptos esperados. Editable por materia después."
                    ),
                )

                if st.button(
                    "Crear borrador y continuar →",
                    type="primary",
                    key="wizard_create_draft",
                    disabled=not _w_nombre.strip(),
                ):
                    from src.services.plan_generation_service import (
                        preview_plan_from_schedule,
                        generate_plan_from_preview,
                    )
                    with next(get_session()) as _gs:
                        _gen_preview = preview_plan_from_schedule(_gs, _sel_sched_w)
                        _result = generate_plan_from_preview(
                            _gs,
                            _sel_sched_w,
                            _w_nombre.strip(),
                            sel_ciclo_w,
                            _gen_preview.materias,
                            descripcion=_w_descripcion,
                            forecast_metodo_default=_w_metodo,
                        )
                    if _result.errors:
                        for err in _result.errors:
                            st.error(err)
                    else:
                        _new_id = _result.plan.id if _result.plan else None
                        if _new_id:
                            st.session_state["wizard_plan_id"] = _new_id
                            st.toast(
                                f"Borrador creado: {_result.comisiones_created} "
                                f"comision(es), {_result.horarios_created} horario(s)."
                            )
                            st.rerun()

    # ----- Paso 2: Edicion del plan recien creado -----
    else:
        with next(get_session()) as _es:
            _wizard_plan = _es.get(PlanificacionCursadaDB, _wizard_plan_id)
        if _wizard_plan is None:
            st.error(
                "El plan borrador ya no existe. Empezá de nuevo."
            )
            _wizard_reset()
            if st.button("Volver al inicio", key="wizard_back_to_step1"):
                st.rerun()
        else:
            _bc1, _bc2, _bc3 = st.columns([2, 2, 4])
            with _bc1:
                if st.button(
                    "🗑️ Cancelar (borra el plan)",
                    key="wizard_cancel",
                    help=(
                        "Borra el plan borrador y todas sus comisiones, "
                        "horarios y clases. No se puede deshacer."
                    ),
                ):
                    from src.services.plan_generation_service import (
                        delete_plan_cascade,
                    )
                    with next(get_session()) as _ds:
                        delete_plan_cascade(_ds, _wizard_plan_id)
                    _wizard_reset()
                    st.toast("Plan borrador eliminado.")
                    st.rerun()
            with _bc2:
                if st.button(
                    "✅ Confirmar y salir del wizard",
                    type="primary",
                    key="wizard_confirm",
                    help=(
                        "Sale del modo wizard. El plan ya está creado como "
                        "borrador. Activarlo desde Vista General cuando esté listo."
                    ),
                ):
                    # Pre-seleccionar el plan en Detalle
                    st.session_state["planes_sel_ciclo_detalle"] = _wizard_plan.ciclo_id
                    st.session_state["planes_sel_plan"] = _wizard_plan_id
                    _wizard_reset()
                    st.toast("Plan listo. Andá a 🔍 Detalle del Plan para seguir editándolo.")
                    st.rerun()
            with _bc3:
                st.markdown(
                    f"### Editando: **{_wizard_plan.nombre}** "
                    f"<span style='color:#888;font-size:0.85em'>"
                    f"(borrador inactivo)</span>",
                    unsafe_allow_html=True,
                )

            st.caption(
                "💡 Editá comisiones, horarios, tipo de clase, coeficientes "
                "y método de forecast. Los cambios afectan solo a este plan, "
                "no al cronograma ni al catálogo. Si cerrás esta pestaña sin "
                "Confirmar ni Cancelar, el plan queda como borrador en "
                "**Vista General**."
            )
            st.divider()

            # Embeber el editor del plan in-place. La lista pasada como
            # `planes_detalle` solo necesita contener este plan.
            _render_plan_editor(
                _wizard_plan_id, [_wizard_plan], key_ns="wizard",
            )



# =============================================================================
# Tab 3: Vista General
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
# Tab 3: Detalle del Plan (editable)
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
                _render_plan_editor(sel_plan_id, planes_detalle)




# =============================================================================
# Tab 4: Grilla Horaria (visual read-only timetable)
# =============================================================================
with tab_grilla:
    st.subheader("Grilla Horaria")
    st.caption("Visualizacion de horarios en formato de cronograma semanal.")

    sel_ciclo_grilla = st.selectbox(
        "Seleccionar Ciclo", options=ciclo_ids, key="planes_sel_ciclo_grilla"
    )

    if sel_ciclo_grilla:
        with next(get_session()) as session:
            planes_grilla = session.exec(
                select(PlanificacionCursadaDB)
                .where(PlanificacionCursadaDB.ciclo_id == sel_ciclo_grilla)
            ).all()

        if not planes_grilla:
            st.info("No hay planes para este ciclo.")
        else:
            plan_options_grilla = {
                p.id: f"{p.nombre} {'[ACTIVO]' if p.activo else ''}"
                for p in planes_grilla
            }
            sel_plan_grilla_id = st.selectbox(
                "Seleccionar Plan",
                options=list(plan_options_grilla.keys()),
                format_func=lambda x: plan_options_grilla[x],
                key="planes_sel_plan_grilla"
            )

            if sel_plan_grilla_id:
                # --- Filters ---
                with next(get_session()) as session:
                    grilla_pv_ids = session.exec(
                        select(CicloPlanVersionDB.plan_version_id)
                        .where(CicloPlanVersionDB.ciclo_id == sel_ciclo_grilla)
                    ).all()

                    grilla_carreras = []
                    if grilla_pv_ids:
                        grilla_carreras = session.exec(
                            select(CarreraDB)
                            .join(PlanCarreraVersionDB, CarreraDB.codigo == PlanCarreraVersionDB.carrera_codigo)
                            .where(PlanCarreraVersionDB.id.in_(grilla_pv_ids))
                            .distinct()
                        ).all()

                col_gf1, col_gf2, col_gf3 = st.columns(3)
                with col_gf1:
                    g_carrera_opts = ["Todas"] + [f"{c.codigo} - {c.nombre}" for c in grilla_carreras]
                    g_filtro_carrera = st.selectbox(
                        "Carrera", options=g_carrera_opts, key="grilla_filtro_carrera"
                    )
                with col_gf2:
                    g_filtro_anio = st.selectbox(
                        "Año", options=["Todos", 1, 2, 3, 4, 5, 6], key="grilla_filtro_anio"
                    )
                with col_gf3:
                    g_filtro_cuatri = st.selectbox(
                        "Cuatrimestre",
                        options=["Todos", "1C", "2C", "Anual"],
                        key="grilla_filtro_cuatri"
                    )

                # Determine filtered materia codigos
                g_filtered_mats = None
                if g_filtro_carrera != "Todas" or g_filtro_anio != "Todos" or g_filtro_cuatri != "Todos":
                    with next(get_session()) as session:
                        g_query = (
                            select(PlanEstudioDB.materia_codigo)
                            .where(PlanEstudioDB.plan_version_id.in_(grilla_pv_ids))
                        )
                        if g_filtro_carrera != "Todas":
                            g_carrera_cod = g_filtro_carrera.split(" - ")[0]
                            g_query = g_query.where(PlanEstudioDB.carrera_codigo == g_carrera_cod)
                        if g_filtro_anio != "Todos":
                            g_query = g_query.where(PlanEstudioDB.anio_plan == int(g_filtro_anio))
                        if g_filtro_cuatri != "Todos":
                            if g_filtro_cuatri == "Anual":
                                g_query = g_query.where(PlanEstudioDB.cuatrimestre_plan.in_(["Anual", "anual"]))
                            else:
                                g_query = g_query.where(PlanEstudioDB.cuatrimestre_plan == g_filtro_cuatri)
                        g_filtered_mats = set(session.exec(g_query.distinct()).all())

                # --- Filter: solo materias del cuatrimestre ---
                solo_cuatri = st.checkbox(
                    "Solo materias del cuatrimestre del ciclo",
                    value=False,
                    key="grilla_solo_cuatri",
                )

                st.divider()

                # --- Build grid data ---
                with next(get_session()) as session:
                    config = get_or_create_config(session)
                    grid_data = build_timetable_grid(
                        session, sel_plan_grilla_id, config, g_filtered_mats,
                        ciclo_id=sel_ciclo_grilla,
                    )

                # Apply cuatrimestre filter if checkbox is checked
                if solo_cuatri and grid_data:
                    for dia in grid_data:
                        grid_data[dia] = [b for b in grid_data[dia] if b.en_periodo is not False]

                render_timetable_calendar(grid_data, config, key="grilla_cal")


# =============================================================================
# Tab 5: Clases
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


# =============================================================================
# Tab 5: Configuración Horaria
# =============================================================================
with tab_config:
    st.subheader("Configuración Horaria")
    st.caption("Parametros globales que afectan la generacion de franjas horarias.")

    with next(get_session()) as session:
        config = get_or_create_config(session)

    with st.form("config_horaria_form"):
        col1, col2 = st.columns(2)

        with col1:
            granularidad = st.number_input(
                "Granularidad (minutos)",
                min_value=5, max_value=60, value=config.granularidad_minutos,
                step=5,
                help="Duración de cada franja horaria en minutos",
            )
            step_td = timedelta(minutes=config.granularidad_minutos)
            hora_inicio = st.time_input(
                "Hora inicio operativo",
                value=config.hora_inicio_operativo,
                step=step_td,
            )

        with col2:
            hora_fin = st.time_input(
                "Inicio última franja",
                value=config.hora_fin_operativo,
                step=step_td,
                help="Hora de inicio de la última franja horaria (ej: 23:00 para cubrir 23:00-00:00)",
            )
            # Parse dias_operativos
            dias_actuales = [d.strip() for d in config.dias_operativos.split(",") if d.strip()]
            all_dias = ["Lunes", "Martes", "Miércoles", "Jueves", "Viernes", "Sábado"]
            dias_seleccionados = st.multiselect(
                "Dias operativos",
                options=all_dias,
                default=[d for d in dias_actuales if d in all_dias],
            )

        save_config = st.form_submit_button("Guardar configuración", type="primary")

        if save_config:
            if hora_fin < hora_inicio:
                st.error("La última franja no puede ser anterior a la hora de inicio")
            elif not dias_seleccionados:
                st.error("Debe seleccionar al menos un dia operativo")
            else:
                with next(get_session()) as session:
                    new_config = ConfiguracionHoraria(
                        id=1,
                        granularidad_minutos=granularidad,
                        hora_inicio_operativo=hora_inicio,
                        hora_fin_operativo=hora_fin,
                        dias_operativos=",".join(dias_seleccionados),
                    )
                    update_config(session, new_config)
                st.success("Configuración guardada")
                st.rerun()

    # --- Preview of generated time slots ---
    st.divider()
    st.markdown("#### Preview de franjas horarias")

    with next(get_session()) as session:
        config = get_or_create_config(session)
    slots = generate_time_slots(config)

    if slots:
        slot_data = [{
            "Franja": i + 1,
            "Inicio": s.strftime("%H:%M"),
            "Fin": e.strftime("%H:%M"),
        } for i, (s, e) in enumerate(slots)]
        st.dataframe(slot_data, use_container_width=True, hide_index=True)
        st.caption(f"{len(slots)} franjas de {config.granularidad_minutos} minutos")
    else:
        st.warning("No se generaron franjas. Verifique la configuración.")
