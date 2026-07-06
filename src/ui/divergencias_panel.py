"""Panel de divergencias entre los dictados de un ciclo y las reglas
vigentes en MateriaDB/CarreraDB.

Componente reutilizable para la pagina de Ciclos (`4_📆_Ciclos.py`).
Muestra en tres secciones colapsables (una por categoria de divergencia)
las materias/dictados afectados, con acciones fila-a-fila:

- **to_create** (materia del plan sin dictado, regla dice que si):
  - `[✅ Crear]`: crea el dictado.
  - `[⏭️ Omitir en regla]`: setea MateriaDB.dicta_recursado=False para
    que ciclos futuros la skippen automaticamente.

- **to_delete** (dictado huerfano, la materia ya no esta en el plan):
  - `[🗑️ Borrar]`: borra el dictado y nullifica clases huerfanas.

- **rule_says_skip_but_exists** (dictado existe pero regla dice skippear):
  - `[🗑️ Borrar]`.
  - `[⬆️ Promover a regla]`: setea MateriaDB.dicta_recursado=True para
    que ciclos futuros la creen automaticamente.

Adicionalmente ofrece un boton masivo "Aplicar todo (crear + borrar)"
que corre `sync_dictados_para_ciclo(apply=True)`.
"""

from __future__ import annotations

import streamlit as st

from src.database.connection import get_session
from src.services.change_log_service import change_context
from src.services.dictado_service import (
    borrar_dictado_de_ciclo,
    create_dictado_for_materia,
    promover_a_regla,
    sync_dictados_para_ciclo,
)


def _fmt_ubicacion(item: dict) -> str:
    """`3° · 1C` / `5° · Anual` / `—` segun anio/cuatri."""
    a = item.get("anio_plan")
    c = item.get("cuatrimestre_plan")
    if a and c:
        return f"{a}° · {c}"
    if a:
        return f"{a}°"
    if c:
        return c
    return "—"


