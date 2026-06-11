"""UI unificada de validacion para cronograma y plan de cursada.

Punto de entrada: `render_validation(source, ...)`. Replica el panel
existente de Cronogramas → Validar pero con dos fuentes:

- `source='plan'` (B.1): opera sobre `PlanificacionCursadaDB`, comisiones
  reales, conflictos via `validar_conflictos_horarios_plan_estructurados`,
  permite ignorar conflictos y persiste snapshots en `PlanValidationDB`.
- `source='schedule'` (B.3, pendiente): mantendra la logica actual del
  cronograma con comisiones auto-derivadas.

Layout (comun a ambos sources):

1. Toggle "Excluir virtuales/optativas" + boton "Validar".
2. Pre-check (sin comisiones / sin dictados → error y return).
3. 6 metricas de cobertura.
4. Bloque de particion teoria/lab.
5. Expander "Detalle por carrera" con tabla resumen + sub-expanders
   por carrera (faltantes, no esperadas, conflictos).
6. Expander "Detalle por materia" con filtros (carrera, año, cuatri,
   tipo, lab, **estado**) + lista.
7. Activacion gate (solo plan): boton "Activar plan" deshabilitado si
   hay conflictos no ignorados.

Importante:
- Todas las keys de session_state usan el `key_ns` que recibe la funcion
  para no chocar entre paginas/tabs en el mismo run de Streamlit.
"""

from __future__ import annotations

from collections import Counter
from typing import Literal, Optional

import pandas as pd
import streamlit as st
from sqlmodel import col, func, select

from src.database.connection import get_session
from src.database.models import (
    CarreraDB,
    CicloPlanVersionDB,
    ComisionDB,
    HorarioDB,
    MateriaDB,
    PlanCarreraVersionDB,
    PlanEstudioDB,
    PlanificacionCursadaDB,
)
from src.services.cronograma_validation_service import (
    CronogramaValidationSummary,
    get_latest_validation as _crono_get_latest,
    is_validation_stale as _crono_validation_stale,
    parse_details_json as _crono_parse_details,
    persist_validation as _crono_persist_validation,
    validar_cronograma,
)
from src.services.dictado_service import set_activo_for_materias_in_ciclo
from src.services.plan_validation_service import (
    PlanValidationSummary,
    add_ignored_pair,
    get_latest_validation,
    is_validation_stale as _plan_validation_stale,
    parse_details_json as _plan_parse_details,
    persist_validation,
    remove_ignored_pair,
    validar_plan,
)


# =============================================================================
# Entrypoint
# =============================================================================

def render_validation(
    source: Literal["schedule", "plan"],
    *,
    schedule_id: Optional[str] = None,
    ciclo_id: Optional[str] = None,
    plan_id: Optional[str] = None,
    key_ns: str,
) -> None:
    """Render del panel unificado de validacion.

    Args:
        source: "schedule" → valida un cronograma vs un ciclo; "plan" →
            valida un plan de cursada (con comisiones reales).
        schedule_id, ciclo_id: requeridos si source='schedule'.
        plan_id: requerido si source='plan'.
        key_ns: namespace para keys de session_state.
    """
    if source == "plan":
        if not plan_id:
            st.error("plan_id requerido para source='plan'.")
            return
        _render_plan(plan_id=plan_id, key_ns=key_ns)
    elif source == "schedule":
        if not schedule_id or not ciclo_id:
            st.error("schedule_id + ciclo_id requeridos para source='schedule'.")
            return
        _render_schedule(
            schedule_id=schedule_id, ciclo_id=ciclo_id, key_ns=key_ns,
        )
    else:
        st.error(f"source desconocido: {source!r}")


# =============================================================================
# PLAN — entrypoint
# =============================================================================

def _render_plan(plan_id: str, key_ns: str) -> None:
    """Render del panel para un plan de cursada."""
    # Cargar plan + ciclo
    with next(get_session()) as session:
        plan = session.get(PlanificacionCursadaDB, plan_id)
    if plan is None:
        st.error(f"Plan '{plan_id}' no encontrado.")
        return

    if not plan.ciclo_id:
        st.error("El plan no tiene ciclo asignado.")
        return

    # Toggles + boton
    _toggle_key = f"{key_ns}_exclude_optativas"
    _autoval_key = f"{key_ns}_auto_validate"
    _validation_key = f"{key_ns}_validation_summary"
    _pending_revalidate_key = f"{key_ns}_pending_revalidate"

    _col_t1, _col_t2, _col_b = st.columns([3, 2, 2])
    with _col_t1:
        exclude_optativas = st.toggle(
            "Excluir optativas del cómputo",
            value=st.session_state.get(_toggle_key, False),
            key=_toggle_key,
            help=(
                "Las materias optativas no se cuentan en el set esperado. "
                "Las virtuales SÍ cuentan: estructuralmente sus comisiones "
                "y horarios deben ser consistentes (aunque no se les asigna "
                "aula al planificar)."
            ),
        )
    with _col_t2:
        auto_validate = st.toggle(
            "Auto-revalidar al cambiar",
            value=st.session_state.get(_autoval_key, True),
            key=_autoval_key,
            help=(
                "Si está ON, cualquier acción del panel (activar/desactivar "
                "dictados, ignorar conflictos, etc) re-corre la validación "
                "automáticamente. Si está OFF, vas a ver un warning de "
                "'stale' hasta que apretes Validar plan."
            ),
        )
    with _col_b:
        _run_button = st.button(
            "Validar plan", type="primary",
            key=f"{key_ns}_btn_validate",
            use_container_width=True,
        )

    # Re-prevalidar si cambio el toggle (comparado con el snapshot vivo)
    _last_toggle_key = f"{key_ns}_last_toggle"
    _toggle_changed = (
        _validation_key in st.session_state
        and st.session_state.get(_last_toggle_key) is not None
        and st.session_state[_last_toggle_key] != exclude_optativas
    )

    # Auto-revalidar pendiente: alguna accion del panel marco que hay
    # cambios pendientes; si auto_validate=True corremos ya. Si OFF,
    # dejamos la flag para mostrar el warning de stale hasta que el
    # usuario apriete el boton manualmente.
    _pending_auto = (
        auto_validate
        and st.session_state.pop(_pending_revalidate_key, False)
    )

    if _run_button or _toggle_changed or _pending_auto:
        with next(get_session()) as session:
            summary = validar_plan(
                session, plan_id, exclude_optativas=exclude_optativas,
            )
            if summary.error is None:
                # Persistir snapshot en cada validacion
                persist_validation(session, summary)
        st.session_state[_validation_key] = summary
        st.session_state[_last_toggle_key] = exclude_optativas
        if _pending_auto:
            st.toast("✓ Plan revalidado tras cambios.")

    # Si no hay summary aun, intentar recuperar el ultimo persistido
    if _validation_key not in st.session_state:
        with next(get_session()) as session:
            _last = get_latest_validation(session, plan_id)
            if _last is not None:
                # Reconstruir summary desde DB (parse details_json)
                _details = _plan_parse_details(_last.details_json)
                summary = PlanValidationSummary(
                    plan_cursada_id=_last.plan_cursada_id,
                    validated_at=_last.validated_at,
                    comision_count_at_validation=_last.comision_count_at_validation,
                    horario_count_at_validation=_last.horario_count_at_validation,
                    dictado_count_at_validation=_last.dictado_count_at_validation,
                    excluir_optativas=_last.excluir_optativas,
                    excluir_virtuales_optativas=_last.excluir_virtuales_optativas,
                    n_materias=_last.n_materias,
                    n_clases=_last.n_clases,
                    total_horas=_last.total_horas,
                    n_esperadas=_last.n_esperadas,
                    n_cubiertas=_last.n_cubiertas,
                    n_faltantes=_last.n_faltantes,
                    n_extra=_last.n_extra,
                    particion_valid=_last.particion_valid,
                    particion_n_infactibles=_last.particion_n_infactibles,
                    particion_message=_details.get("particion_message", ""),
                    n_conflictos_horarios=_last.n_conflictos_horarios,
                    n_conflictos_ignorados=_last.n_conflictos_ignorados,
                    faltantes_por_carrera=_details.get("faltantes_por_carrera", []),
                    extras=_details.get("extras", []),
                    particion_details=_details.get("particion_details", []),
                    conflictos_horarios=_details.get("conflictos_horarios", []),
                    conflictos_ignorados=_details.get("conflictos_ignorados", []),
                    esperadas=_details.get("esperadas", {}),
                    mat_map=_details.get("mat_map", {}),
                )
                st.session_state[_validation_key] = summary
                st.session_state[_last_toggle_key] = _last.excluir_optativas

    if _validation_key not in st.session_state:
        st.info(
            "Apretá **Validar plan** para correr la validacion completa "
            "(cobertura, conflictos de horarios, partición teoría/lab)."
        )
        return

    summary: PlanValidationSummary = st.session_state[_validation_key]

    # Error pre-computo
    if summary.error:
        st.error(summary.error)
        return

    # Staleness
    with next(get_session()) as session:
        _latest = get_latest_validation(session, plan_id)
        if _latest is not None:
            _stale = _plan_validation_stale(
                session, _latest,
                current_exclude_optativas=exclude_optativas,
            )
        else:
            _stale = False
    if _stale:
        st.warning(
            "El plan, sus dictados o el toggle cambiaron desde la última "
            "validación. Apretá **Validar plan** para actualizar."
        )

    # =====================================================================
    # Resumen de cobertura
    # =====================================================================
    st.divider()
    st.markdown("### Resumen de cobertura")
    _c1, _c2, _c3, _c4, _c5, _c6 = st.columns(6)
    _c1.metric("Materias", summary.n_materias)
    _c2.metric("Clases", summary.n_clases)
    _c3.metric("Horas plan", f"{summary.total_horas:.1f}")
    _c4.metric(
        "Esperadas",
        summary.n_esperadas,
        delta=(
            None if not summary.excluir_optativas
            else "(optativas excluidas)"
        ),
        delta_color="off",
    )
    _c5.metric("Cubiertas", f"{summary.n_cubiertas}/{summary.n_esperadas}")
    _c6.metric("Faltantes", summary.n_faltantes)

    # =====================================================================
    # Particion teoria/lab
    # =====================================================================
    if summary.particion_valid:
        st.success(summary.particion_message or "Partición teoría/lab OK.")
    else:
        st.error(summary.particion_message or "Partición teoría/lab inválida.")
        if summary.particion_details:
            with st.expander(
                f"Detalles de partición ({summary.particion_n_infactibles})",
                expanded=False,
            ):
                for d in summary.particion_details:
                    st.text(f"  - {d}")

    # =====================================================================
    # Detalle por carrera
    # =====================================================================
    _grupos = _build_grupos_por_carrera(summary, plan.ciclo_id)
    # Mapa global codigo→nombre que cubre TODAS las materias mencionadas
    # (faltantes + extras + conflictos + materias del plan + esperadas).
    _full_mat_map = _build_full_mat_map(summary, _grupos)
    _has_issues = any(
        len(g["faltantes"]) > 0 or len(g["extras"]) > 0
        or len(g["conflictos"]) > 0
        or len(g.get("conflictos_ignorados", [])) > 0
        for g in _grupos.values()
    )

    with st.expander(
        f"📋 Detalle por carrera ({len(_grupos)} grupo(s))",
        expanded=_has_issues,
    ):
        if not _grupos:
            st.caption("Sin discrepancias por carrera.")
        else:
            _render_resumen_carreras(_grupos)
            for _cc in sorted(_grupos.keys()):
                _g = _grupos[_cc]
                if (
                    len(_g["faltantes"]) == 0
                    and len(_g["extras"]) == 0
                    and len(_g["conflictos"]) == 0
                    and len(_g.get("conflictos_ignorados", [])) == 0
                ):
                    continue
                _render_carrera_subexpander(
                    _g, ciclo_id=plan.ciclo_id,
                    key_ns=key_ns, mat_map=_full_mat_map,
                    invalidate_cache_keys=[
                        _validation_key, _last_toggle_key,
                    ],
                    pending_revalidate_key=_pending_revalidate_key,
                    source="plan", plan_id=plan_id,
                )

    # =====================================================================
    # Detalle por materia
    # =====================================================================
    with st.expander("🔎 Detalle por materia", expanded=False):
        _render_detalle_por_materia(
            summary=summary, key_ns=key_ns,
            source="plan", plan_id=plan_id, ciclo_id=plan.ciclo_id,
            pending_revalidate_key=_pending_revalidate_key,
            invalidate_cache_keys=[
                _validation_key, _last_toggle_key,
            ],
        )

    # =====================================================================
    # Activacion gate
    # =====================================================================
    st.divider()
    _has_blocker = summary.n_conflictos_horarios > 0
    if _has_blocker:
        st.error(
            f"No se puede activar el plan: hay {summary.n_conflictos_horarios} "
            f"conflicto(s) bloqueante(s) sin ignorar. Resolvelos o marcalos "
            f"como ignorados (con razón) y volvé a validar."
        )
    elif not plan.activo:
        if st.button(
            "Activar plan", type="primary",
            key=f"{key_ns}_btn_activate",
        ):
            from src.services.plan_generation_service import activate_plan
            with next(get_session()) as _as:
                activate_plan(_as, plan_id)
            st.success(f"Plan '{plan.nombre}' activado.")
            st.rerun()
    else:
        st.success(f"Plan '{plan.nombre}' está activo.")


