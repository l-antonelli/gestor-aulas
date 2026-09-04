"""Gestion independiente de cronogramas de horarios.

Permite cargar, visualizar, editar y duplicar cronogramas sin necesidad
de asociarlos a un ciclo.  Luego desde Planes se puede seleccionar
un cronograma existente para generar un plan de cursada.
"""

from datetime import time

import pandas as pd
import streamlit as st
from streamlit import column_config
from sqlmodel import select, col, func

from src.database.connection import get_session, init_db
from src.database.models import (
    ScheduleDB, ScheduleEntryDB, MateriaDB, CicloDB, ConfiguracionHoraria,
    CarreraDB, PlanCarreraVersionDB, PlanEstudioDB,
)
from src.database.crud import ciclo_crud, get_or_create_config
from src.services.schedule_service import (
    create_schedule_standalone,
    create_empty_schedule,
    get_all_schedules,
    duplicate_schedule,
    delete_schedule,
    add_schedule_entry,
    update_schedule_entry,
    delete_schedule_entry,
    build_schedule_grid,
)
from src.services.cronograma_validation_service import (
    validar_cronograma,
    persist_validation,
    get_latest_validation,
    is_validation_stale,
    parse_details_json,
)
from src.ui.calendar_render import render_schedule_calendar, render_editable_schedule_calendar

init_db()

st.set_page_config(page_title="Cronogramas", page_icon="📅", layout="wide")
st.title("📅 Cronogramas")

# =============================================================================
# Data loading
# =============================================================================
with next(get_session()) as session:
    all_schedules = get_all_schedules(session)
    ciclos = ciclo_crud.get_all(session, limit=100)
    config = get_or_create_config(session)
    all_materias = list(session.exec(select(MateriaDB).where(MateriaDB.active == True)).all())
    all_carreras = list(session.exec(select(CarreraDB)).all())

    # Materias comunes: aparecen en 2+ carreras via PlanEstudioDB
    _shared_q = (
        select(PlanEstudioDB.materia_codigo)
        .group_by(PlanEstudioDB.materia_codigo)
        .having(func.count(PlanEstudioDB.carrera_codigo.distinct()) > 1)
    )
    materias_comunes: set[str] = set(session.exec(_shared_q).all())

ciclo_ids = [c.id for c in ciclos]
ciclos_map = {c.id: c for c in ciclos}
materias_map = {m.codigo: m.nombre for m in all_materias}
carreras_map = {c.codigo: c.nombre for c in all_carreras}



def _es_ciclo_basico(codigo: str) -> bool:
    """Determina si un codigo de materia pertenece al ciclo basico (F/FB/FI)."""
    return codigo.startswith(("F", "FB", "FI"))


def _aplicar_filtro_tipo(grid_data: dict, filtro_tipo: str, excluir_comunes: bool) -> dict:
    """Aplica filtros de tipo de materia y exclusion de comunes sobre grid_data."""
    if not grid_data:
        return grid_data

    if filtro_tipo == "Sólo del ciclo básico (F/FB)":
        grid_data = {
            dia: [b for b in blocks if _es_ciclo_basico(b.materia_codigo)]
            for dia, blocks in grid_data.items()
        }
    elif filtro_tipo == "Sólo específicas de la carrera":
        grid_data = {
            dia: [b for b in blocks if not _es_ciclo_basico(b.materia_codigo)]
            for dia, blocks in grid_data.items()
        }

    if excluir_comunes:
        grid_data = {
            dia: [b for b in blocks if b.materia_codigo not in materias_comunes]
            for dia, blocks in grid_data.items()
        }

    # Quitar dias vacios
    return {d: bs for d, bs in grid_data.items() if bs}


# =============================================================================
# Dialog: confirmar agregar entrada desde el calendario
# =============================================================================
@st.dialog("Agregar entrada")
def _dialog_confirm_add():
    pending = st.session_state.get("edit_pending_add")
    if not pending:
        st.rerun()
        return

    mat_nombre = materias_map.get(pending["materia"], pending["materia"])
    st.markdown(f"**{mat_nombre}** ({pending['materia']})")
    st.markdown(
        f"**{pending['dia']}** · "
        f"{pending['hora_inicio'].strftime('%H:%M')} - "
        f"{pending['hora_fin'].strftime('%H:%M')}"
    )

    add_comision = st.number_input(
        "Comisión (opcional, 0 = sin asignar)",
        min_value=0, max_value=20,
        value=pending.get("comision") or 0,
        key="dlg_add_comision",
    )

    col1, col2 = st.columns(2)
    with col1:
        if st.button("Confirmar", type="primary", use_container_width=True):
            _com_val = add_comision if add_comision > 0 else None
            with next(get_session()) as session:
                _com_id = None
                if _com_val:
                    from src.services.comision_service import (
                        get_or_create_comision_by_numero,
                    )
                    _com_id = get_or_create_comision_by_numero(
                        session, pending["materia"], _com_val,
                        schedule_id=pending["schedule_id"],
                    ).id
                add_schedule_entry(
                    session,
                    pending["schedule_id"],
                    pending["materia"],
                    pending["dia"],
                    pending["hora_inicio"],
                    pending["hora_fin"],
                    comision_id=_com_id,
                )
            st.session_state["_edit_processed_select"] = pending["_key"]
            st.session_state["_edit_toast"] = (
                f"{mat_nombre} agregada: {pending['dia']} "
                f"{pending['hora_inicio'].strftime('%H:%M')}-"
                f"{pending['hora_fin'].strftime('%H:%M')}"
            )
            del st.session_state["edit_pending_add"]
            st.rerun()
    with col2:
        if st.button("Cancelar", use_container_width=True):
            st.session_state["_edit_processed_select"] = pending["_key"]
            del st.session_state["edit_pending_add"]
            st.rerun()


