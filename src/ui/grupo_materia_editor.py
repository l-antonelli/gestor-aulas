"""Editor de grupos de materias (Streamlit).

Componente reutilizable montado desde la pestaña "📦 Grupos de materias"
del módulo Materias. Cubre:

- Lista de grupos con conteo de materias asignadas.
- Editor del grupo seleccionado: nombre, modo (DURO / BLANDO), lista
  ordenada de sedes (con ↑ / ↓ para reordenar).
- Reasignación de materias entre grupos (filtro rápido "Sólo Sin
  clasificar", filtro por grupo actual).
- Crear grupo nuevo / borrar grupo (deshabilitado si tiene materias
  asignadas o es el grupo Sin clasificar).

La partición estricta ("cada materia pertenece a exactamente un
grupo") se enforza en `asignar_materia_a_grupo` del servicio y en el
UI: la reasignación siempre elige un `grupo_id` del catálogo, no se
puede dejar en None.
"""

from __future__ import annotations

import streamlit as st
from sqlmodel import Session, select

from src.database.models import (
    GrupoMateriaDB,
    GrupoMateriaSedeDB,
    MateriaDB,
    SedeDB,
)
from src.services.grupo_materia_service import (
    asignar_materia_a_grupo,
    contar_materias_por_grupo,
    create_grupo,
    delete_grupo,
    get_config_grupo,
    get_grupo,
    get_grupo_sin_clasificar,
    list_grupos,
    list_materias_por_grupo,
    update_grupo,
)


# =============================================================================
# Punto de entrada público
# =============================================================================


def render_grupos_materias_tab(session: Session) -> None:
    """Renderiza el contenido completo de la pestaña Grupos de materias."""
    st.subheader("📦 Grupos de materias")
    st.caption(
        "Un grupo agrupa materias que comparten un mismo criterio de "
        "sedes admisibles. Cada materia pertenece a un único grupo. "
        "El asignador (LP) usa esta configuración para las restricciones "
        "R10 (sedes duras) y R12 (preferencia blanda). Los grupos base "
        "(F, FB, FI, CE, Específicas de <Carrera>, Sin clasificar) se "
        "crean automáticamente al arrancar la aplicación; podés editarlos "
        "o crear nuevos manualmente."
    )

    sedes_db = list(session.exec(select(SedeDB)).all())
    if not sedes_db:
        st.warning(
            "No hay sedes cargadas. Primero creá al menos una en la "
            "página Aulas → Sedes."
        )
        return

    grupos = list_grupos(session)
    counts = contar_materias_por_grupo(session)

    # Warning si hay materias en "Sin clasificar" — vale la pena
    # empujar al usuario a revisarlas.
    try:
        sc = get_grupo_sin_clasificar(session)
        n_sc = counts.get(sc.id, 0)
        if n_sc > 0:
            st.warning(
                f"⚠️ Hay **{n_sc} materia(s)** en el grupo "
                f"**Sin clasificar**. Reasignalas al grupo correcto para "
                "que el asignador tenga la restricción de sede bien "
                "definida.",
            )
    except ValueError:
        # No debería pasar en runtime porque la migración lo crea, pero
        # no queremos que la UI explote si falta.
        st.warning(
            "El grupo 'Sin clasificar' no existe. Reiniciá la app para "
            "que la migración inicial lo cree."
        )

    # Columnas: lista de grupos a la izquierda, editor a la derecha.
    col_lista, col_editor = st.columns([1, 2])

    with col_lista:
        _render_lista_grupos(session, grupos, counts, sedes_db)

    with col_editor:
        _render_editor_grupo(session, sedes_db)

    st.divider()
    _render_reasignacion_materias(session, grupos, counts)


# =============================================================================
# Lista de grupos + creación / borrado
# =============================================================================