# =============================================================================
# Helpers — formato y mapas
# =============================================================================

def _request_edit_materia(key_ns: str, codigo: str) -> None:
    """Marca una materia como 'pre-seleccionada' para el editor inline
    del bloque "Detalle por materia". Lo consume el selectbox al
    re-renderear la pagina (debe ir seguido de st.rerun()).

    El `key_ns` debe ser el mismo que recibe `_render_plan` (no el de
    los sub-renderers de discrepancias/conflictos, que tienen prefijos
    propios).
    """
    st.session_state[f"{key_ns}_dpm_pending_codigo"] = codigo


def _label_codnom(codigo: str, mat_map: dict[str, str]) -> str:
    """Devuelve 'CÓD — Nombre' si hay nombre, sino solo el código."""
    nom = mat_map.get(codigo)
    if nom and nom != "?":
        return f"{codigo} — {nom}"
    return codigo


def _build_full_mat_map(
    summary, grupos: dict[str, dict],
) -> dict[str, str]:
    """Mapa global código→nombre que cubre faltantes, extras, conflictos
    y materias del plan / esperadas. Usado para mostrar nombres junto a
    códigos en todas las tablas y selectboxes.

    Acepta tanto `PlanValidationSummary` como `CronogramaValidationSummary`.
    """
    m = dict(summary.mat_map)  # materias del plan
    for code, name in summary.esperadas.items():
        m.setdefault(code, name)
    for g in grupos.values():
        for f in g["faltantes"]:
            m.setdefault(f["codigo"], f.get("nombre") or "?")
        for e in g["extras"]:
            m.setdefault(e["codigo"], e.get("nombre") or "?")
    return m


# =============================================================================
# Helpers — Detalle por carrera
# =============================================================================

def _build_grupos_por_carrera(
    summary, ciclo_id: Optional[str],
) -> dict[str, dict]:
    """Construye dict por carrera con faltantes + extras + conflictos.

    Funciona tanto para `PlanValidationSummary` como para
    `CronogramaValidationSummary`: ambos tienen los mismos campos
    relevantes (faltantes_por_carrera, extras, conflictos_horarios,
    mat_map). El de cronograma no tiene `conflictos_ignorados`; lo
    tratamos como lista vacia.

    Las extras llegan como lista plana en summary.extras (sin carrera).
    Para ubicarlas por carrera consultamos PlanEstudioDB del ciclo.
    """
    grupos: dict[str, dict] = {}

    # Faltantes ya vienen agrupados
    for fp in summary.faltantes_por_carrera:
        grupos[fp["carrera_codigo"]] = {
            "carrera_codigo": fp["carrera_codigo"],
            "carrera_nombre": fp["carrera_nombre"],
            "plan_version_nombre": fp.get("plan_version_nombre", ""),
            "dicta_recursado": fp.get("dicta_recursado", False),
            "faltantes": fp["materias"],
            "extras": [],
            "conflictos": [],
            "conflictos_ignorados": [],
        }

    # Extras: pedir PE rows para asociarlos a carrera
    if summary.extras and ciclo_id:
        _extra_codes = [e["codigo"] for e in summary.extras]
        with next(get_session()) as session:
            if True:
                _mats_full = list(session.exec(
                    select(MateriaDB).where(col(MateriaDB.codigo).in_(_extra_codes))
                ).all())
                _mat_full_map = {m.codigo: m for m in _mats_full}
                _ext_pe = list(session.exec(
                    select(PlanEstudioDB)
                    .join(
                        PlanCarreraVersionDB,
                        PlanEstudioDB.plan_version_id == PlanCarreraVersionDB.id,  # type: ignore[arg-type]
                    )
                    .join(
                        CicloPlanVersionDB,
                        PlanCarreraVersionDB.id == CicloPlanVersionDB.plan_version_id,  # type: ignore[arg-type]
                    )
                    .where(CicloPlanVersionDB.ciclo_id == ciclo_id)
                    .where(col(PlanEstudioDB.materia_codigo).in_(_extra_codes))
                ).all())

                _by_carr: dict[str, list[dict]] = {}
                _seen: set[tuple[str, str]] = set()
                for _pe in _ext_pe:
                    _key = (_pe.carrera_codigo, _pe.materia_codigo)
                    if _key in _seen:
                        continue
                    _seen.add(_key)
                    _m_obj = _mat_full_map.get(_pe.materia_codigo)
                    _by_carr.setdefault(_pe.carrera_codigo, []).append({
                        "codigo": _pe.materia_codigo,
                        "nombre": _m_obj.nombre if _m_obj else "?",
                        "anio_plan": _pe.anio_plan,
                        "cuatrimestre_plan": _pe.cuatrimestre_plan,
                        "optativa": bool(_pe.optativa),
                        "virtual": bool(_m_obj.virtual) if _m_obj else False,
                        "periodo": _m_obj.periodo if _m_obj else "cuatrimestral",
                    })

                for _cc, _ms in _by_carr.items():
                    if _cc in grupos:
                        grupos[_cc]["extras"] = _ms
                    else:
                        _carr = session.get(CarreraDB, _cc)
                        grupos[_cc] = {
                            "carrera_codigo": _cc,
                            "carrera_nombre": _carr.nombre if _carr else _cc,
                            "plan_version_nombre": "",
                            "dicta_recursado": False,
                            "faltantes": [],
                            "extras": _ms,
                            "conflictos": [],
                            "conflictos_ignorados": [],
                        }

                # Sin carrera asignada
                _np_codes = set(_extra_codes) - {
                    m["codigo"] for ms in _by_carr.values() for m in ms
                }
                if _np_codes:
                    _np_list = []
                    for _mc in sorted(_np_codes):
                        _m_obj = _mat_full_map.get(_mc)
                        _np_list.append({
                            "codigo": _mc,
                            "nombre": _m_obj.nombre if _m_obj else "?",
                            "anio_plan": None,
                            "cuatrimestre_plan": None,
                            "optativa": False,
                            "virtual": bool(_m_obj.virtual) if _m_obj else False,
                            "periodo": _m_obj.periodo if _m_obj else "cuatrimestral",
                        })
                    grupos["—"] = {
                        "carrera_codigo": "—",
                        "carrera_nombre": "Sin carrera asignada",
                        "plan_version_nombre": "",
                        "dicta_recursado": False,
                        "faltantes": [],
                        "extras": _np_list,
                        "conflictos": [],
                        "conflictos_ignorados": [],
                    }

    # Conflictos (activos e ignorados) por carrera
    def _ensure_grupo(cc: str) -> None:
        if cc not in grupos:
            with next(get_session()) as _s:
                _carr = _s.get(CarreraDB, cc)
            grupos[cc] = {
                "carrera_codigo": cc,
                "carrera_nombre": _carr.nombre if _carr else cc,
                "plan_version_nombre": "",
                "dicta_recursado": False,
                "faltantes": [],
                "extras": [],
                "conflictos": [],
                "conflictos_ignorados": [],
            }

    for c in summary.conflictos_horarios:
        _cc = c["carrera_codigo"]
        _ensure_grupo(_cc)
        grupos[_cc]["conflictos"].append(c)

    # CronogramaValidationSummary no tiene conflictos_ignorados (no aplica
    # acá: no hay IgnoredConflictDB para cronograma).
    for c in getattr(summary, "conflictos_ignorados", []):
        _cc = c["carrera_codigo"]
        _ensure_grupo(_cc)
        grupos[_cc]["conflictos_ignorados"].append(c)

    return grupos


