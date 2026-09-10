"""Editor de grupos de materias (Streamlit).

Cada grupo declara AMBAS configuraciones de sede (set DURO y lista
BLANDA) simultáneamente. La elección del modo por-grupo se hace en el
panel del asignador (LP), no acá. Este editor sólo maneja qué sedes
componen cada set y qué carreras están asociadas al grupo para el
chequeo de consistencia.

Estructura:

1. Lista de grupos (izquierda) con conteo de materias y warnings.
2. Editor del grupo activo (derecha) en contenedores diferenciados:
   nombre, carreras asociadas, sedes DURO (multiselect), sedes BLANDA
   (lista ordenada con ↑ / ↓ / ✕).
3. Botón "Chequear consistencia" que compara materias exclusivas de
   las carreras asociadas contra las que hay en el grupo.
4. Panel de reasignación con filtros robustos (ubicación curricular,
   atributos, búsqueda por código/nombre con normalización de acentos).
"""

from __future__ import annotations

import unicodedata

import streamlit as st
from sqlmodel import Session, select

from src.database.models import (
    CarreraDB,
    GrupoMateriaCarreraDB,
    GrupoMateriaDB,
    GrupoMateriaSedeDB,
    MateriaDB,
    MateriaLaboratorioDB,
    PlanCarreraVersionDB,
    PlanEstudioDB,
    SedeDB,
)
from src.services.grupo_materia_service import (
    asignar_materia_a_grupo,
    chequear_consistencia_grupo,
    contar_materias_por_grupo,
    create_grupo,
    delete_grupo,
    get_config_grupo,
    get_grupo,
    get_grupo_sin_clasificar,
    get_plan_activo,
    list_grupos,
    list_materias_por_grupo,
    list_materias_sin_clasificar,
    update_grupo,
)


# =============================================================================
# Punto de entrada público
# =============================================================================


def render_grupos_materias_tab(session: Session) -> None:
    """Renderiza el contenido completo de la pestaña Grupos de materias."""
    st.subheader("📦 Grupos de materias")
    st.caption(
        "Un **grupo** agrupa materias que comparten un mismo criterio "
        "de sedes admisibles. Cada materia pertenece a un único grupo. "
        "Cada grupo declara **dos configuraciones** al mismo tiempo: un "
        "**set duro** (sedes admisibles cuando el asignador corre en "
        "modo DURO) y una **lista ordenada blanda** (sedes preferidas "
        "cuando el asignador corre en modo BLANDO). La elección del "
        "modo por-grupo se hace en el panel del asignador."
    )

    sedes_db = list(session.exec(select(SedeDB)).all())
    if not sedes_db:
        st.warning(
            "No hay sedes cargadas. Primero creá al menos una en la "
            "página Aulas → Sedes."
        )
        return

    carreras_db = list(session.exec(select(CarreraDB)).all())
    grupos = list_grupos(session)
    counts = contar_materias_por_grupo(session)

    # Warning global si "Sin clasificar" tiene materias.
    try:
        sc = get_grupo_sin_clasificar(session)
        n_sc = counts.get(sc.id, 0)
        if n_sc > 0:
            st.warning(
                f"⚠️ Hay **{n_sc} materia(s)** en el grupo "
                f"**Sin clasificar**. Reasignalas al grupo correcto "
                "para que el asignador tenga la restricción de sede "
                "bien definida."
            )
    except ValueError:
        st.warning(
            "El grupo 'Sin clasificar' no existe. Reiniciá la app "
            "para que la migración inicial lo cree."
        )

    # Layout vertical: selector arriba (compacto), editor abajo
    # (full-width). Elimina la disparidad de alturas del layout de
    # dos columnas cuando hay muchos grupos y el editor es más corto.
    _render_selector_grupo(session, grupos, counts, sedes_db)
    _render_editor_grupo(session, sedes_db, carreras_db)

    st.divider()
    _render_reasignacion_materias(session, grupos, sedes_db)


# =============================================================================
# Selector de grupo (arriba, compacto)
# =============================================================================


