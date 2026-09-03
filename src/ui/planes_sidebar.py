"""Selector global de ciclo + plan para la página de Planes.

Renderiza en el sidebar dos selectores (Ciclo activo y Plan activo)
separados de la navegación por un divider. Ambos son opcionales:
si el usuario no elige un ciclo, la página muestra un mensaje y
detiene el render. Si elige ciclo pero no plan, sólo se muestran
las pestañas que no dependen de plan (ej. lista de planes del
ciclo, configuración).

El estado se persiste en ``session_state`` bajo las keys
``planes_ciclo_activo`` y ``planes_plan_activo`` para que los
cambios sobrevivan reruns dentro de la página.
"""

from __future__ import annotations

from typing import Optional

import streamlit as st
from sqlmodel import Session, select

from src.database.models import CicloDB, PlanificacionCursadaDB


CICLO_KEY = "planes_ciclo_activo"
PLAN_KEY = "planes_plan_activo"


def _fmt_ciclo(ciclo: CicloDB) -> str:
    return f"{ciclo.anio} · {ciclo.numero}C"


def render_ciclo_plan_sidebar(
    session: Session,
) -> tuple[Optional[str], Optional[str]]:
    """Renderiza los selectores en el sidebar y devuelve
    ``(ciclo_id, plan_id)``. Ambos pueden ser ``None`` si el
    usuario no eligió."""
    ciclos = list(session.exec(
        select(CicloDB).order_by(CicloDB.anio, CicloDB.numero)  # type: ignore[arg-type]
    ).all())

    with st.sidebar:
        st.divider()
        st.markdown("**📊 Contexto de Planes**")
        if not ciclos:
            st.caption(
                "No hay ciclos registrados. Creá uno desde la página "
                "de Ciclos."
            )
            return None, None

        ciclo_ids = [c.id for c in ciclos]
        ciclo_map = {c.id: c for c in ciclos}
        # Si la key ya está pero el ciclo desapareció (raro pero
        # posible tras borrado), la reseteamos.
        _current = st.session_state.get(CICLO_KEY)
        if _current is not None and _current not in ciclo_ids:
            st.session_state[CICLO_KEY] = None

        sel_ciclo = st.selectbox(
            "Ciclo activo",
            options=[None] + ciclo_ids,
            format_func=lambda cid: (
                "— Seleccionar ciclo —" if cid is None
                else _fmt_ciclo(ciclo_map[cid])
            ),
            index=(
                ([None] + ciclo_ids).index(_current)
                if _current in ciclo_ids else 0
            ),
            key=CICLO_KEY,
            help=(
                "Elegí un ciclo para trabajar con sus planes. El "
                "ciclo elegido persiste mientras navegás dentro de la "
                "página Planes."
            ),
        )

        if sel_ciclo is None:
            # Sin ciclo: no mostramos selector de plan.
            return None, None

        planes = list(session.exec(
            select(PlanificacionCursadaDB)
            .where(PlanificacionCursadaDB.ciclo_id == sel_ciclo)
            .order_by(PlanificacionCursadaDB.nombre)  # type: ignore[arg-type]
        ).all())

        if not planes:
            st.caption(
                "Este ciclo no tiene planes todavía. Generá uno "
                "desde la pestaña **📋 Planes del ciclo**."
            )
            return sel_ciclo, None

        plan_ids = [p.id for p in planes]
        plan_map = {p.id: p for p in planes}
        # Reset si el plan quedó huérfano (cambió el ciclo o se borró).
        _current_plan = st.session_state.get(PLAN_KEY)
        if _current_plan is not None and _current_plan not in plan_ids:
            st.session_state[PLAN_KEY] = None

        sel_plan = st.selectbox(
            "Plan activo",
            options=[None] + plan_ids,
            format_func=lambda pid: (
                "— Seleccionar plan —" if pid is None
                else plan_map[pid].nombre
            ),
            index=(
                ([None] + plan_ids).index(_current_plan)
                if _current_plan in plan_ids else 0
            ),
            key=PLAN_KEY,
            help=(
                "Elegí un plan para acceder a Detalle, Grilla Horaria "
                "y Aulas. Sin plan seleccionado, esas pestañas "
                "quedan ocultas."
            ),
        )

    return sel_ciclo, sel_plan
