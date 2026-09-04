"""Detalle del resultado del LP de asignación de aulas.

Renderiza una tabla coloreada (verde/amarillo/rojo) con el gap por
horario, métricas agregadas y una lista de candidatas a partir comisión.

Se llama desde el panel de asignación (``asignacion_panel.render_panel``)
una vez que existe un ``LPRunDB`` para el plan.
"""

from __future__ import annotations

import json
from typing import Optional

import pandas as pd
import streamlit as st
from sqlmodel import Session, select

from src.database.models import (
    AulaDB,
    ComisionDB,
    LPRunDB,
    MateriaDB,
    SedeDB,
)


# =============================================================================
# Helpers
# =============================================================================

def _get_horarios_virtuales_ahora(
    session: Session, plan_id: str,
) -> set[str]:
    """Devuelve el set de ``horario_id`` que actualmente resuelven como
    virtuales en el plan (según jerarquía horario > dictado > materia).

    Se usa para filtrar diagnósticos del snapshot del LPRun cuando el
    usuario marcó algún horario virtual **después** de correr el LP —
    esos horarios ya no cuentan aunque el snapshot los siga listando.
    """
    from src.database.models import (
        ComisionDB as _Com,
        DictadoCicloDB as _DictCic,
        DictadoDB as _Dict,
        HorarioDB as _Hor,
        MateriaDB as _Mat,
        PlanificacionCursadaDB as _Plan,
    )
    from src.services.resolucion_jerarquica import resolve_virtual

    plan = session.get(_Plan, plan_id)
    if plan is None:
        return set()
    com_ids = list(session.exec(
        select(_Com.id).where(_Com.plan_cursada_id == plan_id)
    ).all())
    if not com_ids:
        return set()
    hs = list(session.exec(
        select(_Hor).where(_Hor.comision_id.in_(com_ids))  # type: ignore[attr-defined]
    ).all())
    materias_codes = sorted({h.codigo_materia for h in hs})
    materias = list(session.exec(
        select(_Mat).where(_Mat.codigo.in_(materias_codes))  # type: ignore[attr-defined]
    ).all()) if materias_codes else []
    materia_virtual = {m.codigo: m.virtual for m in materias}
    materia_dictado_virtual: dict[str, bool | None] = {}
    if plan.ciclo_id is not None:
        for mc, v in session.exec(
            select(_Dict.materia_codigo, _Dict.virtual)
            .join(_DictCic, _Dict.id == _DictCic.dictado_id)  # type: ignore[arg-type]
            .where(_DictCic.ciclo_id == plan.ciclo_id)
        ).all():
            materia_dictado_virtual[mc] = v
    return {
        h.id for h in hs
        if resolve_virtual(
            horario_virtual=h.virtual,
            dictado_virtual=materia_dictado_virtual.get(h.codigo_materia),
            materia_virtual=materia_virtual.get(h.codigo_materia, False),
        )
    }


def _filtrar_diag_virtuales(
    diag: Optional[dict], virtuales: set[str],
) -> Optional[dict]:
    """Devuelve una copia del `diag` (dict serializado de
    `InfeasibilityDiagnosis`) con los items que **solo** referencian
    horarios ahora-virtuales eliminados. Preserva items multi-horario
    donde queda al menos un horario no-virtual (sólo actualiza los
    contadores derivados donde es trivial).

    Sin este filtro, tras marcar un horario virtual desde el inspector,
    el snapshot cacheado del LPRun sigue mostrando ese horario como
    "faltante", aunque el modelo ahora lo ignore.

    Nota: `particion_problemas` no se filtra ni se renderiza en el
    diagnóstico del tab Aulas — esa validación vive en la página de
    detalle del plan (10 checks por materia).
    """
    if not diag or not virtuales:
        return diag

    def _keep_single(items: list[dict]) -> list[dict]:
        return [
            i for i in items
            if i.get("horario_id") not in virtuales
        ]

    def _keep_multi(items: list[dict]) -> list[dict]:
        out = []
        for i in items:
            ids = i.get("horario_ids") or []
            filtered_ids = [x for x in ids if x not in virtuales]
            if not filtered_ids:
                continue
            new = dict(i)
            new["horario_ids"] = filtered_ids
            # Actualizar contadores triviales si aparecen.
            if "n_clases" in new:
                new["n_clases"] = len(filtered_ids)
            out.append(new)
        return out

    new_diag = dict(diag)
    if diag.get("horarios_sin_aula_compatible"):
        new_diag["horarios_sin_aula_compatible"] = _keep_single(
            diag["horarios_sin_aula_compatible"]
        )
    for key in (
        "franjas_saturadas",
        "saturacion_por_tipo",
        "hall_violators",
    ):
        if diag.get(key):
            new_diag[key] = _keep_multi(diag[key])
    return new_diag


def _recompute_heatmap_por_sede_live(
    session: Session, plan_id: str,
) -> Optional[dict]:
    """Recomputa el mapa de saturación por sede leyendo horarios frescos
    de la DB (respetando `HorarioDB.virtual` actual y regla jerárquica
    horario > dictado > materia).

    Devuelve el mismo shape que `heatmap_por_sede` del `LPRunDB.details_json`
    (para poder swapearlo sin cambiar el render). Devuelve None si el
    plan no tiene comisiones/horarios.

    Este helper existe porque el snapshot del último LPRun queda desac-
    tualizado apenas el usuario marca un horario como virtual desde el
    inspector de franja: el heatmap y el mensaje "Faltan N aulas" seguirían
    contando el horario aunque ya no cuente. Con este recompute, la vista
    se sincroniza con el estado real de la DB en cada rerun.
    """
    from src.database.models import (
        ComisionDB as _Com,
        DictadoCicloDB as _DictCic,
        DictadoDB as _Dict,
        HorarioDB as _Hor,
        MateriaDB as _Mat,
        MateriaLaboratorioDB as _MatLab,
        PlanificacionCursadaDB as _Plan,
        SedeDB as _Sede,
    )
    from src.services.asignacion_aulas_helpers import (
        AulaSlot,
        HorarioSlot,
        compute_heatmap_por_sede,
    )
    from src.services.carrera_sede_service import (
        sedes_admisibles_para_carrera,
        sedes_admisibles_para_materia,
    )
    from src.services.resolucion_jerarquica import resolve_virtual

    plan = session.get(_Plan, plan_id)
    if plan is None:
        return None

    com_ids = list(session.exec(
        select(_Com.id).where(_Com.plan_cursada_id == plan_id)
    ).all())
    if not com_ids:
        return None
    coms = list(session.exec(
        select(_Com).where(_Com.id.in_(com_ids))  # type: ignore[attr-defined]
    ).all())
    _carrera_override_por_com = {c.id: c.carrera_asignada for c in coms}
    hs_all = list(session.exec(
        select(_Hor).where(_Hor.comision_id.in_(com_ids))  # type: ignore[attr-defined]
    ).all())
    if not hs_all:
        return None

    materias_codes = sorted({h.codigo_materia for h in hs_all})
    materias = list(session.exec(
        select(_Mat).where(_Mat.codigo.in_(materias_codes))  # type: ignore[attr-defined]
    ).all()) if materias_codes else []
    materia_virtual = {m.codigo: m.virtual for m in materias}

    # Virtual del dictado por materia del ciclo del plan.
    materia_dictado_virtual: dict[str, bool | None] = {}
    if plan.ciclo_id is not None:
        for mc, v in session.exec(
            select(_Dict.materia_codigo, _Dict.virtual)
            .join(_DictCic, _Dict.id == _DictCic.dictado_id)  # type: ignore[arg-type]
            .where(_DictCic.ciclo_id == plan.ciclo_id)
        ).all():
            materia_dictado_virtual[mc] = v

    # Filtrar virtuales aplicando la misma jerarquía que el LP.
    horario_slots: list[HorarioSlot] = []
    for h in hs_all:
        if resolve_virtual(
            horario_virtual=h.virtual,
            dictado_virtual=materia_dictado_virtual.get(h.codigo_materia),
            materia_virtual=materia_virtual.get(h.codigo_materia, False),
        ):
            continue
        horario_slots.append(HorarioSlot(
            id=h.id, dia=h.dia,
            hora_inicio=h.hora_inicio, hora_fin=h.hora_fin,
            materia_codigo=h.codigo_materia, tipo_clase=h.tipo_clase,
        ))
    if not horario_slots:
        return None

    # Aulas + sedes.
    aulas_db = list(session.exec(select(AulaDB)).all())
    aulas = [
        AulaSlot(id=a.id, tipo=a.tipo, capacidad=a.capacidad)
        for a in aulas_db
    ]
    aula_sede_id = {a.id: a.sede_id for a in aulas_db}
    sedes = list(session.exec(select(_Sede)).all())
    sede_nombre = {s.id: s.nombre for s in sedes}

    # Materia lab map.
    lab_pairs = list(session.exec(select(_MatLab)).all())
    materia_lab_map: dict[str, set[str]] = {}
    for ml in lab_pairs:
        materia_lab_map.setdefault(ml.materia_codigo, set()).add(ml.aula_id)

    # Sedes admisibles por materia (con override de comisión aplicado
    # al horario, tomando la carrera_asignada de la comisión si existe).
    # `compute_heatmap_por_sede` recibe el dict por-materia; para respetar
    # el override por-comisión hacemos un pre-fold: si TODOS los horarios
    # de una materia comparten el mismo override (o ninguno lo tiene), el
    # dict por-materia es suficiente. Cuando hay override mixto, dejamos
    # las sedes de la materia (fallback conservador) — la corrida del LP
    # sí aplica override por comisión, y el "Detalle de horarios" del
    # inspector también filtra bien por resolve_virtual.
    hs_por_materia: dict[str, list[_Hor]] = {}
    for h in hs_all:
        hs_por_materia.setdefault(h.codigo_materia, []).append(h)
    sedes_admis_por_mat: dict[str, set[str] | None] = {}
    for mc in materias_codes:
        overrides = {
            _carrera_override_por_com.get(h.comision_id)
            for h in hs_por_materia.get(mc, [])
        }
        overrides.discard(None)
        if len(overrides) == 1:
            (_car,) = overrides
            if _car:
                sedes_admis_por_mat[mc] = sedes_admisibles_para_carrera(
                    session, _car,
                )
                continue
        sedes_admis_por_mat[mc] = sedes_admisibles_para_materia(session, mc)

    heatmap = compute_heatmap_por_sede(
        horario_slots, aulas, materia_lab_map,
        sedes_admis_por_mat, aula_sede_id, sede_nombre,
    )

    # Enriquecer con "aulas libres" por celda usando el estado actual
    # de HorarioDB.aula_id. Para cada (sede × día × slot × categoría),
    # calculamos qué aulas del pool están libres — o sea, ninguna
    # HorarioDB del plan con esa aula asignada activa en la celda.
    _agregar_aulas_libres_al_heatmap(
        heatmap,
        horarios_db=hs_all,
        aulas_db=aulas_db,
    )
    return heatmap