def _render_selector_grupo(
    session: Session,
    grupos: list[GrupoMateriaDB],
    counts: dict[str, int],
    sedes_db: list[SedeDB],
) -> None:
    """Panel superior compacto: dropdown para elegir grupo activo + botón
    para crear uno nuevo. Reemplaza la vista de lista lateral para no
    generar disparidad de alturas contra el editor."""
    with st.container(border=True):
        # Sin clasificar primero, resto alfabético.
        def _sort_key(g: GrupoMateriaDB) -> tuple[int, str]:
            return (0 if g.es_sin_clasificar else 1, g.nombre.lower())

        grupos_ord = sorted(grupos, key=_sort_key)
        if not grupos_ord:
            st.info(
                "No hay grupos cargados. Creá uno con el botón de abajo."
            )
        else:
            labels = []
            for g in grupos_ord:
                prefix = "⚠️ " if g.es_sin_clasificar else "📦 "
                n = counts.get(g.id, 0)
                labels.append(f"{prefix}{g.nombre} · {n} materia(s)")

            seleccionado = st.session_state.get(
                "grupo_materia_seleccionado",
            )
            default_idx = 0
            if seleccionado:
                for i, g in enumerate(grupos_ord):
                    if g.id == seleccionado:
                        default_idx = i
                        break

            col_select, col_new = st.columns([5, 1])
            with col_select:
                elegido = st.selectbox(
                    "Grupo activo",
                    options=list(range(len(labels))),
                    format_func=lambda i: labels[i],
                    index=default_idx,
                    key="grupo_materia_selector",
                    label_visibility="collapsed",
                )
                st.session_state["grupo_materia_seleccionado"] = (
                    grupos_ord[elegido].id
                )
            with col_new:
                if st.button(
                    "➕ Nuevo",
                    key="btn_crear_grupo_toggle",
                    use_container_width=True,
                ):
                    st.session_state["mostrar_crear_grupo"] = (
                        not st.session_state.get(
                            "mostrar_crear_grupo", False,
                        )
                    )
                    st.rerun()

        if st.session_state.get("mostrar_crear_grupo"):
            st.divider()
            with st.form(key="crear_grupo_form", clear_on_submit=True):
                st.markdown("**Crear grupo nuevo**")
                nuevo_nombre = st.text_input(
                    "Nombre del grupo",
                    placeholder="Ej: Optativas de Sistemas",
                )
                sede_names = [s.nombre for s in sedes_db]
                sede_ids_map = {s.nombre: s.id for s in sedes_db}
                c1, c2 = st.columns(2)
                with c1:
                    nuevas_duras = st.multiselect(
                        "Sedes admisibles (modo DURO)",
                        options=sede_names,
                        help=(
                            "Cuando el asignador corre en modo DURO para "
                            "este grupo, sólo se admiten aulas de estas "
                            "sedes. Podés dejarlo vacío y llenarlo después."
                        ),
                    )
                with c2:
                    nuevas_blandas = st.multiselect(
                        "Sedes preferidas (modo BLANDO)",
                        options=sede_names,
                        help=(
                            "Cuando el asignador corre en modo BLANDO, la "
                            "primera sede es la preferida y las siguientes "
                            "son alternativas con costo. Podés reordenar "
                            "después."
                        ),
                    )
                col_ok, col_cancel = st.columns(2)
                with col_ok:
                    submitted = st.form_submit_button(
                        "Crear grupo", type="primary",
                        use_container_width=True,
                    )
                with col_cancel:
                    cancel = st.form_submit_button(
                        "Cancelar", use_container_width=True,
                    )
                if cancel:
                    st.session_state.pop("mostrar_crear_grupo", None)
                    st.rerun()
                if submitted:
                    if not nuevo_nombre.strip():
                        st.error("El nombre no puede quedar vacío.")
                    else:
                        try:
                            create_grupo(
                                session,
                                nuevo_nombre.strip(),
                                sedes_duras=[
                                    sede_ids_map[n] for n in nuevas_duras
                                ],
                                sedes_blandas_ordenadas=[
                                    sede_ids_map[n] for n in nuevas_blandas
                                ],
                            )
                            st.success(f"Grupo '{nuevo_nombre}' creado.")
                            st.session_state.pop(
                                "mostrar_crear_grupo", None,
                            )
                            st.rerun()
                        except ValueError as e:
                            st.error(str(e))


# =============================================================================
# Editor del grupo activo (derecha)
# =============================================================================