@st.dialog("Editar entrada", width="large")
def _dialog_edit_entry():
    pending = st.session_state.get("edit_pending_click")
    if not pending:
        st.rerun()
        return

    all_mat_codes = sorted(materias_map.keys())
    dias_list = ["Lunes", "Martes", "Miércoles", "Jueves", "Viernes", "Sábado"]

    # --- Campos editables ---
    dlg_busqueda = st.text_input(
        "🔍 Buscar materia",
        key="dlg_buscar_mat",
        placeholder="Nombre o código...",
    )
    if dlg_busqueda.strip():
        _term = dlg_busqueda.strip().lower()
        dlg_mat_opts = [c for c in all_mat_codes if _term in c.lower() or _term in materias_map[c].lower()]
    else:
        dlg_mat_opts = all_mat_codes

    if not dlg_mat_opts:
        dlg_mat_opts = all_mat_codes  # fallback si no hay match

    # Mantener materia actual seleccionada si esta en la lista filtrada
    dlg_idx = dlg_mat_opts.index(pending["materia"]) if pending["materia"] in dlg_mat_opts else 0

    new_mat = st.selectbox(
        "Materia",
        options=dlg_mat_opts,
        index=dlg_idx,
        format_func=lambda x: f"{materias_map[x]} — {x}",
        key="dlg_edit_mat",
    )
    col_dia, col_ini, col_fin = st.columns(3)
    with col_dia:
        new_dia = st.selectbox(
            "Dia",
            options=dias_list,
            index=dias_list.index(pending["dia"]) if pending["dia"] in dias_list else 0,
            key="dlg_edit_dia",
        )
    with col_ini:
        new_inicio = st.time_input(
            "Inicio", value=pending["hora_inicio"], key="dlg_edit_ini",
        )
    with col_fin:
        new_fin = st.time_input(
            "Fin", value=pending["hora_fin"], key="dlg_edit_fin",
        )

    # Selector de comisión: comisiones existentes para (schedule, materia)
    # + opción "Crear nueva…" que abre un mini-form inline.
    from src.services.comision_service import (
        create_comision_for_schedule,
        list_comisiones_for_schedule_materia,
    )
    _sched_id_dlg = pending.get("schedule_id") or sel_edit_id
    with next(get_session()) as _dsess:
        _dlg_coms = list_comisiones_for_schedule_materia(
            _dsess, _sched_id_dlg, new_mat,
        )
    _dlg_com_labels: dict[str, str] = {
        c.id: f"{c.numero} · {c.nombre}" for c in _dlg_coms
    }
    _dlg_labels_by_com: dict[str, str] = {
        v: k for k, v in _dlg_com_labels.items()
    }
    _SIN = "— sin comisión —"
    _NUEVA = "➕ Crear nueva comisión…"
    _dlg_options = (
        [_SIN]
        + sorted(_dlg_com_labels.values(), key=lambda s: int(s.split(" · ")[0]))
        + [_NUEVA]
    )
    # Resolver la comisión actual del entry para preseleccionar
    _pending_current_label = _SIN
    with next(get_session()) as _dsess2:
        _entry_db = _dsess2.get(ScheduleEntryDB, pending["entry_id"])
        if _entry_db and _entry_db.comision_id and _entry_db.comision_id in _dlg_com_labels:
            _pending_current_label = _dlg_com_labels[_entry_db.comision_id]
    _default_idx = _dlg_options.index(_pending_current_label) if _pending_current_label in _dlg_options else 0
    new_com_label = st.selectbox(
        "Comisión",
        options=_dlg_options,
        index=_default_idx,
        key="dlg_edit_comision",
    )

    # Si eligió crear nueva, mostrar mini form
    if new_com_label == _NUEVA:
        st.markdown("**Datos de la nueva comisión**")
        _dlg_new_nombre = st.text_input(
            "Nombre", value=f"Comisión {len(_dlg_coms) + 1}",
            key="dlg_edit_new_com_nombre",
        )
        _dlg_new_cupo = st.number_input(
            "Cupo", min_value=1, value=30, step=1,
            key="dlg_edit_new_com_cupo",
        )
        _car_opts = ["—"] + sorted([c.codigo for c in all_carreras])
        _dlg_new_carrera = st.selectbox(
            "Restringir a una carrera (opcional)",
            options=_car_opts,
            key="dlg_edit_new_com_carrera",
            help=(
                "Sólo aplica cuando la materia es común a varias "
                "carreras. Si elegís una carrera, la comisión se "
                "dicta únicamente en las sedes de esa carrera. "
                "Dejá **—** para no aplicar ninguna restricción."
            ),
        )

    # --- Tipo de clase y Virtualidad del horario ---
    # Etiquetas visibles al usuario (rioplatense) vs. valores DB.
    _TIPO_LABEL_TO_DB = {
        "Automático": None,
        "Teórica": "teorica",
        "Laboratorio": "laboratorio",
    }
    _TIPO_DB_TO_LABEL = {v: k for k, v in _TIPO_LABEL_TO_DB.items()}
    _tipo_opts_lbl = list(_TIPO_LABEL_TO_DB.keys())
    _entry_tipo = _entry_db.tipo_clase if _entry_db else None
    _tipo_current_lbl = _TIPO_DB_TO_LABEL.get(_entry_tipo, "Automático")

    _entry_virtual = _entry_db.virtual if _entry_db else None
    _VIRT_LABEL_TO_DB = {
        "Según la materia": None,
        "Sí (virtual)": True,
        "No (presencial)": False,
    }
    _VIRT_DB_TO_LABEL = {
        None: "Según la materia",
        True: "Sí (virtual)",
        False: "No (presencial)",
    }
    _virtual_labels = list(_VIRT_LABEL_TO_DB.keys())
    _virtual_current_label = _VIRT_DB_TO_LABEL.get(
        _entry_virtual, "Según la materia",
    )

    col_tipo_dlg, col_virt_dlg = st.columns(2)
    with col_tipo_dlg:
        new_tipo = st.selectbox(
            "Tipo de clase",
            options=_tipo_opts_lbl,
            index=_tipo_opts_lbl.index(_tipo_current_lbl),
            key="dlg_edit_tipo",
            help=(
                "**Automático**: dejá que la asignación decida "
                "según las horas de teoría/laboratorio "
                "declaradas por la materia.\n"
                "**Teórica** / **Laboratorio**: forzá el tipo de "
                "este horario puntual."
            ),
        )
    with col_virt_dlg:
        new_virtual_label = st.selectbox(
            "Modalidad",
            options=_virtual_labels,
            index=_virtual_labels.index(_virtual_current_label),
            key="dlg_edit_virtual",
            help=(
                "**Según la materia**: usa la modalidad "
                "configurada en la materia (o en el dictado del "
                "ciclo si tiene una configuración específica).\n"
                "**Sí (virtual)**: forzá virtual — no se le "
                "asigna aula.\n"
                "**No (presencial)**: forzá presencial (aunque la "
                "materia esté marcada virtual)."
            ),
        )

    st.divider()

    col1, col2, col3 = st.columns(3)
    with col1:
        if st.button("Guardar", type="primary", use_container_width=True):
            cambios = {}
            if new_mat != pending["materia"]:
                cambios["codigo_materia"] = new_mat
            if new_dia != pending["dia"]:
                cambios["dia"] = new_dia
            if new_inicio != pending["hora_inicio"]:
                cambios["hora_inicio"] = new_inicio
            if new_fin != pending["hora_fin"]:
                cambios["hora_fin"] = new_fin
            # Resolver el comision_id según lo elegido en el selectbox.
            _selected_com_id: str | None
            with next(get_session()) as _guard:
                if new_com_label == _NUEVA:
                    _new_com_obj = create_comision_for_schedule(
                        _guard, _sched_id_dlg, new_mat,
                        nombre=st.session_state.get("dlg_edit_new_com_nombre", ""),
                        cupo=int(st.session_state.get("dlg_edit_new_com_cupo") or 30),
                        carrera_asignada=(
                            None
                            if st.session_state.get("dlg_edit_new_com_carrera") in (None, "—")
                            else st.session_state["dlg_edit_new_com_carrera"]
                        ),
                    )
                    _selected_com_id = _new_com_obj.id
                elif new_com_label == _SIN:
                    _selected_com_id = None
                else:
                    _selected_com_id = _dlg_labels_by_com.get(new_com_label)
            _current_com_id = _entry_db.comision_id if _entry_db else None
            if _selected_com_id != _current_com_id:
                cambios["comision_id"] = _selected_com_id
            # Tipo y virtual
            _new_tipo_val = _TIPO_LABEL_TO_DB.get(new_tipo)
            if _new_tipo_val != _entry_tipo:
                cambios["tipo_clase"] = _new_tipo_val
            _new_virtual_val = _VIRT_LABEL_TO_DB.get(new_virtual_label)
            if _new_virtual_val != _entry_virtual:
                cambios["virtual"] = _new_virtual_val
            mat_label = materias_map.get(new_mat, new_mat)
            if cambios:
                with next(get_session()) as session:
                    update_schedule_entry(session, pending["entry_id"], **cambios)
                st.session_state["_edit_toast"] = (
                    f"{mat_label} actualizada: {new_dia} "
                    f"{new_inicio.strftime('%H:%M')}-{new_fin.strftime('%H:%M')}"
                )
            else:
                st.session_state["_edit_toast"] = "Sin cambios"
            st.session_state["_edit_processed_click"] = pending["_key"]
            del st.session_state["edit_pending_click"]
            st.rerun()
    with col2:
        if st.button("Eliminar", use_container_width=True):
            mat_label = materias_map.get(pending["materia"], pending["materia"])
            with next(get_session()) as session:
                delete_schedule_entry(session, pending["entry_id"])
            st.session_state["_edit_processed_click"] = pending["_key"]
            st.session_state["_edit_toast"] = (
                f"{mat_label} eliminada ({pending['dia']} "
                f"{pending['hora_inicio'].strftime('%H:%M')}-"
                f"{pending['hora_fin'].strftime('%H:%M')})"
            )
            del st.session_state["edit_pending_click"]
            st.rerun()
    with col3:
        if st.button("Cancelar", use_container_width=True):
            st.session_state["_edit_processed_click"] = pending["_key"]
            del st.session_state["edit_pending_click"]
            st.rerun()


# =============================================================================
# Tabs
# =============================================================================
tab_lista, tab_cargar, tab_visualizar, tab_editar, tab_validar = st.tabs([
    "📋 Lista", "📤 Cargar", "👁 Visualizar", "✏️ Editar", "✅ Validar",
])