def _agregar_aulas_libres_al_heatmap(
    heatmap: dict, horarios_db: list, aulas_db: list,
) -> None:
    """Enriquece cada celda del ``heatmap`` con la lista de aulas
    libres por sede × categoría. Se hace in-place: agrega la key
    ``aulas_libres`` a cada `data[sede][categoria]` como matriz
    [slot][dia] -> list[(aula_nombre, capacidad, tipo)].

    Un aula se considera "libre" en una celda si ningún HorarioDB del
    plan con esa aula asignada al patrón está activo en esa
    celda (día + solapamiento con la franja).
    """
    if not heatmap or "data" not in heatmap:
        return
    dias = heatmap.get("dias", [])
    slots = heatmap.get("slots", [])
    if not dias or not slots:
        return
    n_slots = len(slots)
    n_dias = len(dias)
    dia_idx = {d: i for i, d in enumerate(dias)}

    # Reconstruir slot_bounds desde los labels "HH:MM-HH:MM".
    def _label_to_bounds(lbl: str) -> tuple[int, int]:
        a_txt, b_txt = lbl.split("-")
        ah, am = map(int, a_txt.split(":"))
        bh, bm = map(int, b_txt.split(":"))
        return (ah * 60 + am, bh * 60 + bm)

    slot_bounds = [_label_to_bounds(s) for s in slots]

    # Para cada aula, marcar en qué celdas está ocupada por algún
    # HorarioDB del plan.
    aula_meta = {a.id: (a.nombre, a.capacidad, a.tipo, a.sede_id) for a in aulas_db}
    aulas_por_sede: dict[str, dict[str, list[str]]] = {}
    for aid, (_n, _c, tipo, sede) in aula_meta.items():
        if tipo in ("teorica", "anfiteatro"):
            aulas_por_sede.setdefault(sede, {}).setdefault("teorica", []).append(aid)
        elif tipo == "laboratorio":
            aulas_por_sede.setdefault(sede, {}).setdefault("laboratorio", []).append(aid)

    # Marcar ocupaciones: (aula_id, si, di) -> True si el aula tiene un
    # horario del plan activo en esa celda.
    ocupada: dict[tuple[str, int, int], bool] = {}
    for h in horarios_db:
        if not h.aula_id:
            continue
        di = dia_idx.get(h.dia)
        if di is None:
            continue
        h_s = h.hora_inicio.hour * 60 + h.hora_inicio.minute
        h_e = h.hora_fin.hour * 60 + h.hora_fin.minute
        for si, (a, b) in enumerate(slot_bounds):
            if h_s < b and h_e > a:
                ocupada[(h.aula_id, si, di)] = True

    # Para cada sede × categoría × celda, computar aulas libres.
    for sede_id, cats in aulas_por_sede.items():
        if sede_id not in heatmap["data"]:
            continue
        for cat in ("teorica", "laboratorio"):
            aulas_ids_cat = cats.get(cat, [])
            if cat not in heatmap["data"][sede_id]:
                continue
            libres_matrix: list[list[list[tuple]]] = [
                [[] for _ in range(n_dias)] for _ in range(n_slots)
            ]
            for si in range(n_slots):
                for di in range(n_dias):
                    for aid in aulas_ids_cat:
                        if not ocupada.get((aid, si, di)):
                            nombre, cap, tipo, _sede = aula_meta[aid]
                            libres_matrix[si][di].append(
                                (nombre, cap)
                            )
            heatmap["data"][sede_id][cat]["aulas_libres"] = libres_matrix

        # "peor": aulas libres del tipo con peor ratio. Como el peor
        # varía por celda, usamos la unión de teorica+laboratorio como
        # "todas las aulas libres compatibles" — decisión conservadora.
        if "peor" in heatmap["data"][sede_id]:
            libres_peor: list[list[list[tuple]]] = [
                [[] for _ in range(n_dias)] for _ in range(n_slots)
            ]
            for si in range(n_slots):
                for di in range(n_dias):
                    seen: set[str] = set()
                    for cat in ("teorica", "laboratorio"):
                        lst = heatmap["data"][sede_id].get(cat, {}).get(
                            "aulas_libres", [[]]
                        )
                        if si < len(lst) and di < len(lst[si]):
                            for nom_cap in lst[si][di]:
                                if nom_cap[0] not in seen:
                                    seen.add(nom_cap[0])
                                    libres_peor[si][di].append(nom_cap)
            heatmap["data"][sede_id]["peor"]["aulas_libres"] = libres_peor


def _build_dataframe(
    session: Session, run: LPRunDB,
) -> pd.DataFrame:
    """Arma el DataFrame por horario **leyendo la DB en vivo** (no el
    snapshot del último LPRun).

    El estado de asignación (aula + tipo + capacidad + esperados) se
    calcula sobre el estado actual del plan, respetando ediciones
    manuales, cambios de aulas del catálogo, y cambios de forecast
    o comisiones que hayan ocurrido después de la última corrida.

    Se toman los parámetros de tolerancia y virtualidad del `run` para
    mantener consistencia con la última decisión del asignador.
    """
    from src.services.plan_generation_service import (
        get_inscriptos_esperados_por_comision,
    )
    from src.services.resolucion_jerarquica import resolve_virtual
    from src.database.models import (
        ComisionDB as _Com,
        DictadoCicloDB as _DictCic,
        DictadoDB as _Dict,
        HorarioDB as _Hor,
        MateriaDB as _Mat,
        PlanificacionCursadaDB as _Plan,
    )

    plan = session.get(_Plan, run.plan_cursada_id)
    if plan is None:
        return pd.DataFrame()

    # Traer horarios del plan (filtrando virtuales, mismo criterio que
    # el LP y el heatmap live).
    com_ids = list(session.exec(
        select(_Com.id).where(_Com.plan_cursada_id == plan.id)
    ).all())
    if not com_ids:
        return pd.DataFrame()
    coms = list(session.exec(
        select(_Com).where(_Com.id.in_(com_ids))  # type: ignore[attr-defined]
    ).all())
    coms_map = {c.id: c for c in coms}

    hs_all = list(session.exec(
        select(_Hor).where(_Hor.comision_id.in_(com_ids))  # type: ignore[attr-defined]
    ).all())
    materia_codigos = sorted({h.codigo_materia for h in hs_all})
    materias = list(session.exec(
        select(_Mat).where(_Mat.codigo.in_(materia_codigos))  # type: ignore[attr-defined]
    ).all()) if materia_codigos else []
    materia_virtual = {m.codigo: m.virtual for m in materias}
    mat_map = {m.codigo: m for m in materias}

    materia_dictado_virtual: dict[str, bool | None] = {}
    if plan.ciclo_id is not None:
        for mc, v in session.exec(
            select(_Dict.materia_codigo, _Dict.virtual)
            .join(_DictCic, _Dict.id == _DictCic.dictado_id)  # type: ignore[arg-type]
            .where(_DictCic.ciclo_id == plan.ciclo_id)
        ).all():
            materia_dictado_virtual[mc] = v

    horarios_no_virtuales = [
        h for h in hs_all
        if not resolve_virtual(
            horario_virtual=h.virtual,
            dictado_virtual=materia_dictado_virtual.get(h.codigo_materia),
            materia_virtual=materia_virtual.get(h.codigo_materia, False),
        )
    ]
    if not horarios_no_virtuales:
        return pd.DataFrame()

    # Esperados por comisión (forecast).
    esperados_por_com = get_inscriptos_esperados_por_comision(
        session, plan.id,
    )

    # Aulas + sedes.
    aula_ids = {h.aula_id for h in horarios_no_virtuales if h.aula_id}
    aulas_db_all = list(session.exec(
        select(AulaDB).where(AulaDB.id.in_(aula_ids))  # type: ignore[attr-defined]
    ).all()) if aula_ids else []
    aula_map = {a.id: a for a in aulas_db_all}
    sede_ids = {a.sede_id for a in aulas_db_all if a.sede_id}
    sede_nombre_por_id = {
        s.id: s.nombre for s in session.exec(
            select(SedeDB).where(SedeDB.id.in_(sede_ids))  # type: ignore[attr-defined]
        ).all()
    } if sede_ids else {}

    # Umbrales del último run (para clasificar sobre/sub-ocupación de
    # forma consistente con la corrida vigente).
    tol_over = run.tol_over
    tol_under = run.tol_under

    rows = []
    for h in horarios_no_virtuales:
        com = coms_map.get(h.comision_id)
        mat = mat_map.get(h.codigo_materia)
        aula = aula_map.get(h.aula_id) if h.aula_id else None
        cap = aula.capacidad if aula else 0
        insc = float(esperados_por_com.get(h.comision_id, 0.0) or 0.0)
        delta = cap - insc
        # Estado consistente con LP: sobre si cap < insc*(1-tol_over),
        # sub si cap > insc*(1+tol_under), ok en el medio.
        if insc <= 0:
            estado = "ok"
        elif cap < insc * (1 - tol_over):
            estado = "sobre"
        elif cap > insc * (1 + tol_under):
            estado = "sub"
        else:
            estado = "ok"
        rows.append({
            "Materia": mat.nombre if mat else h.codigo_materia,
            "Comisión": com.nombre if com else "?",
            "Día": h.dia,
            "Inicio": h.hora_inicio.strftime("%H:%M"),
            "Fin": h.hora_fin.strftime("%H:%M"),
            "Aula": aula.nombre if aula else "—",
            "Sede": (
                sede_nombre_por_id.get(aula.sede_id, "—")
                if aula else "—"
            ),
            "Manual": "🔒" if h.aula_asignada_manualmente else "",
            "Cap": cap,
            "Esperados": insc,
            "Δ": delta,
            "Estado": estado,
        })
    df = pd.DataFrame(rows)
    return df


def _color_estado(val: str) -> str:
    """Devuelve un estilo CSS para una celda de la columna Estado."""
    if val == "ok":
        return "background-color: #d4edda; color: #155724"  # verde
    if val == "sub":
        return "background-color: #fff3cd; color: #856404"  # amarillo
    if val == "sobre":
        return "background-color: #f8d7da; color: #721c24"  # rojo
    return ""


def _candidatas_partir_comision(df: pd.DataFrame) -> pd.DataFrame:
    """Materias con horarios sobre-ocupados: Σ over por materia.

    Sirve como sugerencia 'partir comisión' (subir n_comisiones de la
    materia para distribuir alumnos en más aulas).
    """
    if df.empty:
        return df
    sobre = df[df["Estado"] == "sobre"].copy()
    if sobre.empty:
        return sobre
    sobre["Exceso"] = -sobre["Δ"]  # cuántos alumnos quedan afuera
    agg = (
        sobre.groupby("Materia", as_index=False)
        .agg(Comisiones_sobreocupadas=("Comisión", "nunique"),
             Total_exceso=("Exceso", "sum"))
        .sort_values("Total_exceso", ascending=False)
    )
    return agg


# =============================================================================
# Public API
# =============================================================================