def _render_editor_grupo(
    session: Session,
    sedes_db: list[SedeDB],
    carreras_db: list[CarreraDB],
) -> None:
    grupo_id = st.session_state.get("grupo_materia_seleccionado")
    if not grupo_id:
        with st.container(border=True):
            st.info("Seleccioná un grupo de la lista para editarlo.")
        return

    try:
        grupo = get_grupo(session, grupo_id)
    except ValueError:
        with st.container(border=True):
            st.error("El grupo ya no existe.")
        st.session_state.pop("grupo_materia_seleccionado", None)
        return

    cfg = get_config_grupo(session, grupo.id)
    sede_nombre_by_id = {s.id: s.nombre for s in sedes_db}
    sede_id_by_nombre = {s.nombre: s.id for s in sedes_db}
    carrera_nombre_by_codigo = {c.codigo: c.nombre for c in carreras_db}
    carrera_codigo_by_nombre = {c.nombre: c.codigo for c in carreras_db}

    # -------------------------------------------------------------
    # Editor unificado en un solo contenedor con divisores internos.
    # Metadata / DURO / BLANDO conviven en un mismo bloque para no
    # dispersar visualmente. Acciones al pie sin container extra.
    # El chequeo de consistencia queda debajo, en su propio bloque.
    # -------------------------------------------------------------
    with st.container(border=True):
        st.markdown(f"### Editar grupo: **{grupo.nombre}**")
        # -- Metadata --
        nombre_edit = st.text_input(
            "Nombre",
            value=grupo.nombre,
            disabled=grupo.es_sin_clasificar,
            key=f"grupo_nombre_{grupo.id}",
            help=(
                "El grupo 'Sin clasificar' no puede renombrarse."
                if grupo.es_sin_clasificar else None
            ),
        )
        carrera_names_actuales = [
            carrera_nombre_by_codigo.get(c, c)
            for c in cfg.carreras_asociadas
        ]
        carreras_seleccionadas_names = st.multiselect(
            "Carreras asociadas",
            options=[c.nombre for c in carreras_db],
            default=carrera_names_actuales,
            key=f"grupo_carreras_{grupo.id}",
            help=(
                "Carreras a las que 'pertenece' este grupo, para el "
                "chequeo de consistencia. No dispara sync automático — "
                "sirve para que el botón 'Chequear consistencia' pueda "
                "listar las materias exclusivas de estas carreras que "
                "todavía no están acá."
            ),
        )
        carreras_seleccionadas = [
            carrera_codigo_by_nombre[n]
            for n in carreras_seleccionadas_names
        ]

        st.divider()
        # -- Sedes admisibles (modo DURO) --
        st.markdown("#### 🔒 Sedes admisibles (modo DURO)")
        st.caption(
            "Cuando el asignador corre este grupo en modo DURO, sólo "
            "se admiten aulas en estas sedes. El orden no tiene "
            "semántica. Lista vacía = fallback permisivo (todas "
            "admisibles)."
        )
        duras_actuales_names = [
            sede_nombre_by_id.get(s, s) for s in cfg.sedes_duras
        ]
        duras_edit_names = st.multiselect(
            "Sedes en el set DURO",
            options=[s.nombre for s in sedes_db],
            default=duras_actuales_names,
            key=f"grupo_duras_{grupo.id}",
            label_visibility="collapsed",
        )
        duras_edit_ids = [
            sede_id_by_nombre[n] for n in duras_edit_names
        ]

        st.divider()
        # -- Sedes preferidas (modo BLANDO) — lista ordenada --
        st.markdown("#### 🎯 Sedes preferidas (modo BLANDO)")
        st.caption(
            "Cuando el asignador corre este grupo en modo BLANDO, la "
            "**primera** sede es la preferida (cost 0), las **siguientes** "
            "son alternativas con costo `λ_sede_pref` por horario "
            "desplazado. Reordenalas con ↑ / ↓."
        )
        blandas_order_key = f"grupo_blandas_orden_{grupo.id}"
        blandas_source_key = f"{blandas_order_key}_source"
        if (
            blandas_order_key not in st.session_state
            or st.session_state.get(blandas_source_key) != grupo.id
        ):
            st.session_state[blandas_order_key] = list(
                cfg.sedes_blandas_ordenadas
            )
            st.session_state[blandas_source_key] = grupo.id
        blandas_local: list[str] = list(
            st.session_state[blandas_order_key]
        )
        blandas_local = [
            s for s in blandas_local if s in sede_nombre_by_id
        ]

        if not blandas_local:
            st.caption(
                "_(Lista vacía — el modo BLANDO no aplica R12 para este "
                "grupo.)_"
            )

        for i, sede_id in enumerate(blandas_local):
            row_cols = st.columns([5, 1, 1, 1])
            etiqueta_pref = " · 🎯 preferida" if i == 0 else ""
            row_cols[0].markdown(
                f"**{i + 1}. {sede_nombre_by_id.get(sede_id, sede_id)}**"
                f"{etiqueta_pref}"
            )
            if row_cols[1].button(
                "↑", key=f"blup_{grupo.id}_{sede_id}",
                disabled=(i == 0),
                help="Mover hacia arriba",
            ):
                blandas_local[i - 1], blandas_local[i] = (
                    blandas_local[i], blandas_local[i - 1]
                )
                st.session_state[blandas_order_key] = blandas_local
                st.rerun()
            if row_cols[2].button(
                "↓", key=f"bldn_{grupo.id}_{sede_id}",
                disabled=(i == len(blandas_local) - 1),
                help="Mover hacia abajo",
            ):
                blandas_local[i], blandas_local[i + 1] = (
                    blandas_local[i + 1], blandas_local[i]
                )
                st.session_state[blandas_order_key] = blandas_local
                st.rerun()
            if row_cols[3].button(
                "✕", key=f"blrm_{grupo.id}_{sede_id}",
                help="Quitar de la lista blanda",
            ):
                blandas_local.remove(sede_id)
                st.session_state[blandas_order_key] = blandas_local
                st.rerun()

        # Agregar sede blanda.
        sedes_no_incluidas = [
            s for s in sedes_db if s.id not in blandas_local
        ]
        if sedes_no_incluidas:
            add_col1, add_col2 = st.columns([3, 1])
            with add_col1:
                add_choice = st.selectbox(
                    "Agregar sede a la lista blanda",
                    options=[s.nombre for s in sedes_no_incluidas],
                    key=f"blad_{grupo.id}",
                    label_visibility="collapsed",
                )
            with add_col2:
                if st.button(
                    "Agregar",
                    key=f"blad_btn_{grupo.id}",
                    use_container_width=True,
                ):
                    blandas_local.append(
                        sede_id_by_nombre[add_choice]
                    )
                    st.session_state[blandas_order_key] = blandas_local
                    st.rerun()
        else:
            st.caption("Todas las sedes ya están en la lista.")

        st.divider()
        # -- Acciones al pie --
        col_save, col_reset, col_delete = st.columns([2, 1, 1])
        with col_save:
            if st.button(
                "💾 Guardar cambios",
                type="primary",
                key=f"save_{grupo.id}",
                use_container_width=True,
            ):
                try:
                    nombre_final = (
                        (nombre_edit or grupo.nombre).strip()
                        or grupo.nombre
                    )
                    update_grupo(
                        session,
                        grupo.id,
                        nombre=nombre_final,
                        sedes_duras=duras_edit_ids,
                        sedes_blandas_ordenadas=blandas_local,
                        carreras_asociadas=carreras_seleccionadas,
                    )
                    st.success("Cambios guardados.")
                    st.session_state.pop(blandas_order_key, None)
                    st.session_state.pop(blandas_source_key, None)
                    st.rerun()
                except ValueError as e:
                    st.error(str(e))
        with col_reset:
            if st.button(
                "↺ Descartar",
                key=f"reset_{grupo.id}",
                use_container_width=True,
            ):
                st.session_state.pop(blandas_order_key, None)
                st.session_state.pop(blandas_source_key, None)
                st.rerun()
        with col_delete:
            tiene_materias = _grupo_tiene_materias(session, grupo.id)
            disabled = grupo.es_sin_clasificar or tiene_materias
            delete_help = (
                "El grupo 'Sin clasificar' no se puede borrar."
                if grupo.es_sin_clasificar else (
                    "Tiene materias asignadas — reasignalas primero."
                    if tiene_materias else "Borrar este grupo."
                )
            )
            if st.button(
                "🗑️ Borrar",
                disabled=disabled,
                help=delete_help,
                key=f"del_{grupo.id}",
                use_container_width=True,
            ):
                try:
                    delete_grupo(session, grupo.id)
                    st.success(f"Grupo '{grupo.nombre}' borrado.")
                    st.session_state.pop(
                        "grupo_materia_seleccionado", None,
                    )
                    st.rerun()
                except ValueError as e:
                    st.error(str(e))

    # -------------------------------------------------------------
    # Chequeo de consistencia (fuera del editor unificado)
    # -------------------------------------------------------------
    _render_chequeo_consistencia(session, grupo, carreras_db)


