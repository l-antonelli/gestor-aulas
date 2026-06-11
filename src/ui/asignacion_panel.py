"""Panel UI del LP de asignación de aulas.

Este módulo es el wrapper de Streamlit para el tab "Aulas" en la página
de Planes. Contiene:

- ``render_panel(session, plan_id, key_ns)``: form de configuración +
  botón "Correr LP" + summary del último run.

La lógica de cómputo vive en ``src/services/asignacion_aulas_service.py``.
"""

from __future__ import annotations

from datetime import date

import streamlit as st
from sqlmodel import Session, select

from src.database.models import (
    ClaseDB,
    LPRunDB,
    PlanificacionCursadaDB,
)
from src.services.asignacion_aulas_service import (
    LPConfig,
    get_latest_run,
    run_lp,
)


# =============================================================================
# Pre-checks
# =============================================================================

def _precheck(session: Session, plan_id: str) -> tuple[bool, list[str]]:
    """Devuelve (puede_correr, mensajes). Si puede_correr es False, los
    mensajes son los problemas detectados."""
    problemas: list[str] = []
    plan = session.get(PlanificacionCursadaDB, plan_id)
    if plan is None:
        return False, ["Plan no encontrado."]

    n_clases = session.exec(
        select(ClaseDB).where(ClaseDB.plan_cursada_id == plan_id).limit(1)
    ).first()
    if n_clases is None:
        problemas.append(
            "El plan no tiene clases generadas. Generalas desde el tab 📅 Clases."
        )

    return (len(problemas) == 0, problemas)


# =============================================================================
# Config form
# =============================================================================

def _render_config_form(
    session: Session, plan_id: str, key_ns: str,
) -> LPConfig | None:
    """Renderiza el form. Devuelve un LPConfig si el usuario apretó
    "Correr LP", sino None."""
    plan = session.get(PlanificacionCursadaDB, plan_id)
    if plan is None:
        return None
    from src.database.models import CicloDB
    ciclo = session.get(CicloDB, plan.ciclo_id) if plan.ciclo_id else None

    default_fecha = date.today()
    if ciclo is not None:
        # Si hoy < inicio del ciclo, usar el inicio (no tiene sentido un
        # rango futuro vacío).
        if default_fecha < ciclo.fecha_inicio:
            default_fecha = ciclo.fecha_inicio

    with st.form(f"{key_ns}_lp_form"):
        st.markdown("**Configuración del LP**")
        c1, c2 = st.columns(2)
        with c1:
            fecha_desde = st.date_input(
                "Aplicar desde la fecha",
                value=default_fecha,
                help="Las clases anteriores a esta fecha quedan intactas. "
                     "Sólo se reasignan clases con fecha ≥ la elegida y "
                     "no ejecutadas.",
                key=f"{key_ns}_fecha_desde",
            )
            lambda_over = st.number_input(
                "λ_over (peso sobre-ocupación)",
                min_value=0.0, value=10.0, step=1.0,
                help="Cuánto se castiga que el aula tenga menos capacidad "
                     "que los inscriptos esperados.",
                key=f"{key_ns}_lover",
            )
            tol_over = st.slider(
                "Tolerancia de sobre-ocupación",
                min_value=0.0, max_value=0.5, value=0.0, step=0.05,
                help="Margen relativo donde la sobre-ocupación no penaliza. "
                     "0 = cualquier exceso penaliza.",
                key=f"{key_ns}_tover",
            )
        with c2:
            respetar = st.toggle(
                "Respetar ediciones manuales",
                value=True,
                help="Si activo, el LP no pisa clases con aula asignada "
                     "manualmente. Desactivar sólo si querés re-asignar todo.",
                key=f"{key_ns}_respetar",
            )
            lambda_under = st.number_input(
                "λ_under (peso sub-utilización)",
                min_value=0.0, value=1.0, step=0.5,
                help="Cuánto se castiga que el aula tenga capacidad "
                     "muy superior a los inscriptos.",
                key=f"{key_ns}_lunder",
            )
            tol_under = st.slider(
                "Tolerancia de sub-utilización",
                min_value=0.0, max_value=1.0, value=0.20, step=0.05,
                help="Margen relativo donde la sub-utilización no "
                     "penaliza. 0.20 = hasta 20% de espacio vacío gratis.",
                key=f"{key_ns}_tunder",
            )

        timeout = st.number_input(
            "Timeout del solver (segundos)",
            min_value=10, max_value=1800, value=300, step=30,
            key=f"{key_ns}_timeout",
        )

        activar_alpha = st.toggle(
            "Redistribuir pesos α (avanzado)",
            value=False,
            help=(
                "Permite que el LP redistribuya `coef_asignacion` entre "
                "comisiones del mismo dictado para mejorar el ajuste a "
                "la capacidad disponible. Los pesos propuestos se "
                "muestran como diff y se aplican sólo si los confirmás."
            ),
            key=f"{key_ns}_activar_alpha",
        )

        submitted = st.form_submit_button("🚀 Correr LP", type="primary")

    if not submitted:
        return None

    return LPConfig(
        lambda_over=float(lambda_over),
        lambda_under=float(lambda_under),
        tol_over=float(tol_over),
        tol_under=float(tol_under),
        timeout_seconds=int(timeout),
        respetar_ediciones_manuales=bool(respetar),
        activar_alpha=bool(activar_alpha),
        fecha_desde=fecha_desde,
    )