def _render_lista_grupos(
    session: Session,
    grupos: list[GrupoMateriaDB],
    counts: dict[str, int],
    sedes_db: list[SedeDB],
) -> None:
    """Panel izquierdo con la lista de grupos y controles de crear /
    borrar."""
    st.markdown("### Lista de grupos")

    # Ordenar: primero "Sin clasificar" (fallback), después alfabético.
    def _sort_key(g: GrupoMateriaDB) -> tuple[int, str]:
        return (0 if g.es_sin_clasificar else 1, g.nombre.lower())

    grupos_ordenados = sorted(grupos, key=_sort_key)
    labels = []
    for g in grupos_ordenados:
        prefix = "⚠️ " if g.es_sin_clasificar else "📦 "
        n = counts.get(g.id, 0)
        labels.append(f"{prefix}{g.nombre} · {n} materia(s) · {g.modo}")

    seleccionado = st.session_state.get("grupo_materia_seleccionado")
    default_idx = 0
    if seleccionado:
        for i, g in enumerate(grupos_ordenados):
            if g.id == seleccionado:
                default_idx = i
                break

    if labels:
        elegido = st.radio(
            "Grupos existentes",
            options=list(range(len(labels))),
            format_func=lambda i: labels[i],
            index=default_idx,
            key="grupo_materia_radio",
            label_visibility="collapsed",
        )
        st.session_state["grupo_materia_seleccionado"] = (
            grupos_ordenados[elegido].id
        )
    else:
        st.info("No hay grupos cargados.")

    st.divider()

    # ---- Crear grupo nuevo ---------------------------------------------
    with st.expander("➕ Crear grupo nuevo", expanded=False):
        with st.form(key="crear_grupo_form"):
            nuevo_nombre = st.text_input(
                "Nombre del grupo",
                placeholder="Ej: Optativas de Sistemas",
            )
            nuevo_modo = st.radio(
                "Modo",
                options=["DURO", "BLANDO"],
                horizontal=True,
                help=(
                    "DURO: sólo se admiten las sedes de la lista. "
                    "BLANDO: cualquier sede admite, pero la primera "
                    "es preferida a nivel objetivo."
                ),
            )
            sede_names = [s.nombre for s in sedes_db]
            sede_ids_map = {s.nombre: s.id for s in sedes_db}
            nuevas_sedes = st.multiselect(
                "Sedes admisibles",
                options=sede_names,
                help=(
                    "El orden importa sólo en BLANDO (0 = preferida)."
                ),
            )
            submitted = st.form_submit_button(
                "Crear grupo", type="primary",
            )
            if submitted:
                if not nuevo_nombre.strip():
                    st.error("El nombre no puede quedar vacío.")
                else:
                    try:
                        create_grupo(
                            session,
                            nuevo_nombre.strip(),
                            nuevo_modo,  # type: ignore[arg-type]
                            [sede_ids_map[n] for n in nuevas_sedes],
                        )
                        st.success(f"Grupo '{nuevo_nombre}' creado.")
                        st.rerun()
                    except ValueError as e:
                        st.error(str(e))


# =============================================================================
# Editor del grupo seleccionado
# =============================================================================