def _render_chequeo_consistencia(
    session: Session,
    grupo: GrupoMateriaDB,
    carreras_db: list[CarreraDB],  # noqa: ARG001 (reservado para futuros contextos)
) -> None:
    """Panel que muestra faltantes según carreras asociadas + planes
    activos, y permite agregarlas de a una."""
    with st.container(border=True):
        st.markdown("#### 🔍 Chequeo de consistencia")
        st.caption(
            "Compara las materias del grupo con las materias exclusivas "
            "de las carreras asociadas en sus **planes activos**. "
            "Sirve para detectar qué materias 'de la carrera' todavía "
            "no fueron agregadas al grupo."
        )

        run_key = f"consist_run_{grupo.id}"
        result_key = f"consist_result_{grupo.id}"
        if st.button(
            "🔍 Chequear consistencia",
            key=run_key,
            disabled=False,
        ):
            faltantes, warnings = chequear_consistencia_grupo(
                session, grupo.id,
            )
            st.session_state[result_key] = {
                "faltantes": [
                    {
                        "codigo": f.codigo,
                        "nombre": f.nombre,
                        "carrera": f.carrera_codigo,
                        "anio": f.anio,
                        "cuatri": f.cuatri,
                        "grupo_actual_id": f.grupo_actual_id,
                        "grupo_actual_nombre": f.grupo_actual_nombre,
                    }
                    for f in faltantes
                ],
                "warnings": warnings,
            }
            st.rerun()

        result = st.session_state.get(result_key)
        if result is None:
            st.caption(
                "_Corré el chequeo para ver las materias exclusivas "
                "de las carreras asociadas que aún no están en este "
                "grupo._"
            )
            return

        for w in result["warnings"]:
            st.info(w)

        faltantes_list = result["faltantes"]
        if not faltantes_list:
            st.success(
                "Todas las materias exclusivas de las carreras "
                "asociadas ya están en este grupo. 🎉"
            )
            return

        st.warning(
            f"Se detectaron **{len(faltantes_list)} materia(s)** que "
            "corresponderían a este grupo pero están en otro lado."
        )
        for i, item in enumerate(faltantes_list):
            row = st.container()
            cols = row.columns([1, 3, 2, 2, 1])
            cols[0].markdown(f"`{item['codigo']}`")
            cols[1].write(item["nombre"])
            cols[2].caption(
                f"Carrera: **{item['carrera']}** · "
                f"Año {item['anio']} {item['cuatri']}"
                if item["anio"] else f"Carrera: **{item['carrera']}**"
            )
            cols[3].caption(
                f"Ahora en: **{item['grupo_actual_nombre']}**"
                if item["grupo_actual_nombre"] else
                "_Sin grupo actual_"
            )
            if cols[4].button(
                "➕",
                key=f"add_faltante_{grupo.id}_{item['codigo']}_{i}",
                help=(
                    f"Agregar {item['codigo']} a este grupo "
                    f"({grupo.nombre})"
                ),
            ):
                try:
                    asignar_materia_a_grupo(
                        session, item["codigo"], grupo.id,
                    )
                    st.toast(
                        f"{item['codigo']} agregada a {grupo.nombre}."
                    )
                    # Actualizar el cache del resultado sacando este.
                    st.session_state[result_key]["faltantes"] = [
                        f for f in faltantes_list
                        if f["codigo"] != item["codigo"]
                    ]
                    st.rerun()
                except ValueError as e:
                    st.error(str(e))