def _render_resumen_carreras(grupos: dict[str, dict]) -> None:
    """Tabla resumen de issues por carrera."""
    _rows = []
    for _cc in sorted(grupos.keys()):
        _g = grupos[_cc]
        _rows.append({
            "Carrera": f"{_g['carrera_codigo']} — {_g['carrera_nombre']}",
            "Faltantes": len(_g["faltantes"]),
            "No esperadas": len(_g["extras"]),
            "Conflictos": len(_g["conflictos"]),
        })
    if not _rows:
        return
    _df = pd.DataFrame(_rows)
    # Total al pie
    _total = pd.DataFrame([{
        "Carrera": "**Total**",
        "Faltantes": _df["Faltantes"].sum(),
        "No esperadas": _df["No esperadas"].sum(),
        "Conflictos": _df["Conflictos"].sum(),
    }])
    st.markdown("**Resumen por carrera**")
    st.dataframe(
        pd.concat([_df, _total], ignore_index=True),
        use_container_width=True, hide_index=True,
    )


def _render_carrera_subexpander(
    g: dict, ciclo_id: str, key_ns: str,
    mat_map: dict[str, str],
    invalidate_cache_keys: list[str],
    pending_revalidate_key: str,
    source: Literal["plan", "schedule"] = "plan",
    plan_id: Optional[str] = None,
) -> None:
    """Sub-expander por carrera con discrepancias + conflictos.

    Si source='schedule', omite el shortcut "Editar materia" (el editor
    real vive en el tab Editar de la pagina de Cronogramas) y la opcion
    de "Ignorar conflicto" (no hay IgnoredConflictDB para cronograma:
    los conflictos del cronograma se resuelven editando los entries).
    """
    _cc = g["carrera_codigo"]
    _n_fc = len(g["faltantes"])
    _n_ec = len(g["extras"])
    _n_conf = len(g["conflictos"])
    _n_ign = len(g.get("conflictos_ignorados", []))

    _conf_part = f" · ⚠️ {_n_conf} conflicto(s)" if _n_conf else ""
    _ign_part = f" · 🙈 {_n_ign} ignorado(s)" if _n_ign else ""
    _exp_lbl = (
        f"{g['carrera_nombre']} ({_cc}) — "
        f"📭 {_n_fc} faltante(s) · 📥 {_n_ec} no esperada(s)"
        f"{_conf_part}{_ign_part}"
    )
    with st.expander(_exp_lbl, expanded=False):
        # Discrepancias de dictado
        if _n_fc or _n_ec:
            with st.expander(
                f"📋 Discrepancias de dictado (📭 {_n_fc} · 📥 {_n_ec})",
                expanded=True,
            ):
                if g["faltantes"]:
                    st.markdown(f"**Faltantes ({_n_fc})**")
                    _ft_rows = []
                    for _mf in g["faltantes"]:
                        _anio = (
                            f"{_mf['anio_plan']}°" if _mf["anio_plan"] else "—"
                        )
                        _cuatri = _mf["cuatrimestre_plan"] or "—"
                        _hsem = _mf.get("horas_semanales")
                        _ft_rows.append({
                            "Código": _mf["codigo"],
                            "Nombre": _mf["nombre"],
                            "Año": _anio,
                            "Cuatri": _cuatri,
                            "h/sem": f"{_hsem:g}" if _hsem else "—",
                            "Optativa": "Sí" if _mf.get("optativa") else "—",
                            "Virtual": "Sí" if _mf.get("virtual") else "—",
                            "Anual": (
                                "Sí" if _mf.get("periodo") == "anual" else "—"
                            ),
                            "Dictado": _mf.get("dictado_codigo", "—"),
                        })
                    st.dataframe(
                        pd.DataFrame(_ft_rows),
                        use_container_width=True, hide_index=True,
                    )
                    if source == "plan":
                        _render_edit_materia_selector(
                            materias=g["faltantes"], carrera_codigo=_cc,
                            slot="faltantes", key_ns=key_ns,
                            mat_map=mat_map,
                        )
                    _render_dictado_action_selector(
                        materias=g["faltantes"],
                        action="deactivate", carrera_codigo=_cc,
                        ciclo_id=ciclo_id, key_ns=key_ns,
                        invalidate_cache_keys=invalidate_cache_keys,
                        pending_revalidate_key=pending_revalidate_key,
                        mat_map=mat_map,
                    )

                if g["extras"]:
                    st.markdown(
                        f"**No esperadas — comisiones sin dictado activo "
                        f"({_n_ec})**"
                    )
                    _ex_rows = []
                    for _ex in g["extras"]:
                        _anio = (
                            f"{_ex['anio_plan']}°"
                            if _ex.get("anio_plan") else "—"
                        )
                        _cuatri = _ex.get("cuatrimestre_plan") or "—"
                        _ex_rows.append({
                            "Código": _ex["codigo"],
                            "Nombre": _ex["nombre"],
                            "Año": _anio,
                            "Cuatri": _cuatri,
                            "Optativa": "Sí" if _ex.get("optativa") else "—",
                            "Virtual": "Sí" if _ex.get("virtual") else "—",
                            "Anual": (
                                "Sí" if _ex.get("periodo") == "anual" else "—"
                            ),
                        })
                    st.dataframe(
                        pd.DataFrame(_ex_rows),
                        use_container_width=True, hide_index=True,
                    )
                    if source == "plan":
                        _render_edit_materia_selector(
                            materias=g["extras"], carrera_codigo=_cc,
                            slot="extras", key_ns=key_ns,
                            mat_map=mat_map,
                        )
                    _render_dictado_action_selector(
                        materias=g["extras"],
                        action="activate", carrera_codigo=_cc,
                        ciclo_id=ciclo_id, key_ns=key_ns,
                        invalidate_cache_keys=invalidate_cache_keys,
                        pending_revalidate_key=pending_revalidate_key,
                        mat_map=mat_map,
                    )

        # Conflictos de horarios (activos + ignorados)
        if g["conflictos"] or g.get("conflictos_ignorados"):
            _hdr = f"⚠️ Conflictos de horarios ({_n_conf}"
            if _n_ign:
                _hdr += f" · 🙈 {_n_ign} ignorado(s)"
            _hdr += ")"
            with st.expander(_hdr, expanded=bool(g["conflictos"])):
                _render_conflictos_carrera(
                    activos=g["conflictos"],
                    ignorados=g.get("conflictos_ignorados", []),
                    carrera_codigo=_cc, plan_id=plan_id, key_ns=key_ns,
                    mat_map=mat_map,
                    invalidate_cache_keys=invalidate_cache_keys,
                    pending_revalidate_key=pending_revalidate_key,
                    source=source,
                )


def _render_edit_materia_selector(
    *, materias: list[dict], carrera_codigo: str, slot: str, key_ns: str,
    mat_map: dict[str, str],
) -> None:
    """Selector + boton "Editar materia" que pre-popula el detalle inline.

    Al apretar, setea el buffer key consumido por el selector "Materia
    activa" en `_render_detalle_por_materia` y dispara rerun. La materia
    se abre en el editor inline (incluyendo calendario) aunque no
    matchee los filtros vigentes.

    Args:
        slot: identificador para evitar colisiones de keys cuando hay
            multiples selectores en la misma carrera ('faltantes',
            'extras', 'conflicto-A', 'conflicto-B').
    """
    if not materias:
        return

    _options = {
        _label_codnom(_m["codigo"], mat_map): _m["codigo"]
        for _m in materias
    }
    _all_labels = list(_options.keys())

    _sel_key = f"{key_ns}_em_sel_{slot}_{carrera_codigo}"
    _btn_key = f"{key_ns}_em_btn_{slot}_{carrera_codigo}"

    _ec1, _ec2 = st.columns([3, 1])
    with _ec1:
        _lbl = st.selectbox(
            "Editar materia (abre el editor inline abajo)",
            options=_all_labels,
            key=_sel_key,
            label_visibility="collapsed",
        )
    with _ec2:
        if st.button(
            "✏️ Editar materia", key=_btn_key, use_container_width=True,
        ):
            _request_edit_materia(key_ns, _options[_lbl])
            st.rerun()


def _render_dictado_action_selector(
    *, materias: list[dict], action: Literal["activate", "deactivate"],
    carrera_codigo: str, ciclo_id: str, key_ns: str,
    invalidate_cache_keys: list[str],
    pending_revalidate_key: str,
    mat_map: dict[str, str],
) -> None:
    """Selector multi + boton para activar o desactivar dictados en bulk.

    `action='deactivate'` aplica a faltantes (sacarlas del set esperado);
    `action='activate'` aplica a extras (incorporarlas como esperadas).
    El selector ofrece tildar todas con un toggle previo.
    """
    if not materias:
        return

    _options = {
        _label_codnom(_m["codigo"], mat_map): _m["codigo"]
        for _m in materias
    }
    _all_labels = list(_options.keys())

    _verbo = "Desactivar" if action == "deactivate" else "Activar"
    _prefix = "deact" if action == "deactivate" else "act"
    _help = (
        "Marca como Inactivo el dictado de las materias elegidas. "
        "Salen del set de esperadas (no aparecen mas como faltantes)."
        if action == "deactivate"
        else "Activa el dictado de las materias elegidas (creandolo si "
             "no existe). Pasan a contarse como esperadas."
    )

    _sel_key = f"{key_ns}_dict_sel_{_prefix}_{carrera_codigo}"
    _btn_key = f"{key_ns}_dict_btn_{_prefix}_{carrera_codigo}"
    _all_btn_key = f"{key_ns}_dict_all_{_prefix}_{carrera_codigo}"
    _clr_btn_key = f"{key_ns}_dict_clr_{_prefix}_{carrera_codigo}"

    # Botones para tildar/destildar TODAS, antes de instanciar el multiselect
    # (no podemos modificar `_sel_key` despues de que el widget se instancie).
    _bcol1, _bcol2, _bcol3 = st.columns([1, 1, 3])
    with _bcol1:
        if st.button(
            f"☑️ Todas ({len(_all_labels)})",
            key=_all_btn_key, use_container_width=True,
        ):
            st.session_state[_sel_key] = list(_all_labels)
            st.rerun()
    with _bcol2:
        if st.button(
            "🚫 Ninguna", key=_clr_btn_key, use_container_width=True,
        ):
            st.session_state[_sel_key] = []
            st.rerun()

    _sel_labels = st.multiselect(
        f"{_verbo} dictados de:",
        options=_all_labels,
        key=_sel_key,
        help=_help,
    )

    if _sel_labels:
        # Para "activate" ofrecemos dos botones: presencial y virtual.
        # Para "deactivate" sigue siendo un único botón.
        _codes = [_options[lbl] for lbl in _sel_labels]

        def _aplicar_bulk(activo: bool, marcar_virtual: Optional[bool]) -> None:
            with next(get_session()) as _ds:
                _n = set_activo_for_materias_in_ciclo(
                    _ds, ciclo_id, _codes, activo=activo,
                    marcar_virtual=marcar_virtual,
                )
            for _k in invalidate_cache_keys:
                st.session_state.pop(_k, None)
            # El bulk modificó DB sin pasar por los toggles del panel
            # de Ciclos → Dictados (que es otra página). Si el usuario
            # después abre esa página, los checkboxes podrían mostrar
            # valores viejos del session_state. Marcamos resync
            # pendiente para que el panel de Ciclos los re-sincronice
            # con DB en su próximo render.
            st.session_state["dict_resync_pending"] = True
            st.session_state[pending_revalidate_key] = True
            if activo and marcar_virtual:
                _msg = f"{_n} dictado(s) activado(s) como virtual(es)."
            elif activo:
                _msg = f"{_n} dictado(s) activado(s)."
            else:
                _msg = f"{_n} dictado(s) desactivado(s)."
            st.toast(_msg)
            st.rerun()

        if action == "activate":
            st.caption(
                "**Activar** marca el dictado como esperado y presencial. "
                "**Activar y marcar virtual** lo marca como esperado pero "
                "**virtual sólo en este ciclo** (modalidad puntual): el LP "
                "de asignación de aulas lo ignorará. Útil para recursados "
                "u ofertas por Zoom."
            )
            _bcol_a, _bcol_v = st.columns(2)
            with _bcol_a:
                if st.button(
                    f"🟢 Activar {len(_sel_labels)} dictado(s)",
                    key=_btn_key, type="primary",
                    use_container_width=True,
                ):
                    _aplicar_bulk(activo=True, marcar_virtual=False)
            with _bcol_v:
                if st.button(
                    f"🌐 Activar y marcar virtual ({len(_sel_labels)})",
                    key=f"{_btn_key}_virtual",
                    use_container_width=True,
                    help=(
                        "Marca los dictados como activos y virtuales "
                        "sólo para este ciclo. La materia en el catálogo "
                        "no se modifica."
                    ),
                ):
                    _aplicar_bulk(activo=True, marcar_virtual=True)
        else:
            if st.button(
                f"⚪ {_verbo} {len(_sel_labels)} dictado(s)",
                key=_btn_key, type="primary",
            ):
                _aplicar_bulk(activo=False, marcar_virtual=None)