# =============================================================================
# Tab 1: Lista
# =============================================================================
with tab_lista:
    st.subheader("Cronogramas existentes")
    st.caption(
        "Cada fila muestra el estado de validación contra el "
        "último ciclo evaluado. Para validar un cronograma o "
        "revisar el detalle, abrilo en la pestaña **Validar**."
    )

    if not all_schedules:
        st.info("No hay cronogramas cargados. Usá la pestaña 'Cargar' para subir uno.")
    else:
        for s in all_schedules:
            with next(get_session()) as session:
                n_entries = session.exec(
                    select(func.count(ScheduleEntryDB.id)).where(
                        ScheduleEntryDB.schedule_id == s.id
                    )
                ).one()
                # Latest validation across any ciclo (for badge)
                _latest_val = get_latest_validation(session, s.id)
                _val_stale = (
                    is_validation_stale(session, _latest_val)
                    if _latest_val else False
                )

            # Badge de estado de validacion
            if _latest_val is None:
                _val_badge = "⚪ sin validar"
            elif _val_stale:
                _val_badge = (
                    f"🟡 validado vs {_latest_val.ciclo_id}, "
                    f"con cambios posteriores"
                )
            elif not _latest_val.particion_valid or _latest_val.n_faltantes > 0:
                _val_badge = (
                    f"🔴 con problemas vs {_latest_val.ciclo_id} "
                    f"({_latest_val.n_faltantes} materias faltantes, "
                    f"{_latest_val.particion_n_infactibles} particiones sin cupo)"
                )
            else:
                _val_badge = f"🟢 validado vs {_latest_val.ciclo_id}"

            ciclo_label = s.ciclo_id if s.ciclo_id else "sin ciclo"
            _header = (
                f"**{s.nombre}** \u2014 {n_entries} entradas \u2014 "
                f"ciclo upload: {ciclo_label} \u2014 {s.fecha_upload} \u2014 "
                f"{_val_badge}"
            )
            with st.expander(_header):
                # Nombre editable
                _new_name = st.text_input(
                    "Nombre del cronograma",
                    value=s.nombre,
                    key=f"name_edit_{s.id}",
                    help="Editar y presionar Enter para guardar.",
                )
                if _new_name != s.nombre and _new_name.strip():
                    with next(get_session()) as session:
                        _sched = session.get(ScheduleDB, s.id)
                        if _sched:
                            _sched.nombre = _new_name.strip()
                            session.add(_sched)
                            session.commit()
                    st.toast(f"Nombre actualizado a '{_new_name.strip()}'.")
                    st.rerun()

                # Mini-resumen de la ultima validacion (si existe)
                if _latest_val is not None:
                    _val_caption = (
                        f"\u00daltima validaci\u00f3n: **{_latest_val.validated_at:%Y-%m-%d %H:%M}** "
                        f"vs ciclo **{_latest_val.ciclo_id}** \u00b7 "
                        f"cubiertas {_latest_val.n_cubiertas}/{_latest_val.n_esperadas} \u00b7 "
                        f"con laboratorio: {_latest_val.n_con_lab_asignado} "
                        f"({_latest_val.n_lab_fijo} fijo, "
                        f"{_latest_val.n_lab_reserva} en reserva, "
                        f"{_latest_val.n_lab_pendiente} pendiente) \u00b7 "
                        f"partici\u00f3n: "
                        f"{'OK' if _latest_val.particion_valid else f'{_latest_val.particion_n_infactibles} sin cupo'}"
                    )
                    if _val_stale:
                        st.warning(
                            _val_caption
                            + "\n\n\u26a0\ufe0f El cronograma se modific\u00f3 "
                            "despu\u00e9s de esta validaci\u00f3n. Volv\u00e9 a validar "
                            "desde la pesta\u00f1a **Validar** para refrescar el estado."
                        )
                    else:
                        st.info(_val_caption)
                else:
                    st.caption(
                        "Este cronograma todav\u00eda no fue validado contra "
                        "ning\u00fan ciclo. Abr\u00ed la pesta\u00f1a **Validar** para hacerlo."
                    )

                # Acciones (duplicar, eliminar)
                with st.container(border=True):
                    st.markdown("**📄 Duplicar cronograma**")
                    st.caption(
                        "Crea una copia idéntica de este cronograma con "
                        "un nombre nuevo. Se copian todas las entradas."
                    )
                    new_name = st.text_input(
                        "Nombre de la copia",
                        value=f"{s.nombre} (copia)",
                        key=f"dup_name_{s.id}",
                    )
                    if st.button(
                        "Duplicar", key=f"dup_{s.id}",
                        width="stretch",
                    ):
                        with next(get_session()) as session:
                            duplicate_schedule(session, s.id, new_name)
                        st.success(f"Cronograma duplicado como '{new_name}'")
                        st.rerun()

                with st.container(border=True):
                    st.markdown("**🗑️ Eliminar cronograma**")
                    st.warning(
                        "Esta acción es irreversible. Se borran también "
                        "todas las entradas y validaciones asociadas."
                    )
                    if st.button(
                        "Eliminar", key=f"del_{s.id}", type="primary",
                        width="stretch",
                    ):
                        with next(get_session()) as session:
                            delete_schedule(session, s.id)
                        st.success("Cronograma eliminado")
                        st.rerun()


# =============================================================================
# Tab 2: Cargar
# =============================================================================
with tab_cargar:
    st.subheader("Crear nuevo cronograma")
    st.caption(
        "Un cronograma es un conjunto de horarios (día + rango + "
        "materia + comisión) que después se valida contra un ciclo. "
        "Podés armarlo desde cero o importarlo desde un archivo."
    )

    with st.container(border=True):
        st.markdown("**⚙️ Configuración básica**")
        modo_carga = st.radio(
            "¿Cómo lo querés crear?",
            options=["Crear vacío", "Cargar desde archivo"],
            horizontal=True,
            key="crono_modo",
            help=(
                "**Crear vacío**: arranca sin entradas, las cargás a "
                "mano desde la pestaña Editar.\n"
                "**Cargar desde archivo**: importa un CSV/Excel con "
                "los horarios ya armados."
            ),
        )

        nombre = st.text_input(
            "Nombre del cronograma",
            key="crono_nombre",
            placeholder="Ej: Cronograma 2026 - 1C",
        )

        ciclo_sel = st.selectbox(
            "Ciclo asociado (opcional)",
            options=["(ninguno)"] + ciclo_ids,
            key="crono_ciclo",
            help=(
                "Ciclo académico con el que se cargó originalmente "
                "este cronograma. Es solo una referencia — la "
                "validación se hace después contra el ciclo que elijas."
            ),
        )
    ciclo_id_val = ciclo_sel if ciclo_sel != "(ninguno)" else None

    if modo_carga == "Cargar desde archivo":
        with st.container(border=True):
            st.markdown("**📤 Archivo de importación**")
            st.caption(
                "El archivo debe tener las columnas mínimas: materia, "
                "día, hora inicio, hora fin. Comisión y tipo son opcionales."
            )
            uploaded = st.file_uploader(
                "Archivo CSV o Excel con horarios",
                type=["csv", "xlsx", "xls"],
                key="crono_upload",
            )

            if st.button(
                "Crear cronograma",
                disabled=not nombre or not uploaded,
                type="primary",
                width="stretch",
            ):
                with next(get_session()) as session:
                    result = create_schedule_standalone(
                        session, nombre, uploaded, ciclo_id=ciclo_id_val
                    )
                if result.errors:
                    for e in result.errors:
                        st.error(e)
                if result.warnings:
                    for w in result.warnings:
                        st.warning(w)
                if result.schedule:
                    st.success(
                        f"Cronograma '{result.schedule.nombre}' creado con "
                        f"{result.entries_created} entradas."
                    )
                    st.rerun()
    else:
        st.info(
            "Se va a crear un cronograma sin entradas. Después "
            "podés cargar los horarios desde la pestaña **Editar**."
        )
        if st.button(
            "Crear cronograma vacío",
            disabled=not nombre,
            type="primary",
            width="stretch",
        ):
            with next(get_session()) as session:
                try:
                    schedule = create_empty_schedule(
                        session, nombre, ciclo_id=ciclo_id_val
                    )
                    st.success(
                        f"Cronograma '{schedule.nombre}' creado. "
                        f"Andá a la pestaña **Editar** para agregar entradas."
                    )
                    st.rerun()
                except ValueError as e:
                    st.error(str(e))


