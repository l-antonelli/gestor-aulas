"""Detalle del resultado del LP de asignación de aulas.

Renderiza una tabla coloreada (verde/amarillo/rojo) con el gap por
horario, métricas agregadas y una lista de candidatas a partir comisión.

Se llama desde el panel de asignación (``asignacion_panel.render_panel``)
una vez que existe un ``LPRunDB`` para el plan.
"""

from __future__ import annotations

import json

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


def _render_diagnostico_infactibilidad(diag: dict) -> None:
    """Renderiza el diagnóstico estructural de una corrida infeasible."""
    sin_aula = diag.get("horarios_sin_aula_compatible", [])
    franjas = diag.get("franjas_saturadas", [])
    particion = diag.get("particion_problemas", [])
    inventario = diag.get("inventario_aulas", {})

    _render_inventario(inventario)

    if particion:
        st.error(
            f"**{len(particion)} comisión(es) con partición teoría/lab "
            f"infactible**"
        )
        df_p = pd.DataFrame(particion)
        if not df_p.empty:
            st.dataframe(
                df_p[[
                    "materia", "hteo", "hlab", "suma_total",
                    "suma_teorica_fijada", "suma_lab_fijado", "razon",
                ]].rename(columns={
                    "materia": "Materia",
                    "hteo": "hteo",
                    "hlab": "hlab",
                    "suma_total": "Σ horas",
                    "suma_teorica_fijada": "Teo fijada",
                    "suma_lab_fijado": "Lab fijada",
                    "razon": "Razón",
                }),
                width='stretch', hide_index=True,
            )
        st.caption(
            "🛠 Acciones posibles: (a) ajustar `horas_teoria` / "
            "`horas_laboratorio` de la materia desde `Materias`, "
            "(b) cambiar el tipo fijado de algún horario en el "
            "cronograma, (c) verificar que la suma de duraciones de los "
            "horarios coincida con el total semanal de la materia."
        )
        st.divider()

    if not sin_aula and not franjas and not particion:
        st.info(
            "El solver reportó infactibilidad pero no se detectaron "
            "causas estructurales obvias. Probá con `λ_over = 0, "
            "λ_under = 0` para descartar problemas de configuración del "
            "penalty (no debería afectar la factibilidad, pero ayuda "
            "como sanity check)."
        )
        return

    if sin_aula:
        st.error(
            f"**{len(sin_aula)} horario(s) sin ninguna aula compatible**"
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
            "🛠 Acciones posibles: (a) cargar laboratorios compatibles "
            "para esas materias en `Materias → Laboratorios`, (b) marcar "
            "el horario como teoría en el cronograma, (c) agregar aulas "
            "del tipo correcto."
        )

    if franjas:
        st.divider()
        st.error(
            f"**{len(franjas)} franja(s) con más clases simultáneas que "
            f"aulas compatibles**"
        )
        st.caption(
            "**Cómo leer esta tabla**: cada fila lista N horarios que "
            "coinciden temporalmente en al menos un instante (intersección "
            "no vacía). La columna **Solapan** muestra la franja exacta "
            "donde los N están activos a la vez (último inicio → primer "
            "fin); **Ventana total** muestra el rango completo desde el "
            "primer inicio hasta el último fin del grupo. **Aulas compat.** "
            "es la unión de aulas que podrían recibir a *cualquiera* de los "
            "N horarios — si ese número es menor que N, no alcanza para "
            "todos al mismo tiempo (por compatibilidad de tipo o "
            "MateriaLaboratorioDB)."
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
            "🛠 Acciones posibles: (a) mover algún horario a otra franja, "
            "(b) habilitar más aulas compatibles para alguna de esas "
            "materias en `Materias → Laboratorios`, (c) verificar si "
            "todas las clases listadas son del mismo tipo (laboratorio vs "
            "teoría) — si una es lab y las demás teoría, conviene fijar "
            "el tipo en el cronograma para que el LP separe los pools."
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
        with st.expander("📊 Heatmap de carga (día × franja)", expanded=(run.status != "optimal")):
            _render_heatmap_carga(heatmap, key_ns=key_ns)

    # Diagnóstico SIEMPRE arriba si hay causa estructural detectada,
    # incluso cuando el run resolvió OK (es informativo).
    diag = details.get("infeasibility_diagnosis")

    if run.status != "optimal":
        st.markdown("### 🔍 Diagnóstico")
        if diag:
            _render_diagnostico_infactibilidad(diag)
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
            _render_diagnostico_infactibilidad(diag)

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