def _render_resolve_conflicto(
    *, activos: list[dict], carrera_codigo: str,
    plan_id: str, key_ns: str, mat_map: dict[str, str],
) -> None:
    """Para conflictos activos: selector de par + 2 botones (Editar A /
    Editar B) + calendario read-only del par seleccionado.

    Foco: que el usuario pueda saltar al editor inline (B.2.6.2) de una
    de las dos materias en conflicto sin perder contexto, y vea cómo se
    superponen graficamente.
    """
    if not activos:
        return

    st.markdown("**🛠️ Resolver conflicto**")
    st.caption(
        "Elegí un par y abrí el editor de una de las dos materias. "
        "El editor inline aparece más abajo en 'Detalle por materia'."
    )

    _pair_options: dict[str, dict] = {}
    for c in activos:
        _lbl = (
            f"{_label_codnom(c['materia_a'], mat_map)}  vs  "
            f"{_label_codnom(c['materia_b'], mat_map)} · "
            f"{c['dia']} {c['hora_inicio_a']}-{c['hora_fin_a']}"
        )
        _pair_options[_lbl] = c

    _sel_key = f"{key_ns}_resolve_pair_{carrera_codigo}"
    _selected_lbl = st.selectbox(
        "Conflicto",
        options=list(_pair_options.keys()),
        key=_sel_key,
    )
    _conf = _pair_options[_selected_lbl]
    _mat_a, _mat_b = _conf["materia_a"], _conf["materia_b"]

    _ca, _cb = st.columns(2)
    with _ca:
        if st.button(
            f"✏️ Editar {_label_codnom(_mat_a, mat_map)}",
            key=f"{key_ns}_resolve_edit_a_{carrera_codigo}",
            use_container_width=True,
        ):
            _request_edit_materia(key_ns, _mat_a)
            st.rerun()
    with _cb:
        if st.button(
            f"✏️ Editar {_label_codnom(_mat_b, mat_map)}",
            key=f"{key_ns}_resolve_edit_b_{carrera_codigo}",
            use_container_width=True,
        ):
            _request_edit_materia(key_ns, _mat_b)
            st.rerun()

    # Calendario read-only del par
    with next(get_session()) as _cal_sess:
        _cal_plan = _cal_sess.get(PlanificacionCursadaDB, plan_id)
        if _cal_plan and _cal_plan.ciclo_id:
            from src.database.crud import get_or_create_config as _gc
            from src.services.plan_generation_service import (
                build_timetable_grid as _btg,
            )
            _cal_config = _gc(_cal_sess)
            _grid = _btg(
                _cal_sess, plan_id, _cal_config,
                filtered_materia_codigos={_mat_a, _mat_b},
                ciclo_id=_cal_plan.ciclo_id,
            )
        else:
            _grid = {}
            _cal_config = None
    if _grid and _cal_config is not None:
        from src.ui.calendar_render import render_timetable_calendar
        st.markdown("**🗓️ Vista calendario del conflicto (read-only)**")
        render_timetable_calendar(
            _grid, _cal_config,
            key=f"{key_ns}_resolve_cal_{carrera_codigo}_{_mat_a}_{_mat_b}",
        )
        st.caption(
            "Para editar los horarios de cualquiera de las dos materias, "
            "apretá uno de los botones de arriba. El editor inline aparece "
            "abajo en **🔎 Detalle por materia**."
        )


def _render_conflictos_carrera(
    *, activos: list[dict], ignorados: list[dict],
    carrera_codigo: str,
    plan_id: Optional[str], key_ns: str,
    mat_map: dict[str, str],
    invalidate_cache_keys: list[str],
    pending_revalidate_key: str,
    source: Literal["plan", "schedule"] = "plan",
) -> None:
    """Conflictos activos + ignorados de una carrera.

    Para `source='schedule'`: omite el bloque "Resolver conflicto"
    (shortcut al editor inline) y "Ignorar conflicto" (no aplica:
    los conflictos del cronograma se resuelven editando los entries).
    """
    if activos:
        if source == "plan":
            st.caption(
                "Conflictos detectados con las **comisiones reales del plan**. "
                "Si sabés que un par no es un conflicto real (ej: docentes "
                "distintos, materia virtual con misma aula), podés marcarlo "
                "como ignorado."
            )
        else:
            st.caption(
                "Conflictos detectados con las **comisiones auto-derivadas** "
                "del cronograma. Para resolverlos, editar los horarios "
                "afectados desde el tab **Editar** de Cronogramas."
            )

        # Resumen por (anio, cuatri)
        _resumen = Counter()
        for c in activos:
            _resumen[(c["anio_plan"], c["cuatrimestre_plan"])] += 1
        _rs_rows = [
            {"Año": f"{a}°", "Cuatri": cu, "Conflictos": n}
            for (a, cu), n in sorted(_resumen.items())
        ]
        st.markdown("**Resumen por año y cuatri**")
        st.dataframe(
            pd.DataFrame(_rs_rows),
            use_container_width=True, hide_index=True,
        )

        # Detalle
        _conf_rows = [
            {
                "Año": f"{c['anio_plan']}°",
                "Cuatri": c["cuatrimestre_plan"],
                "Materia A": _label_codnom(c["materia_a"], mat_map),
                "Materia B": _label_codnom(c["materia_b"], mat_map),
                "Día": c["dia"],
                "Horario A": f"{c['hora_inicio_a']}-{c['hora_fin_a']}",
                "Horario B": f"{c['hora_inicio_b']}-{c['hora_fin_b']}",
            }
            for c in activos
        ]
        st.markdown(f"**Detalle ({len(activos)})**")
        st.dataframe(
            pd.DataFrame(_conf_rows),
            use_container_width=True, hide_index=True,
        )

        # Resolver conflicto + Ignorar: solo aplica para plan.
        if source != "plan" or not plan_id:
            return  # schedule no soporta resolver ni ignorar
        _render_resolve_conflicto(
            activos=activos, carrera_codigo=carrera_codigo,
            plan_id=plan_id, key_ns=key_ns, mat_map=mat_map,
        )

        st.markdown("**Ignorar conflicto**")
        _pair_options = {
            f"{_label_codnom(c['materia_a'], mat_map)}  vs  "
            f"{_label_codnom(c['materia_b'], mat_map)} · "
            f"{c['dia']} {c['hora_inicio_a']}-{c['hora_fin_a']}": (
                c["materia_a"], c["materia_b"]
            )
            for c in activos
        }
        _ig_col1, _ig_col2 = st.columns([3, 2])
        with _ig_col1:
            _selected_lbl = st.selectbox(
                "Conflicto",
                options=list(_pair_options.keys()),
                key=f"{key_ns}_ign_pair_{carrera_codigo}",
            )
        with _ig_col2:
            _razon = st.text_input(
                "Razón (opcional)",
                key=f"{key_ns}_ign_razon_{carrera_codigo}",
                placeholder="ej: docentes distintos, mismo aula virtual",
            )
        if st.button(
            "Marcar como ignorado",
            key=f"{key_ns}_ign_btn_{carrera_codigo}",
        ):
            _mat_a, _mat_b = _pair_options[_selected_lbl]
            with next(get_session()) as _is:
                add_ignored_pair(_is, plan_id, _mat_a, _mat_b, razon=_razon)
            for _k in invalidate_cache_keys:
                st.session_state.pop(_k, None)
            st.session_state[pending_revalidate_key] = True
            st.toast(
                f"Conflicto {_mat_a} vs {_mat_b} marcado como ignorado."
            )
            st.rerun()

    # Bloque de IGNORADOS — solo para plan (schedule no tiene ignorados)
    if ignorados and source == "plan" and plan_id:
        if activos:
            st.divider()
        st.markdown(f"**🙈 Conflictos ignorados ({len(ignorados)})**")
        st.caption(
            "Estos conflictos fueron marcados como ignorados. No bloquean "
            "la activación del plan, pero acá podés ver el detalle y "
            "quitarlos de la lista si querés que vuelvan a contarse."
        )

        # Tabla detalle
        _ign_rows = [
            {
                "Año": f"{c['anio_plan']}°",
                "Cuatri": c["cuatrimestre_plan"],
                "Materia A": _label_codnom(c["materia_a"], mat_map),
                "Materia B": _label_codnom(c["materia_b"], mat_map),
                "Día": c["dia"],
                "Horario A": f"{c['hora_inicio_a']}-{c['hora_fin_a']}",
                "Horario B": f"{c['hora_inicio_b']}-{c['hora_fin_b']}",
            }
            for c in ignorados
        ]
        st.dataframe(
            pd.DataFrame(_ign_rows),
            use_container_width=True, hide_index=True,
        )

        # Selector + boton para quitar de ignorados (deduplicado por par)
        _seen_pairs: set[tuple[str, str]] = set()
        _unign_options: dict[str, tuple[str, str]] = {}
        for c in ignorados:
            _pair = (c["materia_a"], c["materia_b"])
            if _pair in _seen_pairs:
                continue
            _seen_pairs.add(_pair)
            _lbl = (
                f"{_label_codnom(c['materia_a'], mat_map)}  vs  "
                f"{_label_codnom(c['materia_b'], mat_map)}"
            )
            _unign_options[_lbl] = _pair

        _unign_lbl = st.selectbox(
            "Quitar de ignorados",
            options=list(_unign_options.keys()),
            key=f"{key_ns}_unign_pair_{carrera_codigo}",
        )
        if st.button(
            "Dejar de ignorar",
            key=f"{key_ns}_unign_btn_{carrera_codigo}",
        ):
            _mat_a, _mat_b = _unign_options[_unign_lbl]
            with next(get_session()) as _us:
                remove_ignored_pair(_us, plan_id, _mat_a, _mat_b)
            for _k in invalidate_cache_keys:
                st.session_state.pop(_k, None)
            st.session_state[pending_revalidate_key] = True
            st.toast(
                f"Conflicto {_mat_a} vs {_mat_b} quitado de ignorados."
            )
            st.rerun()