# =============================================================================
# Reasignación de materias con filtros robustos
# =============================================================================


def _normalizar(texto: str) -> str:
    """Normaliza (lower + saca acentos) para búsqueda tolerante."""
    nfkd = unicodedata.normalize("NFKD", texto)
    return "".join(
        c for c in nfkd if not unicodedata.combining(c)
    ).lower()


def _render_reasignacion_materias(
    session: Session,
    grupos: list[GrupoMateriaDB],
    sedes_db: list[SedeDB],  # noqa: ARG001
) -> None:
    with st.container(border=True):
        st.markdown("### Reasignar materias")
        st.caption(
            "Filtrá el conjunto de materias con los controles de abajo. "
            "Después podés reasignar **todas las que coinciden** desde "
            "el bloque **Acciones**, o **una por una** con el botón "
            "'Reasignar' de cada fila."
        )

        # ---------------------------------------------------
        # Filtros
        # ---------------------------------------------------
        with st.container(border=True):
            st.markdown("**🔎 Filtros**")

            # 1. Ubicación curricular (carrera + año + cuatri).
            with st.expander("📍 Ubicación curricular", expanded=True):
                st.caption(
                    "Filtra por dónde aparecen las materias en el "
                    "**plan activo** de cada carrera. Si no hay plan "
                    "activo para alguna, esa carrera se ignora."
                )
                carreras_db = list(session.exec(select(CarreraDB)).all())
                carrera_names = sorted(c.nombre for c in carreras_db)
                sel_carrera = st.multiselect(
                    "Carrera(s)",
                    options=carrera_names,
                    key="filtro_ubic_carrera",
                )
                col_y, col_c = st.columns(2)
                with col_y:
                    sel_anio = st.multiselect(
                        "Año(s)",
                        options=list(range(1, 7)),
                        key="filtro_ubic_anio",
                    )
                with col_c:
                    sel_cuatri = st.multiselect(
                        "Cuatri",
                        options=["1C", "2C", "Anual"],
                        key="filtro_ubic_cuatri",
                    )

            # 2. Atributos de la materia.
            with st.expander("🏷️ Atributos", expanded=False):
                # Lista de grupos SIN el "Sin clasificar" (que aparece
                # explícito arriba como opción "Sólo Sin clasificar") —
                # así evitamos que "Sin clasificar" figure dos veces.
                grupos_ordenados_para_filtro = sorted(
                    (g for g in grupos if not g.es_sin_clasificar),
                    key=lambda x: x.nombre,
                )
                sel_grupo_actual = st.selectbox(
                    "Grupo actual",
                    options=["Todos", "Sólo Sin clasificar"]
                    + [g.nombre for g in grupos_ordenados_para_filtro],
                    key="filtro_grupo_actual",
                    help=(
                        "Filtra materias por el grupo al que están "
                        "asignadas hoy. 'Sólo Sin clasificar' es el "
                        "atajo para atacar el backlog de materias sin "
                        "grupo real."
                    ),
                )
                col_a1, col_a2 = st.columns(2)
                with col_a1:
                    filtro_optativa = st.selectbox(
                        "Optativa",
                        options=["Todas", "Sólo optativas", "Sólo obligatorias"],
                        key="filtro_optativa",
                    )
                    filtro_virtual = st.selectbox(
                        "Virtual",
                        options=["Todas", "Sólo virtuales", "Sólo presenciales"],
                        key="filtro_virtual",
                    )
                with col_a2:
                    filtro_lab = st.selectbox(
                        "Laboratorio",
                        options=[
                            "Todas",
                            "Con horas de lab",
                            "Sin horas de lab",
                            "Con lab compatible",
                            "Sin lab compatible",
                        ],
                        key="filtro_lab",
                    )
                    filtro_periodo = st.selectbox(
                        "Período",
                        options=["Todos", "Cuatrimestral", "Anual"],
                        key="filtro_periodo",
                    )

            # 3. Búsqueda por código/nombre.
            busqueda = st.text_input(
                "🔍 Buscar por código o nombre",
                key="filtro_busqueda",
                placeholder="Ej: F14, algebra, matemática...",
                help=(
                    "La búsqueda ignora mayúsculas y acentos. "
                    "Escribí 'fisica' y encuentra 'Física'."
                ),
            )

        # ---------------------------------------------------
        # Query materias con los filtros aplicados
        # ---------------------------------------------------
        materias_filtradas = _aplicar_filtros(
            session=session,
            grupos=grupos,
            sel_carrera_names=sel_carrera,
            sel_anio=sel_anio,
            sel_cuatri=sel_cuatri,
            grupo_actual_filtro=sel_grupo_actual,
            filtro_optativa=filtro_optativa,
            filtro_virtual=filtro_virtual,
            filtro_lab=filtro_lab,
            filtro_periodo=filtro_periodo,
            busqueda=busqueda,
        )

        if not materias_filtradas:
            st.info(
                "Ninguna materia coincide con los filtros. Ajustá los "
                "criterios."
            )
            return

        st.caption(
            f"**{len(materias_filtradas)} materia(s)** que coinciden."
        )

        # ---------------------------------------------------
        # Acciones masivas sobre el resultado filtrado
        # ---------------------------------------------------
        _render_acciones_masivas(session, materias_filtradas, grupos)

        # ---------------------------------------------------
        # Tabla (con botón Reasignar por fila)
        # ---------------------------------------------------
        _render_tabla_reasignacion(session, materias_filtradas, grupos)