def _render_editor_grupo(
    session: Session, sedes_db: list[SedeDB],
) -> None:
    """Panel derecho: editor del grupo que esté activo."""
    st.markdown("### Editar grupo")
    grupo_id = st.session_state.get("grupo_materia_seleccionado")
    if not grupo_id:
        st.info("Seleccioná un grupo de la lista para editarlo.")
        return

    try:
        grupo = get_grupo(session, grupo_id)
    except ValueError:
        st.error("El grupo ya no existe.")
        st.session_state.pop("grupo_materia_seleccionado", None)
        return

    sedes_ordenadas_actual, modo_actual = get_config_grupo(session, grupo.id)
    sede_nombre_by_id = {s.id: s.nombre for s in sedes_db}
    sede_id_by_nombre = {s.nombre: s.id for s in sedes_db}

    # --- Editor de metadata ---------------------------------------------
    nombre_edit = st.text_input(
        "Nombre",
        value=grupo.nombre,
        disabled=grupo.es_sin_clasificar,
        key=f"grupo_nombre_{grupo.id}",
        help=(
            "El grupo 'Sin clasificar' no puede renombrarse — es el "
            "fallback del sistema." if grupo.es_sin_clasificar else None
        ),
    )
    modo_edit = st.radio(
        "Modo",
        options=["DURO", "BLANDO"],
        index=0 if modo_actual == "DURO" else 1,
        horizontal=True,
        key=f"grupo_modo_{grupo.id}",
        help=(
            "DURO: sólo se admiten las sedes de la lista. "
            "BLANDO: cualquier sede admite, pero la primera es "
            "preferida a nivel objetivo (R12 del LP)."
        ),
    )

    # --- Lista ordenada de sedes con ↑ / ↓ ------------------------------
    st.markdown("**Sedes admisibles (orden)**")
    st.caption(
        "En modo BLANDO, el orden es semántico: la primera es la sede "
        "preferida, las siguientes son alternativas con costo. En modo "
        "DURO, todas son equivalentes; el orden se conserva para "
        "estabilidad visual."
    )

    # Estado local del orden (session_state por grupo).
    order_key = f"grupo_orden_{grupo.id}"
    if (
        order_key not in st.session_state
        or st.session_state.get(f"{order_key}_source") != grupo.id
    ):
        st.session_state[order_key] = list(sedes_ordenadas_actual)
        st.session_state[f"{order_key}_source"] = grupo.id
    orden_local: list[str] = list(st.session_state[order_key])

    # Filtrar sedes que quedaron huérfanas (por borrado de sede).
    orden_local = [s for s in orden_local if s in sede_nombre_by_id]

    for i, sede_id in enumerate(orden_local):
        row = st.container()
        cols = row.columns([5, 1, 1, 1])
        cols[0].markdown(
            f"**{i + 1}. {sede_nombre_by_id.get(sede_id, sede_id)}**"
        )
        # ↑
        if cols[1].button(
            "↑", key=f"up_{grupo.id}_{sede_id}",
            disabled=(i == 0),
            help="Mover hacia arriba",
        ):
            orden_local[i - 1], orden_local[i] = (
                orden_local[i], orden_local[i - 1]
            )
            st.session_state[order_key] = orden_local
            st.rerun()
        # ↓
        if cols[2].button(
            "↓", key=f"dn_{grupo.id}_{sede_id}",
            disabled=(i == len(orden_local) - 1),
            help="Mover hacia abajo",
        ):
            orden_local[i], orden_local[i + 1] = (
                orden_local[i + 1], orden_local[i]
            )
            st.session_state[order_key] = orden_local
            st.rerun()
        # ✕
        if cols[3].button(
            "✕", key=f"rm_{grupo.id}_{sede_id}",
            help="Quitar del grupo",
        ):
            orden_local.remove(sede_id)
            st.session_state[order_key] = orden_local
            st.rerun()

    # Agregar sede.
    sedes_no_incluidas = [
        s for s in sedes_db if s.id not in orden_local
    ]
    if sedes_no_incluidas:
        add_col1, add_col2 = st.columns([3, 1])
        with add_col1:
            add_choice = st.selectbox(
                "Agregar sede al grupo",
                options=[s.nombre for s in sedes_no_incluidas],
                key=f"add_{grupo.id}",
                label_visibility="collapsed",
            )
        with add_col2:
            if st.button("Agregar", key=f"add_btn_{grupo.id}"):
                orden_local.append(sede_id_by_nombre[add_choice])
                st.session_state[order_key] = orden_local
                st.rerun()
    else:
        st.caption("Todas las sedes ya están en el grupo.")

    # Preview.
    if orden_local:
        st.info(
            "**Vista previa · sedes admisibles resultantes**: "
            + " → ".join(
                sede_nombre_by_id.get(s, s) for s in orden_local
            )
            + (
                f" (preferida en BLANDO: **"
                f"{sede_nombre_by_id.get(orden_local[0], orden_local[0])}**)"
                if modo_edit == "BLANDO" and orden_local else ""
            )
        )
    else:
        st.warning(
            "Lista vacía. En modo DURO significa 'todas las sedes "
            "admisibles' (fallback permisivo). En modo BLANDO no hay "
            "sede preferida — el LP no aplica R12 para materias de "
            "este grupo."
        )

    # --- Guardar / borrar -----------------------------------------------
    st.divider()
    col_save, col_reset, col_delete = st.columns([2, 1, 1])
    with col_save:
        if st.button(
            "💾 Guardar cambios", type="primary",
            key=f"save_{grupo.id}",
        ):
            try:
                nombre_final = (
                    (nombre_edit or grupo.nombre).strip()
                    or grupo.nombre
                )
                update_grupo(
                    session,
                    grupo.id,
                    nombre_final,
                    modo_edit,  # type: ignore[arg-type]
                    orden_local,
                )
                st.success("Cambios guardados.")
                # Limpiar cache local.
                st.session_state.pop(order_key, None)
                st.session_state.pop(f"{order_key}_source", None)
                st.rerun()
            except ValueError as e:
                st.error(str(e))
    with col_reset:
        if st.button(
            "↺ Descartar", key=f"reset_{grupo.id}",
        ):
            st.session_state.pop(order_key, None)
            st.session_state.pop(f"{order_key}_source", None)
            st.rerun()
    with col_delete:
        tiene_materias = _grupo_tiene_materias(session, grupo.id)
        disabled = grupo.es_sin_clasificar or tiene_materias
        delete_help = (
            "El grupo 'Sin clasificar' no se puede borrar."
            if grupo.es_sin_clasificar else (
                "El grupo tiene materias asignadas — reasignalas primero."
                if tiene_materias else "Borrar este grupo."
            )
        )
        if st.button(
            "🗑️ Borrar",
            disabled=disabled,
            help=delete_help,
            key=f"del_{grupo.id}",
        ):
            try:
                delete_grupo(session, grupo.id)
                st.success(f"Grupo '{grupo.nombre}' borrado.")
                st.session_state.pop("grupo_materia_seleccionado", None)
                st.rerun()
            except ValueError as e:
                st.error(str(e))


# =============================================================================
# Reasignación de materias
# =============================================================================


