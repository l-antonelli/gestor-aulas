"""Gestión de Aulas y Sedes.

La página unifica el CRUD de aulas con la gestión de sedes (entidad
referenciada por las aulas) en tabs separadas:

- 📋 Listado: tabla de aulas con filtro por sede.
- ➕ Crear: alta de un aula nueva. El `id` se autogenera (UUID); el
  `codigo_aula` (display) se autoderiva como ``{sede.nombre}-{nombre}``
  con espacios reemplazados por guiones, salvo que el usuario lo edite.
- 👁️ Ver detalle: edición inline + materias compatibles si es laboratorio.
- 📍 Sedes: listar / crear / renombrar / borrar / fusionar sedes.
"""

import streamlit as st
from sqlmodel import select, col

from src.database.connection import get_session, init_db
from src.database.models import (
    AulaDB,
    MateriaDB,
    MateriaLaboratorioDB,
    SedeDB,
)
from src.services.crud_services import sede_service

# Import relationship definitions to register relationships
import src.services.relationship_definitions  # noqa: F401

init_db()
st.set_page_config(page_title="Aulas y Sedes", page_icon="🏛️", layout="wide")


# =============================================================================
# Helpers
# =============================================================================


def _slugify_codigo(sede_nombre: str, aula_nombre: str) -> str:
    """Genera un código display autoderivado: ``{Sede}-{Aula}`` con
    espacios reemplazados por guiones."""
    base = f"{sede_nombre}-{aula_nombre}".strip()
    return "-".join(base.split())


def _sede_options(session) -> tuple[list[str], dict[str, str]]:
    """Devuelve (lista de ids ordenadas por nombre, dict id->nombre)."""
    sedes = list(session.exec(
        select(SedeDB).order_by(col(SedeDB.nombre))
    ).all())
    nombres = {s.id: s.nombre for s in sedes}
    return [s.id for s in sedes], nombres


# =============================================================================
# Tab: Listado
# =============================================================================


def _render_tab_listado(session) -> None:
    aulas = list(session.exec(
        select(AulaDB).order_by(col(AulaDB.sede_id), col(AulaDB.nombre))
    ).all())
    if not aulas:
        st.info("No hay aulas cargadas todavía.")
        return

    _, sede_nombres = _sede_options(session)

    # Filtro por sede (incluye opción "Todas").
    filtro_options = ["Todas"] + sorted(set(sede_nombres.values()))
    sel_filtro = st.selectbox("Filtrar por sede", filtro_options, index=0)
    if sel_filtro != "Todas":
        aulas = [
            a for a in aulas
            if sede_nombres.get(a.sede_id) == sel_filtro
        ]

    rows = [
        {
            "Código": a.codigo_aula,
            "Sede": sede_nombres.get(a.sede_id, "—"),
            "Nombre": a.nombre,
            "Capacidad": a.capacidad,
            "Tipo": a.tipo,
        }
        for a in aulas
    ]
    st.dataframe(rows, use_container_width=True, hide_index=True)
    st.caption(f"Total: {len(aulas)} aula(s).")


# =============================================================================
# Tab: Crear
# =============================================================================


def _render_tab_crear(session) -> None:
    sede_ids, sede_nombres = _sede_options(session)
    if not sede_ids:
        st.warning(
            "No hay sedes cargadas. Creá al menos una sede en la pestaña "
            "'📍 Sedes' antes de crear un aula."
        )
        return

    nombre = st.text_input(
        "Nombre del aula", key="aula_create_nombre",
        help="Por ejemplo: 'AULA 01', 'LAB 1'.",
    )
    sede_id = st.selectbox(
        "Sede",
        options=sede_ids,
        format_func=lambda x: sede_nombres[x],
        key="aula_create_sede",
    )
    sede_nombre = sede_nombres.get(sede_id, "?") if sede_id else ""

    auto_codigo = (
        _slugify_codigo(sede_nombre, nombre) if nombre and sede_nombre else ""
    )
    codigo_aula = st.text_input(
        "Código (display)",
        value="",
        key="aula_create_codigo",
        placeholder=auto_codigo or "Se autogenera al guardar",
        help=(
            "Si lo dejás vacío, se autocompleta como "
            f"`{auto_codigo}` (sede + nombre, con guiones)."
        ),
    )
    capacidad = st.number_input(
        "Capacidad", min_value=1, value=30, step=1,
        key="aula_create_capacidad",
    )
    tipos = ["teorica", "practica", "laboratorio", "anfiteatro"]
    tipo = st.selectbox("Tipo", options=tipos, index=0, key="aula_create_tipo")
    descripcion = st.text_area(
        "Descripción", value="", key="aula_create_desc", height=80,
    )

    can_create = bool(nombre.strip() and sede_id)
    if not can_create:
        st.caption("Completá nombre y sede para habilitar la creación.")
        return

    if st.button("Crear aula", type="primary", key="aula_create_btn"):
        codigo_final = (codigo_aula or "").strip() or auto_codigo
        # Verificar unicidad de codigo_aula.
        existing = session.exec(
            select(AulaDB).where(AulaDB.codigo_aula == codigo_final)
        ).first()
        if existing is not None:
            st.error(
                f"Ya existe un aula con código '{codigo_final}'. "
                "Editalo manualmente para usar otro."
            )
            return

        aula = AulaDB(
            sede_id=sede_id,
            codigo_aula=codigo_final,
            nombre=nombre.strip(),
            capacidad=int(capacidad),
            tipo=tipo,
            descripcion=descripcion or "",
        )
        session.add(aula)
        session.commit()
        st.success(f"Aula '{codigo_final}' creada.")
        st.rerun()