def _aplicar_filtros(
    *,
    session: Session,
    grupos: list[GrupoMateriaDB],
    sel_carrera_names: list[str],
    sel_anio: list[int],
    sel_cuatri: list[str],
    grupo_actual_filtro: str,
    filtro_optativa: str,
    filtro_virtual: str,
    filtro_lab: str,
    filtro_periodo: str,
    busqueda: str,
) -> list[MateriaDB]:
    """Aplica todos los filtros a la lista de materias y devuelve el
    resultado ordenado por código."""
    # Base: todas las materias.
    all_materias = list(session.exec(
        select(MateriaDB).order_by(MateriaDB.codigo)  # type: ignore[arg-type]
    ).all())

    # Filtro 1: ubicación curricular (usa plan activo de la carrera).
    if sel_carrera_names:
        carreras_db = list(session.exec(select(CarreraDB)).all())
        codigos_carrera = [
            c.codigo for c in carreras_db if c.nombre in sel_carrera_names
        ]
        # Recolectar plan_version_id activos de cada carrera.
        plan_ids_activos: list[str] = []
        for cod in codigos_carrera:
            pv = get_plan_activo(session, cod)
            if pv is not None:
                plan_ids_activos.append(pv.id)
        if not plan_ids_activos:
            return []  # ninguna carrera con plan activo → nada matchea
        pe_entries = list(session.exec(
            select(PlanEstudioDB).where(
                PlanEstudioDB.plan_version_id.in_(plan_ids_activos),  # type: ignore[attr-defined]
            )
        ).all())
        codigos_ok: set[str] = set()
        for pe in pe_entries:
            if sel_anio and pe.anio_plan not in sel_anio:
                continue
            if sel_cuatri and pe.cuatrimestre_plan not in sel_cuatri:
                continue
            codigos_ok.add(pe.materia_codigo)
        all_materias = [
            m for m in all_materias if m.codigo in codigos_ok
        ]
    elif sel_anio or sel_cuatri:
        # Sin carrera pero con año/cuatri: usa plan activo de todas
        # las carreras.
        pes_all = list(session.exec(select(PlanEstudioDB)).all())
        # Índice plan_id → active
        planes_activos_ids = {
            pv.id
            for pv in session.exec(
                select(PlanCarreraVersionDB)
            ).all()
            if pv.active
        }
        codigos_ok = set()
        for pe in pes_all:
            if pe.plan_version_id not in planes_activos_ids:
                continue
            if sel_anio and pe.anio_plan not in sel_anio:
                continue
            if sel_cuatri and pe.cuatrimestre_plan not in sel_cuatri:
                continue
            codigos_ok.add(pe.materia_codigo)
        all_materias = [
            m for m in all_materias if m.codigo in codigos_ok
        ]

    # Filtro 2: grupo actual.
    if grupo_actual_filtro == "Sólo Sin clasificar":
        try:
            sc = get_grupo_sin_clasificar(session)
            all_materias = [
                m for m in all_materias if m.grupo_id == sc.id
            ]
        except ValueError:
            all_materias = []
    elif grupo_actual_filtro != "Todos":
        target = next(
            (g for g in grupos if g.nombre == grupo_actual_filtro), None,
        )
        if target:
            all_materias = [
                m for m in all_materias if m.grupo_id == target.id
            ]
        else:
            all_materias = []

    # Filtro 3: optativa.
    if filtro_optativa == "Sólo optativas":
        all_materias = [m for m in all_materias if m.optativa]
    elif filtro_optativa == "Sólo obligatorias":
        all_materias = [m for m in all_materias if not m.optativa]

    # Filtro 4: virtual.
    if filtro_virtual == "Sólo virtuales":
        all_materias = [m for m in all_materias if m.virtual]
    elif filtro_virtual == "Sólo presenciales":
        all_materias = [m for m in all_materias if not m.virtual]

    # Filtro 5: laboratorio.
    if filtro_lab in ("Con lab compatible", "Sin lab compatible"):
        lab_pairs = list(session.exec(
            select(MateriaLaboratorioDB.materia_codigo)
        ).all())
        materias_con_lab = set(lab_pairs)
        if filtro_lab == "Con lab compatible":
            all_materias = [
                m for m in all_materias if m.codigo in materias_con_lab
            ]
        else:
            all_materias = [
                m for m in all_materias
                if m.codigo not in materias_con_lab
            ]
    elif filtro_lab == "Con horas de lab":
        all_materias = [
            m for m in all_materias
            if (m.horas_laboratorio or 0) > 0
        ]
    elif filtro_lab == "Sin horas de lab":
        all_materias = [
            m for m in all_materias
            if (m.horas_laboratorio or 0) == 0
        ]

    # Filtro 6: período.
    if filtro_periodo == "Cuatrimestral":
        all_materias = [
            m for m in all_materias if m.periodo == "cuatrimestral"
        ]
    elif filtro_periodo == "Anual":
        all_materias = [m for m in all_materias if m.periodo == "anual"]

    # Filtro 7: búsqueda por código/nombre (tolerante a acentos).
    if busqueda.strip():
        term = _normalizar(busqueda.strip())
        all_materias = [
            m for m in all_materias
            if term in _normalizar(m.codigo)
            or term in _normalizar(m.nombre)
        ]

    return all_materias


