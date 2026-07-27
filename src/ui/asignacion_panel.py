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
    ComisionDB,
    HorarioDB,
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

    # El LP asigna aulas al PATRÓN (HorarioDB.aula_id), así que basta
    # con que el plan tenga al menos un horario.
    tiene_horarios = session.exec(
        select(HorarioDB)
        .join(ComisionDB, HorarioDB.comision_id == ComisionDB.id)  # type: ignore[arg-type]
        .where(ComisionDB.plan_cursada_id == plan_id)
        .limit(1)
    ).first()
    if tiene_horarios is None:
        problemas.append(
            "El plan no tiene horarios cargados. Agregá horarios "
            "desde el tab 📋 Grilla Horaria."
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
        st.markdown("**Configuración de la asignación de aulas**")
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
                "Peso de sobre-ocupación",
                min_value=0.0, value=10.0, step=1.0,
                help="Cuánto se castiga que el aula tenga menos capacidad "
                     "que los inscriptos esperados. Cuanto más alto, más "
                     "prioriza evitar que una comisión no entre.",
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
                help="Si está activo, la asignación no pisa clases con "
                     "aula elegida manualmente. Desactivalo sólo si "
                     "querés re-asignar todo desde cero.",
                key=f"{key_ns}_respetar",
            )
            lambda_under = st.number_input(
                "Peso de sub-utilización",
                min_value=0.0, value=1.0, step=0.5,
                help="Cuánto se castiga que el aula tenga capacidad muy "
                     "superior a los inscriptos (aula grande con pocos "
                     "alumnos).",
                key=f"{key_ns}_lunder",
            )
            tol_under = st.slider(
                "Tolerancia de sub-utilización",
                min_value=0.0, max_value=1.0, value=0.20, step=0.05,
                help="Margen relativo donde la sub-utilización no "
                     "penaliza. 0.20 = hasta 20% de espacio vacío sin "
                     "penalidad.",
                key=f"{key_ns}_tunder",
            )

        timeout = st.number_input(
            "Tiempo máximo de resolución (segundos)",
            min_value=10, max_value=1800, value=300, step=30,
            help="Si la asignación tarda más que esto, se corta y "
                 "devuelve la mejor solución parcial encontrada.",
            key=f"{key_ns}_timeout",
        )

        activar_alpha = st.toggle(
            "Redistribuir pesos entre comisiones (avanzado)",
            value=False,
            help=(
                "Permite que la asignación redistribuya el peso relativo "
                "de las comisiones del mismo dictado para mejorar el "
                "ajuste a la capacidad disponible. Los pesos propuestos "
                "se muestran como diferencia y se aplican sólo si los "
                "confirmás."
            ),
            key=f"{key_ns}_activar_alpha",
        )

        submitted = st.form_submit_button("🚀 Asignar aulas", type="primary")

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
    _status_humano = {
        "optimal": "resuelta",
        "infeasible": "no se pudo resolver",
        "timeout": "se agotó el tiempo",
        "error": "hubo un error",
    }.get(run.status, run.status)
    st.markdown(
        f"### {status_emoji} Última corrida — {_status_humano}"
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
        c6.metric("Costo total", f"{run.objective_value:.2f}",
                  help="Suma ponderada de sobre-ocupación y sub-utilización. "
                       "Cuanto más bajo, mejor el ajuste global.")
    if run.solver_seconds is not None:
        c7.metric("Tiempo de resolución (s)", f"{run.solver_seconds:.2f}")
    c8.metric("Manuales respetadas", run.n_ediciones_manuales_respetadas)

    with st.expander("Configuración aplicada", expanded=False):
        st.write({
            "Aplicar desde la fecha": run.fecha_desde.isoformat(),
            "Peso sobre-ocupación": run.lambda_over,
            "Peso sub-utilización": run.lambda_under,
            "Tolerancia sobre-ocupación": run.tol_over,
            "Tolerancia sub-utilización": run.tol_under,
            "Respetar ediciones manuales": run.respetar_ediciones_manuales,
            "Redistribuir pesos entre comisiones": run.activar_alpha,
            "Tiempo máximo de resolución (s)": run.timeout_seconds,
        })


# =============================================================================
# Public API
# =============================================================================

def render_panel(session: Session, plan_id: str, key_ns: str = "asig") -> None:
    """Punto de entrada del tab 'Aulas' en la página de Planes."""
    st.subheader("🏛️ Asignación de aulas")

    ok, problemas = _precheck(session, plan_id)
    if not ok:
        for p in problemas:
            st.error(p)
        return

    with st.expander(
        "ℹ️ Qué horarios entran a la asignación", expanded=False,
    ):
        st.markdown(
            "La asignación intenta encontrarle un aula a cada horario "
            "presencial del plan. **No** entran los siguientes horarios "
            "(se ignoran sin generar error):\n\n"
            "- Horarios de materias **virtuales** del catálogo (la "
            "materia está marcada como virtual).\n"
            "- Horarios cuyo **dictado del ciclo** está marcado como "
            "**virtual**. Útil para recursados que se dictan por Zoom "
            "este cuatrimestre — el dictado existe y la cobertura del "
            "cronograma lo cuenta como cubierto, pero no consume aula. "
            "Configurable desde **Ciclos → 📚 Dictados**, columna "
            "**Virtual**.\n"
            "- Horarios individuales marcados como **virtuales**. "
            "Permite mezclar modalidades dentro de un mismo dictado "
            "(por ejemplo, teoría virtual + laboratorio presencial).\n\n"
            "Si la asignación no encuentra solución, lo más común es "
            "que haya horarios del 2C en el cronograma del plan que "
            "en realidad deberían estar marcados como virtuales "
            "(recursados). Revisalos en Dictados antes de tocar las "
            "tolerancias."
        )

    # Sugerencia: si hay horarios cuyo tipo se podría auto-completar,
    # avisamos antes de correr el LP. No bloquea (la red de seguridad
    # del LP los infiere igual en memoria), pero recomendamos
    # persistirlos para que las vistas e informes los muestren bien.
    from src.services.plan_actions_service import (
        preview_auto_completar_tipos,
    )
    _autotipos_prev = preview_auto_completar_tipos(session, plan_id)
    if _autotipos_prev.total > 0:
        st.warning(
            f"💡 Hay **{_autotipos_prev.total} horario(s)** con tipo "
            "todavía sin determinar que se podrían completar "
            "automáticamente a partir de las horas declaradas en sus "
            "materias "
            f"({len(_autotipos_prev.a_teorica)} a teórica, "
            f"{len(_autotipos_prev.a_laboratorio)} a laboratorio). "
            "Aplicalo desde **🔧 Acciones del plan → Auto-completar "
            "tipo de horarios** para que las vistas e informes los "
            "muestren bien. La asignación igual los deduce sola al "
            "correr, así que no bloquea esta corrida."
        )

    cfg = _render_config_form(session, plan_id, key_ns)

    if cfg is not None:
        with st.spinner("Asignando aulas…"):
            run = run_lp(session, plan_id, cfg)
        if run.status == "optimal":
            st.success(
                f"Asignación resuelta en {run.solver_seconds:.2f}s. "
                f"{run.n_clases_actualizadas} clases actualizadas."
            )
        else:
            _mensajes_status = {
                "infeasible": "no se encontró solución válida",
                "timeout": "se agotó el tiempo máximo",
                "error": "hubo un error inesperado",
            }
            _msg = _mensajes_status.get(run.status, run.status)
            st.error(
                f"La asignación no resolvió: {_msg}. "
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