# =============================================================================
# Tab: Ver detalle (selector + edición + lab compats)
# =============================================================================


def _render_aula_edit_form(session, aula: AulaDB, key_prefix: str) -> None:
    sede_ids, sede_nombres = _sede_options(session)
    if not sede_ids:
        st.error("No hay sedes para asignar.")
        return

    st.markdown("### ✏️ Editar aula")
    st.caption(f"ID interno: `{aula.id}`")

    c1, c2 = st.columns(2)
    with c1:
        new_nombre = st.text_input(
            "Nombre", value=aula.nombre, key=f"{key_prefix}_nombre",
        )
        sede_idx = sede_ids.index(aula.sede_id) if aula.sede_id in sede_ids else 0
        new_sede_id = st.selectbox(
            "Sede",
            options=sede_ids,
            format_func=lambda x: sede_nombres[x],
            index=sede_idx,
            key=f"{key_prefix}_sede",
        )
        new_codigo = st.text_input(
            "Código (display)",
            value=aula.codigo_aula,
            key=f"{key_prefix}_codigo",
            help="Único globalmente. Editable a mano.",
        )
        new_capacidad = st.number_input(
            "Capacidad",
            min_value=1, value=int(aula.capacidad),
            step=1, key=f"{key_prefix}_capacidad",
        )
    with c2:
        tipos = ["teorica", "practica", "laboratorio", "anfiteatro"]
        tipo_idx = tipos.index(aula.tipo) if aula.tipo in tipos else 0
        new_tipo = st.selectbox(
            "Tipo", options=tipos, index=tipo_idx, key=f"{key_prefix}_tipo",
            help=(
                "Si cambias a/desde 'laboratorio', recordá que la "
                "relación M:N con materias se mantiene; revisarla "
                "abajo si es necesario."
            ),
        )
        new_descripcion = st.text_area(
            "Descripción",
            value=aula.descripcion or "",
            key=f"{key_prefix}_desc",
            height=100,
        )

    changed = (
        new_nombre.strip() != aula.nombre
        or new_sede_id != aula.sede_id
        or new_codigo.strip() != aula.codigo_aula
        or int(new_capacidad) != aula.capacidad
        or new_tipo != aula.tipo
        or (new_descripcion or "") != (aula.descripcion or "")
    )
    if not changed:
        st.caption("Sin cambios.")
        return

    if st.button("Guardar cambios", type="primary", key=f"{key_prefix}_save"):
        # Verificar unicidad de codigo_aula si cambió.
        codigo_final = new_codigo.strip()
        if codigo_final != aula.codigo_aula:
            collision = session.exec(
                select(AulaDB).where(AulaDB.codigo_aula == codigo_final)
            ).first()
            if collision is not None and collision.id != aula.id:
                st.error(
                    f"Ya existe otra aula con código '{codigo_final}'."
                )
                return

        aula.nombre = new_nombre.strip()
        aula.sede_id = new_sede_id
        aula.codigo_aula = codigo_final
        aula.capacidad = int(new_capacidad)
        aula.tipo = new_tipo
        aula.descripcion = new_descripcion or ""
        session.add(aula)
        session.commit()
        st.toast(f"Aula '{aula.codigo_aula}' actualizada.")
        st.rerun()