def _render_acciones_masivas(
    session: Session,
    materias_filtradas: list[MateriaDB],
    grupos: list[GrupoMateriaDB],
) -> None:
    """Sección 'Acciones' para reasignar en batch todas las materias
    filtradas a un grupo destino. Flujo de dos pasos: primer click
    muestra un aviso de confirmación; segundo click aplica."""
    with st.container(border=True):
        st.markdown("**⚡ Acciones**")
        st.caption(
            "Aplicá el mismo grupo destino a **todas las materias "
            "que coinciden con los filtros** en un solo click."
        )
        grupos_ord = sorted(
            grupos,
            key=lambda g: (
                0 if g.es_sin_clasificar else 1, g.nombre.lower(),
            ),
        )
        grupo_labels_by_id = {
            g.id: (
                f"⚠️ {g.nombre}"
                if g.es_sin_clasificar
                else f"📦 {g.nombre}"
            )
            for g in grupos_ord
        }

        col_dest, col_btn = st.columns([3, 2])
        with col_dest:
            destino_id = st.selectbox(
                "Grupo destino",
                options=[g.id for g in grupos_ord],
                format_func=lambda gid: (
                    grupo_labels_by_id.get(gid) or str(gid)
                ),
                key="acciones_masivas_destino",
                label_visibility="collapsed",
            )

        confirm_key = "acciones_masivas_confirmando"
        confirmando = st.session_state.get(confirm_key, False)

        with col_btn:
            label = (
                f"⚠️ Confirmar ({len(materias_filtradas)})"
                if confirmando else
                f"🚀 Reasignar {len(materias_filtradas)} materia(s)"
            )
            btn_type = "primary" if confirmando else "secondary"
            if st.button(
                label,
                type=btn_type,
                key="acciones_masivas_btn",
                use_container_width=True,
                disabled=not destino_id or not materias_filtradas,
            ):
                if not confirmando:
                    st.session_state[confirm_key] = True
                    st.rerun()
                else:
                    _aplicar_reasignacion_masiva(
                        session, materias_filtradas, destino_id,
                    )
                    st.session_state.pop(confirm_key, None)
                    st.rerun()

        if confirmando:
            destino = next(
                (g for g in grupos_ord if g.id == destino_id), None,
            )
            destino_nombre = destino.nombre if destino else "?"
            st.warning(
                f"Vas a mover **{len(materias_filtradas)} materia(s)** "
                f"al grupo **{destino_nombre}**. "
                "Presioná de nuevo el botón para confirmar."
            )
            if st.button(
                "↺ Cancelar",
                key="acciones_masivas_cancel",
            ):
                st.session_state.pop(confirm_key, None)
                st.rerun()


def _aplicar_reasignacion_masiva(
    session: Session,
    materias: list[MateriaDB],
    destino_grupo_id: str,
) -> None:
    """Aplica reasignación masiva y muestra toast con el resultado."""
    n_ok = 0
    n_skip = 0
    errores: list[str] = []
    for m in materias:
        if m.grupo_id == destino_grupo_id:
            n_skip += 1
            continue
        try:
            asignar_materia_a_grupo(session, m.codigo, destino_grupo_id)
            n_ok += 1
        except ValueError as e:
            errores.append(f"{m.codigo}: {e}")
    if errores:
        st.error(
            f"{len(errores)} error(es): " + "; ".join(errores[:5])
        )
    if n_ok:
        msg = f"{n_ok} materia(s) reasignada(s)."
        if n_skip:
            msg += f" ({n_skip} ya estaban en el destino.)"
        st.toast(msg)
    elif n_skip and not errores:
        st.toast(
            f"Todas las {n_skip} materia(s) ya estaban en el destino."
        )