def _render_heatmap_por_sede(heatmap_sede: dict, key_ns: str) -> None:
    """Mapa de saturación PARTICIONADO POR SEDE.

    Para cada sede del sistema, renderiza un mini-heatmap (día × franja)
    con la saturación de aulas: cantidad de horarios que la sede admite
    sobre cantidad de aulas disponibles del tipo necesario. Permite ver
    EXACTAMENTE en qué sede × franja × tipo de aula falta capacidad
    (la herramienta principal cuando R10 está apretada).

    El usuario puede filtrar por categoría: 'peor caso' (default,
    máximo entre teóricas y labs), 'teórica' (sólo aulas teóricas/
    anfiteatros), 'laboratorio' (sólo aulas tipo lab). Las sedes sin
    demanda se listan en un expander al final, colapsado.
    """
    if not heatmap_sede or not heatmap_sede.get("sedes"):
        return

    import altair as alt
    import pandas as pd

    st.markdown(
        "**🔥 Mapa de saturación por sede: dónde faltan aulas**"
    )
    st.caption(
        "Cada celda muestra **demanda/oferta** en esa sede para esa "
        "franja. La demanda son los horarios que la sede admite "
        "(según la regla de sedes admisibles: sedes habilitadas para "
        "la carrera de la materia o sede por defecto para materias "
        "comunes, más la compatibilidad de laboratorio). La oferta "
        "son las aulas de la sede del tipo necesario. Verde ≤80% · "
        "amarillo 80–100% · rojo >100% (saturación segura: más "
        "horarios que aulas).  \n"
        "En la vista **peor caso**, la etiqueta incluye "
        "**T** (peor entre teóricas) o **L** (peor entre "
        "laboratorios) para que se distinga en qué categoría satura "
        "cada celda. En el tooltip se ve el desglose completo de las "
        "dos categorías."
    )

    cat_label = {
        "peor": "Peor caso (entre teóricas y laboratorios)",
        "teorica": "Sólo aulas teóricas / anfiteatros",
        "laboratorio": "Sólo aulas laboratorio",
    }
    cat_sel = st.radio(
        "Categoría",
        options=["peor", "teorica", "laboratorio"],
        format_func=lambda c: cat_label[c],
        horizontal=True,
        key=f"{key_ns}_heatsede_cat",
    )

    sedes_meta = heatmap_sede["sedes"]
    dias = heatmap_sede["dias"]
    slots = heatmap_sede["slots"]
    data_all = heatmap_sede["data"]

    sedes_con_demanda = [s for s in sedes_meta if s.get("tiene_demanda")]
    sedes_sin_demanda = [s for s in sedes_meta if not s.get("tiene_demanda")]

    if not sedes_con_demanda:
        st.info(
            "Ninguna sede tiene demanda con la configuración actual "
            "de sedes admisibles. Revisá las sedes habilitadas para "
            "cada carrera."
        )
        return

    color_scale = alt.Scale(
        domain=["vacío", "OK (≤80%)", "ajustado (80–100%)", "saturado (>100%)"],
        range=["#1e1e1e", "#2e7d32", "#f9a825", "#c62828"],
    )

    def _bucket(r: float) -> str:
        if r <= 0:
            return "vacío"
        if r <= 0.8:
            return "OK (≤80%)"
        if r <= 1.0:
            return "ajustado (80–100%)"
        return "saturado (>100%)"

    for sede_meta in sedes_con_demanda:
        sede_id = sede_meta["sede_id"]
        sede_nombre = sede_meta["sede_nombre"]
        n_teo = sede_meta["n_aulas_teoricas"]
        n_lab = sede_meta["n_aulas_laboratorio"]

        cat_data = data_all[sede_id][cat_sel]
        ratio = cat_data["ratio"]
        demanda = cat_data["demanda"]
        oferta = cat_data["oferta"]

        # ¿Hay alguna celda con demanda en esta categoría?
        _hay_dem_cat = any(
            demanda[si][di] > 0
            for si in range(len(slots))
            for di in range(len(dias))
        )
        if not _hay_dem_cat:
            continue

        # Recorte de filas extremas vacías para no llenar pantalla.
        row_sums = [sum(ratio[i]) for i in range(len(slots))]
        nz = [i for i, s in enumerate(row_sums) if s > 0]
        if not nz:
            continue
        i0, i1 = nz[0], nz[-1]
        slots_v = slots[i0:i1 + 1]
        ratio_v = ratio[i0:i1 + 1]
        demanda_v = demanda[i0:i1 + 1]
        oferta_v = oferta[i0:i1 + 1]
        # Aulas libres por celda (opcional; enriquecido en la UI live).
        aulas_libres_raw = cat_data.get("aulas_libres")
        if aulas_libres_raw:
            aulas_libres_v = aulas_libres_raw[i0:i1 + 1]
        else:
            aulas_libres_v = None

        # Resumen para el header del expander: max ratio + un emoji
        # según el peor bucket de la sede. Expandido por default sólo
        # si hay saturación (ratio > 1), para que la primera mirada
        # destaque los problemas y el usuario pueda colapsar lo que
        # no le interesa.
        max_ratio = 0.0
        max_demanda = 0
        max_oferta = 0
        for si in range(len(slots_v)):
            for di in range(len(dias)):
                if ratio_v[si][di] > max_ratio:
                    max_ratio = ratio_v[si][di]
                    max_demanda = int(demanda_v[si][di])
                    max_oferta = int(oferta_v[si][di])
        if max_ratio > 1.0:
            emoji = "🔴"
        elif max_ratio > 0.8:
            emoji = "🟡"
        else:
            emoji = "🟢"
        if max_oferta > 0:
            resumen = f"peor {max_demanda}/{max_oferta} ({max_ratio:.2f})"
        else:
            resumen = "sin oferta"
        header = (
            f"{emoji} 🏛 {sede_nombre} · {n_teo} teórica(s) · "
            f"{n_lab} laboratorio(s) · {resumen}"
        )

        def _fmt_libres(items: list) -> str:
            if not items:
                return "(ninguna)"
            # items: list de (nombre, capacidad)
            n = len(items)
            visibles = items[:6]
            piezas = [f"{nombre} ({cap})" for nombre, cap in visibles]
            txt = ", ".join(piezas)
            if n > 6:
                txt += f", +{n - 6} más"
            return txt

        # Para la vista "peor" traemos también las matrices de teorica
        # y laboratorio para poder enriquecer el tooltip con datos por
        # categoría. Cuando la vista es una categoría fija, no aplica.
        _cat_gan_v = None
        _teo_demanda_v = None
        _teo_oferta_v = None
        _lab_demanda_v = None
        _lab_oferta_v = None
        if cat_sel == "peor":
            _cat_gan_raw = cat_data.get("cat_ganadora")
            if _cat_gan_raw:
                _cat_gan_v = _cat_gan_raw[i0:i1 + 1]
            _teo = data_all[sede_id].get("teorica", {})
            _lab = data_all[sede_id].get("laboratorio", {})
            _teo_demanda_v = _teo.get("demanda", [])[i0:i1 + 1] or None
            _teo_oferta_v = _teo.get("oferta", [])[i0:i1 + 1] or None
            _lab_demanda_v = _lab.get("demanda", [])[i0:i1 + 1] or None
            _lab_oferta_v = _lab.get("oferta", [])[i0:i1 + 1] or None

        _CAT_ABREV = {"teorica": "T", "laboratorio": "L"}
        _CAT_NOMBRE = {"teorica": "Teóricas", "laboratorio": "Laboratorios"}

        with st.expander(header, expanded=max_ratio > 1.0):
            long_rows = []
            for si, slot_label in enumerate(slots_v):
                for di, dia in enumerate(dias):
                    d = int(demanda_v[si][di])
                    o = int(oferta_v[si][di])
                    r_ = float(ratio_v[si][di])
                    libres_lst = (
                        aulas_libres_v[si][di]
                        if aulas_libres_v is not None
                        else []
                    )
                    n_libres = len(libres_lst)
                    libres_str = _fmt_libres(libres_lst)
                    # Categoría ganadora + etiqueta con abreviatura.
                    cat_gan = ""
                    if _cat_gan_v is not None:
                        cat_gan = _cat_gan_v[si][di]
                    if d > 0:
                        abrev = _CAT_ABREV.get(cat_gan, "")
                        etiqueta = (
                            f"{d}/{o} {abrev}".strip()
                            if abrev else f"{d}/{o}"
                        )
                        cat_nombre = _CAT_NOMBRE.get(cat_gan, "—")
                    else:
                        etiqueta = ""
                        cat_nombre = "—"
                    # Desglose demanda/oferta por categoría para tooltip.
                    if (
                        _teo_demanda_v is not None
                        and _teo_oferta_v is not None
                    ):
                        t_d = int(_teo_demanda_v[si][di]) if _teo_demanda_v[si] else 0
                        t_o = int(_teo_oferta_v[si][di]) if _teo_oferta_v[si] else 0
                    else:
                        t_d, t_o = 0, 0
                    if (
                        _lab_demanda_v is not None
                        and _lab_oferta_v is not None
                    ):
                        l_d = int(_lab_demanda_v[si][di]) if _lab_demanda_v[si] else 0
                        l_o = int(_lab_oferta_v[si][di]) if _lab_oferta_v[si] else 0
                    else:
                        l_d, l_o = 0, 0
                    teo_txt = f"{t_d}/{t_o}" if t_o or t_d else "—"
                    lab_txt = f"{l_d}/{l_o}" if l_o or l_d else "—"

                    long_rows.append({
                        "slot": slot_label,
                        "dia": dia,
                        "demanda": d,
                        "oferta": o,
                        "ratio": r_,
                        "bucket": _bucket(r_),
                        "etiqueta": etiqueta,
                        "n_libres": n_libres,
                        "aulas_libres": libres_str,
                        "cat_ganadora": cat_nombre,
                        "teorica_txt": teo_txt,
                        "laboratorio_txt": lab_txt,
                    })
            df_long = pd.DataFrame(long_rows)

            base = alt.Chart(df_long).encode(
                x=alt.X(
                    "dia:N", title=None, sort=dias,
                    axis=alt.Axis(
                        orient="top", labelAngle=0, labelFontSize=11,
                    ),
                ),
                y=alt.Y(
                    "slot:N", title=None, sort=slots_v,
                    axis=alt.Axis(labelFontSize=10),
                ),
            )
            rect = base.mark_rect(stroke="#444", strokeWidth=0.5).encode(
                color=alt.Color(
                    "bucket:N",
                    scale=color_scale,
                    legend=alt.Legend(title="Saturación"),
                ),
                tooltip=[
                    alt.Tooltip("dia:N", title="Día"),
                    alt.Tooltip("slot:N", title="Franja"),
                    alt.Tooltip("cat_ganadora:N", title="Categoría peor"),
                    alt.Tooltip("demanda:Q", title="Horarios (peor)"),
                    alt.Tooltip("oferta:Q", title="Aulas (peor)"),
                    alt.Tooltip("ratio:Q", title="Ratio", format=".2f"),
                    alt.Tooltip("teorica_txt:N", title="Teóricas d/o"),
                    alt.Tooltip("laboratorio_txt:N", title="Laboratorios d/o"),
                    alt.Tooltip("n_libres:Q", title="N° aulas libres"),
                    alt.Tooltip("aulas_libres:N", title="Aulas libres"),
                ],
            )
            text = base.mark_text(fontSize=9, fontWeight="bold").encode(
                text=alt.Text("etiqueta:N"),
                color=alt.condition(
                    "datum.ratio > 0.5",
                    alt.value("white"),
                    alt.value("#bbb"),
                ),
            )
            chart = (rect + text).properties(
                width="container",
                height=max(280, len(slots_v) * 22),
            )
            st.altair_chart(chart, use_container_width=True)

    if sedes_sin_demanda:
        with st.expander(
            f"Sedes sin demanda ({len(sedes_sin_demanda)})",
            expanded=False,
        ):
            for s in sedes_sin_demanda:
                st.caption(
                    f"🏛 {s['sede_nombre']}: "
                    f"{s['n_aulas_teoricas']} teórica(s) + "
                    f"{s['n_aulas_laboratorio']} laboratorio(s) — "
                    "sin demanda"
                )