def _render_materias_compatibles_editor(session, aula_id: str, key_prefix: str):
    """Editor de materias compatibles con un laboratorio (relación M:N)."""
    materias = list(session.exec(
        select(MateriaDB)
        .where(MateriaDB.active == True)  # noqa: E712
        .order_by(col(MateriaDB.codigo))
    ).all())
    if not materias:
        st.info("No hay materias activas en la base de datos.")
        return

    current = list(session.exec(
        select(MateriaLaboratorioDB.materia_codigo)
        .where(MateriaLaboratorioDB.aula_id == aula_id)
    ).all())
    current_set = set(current)

    st.markdown("### Materias que usan este laboratorio")
    st.caption(
        "Seleccioná las materias que pueden dictar clases de tipo "
        "'laboratorio' en este lab."
    )

    mat_options = [f"{m.codigo} — {m.nombre}" for m in materias]
    mat_codes = [m.codigo for m in materias]
    mat_code_to_label = dict(zip(mat_codes, mat_options))

    default_selected = [
        mat_code_to_label[mc] for mc in current
        if mc in mat_code_to_label
    ]
    selected = st.multiselect(
        "Materias compatibles",
        options=mat_options,
        default=default_selected,
        key=f"{key_prefix}_mats",
    )
    selected_codes = {opt.split(" — ")[0] for opt in selected}
    to_add = selected_codes - current_set
    to_remove = current_set - selected_codes

    if to_add or to_remove:
        st.info(
            f"{len(to_add)} para agregar, {len(to_remove)} para quitar. "
            "Presioná 'Guardar' para aplicar."
        )
        if st.button("Guardar", type="primary", key=f"{key_prefix}_save"):
            for mat_codigo in to_add:
                session.add(MateriaLaboratorioDB(
                    materia_codigo=mat_codigo,
                    aula_id=aula_id,
                ))
            for mat_codigo in to_remove:
                existing = session.get(
                    MateriaLaboratorioDB, (mat_codigo, aula_id),
                )
                if existing:
                    session.delete(existing)
            session.commit()
            st.toast(
                f"Materias actualizadas: {len(to_add)} agregadas, "
                f"{len(to_remove)} quitadas."
            )
            st.rerun()
    else:
        st.caption(f"{len(current_set)} materia(s) asociada(s). Sin cambios.")


def _render_tab_detalle(session) -> None:
    aulas = list(session.exec(
        select(AulaDB).order_by(col(AulaDB.codigo_aula))
    ).all())
    if not aulas:
        st.info("No hay aulas cargadas.")
        return

    _, sede_nombres = _sede_options(session)
    options = {
        a.id: f"{a.codigo_aula} — {a.nombre} ({sede_nombres.get(a.sede_id, '?')})"
        for a in aulas
    }
    sel_id = st.selectbox(
        "Seleccionar aula",
        options=list(options.keys()),
        format_func=lambda x: options[x],
        key="aula_detail_select",
    )
    if not sel_id:
        return
    aula = session.get(AulaDB, sel_id)
    if aula is None:
        st.error("Aula no encontrada.")
        return

    _render_aula_edit_form(session, aula, key_prefix=f"aula_edit_{aula.id}")
    st.divider()

    # Borrar aula (solo si no tiene clases ni labs asociados).
    with st.expander("🗑️ Borrar aula"):
        if st.button(
            "Borrar definitivamente",
            type="secondary", key=f"aula_del_{aula.id}",
        ):
            from src.database.models import ClaseDB
            tiene_clases = session.exec(
                select(ClaseDB).where(ClaseDB.aula_id == aula.id)
            ).first()
            if tiene_clases is not None:
                st.error(
                    "No se puede borrar: el aula tiene clases asignadas. "
                    "Reasignalas primero."
                )
            else:
                session.delete(aula)
                session.commit()
                st.success("Aula borrada.")
                st.rerun()

    if aula.tipo == "laboratorio":
        st.divider()
        _render_materias_compatibles_editor(
            session, aula.id, key_prefix=f"aula_detail_{aula.id}",
        )


# =============================================================================
# Tab: Sedes
# =============================================================================


