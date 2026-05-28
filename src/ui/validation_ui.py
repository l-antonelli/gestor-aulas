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
        # B.3: pendiente. Por ahora se sigue usando
        # `validacion_cronograma_tab.render_tab` directamente.
        st.error(
            "render_validation(source='schedule') aun no implementado. "
            "Usar `validacion_cronograma_tab.render_tab` por ahora."
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
    _grupos = _build_grupos_por_carrera(summary, plan_id)
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
                    _g, plan_id=plan_id, ciclo_id=plan.ciclo_id,
                    key_ns=key_ns, mat_map=_full_mat_map,
                    invalidate_cache_keys=[
                        _validation_key, _last_toggle_key,
                    ],
                    pending_revalidate_key=_pending_revalidate_key,
                )

    # =====================================================================
    # Detalle por materia
    # =====================================================================
    with st.expander("🔎 Detalle por materia", expanded=False):
        _render_detalle_por_materia(summary, plan_id, key_ns=key_ns)

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

def _label_codnom(codigo: str, mat_map: dict[str, str]) -> str:
    """Devuelve 'CÓD — Nombre' si hay nombre, sino solo el código."""
    nom = mat_map.get(codigo)
    if nom and nom != "?":
        return f"{codigo} — {nom}"
    return codigo


def _build_full_mat_map(
    summary: PlanValidationSummary, grupos: dict[str, dict],
) -> dict[str, str]:
    """Mapa global código→nombre que cubre faltantes, extras, conflictos
    y materias del plan / esperadas. Usado para mostrar nombres junto a
    códigos en todas las tablas y selectboxes."""
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
    summary: PlanValidationSummary, plan_id: str,
) -> dict[str, dict]:
    """Construye dict por carrera con faltantes + extras + conflictos.

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
    if summary.extras:
        _extra_codes = [e["codigo"] for e in summary.extras]
        with next(get_session()) as session:
            _plan = session.get(PlanificacionCursadaDB, plan_id)
            if _plan and _plan.ciclo_id:
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
                    .where(CicloPlanVersionDB.ciclo_id == _plan.ciclo_id)
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

    for c in summary.conflictos_ignorados:
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
    g: dict, plan_id: str, ciclo_id: str, key_ns: str,
    mat_map: dict[str, str],
    invalidate_cache_keys: list[str],
    pending_revalidate_key: str,
) -> None:
    """Sub-expander por carrera con discrepancias + conflictos."""
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
                )


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

    if _sel_labels and st.button(
        f"{'⚪' if action == 'deactivate' else '🟢'} "
        f"{_verbo} {len(_sel_labels)} dictado(s)",
        key=_btn_key,
        type="primary",
    ):
        _codes = [_options[lbl] for lbl in _sel_labels]
        _activo = action == "activate"
        with next(get_session()) as _ds:
            _n = set_activo_for_materias_in_ciclo(
                _ds, ciclo_id, _codes, activo=_activo,
            )
        # Invalidar caches de validacion + marcar para auto-revalidar
        for _k in invalidate_cache_keys:
            st.session_state.pop(_k, None)
        st.session_state[pending_revalidate_key] = True
        st.toast(
            f"{_n} dictado(s) {'activado(s)' if _activo else 'desactivado(s)'}."
        )
        st.rerun()


def _render_conflictos_carrera(
    *, activos: list[dict], ignorados: list[dict],
    carrera_codigo: str,
    plan_id: str, key_ns: str,
    mat_map: dict[str, str],
    invalidate_cache_keys: list[str],
    pending_revalidate_key: str,
) -> None:
    """Conflictos activos + ignorados de una carrera."""
    if activos:
        st.caption(
            "Conflictos detectados con las **comisiones reales del plan**. "
            "Si sabés que un par no es un conflicto real (ej: docentes "
            "distintos, materia virtual con misma aula), podés marcarlo "
            "como ignorado."
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

        # Ignorar conflicto
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

    # Bloque de IGNORADOS — permite ver y quitar
    if ignorados:
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


def _render_detalle_por_materia(
    summary: PlanValidationSummary, plan_id: str, key_ns: str,
) -> None:
    """Lista filtrada de materias del plan + esperadas con su estado."""
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

        # PE rows para carrera/anio/cuatri (cualquiera del ciclo)
        _plan = session.get(PlanificacionCursadaDB, plan_id)
        _pe_map: dict[str, list[PlanEstudioDB]] = {}
        if _plan and _plan.ciclo_id:
            _pv_ids = list(session.exec(
                select(CicloPlanVersionDB.plan_version_id)
                .where(CicloPlanVersionDB.ciclo_id == _plan.ciclo_id)
            ).all())
            if _pv_ids:
                _pes = list(session.exec(
                    select(PlanEstudioDB)
                    .where(col(PlanEstudioDB.plan_version_id).in_(_pv_ids))
                    .where(col(PlanEstudioDB.materia_codigo).in_(_all_codes))
                ).all())
                for _pe in _pes:
                    _pe_map.setdefault(_pe.materia_codigo, []).append(_pe)

        # Conteo de comisiones + horarios por materia
        _coms = list(session.exec(
            select(ComisionDB).where(ComisionDB.plan_cursada_id == plan_id)
        ).all())
        _coms_por_mat: dict[str, list[ComisionDB]] = {}
        for c in _coms:
            _coms_por_mat.setdefault(c.materia_codigo, []).append(c)
        _com_ids = [c.id for c in _coms]
        _h_count_per_com: dict[str, int] = {}
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

    # Construir filas
    _rows: list[dict] = []
    for _code in _all_codes:
        _m = _mat_map.get(_code)
        _pes = _pe_map.get(_code, [])
        # Tomar primera carrera/anio/cuatri (mas comun: una sola) para filtros.
        _carrera = (_pes[0].carrera_codigo if _pes else None) or "—"
        _anio = _pes[0].anio_plan if _pes else None
        _cuatri = (_pes[0].cuatrimestre_plan if _pes else None) or "—"
        _optativa = any(bool(_pe.optativa) for _pe in _pes)

        _coms_de_m = _coms_por_mat.get(_code, [])
        _n_coms = len(_coms_de_m)
        _n_horarios = sum(
            _h_count_per_com.get(c.id, 0) for c in _coms_de_m
        )
        _hsem = _m.horas_semanales if _m else None
        _virtual = bool(_m.virtual) if _m else False

        _data = {
            "codigo": _code,
            "nombre": _m.nombre if _m else "?",
            "carrera": _carrera,
            "anio": _anio,
            "cuatri": _cuatri,
            "optativa": _optativa,
            "virtual": _virtual,
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

    # Filtros
    _carreras_opts = sorted({r["carrera"] for r in _rows if r["carrera"] != "—"})
    _anios_opts = sorted({r["anio"] for r in _rows if r["anio"] is not None})
    _cuatris_opts = sorted({r["cuatri"] for r in _rows if r["cuatri"] != "—"})
    _estados_opts = ["OK", "Faltante", "No esperada", "Conflictiva", "Sin datos"]

    _f1, _f2, _f3, _f4, _f5 = st.columns(5)
    with _f1:
        _busc = st.text_input(
            "🔍 Buscar", key=f"{key_ns}_dpm_busc",
            placeholder="código o nombre",
        )
    with _f2:
        _f_carr = st.multiselect(
            "Carrera", options=_carreras_opts, default=[],
            key=f"{key_ns}_dpm_carrera",
        )
    with _f3:
        _f_anio = st.multiselect(
            "Año", options=_anios_opts, default=[],
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

    # Aplicar filtros
    def _passes(r: dict) -> bool:
        if _busc.strip():
            _t = _busc.strip().lower()
            if _t not in r["codigo"].lower() and _t not in r["nombre"].lower():
                return False
        if _f_carr and r["carrera"] not in _f_carr:
            return False
        if _f_anio and r["anio"] not in _f_anio:
            return False
        if _f_cuatri and r["cuatri"] not in _f_cuatri:
            return False
        if _f_estado and r["estado"] not in _f_estado:
            return False
        return True

    _filtered = [r for r in _rows if _passes(r)]
    _filtered.sort(key=lambda r: (r["carrera"], r["anio"] or 99, r["codigo"]))

    if not _filtered:
        st.caption(
            "Ninguna materia matchea los filtros. "
            "Probá ajustar la búsqueda."
        )
        return

    st.caption(f"Mostrando {len(_filtered)} de {_n_total} materias.")

    # Tabla compacta
    _disp_rows = []
    for r in _filtered:
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
            "Virtual": "Sí" if r["virtual"] else "—",
        })
    st.dataframe(
        pd.DataFrame(_disp_rows),
        use_container_width=True, hide_index=True,
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