# =============================================================================
# Helpers — Detalle por materia
# =============================================================================

def _estado_de_materia(data: dict) -> str:
    """Devuelve un estado descriptivo para una materia del plan.

    Categorias:
    - "Faltante": esperada pero sin comisiones
    - "No esperada": tiene comisiones pero sin dictado activo
    - "Conflictiva": con comisiones y conflictos sin ignorar
    - "Sin datos": esperada con dictado pero falta info de horas
    - "OK": cubierta sin issues
    """
    if data.get("es_faltante"):
        return "Faltante"
    if data.get("es_no_esperada"):
        return "No esperada"
    if data.get("tiene_conflicto"):
        return "Conflictiva"
    if data.get("falta_horas"):
        return "Sin datos"
    return "OK"


def _compute_live_fingerprint(
    *,
    source: Literal["plan", "schedule"],
    plan_id: Optional[str],
    schedule_id: Optional[str],
) -> tuple:
    """Fingerprint del estado vivo en DB. Si cambia entre renders,
    significa que algo se edito y hay que revalidar."""
    with next(get_session()) as session:
        if source == "plan" and plan_id:
            n_com = session.exec(
                select(func.count(ComisionDB.id))
                .where(ComisionDB.plan_cursada_id == plan_id)
            ).one()
            com_ids = list(session.exec(
                select(ComisionDB.id)
                .where(ComisionDB.plan_cursada_id == plan_id)
            ).all())
            n_h = 0
            if com_ids:
                n_h = session.exec(
                    select(func.count(HorarioDB.id))
                    .where(col(HorarioDB.comision_id).in_(com_ids))
                ).one()
            return ("plan", n_com, n_h)
        elif source == "schedule" and schedule_id:
            from src.database.models import ScheduleEntryDB as _SE
            n_e = session.exec(
                select(func.count(_SE.id))
                .where(_SE.schedule_id == schedule_id)
            ).one()
            return ("schedule", n_e)
    return ("none",)


def _compute_summary_fingerprint(
    summary, *, source: Literal["plan", "schedule"],
) -> tuple:
    """Fingerprint equivalente al `_compute_live_fingerprint` pero
    derivado del summary cacheado. Si difieren, hubo cambios en DB
    que el summary no refleja."""
    if source == "plan":
        return (
            "plan",
            getattr(summary, "comision_count_at_validation", 0),
            getattr(summary, "horario_count_at_validation", 0),
        )
    elif source == "schedule":
        return (
            "schedule",
            getattr(summary, "entry_count_at_validation", 0),
        )
    return ("none",)


