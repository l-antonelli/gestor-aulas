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

def _render_tabla_manuales(
    session: Session, plan_id: str, key_ns: str,
) -> None:
    """Lista los HorarioDB del plan con
    ``aula_asignada_manualmente=True`` con opción de desmarcarlos.

    Se muestra sólo cuando el toggle "Respetar ediciones manuales"
    está activo (el caller ya lo verifica). Sirve para que el usuario
    revise qué asignaciones va a proteger la próxima corrida y pueda
    liberarlas fácilmente.
    """
    from src.database.models import (
        AulaDB, ComisionDB, HorarioDB, MateriaDB, SedeDB,
    )
    from src.services.asignacion_aulas_service import (
        cambiar_aula_horario,
    )

    com_ids = list(session.exec(
        select(ComisionDB.id).where(
            ComisionDB.plan_cursada_id == plan_id,
        )
    ).all())
    if not com_ids:
        return
    horarios_manuales = list(session.exec(
        select(HorarioDB)
        .where(HorarioDB.comision_id.in_(com_ids))  # type: ignore[attr-defined]
        .where(HorarioDB.aula_asignada_manualmente == True)  # noqa: E712
    ).all())

    with st.expander(
        f"🔒 Asignaciones manuales protegidas "
        f"({len(horarios_manuales)})",
        expanded=False,
    ):
        st.caption(
            "Estas asignaciones tienen el flag **'manual'** activado: "
            "el asignador NO las va a pisar mientras el toggle "
            "'Respetar ediciones manuales' esté activo. Destildá el "
            "flag de las que quieras liberar."
        )

        if not horarios_manuales:
            st.info(
                "No hay asignaciones marcadas como manuales todavía. "
                "Se marcan desde el diálogo de reasignación del "
                "cronograma por aula."
            )
            return

        # Pre-cargar datos relacionados para labels legibles.
        aula_ids = {h.aula_id for h in horarios_manuales if h.aula_id}
        com_ids_h = {h.comision_id for h in horarios_manuales}
        aulas_map = {
            a.id: a for a in session.exec(
                select(AulaDB).where(AulaDB.id.in_(aula_ids))  # type: ignore[attr-defined]
            ).all()
        } if aula_ids else {}
        coms_map = {
            c.id: c for c in session.exec(
                select(ComisionDB).where(
                    ComisionDB.id.in_(com_ids_h)  # type: ignore[attr-defined]
                )
            ).all()
        }
        mat_codes = {c.materia_codigo for c in coms_map.values()}
        mats_map = {
            m.codigo: m for m in session.exec(
                select(MateriaDB).where(
                    MateriaDB.codigo.in_(mat_codes)  # type: ignore[attr-defined]
                )
            ).all()
        } if mat_codes else {}
        sede_ids = {a.sede_id for a in aulas_map.values() if a.sede_id}
        sede_map = {
            s.id: s.nombre for s in session.exec(
                select(SedeDB).where(SedeDB.id.in_(sede_ids))  # type: ignore[attr-defined]
            ).all()
        } if sede_ids else {}

        # Sort por día + hora + materia.
        DIAS_ORDER = {
            "Lunes": 0, "Martes": 1, "Miércoles": 2,
            "Jueves": 3, "Viernes": 4, "Sábado": 5,
        }
        horarios_manuales.sort(
            key=lambda h: (
                DIAS_ORDER.get(h.dia, 99),
                h.hora_inicio,
                mats_map.get(h.codigo_materia).nombre  # type: ignore[union-attr]
                if h.codigo_materia in mats_map
                else h.codigo_materia,
            )
        )

        # Header + filas.
        col_widths = [3, 2, 2, 2, 1]
        h1, h2, h3, h4, h5 = st.columns(col_widths)
        h1.markdown("**Materia**")
        h2.markdown("**Comisión**")
        h3.markdown("**Día / Franja**")
        h4.markdown("**Aula**")
        h5.markdown("")

        for horario in horarios_manuales:
            com = coms_map.get(horario.comision_id)
            mat = mats_map.get(horario.codigo_materia)
            mat_nombre = (
                mat.nombre if mat else horario.codigo_materia
            )
            com_nombre = com.nombre if com else "?"
            aula = aulas_map.get(horario.aula_id) if horario.aula_id else None
            sede_nom = (
                sede_map.get(aula.sede_id, "?") if aula else "—"
            )
            aula_txt = (
                f"{sede_nom} · {aula.nombre}" if aula else "sin aula"
            )
            hf = (
                f"{horario.dia} "
                f"{horario.hora_inicio.strftime('%H:%M')}"
                f"–{horario.hora_fin.strftime('%H:%M')}"
            )

            c1, c2, c3, c4, c5 = st.columns(col_widths)
            c1.write(mat_nombre)
            c2.write(com_nombre)
            c3.write(hf)
            c4.write(aula_txt)
            if c5.button(
                "🔓 Liberar",
                key=f"{key_ns}_liberar_{horario.id}",
                help=(
                    "Baja el flag 'manual' de este horario. La próxima "
                    "corrida del asignador podrá reasignar esta aula."
                ),
            ):
                cambiar_aula_horario(
                    session, horario.id, horario.aula_id,
                    marcar_manual=False,
                )
                st.rerun()


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

    # Fuera del form: si el toggle "Respetar ediciones manuales" está
    # activo, mostramos la tabla de asignaciones ya marcadas como
    # manuales con controles para desmarcarlas.
    _respetar_state = st.session_state.get(f"{key_ns}_respetar", True)
    if _respetar_state:
        _render_tabla_manuales(session, plan_id, key_ns)

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
    """Renderiza el resumen del LPRunDB en métricas + nota de status.

    Se asume que el caller lo envuelve dentro del expander principal
    del "Asignador de aulas".
    """
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
        f"**{status_emoji} Estado:** {_status_humano}  \n"
        f"**🕒 Corrida:** {run.run_at.strftime('%Y-%m-%d %H:%M')}"
    )

    if run.error_message:
        st.error(run.error_message)

    c1, c2, c3, c4, c5 = st.columns(5)
    c1.metric(
        "Horarios totales", run.n_horarios_total,
        help=(
            "Cantidad total de horarios del plan que la asignación "
            "consideró. Excluye horarios virtuales (que no requieren "
            "aula por definición)."
        ),
    )
    c2.metric(
        "Asignados", run.n_horarios_asignados,
        help=(
            "Horarios a los que la asignación les encontró aula. "
            "Idealmente coincide con Horarios totales; si es menor, "
            "hay horarios sin aula (revisar el diagnóstico)."
        ),
    )
    c3.metric(
        "Horarios reasignados", run.n_horarios_reasignados,
        help=(
            "Cantidad de horarios del patrón cuya aula cambió respecto "
            "al valor previo. Un valor bajo puede significar que la "
            "asignación anterior ya era óptima, que la mayoría de los "
            "horarios están pinneados como manuales, o que los "
            "parámetros de esta corrida no afectan la solución."
        ),
    )
    c4.metric(
        "Sobre-ocupados", run.n_clases_sobreocupadas,
        help=(
            "Horarios en aulas más chicas que los inscriptos esperados "
            "(cap. < esperados, superando la tolerancia configurada). "
            "Idealmente cero."
        ),
    )
    c5.metric(
        "Sub-utilizados", run.n_clases_subutilizadas,
        help=(
            "Horarios en aulas mucho más grandes que los inscriptos "
            "esperados. No es un problema grave, pero indica margen "
            "de mejora de ajuste (aulas grandes que podrían usarse "
            "para grupos más grandes)."
        ),
    )

    c6, c7, c8 = st.columns(3)
    if run.objective_value is not None:
        c6.metric(
            "Costo total", f"{run.objective_value:.2f}",
            help=(
                "Puntaje del ajuste global calculado por la asignación: "
                "suma ponderada de la sobre-ocupación (penalizada con "
                "el peso de sobre-ocupación) y de la sub-utilización "
                "(penalizada con el peso de sub-utilización). Cuanto "
                "más bajo, mejor. Sirve para comparar corridas entre "
                "sí; el número absoluto por sí solo no dice mucho."
            ),
        )
    if run.solver_seconds is not None:
        c7.metric(
            "Tiempo de resolución (s)", f"{run.solver_seconds:.2f}",
            help=(
                "Cuánto tardó la asignación en encontrar la solución. "
                "Si se acerca al tiempo máximo configurado, la solución "
                "puede no ser óptima."
            ),
        )
    c8.metric(
        "Manuales respetadas", run.n_ediciones_manuales_respetadas,
        help=(
            "Aulas asignadas manualmente que la corrida decidió NO "
            "modificar (respetadas por el toggle 'Respetar ediciones "
            "manuales'). Si el toggle está desactivado, siempre es 0."
        ),
    )

    with st.expander("⚙️ Configuración aplicada", expanded=False):
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
    ok, problemas = _precheck(session, plan_id)
    if not ok:
        for p in problemas:
            st.error(p)
        return

    # Sugerencias antes de correr — informativas, no bloquean.
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

    latest = get_latest_run(session, plan_id)

    # ======================================================
    # Expander: Asignador de Aulas (última corrida + correr nueva)
    # ======================================================
    with st.expander("🏛️ Asignador de aulas", expanded=True):
        if latest is not None:
            _render_summary(latest)
        else:
            st.info(
                "Todavía no se ejecutó ninguna asignación para este "
                "plan. Configurá los parámetros abajo y apretá "
                "**🚀 Asignar aulas**."
            )

        with st.expander(
            "🚀 Correr la asignación (config + botón)",
            expanded=latest is None,
        ):
            st.markdown(
                "Configurá los parámetros y apretá **🚀 Asignar "
                "aulas** para correr una nueva corrida."
            )
            st.caption(
                "ℹ️ La asignación intenta encontrar un aula a cada "
                "horario presencial del plan. NO entran los horarios "
                "de materias virtuales del catálogo, dictados marcados "
                "como virtuales para el ciclo, ni horarios individuales "
                "marcados como virtuales. Si la asignación no resuelve, "
                "revisá primero en **Ciclos → 📚 Dictados** que las "
                "materias recursadas estén marcadas como virtuales."
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

    # ======================================================
    # Expander: Gestión de Asignaciones (mapa + advertencias + detalle)
    # ======================================================
    if latest is not None:
        with st.expander("🧭 Gestión de asignaciones", expanded=False):
            from src.ui.asignacion_resultado_ui import render_resultado
            render_resultado(session, latest, key_ns=f"{key_ns}_res")

    # ======================================================
    # Expander: Cronograma por aula (independiente del run)
    # ======================================================
    with st.expander("📅 Cronograma por aula", expanded=False):
        from src.ui.aula_cronograma_view import render_aula_cronograma
        render_aula_cronograma(session, plan_id, key_ns=f"{key_ns}_aula")