def _render_tab_sedes(session) -> None:
    st.markdown("### 📍 Sedes")
    st.caption(
        "Las sedes son los espacios físicos donde se ubican las aulas. "
        "Cada aula referencia una sede; podés crear nuevas, renombrarlas, "
        "borrarlas (sólo si no tienen aulas) o fusionarlas."
    )

    sedes = list(session.exec(
        select(SedeDB).order_by(col(SedeDB.nombre))
    ).all())

    # Conteo de aulas por sede para la tabla.
    aulas_all = list(session.exec(select(AulaDB)).all())
    n_aulas_por_sede: dict[str, int] = {}
    for a in aulas_all:
        n_aulas_por_sede[a.sede_id] = n_aulas_por_sede.get(a.sede_id, 0) + 1

    rows = [
        {
            "Sede": s.nombre,
            "Aulas": n_aulas_por_sede.get(s.id, 0),
        }
        for s in sedes
    ]
    if rows:
        st.dataframe(rows, use_container_width=True, hide_index=True)
    else:
        st.info("No hay sedes todavía.")

    st.divider()

    # Crear sede
    with st.expander("➕ Crear sede"):
        nuevo_nombre = st.text_input("Nombre", key="sede_create_nombre")
        if st.button(
            "Crear", type="primary", key="sede_create_btn",
            disabled=not nuevo_nombre.strip(),
        ):
            existing = session.exec(
                select(SedeDB).where(SedeDB.nombre == nuevo_nombre.strip())
            ).first()
            if existing is not None:
                st.error(f"Ya existe la sede '{nuevo_nombre.strip()}'.")
            else:
                session.add(SedeDB(nombre=nuevo_nombre.strip()))
                session.commit()
                st.success(f"Sede '{nuevo_nombre.strip()}' creada.")
                st.rerun()

    if not sedes:
        return

    # Renombrar / borrar sede
    with st.expander("✏️ Renombrar / borrar sede"):
        sel_sede_id = st.selectbox(
            "Sede",
            options=[s.id for s in sedes],
            format_func=lambda x: next(s.nombre for s in sedes if s.id == x),
            key="sede_edit_select",
        )
        sel_sede = next((s for s in sedes if s.id == sel_sede_id), None)
        if sel_sede is None:
            return

        nuevo = st.text_input(
            "Nuevo nombre", value=sel_sede.nombre, key=f"sede_rename_{sel_sede.id}",
        ) or ""
        c1, c2 = st.columns(2)
        with c1:
            if st.button(
                "Renombrar", key=f"sede_rename_btn_{sel_sede.id}",
                disabled=(nuevo.strip() == sel_sede.nombre),
            ):
                colliding = session.exec(
                    select(SedeDB).where(SedeDB.nombre == nuevo.strip())
                ).first()
                if colliding is not None and colliding.id != sel_sede.id:
                    st.error(f"Ya existe la sede '{nuevo.strip()}'.")
                else:
                    sel_sede.nombre = nuevo.strip()
                    session.add(sel_sede)
                    session.commit()
                    st.success("Sede renombrada.")
                    st.rerun()
        with c2:
            n_aulas = n_aulas_por_sede.get(sel_sede.id, 0)
            disabled = n_aulas > 0
            help_txt = (
                f"No se puede borrar: tiene {n_aulas} aula(s) asociada(s)."
                if disabled else "Se borrará la sede definitivamente."
            )
            if st.button(
                "Borrar", key=f"sede_del_btn_{sel_sede.id}",
                type="secondary", disabled=disabled, help=help_txt,
            ):
                try:
                    sede_service.delete(session, sel_sede.id)
                    st.success("Sede borrada.")
                    st.rerun()
                except ValueError as e:
                    st.error(str(e))

    # Fusionar sede
    with st.expander("🔗 Fusionar sedes"):
        st.caption(
            "Reasigna todas las aulas de la sede 'origen' a la 'destino' "
            "y borra la origen."
        )
        if len(sedes) < 2:
            st.info("Necesitás al menos dos sedes para fusionar.")
        else:
            c1, c2 = st.columns(2)
            with c1:
                origen_id = st.selectbox(
                    "Sede origen (se borra)",
                    options=[s.id for s in sedes],
                    format_func=lambda x: (
                        f"{next(s.nombre for s in sedes if s.id == x)} "
                        f"({n_aulas_por_sede.get(x, 0)} aulas)"
                    ),
                    key="sede_merge_origen",
                )
            with c2:
                destino_options = [s.id for s in sedes if s.id != origen_id]
                destino_id = st.selectbox(
                    "Sede destino (recibe las aulas)",
                    options=destino_options,
                    format_func=lambda x: (
                        f"{next(s.nombre for s in sedes if s.id == x)} "
                        f"({n_aulas_por_sede.get(x, 0)} aulas)"
                    ),
                    key="sede_merge_destino",
                )

            if st.button(
                "Fusionar", type="primary", key="sede_merge_btn",
                disabled=(not origen_id or not destino_id),
            ):
                try:
                    n = sede_service.merge_into(
                        session,
                        sede_origen_id=origen_id,
                        sede_destino_id=destino_id,
                    )
                    st.success(
                        f"{n} aula(s) reasignada(s). Sede origen borrada."
                    )
                    st.rerun()
                except ValueError as e:
                    st.error(str(e))


# =============================================================================
# Render
# =============================================================================

st.title("🏛️ Aulas y Sedes")

tab_list, tab_create, tab_view, tab_sedes = st.tabs([
    "📋 Listado", "➕ Crear", "👁️ Ver detalle", "📍 Sedes",
])

with next(get_session()) as session:
    with tab_list:
        _render_tab_listado(session)
    with tab_create:
        _render_tab_crear(session)
    with tab_view:
        _render_tab_detalle(session)
    with tab_sedes:
        _render_tab_sedes(session)
