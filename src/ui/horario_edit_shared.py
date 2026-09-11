"""Widgets compartidos para editar horarios del plan de cursada.

Cualquier UI que muta ``HorarioDB.dia/hora_inicio/hora_fin`` (día u horas)
debe correr el preview antes de commitear, para que el operador vea:

- **Colisiones de aula** (mismo aula, franjas superpuestas — doble booking).
- **Conflictos de solapamiento** entre materias del mismo grupo curricular
  que el cambio agrega o resuelve.
- **Duplicados** de la misma comisión en el mismo día.

El resultado se muestra inline con banners de severidad; el botón
Guardar se etiqueta según haya o no riesgo residual. La lógica de
detección vive en ``plan_actions_service.preview_cambio_horario``; este
módulo solo aporta el renderer de UI compartido.
"""

from __future__ import annotations

from datetime import time
from typing import Optional

import streamlit as st

from src.database.connection import get_session
from src.services.plan_actions_service import (
    CambioHorarioPreview,
    preview_cambio_horario,
)


def render_preview_impacto_edicion(
    *,
    plan_id: str,
    horario_id: str,
    nuevo_dia: str,
    nuevo_hora_inicio: Optional[time],
    nuevo_hora_fin: Optional[time],
    hubo_cambio_slot: bool,
) -> Optional[CambioHorarioPreview]:
    """Renderea el bloque de preview (banners + tablas) para una
    edición propuesta y devuelve el ``CambioHorarioPreview``.

    Cuando ``hubo_cambio_slot`` es False (el usuario no cambió día ni
    horas), devuelve ``None`` y no renderea nada. Cuando alguno de los
    tiempos es ``None`` también salta — el widget de input todavía
    no tiene un valor válido.

    Uso:
        preview = render_preview_impacto_edicion(...)
        hay_riesgo = bool(
            preview and not preview.error and (
                preview.colisiones_aula
                or preview.conflictos_agregados
                or preview.duplicados_mismo_dia
            )
        )
        label = "⚠️ Guardar de todos modos" if hay_riesgo else "Guardar"
        if st.button(label, ...):
            ... commit
    """
    if not hubo_cambio_slot:
        return None
    if nuevo_hora_inicio is None or nuevo_hora_fin is None:
        return None

    with next(get_session()) as _sess:
        preview = preview_cambio_horario(
            _sess, plan_id, horario_id,
            nuevo_dia, nuevo_hora_inicio, nuevo_hora_fin,
        )

    if preview.error:
        st.error(f"❌ {preview.error}")
        return preview

    if preview.colisiones_aula:
        st.error(
            f"🚨 **Doble booking de aula**: mover este horario "
            f"dejaría el aula asignada en simultáneo con "
            f"**{len(preview.colisiones_aula)} otra(s) clase(s)**. "
            "Después de guardar podés liberar el aula del horario "
            "editado o del que colisiona desde el panel del "
            "asignador (**🚨 colisiones de aula**)."
        )
        with st.expander(
            f"Ver colisiones ({len(preview.colisiones_aula)})",
            expanded=True,
        ):
            _rows_col = [
                {
                    "Materia": c.get("codigo_materia"),
                    "Día": c.get("dia"),
                    "Inicio": c.get("hora_inicio"),
                    "Fin": c.get("hora_fin"),
                    "Manual": "sí" if c.get("otro_manual") else "no",
                }
                for c in preview.colisiones_aula
            ]
            st.dataframe(
                _rows_col,
                hide_index=True,
                use_container_width=True,
            )

    if preview.conflictos_agregados:
        st.warning(
            f"⚠️ Este cambio agregaría "
            f"**{len(preview.conflictos_agregados)} conflicto(s) "
            "nuevo(s)** de solapamiento entre materias del mismo "
            "grupo curricular."
        )
        with st.expander(
            f"Ver detalle ({len(preview.conflictos_agregados)})",
            expanded=False,
        ):
            st.dataframe(
                [
                    {
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
                    }
                    for c in preview.conflictos_agregados
                ],
                hide_index=True,
                use_container_width=True,
            )

    if preview.duplicados_mismo_dia:
        st.warning(
            f"⚠️ La comisión ya tiene "
            f"**{len(preview.duplicados_mismo_dia)} clase(s)** el "
            f"{preview.propuesto.get('dia')}. "
            "Verificá que no sea un duplicado."
        )

    if preview.conflictos_resueltos:
        st.info(
            f"ℹ️ El cambio **resuelve** "
            f"{len(preview.conflictos_resueltos)} "
            "conflicto(s) existente(s)."
        )

    if preview.es_seguro:
        st.success(
            "✅ Sin conflictos nuevos ni colisiones de aula."
        )

    return preview


def preview_hay_riesgo(preview: Optional[CambioHorarioPreview]) -> bool:
    """True si el preview reporta algún riesgo residual (colisión,
    conflicto agregado, duplicado). El botón Guardar debe cambiar de
    etiqueta cuando esto sea True.

    ``preview=None`` → no hay riesgo (el usuario no tocó día/hora).
    """
    if preview is None or preview.error:
        return False
    return bool(
        preview.colisiones_aula
        or preview.conflictos_agregados
        or preview.duplicados_mismo_dia
    )