def render_panel_divergencias(
    ciclo_id: str,
    drift,
    *,
    on_change_key: str = "dict_resync_pending",
) -> None:
    """Renderiza el panel completo de divergencias.

    Args:
        ciclo_id: ciclo a sincronizar.
        drift: `DriftSummary` computado previamente (evita re-consultar).
        on_change_key: session_state key que se setea a True cuando el
            usuario aplica cualquier cambio (para que la pagina llamante
            re-sincronice sus caches).
    """
    if drift.is_clean:
        st.success(
            "✅ No hay divergencias: los dictados del ciclo están "
            "alineados con las reglas vigentes."
        )
        return

    n_create = len(drift.to_create)
    n_delete = len(drift.to_delete)
    n_keep_skip = len(drift.rule_says_skip_but_exists)

    st.markdown(
        f"### ⚠️ Divergencias: {n_create} a crear · {n_delete} a "
        f"borrar · {n_keep_skip} existen pero la regla dice que no"
    )
    st.caption(
        "Compara los dictados del ciclo contra las materias del plan "
        "asignado + las reglas de recursado (MateriaDB/CarreraDB.dicta_"
        "recursado). Cada fila tiene acciones para aplicar puntualmente "
        "o promover la decisión a la regla general."
    )

    # ----- Botón masivo "Aplicar todo" -----
    _bc1, _bc2, _bc_rest = st.columns([2, 3, 5])
    with _bc1:
        if (n_create + n_delete) > 0 and st.button(
            f"⚡ Aplicar todo ({n_create + n_delete} cambios)",
            type="primary",
            key=f"btn_apply_all_divergencias_{ciclo_id}",
            help=(
                "Aplica los cambios de to_create y to_delete. NO toca "
                "'existen pero regla dice que no' (esos requieren "
                "decision explicita por fila)."
            ),
        ):
            with next(get_session()) as _s:
                with change_context(
                    origin="ui:ciclos",
                    reason=(
                        f"Sincronización masiva del ciclo {ciclo_id} "
                        "desde el panel de divergencias"
                    ),
                ):
                    res = sync_dictados_para_ciclo(_s, ciclo_id, apply=True)
            st.session_state[on_change_key] = True
            st.toast(
                f"✅ {res.n_changes} cambio(s) aplicado(s): "
                f"{len(res.to_create)} creado(s), "
                f"{len(res.to_delete)} borrado(s)."
            )
            st.rerun()
    with _bc2:
        st.caption(
            "Los cambios en 'existen pero la regla dice que no' NO se "
            "aplican masivamente — hay que decidir fila a fila."
        )

    st.divider()

    # ----- Seccion to_create -----
    if n_create > 0:
        with st.expander(
            f"➕ Materias del plan sin dictado ({n_create})",
            expanded=True,
        ):
            st.caption(
                "La materia está en el plan del ciclo y la regla de "
                "recursado dice que debería existir un dictado, pero "
                "no está creado."
            )
            _render_bulk_promover(
                ciclo_id, drift.to_create, on_change_key,
                accion="omitir-en-regla",
                boton_label="⏭️ Omitir TODAS en regla",
                confirm_prefix=f"omitir_{ciclo_id}",
                help_text=(
                    "Setea MateriaDB.dicta_recursado=False para TODAS "
                    "las materias de esta lista. En ciclos futuros dejarán "
                    "de aparecer como esperadas. NO crea ni borra dictados "
                    "en este ciclo."
                ),
            )
            for it in drift.to_create:
                _render_row_to_create(ciclo_id, it, on_change_key)

    # ----- Seccion to_delete -----
    if n_delete > 0:
        with st.expander(
            f"🗑️ Dictados huérfanos ({n_delete})",
            expanded=True,
        ):
            st.caption(
                "El dictado existe pero la materia ya no está en el plan "
                "asignado al ciclo (suele pasar tras cambiar de versión "
                "de plan)."
            )
            for it in drift.to_delete:
                _render_row_to_delete(ciclo_id, it, on_change_key)

    # ----- Seccion rule_says_skip_but_exists -----
    if n_keep_skip > 0:
        with st.expander(
            f"⚠️ Existen pero la regla dice que no ({n_keep_skip})",
            expanded=False,
        ):
            st.caption(
                "El dictado fue creado (probablemente a mano) pero las "
                "reglas actuales de MateriaDB/CarreraDB dicen que no "
                "debería existir. **No se borran automáticamente**. "
                "Elegí: borrarlos si fue error, o promover la decisión "
                "a regla general para que en ciclos futuros no se marquen "
                "como divergencia."
            )
            _render_bulk_promover(
                ciclo_id, drift.rule_says_skip_but_exists, on_change_key,
                accion="crear-en-regla",
                boton_label="⬆️ Promover TODAS a regla",
                confirm_prefix=f"promover_{ciclo_id}",
                help_text=(
                    "Setea MateriaDB.dicta_recursado=True para TODAS "
                    "las materias de esta lista. En ciclos futuros pasarán "
                    "a ser esperadas por defecto. NO crea ni borra "
                    "dictados en este ciclo."
                ),
            )
            for it in drift.rule_says_skip_but_exists:
                _render_row_keep_skip(ciclo_id, it, on_change_key)