# =============================================================================
# Tab 3: Visualizar
# =============================================================================
with tab_visualizar:
    st.subheader("Visualizar cronograma")
    st.caption(
        "Mirá los horarios cargados sin editarlos. Podés filtrar "
        "por carrera/año/cuatri, o enfocarte en una sola materia."
    )

    if not all_schedules:
        st.info("No hay cronogramas para visualizar.")
    else:
        schedule_options = {s.id: f"{s.nombre} ({s.fecha_upload})" for s in all_schedules}
        sel_id = st.selectbox(
            "Cronograma",
            options=list(schedule_options.keys()),
            format_func=lambda x: schedule_options[x],
            key="viz_schedule",
        )

        if sel_id:
            viz_modo = st.radio(
                "Modo de visualización",
                options=["Por grupo", "Por materia"],
                horizontal=True,
                key="viz_modo",
                help=(
                    "**Por grupo**: filtra por carrera + año + "
                    "cuatrimestre. Ideal para armar la vista de "
                    "un grupo puntual (por ejemplo, Electrónica 3er año 1C).\n"
                    "**Por materia**: te enfoca en una sola materia. "
                    "Útil para materias que se dictan en varias carreras."
                ),
            )

            # =================================================================
            # Mode: Por materia
            # =================================================================
            if viz_modo == "Por materia":
                _vm_busqueda = st.text_input(
                    "🔍 Buscar materia por nombre o código",
                    key="viz_sm_buscar",
                    placeholder="Ej: fisica III, FB10, algebra...",
                )
                _vm_all = sorted(materias_map.keys())
                if _vm_busqueda.strip():
                    _vm_term = _vm_busqueda.strip().lower()
                    _vm_opts = [
                        c for c in _vm_all
                        if _vm_term in c.lower()
                        or _vm_term in materias_map[c].lower()
                    ]
                else:
                    _vm_opts = _vm_all
                if not _vm_opts:
                    _vm_opts = _vm_all

                _vm_sel = st.selectbox(
                    "Materia",
                    options=_vm_opts,
                    index=None,
                    format_func=lambda x: f"{materias_map.get(x, x)} — {x}",
                    placeholder="Seleccioná una materia...",
                    key="viz_sm_materia",
                )

                if _vm_sel:
                    with next(get_session()) as session:
                        _vm_grid = build_schedule_grid(session, sel_id)

                    _vm_grid = {
                        dia: [b for b in blocks if b.materia_codigo == _vm_sel]
                        for dia, blocks in _vm_grid.items()
                    }
                    _vm_grid = {d: bs for d, bs in _vm_grid.items() if bs}

                    _vm_n = sum(len(bs) for bs in _vm_grid.values())
                    if _vm_n > 0:
                        st.caption(
                            f"{_vm_n} entrada(s) para "
                            f"**{materias_map.get(_vm_sel, _vm_sel)}**."
                        )
                    else:
                        st.info(
                            f"No hay entradas para "
                            f"**{materias_map.get(_vm_sel, _vm_sel)}** "
                            f"en este cronograma."
                        )

                    st.divider()

                    if _vm_grid:
                        render_schedule_calendar(
                            _vm_grid, config,
                            key=f"viz_cal_mat_{_vm_n}",
                            color_by_comision=True,
                        )
                else:
                    st.caption(
                        "Seleccioná una materia para ver sus horarios "
                        "en el cronograma."
                    )

            # =================================================================
            # Mode: Por grupo (carrera/año/cuatri)
            # =================================================================
            else:
                with st.container(border=True):
                    st.markdown("**🔎 Filtros del grupo**")
                    st.caption(
                        "Elegí la carrera, el año y el cuatrimestre "
                        "para acotar las materias que se muestran."
                    )
                    # --- Filtros fila 1: carrera, año, cuatrimestre ---
                    col_f1, col_f2, col_f3 = st.columns(3)
                    with col_f1:
                        carrera_opts = [
                            f"{c.codigo} - {c.nombre}" for c in all_carreras
                        ]
                        viz_filtro_carrera = st.selectbox(
                            "Carrera", options=carrera_opts,
                            index=None, placeholder="Elegí una carrera...",
                            key="viz_filtro_carrera",
                        )
                    with col_f2:
                        viz_filtro_anio = st.selectbox(
                            "Año de cursada",
                            options=[1, 2, 3, 4, 5, 6],
                            index=None, placeholder="Elegí un año...",
                            key="viz_filtro_anio",
                        )
                    with col_f3:
                        viz_filtro_cuatri = st.selectbox(
                            "Cuatrimestre",
                            options=["1C", "2C", "Anual"],
                            index=None, placeholder="Elegí un cuatri...",
                            key="viz_filtro_cuatri",
                        )

                    # --- Filtros fila 2: alcance ---
                    col_f4, col_f5 = st.columns(2)
                    with col_f4:
                        viz_filtro_tipo = st.selectbox(
                            "Alcance de las materias",
                            options=[
                                "Todas",
                                "Sólo del ciclo básico (F/FB)",
                                "Sólo específicas de la carrera",
                            ],
                            key="viz_filtro_tipo",
                            help=(
                                "Filtra por el segmento del plan de "
                                "estudio.\n"
                                "**Todas**: no filtra por segmento.\n"
                                "**Ciclo básico**: sólo materias cuyo "
                                "código empieza con F o FB.\n"
                                "**Específicas**: excluye el ciclo básico."
                            ),
                        )
                    with col_f5:
                        viz_excluir_comunes = st.checkbox(
                            "Ocultar materias compartidas con otras carreras",
                            key="viz_excluir_comunes",
                            help=(
                                "Si tildás, se ocultan las materias "
                                "que aparecen en el plan de estudio "
                                "de más de una carrera (útil para "
                                "ver sólo las propias de la carrera "
                                "elegida)."
                            ),
                        )

                _viz_all_filters_set = (
                    viz_filtro_carrera is not None
                    and viz_filtro_anio is not None
                    and viz_filtro_cuatri is not None
                )

                # Determinar materias filtradas via PlanEstudioDB
                viz_filtered_mats: set[str] | None = None
                if _viz_all_filters_set:
                    with next(get_session()) as session:
                        q = select(PlanEstudioDB.materia_codigo)
                        carrera_cod = viz_filtro_carrera.split(" - ")[0]
                        q = q.where(PlanEstudioDB.carrera_codigo == carrera_cod)
                        q = q.where(PlanEstudioDB.anio_plan == int(viz_filtro_anio))
                        if viz_filtro_cuatri == "Anual":
                            q = q.where(PlanEstudioDB.cuatrimestre_plan.in_(["Anual", "anual"]))
                        else:
                            q = q.where(PlanEstudioDB.cuatrimestre_plan == viz_filtro_cuatri)
                        viz_filtered_mats = set(session.exec(q.distinct()).all())

                if not _viz_all_filters_set:
                    st.caption(
                        "Seleccioná Carrera, Año y Cuatrimestre para ver "
                        "las materias del cronograma."
                    )
                else:
                    # --- Multiselect de materias ---
                    with next(get_session()) as session:
                        grid_data = build_schedule_grid(session, sel_id)

                    # Materias presentes en el cronograma
                    _viz_mats_en_schedule = set()
                    for _blocks in grid_data.values():
                        for _b in _blocks:
                            _viz_mats_en_schedule.add(_b.materia_codigo)

                    # Intersectar con filtros de plan
                    _viz_mats_disponibles = _viz_mats_en_schedule
                    if viz_filtered_mats is not None:
                        _viz_mats_disponibles = _viz_mats_en_schedule & viz_filtered_mats

                    _viz_mat_list = sorted(_viz_mats_disponibles, key=lambda c: materias_map.get(c, c))
                    viz_materias_sel = st.multiselect(
                        "Materias a mostrar",
                        options=_viz_mat_list,
                        default=_viz_mat_list,
                        format_func=lambda x: f"{materias_map.get(x, x)} — {x}",
                        key="viz_filtro_materias",
                    )
                    _viz_selected_set = set(viz_materias_sel) if viz_materias_sel else _viz_mats_disponibles

                    st.divider()

                    # Aplicar filtro de materias seleccionadas
                    if grid_data:
                        grid_data = {
                            dia: [b for b in blocks if b.materia_codigo in _viz_selected_set]
                            for dia, blocks in grid_data.items()
                        }
                        grid_data = {d: bs for d, bs in grid_data.items() if bs}

                    # Aplicar filtros de tipo y comunes
                    grid_data = _aplicar_filtro_tipo(grid_data, viz_filtro_tipo, viz_excluir_comunes)

                    render_schedule_calendar(grid_data, config, key="viz_cal")


