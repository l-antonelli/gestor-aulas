"""Tab "Validar" de la pagina Cronogramas — wrapper delgado.

Originalmente vivia aca toda la logica de prevalidacion (Phase 1 +
Phase 2 + dialogs + ~2800 lineas). Sub-task C movio todo a
`src/ui/validation_ui.py::render_validation(source='schedule', ...)`.

Este modulo mantiene solo la UI exclusiva del tab: selector de ciclo
+ selector de cronograma, mas la seccion explicativa "Que significa
validar?". Despues delega al renderer unificado.
"""

from __future__ import annotations

import streamlit as st

from src.database.connection import get_session
from src.services.schedule_service import get_schedules_for_ciclo
from src.ui.validation_ui import render_validation


def render_tab(ciclo_ids: list[str], ciclos_map: dict) -> None:
    """Render the cronograma validation tab.

    Args:
        ciclo_ids: List of ciclo IDs to choose from in the selectbox.
        ciclos_map: Map ciclo_id → CicloDB for any extra info.
    """
    st.subheader("Prevalidacion de cronograma contra ciclo")
    st.caption(
        "Selecciona un ciclo y un cronograma para prevalidar los datos. "
        "Podes ajustar comisiones, horarios y horas teoria/lab antes de "
        "generar un plan. Cada validacion queda registrada en el historial."
    )

    with st.expander("ℹ️ Que significa validar?", expanded=False):
        st.markdown(
            """
            **Validar un cronograma contra un ciclo** compara las materias
            presentes en el cronograma con las que se esperan dictar en ese
            ciclo, y verifica condiciones estructurales que necesita el
            siguiente paso (generar plan + asignar aulas).

            **Materias esperadas = `Dictados` activos del ciclo**. Los dictados
            se gestionan en **📆 Ciclos → 📚 Dictados**: ahi se decide para
            cada materia del plan si se va a dictar este cuatrimestre y como
            (`activo`, `virtual`). Si una materia esta marcada `activo=False`,
            no aparece en faltantes ni se considera esperada.

            **Que se controla**:

            - **Cobertura**: cuantas materias esperadas (dictados activos) estan
              cubiertas, cuales faltan (con detalle por carrera y dictado
              codigo), y cuales aparecen en el cronograma sin tener un dictado
              activo en el ciclo (extras).
            - **Laboratorios**: cuantas materias del cronograma tienen
              laboratorios compatibles asignados, y como esta configurado su
              modo:
                - **fijo** (`horas_laboratorio > 0`): el LP usara los slots
                  para fijar lab.
                - **reserva ad-hoc** (`horas_laboratorio = 0`): el LP no fija
                  lab; los docentes lo reservan caso por caso durante el
                  ejercicio.
                - **pendiente** (`horas_laboratorio is None`): falta definir;
                  bloqueante.
            - **Particion teoria/lab**: para cada comision de materia con lab
              fijo, que las clases puedan dividirse en subconjuntos que sumen
              `horas_teoria` y `horas_laboratorio`.

            La pagina **Planes** empieza desde un cronograma validado para
            generar el plan + asignar aulas + fijar la agenda concreta de
            clases.
            """
        )

    # --- Restore persisted selections (survive page navigation) ---
    _P_CICLO = "_persist_planes_ciclo_crono"
    _P_CRONO = "_persist_planes_cronograma"
    if (
        _P_CICLO in st.session_state
        and "planes_sel_ciclo_crono" not in st.session_state
    ):
        _v = st.session_state[_P_CICLO]
        if _v in ciclo_ids:
            st.session_state["planes_sel_ciclo_crono"] = _v

    # --- Selection row ---
    _vc_c1, _vc_c2 = st.columns(2)
    with _vc_c1:
        sel_ciclo_crono = st.selectbox(
            "Ciclo",
            options=ciclo_ids,
            key="planes_sel_ciclo_crono",
            help="Ciclo lectivo contra el cual se valida el cronograma.",
        )
    st.session_state[_P_CICLO] = sel_ciclo_crono

    if not sel_ciclo_crono:
        return

    with next(get_session()) as session:
        schedules = get_schedules_for_ciclo(session, sel_ciclo_crono)

    with _vc_c2:
        if not schedules:
            st.info("No hay cronogramas cargados para este ciclo.")
            return
        _sched_options = {s.id: s.nombre for s in schedules}
        if (
            _P_CRONO in st.session_state
            and "planes_sel_cronograma" not in st.session_state
        ):
            _v = st.session_state[_P_CRONO]
            if _v in _sched_options:
                st.session_state["planes_sel_cronograma"] = _v

        _sel_sched_id = st.selectbox(
            "Cronograma",
            options=list(_sched_options.keys()),
            format_func=lambda x: _sched_options[x],
            key="planes_sel_cronograma",
            help="Cronograma cargado para este ciclo.",
        )
        st.session_state[_P_CRONO] = _sel_sched_id

    if not _sel_sched_id:
        return

    # Delegamos al renderer unificado.
    render_validation(
        source="schedule",
        schedule_id=_sel_sched_id,
        ciclo_id=sel_ciclo_crono,
        key_ns="cron_val",
    )