@st.dialog("Reasignar materia a otro grupo")
def _dialog_reasignar_materia(
    materia_codigo: str,
    materia_nombre: str,
    grupo_actual_nombre: str | None,
    grupos: list[GrupoMateriaDB],
) -> None:
    """Dialog puntual para reasignar una materia individual."""
    st.markdown(f"**`{materia_codigo}`** — {materia_nombre}")
    st.caption(
        f"Grupo actual: **{grupo_actual_nombre or '—'}**. "
        "Elegí el grupo destino:"
    )
    grupos_ord = sorted(
        grupos,
        key=lambda g: (
            0 if g.es_sin_clasificar else 1, g.nombre.lower(),
        ),
    )
    labels = [
        (
            f"⚠️ {g.nombre}"
            if g.es_sin_clasificar else f"📦 {g.nombre}"
        )
        for g in grupos_ord
    ]
    destino_idx = st.selectbox(
        "Grupo destino",
        options=list(range(len(labels))),
        format_func=lambda i: labels[i],
        key=f"dialog_reasign_dest_{materia_codigo}",
    )
    destino_grupo = grupos_ord[destino_idx] if grupos_ord else None
    c_ok, c_cancel = st.columns(2)
    with c_ok:
        if st.button(
            "💾 Confirmar",
            type="primary",
            key=f"dialog_reasign_ok_{materia_codigo}",
            use_container_width=True,
            disabled=not destino_grupo,
        ):
            from src.database.connection import get_session
            with next(get_session()) as _sess:
                try:
                    asignar_materia_a_grupo(
                        _sess, materia_codigo, destino_grupo.id,  # type: ignore[union-attr]
                    )
                    st.toast(
                        f"{materia_codigo} → "
                        f"{destino_grupo.nombre}."  # type: ignore[union-attr]
                    )
                except ValueError as e:
                    st.error(str(e))
                    return
            st.rerun()
    with c_cancel:
        if st.button(
            "↺ Cancelar",
            key=f"dialog_reasign_cancel_{materia_codigo}",
            use_container_width=True,
        ):
            st.rerun()


def _render_tabla_reasignacion(
    session: Session,  # noqa: ARG001 (los botones abren un dialog con su propia session)
    materias: list[MateriaDB],
    grupos: list[GrupoMateriaDB],
) -> None:
    """Tabla de materias filtradas con un botón 'Reasignar' por fila
    que abre un dialog para elegir el grupo destino puntual."""
    grupo_id_to_grupo = {g.id: g for g in grupos}

    CAP_MOSTRAR = 200
    if len(materias) > CAP_MOSTRAR:
        st.caption(
            f"Mostrando las primeras {CAP_MOSTRAR} de {len(materias)}. "
            "Aplicá más filtros para acotar."
        )
    a_mostrar = materias[:CAP_MOSTRAR]

    with st.container(border=True):
        h1, h2, h3, h4 = st.columns([1, 3, 2, 1])
        h1.markdown("**Código**")
        h2.markdown("**Nombre**")
        h3.markdown("**Grupo actual**")
        h4.markdown("**Acciones**")

        for m in a_mostrar:
            c1, c2, c3, c4 = st.columns([1, 3, 2, 1])
            c1.markdown(f"`{m.codigo}`")
            c2.write(m.nombre)
            gactual = (
                grupo_id_to_grupo.get(m.grupo_id) if m.grupo_id else None
            )
            c3.write(gactual.nombre if gactual else "—")
            if c4.button(
                "🔀 Reasignar",
                key=f"reasign_btn_{m.codigo}",
                use_container_width=True,
            ):
                _dialog_reasignar_materia(
                    materia_codigo=m.codigo,
                    materia_nombre=m.nombre,
                    grupo_actual_nombre=(
                        gactual.nombre if gactual else None
                    ),
                    grupos=grupos,
                )


# =============================================================================
# Helpers privados
# =============================================================================


def _grupo_tiene_materias(session: Session, grupo_id: str) -> bool:
    row = session.exec(
        select(MateriaDB).where(MateriaDB.grupo_id == grupo_id).limit(1)
    ).first()
    return row is not None


# Referencia explícita para que el linter no marque el import como
# no usado (usamos GrupoMateriaSedeDB / GrupoMateriaCarreraDB sólo
# indirectamente vía el servicio).
_ = (GrupoMateriaSedeDB, GrupoMateriaCarreraDB)


# NOTE: list_materias_por_grupo y list_materias_sin_clasificar se
# importan para dejarlos disponibles a call sites externos y evitar
# regressions si alguien los usaba desde otro módulo. También se
# consultan indirectamente vía chequear_consistencia_grupo del servicio.
_ = (list_materias_por_grupo, list_materias_sin_clasificar)