# =============================================================================
# Tab 4: Editar
# =============================================================================
with tab_editar:
    # Mostrar toast pendiente de accion anterior
    if "_edit_toast" in st.session_state:
        st.toast(st.session_state.pop("_edit_toast"))

    st.subheader("Editar entradas del cronograma")
    st.caption(
        "🖱️ **Arrastrá** un bloque para cambiar el día o la hora. "
        "Redimensionalo tirando del borde para ajustar la "
        "duración. **Presioná** un bloque para editarlo o "
        "eliminarlo. Para sumar una entrada nueva, arrastrá "
        "sobre un espacio vacío del cronograma."
    )

    if not all_schedules:
        st.info("No hay cronogramas para editar.")
    else:
        schedule_options_edit = {
            s.id: f"{s.nombre} ({s.fecha_upload})" for s in all_schedules
        }
        # Consumir buffer de pre-seleccion (viene de Validacion → Editar).
        # Setear `edit_schedule` ANTES de instanciar el widget.
        _pending = st.session_state.pop("_pending_edit_schedule_id", None)
        if _pending and _pending in schedule_options_edit:
            st.session_state["edit_schedule"] = _pending
        sel_edit_id = st.selectbox(
            "Seleccionar cronograma",
            options=list(schedule_options_edit.keys()),
            format_func=lambda x: schedule_options_edit[x],
            key="edit_schedule",
        )

        if sel_edit_id:
            edit_modo = st.radio(
                "Modo de edición",
                options=["Por grupo", "Por materia"],
                horizontal=True,
                key="edit_modo",
                help=(
                    "'Por grupo' filtra por carrera/año/cuatrimestre. "
                    "'Por materia' permite enfocarse en una sola materia "
                    "(útil para materias compartidas entre carreras)."
                ),
            )

            action = None
            sel_mat_add = None

            # =================================================================
            # Mode: Por materia
            # =================================================================
            if edit_modo == "Por materia":
                _sm_busqueda = st.text_input(
                    "🔍 Buscar materia por nombre o código",
                    key="edit_sm_buscar",
                    placeholder="Ej: fisica III, FB10, algebra...",
                )
                _sm_all = sorted(materias_map.keys())
                if _sm_busqueda.strip():
                    _sm_term = _sm_busqueda.strip().lower()
                    _sm_opts = [
                        c for c in _sm_all
                        if _sm_term in c.lower()
                        or _sm_term in materias_map[c].lower()
                    ]
                else:
                    _sm_opts = _sm_all
                if not _sm_opts:
                    _sm_opts = _sm_all

                _sm_sel = st.selectbox(
                    "Materia",
                    options=_sm_opts,
                    index=None,
                    format_func=lambda x: f"{materias_map.get(x, x)} — {x}",
                    placeholder="Seleccioná una materia...",
                    key="edit_sm_materia",
                )

                if _sm_sel:
                    sel_mat_add = _sm_sel

                    with next(get_session()) as session:
                        _sm_grid = build_schedule_grid(session, sel_edit_id)

                    # Filter to only selected materia
                    _sm_grid = {
                        dia: [b for b in blocks if b.materia_codigo == _sm_sel]
                        for dia, blocks in _sm_grid.items()
                    }
                    _sm_grid = {d: bs for d, bs in _sm_grid.items() if bs}

                    _sm_n = sum(len(bs) for bs in _sm_grid.values())
                    if _sm_n > 0:
                        st.caption(
                            f"{_sm_n} entrada(s) para "
                            f"**{materias_map.get(_sm_sel, _sm_sel)}**. "
                            f"Seleccioná un rango vacío en la grilla para agregar."
                        )
                    else:
                        st.info(
                            f"No hay entradas para "
                            f"**{materias_map.get(_sm_sel, _sm_sel)}**. "
                            f"Seleccioná un rango en la grilla para agregar la primera."
                        )

                    st.divider()

                    action = render_editable_schedule_calendar(
                        _sm_grid, config,
                        key=f"edit_cal_{_sm_n}",
                        allow_empty=True,
                        color_by_comision=True,
                    )

                    # --- Tabla editable de entradas ---
                    st.divider()
                    st.markdown("##### Entradas y comisiones")

                    from src.services.comision_service import (
                        create_comision_for_schedule,
                        delete_comision,
                        get_or_create_comision_by_numero,
                        list_comisiones_for_schedule_materia,
                        update_comision,
                    )
                    from src.database.models import ComisionDB

                    with next(get_session()) as session:
                        _sm_entries = list(session.exec(
                            select(ScheduleEntryDB)
                            .where(ScheduleEntryDB.schedule_id == sel_edit_id)
                            .where(ScheduleEntryDB.codigo_materia == _sm_sel)
                            .order_by(ScheduleEntryDB.dia, ScheduleEntryDB.hora_inicio)
                        ).all())
                        # Comisiones template de la materia en este cronograma
                        _sm_comisiones = list_comisiones_for_schedule_materia(
                            session, sel_edit_id, _sm_sel,
                        )

                    _dias_orden = ["Lunes", "Martes", "Miércoles", "Jueves", "Viernes", "Sábado"]

                    # Mapa {id: ComisionDB} para resolver rápido en el render.
                    _com_by_id: dict[str, ComisionDB] = {
                        c.id: c for c in _sm_comisiones
                    }
                    # Labels display -> id para el selectbox de la tabla.
                    # Formato: "N · nombre" ordenado por numero.
                    _com_label_by_id: dict[str, str] = {
                        c.id: f"{c.numero} · {c.nombre}" for c in _sm_comisiones
                    }
                    _com_id_by_label: dict[str, str] = {
                        lbl: cid for cid, lbl in _com_label_by_id.items()
                    }
                    _CREAR_NUEVA_LABEL = "➕ Crear nueva comisión…"
                    _SIN_ASIGNAR_LABEL = "— sin comisión —"
                    _sm_com_selectbox_options = (
                        [_SIN_ASIGNAR_LABEL]
                        + sorted(_com_label_by_id.values(), key=lambda s: int(s.split(" · ")[0]))
                        + [_CREAR_NUEVA_LABEL]
                    )

                    def _virtual_to_label(v: bool | None) -> str:
                        """Optional[bool] → label del selectbox."""
                        if v is None:
                            return "Heredar"
                        return "Sí" if v else "No"

                    def _label_to_virtual(lbl: str) -> bool | None:
                        if lbl == "Sí":
                            return True
                        if lbl == "No":
                            return False
                        return None

                    def _com_id_to_label(cid: str | None) -> str:
                        if cid is None:
                            return _SIN_ASIGNAR_LABEL
                        return _com_label_by_id.get(cid, _SIN_ASIGNAR_LABEL)

                    def _label_to_com_id(lbl: str) -> str | None:
                        if lbl in (_SIN_ASIGNAR_LABEL, _CREAR_NUEVA_LABEL, "", None):
                            return None
                        return _com_id_by_label.get(lbl)

                    _sm_df = pd.DataFrame([
                        {
                            "entry_id": e.id,
                            "Día": e.dia,
                            "Inicio": e.hora_inicio,
                            "Fin": e.hora_fin,
                            "Comisión": _com_id_to_label(e.comision_id),
                            "Tipo": e.tipo_clase or "sin determinar",
                            "Virtual": _virtual_to_label(e.virtual),
                        }
                        for e in _sm_entries
                    ]) if _sm_entries else pd.DataFrame(
                        columns=[
                            "entry_id", "Día", "Inicio", "Fin",
                            "Comisión", "Tipo", "Virtual",
                        ]
                    )

                    _sm_de_key = f"sm_de_{sel_edit_id}_{_sm_sel}_{len(_sm_entries)}"

                    def _coerce_time(val) -> time:
                        """Convierte string HH:MM:SS.mmm o time a time."""
                        if isinstance(val, time):
                            return val
                        s = str(val).split(".")[0]  # strip millis
                        parts = s.split(":")
                        return time(int(parts[0]), int(parts[1]),
                                    int(parts[2]) if len(parts) > 2 else 0)

                    def _sm_on_change():
                        """Autoguardar cambios del data_editor.

                        Nuevo flujo con ComisionDB entidad real:
                        - Columna "Comisión" es un label textual;
                          mapear a comision_id via _label_to_com_id.
                        - Si el usuario elige "➕ Crear nueva comisión…",
                          se levanta un flag en session_state y el
                          proximo rerun abre un dialog para el form.
                          Mientras tanto la fila queda sin cambiar.
                        """
                        edited = st.session_state.get(_sm_de_key)
                        if not edited:
                            return
                        _saved = 0
                        _deleted = 0
                        _created = 0
                        _requested_new = None  # (entry_id | None, added_row_idx | None)
                        with next(get_session()) as sess:
                            # Edited rows
                            for idx_str, changes in (
                                edited.get("edited_rows") or {}
                            ).items():
                                idx = int(idx_str)
                                if idx < len(_sm_entries):
                                    _e = _sm_entries[idx]
                                    _cambios = {}
                                    if "Día" in changes:
                                        _cambios["dia"] = changes["Día"]
                                    if "Inicio" in changes:
                                        _cambios["hora_inicio"] = _coerce_time(changes["Inicio"])
                                    if "Fin" in changes:
                                        _cambios["hora_fin"] = _coerce_time(changes["Fin"])
                                    if "Comisión" in changes:
                                        _new_lbl = changes["Comisión"]
                                        if _new_lbl == _CREAR_NUEVA_LABEL:
                                            _requested_new = ("existing", _e.id)
                                            continue
                                        _cambios["comision_id"] = _label_to_com_id(_new_lbl)
                                    if "Tipo" in changes:
                                        _tv = changes["Tipo"]
                                        _cambios["tipo_clase"] = None if _tv == "sin determinar" else _tv
                                    if "Virtual" in changes:
                                        _cambios["virtual"] = _label_to_virtual(
                                            changes["Virtual"]
                                        )
                                    if _cambios:
                                        update_schedule_entry(
                                            sess, _e.id, **_cambios,
                                        )
                                        _saved += 1
                            # Deleted rows
                            for idx in edited.get("deleted_rows") or []:
                                if idx < len(_sm_entries):
                                    delete_schedule_entry(
                                        sess, _sm_entries[idx].id,
                                    )
                                    _deleted += 1
                            # Added rows
                            for row_idx, row in enumerate(edited.get("added_rows") or []):
                                if row.get("Día") and row.get("Inicio") and row.get("Fin"):
                                    _lbl = row.get("Comisión") or _SIN_ASIGNAR_LABEL
                                    if _lbl == _CREAR_NUEVA_LABEL:
                                        _requested_new = ("new_row", row_idx)
                                        continue
                                    _com_id = _label_to_com_id(_lbl)
                                    _tipo_raw = row.get("Tipo")
                                    _tipo = None if (not _tipo_raw or _tipo_raw == "sin determinar") else _tipo_raw
                                    _virtual_val = _label_to_virtual(
                                        row.get("Virtual") or "Heredar"
                                    )
                                    add_schedule_entry(
                                        sess,
                                        sel_edit_id,
                                        _sm_sel,
                                        row["Día"],
                                        _coerce_time(row["Inicio"]),
                                        _coerce_time(row["Fin"]),
                                        comision_id=_com_id,
                                        tipo_clase=_tipo,
                                        virtual=_virtual_val,
                                    )
                                    _created += 1
                        if _requested_new is not None:
                            st.session_state["_sm_new_com_request"] = _requested_new
                        _parts = []
                        if _saved:
                            _parts.append(f"{_saved} modificada(s)")
                        if _created:
                            _parts.append(f"{_created} agregada(s)")
                        if _deleted:
                            _parts.append(f"{_deleted} eliminada(s)")
                        if _parts:
                            st.session_state["_edit_toast"] = (
                                ", ".join(_parts).capitalize()
                            )

                    st.data_editor(
                        _sm_df,
                        column_config={
                            "entry_id": None,
                            "Día": column_config.SelectboxColumn(
                                options=_dias_orden, width="small",
                            ),
                            "Inicio": column_config.TimeColumn(
                                format="HH:mm", width="small",
                            ),
                            "Fin": column_config.TimeColumn(
                                format="HH:mm", width="small",
                            ),
                            "Comisión": column_config.SelectboxColumn(
                                options=_sm_com_selectbox_options,
                                default=_SIN_ASIGNAR_LABEL,
                                help=(
                                    "Comisión a la que pertenece este horario. "
                                    "Elegí una existente, dejala sin asignar "
                                    "o creá una nueva desde la última opción."
                                ),
                                width="medium",
                            ),
                            "Tipo": column_config.SelectboxColumn(
                                options=["sin determinar", "teorica", "laboratorio"],
                                default="sin determinar",
                                help=(
                                    "Tipo de clase. "
                                    "**sin determinar**: lo decide la "
                                    "asignación automática según las "
                                    "horas de la materia. "
                                    "**teoria** o **laboratorio**: "
                                    "forzá el tipo para este horario."
                                ),
                                width="small",
                            ),
                            "Virtual": column_config.SelectboxColumn(
                                options=["Heredar", "Sí", "No"],
                                default="Heredar",
                                help=(
                                    "Modalidad de este horario. "
                                    "**Heredar**: usa lo configurado "
                                    "en la materia o el dictado. "
                                    "**Sí**: forzá virtual (no se "
                                    "asigna aula). **No**: forzá "
                                    "presencial."
                                ),
                                width="small",
                            ),
                        },
                        num_rows="dynamic",
                        use_container_width=True,
                        hide_index=True,
                        on_change=_sm_on_change,
                        key=_sm_de_key,
                    )

                    # --- Dialog para crear comisión nueva al vuelo ---
                    _req = st.session_state.get("_sm_new_com_request")
                    if _req is not None:
                        _req_kind, _req_ref = _req
                        with st.container(border=True):
                            st.markdown("**Crear nueva comisión**")
                            _new_nombre = st.text_input(
                                "Nombre", value=f"Comisión {len(_sm_comisiones) + 1}",
                                key="_sm_new_com_nombre",
                            )
                            _new_cupo = st.number_input(
                                "Cupo", min_value=1, value=30, step=1,
                                key="_sm_new_com_cupo",
                            )
                            _car_opts = ["—"] + sorted([c.codigo for c in all_carreras])
                            _new_carrera = st.selectbox(
                                "Restringir a una carrera (opcional)",
                                options=_car_opts,
                                key="_sm_new_com_carrera",
                                help=(
                                    "Sólo aplica si la materia es "
                                    "común a varias carreras y esta "
                                    "comisión se organiza para "
                                    "alumnos de una carrera en "
                                    "particular. Dejá **—** para no "
                                    "aplicar ninguna restricción."
                                ),
                            )
                            _new_desc = st.text_area(
                                "Descripción (opcional)", value="",
                                key="_sm_new_com_desc",
                            )
                            _c1, _c2 = st.columns(2)
                            with _c1:
                                if st.button("Crear y asignar", type="primary", use_container_width=True):
                                    with next(get_session()) as _cses:
                                        _new_com = create_comision_for_schedule(
                                            _cses, sel_edit_id, _sm_sel,
                                            nombre=_new_nombre,
                                            cupo=int(_new_cupo),
                                            descripcion=_new_desc,
                                            carrera_asignada=(
                                                None if _new_carrera == "—" else _new_carrera
                                            ),
                                        )
                                        if _req_kind == "existing":
                                            update_schedule_entry(
                                                _cses, _req_ref,
                                                comision_id=_new_com.id,
                                            )
                                    st.session_state.pop("_sm_new_com_request", None)
                                    for _k in ("_sm_new_com_nombre",
                                               "_sm_new_com_cupo",
                                               "_sm_new_com_carrera",
                                               "_sm_new_com_desc"):
                                        st.session_state.pop(_k, None)
                                    st.rerun()
                            with _c2:
                                if st.button("Cancelar", use_container_width=True):
                                    st.session_state.pop("_sm_new_com_request", None)
                                    st.rerun()

                    # --- Tabla de comisiones (editable): cupo, carrera, ... ---
                    st.markdown("##### Comisiones de esta materia")
                    if _sm_comisiones:
                        _carr_opts_full = ["—"] + sorted([c.codigo for c in all_carreras])
                        _com_df = pd.DataFrame([
                            {
                                "comision_id": c.id,
                                "N°": c.numero,
                                "Nombre": c.nombre,
                                "Cupo": c.cupo,
                                "Carrera asignada": c.carrera_asignada or "—",
                                "Descripción": c.descripcion or "",
                            }
                            for c in sorted(_sm_comisiones, key=lambda c: c.numero)
                        ])
                        _com_de_key = f"com_de_{sel_edit_id}_{_sm_sel}_{len(_sm_comisiones)}"

                        def _com_on_change():
                            edited = st.session_state.get(_com_de_key)
                            if not edited:
                                return
                            _com_saved = 0
                            _com_deleted = 0
                            _com_bloqueadas: list[str] = []
                            with next(get_session()) as sess:
                                for idx_str, changes in (edited.get("edited_rows") or {}).items():
                                    idx = int(idx_str)
                                    if idx >= len(_com_df):
                                        continue
                                    cid = str(_com_df.iloc[idx]["comision_id"])
                                    _cambios: dict = {}
                                    if "N°" in changes:
                                        _cambios["numero"] = int(changes["N°"])
                                    if "Nombre" in changes:
                                        _cambios["nombre"] = str(changes["Nombre"])
                                    if "Cupo" in changes:
                                        _new_cupo_val = int(changes["Cupo"])
                                        if _new_cupo_val >= 1:
                                            _cambios["cupo"] = _new_cupo_val
                                    if "Carrera asignada" in changes:
                                        _val = changes["Carrera asignada"]
                                        _cambios["carrera_asignada"] = (
                                            None if _val == "—" else _val
                                        )
                                    if "Descripción" in changes:
                                        _cambios["descripcion"] = str(changes["Descripción"])
                                    if _cambios:
                                        update_comision(sess, cid, **_cambios)
                                        _com_saved += 1
                                for idx in edited.get("deleted_rows") or []:
                                    if idx < len(_com_df):
                                        cid = str(_com_df.iloc[idx]["comision_id"])
                                        _res = delete_comision(sess, cid)
                                        if _res.ok:
                                            _com_deleted += 1
                                        else:
                                            _com_bloqueadas.extend(_res.errores)
                            if _com_bloqueadas:
                                st.session_state["_com_del_warn"] = "\n\n".join(_com_bloqueadas)
                            if _com_saved or _com_deleted:
                                _p = []
                                if _com_saved:
                                    _p.append(f"{_com_saved} comisión(es) actualizada(s)")
                                if _com_deleted:
                                    _p.append(f"{_com_deleted} borrada(s)")
                                st.session_state["_edit_toast"] = ", ".join(_p).capitalize()

                        st.data_editor(
                            _com_df,
                            column_config={
                                "comision_id": None,
                                "N°": column_config.NumberColumn(
                                    "N°", min_value=1, step=1, width="small",
                                ),
                                "Nombre": column_config.TextColumn(width="medium"),
                                "Cupo": column_config.NumberColumn(
                                    # min_value=0 para tolerar valores
                                    # legacy con cupo=0 (materia sin
                                    # cupo). Se filtran en save.
                                    min_value=0, step=1, width="small",
                                    help="Debe ser ≥ 1 para persistirse.",
                                ),
                                "Carrera asignada": column_config.SelectboxColumn(
                                    options=_carr_opts_full,
                                    default="—",
                                    help=(
                                        "Si tiene valor, la asignación "
                                        "automática restringe la sede "
                                        "del aula a las sedes de esa "
                                        "carrera (comisión orientada a "
                                        "una carrera en particular). "
                                        "— = sin restricción."
                                    ),
                                    width="medium",
                                ),
                                "Descripción": column_config.TextColumn(width="large"),
                            },
                            hide_index=True,
                            num_rows="dynamic",
                            on_change=_com_on_change,
                            key=_com_de_key,
                            use_container_width=True,
                        )
                        if st.session_state.get("_com_del_warn"):
                            st.warning(st.session_state.pop("_com_del_warn"))
                    else:
                        st.caption(
                            "Todavía no hay comisiones creadas para esta materia. "
                            "Se van a crear automáticamente al asignar una comisión "
                            "en la tabla de entries de arriba."
                        )

                    # --- Resumen por comisión ---
                    if _sm_entries:
                        _sm_summary_rows = []
                        # Los "cn" ahora son los numeros existentes en las
                        # comisiones + los entries sin comisión.
                        _nums_presentes = sorted({c.numero for c in _sm_comisiones})
                        _sin_entries = [e for e in _sm_entries if not e.comision_id]
                        for _cn in _nums_presentes:
                            # Encuentro las comisiones con este numero (deberia ser una)
                            _coms_num = [c for c in _sm_comisiones if c.numero == _cn]
                            if not _coms_num:
                                continue
                            _cid = _coms_num[0].id
                            _cn_entries = [
                                e for e in _sm_entries if e.comision_id == _cid
                            ]
                            _horarios = []
                            for _e in _cn_entries:
                                _hi = _e.hora_inicio.strftime("%H:%M")
                                _hf = _e.hora_fin.strftime("%H:%M")
                                _horarios.append(f"{_e.dia[:3]} {_hi}-{_hf}")
                            _sm_summary_rows.append({
                                "Comisión": _cn,
                                "Clases": len(_cn_entries),
                                "Horarios": ", ".join(_horarios) if _horarios else "—",
                            })
                        if _sin_entries:
                            _horarios_sin = []
                            for _e in _sin_entries:
                                _hi = _e.hora_inicio.strftime("%H:%M")
                                _hf = _e.hora_fin.strftime("%H:%M")
                                _horarios_sin.append(f"{_e.dia[:3]} {_hi}-{_hf}")
                            _sm_summary_rows.append({
                                "Comisión": "Sin asignar",
                                "Clases": len(_sin_entries),
                                "Horarios": ", ".join(_horarios_sin) if _horarios_sin else "—",
                            })
                        if _sm_summary_rows:
                            st.caption("Resumen por comisión")
                            st.dataframe(
                                pd.DataFrame(_sm_summary_rows),
                                use_container_width=True,
                                hide_index=True,
                            )

                else:
                    st.caption(
                        "Seleccioná una materia para ver y editar "
                        "sus horarios en el cronograma."
                    )

            # =================================================================
            # Mode: Por grupo (carrera/año/cuatri)
            # =================================================================
            else:
                with st.container(border=True):
                    st.markdown("**🔎 Filtros del grupo a editar**")
                    st.caption(
                        "Elegí Carrera + Año + Cuatrimestre para "
                        "acotar las materias que se muestran en el "
                        "cronograma editable."
                    )
                    col_ef1, col_ef2, col_ef3 = st.columns(3)
                    with col_ef1:
                        edit_carrera_opts = [
                            f"{c.codigo} - {c.nombre}" for c in all_carreras
                        ]
                        edit_filtro_carrera = st.selectbox(
                            "Carrera", options=edit_carrera_opts,
                            index=None, placeholder="Elegí una carrera...",
                            key="edit_filtro_carrera",
                        )
                    with col_ef2:
                        edit_filtro_anio = st.selectbox(
                            "Año de cursada",
                            options=[1, 2, 3, 4, 5, 6],
                            index=None, placeholder="Elegí un año...",
                            key="edit_filtro_anio",
                        )
                    with col_ef3:
                        edit_filtro_cuatri = st.selectbox(
                            "Cuatrimestre",
                            options=["1C", "2C", "Anual"],
                            index=None, placeholder="Elegí un cuatri...",
                            key="edit_filtro_cuatri",
                        )

                    col_ef4, col_ef5 = st.columns(2)
                    with col_ef4:
                        edit_filtro_tipo = st.selectbox(
                            "Alcance de las materias",
                            options=[
                                "Todas",
                                "Sólo del ciclo básico (F/FB)",
                                "Sólo específicas de la carrera",
                            ],
                            key="edit_filtro_tipo",
                            help=(
                                "**Todas**: no filtra por segmento.\n"
                                "**Ciclo básico**: sólo materias cuyo "
                                "código empieza con F o FB.\n"
                                "**Específicas**: excluye el ciclo básico."
                            ),
                        )
                    with col_ef5:
                        edit_excluir_comunes = st.checkbox(
                            "Ocultar materias compartidas con otras carreras",
                            key="edit_excluir_comunes",
                            help=(
                                "Si tildás, se ocultan las materias que "
                                "aparecen en el plan de estudio de más "
                                "de una carrera."
                            ),
                        )

                _edit_all_filters_set = (
                    edit_filtro_carrera is not None
                    and edit_filtro_anio is not None
                    and edit_filtro_cuatri is not None
                )

                edit_filtered_mats: set[str] | None = None
                if _edit_all_filters_set:
                    with next(get_session()) as session:
                        eq = select(PlanEstudioDB.materia_codigo)
                        e_carrera_cod = edit_filtro_carrera.split(" - ")[0]
                        eq = eq.where(PlanEstudioDB.carrera_codigo == e_carrera_cod)
                        eq = eq.where(PlanEstudioDB.anio_plan == int(edit_filtro_anio))
                        if edit_filtro_cuatri == "Anual":
                            eq = eq.where(PlanEstudioDB.cuatrimestre_plan.in_(["Anual", "anual"]))
                        else:
                            eq = eq.where(PlanEstudioDB.cuatrimestre_plan == edit_filtro_cuatri)
                        edit_filtered_mats = set(session.exec(eq.distinct()).all())

                if not _edit_all_filters_set:
                    st.caption(
                        "Seleccioná Carrera, Año y Cuatrimestre para ver "
                        "y editar las materias del cronograma."
                    )
                else:
                    with next(get_session()) as session:
                        grid_data_full = build_schedule_grid(session, sel_edit_id)

                    _edit_mats_en_schedule = set()
                    for _blocks in grid_data_full.values():
                        for _b in _blocks:
                            _edit_mats_en_schedule.add(_b.materia_codigo)

                    _edit_mats_disponibles = _edit_mats_en_schedule
                    if edit_filtered_mats is not None:
                        _edit_mats_disponibles = _edit_mats_en_schedule & edit_filtered_mats

                    _edit_mat_list = sorted(
                        _edit_mats_disponibles,
                        key=lambda c: materias_map.get(c, c),
                    )
                    edit_materias_sel = st.multiselect(
                        "Materias a mostrar",
                        options=_edit_mat_list,
                        default=_edit_mat_list,
                        format_func=lambda x: f"{materias_map.get(x, x)} — {x}",
                        key="edit_filtro_materias",
                    )
                    _edit_selected_set = (
                        set(edit_materias_sel)
                        if edit_materias_sel
                        else _edit_mats_disponibles
                    )

                    st.divider()

                    grid_data = grid_data_full
                    if grid_data:
                        grid_data = {
                            dia: [
                                b for b in blocks
                                if b.materia_codigo in _edit_selected_set
                            ]
                            for dia, blocks in grid_data.items()
                        }
                        grid_data = {d: bs for d, bs in grid_data.items() if bs}

                    grid_data = _aplicar_filtro_tipo(
                        grid_data, edit_filtro_tipo, edit_excluir_comunes,
                    )

                    action = render_editable_schedule_calendar(
                        grid_data, config, key="edit_cal",
                    )

                    # --- Selector de materia para agregar ---
                    st.divider()
                    mat_options_base = sorted(
                        c for c in materias_map
                        if c in edit_filtered_mats
                    )

                    busqueda_mat = st.text_input(
                        "🔍 Buscar materia por nombre o código",
                        key="edit_buscar_materia",
                        placeholder="Ej: algebra, F0301, programacion...",
                    )

                    if busqueda_mat.strip():
                        termino = busqueda_mat.strip().lower()
                        mat_options = [
                            c for c in mat_options_base
                            if termino in c.lower()
                            or termino in materias_map[c].lower()
                        ]
                    else:
                        mat_options = mat_options_base

                    if mat_options:
                        sel_mat_add = st.selectbox(
                            "Materia (para agregar al seleccionar un rango)",
                            options=mat_options,
                            index=None,
                            format_func=lambda x: f"{materias_map[x]} — {x}",
                            placeholder="Seleccioná una materia...",
                            key="edit_add_materia",
                        )
                    else:
                        if busqueda_mat.strip():
                            st.warning(
                                f"No se encontraron materias para "
                                f"'{busqueda_mat}'"
                            )
                        else:
                            st.info(
                                "No hay materias disponibles con "
                                "los filtros actuales."
                            )

            # =================================================================
            # Shared: process calendar actions
            # =================================================================
            if action is not None:
                if action.action == "move":
                    move_key = f"{action.entry_id}|{action.dia}|{action.hora_inicio}|{action.hora_fin}"
                    if st.session_state.get("_edit_processed_move") != move_key:
                        with next(get_session()) as session:
                            update_schedule_entry(
                                session,
                                action.entry_id,
                                dia=action.dia,
                                hora_inicio=action.hora_inicio,
                                hora_fin=action.hora_fin,
                            )
                        mat_nombre = materias_map.get(
                            action.materia_codigo,
                            action.materia_codigo or "",
                        )
                        st.session_state["_edit_toast"] = (
                            f"{mat_nombre} movida a {action.dia} "
                            f"{action.hora_inicio.strftime('%H:%M')}-"
                            f"{action.hora_fin.strftime('%H:%M')}"
                        )
                        st.session_state["_edit_processed_move"] = move_key
                        st.rerun()

                elif action.action == "click":
                    click_key = f"{action.entry_id}|{action.dia}|{action.hora_inicio}"
                    if st.session_state.get("_edit_processed_click") != click_key:
                        st.session_state["edit_pending_click"] = {
                            "entry_id": action.entry_id,
                            "materia": action.materia_codigo,
                            "dia": action.dia,
                            "hora_inicio": action.hora_inicio,
                            "hora_fin": action.hora_fin,
                            "comision": action.comision,
                            "_key": click_key,
                        }
                        _dialog_edit_entry()

                elif action.action == "select" and sel_mat_add:
                    select_key = f"{action.dia}|{action.hora_inicio}|{action.hora_fin}"
                    if st.session_state.get("_edit_processed_select") != select_key:
                        st.session_state["edit_pending_add"] = {
                            "schedule_id": sel_edit_id,
                            "materia": sel_mat_add,
                            "dia": action.dia,
                            "hora_inicio": action.hora_inicio,
                            "hora_fin": action.hora_fin,
                            "_key": select_key,
                        }
                        _dialog_confirm_add()


# =============================================================================
# Tab 5: Validar contra ciclo
# =============================================================================
with tab_validar:
    # Cargar ciclos para el selector
    with next(get_session()) as _v_session:
        _v_ciclos = ciclo_crud.get_all(_v_session, limit=100)
    _v_ciclo_ids = [c.id for c in _v_ciclos]
    _v_ciclos_map = {c.id: c for c in _v_ciclos}

    if not _v_ciclo_ids:
        st.info(
            "No hay ciclos registrados. Creá uno en la página **📆 Ciclos** "
            "antes de validar cronogramas."
        )
    else:
        from src.ui.validacion_cronograma_tab import render_tab as _render_validacion_tab
        _render_validacion_tab(_v_ciclo_ids, _v_ciclos_map)