def _render_reasignacion_materias(
    session: Session,
    grupos: list[GrupoMateriaDB],
    counts: dict[str, int],  # noqa: ARG001 (reservado para futuros contadores)
) -> None:
    """Panel inferior con la tabla de materias y su grupo actual —
    permite reasignar en batch."""
    st.markdown("### Reasignar materias")

    grupo_id_to_grupo = {g.id: g for g in grupos}

    # Filtros.
    col_f1, col_f2 = st.columns([1, 2])
    with col_f1:
        filtro_scope = st.selectbox(
            "Filtro rápido",
            options=[
                "Todas",
                "Sólo Sin clasificar",
                "Por grupo actual…",
            ],
            key="filtro_materias_reasignar",
        )
    grupo_actual_filtro: str | None = None
    if filtro_scope == "Por grupo actual…":
        with col_f2:
            grupo_nombre_choice = st.selectbox(
                "Grupo",
                options=[g.nombre for g in grupos],
                key="filtro_grupo_actual",
            )
            for g in grupos:
                if g.nombre == grupo_nombre_choice:
                    grupo_actual_filtro = g.id
                    break

    # Query materias según el filtro.
    if filtro_scope == "Sólo Sin clasificar":
        try:
            sc = get_grupo_sin_clasificar(session)
            materias = list_materias_por_grupo(session, sc.id)
        except ValueError:
            materias = []
    elif filtro_scope == "Por grupo actual…" and grupo_actual_filtro:
        materias = list_materias_por_grupo(session, grupo_actual_filtro)
    else:
        materias = list(session.exec(
            select(MateriaDB).order_by(MateriaDB.codigo)  # type: ignore[arg-type]
        ).all())

    if not materias:
        st.info("No hay materias que coincidan con el filtro.")
        return

    st.caption(
        f"{len(materias)} materia(s) a mostrar. Elegí el grupo de destino "
        "en la columna 'Grupo nuevo' y presioná 'Guardar cambios'."
    )

    grupo_nombres = [g.nombre for g in grupos]
    grupo_nombre_to_id = {g.nombre: g.id for g in grupos}

    # Cache de cambios pendientes en session_state.
    pending_key = "materias_reasignacion_pending"
    pending: dict[str, str] = st.session_state.setdefault(pending_key, {})

    with st.form(key="form_reasignar_materias"):
        # Header.
        h1, h2, h3, h4 = st.columns([1, 3, 2, 2])
        h1.markdown("**Código**")
        h2.markdown("**Nombre**")
        h3.markdown("**Grupo actual**")
        h4.markdown("**Grupo nuevo**")

        for m in materias[:200]:  # cota para no romper el render
            c1, c2, c3, c4 = st.columns([1, 3, 2, 2])
            c1.write(f"`{m.codigo}`")
            c2.write(m.nombre)
            gactual = (
                grupo_id_to_grupo.get(m.grupo_id) if m.grupo_id else None
            )
            gactual_nombre = gactual.nombre if gactual else "—"
            c3.write(gactual_nombre)
            # Selectbox.
            default_idx = 0
            if m.grupo_id and gactual:
                try:
                    default_idx = grupo_nombres.index(gactual.nombre)
                except ValueError:
                    default_idx = 0
            nuevo = c4.selectbox(
                f"grupo_{m.codigo}",
                options=grupo_nombres,
                index=default_idx,
                key=f"reasign_{m.codigo}",
                label_visibility="collapsed",
            )
            nuevo_id = grupo_nombre_to_id.get(nuevo)
            if nuevo_id and nuevo_id != m.grupo_id:
                pending[m.codigo] = nuevo_id
            elif m.codigo in pending and nuevo_id == m.grupo_id:
                pending.pop(m.codigo, None)

        if len(materias) > 200:
            st.caption(
                f"Mostrando las primeras 200 de {len(materias)}. Usá "
                "el filtro para acotar."
            )

        submit = st.form_submit_button(
            f"💾 Guardar cambios ({len(pending)} pendiente(s))",
            type="primary",
            disabled=len(pending) == 0,
        )
        if submit and pending:
            n_ok = 0
            errores: list[str] = []
            for materia_codigo, nuevo_gid in pending.items():
                try:
                    asignar_materia_a_grupo(
                        session, materia_codigo, nuevo_gid,
                    )
                    n_ok += 1
                except ValueError as e:
                    errores.append(f"{materia_codigo}: {e}")
            if errores:
                st.error(
                    f"{len(errores)} error(es): "
                    + "; ".join(errores[:5])
                )
            if n_ok:
                st.success(f"{n_ok} materia(s) reasignada(s).")
            st.session_state[pending_key] = {}
            st.rerun()


# =============================================================================
# Helpers privados
# =============================================================================


def _grupo_tiene_materias(session: Session, grupo_id: str) -> bool:
    row = session.exec(
        select(MateriaDB).where(MateriaDB.grupo_id == grupo_id).limit(1)
    ).first()
    return row is not None


# NOTE: no exponemos `GrupoMateriaSedeDB` en la API pública del módulo —
# la tabla se manipula sólo a través del servicio.
_ = GrupoMateriaSedeDB  # noqa: F841
