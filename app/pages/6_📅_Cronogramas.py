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
    CarreraDB, PlanCarreraVersionDB, PlanEstudioDB, CicloPlanVersionDB,
)
from src.database.crud import ciclo_crud, get_or_create_config
from src.services.schedule_service import (
    clonar_plan_a_cronograma,
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
    compute_validation_status,
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
    # Paso del selector según la granularidad configurada
    # (2026-09-24: antes quedaba el default de 15' sin importar la
    # config).
    from datetime import timedelta as _td
    _paso_cfg = _td(minutes=config.granularidad_minutos or 15)
    with col_ini:
        new_inicio = st.time_input(
            "Inicio", value=pending["hora_inicio"], key="dlg_edit_ini",
            step=_paso_cfg,
        )
    with col_fin:
        new_fin = st.time_input(
            "Fin", value=pending["hora_fin"], key="dlg_edit_fin",
            step=_paso_cfg,
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
    # Fase I.3 · Terminología unificada "Virtual" con opciones
    # Heredar/Sí/No — consistente con el data_editor de la tabla.
    _VIRT_LABEL_TO_DB = {
        "Heredar": None,
        "Sí (virtual)": True,
        "No (presencial)": False,
    }
    _VIRT_DB_TO_LABEL = {
        None: "Heredar",
        True: "Sí (virtual)",
        False: "No (presencial)",
    }
    _virtual_labels = list(_VIRT_LABEL_TO_DB.keys())
    _virtual_current_label = _VIRT_DB_TO_LABEL.get(
        _entry_virtual, "Heredar",
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
            "Virtual",
            options=_virtual_labels,
            index=_virtual_labels.index(_virtual_current_label),
            key="dlg_edit_virtual",
            help=(
                "**Heredar**: usa el flag virtual "
                "configurado en la materia (o en el dictado del "
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
                try:
                    with next(get_session()) as session:
                        update_schedule_entry(
                            session, pending["entry_id"], **cambios,
                        )
                except ValueError as _exc:
                    # Invariante virtual/tipo (2026-09-24).
                    st.error(f"No se guardó: {_exc}")
                    st.stop()
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
# Toast diferido de la última acción de import. Se consume ANTES de
# instanciar los tabs (fix auditoría 2026-09-23): si estuviera dentro
# de `with tab_cargar:` y algo en `tab_lista` levantara una excepción,
# la clave quedaría en session_state y el toast aparecería fuera de
# contexto en un rerun posterior.
if "_crono_import_toast" in st.session_state:
    st.toast(
        st.session_state.pop("_crono_import_toast"),
        icon="✅",
    )

# Fase I.2 · Unificamos Visualizar con Editar: en vez de dos tabs
# distintas, dejamos una sola pestaña "Ver / Editar" con un toggle
# "Solo lectura" arriba (default OFF) para ver sin editar. Simplifica
# el mapa de la app y garantiza que las dos vistas siempre están al día.
tab_lista, tab_cargar, tab_editar, tab_validar = st.tabs([
    "📋 Lista", "📤 Cargar", "✏️ Ver / Editar", "✅ Validar",
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
                # Estado consolidado de la ultima validacion (Fase A).
                # Cubre faltantes, particion, conflictos horarios y extras,
                # detectando staleness por hash de contenido (no solo counts).
                _val_status = compute_validation_status(session, s.id)

            _latest_val = _val_status.validation
            _val_stale = _val_status.stale
            _val_badge = _val_status.badge

            ciclo_label = s.ciclo_id if s.ciclo_id else "sin ciclo"
            _header = (
                f"**{s.nombre}** \u2014 {n_entries} entradas \u2014 "
                f"ciclo: {ciclo_label} \u2014 {s.fecha_upload} \u2014 "
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

                # Exportar como plantilla precargada, una hoja por
                # grupo de materias (2026-09-24): para repartir a
                # cada cátedra/departamento la hoja de su grupo,
                # corregir en Excel y reimportar hoja por hoja.
                with st.container(border=True):
                    st.markdown("**📤 Exportar horarios a Excel**")
                    st.caption(
                        "Genera la misma plantilla del importador "
                        "pero precargada con los horarios de este "
                        "cronograma, con una hoja por grupo de "
                        "materias. Ideal para repartir, corregir y "
                        "reimportar hoja por hoja."
                    )
                    if not s.ciclo_id:
                        st.caption(
                            "⚠️ Este cronograma no tiene ciclo "
                            "asociado — se necesita para armar las "
                            "listas de la plantilla."
                        )
                    else:
                        _exp_key = f"exp_bytes_{s.id}"
                        _exp_catalogo = st.checkbox(
                            "Ofrecer el catálogo completo de materias",
                            value=False,
                            key=f"exp_cat_{s.id}",
                            help=(
                                "Por defecto la hoja Materias y las "
                                "listas ofrecen sólo las materias con "
                                "dictado en el ciclo del cronograma. "
                                "Tildá para incluir TODO el catálogo "
                                "activo — útil si las cátedras van a "
                                "sumar materias que todavía no tienen "
                                "dictado creado."
                            ),
                        )
                        if st.button(
                            "Generar Excel por grupos",
                            key=f"exp_btn_{s.id}",
                        ):
                            from src.services.template_export_service import (
                                exportar_cronograma_por_grupos_excel,
                            )
                            try:
                                with next(get_session()) as _sess:
                                    st.session_state[_exp_key] = (
                                        exportar_cronograma_por_grupos_excel(
                                            _sess, s.id,
                                            catalogo_completo=_exp_catalogo,
                                        )
                                    )
                            except ValueError as _exc:
                                st.error(f"No se pudo exportar: {_exc}")
                                st.session_state.pop(_exp_key, None)
                        if _exp_key in st.session_state:
                            _exp_nombre = (
                                f"horarios_{s.nombre}".replace(" ", "_")
                                + ".xlsx"
                            )
                            st.download_button(
                                "⬇️ Descargar Excel precargado",
                                data=st.session_state[_exp_key],
                                file_name=_exp_nombre,
                                mime=(
                                    "application/vnd.openxmlformats-"
                                    "officedocument.spreadsheetml.sheet"
                                ),
                                key=f"exp_dl_{s.id}",
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
    st.subheader("Crear o cargar cronograma")
    st.caption(
        "Un cronograma es un conjunto de horarios (día + rango + "
        "materia + comisión) asociado a un ciclo. Podés crear uno "
        "vacío para cargar a mano, crear uno desde un archivo, o "
        "importar horarios adicionales sobre un cronograma existente "
        "(ideal para agregar los datos que van llegando de las "
        "cátedras en distintas tandas)."
    )

    with st.container(border=True):
        st.markdown("**⚙️ Configuración básica**")
        modo_carga = st.radio(
            "¿Qué querés hacer?",
            options=[
                "Crear vacío",
                "Crear desde archivo",
                "Importar en cronograma existente",
                "Copiar desde plan",
            ],
            horizontal=True,
            key="crono_modo",
            help=(
                "**Crear vacío**: arranca sin entradas, las cargás a "
                "mano desde la pestaña Editar.\n\n"
                "**Crear desde archivo**: crea un cronograma nuevo y "
                "carga las entradas del archivo de una.\n\n"
                "**Importar en cronograma existente**: toma un "
                "cronograma que ya está en la lista y le suma / "
                "reemplaza horarios desde un archivo. Con vista previa "
                "y decisión de combinación por materia.\n\n"
                "**Copiar desde plan**: crea un cronograma nuevo con "
                "el estado consolidado de un plan de cursada — útil "
                "para archivar la versión que quedó firme tras las "
                "validaciones y ediciones."
            ),
        )

        # El campo "Nombre" aplica a los modos que crean cronograma nuevo
        # (Crear vacío, Crear desde archivo, Copiar desde plan). El modo
        # "Copiar desde plan" ofrece un default derivado del plan, pero
        # el usuario lo puede editar.
        if modo_carga == "Importar en cronograma existente":
            nombre = ""
        elif modo_carga == "Copiar desde plan":
            # El default se recalcula cuando el usuario elige plan;
            # acá se muestra el input vacío y se sugiere abajo con
            # `session_state`.
            nombre = st.text_input(
                "Nombre del cronograma nuevo",
                key="crono_nombre",
                placeholder="Se autocompleta al elegir plan",
            )
        else:
            nombre = st.text_input(
                "Nombre del cronograma",
                key="crono_nombre",
                placeholder="Ej: Cronograma 2026 - 1C",
            )

        # El ciclo puede elegirse para todos los modos (referencia).
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

    if modo_carga in ("Crear desde archivo", "Importar en cronograma existente"):
        with st.container(border=True):
            st.markdown("**📤 Archivo de importación**")
            st.caption(
                "El archivo debe tener las columnas mínimas: materia, "
                "día, hora inicio, hora fin. Comisión, tipo_clase y "
                "virtual son opcionales."
            )

            # Descarga de plantilla Excel con dropdowns de códigos válidos
            # (Fase C1 del rediseño 2026-09-15).
            with st.expander(
                "📥 Descargar plantilla Excel con listas predeterminadas",
                expanded=False,
            ):
                st.caption(
                    "Genera un Excel con la hoja Horarios como tabla, "
                    "donde la materia se ingresa por código (lista "
                    "desplegable) y el nombre se autocompleta como "
                    "verificación de sólo lectura, más listas de días, "
                    "tipos y VERDADERO/FALSO para virtual. Ideal para "
                    "pasarle a las cátedras: no pueden escribir "
                    "códigos inválidos."
                )
                if ciclo_id_val is None:
                    st.info(
                        "Elegí primero un ciclo arriba — la lista de "
                        "códigos válidos depende de los dictados del "
                        "ciclo."
                    )
                else:
                    from src.services.template_export_service import (
                        generar_plantilla_cronograma_excel,
                        obtener_referencia_materias_del_ciclo,
                    )
                    _plantilla_key = f"crono_plantilla_bytes_{ciclo_id_val}"
                    _plantilla_err_key = f"crono_plantilla_err_{ciclo_id_val}"
                    if st.button(
                        "🧮 Generar plantilla",
                        key=f"crono_plantilla_btn_{ciclo_id_val}",
                        help=(
                            "Arma el Excel a partir de los dictados "
                            "activos del ciclo. Puede tardar 1-2 "
                            "segundos con muchas materias."
                        ),
                    ):
                        try:
                            with next(get_session()) as _sess:
                                st.session_state[_plantilla_key] = (
                                    generar_plantilla_cronograma_excel(
                                        _sess, ciclo_id_val,
                                    )
                                )
                            st.session_state.pop(_plantilla_err_key, None)
                        except ValueError as _exc:
                            st.session_state[_plantilla_err_key] = str(_exc)
                            st.session_state.pop(_plantilla_key, None)

                    if _plantilla_err_key in st.session_state:
                        st.error(st.session_state[_plantilla_err_key])
                    elif _plantilla_key in st.session_state:
                        st.download_button(
                            "⬇️ Descargar plantilla_horarios.xlsx",
                            data=st.session_state[_plantilla_key],
                            file_name=f"plantilla_horarios_{ciclo_id_val}.xlsx",
                            mime=(
                                "application/vnd.openxmlformats-officedocument"
                                ".spreadsheetml.sheet"
                            ),
                            key=f"crono_plantilla_dl_{ciclo_id_val}",
                        )
                        with next(get_session()) as _sess:
                            _refs = obtener_referencia_materias_del_ciclo(
                                _sess, ciclo_id_val,
                            )
                        st.caption(
                            f"Plantilla lista con **{len(_refs)}** códigos "
                            "válidos en la lista desplegable."
                        )

            uploaded = st.file_uploader(
                "Archivo CSV o Excel con horarios",
                type=["csv", "xlsx", "xls"],
                key="crono_upload",
            )

            # Selector de hoja cuando el Excel trae más de una hoja
            # visible (típico: un archivo de cátedra con 1C/2C/Verano
            # como hojas separadas). El fallback automático (elige
            # "Horarios" si existe, sino la primera visible) no le
            # sirve al usuario en ese caso.
            _sheet_choice: str | None = None
            if uploaded is not None:
                from src.services.horario_file_parser import (
                    hoja_default,
                    list_horarios_sheets,
                )
                # Cache por archivo (fix auditoría H2-perf, 2026-09-23):
                # listar las hojas corre en cada rerun del script — sin
                # cache se re-leía el workbook con cada interacción de
                # la página, incluso desde otros tabs.
                _upl_fid = getattr(uploaded, "file_id", None) or uploaded.name
                _sheets_cache = st.session_state.get("_crono_sheets_cache")
                if not _sheets_cache or _sheets_cache[0] != _upl_fid:
                    _sheets_cache = (_upl_fid, list_horarios_sheets(uploaded))
                    st.session_state["_crono_sheets_cache"] = _sheets_cache
                _sheets_visible = _sheets_cache[1]
                if len(_sheets_visible) > 1:
                    _sheet_choice = st.selectbox(
                        "Hoja del Excel a importar",
                        options=_sheets_visible,
                        # Fix auditoría H2 (2026-09-23): arrancar en la
                        # hoja que el parser prefiere ("Horarios"), no
                        # en la primera del workbook — sin esto, una
                        # hoja "Resumen" agregada antes de "Horarios"
                        # rompía un archivo que el fallback importaba
                        # bien.
                        index=hoja_default(_sheets_visible),
                        key="crono_upload_sheet",
                        help=(
                            "El archivo tiene varias hojas. Elegí "
                            "cuál querés previsualizar e importar."
                        ),
                    )
                elif len(_sheets_visible) == 1:
                    # Una sola hoja visible — igual la fijamos para
                    # que el parser use exactamente ésa (por si el
                    # archivo tiene además hojas ocultas).
                    _sheet_choice = _sheets_visible[0]

    if modo_carga == "Crear desde archivo":
        # Flujo legacy: crea el cronograma y carga en un solo paso.
        # Sin preview — para cronogramas nuevos alcanza con crear +
        # dejar que la validación posterior detecte cualquier
        # inconsistencia.
        if st.button(
            "Crear cronograma",
            disabled=not nombre or not uploaded,
            type="primary",
            width="stretch",
        ):
            with next(get_session()) as session:
                result = create_schedule_standalone(
                    session, nombre, uploaded,
                    ciclo_id=ciclo_id_val,
                    sheet_name=_sheet_choice,
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

    elif modo_carga == "Importar en cronograma existente":
        # Flujo Fase G del rediseño 2026-09-15: preview via shadow
        # schedule + tarjetas per-materia (rediseño 2026-09-23).
        from src.services.cronograma_import_service import (
            crear_shadow_import,
            descartar_shadow_import,
            finalizar_shadow_import,
            list_shadows_huerfanos,
        )
        from src.ui.calendar_render import (
            render_schedule_calendar,
        )

        def _limpiar_preview_state(
            sched_id: str, shadow_id: str | None,
        ) -> None:
            """Limpia TODAS las claves de session_state de un preview.

            Fix auditoría H13 (2026-09-23): antes cada camino de salida
            (confirmar, descartar de arriba, descartar de abajo,
            "preview perdido", re-crear) limpiaba un subconjunto
            distinto — los bytes del Excel quedaban acumulados en
            session_state y las decisiones per-materia sobrevivían al
            preview que las creó.
            """
            st.session_state.pop(f"crono_import_shadow_{sched_id}", None)
            st.session_state.pop(
                f"crono_import_shadow_val_{sched_id}", None,
            )
            if shadow_id:
                for _pref in (
                    "crono_import_decisiones",
                    "crono_import_file_bytes",
                    "crono_import_file_meta",
                    "cimp_pending_reval",
                    "cimp_regen_errs",
                ):
                    st.session_state.pop(f"{_pref}_{shadow_id}", None)

        # --------------------------------------------------------------
        # Banner de shadows huérfanos (si el usuario cerró el navegador
        # con un preview abierto, quedan en la DB).
        # --------------------------------------------------------------
        with next(get_session()) as _sess:
            _huerfanos = list_shadows_huerfanos(_sess)
        # Excluir los shadows de previews ABIERTOS en esta sesión —
        # antes el banner ofrecía descartar el preview que el usuario
        # estaba mirando (auditoría H13, 2026-09-23).
        _shadows_abiertos = {
            v.get("shadow_id")
            for k, v in st.session_state.items()
            if isinstance(k, str)
            and k.startswith("crono_import_shadow_")
            and isinstance(v, dict)
        }
        _huerfanos = [
            sh for sh in _huerfanos if sh.id not in _shadows_abiertos
        ]
        if _huerfanos:
            with st.container(border=True):
                st.warning(
                    f"🧹 Hay {len(_huerfanos)} vista(s) previa(s) de "
                    "importación sin finalizar. Se crean cuando abrís "
                    "una vista previa y no la confirmás ni cancelás "
                    "(por ejemplo si cerraste el navegador). Podés "
                    "limpiarlas acá:"
                )
                for _sh in _huerfanos:
                    _c1, _c2 = st.columns([3, 1])
                    _c1.caption(
                        f"**{_sh.nombre}** · destino "
                        f"`{_sh.shadow_target_schedule_id or '?'}` · "
                        f"{_sh.fecha_upload}"
                    )
                    if _c2.button(
                        "Descartar", key=f"discard_shadow_{_sh.id}",
                    ):
                        with next(get_session()) as _sess:
                            descartar_shadow_import(_sess, _sh.id)
                        # Limpiar cualquier resto de session_state
                        # keyed por este shadow (fix auditoría H13).
                        _limpiar_preview_state("", _sh.id)
                        st.rerun()

        if not all_schedules:
            st.info(
                "No hay cronogramas cargados. Creá primero uno vacío o "
                "desde archivo antes de importar."
            )
        else:
            _sched_options = {
                s.id: f"{s.nombre} ({s.fecha_upload})"
                for s in all_schedules
            }
            _sel_sched_id = st.selectbox(
                "Cronograma destino",
                options=list(_sched_options.keys()),
                format_func=lambda sid: _sched_options[sid],
                key="crono_import_sched",
                help=(
                    "El archivo se va a importar dentro de este "
                    "cronograma. Se muestra una vista previa con "
                    "calendario editable antes de confirmar."
                ),
            )

            # session_state keys namespaced por destino.
            _shadow_key = f"crono_import_shadow_{_sel_sched_id}"
            _validation_key = f"crono_import_shadow_val_{_sel_sched_id}"

            col_pv, col_reset = st.columns([3, 1])
            with col_pv:
                if st.button(
                    "🔍 Ver vista previa del archivo",
                    disabled=not uploaded,
                    type="primary",
                    width="stretch",
                    key="crono_import_preview_btn",
                ):
                    try:
                        # Fix auditoría H13 (2026-09-23): si ya había
                        # un preview abierto para este destino,
                        # descartarlo — antes el shadow viejo quedaba
                        # abandonado en la DB y reaparecía en el
                        # banner de huérfanos.
                        _prev_state = st.session_state.get(_shadow_key)
                        if _prev_state:
                            _old_shadow = _prev_state.get("shadow_id")
                            if _old_shadow:
                                with next(get_session()) as _sess:
                                    descartar_shadow_import(
                                        _sess, _old_shadow,
                                    )
                            _limpiar_preview_state(
                                _sel_sched_id, _old_shadow,
                            )
                        with next(get_session()) as _sess:
                            _shadow, _preview = crear_shadow_import(
                                _sess, _sel_sched_id, uploaded,
                                sheet_name=_sheet_choice,
                            )
                        st.session_state[_shadow_key] = {
                            "shadow_id": _shadow.id,
                            "preview_summary": {
                                "total_horarios": _preview.total_horarios,
                                "materias": len(_preview.materias),
                                # Fix auditoría H5 (2026-09-23): el
                                # listado per-materia se deriva del
                                # PREVIEW, no de la DB — sin esto una
                                # materia cuyo import falló por
                                # colisión y sin entries previas
                                # desaparecía de la pantalla.
                                "materias_codigos": sorted({
                                    m.materia_codigo
                                    for m in _preview.materias
                                }),
                                "materias_no_resueltas": (
                                    _preview.materias_no_resueltas
                                ),
                                "warnings": _preview.warnings,
                                "con_conflicto": [
                                    m.materia_codigo
                                    for m in _preview.materias_con_conflicto
                                ],
                            },
                        }
                        # Reset validación cacheada al recrear preview.
                        st.session_state.pop(_validation_key, None)
                    except ValueError as _exc:
                        st.error(str(_exc))
            with col_reset:
                if _shadow_key in st.session_state:
                    if st.button(
                        "🗑 Descartar",
                        key="crono_import_reset_btn",
                        width="stretch",
                    ):
                        _shadow_id = (
                            st.session_state[_shadow_key]["shadow_id"]
                        )
                        with next(get_session()) as _sess:
                            descartar_shadow_import(_sess, _shadow_id)
                        _limpiar_preview_state(_sel_sched_id, _shadow_id)
                        st.rerun()

            # ------------------------------------------------------------
            # Render del preview (shadow schedule + calendario)
            # ------------------------------------------------------------
            if _shadow_key in st.session_state:
                _pv_data = st.session_state[_shadow_key]
                _shadow_id = _pv_data["shadow_id"]
                _summary = _pv_data["preview_summary"]

                # Verificar que el shadow siga vivo.
                with next(get_session()) as _sess:
                    _shadow_db = _sess.get(ScheduleDB, _shadow_id)
                if _shadow_db is None:
                    st.warning(
                        "La vista previa se perdió (la copia temporal "
                        "se borró). Volvé a apretar 'Ver vista previa'."
                    )
                    _limpiar_preview_state(_sel_sched_id, _shadow_id)
                else:
                    st.info(
                        "👀 Esta es una **vista previa**: los cambios "
                        "todavía **no se guardaron** en el cronograma "
                        "destino. Revisá las tarjetas por materia de "
                        "abajo y apretá **Confirmar importación** "
                        "para persistir."
                    )

                    # Métricas.
                    _m1, _m2, _m3, _m4 = st.columns(4)
                    _m1.metric(
                        "Horarios en el archivo", _summary["total_horarios"],
                    )
                    _m2.metric("Materias del archivo", _summary["materias"])
                    _m3.metric(
                        "Requieren decisión", len(_summary["con_conflicto"]),
                        # Fix auditoría H12/B6 (2026-09-23): el tooltip
                        # explicaba el default viejo ("agregar") y un
                        # flujo que ya no existe.
                        help=(
                            "Materias que ya tenían horarios en el "
                            "cronograma destino. Por defecto se "
                            "**reemplazan**: quedan sólo las "
                            "comisiones que trae el archivo. Si "
                            "querés conservar las previas, cambiá la "
                            "decisión a 'agregar' o 'ignorar' en la "
                            "tarjeta de la materia, más abajo."
                        ),
                    )
                    with next(get_session()) as _sess:
                        _n_ent = _sess.exec(
                            select(func.count(ScheduleEntryDB.id))
                            .where(ScheduleEntryDB.schedule_id == _shadow_id)
                        ).one()
                    _m4.metric(
                        "Horarios en la vista previa", _n_ent,
                        help=(
                            "Total de horarios que quedan en el "
                            "cronograma después de confirmar (mezcla "
                            "de existentes + importados)."
                        ),
                    )

                    # Warnings + no resueltas.
                    if _summary["warnings"]:
                        with st.expander(
                            f"⚠️ Avisos ({len(_summary['warnings'])})",
                            expanded=False,
                        ):
                            for _w in _summary["warnings"]:
                                st.warning(_w)
                    if _summary["materias_no_resueltas"]:
                        with st.expander(
                            "🚫 Códigos no reconocidos "
                            f"({len(_summary['materias_no_resueltas'])})",
                            expanded=True,
                        ):
                            for _cod, _fila in _summary["materias_no_resueltas"]:
                                st.warning(
                                    f"Fila ~{_fila}: `{_cod}` no "
                                    "está en el catálogo — se ignoró."
                                )

                    # Rediseño 2026-09-23 (task #360): en vez de un
                    # calendario global del shadow + toggles de filtro,
                    # el preview es ahora un loop de expanders por
                    # materia del archivo. Cada expander muestra Antes
                    # (destino actual) y Después (shadow), con radio
                    # de decisión (reemplazar/agregar) que regenera la
                    # materia en el shadow, más chequeos estructurales.
                    # Todo lo hipotético queda contenido en cada tarjeta
                    # y la revisión se fuerza per-materia.
                    #
                    # Fix auditoría H5 (2026-09-23): el listado sale del
                    # PREVIEW (fuente de verdad de "qué trajo el
                    # archivo"), no de diffs contra la DB — antes una
                    # materia cuyo import falló por colisión y sin
                    # entries previas desaparecía del listado, dejando
                    # la pantalla autocontradictoria. El fallback cubre
                    # session_state de previews creados antes del fix.
                    _mats_con_prev = set(_summary["con_conflicto"])
                    _materias_del_archivo = _summary.get("materias_codigos")
                    if _materias_del_archivo is None:
                        with next(get_session()) as _sess:
                            _all_mat_shadow = set(_sess.exec(
                                select(ScheduleEntryDB.codigo_materia)
                                .where(
                                    ScheduleEntryDB.schedule_id == _shadow_id
                                )
                                .distinct()
                            ).all())
                            _all_mat_dest = set(_sess.exec(
                                select(ScheduleEntryDB.codigo_materia)
                                .where(
                                    ScheduleEntryDB.schedule_id
                                    == _sel_sched_id
                                )
                                .distinct()
                            ).all())
                        _materias_del_archivo = sorted(
                            _mats_con_prev
                            | (_all_mat_shadow - _all_mat_dest)
                        )

                    # Estado por-materia (decisión elegida). Persistido
                    # en session_state para que rerun no lo pise.
                    _decisiones_key = (
                        f"crono_import_decisiones_{_shadow_id}"
                    )
                    if _decisiones_key not in st.session_state:
                        st.session_state[_decisiones_key] = {
                            mc: "reemplazar" if mc in _mats_con_prev
                            else "agregar"
                            for mc in _materias_del_archivo
                        }
                    _decisiones_map = st.session_state[_decisiones_key]

                    # Guardar los bytes del archivo en session_state
                    # para poder llamar `regenerar_materia_en_shadow`
                    # cuando el usuario cambia una decisión, sin
                    # depender de que el uploader mantenga el archivo
                    # (Streamlit lo puede vaciar al rerun).
                    _file_bytes_key = (
                        f"crono_import_file_bytes_{_shadow_id}"
                    )
                    _file_meta_key = f"crono_import_file_meta_{_shadow_id}"
                    if _file_bytes_key not in st.session_state:
                        # `uploaded` puede ser None en el rerun. En ese
                        # caso, si ya tenemos bytes guardados no hace
                        # falta re-guardar.
                        if uploaded is not None:
                            # Fix auditoría (2026-09-23): sin el rewind
                            # verificado, un `seek` fallido dejaba
                            # `read()` devolviendo b"" y se persistían
                            # cero bytes — el mismo antipatrón que la
                            # task #339 eliminó del servicio. Si no se
                            # puede rebobinar, avisamos en vez de
                            # guardar basura.
                            try:
                                uploaded.seek(0)
                                _bytes_arch = uploaded.read()
                            except Exception:  # noqa: BLE001
                                _bytes_arch = b""
                            if _bytes_arch:
                                st.session_state[_file_bytes_key] = (
                                    _bytes_arch
                                )
                                st.session_state[_file_meta_key] = {
                                    "name": uploaded.name,
                                    "sheet": _sheet_choice,
                                }
                            else:
                                st.warning(
                                    "No se pudo conservar una copia "
                                    "del archivo para regenerar "
                                    "decisiones por materia. Si "
                                    "cambiás una decisión y falla, "
                                    "descartá la vista previa y volvé "
                                    "a subir el archivo."
                                )

                    def _archivo_para_regenerar():
                        """Reconstruye un file-like con `.name` para
                        `regenerar_materia_en_shadow`. Reusa los bytes
                        guardados en session_state.
                        """
                        _meta = st.session_state.get(_file_meta_key) or {}
                        _bytes = st.session_state.get(_file_bytes_key)
                        if _bytes is None:
                            return None, None
                        import io as _io
                        buf = _io.BytesIO(_bytes)
                        buf.name = _meta.get("name", "archivo.xlsx")  # type: ignore[attr-defined]
                        return buf, _meta.get("sheet")

                    # Correr validaciones sobre el shadow.
                    _pending_reval_key = f"cimp_pending_reval_{_shadow_id}"
                    _val_sum = None
                    if _shadow_db.ciclo_id is not None:
                        from src.services.cronograma_validation_service import (  # noqa: E501
                            validar_cronograma,
                            CronogramaValidationSummary,
                        )
                        _pending = st.session_state.pop(
                            _pending_reval_key, False,
                        )
                        if (
                            _validation_key not in st.session_state
                            or _pending
                        ):
                            with next(get_session()) as _sess:
                                st.session_state[_validation_key] = (
                                    validar_cronograma(
                                        _sess, _shadow_id,
                                        _shadow_db.ciclo_id,
                                        exclude_optativas=True,
                                    )
                                )
                        _val_sum = st.session_state[_validation_key]

                    # ============ Loop de expanders por materia ============
                    if not _materias_del_archivo:
                        st.info(
                            "El archivo no aportó materias "
                            "reconocibles a la vista previa."
                        )
                    else:
                        st.markdown(
                            f"### 📚 Materias del archivo "
                            f"({len(_materias_del_archivo)})"
                        )
                        st.caption(
                            "Para cada materia elegí si querés "
                            "**reemplazar** las entradas del destino "
                            "por las del archivo, **agregar** las "
                            "nuevas dejando las previas, o "
                            "**ignorarla** en este import (también "
                            "para materias nuevas, si el archivo vino "
                            "mal). Los calendarios Antes/Después son "
                            "de sólo lectura para comparar; los "
                            "ajustes finos se hacen en la sección "
                            "**✏️ Ajustes manuales** de cada tarjeta, "
                            "que edita la vista previa antes de "
                            "confirmar."
                        )

                        from src.ui.schedule_materia_editor import (
                            _opciones_horarias as _sme_opciones_horarias,
                            _DIAS_LIST as _SME_DIAS_LIST,
                            _persist_edits as _sme_persist_edits,
                            _time_str as _sme_time_str,
                            ESTADO_ICON_MAP,
                            compute_materia_checks_from_db,
                            render_materia_checks_inline,
                        )
                        from src.services.comision_service import (
                            list_comisiones_for_schedule_materia,
                        )
                        from src.services.cronograma_import_service import (
                            regenerar_materia_en_shadow,
                        )

                        # Errores de regeneración persistidos por
                        # materia (fix auditoría H3/H11, 2026-09-23:
                        # un `st.error` emitido antes del rerun se
                        # pierde — se guardan acá y se muestran dentro
                        # del expander de la materia).
                        _regen_errs_key = f"cimp_regen_errs_{_shadow_id}"
                        _regen_errs: dict = st.session_state.setdefault(
                            _regen_errs_key, {},
                        )

                        # Fix auditoría H4 (2026-09-23): las dos
                        # grillas se construyen UNA vez y se indexan
                        # por materia dentro del loop. Antes se llamaba
                        # `build_schedule_grid` (que carga el
                        # cronograma COMPLETO) dos veces por materia:
                        # con 248 materias eran 496 llamadas ≈ 8 s por
                        # rerun; ahora son 2 (~90 ms).
                        with next(get_session()) as _sess:
                            _grid_dest_full = build_schedule_grid(
                                _sess, _sel_sched_id,
                            )
                            _grid_shadow_full = build_schedule_grid(
                                _sess, _shadow_id,
                            )

                        def _grid_de_materia(grid_full, mc):
                            _out = {}
                            for _dia, _blocks in grid_full.items():
                                _bs = [
                                    b for b in _blocks
                                    if b.materia_codigo == mc
                                ]
                                if _bs:
                                    _out[_dia] = _bs
                            return _out

                        for _mc in _materias_del_archivo:
                            _mat_nombre = materias_map.get(_mc, _mc)
                            _decision_actual = _decisiones_map.get(
                                _mc, "reemplazar" if _mc in _mats_con_prev
                                else "agregar",
                            )
                            _check_res = compute_materia_checks_from_db(
                                _shadow_id, _mc,
                            )
                            _estado_badge_icon = ESTADO_ICON_MAP.get(
                                _check_res["estado"], "•",
                            )
                            _tiene_prev = _mc in _mats_con_prev
                            _prev_tag = (
                                "· 🕰 con datos previos"
                                if _tiene_prev else "· 🆕 nueva"
                            )
                            # El título refleja también los errores de
                            # la última regeneración (pedido
                            # 2026-09-23): el estado estructural solo
                            # no alcanza si la decisión no se pudo
                            # aplicar por completo.
                            _err_tag = (
                                " · ⚠️ con errores"
                                if _regen_errs.get(_mc) else ""
                            )
                            _dec_tag = (
                                " · 🚫 se ignora"
                                if _decision_actual == "ignorar" else ""
                            )
                            _exp_label = (
                                f"{_estado_badge_icon} **{_mc}** · "
                                f"{_mat_nombre} — "
                                f"{_check_res['estado']} · "
                                f"{_check_res['n_entries']} entrada(s) "
                                f"{_prev_tag}{_dec_tag}{_err_tag}"
                            )
                            _default_open = (
                                _check_res["estado"] != "OK"
                                or bool(_regen_errs.get(_mc))
                            )
                            with st.expander(
                                _exp_label, expanded=_default_open,
                            ):
                                # --- Ajustes manuales, arriba de todo (pedido
                                # 2026-09-23): expander anidado colapsado para no
                                # tapar el radio ni los calendarios. Streamlit 1.52
                                # tolera el anidamiento (verificado en la auditoría).
                                with st.expander(
                                    "✏️ Ajustes manuales (se aplican a la vista previa, no al destino)",
                                    expanded=False,
                                ):
                                    # --- Ajustes manuales del "Después" ---
                                    # (Pedido 2026-09-23, cierre del punto
                                    # que quedó sin implementar del rediseño
                                    # per-materia: "respeta ediciones
                                    # manuales posteriores que haga el
                                    # usuario con los controles".)
                                    # Data editor precargado con las entries
                                    # del shadow para esta materia. Al
                                    # aplicar, persiste al shadow (no al
                                    # destino) y refresca el Después + los
                                    # chequeos + las métricas globales.
                                    # Cambiar la decisión del radio regenera
                                    # la materia y pisa estos ajustes
                                    # (semántica documentada).
                                    with next(get_session()) as _sess:
                                        _ed_entries = list(_sess.exec(
                                            select(ScheduleEntryDB)
                                            .where(
                                                ScheduleEntryDB.schedule_id
                                                == _shadow_id
                                            )
                                            .where(
                                                ScheduleEntryDB.codigo_materia
                                                == _mc
                                            )
                                        ).all())
                                        _ed_coms = (
                                            list_comisiones_for_schedule_materia(
                                                _sess, _shadow_id, _mc,
                                            )
                                        )
                                    _ed_com_by_id = {c.id: c for c in _ed_coms}
                                    _ed_rows = []
                                    for _e in _ed_entries:
                                        _ec = (
                                            _ed_com_by_id.get(_e.comision_id)
                                            if _e.comision_id else None
                                        )
                                        _ed_rows.append({
                                            "_eid": _e.id,
                                            "Día": _e.dia,
                                            "Inicio": _sme_time_str(
                                                _e.hora_inicio,
                                            ),
                                            "Fin": _sme_time_str(_e.hora_fin),
                                            "Comisión": (
                                                _ec.numero if _ec else None
                                            ),
                                            "Tipo": (
                                                _e.tipo_clase
                                                or "sin determinar"
                                            ),
                                            # 2026-09-23: booleano; un
                                            # nulo se interpreta False.
                                            "Virtual": bool(_e.virtual),
                                        })
                                    _ed_df = pd.DataFrame(
                                        _ed_rows,
                                        columns=[
                                            "_eid", "Día", "Inicio", "Fin",
                                            "Comisión", "Tipo", "Virtual",
                                        ],
                                    )
                                    # Fingerprint de las entries: cuando la
                                    # regeneración (u otro apply) cambia el
                                    # shadow, cambia la key y el editor se
                                    # resetea con los datos frescos. Con
                                    # ediciones sin aplicar, el fingerprint
                                    # no cambia y el estado del widget
                                    # sobrevive al rerun.
                                    _ed_fp = abs(hash(tuple(sorted(
                                        (r["_eid"], r["Día"], r["Inicio"],
                                         r["Fin"], str(r["Comisión"]),
                                         r["Tipo"], str(r["Virtual"]))
                                        for r in _ed_rows
                                    )))) % 10**10
                                    _ed_com_nums = sorted(
                                        {c.numero for c in _ed_coms}
                                    ) or [1]
                                    _ed_com_opts = _ed_com_nums + [
                                        max(_ed_com_nums) + 1,
                                    ]
                                    _ed_times = sorted(
                                        set(_sme_opciones_horarias())
                                        | {r["Inicio"] for r in _ed_rows}
                                        | {r["Fin"] for r in _ed_rows}
                                    )
                                    st.caption(
                                        "Corregí acá los horarios que "
                                        "vinieron mal en el archivo antes "
                                        "de confirmar: editá celdas, "
                                        "agregá filas con «+» o borrá "
                                        "filas con la papelera (una fila "
                                        "borrada no se importa). Si "
                                        "cambiás la decisión de arriba, "
                                        "estos ajustes se pierden."
                                    )
                                    _ed_edited = st.data_editor(
                                        _ed_df,
                                        column_config={
                                            "_eid": None,
                                            "Día": st.column_config.SelectboxColumn(
                                                "Día",
                                                options=_SME_DIAS_LIST,
                                                required=True,
                                                width="medium",
                                            ),
                                            "Inicio": st.column_config.SelectboxColumn(
                                                "Inicio",
                                                options=_ed_times,
                                                required=True,
                                                width="small",
                                            ),
                                            "Fin": st.column_config.SelectboxColumn(
                                                "Fin",
                                                options=_ed_times,
                                                required=True,
                                                width="small",
                                            ),
                                            "Comisión": st.column_config.SelectboxColumn(
                                                "Comisión",
                                                options=_ed_com_opts,
                                                required=True,
                                                width="small",
                                            ),
                                            "Tipo": st.column_config.SelectboxColumn(
                                                "Tipo",
                                                options=[
                                                    "sin determinar",
                                                    "teorica",
                                                    "laboratorio",
                                                ],
                                                default="sin determinar",
                                                help=(
                                                    "Dejalo en 'sin "
                                                    "determinar' salvo "
                                                    "que haga falta "
                                                    "fijarlo ya: lo "
                                                    "resuelve la "
                                                    "asignación "
                                                    "automática (LP)."
                                                ),
                                                width="small",
                                            ),
                                            "Virtual": st.column_config.CheckboxColumn(
                                                "Virtual",
                                                default=False,
                                                help=(
                                                    "Sólo excepciones: "
                                                    "tildá si ESTA clase "
                                                    "es virtual aunque "
                                                    "el dictado sea "
                                                    "presencial. Un "
                                                    "laboratorio no "
                                                    "puede ser virtual."
                                                ),
                                                width="small",
                                            ),
                                        },
                                        num_rows="dynamic",
                                        use_container_width=True,
                                        hide_index=True,
                                        key=f"cimp_ed_{_shadow_id}_{_mc}_{_ed_fp}",
                                    )
                                    _ed_cols_cmp = [
                                        "Día", "Inicio", "Fin",
                                        "Comisión", "Tipo", "Virtual",
                                    ]
                                    _ed_changed = (
                                        len(_ed_edited) != len(_ed_df)
                                        or not _ed_edited[_ed_cols_cmp]
                                        .reset_index(drop=True)
                                        .equals(
                                            _ed_df[_ed_cols_cmp]
                                            .reset_index(drop=True)
                                        )
                                    )
                                    if _ed_changed and st.button(
                                        "💾 Aplicar ajustes a la vista previa",
                                        key=f"cimp_ed_apply_{_shadow_id}_{_mc}",
                                        type="primary",
                                    ):
                                        _ed_valid = _ed_edited.dropna(
                                            subset=["Día", "Inicio", "Fin"],
                                        )
                                        try:
                                            _sme_persist_edits(
                                                _shadow_id, _mc, _ed_valid,
                                            )
                                            st.session_state[
                                                _pending_reval_key
                                            ] = True
                                            st.rerun()
                                        except ValueError as _exc:
                                            st.error(
                                                f"No se pudieron aplicar "
                                                f"los ajustes: {_exc}"
                                            )

                                # Radio de decisión. Para materias con
                                # datos previos: reemplazar / agregar /
                                # ignorar. Para materias nuevas
                                # (2026-09-23): agregar / ignorar — el
                                # usuario puede excluir del import una
                                # materia cuyo archivo vino mal, sin
                                # comprometerse a subirla, y corregirla
                                # en el Excel de origen o con el editor
                                # de abajo.
                                if _tiene_prev:
                                    _dec_options = [
                                        "reemplazar",
                                        "agregar",
                                        "ignorar",
                                    ]
                                else:
                                    _dec_options = [
                                        "agregar",
                                        "ignorar",
                                    ]
                                _dec_labels = {
                                    "reemplazar": (
                                        "Reemplazar (borrar previas + "
                                        "usar sólo las del archivo)"
                                    ),
                                    "agregar": (
                                        "Agregar (dejar previas + "
                                        "sumar comisiones nuevas del "
                                        "archivo)"
                                        if _tiene_prev else
                                        "Agregar (importar los "
                                        "horarios del archivo)"
                                    ),
                                    "ignorar": (
                                        "Ignorar (dejar exactamente "
                                        "como está el destino)"
                                        if _tiene_prev else
                                        "Ignorar (no importar esta "
                                        "materia en este import)"
                                    ),
                                }
                                _new_dec = st.radio(
                                    "Decisión al confirmar el import",
                                    options=_dec_options,
                                    index=_dec_options.index(
                                        _decision_actual
                                    ),
                                    format_func=lambda k: _dec_labels[k],
                                    key=f"cimp_dec_{_shadow_id}_{_mc}",
                                    horizontal=False,
                                )
                                if _new_dec != _decision_actual:
                                    # Fix auditoría H11 (2026-09-23):
                                    # la decisión se persiste SOLO
                                    # si la regeneración salió bien
                                    # — antes se guardaba primero y
                                    # un fallo dejaba el radio
                                    # mostrando una decisión que el
                                    # shadow nunca aplicó (y
                                    # Confirmar persistía lo que el
                                    # shadow tenía, no lo que la
                                    # pantalla decía).
                                    _archivo, _sheet = (
                                        _archivo_para_regenerar()
                                    )
                                    if _archivo is None:
                                        _regen_errs[_mc] = [
                                            "Se perdió la copia del "
                                            "archivo en esta sesión "
                                            "— descartá la vista "
                                            "previa y volvé a subirlo."
                                        ]
                                        st.rerun()
                                    else:
                                        try:
                                            with next(get_session()) as _sess:  # noqa: E501
                                                _regen_res = regenerar_materia_en_shadow(  # noqa: E501
                                                    _sess, _shadow_id,
                                                    _mc,
                                                    decision=_new_dec,
                                                    file=_archivo,
                                                    sheet_name=_sheet,
                                                )
                                            _decisiones_map[_mc] = (
                                                _new_dec
                                            )
                                            # Fix auditoría H3
                                            # (2026-09-23): los
                                            # errores del commit
                                            # (colisión de nombre
                                            # de comisión) ya no se
                                            # descartan — se
                                            # persisten y se
                                            # muestran tras el
                                            # rerun.
                                            if _regen_res.errors:
                                                _regen_errs[_mc] = list(
                                                    _regen_res.errors
                                                )
                                            else:
                                                _regen_errs.pop(
                                                    _mc, None,
                                                )
                                            st.session_state[
                                                _pending_reval_key
                                            ] = True
                                            st.rerun()
                                        except ValueError as _exc:
                                            _regen_errs[_mc] = [
                                                str(_exc)
                                            ]
                                            st.rerun()

                                # Errores persistidos de la última
                                # regeneración de ESTA materia.
                                for _err_msg in _regen_errs.get(_mc, []):
                                    st.error(
                                        f"⚠️ La última decisión no se "
                                        f"aplicó por completo: {_err_msg}"
                                    )

                                # Columnas Antes / Después (grillas
                                # pre-construidas fuera del loop — fix
                                # auditoría H4).
                                _col_ab, _col_ds = st.columns(2)
                                with _col_ab:
                                    st.markdown("**⏮ Antes** (destino actual)")
                                    _grid_before = _grid_de_materia(
                                        _grid_dest_full, _mc,
                                    )
                                    if _grid_before:
                                        render_schedule_calendar(
                                            _grid_before, config,
                                            key=f"cimp_before_{_shadow_id}_{_mc}",
                                            color_by_comision=True,
                                        )
                                    else:
                                        st.caption(
                                            "Sin horarios previos en "
                                            "el destino."
                                        )
                                with _col_ds:
                                    st.markdown(
                                        "**⏭ Después** (estado hipotético)"
                                    )
                                    _grid_after = _grid_de_materia(
                                        _grid_shadow_full, _mc,
                                    )
                                    if _grid_after:
                                        render_schedule_calendar(
                                            _grid_after, config,
                                            key=f"cimp_after_{_shadow_id}_{_mc}",
                                            color_by_comision=True,
                                        )
                                    else:
                                        st.caption(
                                            "Sin horarios después "
                                            "(decisión = ignorar y "
                                            "sin datos previos)."
                                        )

                                # Chequeos estructurales de la materia.
                                # `as_expander=False`: ya estamos dentro
                                # del expander de la tarjeta — el
                                # expander anidado duplicaba el rótulo
                                # y enterraba los chequeos a dos clics
                                # (auditoría 2026-09-23).
                                render_materia_checks_inline(
                                    _check_res,
                                    materia_codigo=_mc,
                                    materia_nombre=_mat_nombre,
                                    as_expander=False,
                                )

                    # ============ Bloque final: métricas + confirmar ============
                    st.divider()
                    with st.container(border=True):
                        if _val_sum is not None:
                            st.markdown(
                                "**📊 Estado global del cronograma "
                                "hipotético (vs ciclo)**"
                            )
                            st.caption(
                                "Métricas que cubren todo el "
                                "cronograma después de confirmar el "
                                "import (no sólo las materias del "
                                "archivo)."
                            )
                            _vc1, _vc2, _vc3, _vc4, _vc5 = st.columns(5)
                            _vc1.metric("Faltantes", _val_sum.n_faltantes)
                            _vc2.metric(
                                "Conflictos horarios",
                                _val_sum.n_conflictos_horarios,
                            )
                            _vc3.metric(
                                "Bloqueos camino",
                                _val_sum.n_camino_bloqueos,
                            )
                            _vc4.metric(
                                "Partición",
                                "OK" if _val_sum.particion_valid
                                else f"{_val_sum.particion_n_infactibles} !",
                            )
                            _vc5.metric(
                                "Fuera de config",
                                _val_sum.n_horarios_fuera_config,
                            )
                        else:
                            st.caption(
                                "El cronograma destino no tiene ciclo "
                                "asociado — no se puede computar el "
                                "estado global."
                            )

                        st.divider()
                        st.warning(
                            "⚠️ Los cambios todavía no se guardaron. "
                            "Apretá **Confirmar** para persistir el "
                            "estado de la vista previa en el cronograma "
                            "destino, o **Descartar** para tirarlo."
                        )
                        _bc1, _bc2 = st.columns(2)
                        with _bc1:
                            if st.button(
                                "✅ Confirmar importación",
                                type="primary",
                                width="stretch",
                                key="crono_import_confirm_btn",
                            ):
                                try:
                                    with next(get_session()) as _sess:
                                        _fin_res = finalizar_shadow_import(
                                            _sess, _shadow_id,
                                        )
                                    # Toast con métricas honestas
                                    # (task #358, 2026-09-23): agregadas,
                                    # eliminadas y sin_cambio son
                                    # disjuntas y suman `finales` +
                                    # `eliminadas`. Antes se reportaban
                                    # "pisadas" que en realidad no
                                    # cambiaban nada al re-importar.
                                    _partes = []
                                    if _fin_res.entries_agregadas:
                                        _partes.append(
                                            f"{_fin_res.entries_agregadas} "
                                            "agregada(s)"
                                        )
                                    if _fin_res.entries_eliminadas:
                                        _partes.append(
                                            f"{_fin_res.entries_eliminadas} "
                                            "eliminada(s)"
                                        )
                                    if _fin_res.entries_sin_cambio:
                                        _partes.append(
                                            f"{_fin_res.entries_sin_cambio} "
                                            "sin cambio"
                                        )
                                    _resumen = (
                                        " · ".join(_partes)
                                        if _partes else "sin diferencias"
                                    )
                                    st.session_state[
                                        "_crono_import_toast"
                                    ] = (
                                        f"✅ Import aplicado en "
                                        f"«{_fin_res.destino_nombre}»: "
                                        f"{_resumen}. Total ahora: "
                                        f"{_fin_res.entries_finales} "
                                        "entrada(s)."
                                    )
                                    _limpiar_preview_state(
                                        _sel_sched_id, _shadow_id,
                                    )
                                    st.rerun()
                                except ValueError as _exc:
                                    st.error(str(_exc))
                        with _bc2:
                            if st.button(
                                "🗑 Descartar vista previa",
                                width="stretch",
                                key="crono_import_discard_bottom_btn",
                            ):
                                with next(get_session()) as _sess:
                                    descartar_shadow_import(_sess, _shadow_id)
                                _limpiar_preview_state(
                                    _sel_sched_id, _shadow_id,
                                )
                                st.rerun()

    elif modo_carga == "Copiar desde plan":
        # Fase F del rediseño 2026-09-15: clona el estado consolidado
        # de un plan (comisiones + horarios) como un cronograma nuevo,
        # útil para archivar la versión firme post-validaciones.
        with st.container(border=True):
            st.markdown("**🧬 Plan de origen**")
            st.caption(
                "Se copian las comisiones del plan y sus horarios "
                "(día, rango, tipo de clase, virtual). No se copia el "
                "aula asignada — el asignador la resuelve al generar "
                "el próximo plan."
            )
            from src.database.models import PlanificacionCursadaDB
            with next(get_session()) as _sess:
                _planes = list(_sess.exec(
                    select(PlanificacionCursadaDB).order_by(
                        PlanificacionCursadaDB.nombre  # type: ignore[arg-type]
                    )
                ).all())
                # Pre-cargar ciclo_id + nombre para display.
                _plan_labels = {
                    p.id: (
                        f"{p.nombre} · ciclo {p.ciclo_id}"
                        if p.ciclo_id else p.nombre
                    )
                    for p in _planes
                }

            if not _planes:
                st.info(
                    "No hay planes de cursada creados todavía. Andá "
                    "a **📊 Planes** para generar uno antes de "
                    "copiarlo como cronograma."
                )
            else:
                _sel_plan_id = st.selectbox(
                    "Plan de origen",
                    options=[p.id for p in _planes],
                    format_func=lambda pid: _plan_labels.get(pid, pid),
                    key="crono_clon_plan",
                    help=(
                        "El cronograma nuevo va a quedar linkeado al "
                        "mismo ciclo que este plan, salvo que elijas "
                        "otro ciclo arriba."
                    ),
                )

                # Auto-sugerir nombre si el campo está vacío.
                _plan_sel = next(
                    (p for p in _planes if p.id == _sel_plan_id), None,
                )
                if _plan_sel is not None and not (nombre or "").strip():
                    _sugerido = f"Copia de {_plan_sel.nombre}"
                    st.caption(
                        f"Sugerencia de nombre: **{_sugerido}** "
                        "(escribí uno propio arriba si preferís)."
                    )
                    _nombre_final = _sugerido
                else:
                    _nombre_final = (nombre or "").strip()

                # Override de ciclo: si el usuario eligió un ciclo
                # distinto del que tiene el plan, se muestra warning.
                _ciclo_override = None
                if _plan_sel is not None:
                    if (
                        ciclo_id_val is not None
                        and ciclo_id_val != _plan_sel.ciclo_id
                    ):
                        st.warning(
                            f"El plan pertenece al ciclo "
                            f"**{_plan_sel.ciclo_id}**. Vas a crear "
                            f"el cronograma linkeado a "
                            f"**{ciclo_id_val}** (override)."
                        )
                        _ciclo_override = ciclo_id_val

                if st.button(
                    "🧬 Copiar como cronograma nuevo",
                    disabled=(_plan_sel is None),
                    type="primary",
                    width="stretch",
                    key="crono_clon_btn",
                ):
                    if _plan_sel is None:
                        st.error("Elegí un plan primero.")
                    else:
                        try:
                            with next(get_session()) as _sess:
                                _new_sched = clonar_plan_a_cronograma(
                                    _sess,
                                    _plan_sel.id,
                                    _nombre_final,
                                    ciclo_id_override=_ciclo_override,
                                )
                                # Métricas rápidas para el toast.
                                from src.database.models import (
                                    ComisionDB as _ComDB,
                                )
                                _n_com = _sess.exec(
                                    select(func.count(_ComDB.id))
                                    .where(
                                        _ComDB.schedule_id == _new_sched.id
                                    )
                                ).one()
                                _n_ent = _sess.exec(
                                    select(func.count(ScheduleEntryDB.id))
                                    .where(
                                        ScheduleEntryDB.schedule_id
                                        == _new_sched.id
                                    )
                                ).one()
                            st.success(
                                f"Cronograma '{_new_sched.nombre}' "
                                f"creado con {_n_com} comisiones y "
                                f"{_n_ent} horarios."
                            )
                            st.rerun()
                        except ValueError as _exc:
                            st.error(str(_exc))

    else:  # modo_carga == "Crear vacío"
        st.info(
            "Se va a crear un cronograma sin entradas. Después "
            "podés cargar los horarios desde la pestaña **Editar** "
            "o desde acá mismo con 'Importar en cronograma existente'."
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
# Tab 4: Editar
# =============================================================================
with tab_editar:
    # Mostrar toast pendiente de accion anterior
    if "_edit_toast" in st.session_state:
        st.toast(st.session_state.pop("_edit_toast"))

    st.subheader("Ver / Editar cronograma")

    # Fase I.2 · Toggle "Solo lectura". Default OFF (modo edición).
    # Cuando está ON, la vista muestra exactamente los mismos
    # componentes que en edición, pero:
    # - El calendario se renderea con `render_schedule_calendar`
    #   (drag/drop deshabilitado, click de edición inactivo).
    # - El `data_editor` se marca `disabled=True`.
    # - Los botones de acción (Agregar / Guardar / Eliminar) quedan
    #   ocultos.
    # De esta forma "Visualizar" y "Editar" son la misma vista con
    # sólo un flag distinto — cero duplicación.
    edit_readonly = st.toggle(
        "🔒 Solo lectura",
        value=False,
        key="edit_readonly_toggle",
        help=(
            "Cuando está ON, la vista se comporta como Visualizar: "
            "no permite editar horarios, comisiones ni agregar filas. "
            "Ideal para consultar el cronograma sin miedo a tocarlo "
            "por accidente."
        ),
    )

    if edit_readonly:
        st.caption(
            "👁 **Modo lectura**: la vista muestra los horarios y las "
            "comisiones del cronograma sin permitir ediciones. Podés "
            "usar los filtros de la misma manera que en modo edición. "
            "Apagá el toggle para volver a editar."
        )
    else:
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

                    # Fase I.2 · En modo lectura, usar el calendario
                    # read-only. `action` queda en None y todo el
                    # procesamiento posterior de acciones no dispara.
                    if edit_readonly:
                        render_schedule_calendar(
                            _sm_grid, config,
                            key=f"edit_cal_ro_{_sm_n}",
                            color_by_comision=True,
                        )
                        action = None
                    else:
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

                    def _virtual_to_label(v: bool | None) -> bool:
                        """2026-09-23: virtual es booleano — un nulo
                        (heredar histórico) se interpreta False."""
                        return bool(v)

                    def _label_to_virtual(lbl) -> bool:
                        """Checkbox → bool. Compat con los labels
                        viejos del selectbox por si quedan en el
                        estado del widget."""
                        if isinstance(lbl, bool):
                            return lbl
                        return str(lbl).strip().lower() in ("sí", "si", "true", "1")

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
                                        # Validaciones de coherencia
                                        # (2026-09-23): inicio < fin y
                                        # laboratorio nunca virtual.
                                        _f_hi = _cambios.get(
                                            "hora_inicio", _e.hora_inicio,
                                        )
                                        _f_hf = _cambios.get(
                                            "hora_fin", _e.hora_fin,
                                        )
                                        _f_tipo = _cambios.get(
                                            "tipo_clase", _e.tipo_clase,
                                        )
                                        _f_virt = _cambios.get(
                                            "virtual", bool(_e.virtual),
                                        )
                                        if _f_hi >= _f_hf:
                                            st.session_state["_edit_toast"] = (
                                                "⚠️ No se guardó: la hora "
                                                "de inicio debe ser "
                                                "anterior a la de fin."
                                            )
                                            continue
                                        if _f_tipo == "laboratorio" and _f_virt:
                                            st.session_state["_edit_toast"] = (
                                                "⚠️ No se guardó: una "
                                                "clase de laboratorio no "
                                                "puede ser virtual."
                                            )
                                            continue
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
                                        row.get("Virtual") or False
                                    )
                                    _n_hi = _coerce_time(row["Inicio"])
                                    _n_hf = _coerce_time(row["Fin"])
                                    if _n_hi >= _n_hf:
                                        st.session_state["_edit_toast"] = (
                                            "⚠️ Fila nueva no guardada: "
                                            "inicio debe ser anterior a "
                                            "fin."
                                        )
                                        continue
                                    if _tipo == "laboratorio" and _virtual_val:
                                        st.session_state["_edit_toast"] = (
                                            "⚠️ Fila nueva no guardada: "
                                            "un laboratorio no puede ser "
                                            "virtual."
                                        )
                                        continue
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
                                    "Tipo de clase. Dejalo en **sin "
                                    "determinar** salvo que haga "
                                    "falta fijarlo ya: lo decide la "
                                    "asignación automática según las "
                                    "horas de la materia. "
                                    "**teoria** o **laboratorio**: "
                                    "forzá el tipo para este horario."
                                ),
                                width="small",
                            ),
                            "Virtual": column_config.CheckboxColumn(
                                "Virtual",
                                default=False,
                                help=(
                                    "Sólo para excepciones: tildá "
                                    "cuando ESTA clase se dicta "
                                    "virtual aunque el dictado sea "
                                    "presencial. Si toda la materia "
                                    "es virtual, se configura en el "
                                    "dictado. Destildado = "
                                    "presencial. Un laboratorio no "
                                    "puede ser virtual."
                                ),
                                width="small",
                            ),
                        },
                        num_rows="fixed" if edit_readonly else "dynamic",
                        use_container_width=True,
                        hide_index=True,
                        on_change=None if edit_readonly else _sm_on_change,
                        key=_sm_de_key,
                        disabled=edit_readonly,
                    )

                    # --- Dialog para crear comisión nueva al vuelo ---
                    # (Skippeamos en modo lectura.)
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
                            num_rows="fixed" if edit_readonly else "dynamic",
                            on_change=None if edit_readonly else _com_on_change,
                            key=_com_de_key,
                            use_container_width=True,
                            disabled=edit_readonly,
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

                    # Chequeos estructurales de la materia seleccionada.
                    # Reusa la misma máquina que el editor por-materia y
                    # el panel Validar → mantiene el estado alineado sin
                    # duplicar lógica (Fase I.3 del rediseño, 2026-09-23).
                    from src.ui.schedule_materia_editor import (
                        compute_materia_checks_from_db,
                        render_materia_checks_inline,
                    )
                    st.divider()
                    st.markdown("### 🔎 Chequeos estructurales")
                    _sm_check_result = compute_materia_checks_from_db(
                        sel_edit_id, _sm_sel,
                    )
                    render_materia_checks_inline(
                        _sm_check_result,
                        materia_codigo=_sm_sel,
                        materia_nombre=materias_map.get(_sm_sel, _sm_sel),
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

                    # Fase I.2 · Read-only en modo lectura.
                    if edit_readonly:
                        render_schedule_calendar(
                            grid_data, config, key="edit_cal_ro",
                        )
                        action = None
                    else:
                        action = render_editable_schedule_calendar(
                            grid_data, config, key="edit_cal",
                        )

                    # Chequeos estructurales por materia del grupo (Fase
                    # I.3 del rediseño, 2026-09-23). Recorre las
                    # materias que quedaron visibles según los filtros
                    # y las muestra como expanders con el mismo layout
                    # que "Detalle por materia" del panel Validar, sin
                    # duplicar la lógica (comparten
                    # `compute_materia_checks_from_db`).
                    from src.ui.schedule_materia_editor import (
                        compute_materia_checks_from_db,
                        render_materia_checks_inline,
                    )
                    _mats_para_chequear = sorted(
                        m for m in _edit_selected_set
                        if any(
                            b.materia_codigo == m
                            for blocks in grid_data.values()
                            for b in blocks
                        )
                    )
                    if _mats_para_chequear:
                        st.divider()
                        st.markdown(
                            f"### 🔎 Chequeos por materia ({len(_mats_para_chequear)})"
                        )
                        st.caption(
                            "Mismos chequeos estructurales que aparecen "
                            "en el panel Validar → Detalle por materia. "
                            "Cada tarjeta se abre por defecto cuando el "
                            "estado no es OK."
                        )
                        for _mc in _mats_para_chequear:
                            _res = compute_materia_checks_from_db(
                                sel_edit_id, _mc,
                            )
                            render_materia_checks_inline(
                                _res,
                                materia_codigo=_mc,
                                materia_nombre=materias_map.get(_mc, _mc),
                            )

                    # --- Selector de materia para agregar ---
                    # Fase I.2 · Solo aplica en modo edición. En modo
                    # lectura, se oculta.
                    if not edit_readonly:
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
