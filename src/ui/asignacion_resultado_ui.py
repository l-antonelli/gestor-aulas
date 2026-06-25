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
    HorarioDB,
    LPRunDB,
    MateriaDB,
    SedeDB,
)


# =============================================================================
# Helpers
# =============================================================================

def _build_dataframe(
    session: Session, run: LPRunDB,
) -> pd.DataFrame:
    """Arma el DataFrame por horario a partir de details_json + lookups
    de la base."""
    details = json.loads(run.details_json or "{}")
    horarios_detalle = details.get("horarios", [])
    if not horarios_detalle:
        return pd.DataFrame()

    horario_ids = [h["horario_id"] for h in horarios_detalle]
    horarios_db = list(session.exec(
        select(HorarioDB).where(HorarioDB.id.in_(horario_ids))  # type: ignore[attr-defined]
    ).all())
    horarios_map = {h.id: h for h in horarios_db}

    comision_ids = {h.comision_id for h in horarios_db}
    comisiones_db = list(session.exec(
        select(ComisionDB).where(ComisionDB.id.in_(comision_ids))  # type: ignore[attr-defined]
    ).all()) if comision_ids else []
    comisiones_map = {c.id: c for c in comisiones_db}

    materias_codigos = {h.codigo_materia for h in horarios_db}
    materias_db = list(session.exec(
        select(MateriaDB).where(MateriaDB.codigo.in_(materias_codigos))  # type: ignore[attr-defined]
    ).all()) if materias_codigos else []
    materias_map = {m.codigo: m for m in materias_db}

    aulas_ids_solucion = {h["aula_id"] for h in horarios_detalle if h["aula_id"]}
    aulas_db = list(session.exec(
        select(AulaDB).where(AulaDB.id.in_(aulas_ids_solucion))  # type: ignore[attr-defined]
    ).all()) if aulas_ids_solucion else []
    aulas_map = {a.id: a for a in aulas_db}

    sedes_ids = {a.sede_id for a in aulas_db}
    sedes_db = list(session.exec(
        select(SedeDB).where(SedeDB.id.in_(sedes_ids))  # type: ignore[attr-defined]
    ).all()) if sedes_ids else []
    sede_nombre_por_id = {s.id: s.nombre for s in sedes_db}

    rows = []
    for d in horarios_detalle:
        h = horarios_map.get(d["horario_id"])
        if h is None:
            continue
        com = comisiones_map.get(h.comision_id)
        mat = materias_map.get(h.codigo_materia)
        aula = aulas_map.get(d["aula_id"]) if d["aula_id"] else None
        rows.append({
            "Materia": mat.nombre if mat else h.codigo_materia,
            "Comisión": com.nombre if com else "?",
            "Día": h.dia,
            "Inicio": h.hora_inicio.strftime("%H:%M"),
            "Fin": h.hora_fin.strftime("%H:%M"),
            "Aula": aula.nombre if aula else "—",
            "Sede": sede_nombre_por_id.get(aula.sede_id, "—") if aula else "—",
            "Cap": d["cap"],
            "Esperados": d["insc"],
            "Δ": d["delta"],
            "Estado": d["estado"],
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

def _render_heatmap_carga(heatmap: dict, key_ns: str) -> None:
    """Tabla día × franja con clases simultáneas según el ``tipo_clase``
    declarado en el cronograma.

    Importante: el filtro distingue cómo viene marcada cada clase en el
    cronograma. Las que están como ``None`` (sin determinar) son las que
    el LP eventualmente clasificará vía R5/R6 cuando esté implementada
    la Fase 5 del lab/teoría split.
    """
    if not heatmap or not heatmap.get("slots"):
        return

    st.markdown("**📊 Heatmap de carga: clases simultáneas por franja**")
    st.caption(
        "Cada celda cuenta cuántas clases están activas **a la vez** en "
        "ese día y franja (las virtuales no cuentan). Si dos horarios "
        "están consecutivos sin solapar, se ven como `1` en cada slot, "
        "no como `2` (porque a ningún instante hay 2 simultáneas)."
    )

    filtro = st.radio(
        "Tipo declarado en el cronograma",
        options=[
            "Todas",
            "Teórica fijada",
            "Laboratorio fijado",
            "Sin determinar",
        ],
        horizontal=True,
        key=f"{key_ns}_heatmap_filtro",
        help=(
            "Las clases sin determinar son aquellas cuyo tipo decidirá el "
            "LP (cuando esté implementado el split teoría/lab). Hoy en "
            "tu cronograma probablemente la mayoría está así."
        ),
    )
    matriz_key = {
        "Todas": "total",
        "Teórica fijada": "teorica",
        "Laboratorio fijado": "laboratorio",
        "Sin determinar": "sin_determinar",
    }[filtro]
    matriz = heatmap[matriz_key]

    df = pd.DataFrame(matriz, index=heatmap["slots"], columns=heatmap["dias"])
    # Recortar SÓLO los extremos vacíos: nos quedamos con el rango de
    # filas desde la primera fila no-cero hasta la última no-cero. Las
    # filas todas-cero del medio se conservan para que los huecos sean
    # visibles (si las filtramos, una clase 8-11 y otra 17-19 parecen
    # pegadas y los 0s entre 11 y 17 desaparecen).
    row_sums = df.sum(axis=1)
    nonzero_idx = [i for i, s in enumerate(row_sums.tolist()) if s > 0]
    if not nonzero_idx:
        st.info("No hay clases declaradas con este tipo en ningún slot.")
        return
    df = df.iloc[nonzero_idx[0]: nonzero_idx[-1] + 1]

    # Usamos Altair porque el styler de pandas + dark theme de Streamlit
    # se pelean con el coloreado de celdas en cero (terminan tintadas
    # aunque el alpha sea 0). Altair da un heatmap de verdad con escala
    # consistente y los 0 quedan claramente sin color.
    import altair as alt

    # Long format: una fila por (slot, dia, valor) para que Altair lo
    # mapee a un grid.
    long_rows = []
    for slot_label in df.index:
        for dia in df.columns:
            v = int(df.loc[slot_label, dia])
            long_rows.append({"slot": slot_label, "dia": dia, "valor": v})
    df_long = pd.DataFrame(long_rows)

    max_val = int(df_long["valor"].max()) if not df_long.empty else 0

    # Color: blanco para 0 (transparente para que respete el theme),
    # rojo intenso para el max. Si max==0 evitamos división.
    color_scale = alt.Scale(
        domain=[0, max(1, max_val)],
        range=["#1e1e1e", "#dc3545"],  # gris muy oscuro → rojo brand
    )

    # Heatmap base.
    base = alt.Chart(df_long).encode(
        x=alt.X(
            "dia:N",
            title=None,
            sort=heatmap["dias"],
            axis=alt.Axis(orient="top", labelAngle=0, labelFontSize=12),
        ),
        y=alt.Y(
            "slot:N",
            title=None,
            sort=list(df.index),
            axis=alt.Axis(labelFontSize=11),
        ),
    )
    rect = base.mark_rect(stroke="#444", strokeWidth=0.5).encode(
        color=alt.Color(
            "valor:Q",
            scale=color_scale,
            legend=alt.Legend(title="Clases simultáneas"),
        ),
        tooltip=[
            alt.Tooltip("dia:N", title="Día"),
            alt.Tooltip("slot:N", title="Franja"),
            alt.Tooltip("valor:Q", title="Clases"),
        ],
    )
    # Texto encima del heatmap. Color del texto: blanco cuando el
    # valor está en la mitad superior de la escala, gris claro cuando
    # está abajo. Los 0 quedan sin texto visible.
    text = base.mark_text(fontSize=11, fontWeight="bold").encode(
        text=alt.condition(
            alt.datum.valor > 0,
            alt.Text("valor:Q", format="d"),
            alt.value(""),
        ),
        color=alt.condition(
            f"datum.valor > {max_val * 0.55}",
            alt.value("white"),
            alt.value("#bbb"),
        ),
    )
    chart = (rect + text).properties(
        width="container",
        height=max(400, len(df.index) * 26),
    )
    st.altair_chart(chart, use_container_width=True)


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
        "(según R10 — sedes habilitadas para la carrera de la materia, "
        "o sede default para materias comunes — y compatibilidad de "
        "laboratorio). La oferta son las aulas de la sede del tipo "
        "necesario. Verde ≤80% · amarillo 80–100% · rojo >100% "
        "(saturación segura: más horarios que aulas)."
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
            "Ninguna sede tiene demanda con la configuración de R10 "
            "actual. Revisá las sedes habilitadas para las carreras."
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

        long_rows = []
        for si, slot_label in enumerate(slots_v):
            for di, dia in enumerate(dias):
                d = int(demanda_v[si][di])
                o = int(oferta_v[si][di])
                r_ = float(ratio_v[si][di])
                long_rows.append({
                    "slot": slot_label,
                    "dia": dia,
                    "demanda": d,
                    "oferta": o,
                    "ratio": r_,
                    "bucket": _bucket(r_),
                    "etiqueta": (f"{d}/{o}" if d > 0 else ""),
                })
        df_long = pd.DataFrame(long_rows)

        # Header de la sede.
        st.markdown(
            f"**🏛 {sede_nombre}** · {n_teo} aula(s) teórica(s) · "
            f"{n_lab} laboratorio(s)"
        )

        base = alt.Chart(df_long).encode(
            x=alt.X(
                "dia:N", title=None, sort=dias,
                axis=alt.Axis(orient="top", labelAngle=0, labelFontSize=11),
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
                alt.Tooltip("demanda:Q", title="Horarios"),
                alt.Tooltip("oferta:Q", title="Aulas"),
                alt.Tooltip("ratio:Q", title="Ratio", format=".2f"),
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
        st.divider()

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

    st.markdown(
        f"**Materia:** {materia_label}  \n"
        f"**Comisión:** {comision_label}  \n"
        f"**Actual:** {actual_dia} "
        f"{actual_hi.strftime('%H:%M')}–{actual_hf.strftime('%H:%M')}"
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

    sin_cambio = (
        nuevo_dia == actual_dia
        and nuevo_hi == actual_hi
        and nuevo_hf == actual_hf
    )

    # Preview de validaciones (sólo si hay cambio).
    preview = None
    if not sin_cambio:
        with next(get_session()) as _sess:
            preview = preview_cambio_horario(
                _sess, plan_id, horario_id,
                nuevo_dia, nuevo_hi, nuevo_hf,
            )

    # Saturación de las franjas destino — para confirmar que no
    # estamos trasladando el problema a otra franja también saturada.
    # Sólo aplica si tenemos heatmap_sede e info de sede.
    if (
        not sin_cambio
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
    col_ok, col_cancel = st.columns(2)
    with col_ok:
        # Texto del botón cambia según si hay conflictos.
        if sin_cambio:
            st.button(
                "Sin cambios",
                disabled=True,
                use_container_width=True,
                key=f"edith_{horario_id}_save_disabled",
            )
        elif preview is None or preview.error:
            st.button(
                "Confirmar y aplicar",
                disabled=True,
                use_container_width=True,
                key=f"edith_{horario_id}_save_blocked",
            )
        else:
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
        "Seleccioná uno o más días y una o más franjas (30 min) para "
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
        sel_slots = st.multiselect(
            "Franja(s) (30 min)",
            options=slots_all,
            default=[],
            key=f"{key_ns}_inspect_slots",
            help=(
                "Podés seleccionar varias franjas adyacentes para "
                "una saturación extendida, o una sola para puntual."
            ),
        )
    if not sel_dias or not sel_slots:
        st.info(
            "Seleccioná al menos un día y una franja para inspeccionar."
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

        # Filtrar horarios virtuales — mismo criterio que build_inputs del LP:
        # (a) MateriaDB.virtual=True, (b) DictadoDB.virtual=True para este ciclo.
        # Sin este filtro, el inspector cuenta más horarios que el heatmap.
        materia_virtual = {m.codigo: m.virtual for m in materias_db}
        plan_obj = _s.get(_PlanificacionCursadaDB, plan_id)
        materia_dictado_virtual: dict[str, bool] = {}
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
                materia_dictado_virtual[mc] = bool(es_virt)
        horarios_db = [
            h for h in horarios_db_all
            if not materia_virtual.get(h.codigo_materia, False)
            and not materia_dictado_virtual.get(h.codigo_materia, False)
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
        for pe in pe_rows:
            materia_carreras.setdefault(pe.materia_codigo, set()).add(
                pe.carrera_codigo,
            )
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
        "sede (R10). Cada bloque se muestra **completo** (de su "
        "hora_inicio a hora_fin) aunque cubra parcialmente el "
        "rango. Color por **carrera** — bloques del mismo color "
        "son de la misma carrera y por lo tanto NO se pueden "
        "mover entre sí (rompería la cohorte)."
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
        if len(carreras_de_mat) == 1:
            (car_codigo,) = tuple(carreras_de_mat)
            car_label = carrera_nombre.get(car_codigo, car_codigo)
            car_pretty = car_label
        elif len(carreras_de_mat) >= 2:
            car_codigo = None
            car_label = None
            car_pretty = "— Común (varias carreras) —"
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
            f"⚠️ Faltan **{exceso_max} aula(s)** en la franja más "
            f"saturada del rango. Habría que mover **al menos "
            f"{exceso_max} horario(s)** fuera de esa franja para "
            "descomprimir."
        )
    else:
        st.success(
            "✅ No hay exceso de horarios sobre aulas disponibles "
            "en el rango seleccionado (para este tipo)."
        )

    # Tabla de detalle abajo del calendario.
    st.markdown("**Detalle de horarios**")
    st.caption(
        "Botón **Editar** en cada fila → modal con preview de "
        "validaciones antes de persistir."
    )
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

    # Header.
    h1, h2, h3, h4, h5, h6, h7, h8 = st.columns(
        [1, 1, 1, 3, 2, 1.5, 2, 1]
    )
    for col, txt in zip(
        (h1, h2, h3, h4, h5, h6, h7, h8),
        ("Día", "Inicio", "Fin", "Materia", "Comisión",
         "Tipo", "Carrera", ""),
    ):
        col.markdown(f"**{txt}**")
    st.divider()

    for row in tabla_rows:
        c1, c2, c3, c4, c5, c6, c7, c8 = st.columns(
            [1, 1, 1, 3, 2, 1.5, 2, 1]
        )
        c1.write(row["Día"])
        c2.write(row["Inicio"])
        c3.write(row["Fin"])
        c4.write(row["Materia"])
        c5.write(row["Comisión"])
        c6.write(row["Tipo"])
        c7.write(row["Carrera"])
        if c8.button(
            "✏️ Editar",
            key=f"{key_ns}_edit_{row['horario_id']}",
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
    particion = diag.get("particion_problemas", [])
    inventario = diag.get("inventario_aulas", {})

    _render_inventario(inventario)

    if particion:
        st.error(
            f"**{len(particion)} comisión(es) con horas declaradas "
            f"que no cuadran con sus horarios cargados**"
        )
        df_p = pd.DataFrame(particion)
        if not df_p.empty:
            st.dataframe(
                df_p[[
                    "materia", "hteo", "hlab", "suma_total",
                    "suma_teorica_fijada", "suma_lab_fijado", "razon",
                ]].rename(columns={
                    "materia": "Materia",
                    "hteo": "Horas teoría declaradas",
                    "hlab": "Horas lab declaradas",
                    "suma_total": "Total horas en horarios",
                    "suma_teorica_fijada": "Horas marcadas como teoría",
                    "suma_lab_fijado": "Horas marcadas como lab",
                    "razon": "Razón",
                }),
                width='stretch', hide_index=True,
            )
        st.caption(
            "🛠 Acciones posibles:\n"
            "- **Ajustar las horas declaradas** de la materia "
            "(página Materias).\n"
            "- **Cambiar el tipo (teoría/lab)** de algún horario en "
            "el cronograma.\n"
            "- Verificar que **la suma total de duraciones** de los "
            "horarios coincida con las horas semanales de la materia."
        )
        st.divider()

    if (not sin_aula and not franjas and not particion
            and not saturacion_tipo and not hall_violators):
        # Si hay IIS, ese es el diagnóstico — saltamos el mensaje
        # genérico y caemos directo a la sección IIS al final de la
        # función. Si tampoco hay IIS, mostramos el mensaje y
        # cerramos.
        if not (iis and iis.get("ran")):
            st.info(
                "El solver no logró asignar aulas pero los chequeos "
                "rápidos no encontraron una causa obvia. Probá poner "
                "**λ sobre = 0, λ sub = 0** para descartar problemas "
                "del penalty (no debería afectar la factibilidad, "
                "pero ayuda como verificación)."
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
            "conviene fijar el tipo en el cronograma (así el LP "
            "puede usar ambos pools de aulas)."
        )

    # =========================================================================
    # Diagnóstico cruzado (IIS por relajación)
    # =========================================================================
    if iis and iis.get("ran"):
        st.divider()
        st.markdown("### 🔍 Diagnóstico cruzado")
        st.caption(
            "Cuando los chequeos rápidos de arriba no encuentran "
            "ninguna causa pero el solver no logra asignar aulas, el "
            "sistema prueba **ignorar temporalmente cada una de las "
            "tres reglas blandas** del modelo, una a la vez, y ve si "
            "el problema se resuelve. La regla que al ignorarse "
            "permite resolver es la que está causando el conflicto. "
            "Si más de una regla parece culpable, el sistema te marca "
            "**la causa probable principal** (las otras suelen ser "
            "efectos secundarios)."
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
                                "lab_resuelto": "Horas lab que el LP usaría",
                                "delta": "Diferencia",
                            }),
                            width='stretch', hide_index=True,
                        )
                    st.caption(
                        "**Cómo leer**: la primera columna son las "
                        "horas de laboratorio que la materia tiene "
                        "declaradas en el catálogo; la segunda es "
                        "cuántas horas el LP asignaría como "
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
            "El LP no propone cambios."
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

    st.markdown("**🔄 Pesos propuestos por el LP (`coef_asignacion`)**")
    st.caption(
        "El LP propone redistribuir los pesos para mejorar el ajuste a "
        "la capacidad disponible. Las aulas asignadas en esta corrida "
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
        st.success("✅ Pesos aplicados. Los nuevos coeficientes están persistidos.")
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
                "con esos pesos, re-corré el LP con el toggle α "
                "apagado."
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

    # Heatmap de carga: siempre que haya horarios. Independiente del
    # status — sirve tanto para entender por qué algo es infactible
    # como para ver los picos cuando todo resuelve OK.
    heatmap = details.get("heatmap_carga")
    if heatmap:
        with st.expander("📊 Heatmap de carga (día × franja)", expanded=False):
            _render_heatmap_carga(heatmap, key_ns=key_ns)

    # Mapa de saturación POR SEDE: para cada sede, día × franja con
    # demanda vs oferta de aulas (separado por categoría: teórica,
    # laboratorio, peor caso). Reemplaza el heatmap demanda/oferta global
    # y el panel de impacto R10. Es la herramienta principal para
    # responder "¿en qué sede × franja × tipo de aula me falta capacidad?".
    heatmap_sede = details.get("heatmap_por_sede")
    if heatmap_sede:
        # ¿Hay alguna celda saturada en alguna sede? Por default expandido
        # cuando hay déficit (incluye ratios > 1.0).
        _hay_saturacion = False
        for _sede in heatmap_sede.get("sedes", []):
            if not _sede.get("tiene_demanda"):
                continue
            _data = heatmap_sede["data"][_sede["sede_id"]]
            for _cat in ("teorica", "laboratorio"):
                _ratio_m = _data[_cat]["ratio"]
                if any(r > 1.0 for row in _ratio_m for r in row):
                    _hay_saturacion = True
                    break
            if _hay_saturacion:
                break
        with st.expander(
            "🔥 Mapa de saturación por sede",
            expanded=(run.status != "optimal" or _hay_saturacion),
        ):
            _render_heatmap_por_sede(heatmap_sede, key_ns=key_ns)

        # Inspector de franja: dado uno o más días + slots, muestra
        # los horarios que intersectan en un calendario semanal
        # coloreado por carrera. Útil para evaluar movimientos
        # manuales del cronograma cuando una franja está saturada.
        with st.expander(
            "🔍 Inspeccionar franja",
            expanded=False,
        ):
            _render_inspector_franja(
                heatmap_sede,
                plan_id=run.plan_cursada_id,
                key_ns=key_ns,
            )

    # Diagnóstico SIEMPRE arriba si hay causa estructural detectada,
    # incluso cuando el run resolvió OK (es informativo).
    diag = details.get("infeasibility_diagnosis")
    iis = details.get("iis")

    if run.status != "optimal":
        st.markdown("### 🔍 Diagnóstico")
        if diag:
            _render_diagnostico_infactibilidad(diag, iis=iis)
        else:
            st.info("No se generó diagnóstico para esta corrida.")
        return

    # Caso óptimo: si hubo diagnóstico (que el LP toleró), avisamos.
    if diag and (
        diag.get("horarios_sin_aula_compatible")
        or diag.get("franjas_saturadas")
        or diag.get("particion_problemas")
    ):
        with st.expander("⚠️ Advertencias estructurales detectadas", expanded=False):
            _render_diagnostico_infactibilidad(diag, iis=iis)

    # Si el run usó α activo y hay propuesta, mostrar el diff y los
    # botones de aplicar/descartar antes del detalle por horario.
    alpha_diff = details.get("alpha_propuestos", [])
    if run.activar_alpha and alpha_diff:
        st.divider()
        _render_alpha_propuesto(session, run, alpha_diff, key_ns)

    df = _build_dataframe(session, run)
    if df.empty:
        st.info("No hay detalle por horario para mostrar.")
        return

    # Tabla coloreada.
    st.markdown("**Detalle por horario**")
    styled = df.style.map(_color_estado, subset=["Estado"]).format({
        "Esperados": "{:.0f}",
        "Cap": "{:.0f}",
        "Δ": "{:+.0f}",
    })
    st.dataframe(styled, width='stretch', hide_index=True)

    # Candidatas a partir comisión.
    cand = _candidatas_partir_comision(df)
    if not cand.empty:
        st.divider()
        st.markdown("**🪓 Candidatas a partir comisión**")
        st.caption(
            "Materias con horarios sobre-ocupados, ordenadas por exceso "
            "total de alumnos. Subir `n_comisiones` distribuye los "
            "esperados en más aulas."
        )
        st.dataframe(cand, width='stretch', hide_index=True)