def _render_detalle_por_materia(
    summary, key_ns: str,
    *,
    source: Literal["plan", "schedule"] = "plan",
    plan_id: Optional[str] = None,
    schedule_id: Optional[str] = None,
    ciclo_id: Optional[str] = None,
    save_as_copy: bool = False,
    pending_revalidate_key: Optional[str] = None,
    invalidate_cache_keys: Optional[list[str]] = None,
) -> None:
    """Lista filtrada de materias + esperadas con su estado.

    Sirve tanto para `source='plan'` (con editor inline + calendario) como
    para `source='schedule'` (solo lista, sin editor). En el caso del
    cronograma las "comisiones" se cuentan a nivel de `ScheduleEntryDB`
    (cantidad de entries únicas por materia).
    """
    # Detectar si las entries/comisiones cambiaron en DB respecto del
    # snapshot del summary cacheado. Si cambiaron → marcar pending y
    # rerun para que el panel padre re-corra validar_* al inicio del
    # proximo render. Esto cubre cualquier mutación del editor inline
    # sin necesidad de instrumentar cada punto de mutación uno por uno.
    if pending_revalidate_key is not None:
        _live_fp = _compute_live_fingerprint(
            source=source, plan_id=plan_id, schedule_id=schedule_id,
        )
        _snap_fp = _compute_summary_fingerprint(
            summary, source=source,
        )
        if _live_fp != _snap_fp:
            st.session_state[pending_revalidate_key] = True
            for _k in (invalidate_cache_keys or []):
                st.session_state.pop(_k, None)
            # Invalidar caches de _chk_worst de todos los expanders del
            # editor para que el header del expander muestre el icono
            # fresco en el proximo render (en lugar del cacheado del
            # render anterior, que es stale despues de la edicion).
            _chk_prefix = f"{key_ns}_dpm_edit_"
            for _k in list(st.session_state.keys()):
                if (
                    isinstance(_k, str)
                    and _k.startswith(_chk_prefix)
                    and _k.endswith("_chk_worst")
                ):
                    st.session_state.pop(_k, None)
            # Re-run inmediato para que el panel padre vea el flag
            # antes de que rendereemos contenido stale.
            st.rerun()

    # Construir dataset unificado: union de esperadas + materias del plan
    _esperadas_set = set(summary.esperadas.keys())
    _en_plan_set = set(summary.mat_map.keys())

    _faltantes_set = _esperadas_set - _en_plan_set
    _extras_set = _en_plan_set - _esperadas_set

    _conf_pairs: set[str] = set()
    for c in summary.conflictos_horarios:
        _conf_pairs.add(c["materia_a"])
        _conf_pairs.add(c["materia_b"])

    # Cargar metadatos de todas las materias del universo
    _all_codes = list(_esperadas_set | _en_plan_set)
    if not _all_codes:
        st.caption("Sin materias para mostrar.")
        return

    with next(get_session()) as session:
        _mats = list(session.exec(
            select(MateriaDB).where(col(MateriaDB.codigo).in_(_all_codes))
        ).all())
        _mat_map = {m.codigo: m for m in _mats}

        # Modalidad virtual a nivel dictado del ciclo. El filtro
        # "Virtual" del detalle considera materia virtual de catálogo
        # (`MateriaDB.virtual`) **o** dictado virtual del ciclo
        # (`DictadoDB.virtual=True`). Esto es coherente con el LP, que
        # ignora horarios cuyo dictado es virtual aunque la materia
        # no lo sea (caso típico: recursados por Zoom).
        from src.database.models import (
            DictadoDB as _DD,
            DictadoCicloDB as _DCB,
        )
        _dictado_virtual_por_materia: dict[str, bool] = {}
        if ciclo_id:
            _dvm_rows = list(session.exec(
                select(_DD.materia_codigo, _DD.virtual)
                .join(_DCB, _DD.id == _DCB.dictado_id)  # type: ignore[arg-type]
                .where(_DCB.ciclo_id == ciclo_id)
                .where(col(_DD.materia_codigo).in_(_all_codes))
            ).all())
            for _mc, _v in _dvm_rows:
                _dictado_virtual_por_materia[_mc] = bool(_v)

        # Materias con laboratorio asignado (para filtro "Solo con lab")
        from src.database.models import MateriaLaboratorioDB as _MLB
        _lab_rows = list(session.exec(
            select(_MLB.materia_codigo)
            .where(col(_MLB.materia_codigo).in_(_all_codes))
            .distinct()
        ).all())
        _labs_set: set[str] = set(_lab_rows)

        # Mapa codigo→nombre de carrera (para mostrar nombres en filtro)
        _carrera_rows = list(session.exec(select(CarreraDB)).all())
        _carrera_nombre_map: dict[str, str] = {
            c.codigo: c.nombre for c in _carrera_rows
        }

        # PE rows para carrera/anio/cuatri (cualquiera del ciclo)
        _pe_map: dict[str, list[PlanEstudioDB]] = {}
        if ciclo_id:
            _pv_ids = list(session.exec(
                select(CicloPlanVersionDB.plan_version_id)
                .where(CicloPlanVersionDB.ciclo_id == ciclo_id)
            ).all())
            if _pv_ids:
                _pes = list(session.exec(
                    select(PlanEstudioDB)
                    .where(col(PlanEstudioDB.plan_version_id).in_(_pv_ids))
                    .where(col(PlanEstudioDB.materia_codigo).in_(_all_codes))
                ).all())
                for _pe in _pes:
                    _pe_map.setdefault(_pe.materia_codigo, []).append(_pe)

        # Conteo de comisiones + horarios por materia.
        _coms_por_mat: dict[str, list[ComisionDB]] = {}
        _h_count_per_com: dict[str, int] = {}
        _com_count_sched: dict[str, int] = {}
        _entry_count_sched: dict[str, int] = {}
        if source == "plan" and plan_id:
            _coms = list(session.exec(
                select(ComisionDB).where(ComisionDB.plan_cursada_id == plan_id)
            ).all())
            for c in _coms:
                _coms_por_mat.setdefault(c.materia_codigo, []).append(c)
            _com_ids = [c.id for c in _coms]
            if _com_ids:
                _h_rows = list(session.exec(
                    select(
                        HorarioDB.comision_id,  # type: ignore[arg-type]
                        func.count(HorarioDB.id),  # type: ignore[arg-type]
                    )
                    .where(col(HorarioDB.comision_id).in_(_com_ids))
                    .group_by(HorarioDB.comision_id)  # type: ignore[arg-type]
                ).all())
                _h_count_per_com = {cid: n for cid, n in _h_rows}
        elif source == "schedule" and schedule_id:
            from src.database.models import ScheduleEntryDB as _SE
            _entries = list(session.exec(
                select(_SE).where(_SE.schedule_id == schedule_id)
            ).all())
            for e in _entries:
                _entry_count_sched[e.codigo_materia] = (
                    _entry_count_sched.get(e.codigo_materia, 0) + 1
                )
                # comisiones distintas por materia (tomando ScheduleEntryDB.comision)
                pass
            # Distinct comisiones por materia
            _by_mat: dict[str, set[int]] = {}
            for e in _entries:
                if e.comision is not None:
                    _by_mat.setdefault(e.codigo_materia, set()).add(e.comision)
            _com_count_sched = {mc: len(s) for mc, s in _by_mat.items()}

    # Construir filas
    _rows: list[dict] = []
    for _code in _all_codes:
        _m = _mat_map.get(_code)
        _pes = _pe_map.get(_code, [])
        # Set de carreras a las que pertenece la materia (puede estar en
        # varias). El display "carrera" muestra una representativa para
        # la columna de la tabla; el filtro usa el set completo para
        # detectar pertenencia.
        _carreras_set: set[str] = {
            _pe.carrera_codigo for _pe in _pes if _pe.carrera_codigo
        }
        if not _carreras_set:
            _carrera_display = "—"
        elif len(_carreras_set) == 1:
            _carrera_display = next(iter(_carreras_set))
        else:
            _carrera_display = (
                f"{sorted(_carreras_set)[0]} (+{len(_carreras_set) - 1})"
            )
        _anio = _pes[0].anio_plan if _pes else None
        _cuatri = (_pes[0].cuatrimestre_plan if _pes else None) or "—"
        _optativa = any(bool(_pe.optativa) for _pe in _pes)

        if source == "plan":
            _coms_de_m = _coms_por_mat.get(_code, [])
            _n_coms = len(_coms_de_m)
            _n_horarios = sum(
                _h_count_per_com.get(c.id, 0) for c in _coms_de_m
            )
        else:  # schedule
            _n_coms = _com_count_sched.get(_code, 0)
            _n_horarios = _entry_count_sched.get(_code, 0)
        _hsem = _m.horas_semanales if _m else None
        _hlab = _m.horas_laboratorio if _m else None
        # `_virtual_catalogo`: la materia es virtual de catálogo.
        # `_virtual_dictado`: el dictado del ciclo está marcado virtual
        # (modalidad puntual). El filtro "Virtual" del detalle
        # combina ambos con OR — coherente con el LP.
        _virtual_catalogo = bool(_m.virtual) if _m else False
        _virtual_dictado = _dictado_virtual_por_materia.get(_code, False)
        _virtual = _virtual_catalogo or _virtual_dictado
        _periodo = _m.periodo if _m else "cuatrimestral"
        _anual = _periodo == "anual"
        _n_carreras = len(_carreras_set)

        _data = {
            "codigo": _code,
            "nombre": _m.nombre if _m else "?",
            "carrera": _carrera_display,
            "carreras_set": _carreras_set,
            "anio": _anio,
            "cuatri": _cuatri,
            "optativa": _optativa,
            "virtual": _virtual,
            "virtual_catalogo": _virtual_catalogo,
            "virtual_dictado": _virtual_dictado,
            "anual": _anual,
            "periodo": _periodo,
            "tiene_lab": _code in _labs_set,
            "horas_lab": _hlab,
            "n_carreras": _n_carreras,
            "horas_semanales": _hsem,
            "n_comisiones": _n_coms,
            "n_horarios": _n_horarios,
            "es_faltante": _code in _faltantes_set,
            "es_no_esperada": _code in _extras_set,
            "tiene_conflicto": _code in _conf_pairs,
            "falta_horas": _hsem is None,
        }
        _data["estado"] = _estado_de_materia(_data)
        _rows.append(_data)

    # Metricas
    _n_total = len(_rows)
    _n_ok = sum(1 for r in _rows if r["estado"] == "OK")
    _n_revision = _n_total - _n_ok
    _mt1, _mt2, _mt3 = st.columns(3)
    _mt1.metric("Total materias", _n_total)
    _mt2.metric("OK", _n_ok)
    _mt3.metric("Requieren revisión", _n_revision)

    # =========================================================================
    # Filtros
    # =========================================================================
    # Set completo de carreras de todas las materias (union de
    # carreras_set por row). Asi una materia comun puede ser elegida
    # por cualquiera de sus carreras.
    _all_carreras: set[str] = set()
    for r in _rows:
        _all_carreras |= r.get("carreras_set") or set()
    _carreras_opts = sorted(_all_carreras)
    _anios_opts = sorted({r["anio"] for r in _rows if r["anio"] is not None})
    _cuatris_opts = sorted({r["cuatri"] for r in _rows if r["cuatri"] != "—"})
    _estados_opts = ["OK", "Faltante", "No esperada", "Conflictiva", "Sin datos"]
    _tipo_opts = ["Todas", "Comunes", "Exclusivas"]
    # Atributos de materia: cada uno es un multi-state (sí/no/cualquiera)
    # representado como dos opciones por atributo.
    _attr_opts = [
        "Optativa",
        "No optativa",
        "Virtual",
        "No virtual",
        "Anual",
        "Cuatrimestral",
        "Con lab asignado",
        "Sin lab asignado",
    ]

    _carrera_label = lambda cc: (
        f"{cc} — {_carrera_nombre_map[cc]}"
        if cc in _carrera_nombre_map else cc
    )

    _f1, _f2, _f3, _f4, _f5 = st.columns(5)
    with _f1:
        _busc = st.text_input(
            "🔍 Buscar", key=f"{key_ns}_dpm_busc",
            placeholder="código o nombre",
        )
    with _f2:
        _f_carr = st.multiselect(
            "Carrera", options=_carreras_opts, default=[],
            format_func=_carrera_label,
            key=f"{key_ns}_dpm_carrera",
        )
    with _f3:
        _f_anio = st.multiselect(
            "Año", options=_anios_opts, default=[],
            format_func=lambda a: f"{a}°",
            key=f"{key_ns}_dpm_anio",
        )
    with _f4:
        _f_cuatri = st.multiselect(
            "Cuatri", options=_cuatris_opts, default=[],
            key=f"{key_ns}_dpm_cuatri",
        )
    with _f5:
        _f_estado = st.multiselect(
            "Estado", options=_estados_opts, default=[],
            key=f"{key_ns}_dpm_estado",
        )

    _g1, _g2, _g3 = st.columns(3)
    with _g1:
        _f_tipo = st.selectbox(
            "Tipo (carreras)",
            options=_tipo_opts, index=0,
            key=f"{key_ns}_dpm_tipo",
            help=(
                "Comunes: materias compartidas entre 2+ carreras. "
                "Exclusivas: materias de una sola carrera."
            ),
        )
    with _g2:
        _f_attrs = st.multiselect(
            "Atributos",
            options=_attr_opts, default=[],
            key=f"{key_ns}_dpm_attrs",
            help=(
                "Filtros por atributo de la materia. Si elegís un par "
                "contradictorio (ej. Optativa + No optativa) no queda "
                "ninguna materia. Combinable con los demás filtros.\n\n"
                "**Virtual** filtra materias virtuales por *cualquiera* "
                "de las dos vías: virtuales de catálogo "
                "(`MateriaDB.virtual=True`, ej. asignaturas dictadas "
                "por Zoom siempre) o con dictado virtual del ciclo "
                "actual (`DictadoDB.virtual=True`, modalidad puntual "
                "como recursados que excepcionalmente se dictan online "
                "este cuatri). La columna **Virtual** de la tabla "
                "distingue cuál de las dos aplica."
            ),
        )
    with _g3:
        _only_issues = st.toggle(
            "Solo con alertas",
            value=False,
            key=f"{key_ns}_dpm_only_issues",
            help=(
                "Mostrar solo materias cuyo estado no es OK (faltantes, "
                "no esperadas, conflictivas o sin datos)."
            ),
        )

    # --- Aplicar filtros ---
    def _passes(r: dict) -> bool:
        if _busc.strip():
            _t = _busc.strip().lower()
            if _t not in r["codigo"].lower() and _t not in r["nombre"].lower():
                return False
        if _f_carr:
            # Una materia matchea el filtro de carrera si pertenece a
            # AL MENOS una de las carreras seleccionadas (intersección
            # no vacia entre el set de carreras de la materia y las
            # elegidas). Esto soporta materias comunes que pertenecen
            # a varias carreras simultaneamente.
            _r_set = r.get("carreras_set") or set()
            if not _r_set or not (_r_set & set(_f_carr)):
                return False
        if _f_anio and r["anio"] not in _f_anio:
            return False
        if _f_cuatri and r["cuatri"] not in _f_cuatri:
            return False
        if _f_estado and r["estado"] not in _f_estado:
            return False
        if _f_tipo == "Comunes" and r["n_carreras"] < 2:
            return False
        if _f_tipo == "Exclusivas" and r["n_carreras"] != 1:
            return False
        if _f_attrs:
            if "Optativa" in _f_attrs and not r["optativa"]:
                return False
            if "No optativa" in _f_attrs and r["optativa"]:
                return False
            if "Virtual" in _f_attrs and not r["virtual"]:
                return False
            if "No virtual" in _f_attrs and r["virtual"]:
                return False
            if "Anual" in _f_attrs and not r["anual"]:
                return False
            if "Cuatrimestral" in _f_attrs and r["anual"]:
                return False
            if "Con lab asignado" in _f_attrs and not r["tiene_lab"]:
                return False
            if "Sin lab asignado" in _f_attrs and r["tiene_lab"]:
                return False
        if _only_issues and r["estado"] == "OK":
            return False
        return True

    _filtered = [r for r in _rows if _passes(r)]
    _filtered.sort(key=lambda r: (r["carrera"], r["anio"] or 99, r["codigo"]))

    if not _filtered:
        st.caption(
            "Ninguna materia matchea los filtros. Ajustá los filtros."
        )
        return

    st.caption(f"Mostrando {len(_filtered)} de {_n_total} materias.")

    # =========================================================================
    # Tabla "Resumen por carrera" — counts de status por carrera
    # =========================================================================
    _carrera_counts: dict[str, dict[str, int]] = {}
    for r in _filtered:
        # Una materia comun cuenta en cada carrera a la que pertenece
        # (se considera "esperada" en cada plan).
        for cc in (r.get("carreras_set") or set()):
            bkt = _carrera_counts.setdefault(
                cc, {"OK": 0, "Faltante": 0, "No esperada": 0,
                     "Conflictiva": 0, "Sin datos": 0},
            )
            bkt[r["estado"]] = bkt.get(r["estado"], 0) + 1
    if _carrera_counts:
        _cs_rows = []
        for cc in sorted(_carrera_counts.keys()):
            counts = _carrera_counts[cc]
            _cs_rows.append({
                "Carrera": cc,
                "Materias": sum(counts.values()),
                "✅ OK": counts["OK"],
                "⚠️ Revisión": counts["Conflictiva"] + counts["Sin datos"],
                "📭 Faltantes": counts["Faltante"],
                "📥 No esperadas": counts["No esperada"],
            })
        # Total al pie: cuenta materias UNICAS del set filtrado (no
        # sumas de carrera, porque una materia comun se cuenta en cada
        # carrera y eso inflaria el total).
        _u_total = len(_filtered)
        _u_ok = sum(1 for r in _filtered if r["estado"] == "OK")
        _u_falt = sum(1 for r in _filtered if r["estado"] == "Faltante")
        _u_noesp = sum(1 for r in _filtered if r["estado"] == "No esperada")
        _u_rev = sum(
            1 for r in _filtered
            if r["estado"] in ("Conflictiva", "Sin datos")
        )
        _tot = {
            "Carrera": "**Total (únicas)**",
            "Materias": _u_total,
            "✅ OK": _u_ok,
            "⚠️ Revisión": _u_rev,
            "📭 Faltantes": _u_falt,
            "📥 No esperadas": _u_noesp,
        }
        st.markdown("**Resumen por carrera (sobre el set filtrado)**")
        st.caption(
            "Una materia común se cuenta en cada carrera a la que "
            "pertenece. La fila **Total (únicas)** cuenta materias "
            "distintas (sin duplicar)."
        )
        st.dataframe(
            pd.DataFrame(_cs_rows + [_tot]),
            use_container_width=True, hide_index=True,
        )

    # =========================================================================
    # Tabla resumen (siempre visible, con todas las filtradas)
    # =========================================================================
    _disp_rows = []
    for r in _filtered:
        # "Virtual" en la tabla del detalle distingue entre el flag de
        # catálogo (la materia siempre es virtual) y el flag del dictado
        # del ciclo (modalidad puntual).
        if r.get("virtual_catalogo"):
            _virt_lbl = "Sí (catálogo)"
        elif r.get("virtual_dictado"):
            _virt_lbl = "Sí (dictado)"
        else:
            _virt_lbl = "—"
        _disp_rows.append({
            "Estado": _estado_badge(r["estado"]),
            "Código": r["codigo"],
            "Nombre": r["nombre"],
            "Carrera": r["carrera"],
            "Año": f"{r['anio']}°" if r["anio"] else "—",
            "Cuatri": r["cuatri"],
            "Comisiones": r["n_comisiones"],
            "Horarios": r["n_horarios"],
            "h/sem": (
                f"{r['horas_semanales']:g}"
                if r["horas_semanales"] is not None else "—"
            ),
            "Optativa": "Sí" if r["optativa"] else "—",
            "Virtual": _virt_lbl,
            "Lab": "Sí" if r["tiene_lab"] else "—",
        })
    st.dataframe(
        pd.DataFrame(_disp_rows),
        use_container_width=True, hide_index=True,
    )

    # =========================================================================
    # Loop paginado de expanders por materia (con editor inline + calendario)
    # =========================================================================
    _pending_key = f"{key_ns}_dpm_pending_codigo"
    _pending_codigo: Optional[str] = st.session_state.pop(_pending_key, None)

    # Si lo pedido no está entre las filtradas, lo agregamos al final
    # del set para que aparezca en la página actual del loop.
    _loop_rows = list(_filtered)
    if _pending_codigo and not any(
        r["codigo"] == _pending_codigo for r in _loop_rows
    ):
        _extra = next(
            (r for r in _rows if r["codigo"] == _pending_codigo), None
        )
        if _extra:
            _loop_rows.append(_extra)

    # --- Paginación ---
    _PAGE_SIZE = 10
    _total_pages = max(1, (len(_loop_rows) + _PAGE_SIZE - 1) // _PAGE_SIZE)

    # Si hay pending, forzar la página donde está esa materia
    _page_key = f"{key_ns}_dpm_page"
    if _pending_codigo:
        for _i, _r in enumerate(_loop_rows):
            if _r["codigo"] == _pending_codigo:
                st.session_state[_page_key] = (_i // _PAGE_SIZE) + 1
                break

    st.divider()
    st.markdown(
        f"##### 🛠️ Detalle por materia ({len(_loop_rows)} resultado(s))"
    )

    # Botones globales y selector de página
    _bc1, _bc2, _bc3, _bc4 = st.columns([1, 1, 1, 3])
    with _bc1:
        if st.button(
            "Abrir todas",
            key=f"{key_ns}_dpm_btn_open_all",
            help="Expandir todas las materias visibles en la página actual.",
            use_container_width=True,
        ):
            st.session_state[f"{key_ns}_dpm_force_expand"] = "open"
            st.rerun()
    with _bc2:
        if st.button(
            "Cerrar todas",
            key=f"{key_ns}_dpm_btn_close_all",
            help="Colapsar todas las materias de la página actual.",
            use_container_width=True,
        ):
            st.session_state[f"{key_ns}_dpm_force_expand"] = "close"
            st.rerun()
    with _bc3:
        _page = st.number_input(
            f"Página (de {_total_pages})",
            min_value=1, max_value=_total_pages,
            value=min(
                st.session_state.get(_page_key, 1), _total_pages
            ),
            step=1,
            key=_page_key,
            label_visibility="collapsed",
        )
    with _bc4:
        st.caption(
            f"Página {int(_page)} de {_total_pages} · "
            f"{_PAGE_SIZE} materias/página · "
            f"total {len(_loop_rows)}"
        )

    _force_expand = st.session_state.pop(
        f"{key_ns}_dpm_force_expand", None
    )

    # Slice de la página
    _start = (int(_page) - 1) * _PAGE_SIZE
    _end = _start + _PAGE_SIZE
    _page_rows = _loop_rows[_start:_end]

    # Render expanders
    _icon_map = {
        "ok": "✅", "warn": "⚠️", "error": "🔺", "info": "ℹ️",
        "faltante": "📭",
    }
    for _r in _page_rows:
        _code = _r["codigo"]
        _is_pending = _pending_codigo == _code

        # Worst icon cacheado por el editor en el render anterior. Si
        # no hay cache, usar el estado del row.
        # La key del editor incluye {schedule_id|plan_id}+materia_codigo
        # (ver schedule_materia_editor / plan_materia_editor:
        # `_kp = f"{key_ns}_{schedule_id|plan_id}_{mat}"`).
        if source == "schedule" and schedule_id:
            _worst_key_s = (
                f"{key_ns}_dpm_edit_{schedule_id}_{_code}_chk_worst"
            )
        elif source == "plan" and plan_id:
            _worst_key_s = (
                f"{key_ns}_dpm_edit_{plan_id}_{_code}_chk_worst"
            )
        else:
            _worst_key_s = f"{key_ns}_dpm_edit_chk_worst_{_code}"
        _worst_cached = st.session_state.get(_worst_key_s)
        if _worst_cached:
            _worst_icon = _icon_map.get(_worst_cached, "•")
        else:
            _worst_icon = _estado_badge(_r["estado"]).split(" ")[0]

        _hsem_disp = (
            f"{_r['horas_semanales']:g}h/sem"
            if _r["horas_semanales"] is not None else "h/sem ?"
        )

        # Sufijo de modo lab: ad-hoc (reserva) si tiene lab asignado y
        # hl=0; lab fijo Xh si hl>0.
        _hlab_v = _r.get("horas_lab")
        _has_lab_v = _r.get("tiene_lab", False)
        if _has_lab_v and _hlab_v is not None and _hlab_v == 0:
            _lab_suffix = " · ℹ️ lab por reserva"
        elif _has_lab_v and _hlab_v is not None and _hlab_v > 0:
            _lab_suffix = f" · 🧪 lab fijo {_hlab_v:g}h"
        elif _has_lab_v and _hlab_v is None:
            _lab_suffix = " · ⚠️ lab pendiente"
        else:
            _lab_suffix = ""

        _hdr = (
            f"{_worst_icon} {_code} — "
            f"{_r['nombre']} | {_r['n_comisiones']} com · "
            f"{_r['n_horarios']} clases · {_hsem_disp}{_lab_suffix}"
        )

        # Política de expansión:
        # - Si hubo "Abrir todas" / "Cerrar todas" en este rerun, override.
        # - Si la materia es la pre-seleccionada, abrir.
        # - Default: cerrado.
        if _force_expand == "open":
            _eff_expand = True
        elif _force_expand == "close":
            _eff_expand = False
        elif _is_pending:
            _eff_expand = True
        else:
            _eff_expand = False

        with st.expander(_hdr, expanded=_eff_expand):
            _render_materia_inner(
                row=_r,
                source=source,
                plan_id=plan_id,
                schedule_id=schedule_id,
                ciclo_id=ciclo_id,
                key_ns=f"{key_ns}_dpm_edit",
                save_as_copy=save_as_copy,
                pending_revalidate_key=pending_revalidate_key,
                invalidate_cache_keys=invalidate_cache_keys,
            )


def _render_materia_inner(
    *, row: dict, source: Literal["plan", "schedule"],
    plan_id: Optional[str], schedule_id: Optional[str],
    ciclo_id: Optional[str], key_ns: str,
    save_as_copy: bool = False,
    pending_revalidate_key: Optional[str] = None,
    invalidate_cache_keys: Optional[list[str]] = None,
) -> None:
    """Cuerpo de un expander del loop "Detalle por materia": delega al
    editor inline (plan o schedule), que renderea su propio calendario
    editable + 10 checks + data_editor."""
    _code = row["codigo"]

    if source == "plan" and plan_id:
        # Plan: el editor renderea su propio calendario editable
        # (drag/click/select + dialogs). No agregamos calendario
        # read-only previo (seria redundante).
        from src.ui.plan_materia_editor import render_plan_materia_detail
        render_plan_materia_detail(
            plan_id=plan_id,
            materia_codigo=_code,
            key_ns=key_ns,
            pending_revalidate_key=pending_revalidate_key,
            invalidate_cache_keys=invalidate_cache_keys,
        )
    elif source == "schedule" and schedule_id:
        # Schedule: el editor renderea su propio calendario editable
        # (drag/drop/click/select) + dialogs internos. No agregamos un
        # calendario read-only previo (seria redundante).
        from src.ui.schedule_materia_editor import (
            render_schedule_materia_detail,
        )
        render_schedule_materia_detail(
            schedule_id=schedule_id,
            materia_codigo=_code,
            key_ns=key_ns,
            save_as_copy=save_as_copy,
            pending_revalidate_key=pending_revalidate_key,
            invalidate_cache_keys=invalidate_cache_keys,
        )


def _estado_badge(estado: str) -> str:
    """Emoji + etiqueta corta del estado."""
    return {
        "OK": "✅ OK",
        "Faltante": "📭 Faltante",
        "No esperada": "📥 No esperada",
        "Conflictiva": "⚠️ Conflicto",
        "Sin datos": "❓ Sin datos",
    }.get(estado, estado)


# =============================================================================
# SCHEDULE — entrypoint
# =============================================================================

def _render_schedule(
    schedule_id: str, ciclo_id: str, key_ns: str,
) -> None:
    """Render del panel para un cronograma vs ciclo.

    Espejo de `_render_plan` con tres diferencias:
    - Sin `ignored_pairs` (cronograma no tiene IgnoredConflictDB).
    - Sin editor inline (los conflictos se resuelven editando los
      entries del cronograma desde el tab Editar).
    - Bloque "Resumen de laboratorios" con n_con_lab_asignado, lab_fijo,
      lab_reserva, lab_pendiente.
    - Sin gate de activación (el cronograma no se "activa").
    """
    # Toggles + boton
    _toggle_key = f"{key_ns}_exclude_optativas"
    _autoval_key = f"{key_ns}_auto_validate"
    _validation_key = f"{key_ns}_validation_summary"
    _pending_revalidate_key = f"{key_ns}_pending_revalidate"

    _col_t1, _col_t2, _col_b = st.columns([3, 2, 2])
    with _col_t1:
        exclude_optativas = st.toggle(
            "Excluir optativas del cómputo",
            value=st.session_state.get(_toggle_key, False),
            key=_toggle_key,
            help=(
                "Las materias optativas no se cuentan en el set esperado. "
                "Las virtuales SÍ cuentan: estructuralmente sus comisiones "
                "y horarios deben ser consistentes."
            ),
        )
    with _col_t2:
        auto_validate = st.toggle(
            "Auto-revalidar al cambiar",
            value=st.session_state.get(_autoval_key, True),
            key=_autoval_key,
            help=(
                "Si está ON, cualquier acción del panel re-corre la "
                "validación automáticamente."
            ),
        )
    with _col_b:
        _run_button = st.button(
            "Validar cronograma", type="primary",
            key=f"{key_ns}_btn_validate",
            use_container_width=True,
        )

    # Toggle global "Guardar como copia": cualquier mutacion via
    # calendario editable o data_editor del schedule_materia_editor se
    # aplica a una copia del cronograma en lugar del original.
    _save_as_copy_key = f"{key_ns}_save_as_copy"
    _save_as_copy = st.toggle(
        "Guardar cambios como copia del cronograma",
        value=st.session_state.get(_save_as_copy_key, False),
        key=_save_as_copy_key,
        help=(
            "Si está activo, todas las ediciones (calendario, data "
            "editor, reasignar comisiones) se aplican a una copia del "
            "cronograma — el original no se toca. La copia se crea al "
            "primer cambio y se sigue usando hasta que apagues el toggle."
        ),
    )
    if _save_as_copy:
        _copy_name_default = "Cronograma editado"
        _copy_name = st.text_input(
            "Nombre de la copia",
            value=st.session_state.get(
                "_sme_copy_name", _copy_name_default
            ),
            key="_sme_copy_name",
        )

    _last_toggle_key = f"{key_ns}_last_toggle"
    _toggle_changed = (
        _validation_key in st.session_state
        and st.session_state.get(_last_toggle_key) is not None
        and st.session_state[_last_toggle_key] != exclude_optativas
    )

    _pending_auto = (
        auto_validate
        and st.session_state.pop(_pending_revalidate_key, False)
    )

    if _run_button or _toggle_changed or _pending_auto:
        with next(get_session()) as session:
            summary = validar_cronograma(
                session, schedule_id, ciclo_id,
                exclude_optativas=exclude_optativas,
            )
            if summary.error is None:
                _crono_persist_validation(session, summary)
        st.session_state[_validation_key] = summary
        st.session_state[_last_toggle_key] = exclude_optativas
        if _pending_auto:
            st.toast("✓ Cronograma revalidado tras cambios.")

    # Si no hay summary aun, intentar recuperar el ultimo persistido
    if _validation_key not in st.session_state:
        with next(get_session()) as session:
            _last = _crono_get_latest(session, schedule_id, ciclo_id)
            if _last is not None:
                _details = _crono_parse_details(_last.details_json)
                summary = CronogramaValidationSummary(
                    schedule_id=_last.schedule_id,
                    ciclo_id=_last.ciclo_id,
                    validated_at=_last.validated_at,
                    entry_count_at_validation=_last.entry_count_at_validation,
                    dictado_count_at_validation=_last.dictado_count_at_validation,
                    n_materias=_last.n_materias,
                    n_clases=_last.n_clases,
                    total_horas=_last.total_horas,
                    n_esperadas=_last.n_esperadas,
                    n_cubiertas=_last.n_cubiertas,
                    n_faltantes=_last.n_faltantes,
                    n_extra=_last.n_extra,
                    n_con_lab_asignado=_last.n_con_lab_asignado,
                    n_lab_fijo=_last.n_lab_fijo,
                    n_lab_reserva=_last.n_lab_reserva,
                    n_lab_pendiente=_last.n_lab_pendiente,
                    particion_valid=_last.particion_valid,
                    particion_n_infactibles=_last.particion_n_infactibles,
                    particion_message=_details.get("particion_message", ""),
                    n_conflictos_horarios=_last.n_conflictos_horarios,
                    excluir_optativas=_last.excluir_optativas,
                    excluir_virtuales_optativas=_last.excluir_virtuales_optativas,
                    faltantes_por_carrera=_details.get(
                        "faltantes_por_carrera", []
                    ),
                    extras=_details.get("extras", []),
                    particion_details=_details.get("particion_details", []),
                    conflictos_horarios=_details.get(
                        "conflictos_horarios", []
                    ),
                    esperadas=_details.get("esperadas", {}),
                    mat_map=_details.get("mat_map", {}),
                )
                st.session_state[_validation_key] = summary
                st.session_state[_last_toggle_key] = _last.excluir_optativas

    if _validation_key not in st.session_state:
        st.info(
            "Apretá **Validar cronograma** para correr la validación "
            "completa (cobertura, conflictos, partición teoría/lab)."
        )
        return

    summary: CronogramaValidationSummary = st.session_state[_validation_key]

    if summary.error:
        st.error(summary.error)
        return

    # Staleness
    with next(get_session()) as session:
        _latest = _crono_get_latest(session, schedule_id, ciclo_id)
        if _latest is not None:
            _stale = _crono_validation_stale(session, _latest)
            # Tambien comparar toggle aplicado
            if _latest.excluir_optativas != exclude_optativas:
                _stale = True
        else:
            _stale = False
    if _stale:
        st.warning(
            "El cronograma, sus dictados o el toggle cambiaron desde la "
            "última validación. Apretá **Validar cronograma** para "
            "actualizar."
        )

    # =========================================================================
    # Resumen de cobertura
    # =========================================================================
    st.divider()
    st.markdown("### Resumen de cobertura")
    _c1, _c2, _c3, _c4, _c5, _c6 = st.columns(6)
    _c1.metric("Materias", summary.n_materias)
    _c2.metric("Clases", summary.n_clases)
    _c3.metric("Horas cronograma", f"{summary.total_horas:.1f}")
    _c4.metric(
        "Esperadas",
        summary.n_esperadas,
        delta=(
            None if not summary.excluir_optativas
            else "(optativas excluidas)"
        ),
        delta_color="off",
    )
    _c5.metric("Cubiertas", f"{summary.n_cubiertas}/{summary.n_esperadas}")
    _c6.metric("Faltantes", summary.n_faltantes)

    # =========================================================================
    # Resumen de laboratorios
    # =========================================================================
    if summary.n_con_lab_asignado > 0:
        st.markdown("##### 🧪 Resumen de laboratorios")
        _lc1, _lc2, _lc3, _lc4 = st.columns(4)
        _lc1.metric("Con lab asignado", summary.n_con_lab_asignado)
        _lc2.metric("Lab fijo (h>0)", summary.n_lab_fijo)
        _lc3.metric("Reserva ad-hoc (h=0)", summary.n_lab_reserva)
        _lc4.metric(
            "Pendiente (sin h)", summary.n_lab_pendiente,
            delta=(
                "⚠️ bloqueante" if summary.n_lab_pendiente else None
            ),
            delta_color="inverse",
        )

    # =========================================================================
    # Particion teoria/lab
    # =========================================================================
    if summary.particion_valid:
        st.success(summary.particion_message or "Partición teoría/lab OK.")
    else:
        st.error(summary.particion_message or "Partición teoría/lab inválida.")
        if summary.particion_details:
            with st.expander(
                f"Detalles de partición ({summary.particion_n_infactibles})",
                expanded=False,
            ):
                for d in summary.particion_details:
                    st.text(f"  - {d}")

    # =========================================================================
    # Detalle por carrera
    # =========================================================================
    _grupos = _build_grupos_por_carrera(summary, ciclo_id)
    _full_mat_map = _build_full_mat_map(summary, _grupos)
    _has_issues = any(
        len(g["faltantes"]) > 0 or len(g["extras"]) > 0
        or len(g["conflictos"]) > 0
        for g in _grupos.values()
    )

    with st.expander(
        f"📋 Detalle por carrera ({len(_grupos)} grupo(s))",
        expanded=_has_issues,
    ):
        if not _grupos:
            st.caption("Sin discrepancias por carrera.")
        else:
            _render_resumen_carreras(_grupos)
            for _cc in sorted(_grupos.keys()):
                _g = _grupos[_cc]
                if (
                    len(_g["faltantes"]) == 0
                    and len(_g["extras"]) == 0
                    and len(_g["conflictos"]) == 0
                ):
                    continue
                _render_carrera_subexpander(
                    _g, ciclo_id=ciclo_id,
                    key_ns=key_ns, mat_map=_full_mat_map,
                    invalidate_cache_keys=[
                        _validation_key, _last_toggle_key,
                    ],
                    pending_revalidate_key=_pending_revalidate_key,
                    source="schedule",
                )

    # =========================================================================
    # Detalle por materia
    # =========================================================================
    with st.expander("🔎 Detalle por materia", expanded=False):
        _render_detalle_por_materia(
            summary=summary, key_ns=key_ns,
            source="schedule",
            schedule_id=schedule_id, ciclo_id=ciclo_id,
            save_as_copy=_save_as_copy,
            pending_revalidate_key=_pending_revalidate_key,
            invalidate_cache_keys=[
                _validation_key, _last_toggle_key,
            ],
        )