# =============================================================================
# Summary del último run
# =============================================================================

def _render_summary(run: LPRunDB) -> None:
    """Renderiza un resumen del LPRunDB en métricas + nota de status."""
    status_emoji = {
        "optimal": "✅",
        "infeasible": "❌",
        "timeout": "⏱️",
        "error": "⚠️",
    }.get(run.status, "❔")
    st.markdown(
        f"### {status_emoji} Último run — {run.status}"
        f" · {run.run_at.strftime('%Y-%m-%d %H:%M')}"
    )

    if run.error_message:
        st.error(run.error_message)

    c1, c2, c3, c4, c5 = st.columns(5)
    c1.metric("Horarios totales", run.n_horarios_total)
    c2.metric("Asignados", run.n_horarios_asignados)
    c3.metric("Clases actualizadas", run.n_clases_actualizadas)
    c4.metric("Sobre-ocupados", run.n_clases_sobreocupadas)
    c5.metric("Sub-utilizados", run.n_clases_subutilizadas)

    c6, c7, c8 = st.columns(3)
    if run.objective_value is not None:
        c6.metric("Objetivo", f"{run.objective_value:.2f}")
    if run.solver_seconds is not None:
        c7.metric("Solver (s)", f"{run.solver_seconds:.2f}")
    c8.metric("Manuales respetadas", run.n_ediciones_manuales_respetadas)

    with st.expander("Configuración aplicada", expanded=False):
        st.write({
            "fecha_desde": run.fecha_desde.isoformat(),
            "λ_over": run.lambda_over,
            "λ_under": run.lambda_under,
            "tol_over": run.tol_over,
            "tol_under": run.tol_under,
            "respetar_ediciones_manuales": run.respetar_ediciones_manuales,
            "activar_alpha": run.activar_alpha,
            "timeout_seconds": run.timeout_seconds,
        })


# =============================================================================
# Public API
# =============================================================================

def render_panel(session: Session, plan_id: str, key_ns: str = "asig") -> None:
    """Punto de entrada del tab 'Aulas' en la página de Planes."""
    st.subheader("🏛️ Asignación de aulas (LP)")

    ok, problemas = _precheck(session, plan_id)
    if not ok:
        for p in problemas:
            st.error(p)
        return

    with st.expander(
        "ℹ️ Qué horarios entran al LP", expanded=False,
    ):
        st.markdown(
            "El LP intenta asignar un aula a cada horario presencial del "
            "plan. **No** entran al LP (se ignoran sin error):\n\n"
            "- Horarios de materias **virtuales** del catálogo "
            "(`MateriaDB.virtual = True`).\n"
            "- Horarios cuyo **dictado del ciclo** está marcado "
            "**virtual** (`DictadoDB.virtual = True`). Útil para "
            "recursados que se dictan por Zoom este cuatrimestre — "
            "el dictado figura activo en el ciclo y la cobertura del "
            "cronograma lo cuenta como cubierto, pero no consume aula. "
            "Configurable desde **Ciclos → 📚 Dictados**, columna "
            "**Virtual**.\n\n"
            "Si el LP da **infactible**, lo más común es que haya "
            "horarios del 2C en el cronograma del plan que en realidad "
            "deberían estar marcados como virtuales (recursados). "
            "Revisalos en Dictados antes de jugar con las tolerancias."
        )

    cfg = _render_config_form(session, plan_id, key_ns)

    if cfg is not None:
        with st.spinner("Resolviendo LP…"):
            run = run_lp(session, plan_id, cfg)
        if run.status == "optimal":
            st.success(
                f"LP resuelto en {run.solver_seconds:.2f}s. "
                f"{run.n_clases_actualizadas} clases actualizadas."
            )
        else:
            st.error(
                f"LP no resolvió: {run.status}. "
                f"{run.error_message or 'Sin detalles.'}"
            )
        st.rerun()

    # Mostrar el último run (puede haber sido recién creado o de antes).
    latest = get_latest_run(session, plan_id)
    if latest is not None:
        st.divider()
        _render_summary(latest)
        # render_resultado decide internamente: si es óptimo muestra la
        # tabla, si no es óptimo muestra el diagnóstico estructural.
        st.divider()
        from src.ui.asignacion_resultado_ui import render_resultado
        render_resultado(session, latest, key_ns=f"{key_ns}_res")

    # Vista cronograma por aula: independiente del run (sólo necesita
    # que existan clases con aula). Va abajo de todo en un expander.
    st.divider()
    with st.expander("📅 Cronograma por aula", expanded=False):
        from src.ui.aula_cronograma_view import render_aula_cronograma
        render_aula_cronograma(session, plan_id, key_ns=f"{key_ns}_aula")