def _render_bulk_promover(
    ciclo_id: str,
    items: list[dict],
    on_change_key: str,
    *,
    accion: str,  # "crear-en-regla" | "omitir-en-regla"
    boton_label: str,
    confirm_prefix: str,
    help_text: str,
) -> None:
    """Boton bulk para promover a regla TODAS las materias de una
    seccion, con confirmacion en 2 pasos.

    Estado guardado en session_state: `dict_confirming_bulk_{prefix}`
    (bool). Primer click lo setea a True; en el siguiente render, en
    lugar del boton aparece el bloque de confirmacion. `Confirmar`
    aplica y limpia el flag; `Cancelar` solo limpia el flag.
    """
    if not items:
        return
    n = len(items)
    confirm_key = f"dict_confirming_bulk_{confirm_prefix}"
    is_confirming = bool(st.session_state.get(confirm_key, False))

    if not is_confirming:
        _c1, _c_rest = st.columns([2, 5])
        with _c1:
            if st.button(
                f"{boton_label} ({n})",
                key=f"btn_bulk_{confirm_prefix}",
                help=help_text,
                use_container_width=True,
            ):
                st.session_state[confirm_key] = True
                st.rerun()
        return

    # Modo confirmacion.
    st.warning(
        f"⚠️ Vas a modificar **{n} materia(s) del catálogo** "
        f"(`MateriaDB.dicta_recursado`). Esto **afecta todos los "
        f"ciclos futuros** — no sólo el actual. Los dictados del "
        f"ciclo actual **no se tocan** hasta que apliques manualmente "
        f"(botón `⚡ Aplicar todo` o acciones fila-a-fila).",
    )
    _c1, _c2, _c_rest = st.columns([1.5, 1.2, 5])
    with _c1:
        if st.button(
            f"✅ Confirmar ({n})",
            type="primary",
            key=f"btn_bulk_confirm_{confirm_prefix}",
        ):
            _reason = (
                f"Bulk promover: {accion} en {n} materia(s) desde el "
                f"panel de divergencias del ciclo {ciclo_id}"
            )
            n_aplicados = 0
            with next(get_session()) as _s:
                with change_context(origin="ui:ciclos", reason=_reason):
                    for it in items:
                        if promover_a_regla(
                            _s, it["materia_codigo"], ciclo_id,
                            accion=accion,
                        ):
                            n_aplicados += 1
            st.session_state[on_change_key] = True
            st.session_state[confirm_key] = False
            st.toast(
                f"✅ {n_aplicados}/{n} materia(s) actualizada(s) en la "
                "regla general."
            )
            st.rerun()
    with _c2:
        if st.button(
            "🚫 Cancelar",
            key=f"btn_bulk_cancel_{confirm_prefix}",
        ):
            st.session_state[confirm_key] = False
            st.rerun()


def _render_row_to_create(
    ciclo_id: str, item: dict, on_change_key: str,
) -> None:
    """Fila to_create con acciones [Crear] / [Omitir en regla]."""
    c_info, c_ubic, c_a1, c_a2 = st.columns([4, 1.5, 1.2, 1.6])
    with c_info:
        st.markdown(
            f"**{item['materia_codigo']}** — {item['materia_nombre']}  \n"
            f"<span style='color:#888;font-size:0.85em'>"
            f"🎓 {item['carrera_nombre']} · _{item['razon']}_"
            f"</span>",
            unsafe_allow_html=True,
        )
    with c_ubic:
        st.caption(_fmt_ubicacion(item))
    with c_a1:
        if st.button(
            "✅ Crear",
            key=f"btn_create_{ciclo_id}_{item['materia_codigo']}",
            help="Crear el dictado en este ciclo.",
            use_container_width=True,
        ):
            with next(get_session()) as _s:
                with change_context(
                    origin="ui:ciclos",
                    reason=(
                        f"Crear dictado ({item['materia_codigo']}) "
                        f"desde panel de divergencias del ciclo {ciclo_id}"
                    ),
                ):
                    create_dictado_for_materia(
                        _s, ciclo_id, item["materia_codigo"],
                    )
            st.session_state[on_change_key] = True
            st.toast(f"✅ Dictado creado: {item['materia_codigo']}")
            st.rerun()
    with c_a2:
        if st.button(
            "⏭️ Omitir en regla",
            key=f"btn_skip_rule_{ciclo_id}_{item['materia_codigo']}",
            help=(
                "Setear MateriaDB.dicta_recursado=False para que ciclos "
                "futuros omitan esta materia automáticamente. NO crea "
                "el dictado ni afecta otros ciclos existentes."
            ),
            use_container_width=True,
        ):
            with next(get_session()) as _s:
                with change_context(
                    origin="ui:ciclos",
                    reason=(
                        f"Promoción a regla (omitir) desde panel de "
                        f"divergencias del ciclo {ciclo_id}"
                    ),
                ):
                    promover_a_regla(
                        _s, item["materia_codigo"], ciclo_id,
                        accion="omitir-en-regla",
                    )
            st.session_state[on_change_key] = True
            st.toast(
                f"⏭️ {item['materia_codigo']}: dicta_recursado=False. "
                "Aplica en ciclos futuros."
            )
            st.rerun()