@st.dialog("Editar horario")
def _dialog_editar_horario(
    plan_id: str, horario_id: str,
    materia_label: str, comision_label: str,
    heatmap_sede: Optional[dict] = None,
    sede_id_inspeccionada: Optional[str] = None,
    tipo_filtro: str = "Todas",
) -> None:
    """Modal para cambiar día/hora de un horario, con preview de
    validaciones antes de persistir.

    Sólo permite editar día, hora_inicio y hora_fin. NO toca comisión
    ni tipo (eso se hace desde otras vistas).
    """
    from datetime import time as _time
    from src.database.connection import get_session
    from src.database.models import HorarioDB as _HorarioDB
    from src.services.plan_actions_service import (
        aplicar_cambio_horario,
        preview_cambio_horario,
    )

    with next(get_session()) as _sess:
        h = _sess.get(_HorarioDB, horario_id)
        if h is None:
            st.error("Horario no encontrado.")
            return
        actual_dia = h.dia
        actual_hi = h.hora_inicio
        actual_hf = h.hora_fin
        actual_virtual = h.virtual  # Optional[bool]

    _virtual_lbl_map = {None: "Heredar", True: "Sí", False: "No"}
    _actual_virtual_lbl = _virtual_lbl_map.get(actual_virtual, "Heredar")
    st.markdown(
        f"**Materia:** {materia_label}  \n"
        f"**Comisión:** {comision_label}  \n"
        f"**Actual:** {actual_dia} "
        f"{actual_hi.strftime('%H:%M')}–{actual_hf.strftime('%H:%M')}  \n"
        f"**Virtual actual:** {_actual_virtual_lbl}"
    )
    st.divider()

    DIAS_LIST = ["Lunes", "Martes", "Miércoles", "Jueves", "Viernes", "Sábado"]
    c1, c2, c3 = st.columns(3)
    with c1:
        nuevo_dia = st.selectbox(
            "Nuevo día",
            options=DIAS_LIST,
            index=DIAS_LIST.index(actual_dia)
            if actual_dia in DIAS_LIST else 0,
            key=f"edith_{horario_id}_dia",
        )
    with c2:
        nuevo_hi = st.time_input(
            "Inicio",
            value=actual_hi,
            step=900,  # 15 min
            key=f"edith_{horario_id}_hi",
        )
    with c3:
        nuevo_hf = st.time_input(
            "Fin",
            value=actual_hf,
            step=900,
            key=f"edith_{horario_id}_hf",
        )

    # Selector "Virtual": permite marcar el horario como virtual desde
    # el inspector de franja. Sacar un horario a virtual descomprime la
    # franja sin tener que moverlo (el LP no le asigna aula).
    _v_labels = ["Heredar", "Sí", "No"]
    nuevo_virtual_lbl = st.selectbox(
        "Virtual",
        options=_v_labels,
        index=_v_labels.index(_actual_virtual_lbl)
        if _actual_virtual_lbl in _v_labels else 0,
        key=f"edith_{horario_id}_virtual",
        help=(
            "Marcar el horario como virtual descomprime la franja sin "
            "moverlo (la asignación no le busca aula). Heredar = usa lo "
            "que dice el dictado o la materia. Sí = fuerza virtual. "
            "No = fuerza presencial (aunque el dictado sea virtual)."
        ),
    )
    _new_virtual_val = {"Heredar": None, "Sí": True, "No": False}.get(
        nuevo_virtual_lbl
    )
    _virtual_cambia = _new_virtual_val != actual_virtual

    sin_cambio = (
        nuevo_dia == actual_dia
        and nuevo_hi == actual_hi
        and nuevo_hf == actual_hf
        and not _virtual_cambia
    )

    # Preview de validaciones. Solo hace falta cuando cambia el slot
    # (día/hora), porque ahí es donde se puede generar choque o
    # conflicto de paralelismo. Si el único cambio es `virtual`, se
    # omite el preview (no altera slot ni asignación de aula fuera
    # de este horario).
    _slot_cambia = (
        nuevo_dia != actual_dia
        or nuevo_hi != actual_hi
        or nuevo_hf != actual_hf
    )
    preview = None
    if _slot_cambia:
        with next(get_session()) as _sess:
            preview = preview_cambio_horario(
                _sess, plan_id, horario_id,
                nuevo_dia, nuevo_hi, nuevo_hf,
            )

    # Saturación de las franjas destino — para confirmar que no
    # estamos trasladando el problema a otra franja también saturada.
    # Sólo aplica si tenemos heatmap_sede e info de sede.
    if (
        _slot_cambia
        and heatmap_sede is not None
        and sede_id_inspeccionada is not None
        and preview is not None
        and preview.error is None
    ):
        _slots_all = heatmap_sede.get("slots", [])
        _dias_hm = heatmap_sede.get("dias", [])
        _cat_destino = {
            "Todas": "peor",
            "Sólo teóricas": "teorica",
            "Sólo laboratorios": "laboratorio",
        }.get(tipo_filtro, "peor")
        _data_destino = (
            heatmap_sede["data"]
            .get(sede_id_inspeccionada, {})
            .get(_cat_destino)
        )
        if _data_destino is not None:
            # Identificar las celdas que el horario nuevo cubre
            # (excluyendo el propio horario que se va a mover).
            _h_ini_min = nuevo_hi.hour * 60 + nuevo_hi.minute
            _h_fin_min = nuevo_hf.hour * 60 + nuevo_hf.minute
            _di_destino = None
            for i, d in enumerate(_dias_hm):
                if d == nuevo_dia:
                    _di_destino = i
                    break
            _filas_dest = []
            if _di_destino is not None:
                for si, slot in enumerate(_slots_all):
                    try:
                        ini, fin = slot.split("-")
                        s_h, s_m = ini.split(":")
                        f_h, f_m = fin.split(":")
                        s_min = int(s_h) * 60 + int(s_m)
                        f_min = int(f_h) * 60 + int(f_m)
                    except (ValueError, IndexError):
                        continue
                    if s_min < _h_fin_min and f_min > _h_ini_min:
                        d_act = _data_destino["demanda"][si][_di_destino]
                        o_act = _data_destino["oferta"][si][_di_destino]
                        # Si el horario YA está en este día, la celda
                        # ya cuenta su demanda; al moverlo dentro del
                        # mismo día, no agregaría +1. Si se mueve a
                        # OTRO día, sí.
                        suma_propio = 0 if preview.actual.get("dia") == nuevo_dia else 1
                        d_post = d_act + suma_propio
                        ratio_post = (d_post / o_act) if o_act > 0 else 999.0
                        if ratio_post > 1.0:
                            estado = "🔴 saturado"
                        elif ratio_post > 0.8:
                            estado = "🟡 ajustado"
                        else:
                            estado = "🟢 OK"
                        _filas_dest.append({
                            "Franja": slot,
                            "Demanda actual": d_act,
                            "Demanda post-cambio": d_post,
                            "Oferta": o_act,
                            "Estado post-cambio": estado,
                        })
            if _filas_dest:
                _hay_saturada = any(
                    "🔴" in r["Estado post-cambio"] for r in _filas_dest
                )
                if _hay_saturada:
                    st.warning(
                        f"⚠️ Algunas franjas destino ({nuevo_dia} "
                        f"{nuevo_hi.strftime('%H:%M')}–"
                        f"{nuevo_hf.strftime('%H:%M')}) **ya están "
                        "saturadas**. Mover el horario podría sólo "
                        "trasladar el problema."
                    )
                else:
                    st.info(
                        f"ℹ️ Estado de saturación en las franjas "
                        f"destino ({nuevo_dia} "
                        f"{nuevo_hi.strftime('%H:%M')}–"
                        f"{nuevo_hf.strftime('%H:%M')}):"
                    )
                st.dataframe(
                    _filas_dest,
                    hide_index=True,
                    use_container_width=True,
                )

    if preview is not None:
        if preview.error:
            st.error(f"❌ {preview.error}")
        else:
            # Advertencia de duplicado mismo día (independiente de los
            # conflictos formales): si ya hay otro horario de la misma
            # comisión ese día, probablemente sea un error operativo.
            if preview.duplicados_mismo_dia:
                st.warning(
                    f"⚠️ La comisión ya tiene "
                    f"**{len(preview.duplicados_mismo_dia)} clase(s)** "
                    f"el {preview.propuesto['dia']}. "
                    "Una comisión normalmente tiene una sola clase por "
                    "día. ¿Seguro querés moverla acá?"
                )
                with st.expander(
                    "Ver horarios existentes de la comisión "
                    f"el {preview.propuesto['dia']}",
                    expanded=False,
                ):
                    st.dataframe(
                        [
                            {
                                "Día": d["dia"],
                                "Inicio": d["hora_inicio"],
                                "Fin": d["hora_fin"],
                            }
                            for d in preview.duplicados_mismo_dia
                        ],
                        hide_index=True,
                        use_container_width=True,
                    )

            if preview.conflictos_agregados:
                st.warning(
                    f"⚠️ Este cambio agregaría "
                    f"**{len(preview.conflictos_agregados)} conflicto(s) "
                    "nuevo(s)** de paralelismo en cohortes."
                )
                with st.expander(
                    f"Ver detalle ({len(preview.conflictos_agregados)})",
                    expanded=True,
                ):
                    rows = []
                    for c in preview.conflictos_agregados:
                        rows.append({
                            "Carrera": c.get("carrera_codigo"),
                            "Año": c.get("anio_plan"),
                            "Cuatri": c.get("cuatrimestre_plan"),
                            "Día": c.get("dia"),
                            "Materia A": c.get("materia_a"),
                            "Horario A": (
                                f"{c.get('hora_inicio_a')}–"
                                f"{c.get('hora_fin_a')}"
                            ),
                            "Materia B": c.get("materia_b"),
                            "Horario B": (
                                f"{c.get('hora_inicio_b')}–"
                                f"{c.get('hora_fin_b')}"
                            ),
                        })
                    st.dataframe(
                        rows, hide_index=True, use_container_width=True,
                    )

            if preview.es_seguro:
                msg_partes = [
                    "✅ El cambio NO agrega conflictos nuevos ni "
                    "duplica el día de la comisión."
                ]
                if preview.conflictos_resueltos:
                    msg_partes.append(
                        f"Además **resuelve "
                        f"{len(preview.conflictos_resueltos)} "
                        "conflicto(s) existente(s)**."
                    )
                st.success(" ".join(msg_partes))
            elif preview.conflictos_resueltos:
                st.info(
                    f"ℹ️ Pero también **resuelve "
                    f"{len(preview.conflictos_resueltos)} "
                    "conflicto(s) existente(s)**."
                )

    st.divider()

    def _persist_virtual_if_changed(_sess) -> bool:
        """Persiste HorarioDB.virtual si cambió. Devuelve True si tocó
        algo. Corrida en la misma session que la del cambio de slot
        (si aplica) para commit atómico."""
        if not _virtual_cambia:
            return False
        _db_h = _sess.get(_HorarioDB, horario_id)
        if _db_h is None:
            return False
        _db_h.virtual = _new_virtual_val
        _sess.add(_db_h)
        return True

    col_ok, col_cancel = st.columns(2)
    with col_ok:
        # Casos:
        # A) sin cambios → botón deshabilitado.
        # B) solo cambia virtual → aplicar sin preview (no toca slot).
        # C) cambia slot pero preview es None/error → bloquear.
        # D) cambia slot con preview OK → aplicar (y persistir virtual
        #    también si cambió, en la misma pasada).
        if sin_cambio:
            st.button(
                "Sin cambios",
                disabled=True,
                use_container_width=True,
                key=f"edith_{horario_id}_save_disabled",
            )
        elif not _slot_cambia and _virtual_cambia:
            # Caso B: sólo virtual.
            if st.button(
                "✅ Aplicar cambio de virtualidad",
                type="primary",
                use_container_width=True,
                key=f"edith_{horario_id}_save_virtual",
            ):
                with next(get_session()) as _sess:
                    _persist_virtual_if_changed(_sess)
                    _sess.commit()
                st.success(
                    "Virtualidad del horario actualizada."
                )
                st.rerun()
        elif preview is None or preview.error:
            # Caso C.
            st.button(
                "Confirmar y aplicar",
                disabled=True,
                use_container_width=True,
                key=f"edith_{horario_id}_save_blocked",
            )
        else:
            # Caso D.
            label = (
                "✅ Confirmar y aplicar"
                if preview.es_seguro
                else "⚠️ Aplicar igual (con conflictos)"
            )
            btn_type = "primary" if preview.es_seguro else "secondary"
            if st.button(
                label,
                type=btn_type,
                use_container_width=True,
                key=f"edith_{horario_id}_save",
            ):
                with next(get_session()) as _sess:
                    ok = aplicar_cambio_horario(
                        _sess, horario_id,
                        nuevo_dia, nuevo_hi, nuevo_hf,
                    )
                    if ok:
                        _persist_virtual_if_changed(_sess)
                        _sess.commit()
                if ok:
                    st.success("Horario actualizado.")
                    st.rerun()
                else:
                    st.error("No se pudo actualizar (horario inexistente).")
    with col_cancel:
        if st.button(
            "Cancelar",
            use_container_width=True,
            key=f"edith_{horario_id}_cancel",
        ):
            st.rerun()


def _render_inspector_franja(
    heatmap_sede: dict, plan_id: str, key_ns: str,
) -> None:
    """Inspector de franja: dado uno o más días + slots, muestra los
    horarios que intersectan en un calendario semanal, coloreados por
    carrera (para detectar visualmente cohortes que no se pueden
    mover entre sí).

    Permite ver si una saturación se puede resolver moviendo algún
    horario a otra franja/día con menos demanda.
    """
    sedes_meta = heatmap_sede.get("sedes", [])
    sedes_con_demanda = [s for s in sedes_meta if s.get("tiene_demanda")]
    if not sedes_con_demanda:
        st.caption("No hay sedes con demanda; nada para inspeccionar.")
        return

    DIAS_LIST = ["Lunes", "Martes", "Miércoles", "Jueves", "Viernes", "Sábado"]

    st.caption(
        "Seleccioná uno o más días y una o más franjas (15 min) para "
        "inspeccionar. El cronograma muestra cada horario **completo** "
        "(no recortado al rango) coloreado por **carrera** — bloques "
        "del mismo color son de la misma carrera y no se pueden mover "
        "entre sí. Útil para evaluar si un horario se puede mover a "
        "una franja con disponibilidad."
    )

    c1, c_tipo, c2, c3 = st.columns([2, 1.5, 2, 3])
    with c1:
        sel_sede_id = st.selectbox(
            "Sede",
            options=[s["sede_id"] for s in sedes_con_demanda],
            format_func=lambda sid: next(
                s["sede_nombre"] for s in sedes_con_demanda
                if s["sede_id"] == sid
            ),
            key=f"{key_ns}_inspect_sede",
        )
    with c_tipo:
        sel_tipo = st.selectbox(
            "Tipo de aula",
            options=["Todas", "Sólo teóricas", "Sólo laboratorios"],
            index=0,
            key=f"{key_ns}_inspect_tipo",
            help=(
                "Filtra los horarios mostrados según el tipo de aula "
                "que requieren. Útil cuando el problema está en un "
                "solo tipo (p.ej. faltan teóricas)."
            ),
        )
    with c2:
        sel_dia = st.selectbox(
            "Día",
            options=["— elegir —"] + DIAS_LIST,
            index=0,
            key=f"{key_ns}_inspect_dia",
            help=(
                "Sólo un día por vez para que el calendario tenga "
                "espacio suficiente. Para comparar días, hay que "
                "cambiar el día y mirar otra vez."
            ),
        )
        sel_dias = [sel_dia] if sel_dia != "— elegir —" else []
    with c3:
        slots_all = heatmap_sede.get("slots", [])
        c3a, c3b = st.columns(2)
        with c3a:
            sel_slot_desde = st.selectbox(
                "Desde",
                options=["— elegir —"] + slots_all,
                index=0,
                key=f"{key_ns}_inspect_slot_desde",
                help=(
                    "Franja inicial del rango a inspeccionar (15 min)."
                ),
            )
        with c3b:
            sel_slot_hasta = st.selectbox(
                "Hasta",
                options=["— elegir —"] + slots_all,
                index=0,
                key=f"{key_ns}_inspect_slot_hasta",
                help=(
                    "Franja final del rango (inclusive)."
                ),
            )
    # Resolver el rango [desde, hasta].
    if (
        sel_slot_desde in ("— elegir —",)
        or sel_slot_hasta in ("— elegir —",)
    ):
        sel_slots: list[str] = []
    else:
        i_desde = slots_all.index(sel_slot_desde)
        i_hasta = slots_all.index(sel_slot_hasta)
        if i_desde > i_hasta:
            st.error(
                "La franja **Desde** debe ser anterior o igual a **Hasta**."
            )
            return
        sel_slots = slots_all[i_desde:i_hasta + 1]
    if not sel_dias or not sel_slots:
        st.info(
            "Seleccioná día y rango horario (desde/hasta) para "
            "inspeccionar."
        )
        return

    # ─── Lógica real: cargar datos del plan ───
    from sqlmodel import select as _select
    from src.database.connection import get_session
    from src.database.models import (
        AulaDB as _AulaDB,
        CarreraDB as _CarreraDB,
        ComisionDB as _ComisionDB,
        DictadoCicloDB as _DictadoCicloDB,
        DictadoDB as _DictadoDB,
        HorarioDB as _HorarioDB,
        MateriaDB as _MateriaDB,
        MateriaLaboratorioDB as _MateriaLabDB,
        PlanEstudioDB as _PlanEstudioDB,
        PlanificacionCursadaDB as _PlanificacionCursadaDB,
    )
    from src.services.asignacion_aulas_helpers import (
        HorarioSlot as _HorarioSlot,
        horarios_que_intersectan_rango,
    )
    from src.services.carrera_sede_service import (
        sedes_admisibles_para_materia as _sedes_admis,
    )
    from src.services.plan_generation_service import TimetableBlock
    from src.ui.calendar_render import render_timetable_calendar
    from src.database.crud import get_or_create_config

    with next(get_session()) as _s:
        # Comisiones del plan → horarios.
        com_ids = list(_s.exec(
            _select(_ComisionDB.id).where(
                _ComisionDB.plan_cursada_id == plan_id,
            )
        ).all())
        if not com_ids:
            st.warning("El plan no tiene comisiones cargadas.")
            return
        coms = list(_s.exec(
            _select(_ComisionDB).where(
                _ComisionDB.id.in_(com_ids)  # type: ignore[attr-defined]
            )
        ).all())
        com_map = {c.id: c for c in coms}
        horarios_db_all = list(_s.exec(
            _select(_HorarioDB).where(
                _HorarioDB.comision_id.in_(com_ids)  # type: ignore[attr-defined]
            )
        ).all())
        materias_codes = sorted({h.codigo_materia for h in horarios_db_all})
        materias_db = list(_s.exec(
            _select(_MateriaDB).where(
                _MateriaDB.codigo.in_(materias_codes)  # type: ignore[attr-defined]
            )
        ).all()) if materias_codes else []
        mat_map = {m.codigo: m for m in materias_db}

        # Filtrar horarios virtuales — mismo criterio que build_inputs
        # del LP: resolucion jerarquica horario > dictado > materia.
        # Sin este filtro, el inspector cuenta mas horarios que el heatmap.
        from src.services.resolucion_jerarquica import (
            resolve_virtual as _resolve_virtual,
        )
        materia_virtual = {m.codigo: m.virtual for m in materias_db}
        plan_obj = _s.get(_PlanificacionCursadaDB, plan_id)
        materia_dictado_virtual: dict[str, bool | None] = {}
        if plan_obj is not None and plan_obj.ciclo_id is not None:
            dict_rows = _s.exec(
                _select(_DictadoDB.materia_codigo, _DictadoDB.virtual)
                .join(
                    _DictadoCicloDB,
                    _DictadoDB.id == _DictadoCicloDB.dictado_id,  # type: ignore[arg-type]
                )
                .where(_DictadoCicloDB.ciclo_id == plan_obj.ciclo_id)
            ).all()
            for mc, es_virt in dict_rows:
                materia_dictado_virtual[mc] = es_virt
        horarios_db = [
            h for h in horarios_db_all
            if not _resolve_virtual(
                horario_virtual=h.virtual,
                dictado_virtual=materia_dictado_virtual.get(h.codigo_materia),
                materia_virtual=materia_virtual.get(h.codigo_materia, False),
            )
        ]

        # Sedes admisibles por materia.
        sedes_admis_por_mat: dict[str, set[str] | None] = {
            mc: _sedes_admis(_s, mc) for mc in materias_codes
        }

        # Lab compatibles por materia.
        lab_pairs = list(_s.exec(_select(_MateriaLabDB)).all())
        materia_lab_map: dict[str, set[str]] = {}
        for ml in lab_pairs:
            materia_lab_map.setdefault(ml.materia_codigo, set()).add(ml.aula_id)

        # Aula → sede.
        aulas_db = list(_s.exec(_select(_AulaDB)).all())
        aula_sede_id_map = {a.id: a.sede_id for a in aulas_db}

        # Carrera por materia: una materia es exclusiva de una carrera
        # si aparece en una sola; común si en >=2.
        pe_rows = list(_s.exec(
            _select(_PlanEstudioDB).where(
                _PlanEstudioDB.materia_codigo.in_(materias_codes)  # type: ignore[attr-defined]
            )
        ).all()) if materias_codes else []
        materia_carreras: dict[str, set[str]] = {}
        # Ubicacion curricular (anio, cuatri) por (materia, carrera).
        # Usamos la primera row encontrada — si hay varias versiones de
        # plan para la misma carrera, el dato suele coincidir; si no,
        # la mas reciente queda priorizada al ordenar por fecha.
        materia_carrera_ubic: dict[tuple[str, str], tuple[int | None, str | None]] = {}
        for pe in pe_rows:
            materia_carreras.setdefault(pe.materia_codigo, set()).add(
                pe.carrera_codigo,
            )
            key = (pe.materia_codigo, pe.carrera_codigo)
            # Sólo escribir si todavía no tenemos un dato no-vacío.
            existente = materia_carrera_ubic.get(key)
            if (
                existente is None
                or (existente[0] is None and existente[1] is None)
            ):
                materia_carrera_ubic[key] = (pe.anio_plan, pe.cuatrimestre_plan)
        carreras_codes = sorted({
            c for cs in materia_carreras.values() for c in cs
        })
        carreras_db = list(_s.exec(
            _select(_CarreraDB).where(
                _CarreraDB.codigo.in_(carreras_codes)  # type: ignore[attr-defined]
            )
        ).all()) if carreras_codes else []
        carrera_nombre = {c.codigo: c.nombre for c in carreras_db}

        config = get_or_create_config(_s)

    # Convertir a HorarioSlot para reusar el helper.
    horario_slots = [
        _HorarioSlot(
            id=h.id, dia=h.dia,
            hora_inicio=h.hora_inicio, hora_fin=h.hora_fin,
            materia_codigo=h.codigo_materia, tipo_clase=h.tipo_clase,
        )
        for h in horarios_db
    ]
    horario_slot_map = {h.id: h for h in horario_slots}

    # Sólo demandantes de la sede inspeccionada — alinea exactamente con
    # la demanda que cuenta el heatmap por sede. Los horarios cuya R10
    # no admite esta sede no aparecen (no aportan al diagnóstico).
    res = horarios_que_intersectan_rango(
        horarios=horario_slots,
        dias_seleccionados=sel_dias,
        slots_seleccionados=sel_slots,
        sedes_admisibles_por_materia=sedes_admis_por_mat,
        sede_id_inspeccionada=sel_sede_id,
        materia_lab_map=materia_lab_map,
        aula_sede_id=aula_sede_id_map,
        incluir_no_demandantes=False,
    )
    items = res["horarios"]

    # Filtro por tipo de aula requerido.
    # - "Sólo teóricas": horarios con tipo_clase=teorica o None (los
    #   None caen en teórica si la materia tiene hlab=0, caso típico).
    # - "Sólo laboratorios": horarios con tipo_clase=laboratorio.
    # - "Todas": sin filtro.
    if sel_tipo == "Sólo teóricas":
        items = [
            it for it in items
            if it["tipo_clase"] != "laboratorio"
        ]
    elif sel_tipo == "Sólo laboratorios":
        items = [
            it for it in items
            if it["tipo_clase"] == "laboratorio"
        ]

    sede_nom = next(
        s["sede_nombre"] for s in sedes_con_demanda
        if s["sede_id"] == sel_sede_id
    )
    st.markdown(
        f"**Inspeccionando:** {sede_nom} · "
        f"{', '.join(sel_dias)} · "
        f"{len(sel_slots)} franja(s) "
        f"({sel_slots[0]}"
        + (f" → {sel_slots[-1]}" if len(sel_slots) > 1 else "")
        + ")"
        + (f" · filtro: {sel_tipo}" if sel_tipo != "Todas" else "")
    )
    st.caption(
        f"**{len(items)} horario(s)** demandan {sede_nom} en este "
        "rango. Mismo criterio que el mapa de saturación: se "
        "excluyen virtuales y horarios cuya carrera no usa esta "
        "sede (por la regla de sedes admisibles). Cada bloque se "
        "muestra **completo** (de su hora de inicio a hora de fin) "
        "aunque cubra parcialmente el rango. Color por **carrera** "
        "— bloques del mismo color son de la misma carrera y por lo "
        "tanto NO se pueden mover entre sí (rompería la cohorte)."
    )

    if not items:
        st.success(
            "✅ Ningún horario intersecta el rango seleccionado."
        )
        return

    # Construir grid_data para el calendario y filas para tabla.
    grid_data: dict[str, list[TimetableBlock]] = {}
    tabla_rows: list[dict] = []
    for it in items:
        h_id = it["horario_id"]
        h_db = next((h for h in horarios_db if h.id == h_id), None)
        if h_db is None:
            continue
        com = com_map.get(h_db.comision_id)
        mat = mat_map.get(h_db.codigo_materia)
        carreras_de_mat = materia_carreras.get(h_db.codigo_materia, set())
        ubicacion_label = "—"
        if len(carreras_de_mat) == 1:
            (car_codigo,) = tuple(carreras_de_mat)
            car_label = carrera_nombre.get(car_codigo, car_codigo)
            car_pretty = car_label
            anio, cuatri = materia_carrera_ubic.get(
                (h_db.codigo_materia, car_codigo), (None, None),
            )
            # Format: "3° 1C" / "5° Anual" / "1°" si falta cuatri /
            # "1C" si falta año / "—" si ambos None.
            if anio is not None and cuatri is not None:
                ubicacion_label = f"{anio}° {cuatri}"
            elif anio is not None:
                ubicacion_label = f"{anio}°"
            elif cuatri is not None:
                ubicacion_label = cuatri
        elif len(carreras_de_mat) >= 2:
            car_codigo = None
            car_label = None
            car_pretty = "— Común (varias carreras) —"
            # Para comunes no mostramos ubicacion (varia entre carreras).
        else:
            car_codigo = None
            car_label = None
            car_pretty = "—"

        block = TimetableBlock(
            materia_codigo=h_db.codigo_materia,
            materia_nombre=mat.nombre if mat else h_db.codigo_materia,
            comision_nombre=com.nombre if com else "?",
            hora_inicio=h_db.hora_inicio,
            hora_fin=h_db.hora_fin,
            virtual=False,
            en_periodo=True,
            aula_label=None,
            carrera_codigo=car_codigo,
            carrera_label=car_label,
        )
        grid_data.setdefault(h_db.dia, []).append(block)

        tabla_rows.append({
            "horario_id": h_db.id,
            "Día": h_db.dia,
            "Inicio": h_db.hora_inicio.strftime("%H:%M"),
            "Fin": h_db.hora_fin.strftime("%H:%M"),
            "Materia": (
                f"{h_db.codigo_materia} — {mat.nombre}"
                if mat else h_db.codigo_materia
            ),
            "Comisión": com.nombre if com else "?",
            "Tipo": h_db.tipo_clase or "sin determinar",
            "Carrera": car_pretty,
            "Ubicación": ubicacion_label,
        })

    # Rango horario acotado al min de hora_inicio y max de hora_fin
    # de los bloques mostrados (con un padding de 30 min de cada lado
    # para que no quede el bloque pegado al borde). Si los items
    # quedaron vacíos por el filtro, omitimos el override.
    from datetime import time as _time_for_range
    _h_min = None
    _h_max = None
    if items:
        all_blocks = [b for blocks in grid_data.values() for b in blocks]
        if all_blocks:
            _min_mins = min(
                b.hora_inicio.hour * 60 + b.hora_inicio.minute
                for b in all_blocks
            )
            _max_mins = max(
                b.hora_fin.hour * 60 + b.hora_fin.minute
                for b in all_blocks
            )
            # Padding de 30 min, sin salirse de [00:00, 23:59].
            _min_mins = max(0, _min_mins - 30)
            _max_mins = min(23 * 60 + 59, _max_mins + 30)
            _h_min = _time_for_range(_min_mins // 60, _min_mins % 60)
            _h_max = _time_for_range(_max_mins // 60, _max_mins % 60)

    with st.expander("📅 Cronograma del rango", expanded=True):
        render_timetable_calendar(
            grid_data=grid_data,
            config=config,
            key=f"{key_ns}_inspect_cal",
            color_by_carrera=True,
            dias_visibles=sel_dias,
            hora_min_override=_h_min,
            hora_max_override=_h_max,
            titulo_compacto=True,
        )

    # Contador de exceso: cuántos horarios sobran en las franjas
    # seleccionadas (max sobre las celdas del rango). Esto da una
    # cota inferior de cuántos horarios habría que mover para
    # descomprimir la franja.
    cat_para_exceso = {
        "Todas": "peor",
        "Sólo teóricas": "teorica",
        "Sólo laboratorios": "laboratorio",
    }.get(sel_tipo, "peor")
    data_sede_cat = heatmap_sede["data"][sel_sede_id].get(cat_para_exceso)
    exceso_max = 0
    exceso_total_celdas = 0
    if data_sede_cat:
        dias_idx_map = {d: i for i, d in enumerate(heatmap_sede["dias"])}
        slot_idx_map = {s: i for i, s in enumerate(slots_all)}
        for slot in sel_slots:
            si = slot_idx_map.get(slot)
            if si is None:
                continue
            for dia in sel_dias:
                di = dias_idx_map.get(dia)
                if di is None:
                    continue
                d = data_sede_cat["demanda"][si][di]
                o = data_sede_cat["oferta"][si][di]
                exc = max(0, d - o)
                exceso_max = max(exceso_max, exc)
                exceso_total_celdas += exc
    if exceso_max > 0:
        st.error(
            f"⚠️ Faltan **{exceso_max} aula(s) del catálogo** de "
            f"{sede_nom} en la franja más saturada del rango. "
            f"Habría que mover **al menos {exceso_max} horario(s)** "
            f"fuera de esa franja para descomprimir.\n\n"
            f"📐 **Este número surge de la demanda proyectada** "
            f"según las **reglas y restricciones vigentes** del "
            f"asignador (R10 sede admisible por carrera, R3 tipo de "
            f"aula, R6 lab compatible, etc.) — asume que si el LP "
            f"tuviera que resolver el plan hoy, N horarios no "
            f"encontrarían aula en esta sede. Es una **guía para "
            f"planificar la asignación automática**, no una "
            f"medición del estado actual de la DB.\n\n"
            f"💡 Puede haber aulas libres puntualmente en el rango "
            f"(ver expander de abajo) pero el total de aulas del "
            f"tipo en la sede no alcanza para cubrir toda la "
            f"demanda simultánea — hay que reducir la demanda."
        )
    else:
        st.success(
            "✅ No hay exceso de horarios sobre aulas disponibles "
            "en el rango seleccionado (para este tipo)."
        )

    # Expander: aulas libres en todo el rango (intersección: un aula
    # se considera libre si está libre en TODAS las celdas del rango).
    with st.expander("🏛 Aulas libres en el rango", expanded=False):
        st.caption(
            "📊 **Este listado surge del estado actual de los datos "
            "del plan** (asignaciones vigentes en la DB): aulas de "
            f"**{sede_nom}** del tipo seleccionado que no están "
            "ocupadas por ningún horario **hoy** durante todo el "
            "rango elegido. Útil para saber cuáles quedan "
            "disponibles para reasignar manualmente."
        )
        st.caption(
            "ℹ️ **Ojo**: si el mensaje de arriba dice 'faltan N', "
            "ese es un problema **prospectivo** (la sede no tiene "
            "suficientes aulas del tipo para toda la demanda "
            "simultánea proyectada bajo las reglas actuales). Que "
            "haya aulas libres acá no lo resuelve — esas libres ya "
            "están contadas en la oferta total, y si el LP re-"
            "asigna con las reglas vigentes, se van a llenar y aún "
            "así van a faltar N."
        )
        # Categorías a chequear según el filtro.
        cats_libres: list[str]
        if sel_tipo == "Sólo teóricas":
            cats_libres = ["teorica"]
        elif sel_tipo == "Sólo laboratorios":
            cats_libres = ["laboratorio"]
        else:
            cats_libres = ["teorica", "laboratorio"]

        slot_idx_map = {s: i for i, s in enumerate(slots_all)}
        dias_idx_map = {d: i for i, d in enumerate(heatmap_sede["dias"])}
        # Set de aulas libres para el rango (intersección por celda).
        libres_por_cat: dict[str, list[tuple[str, int]]] = {}
        for cat in cats_libres:
            data_c = heatmap_sede["data"][sel_sede_id].get(cat, {})
            libres_matrix = data_c.get("aulas_libres")
            if not libres_matrix:
                continue
            interseccion: set[tuple[str, int]] | None = None
            for slot in sel_slots:
                si = slot_idx_map.get(slot)
                if si is None:
                    continue
                for dia in sel_dias:
                    di = dias_idx_map.get(dia)
                    if di is None:
                        continue
                    celda_set = {tuple(x) for x in libres_matrix[si][di]}
                    if interseccion is None:
                        interseccion = celda_set
                    else:
                        interseccion &= celda_set
            libres_por_cat[cat] = sorted(interseccion or set())

        cat_label = {"teorica": "Teóricas", "laboratorio": "Laboratorios"}
        algo_mostrado = False
        for cat, items in libres_por_cat.items():
            algo_mostrado = True
            st.markdown(f"**{cat_label[cat]}** — {len(items)} libre(s)")
            if not items:
                st.caption("(ninguna aula libre en todo el rango)")
            else:
                st.markdown(
                    ", ".join(
                        f"{nombre} ({cap})" for nombre, cap in items
                    )
                )
        if not algo_mostrado:
            st.caption(
                "No hay información de aulas libres disponible. Este "
                "cálculo requiere una corrida reciente del asignador."
            )

    # Detalle de horarios: envuelto en expander principal + expanders
    # por cada entrada, con paginación (similar al panel de aulas).
    DIAS_ORDER = {
        "Lunes": 0, "Martes": 1, "Miércoles": 2,
        "Jueves": 3, "Viernes": 4, "Sábado": 5,
    }
    tabla_rows.sort(
        key=lambda r: (
            DIAS_ORDER.get(r["Día"], 99),
            r["Inicio"],
            r["Materia"],
        )
    )

    total_rows = len(tabla_rows)

    # Toggle "Mostrar detalle" para poder ocultar toda la sección
    # (equivalente a un expander principal, sin caer en el problema
    # de expanders anidados que Streamlit no soporta).
    _show_detail_key = f"{key_ns}_inspect_show_detail"
    if _show_detail_key not in st.session_state:
        st.session_state[_show_detail_key] = False
    mostrar_detalle = st.toggle(
        f"📋 Detalle de horarios ({total_rows})",
        key=_show_detail_key,
        help=(
            "Muestra la lista completa de horarios del rango con "
            "controles de edición individuales."
        ),
    )
    if not mostrar_detalle:
        return

    st.caption(
        "Cada horario se puede desplegar para ver los detalles y "
        "editar día/hora con un preview de validaciones antes de "
        "persistir."
    )

    # Paginación.
    _page_size_key = f"{key_ns}_inspect_detail_size"
    _page_num_key = f"{key_ns}_inspect_detail_page"
    if _page_size_key not in st.session_state:
        st.session_state[_page_size_key] = 20
    if _page_num_key not in st.session_state:
        st.session_state[_page_num_key] = 1

    _pag_c1, _pag_c2, _pag_c3 = st.columns([2, 2, 6])
    with _pag_c1:
        page_size = st.selectbox(
            "Por página",
            options=[10, 20, 30, 50, 100],
            index=[10, 20, 30, 50, 100].index(
                st.session_state[_page_size_key]
            ),
            key=f"{key_ns}_inspect_detail_size_sel",
        )
    total_pages = max(1, (total_rows + page_size - 1) // page_size)
    if st.session_state[_page_num_key] > total_pages:
        st.session_state[_page_num_key] = 1
    st.session_state[_page_size_key] = page_size

    with _pag_c2:
        page_num = st.number_input(
            f"Página (1–{total_pages})",
            min_value=1,
            max_value=total_pages,
            value=st.session_state[_page_num_key],
            step=1,
            key=f"{key_ns}_inspect_detail_page_input",
        )
        st.session_state[_page_num_key] = page_num
    with _pag_c3:
        start = (page_num - 1) * page_size + 1
        end = min(page_num * page_size, total_rows)
        st.caption(
            f"Mostrando {start}–{end} de {total_rows} horarios "
            f"(página {page_num} de {total_pages})."
        )

    start_idx = (page_num - 1) * page_size
    rows_pag = tabla_rows[start_idx:start_idx + page_size]

    for row in rows_pag:
        titulo = (
            f"{row['Día']} {row['Inicio']}–{row['Fin']} · "
            f"{row['Materia']} · {row['Comisión']}"
        )
        with st.expander(titulo, expanded=False):
            c1, c2 = st.columns(2)
            with c1:
                st.markdown(
                    f"**Materia:** {row['Materia']}  \n"
                    f"**Comisión:** {row['Comisión']}  \n"
                    f"**Día:** {row['Día']}  \n"
                    f"**Franja:** {row['Inicio']} – {row['Fin']}"
                )
            with c2:
                st.markdown(
                    f"**Tipo:** {row['Tipo']}  \n"
                    f"**Carrera:** {row['Carrera']}  \n"
                    f"**Ubicación:** {row['Ubicación']}"
                )
            if st.button(
                "✏️ Editar día/hora",
                key=f"{key_ns}_edit_{row['horario_id']}",
                help=(
                    "Abre un diálogo con preview de validaciones "
                    "antes de persistir."
                ),
            ):
                _dialog_editar_horario(
                    plan_id=plan_id,
                    horario_id=row["horario_id"],
                    materia_label=row["Materia"],
                    comision_label=row["Comisión"],
                    heatmap_sede=heatmap_sede,
                    sede_id_inspeccionada=sel_sede_id,
                    tipo_filtro=sel_tipo,
                )


def _render_inventario(inv: dict) -> None:
    """Una tira con cantidad de aulas por tipo."""
    if not inv:
        return
    por_tipo = inv.get("por_tipo", {})
    total = inv.get("total", 0)
    if not por_tipo:
        return
    pieces = [f"**{total}** total"] + [
        f"{n} {tipo}" for tipo, n in sorted(por_tipo.items())
    ]
    st.caption("🏛 Inventario de aulas: " + " · ".join(pieces))


def _render_diagnostico_infactibilidad(
    diag: dict, iis: Optional[dict] = None,
) -> None:
    """Renderiza el diagnóstico estructural de una corrida infactible.

    Las secciones se muestran en orden de utilidad descendente:
    1. Horarios sin aula compatible (causa atómica).
    2. Faltante de aulas por tipo en una franja específica.
    3. Grupos de clases con compatibilidad muy limitada que se
       chocan entre sí (Hall).
    4. Franjas saturadas globales (más débil).
    5. Horas declaradas vs horarios cargados (partición).
    6. Diagnóstico cruzado por relajación (cuando 1-5 vinieron
       vacías y el solver no pudo resolver).

    Args:
        diag: dict serializado de InfeasibilityDiagnosis.
        iis: opcional. Resultado de ``_run_iis_relajacion`` cuando se
            ejecutó. Estructura:
            ``{"ran": bool, "culpables": list[str], "principal": str,
               "detalles": {Ri: {"feasible_relajado",
                                  "es_falso_positivo", "explicacion",
                                  "materias_problema"?}}}``.
    """
    sin_aula = diag.get("horarios_sin_aula_compatible", [])
    franjas = diag.get("franjas_saturadas", [])
    saturacion_tipo = diag.get("saturacion_por_tipo", [])
    hall_violators = diag.get("hall_violators", [])
    inventario = diag.get("inventario_aulas", {})

    _render_inventario(inventario)

    # NOTA: el bloque de `particion_problemas` (horas declaradas vs
    # horarios cargados) se eliminó de este diagnóstico. Esa validación
    # ya vive en la página de detalle del plan (10 checks por materia),
    # que trabaja con datos en vivo desde la DB. Acá dependía del
    # snapshot del LPRun y se desactualizaba apenas se cambiaban
    # horarios/virtuales — generando falsas alarmas.

    if (not sin_aula and not franjas
            and not saturacion_tipo and not hall_violators):
        # Si hay IIS, ese es el diagnóstico — saltamos el mensaje
        # genérico y caemos directo a la sección IIS al final de la
        # función. Si tampoco hay IIS, mostramos el mensaje y
        # cerramos.
        if not (iis and iis.get("ran")):
            st.info(
                "La asignación no logró ubicar todas las aulas, pero "
                "los chequeos rápidos no encontraron una causa obvia. "
                "Probá poner los **pesos de sobre y sub-ocupación en "
                "0** para descartar problemas de ponderación (no "
                "debería afectar la factibilidad, pero ayuda como "
                "verificación)."
            )
            return

    if sin_aula:
        st.error(
            f"**{len(sin_aula)} horario(s) que no tienen ninguna "
            f"aula compatible**"
        )
        df_sin = pd.DataFrame(sin_aula)
        if not df_sin.empty:
            st.dataframe(
                df_sin[[
                    "materia_codigo", "dia", "hora_inicio", "hora_fin",
                    "tipo_clase", "razon",
                ]].rename(columns={
                    "materia_codigo": "Materia",
                    "dia": "Día",
                    "hora_inicio": "Inicio",
                    "hora_fin": "Fin",
                    "tipo_clase": "Tipo",
                    "razon": "Razón",
                }),
                width='stretch', hide_index=True,
            )
        st.caption(
            "🛠 Acciones posibles:\n"
            "- **Cargar laboratorios compatibles** para esas materias "
            "(página Materias → laboratorios compatibles).\n"
            "- **Marcar el horario como teoría** en el cronograma "
            "(si en realidad es teoría y no lab).\n"
            "- **Agregar aulas** del tipo correcto a la sede."
        )

    if saturacion_tipo:
        st.divider()
        st.error(
            f"**{len(saturacion_tipo)} franja(s) con faltante de aulas "
            f"de un tipo específico**"
        )
        st.caption(
            "**Cómo leer esta tabla**: cada fila identifica una franja "
            "horaria donde hacen falta más aulas de un tipo concreto "
            "(teóricas o un laboratorio puntual) que las que tenés "
            "cargadas. Por ejemplo: si en un mismo horario hay 5 "
            "clases simultáneas y tenés 6 aulas en total, suena OK, "
            "pero si las 5 son teóricas y sólo 4 aulas son teóricas, "
            "no alcanzan. Las clases sin tipo determinado en el "
            "cronograma sólo se cuentan acá si no tienen alternativa "
            "posible (es decir, si no se pueden mandar a un lab)."
        )
        df_st = pd.DataFrame(saturacion_tipo)
        if not df_st.empty:
            df_view = df_st.copy()
            df_view["Solapan"] = (
                df_view["solapan_inicio"] + "–" + df_view["solapan_fin"]
            )
            df_view["Materias"] = df_view["materias"].apply(
                lambda lst: ", ".join(lst)
            )
            df_view["Disp."] = (
                df_view["n_necesarias"].astype(str)
                + " necesita / "
                + df_view["n_disponibles"].astype(str) + " disp."
            )
            df_view["Detalle"] = df_view.apply(
                lambda r: (
                    f"laboratorio para {r['materia']}"
                    if r["tipo"] == "laboratorio"
                    else "teóricas/anfiteatros"
                ),
                axis=1,
            )
            cols = ["dia", "Solapan", "tipo", "Detalle", "Disp.", "Materias"]
            st.dataframe(
                df_view[cols].rename(columns={
                    "dia": "Día", "tipo": "Tipo",
                }),
                width='stretch', hide_index=True,
            )
        st.caption(
            "🛠 Acciones posibles:\n"
            "- **Marcar virtual** algún dictado de recursado u "
            "optativa que aparezca en el cronograma y no necesite "
            "aula presencial este cuatri (desde Ciclos → Dictados o "
            "desde el panel de no esperadas).\n"
            "- **Agregar aulas** del tipo correcto a la sede "
            "(página Aulas).\n"
            "- Para laboratorios: **ampliar la lista de laboratorios "
            "compatibles** con esa materia (página Materias → "
            "laboratorios compatibles).\n"
            "- **Cambiar horarios** para que no caigan todos en la "
            "misma franja."
        )

    if hall_violators:
        st.divider()
        st.error(
            f"**{len(hall_violators)} grupo(s) de clases que se "
            f"chocan entre sí por compatibilidad muy limitada**"
        )
        st.caption(
            "**Cómo leer esta tabla**: cada fila muestra un grupo de "
            "clases que se dictan al mismo tiempo y que **comparten "
            "la misma lista chica de aulas posibles**, así que entre "
            "ellas se pelean por las pocas aulas compatibles. Este "
            "chequeo detecta casos sutiles donde mirar 'cuántas "
            "aulas hay en total' no alcanza: aunque haya muchas "
            "aulas, si el subgrupo de clases listado abajo sólo "
            "puede ir a las aulas listadas (por tipo o por la lista "
            "de laboratorios compatibles de la materia), no alcanzan "
            "para todas."
        )
        df_h = pd.DataFrame(hall_violators)
        if not df_h.empty:
            df_view = df_h.copy()
            df_view["Materias"] = df_view["materias"].apply(
                lambda lst: ", ".join(lst)
            )
            df_view["Aulas posibles"] = df_view["aulas"].apply(
                lambda lst: ", ".join(lst[:6]) + ("…" if len(lst) > 6 else "")
            )
            df_view["Cuenta"] = (
                df_view["n_horarios"].astype(str) + " hor. / "
                + df_view["n_aulas"].astype(str) + " aulas"
            )
            cols = ["dia", "Cuenta", "Materias", "Aulas posibles"]
            st.dataframe(
                df_view[cols].rename(columns={"dia": "Día"}),
                width='stretch', hide_index=True,
            )
        st.caption(
            "🛠 Acciones posibles: la columna **Aulas posibles** te "
            "dice exactamente qué aulas puede usar ese grupo de "
            "clases. Para resolver:\n"
            "- **Agregar más laboratorios compatibles** a alguna de "
            "las materias del grupo (página Materias).\n"
            "- **Cargar más aulas** del tipo necesario.\n"
            "- **Mover algún horario** del grupo a otra franja para "
            "que no se choquen."
        )

    if franjas:
        st.divider()
        st.error(
            f"**{len(franjas)} franja(s) con más clases simultáneas "
            f"que aulas disponibles**"
        )
        st.caption(
            "**Cómo leer esta tabla**: cada fila lista varios horarios "
            "que se dictan en el mismo momento. La columna **Solapan** "
            "muestra la franja exacta donde todos están activos a la "
            "vez; **Ventana total** muestra el rango completo del "
            "grupo. **Aulas** muestra cuántas aulas en total podrían "
            "recibir a alguna de esas clases — si ese número es menor "
            "que la cantidad de clases simultáneas, no alcanzan para "
            "todas (por tipo de aula o por la lista de laboratorios "
            "compatibles)."
        )
        df_fr = pd.DataFrame(franjas)
        if not df_fr.empty:
            df_view = df_fr.copy()
            df_view["Materias"] = df_view["materias"].apply(
                lambda lst: ", ".join(lst)
            )
            df_view["Solapan"] = (
                df_view["solapan_inicio"] + "–" + df_view["solapan_fin"]
            )
            df_view["Ventana"] = (
                df_view["ventana_inicio"] + "–" + df_view["ventana_fin"]
            )
            df_view["Aulas"] = (
                df_view["n_aulas_compatibles"].astype(str)
                + " / " + df_view["n_aulas_total"].astype(str)
            )
            # Desglose por tipo: "T:5 L:2 ?:1" (omite los que son 0).
            def _desglose(row):
                parts = []
                if row.get("n_teorica", 0) > 0:
                    parts.append(f"T:{row['n_teorica']}")
                if row.get("n_laboratorio", 0) > 0:
                    parts.append(f"L:{row['n_laboratorio']}")
                if row.get("n_sin_determinar", 0) > 0:
                    parts.append(f"?:{row['n_sin_determinar']}")
                return " ".join(parts) if parts else "—"
            df_view["Tipo"] = df_view.apply(_desglose, axis=1)
            st.dataframe(
                df_view[[
                    "dia", "Solapan", "Ventana",
                    "n_clases", "Tipo", "Aulas", "Materias",
                ]].rename(columns={
                    "dia": "Día",
                    "n_clases": "Clases",
                }),
                width='stretch', hide_index=True,
            )
        st.caption(
            "🛠 Acciones posibles:\n"
            "- **Mover algún horario** a otra franja menos cargada.\n"
            "- **Agregar más aulas** o ampliar la **lista de "
            "laboratorios compatibles** con esas materias.\n"
            "- **Verificar el tipo de las clases**: si una es "
            "laboratorio y otras teóricas en la misma franja, "
            "conviene fijar el tipo en el cronograma (así la "
            "asignación puede usar ambos grupos de aulas)."
        )

    # =========================================================================
    # Diagnóstico cruzado (IIS por relajación)
    # =========================================================================
    if iis and iis.get("ran"):
        st.divider()
        st.markdown("### 🔍 Diagnóstico cruzado")
        st.caption(
            "Cuando los chequeos rápidos de arriba no encuentran "
            "ninguna causa pero la asignación no logra ubicar todas "
            "las aulas, el sistema prueba **ignorar temporalmente "
            "cada una de las tres restricciones flexibles** del "
            "modelo, una a la vez, y ve si el problema se resuelve. "
            "La restricción que al ignorarse permite resolver es la "
            "que está causando el conflicto. Si parece que hay más "
            "de una culpable, se marca **la causa probable "
            "principal** (las otras suelen ser efectos secundarios)."
        )

        principal = iis.get("principal")
        descripciones_cortas = {
            "R4": (
                "Más clases simultáneas que aulas disponibles "
                "para recibirlas"
            ),
            "R5": (
                "Horas declaradas teoría/laboratorio no cuadran "
                "con los horarios cargados"
            ),
            "R6": (
                "Horarios sin tipo determinado sin aula compatible "
                "ni como teoría ni como lab"
            ),
        }

        if principal:
            st.error(
                f"**Causa probable: {descripciones_cortas[principal]}**"
            )
        else:
            st.warning(
                "**No se pudo identificar una sola causa.** Ninguna "
                "de las tres reglas, al ignorarse por separado, "
                "permite resolver el modelo. Eso significa que la "
                "infactibilidad **combina varias condiciones a la "
                "vez**. Recomendaciones generales: revisá si tenés "
                "muchas clases en pocas franjas (marcá virtual los "
                "recursados / dictados por Zoom desde Ciclos → "
                "Dictados), si hay materias con horas teoría/lab "
                "incoherentes con sus horarios, y si hay horarios "
                "sin tipo determinado en el cronograma."
            )

        st.markdown("**Detalle por regla:**")
        for ri in ("R4", "R5", "R6"):
            _det = (iis.get("detalles") or {}).get(ri, {})
            if not _det:
                continue
            _feas = _det.get("feasible_relajado", False)
            _falso_pos = _det.get("es_falso_positivo", False)
            _lbl_corta = descripciones_cortas.get(ri, ri)

            if _feas and not _falso_pos:
                # Culpable real
                _icon = "❌" if ri == principal else "⚠️"
                _hdr = (
                    f"{_icon} **{_lbl_corta}** "
                    + ("(causa principal)" if ri == principal
                       else "(también podría aportar)")
                )
            elif _feas and _falso_pos:
                # Falso positivo
                _hdr = (
                    f"➖ {_lbl_corta} *(probablemente no es la "
                    "causa real)*"
                )
            else:
                # No arregló al relajarse
                _hdr = (
                    f"✅ {_lbl_corta} *(no es problema por sí sola)*"
                )

            with st.expander(_hdr, expanded=(_feas and not _falso_pos)):
                st.markdown(_det.get("explicacion", ""))

                _materias_problema = _det.get("materias_problema") or []
                if _materias_problema and ri == "R5":
                    st.markdown(
                        f"**Materias con desajuste "
                        f"({len(_materias_problema)}):**"
                    )
                    df_mp = pd.DataFrame(_materias_problema)
                    if not df_mp.empty:
                        st.dataframe(
                            df_mp[[
                                "materia_codigo",
                                "hlab_declarado",
                                "lab_resuelto",
                                "delta",
                            ]].rename(columns={
                                "materia_codigo": "Materia",
                                "hlab_declarado": "Horas lab declaradas",
                                "lab_resuelto": "Horas lab según la asignación",
                                "delta": "Diferencia",
                            }),
                            width='stretch', hide_index=True,
                        )
                    st.caption(
                        "**Cómo leer**: la primera columna son las "
                        "horas de laboratorio que la materia tiene "
                        "declaradas en el catálogo; la segunda es "
                        "cuántas horas la asignación pondría como "
                        "laboratorio si pudiera elegir libremente. "
                        "Cuando difieren, hay un desajuste: o bien "
                        "el catálogo dice una cosa pero los horarios "
                        "fijados dicen otra, o la suma de duraciones "
                        "no permite la partición."
                    )


def _render_alpha_propuesto(
    session: Session, run: LPRunDB, alpha_diff: list[dict], key_ns: str,
) -> None:
    """Diff entre los pesos actuales y los propuestos por el LP.
    Botones para aplicar o descartar la propuesta.
    """
    # Filtramos sólo los cambios significativos (>1pp).
    cambios = [
        d for d in alpha_diff
        if abs(d.get("delta", 0)) > 0.01
    ]
    if not cambios:
        st.success(
            "🟢 Los pesos actuales ya estaban óptimos. "
            "La asignación no propone cambios."
        )
        return

    # Lookup de comisiones y materias para mostrar nombres.
    com_ids = [d["comision_id"] for d in cambios]
    coms = list(session.exec(
        select(ComisionDB).where(ComisionDB.id.in_(com_ids))  # type: ignore[attr-defined]
    ).all())
    com_map = {c.id: c for c in coms}
    mat_codes = {c.materia_codigo for c in coms}
    from src.database.models import MateriaDB as _Mat
    mats = list(session.exec(
        select(_Mat).where(_Mat.codigo.in_(mat_codes))  # type: ignore[attr-defined]
    ).all()) if mat_codes else []
    mat_map = {m.codigo: m for m in mats}

    rows = []
    for d in cambios:
        com = com_map.get(d["comision_id"])
        mat = mat_map.get(com.materia_codigo) if com else None
        rows.append({
            "Materia": mat.nombre if mat else (
                com.materia_codigo if com else "?"
            ),
            "Comisión": com.nombre if com else d["comision_id"][:8],
            "Peso actual": d["alpha_actual"],
            "Peso propuesto": d["alpha_propuesto"],
            "Δ": d["delta"],
        })
    df = pd.DataFrame(rows)

    st.markdown("**🔄 Pesos propuestos para redistribuir capacidad**")
    st.caption(
        "La asignación propone redistribuir el peso relativo de las "
        "comisiones del mismo dictado para mejorar el ajuste a la "
        "capacidad disponible. Las aulas asignadas en esta corrida "
        "**asumen los pesos propuestos**. Si descartás la propuesta, "
        "los pesos quedan como estaban pero las aulas asignadas pueden "
        "no ser óptimas para esos pesos viejos."
    )

    def _color_delta(v):
        if v > 0.01:
            return "background-color: #d4edda; color: #155724"  # verde (sube)
        if v < -0.01:
            return "background-color: #f8d7da; color: #721c24"  # rojo (baja)
        return ""

    styled = df.style.map(_color_delta, subset=["Δ"]).format({
        "Peso actual": "{:.2f}",
        "Peso propuesto": "{:.2f}",
        "Δ": "{:+.2f}",
    })
    st.dataframe(styled, width='stretch', hide_index=True)

    # Estado de aplicación: lo cacheamos en session_state para que tras
    # apretar "Aplicar" no se vuelva a mostrar como propuesta pendiente.
    applied_key = f"{key_ns}_alpha_applied_{run.id}"
    if st.session_state.get(applied_key):
        st.success("✅ Pesos aplicados. Los nuevos valores quedaron guardados.")
        return

    col_ok, col_no = st.columns(2)
    with col_ok:
        if st.button("Aplicar nuevos pesos", type="primary",
                     key=f"{key_ns}_aplicar_alpha"):
            from src.services.asignacion_aulas_service import (
                aplicar_alpha_propuesto,
            )
            alpha_dict = {
                d["comision_id"]: d["alpha_propuesto"] for d in alpha_diff
            }
            n = aplicar_alpha_propuesto(
                session, run.plan_cursada_id, alpha_dict,
            )
            st.session_state[applied_key] = True
            st.success(f"{n} comisión(es) actualizada(s).")
            st.rerun()
    with col_no:
        if st.button("Descartar propuesta",
                     key=f"{key_ns}_descartar_alpha"):
            st.info(
                "Los pesos quedan como estaban. Si querés coherencia "
                "con esos pesos, volvé a correr la asignación con la "
                "opción de redistribución desactivada."
            )


def render_resultado(
    session: Session, run: LPRunDB, key_ns: str = "asig_res",
) -> None:
    """Renderiza el detalle de un ``LPRunDB``.

    Si ``run.status != 'optimal'``, muestra el diagnóstico de
    infactibilidad. Si es óptimo, muestra la tabla por horario coloreada
    y las candidatas a partir comisión.
    """
    details = json.loads(run.details_json or "{}")

    # Recomputo del heatmap en vivo (respeta cambios post-LP como
    # marcar un horario virtual desde el inspector).
    heatmap_sede = _recompute_heatmap_por_sede_live(session, run.plan_cursada_id)
    if heatmap_sede is None:
        heatmap_sede = details.get("heatmap_por_sede")

    # Diagnóstico: filtramos horarios ahora-virtuales para que no
    # aparezcan como "falta ese horario" tras cambios posteriores al
    # último LP run.
    diag = details.get("infeasibility_diagnosis")
    iis = details.get("iis")
    _virtuales_ahora = _get_horarios_virtuales_ahora(
        session, run.plan_cursada_id,
    )
    diag = _filtrar_diag_virtuales(diag, _virtuales_ahora)

    # ======================================================
    # Este renderer se invoca dentro del expander "Gestión de
    # asignaciones", que ya es nivel 1. Por eso las sub-secciones NO
    # usan `st.expander` (llegaría a 3 niveles: Gestión → sub-sección
    # → expander por sede, que Streamlit no soporta). En su lugar
    # usamos títulos con `st.markdown` y toggles.
    # ======================================================
    if heatmap_sede:
        st.markdown("#### 🔥 Mapa de Saturación")
        _render_heatmap_por_sede(heatmap_sede, key_ns=key_ns)

        # "Ver detalle" como toggle (equivale al ex-Inspeccionar franja).
        _ver_detalle_key = f"{key_ns}_ver_detalle_toggle"
        if _ver_detalle_key not in st.session_state:
            st.session_state[_ver_detalle_key] = False
        mostrar_detalle = st.toggle(
            "🔍 Ver detalle de una franja",
            key=_ver_detalle_key,
            help=(
                "Muestra un cronograma coloreado por carrera y "
                "controles para editar día/hora de los horarios "
                "en el rango seleccionado."
            ),
        )
        if mostrar_detalle:
            with st.container(border=True):
                _render_inspector_franja(
                    heatmap_sede,
                    plan_id=run.plan_cursada_id,
                    key_ns=key_ns,
                )

    if run.status != "optimal":
        with st.expander("🔍 Diagnóstico", expanded=True):
            if diag:
                _render_diagnostico_infactibilidad(diag, iis=iis)
            else:
                st.info(
                    "No se generó diagnóstico para esta corrida."
                )
        return

    # Advertencias estructurales — filtramos entries vacías post-filtro
    # de virtuales para no mostrar el mensaje engañoso cuando el
    # snapshot quedó obsoleto.
    _sin_aula = diag.get("horarios_sin_aula_compatible") if diag else None
    _franjas = diag.get("franjas_saturadas") if diag else None
    _saturacion = diag.get("saturacion_por_tipo") if diag else None
    _hall = diag.get("hall_violators") if diag else None
    if diag and (_sin_aula or _franjas or _saturacion or _hall):
        with st.expander(
            "⚠️ Diagnóstico: advertencias estructurales detectadas",
            expanded=False,
        ):
            _render_diagnostico_infactibilidad(diag, iis=iis)

    # Ajustes avanzados (α) — sólo si aplica.
    alpha_diff = details.get("alpha_propuestos", [])
    if run.activar_alpha and alpha_diff:
        _render_alpha_propuesto(session, run, alpha_diff, key_ns)

    df = _build_dataframe(session, run)
    if df.empty:
        return

    # Detalle por horario (toggle).
    _det_key = f"{key_ns}_show_detalle_horario"
    if _det_key not in st.session_state:
        st.session_state[_det_key] = False
    mostrar_det = st.toggle(
        "📋 Ver detalle por horario",
        key=_det_key,
        help=(
            "Estado de ocupación de cada horario del plan (asignación "
            "vigente en la DB, no del snapshot del último LP). Incluye "
            "los cambios manuales posteriores a la última corrida."
        ),
    )
    if mostrar_det:
        with st.container(border=True):
            st.caption(
                "Los umbrales de sobre-/sub-ocupación son los de la "
                "última corrida del asignador. La columna **Manual** "
                "marca con 🔒 las aulas que están protegidas de "
                "futuras corridas."
            )
            styled = df.style.map(
                _color_estado, subset=["Estado"],
            ).format({
                "Esperados": "{:.0f}",
                "Cap": "{:.0f}",
                "Δ": "{:+.0f}",
            })
            st.dataframe(styled, width='stretch', hide_index=True)

    # Candidatas a partir comisión (toggle).
    cand = _candidatas_partir_comision(df)
    if not cand.empty:
        _cand_key = f"{key_ns}_show_candidatas"
        if _cand_key not in st.session_state:
            st.session_state[_cand_key] = False
        mostrar_cand = st.toggle(
            "🪓 Ver candidatas a partir comisión",
            key=_cand_key,
            help=(
                "Materias con horarios sobre-ocupados, ordenadas por "
                "exceso total de alumnos. Subir `n_comisiones` "
                "distribuye los esperados en más aulas."
            ),
        )
        if mostrar_cand:
            with st.container(border=True):
                st.caption(
                    "Estas materias tienen al menos un horario con "
                    "capacidad por debajo de los inscriptos esperados. "
                    "Subir `n_comisiones` en la materia distribuye "
                    "los esperados en más aulas y descomprime."
                )
                st.dataframe(
                    cand, width='stretch', hide_index=True,
                )