def _render_row_to_delete(
    ciclo_id: str, item: dict, on_change_key: str,
) -> None:
    """Fila to_delete con accion [Borrar]."""
    c_info, c_a = st.columns([6, 1.4])
    with c_info:
        st.markdown(
            f"`{item['dictado_codigo']}` — **{item['materia_codigo']}** "
            f"({item['materia_nombre']})"
        )
    with c_a:
        if st.button(
            "🗑️ Borrar",
            key=f"btn_delete_orphan_{ciclo_id}_{item['dictado_id']}",
            help=(
                "Borra el dictado y sus vinculos con este ciclo. Las "
                "clases asociadas quedan sin dictado (huérfanas) pero "
                "no se borran."
            ),
            use_container_width=True,
        ):
            with next(get_session()) as _s:
                with change_context(
                    origin="ui:ciclos",
                    reason=(
                        f"Borrar huérfano ({item['materia_codigo']}) del "
                        f"ciclo {ciclo_id} (materia ya no está en el plan)"
                    ),
                ):
                    borrar_dictado_de_ciclo(_s, ciclo_id, item["dictado_id"])
            st.session_state[on_change_key] = True
            st.toast(f"🗑️ Dictado borrado: {item['dictado_codigo']}")
            st.rerun()


def _render_row_keep_skip(
    ciclo_id: str, item: dict, on_change_key: str,
) -> None:
    """Fila rule_says_skip_but_exists con acciones [Borrar] / [Promover]."""
    c_info, c_ubic, c_a1, c_a2 = st.columns([4, 1.5, 1.2, 1.6])
    with c_info:
        st.markdown(
            f"**{item['materia_codigo']}** — {item['materia_nombre']}  \n"
            f"<span style='color:#888;font-size:0.85em'>"
            f"🎓 {item['carrera_nombre']} · _{item['razon']}_"
            f"</span>",
            unsafe_allow_html=True,
        )
    with c_ubic:
        st.caption(_fmt_ubicacion(item))
    with c_a1:
        if st.button(
            "🗑️ Borrar",
            key=f"btn_delete_keep_{ciclo_id}_{item['dictado_id']}",
            help="Borrar este dictado (se creó por error o ya no aplica).",
            use_container_width=True,
        ):
            with next(get_session()) as _s:
                with change_context(
                    origin="ui:ciclos",
                    reason=(
                        f"Borrar dictado ({item['materia_codigo']}) del "
                        f"ciclo {ciclo_id} — regla decía skippear"
                    ),
                ):
                    borrar_dictado_de_ciclo(_s, ciclo_id, item["dictado_id"])
            st.session_state[on_change_key] = True
            st.toast(f"🗑️ Dictado borrado: {item['dictado_codigo']}")
            st.rerun()
    with c_a2:
        if st.button(
            "⬆️ Promover a regla",
            key=f"btn_promote_{ciclo_id}_{item['materia_codigo']}",
            help=(
                "Setear MateriaDB.dicta_recursado=True para que ciclos "
                "futuros creen automáticamente el dictado de esta "
                "materia. La regla nueva convierte esta divergencia en "
                "el comportamiento esperado."
            ),
            use_container_width=True,
        ):
            with next(get_session()) as _s:
                with change_context(
                    origin="ui:ciclos",
                    reason=(
                        f"Promoción a regla (crear) desde panel de "
                        f"divergencias del ciclo {ciclo_id}"
                    ),
                ):
                    promover_a_regla(
                        _s, item["materia_codigo"], ciclo_id,
                        accion="crear-en-regla",
                    )
            st.session_state[on_change_key] = True
            st.toast(
                f"⬆️ {item['materia_codigo']}: dicta_recursado=True. "
                "Aplica en ciclos futuros."
            )
            st.rerun()
