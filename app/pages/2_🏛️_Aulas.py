"""Gestión de Aulas - Refactored to use CRUD Service and EntityPageTemplate.

Requirements: 7.1, 7.2, 7.4, 7.5
"""

import streamlit as st
from sqlmodel import select, col

from src.database.connection import get_session, init_db
from src.database.models import AulaDB, MateriaDB, MateriaLaboratorioDB
from src.services.crud_services import aula_service
from src.domain.problem.aula import Aula
from src.ui.page_template import EntityPageTemplate, EntityPageConfig

# Import relationship definitions to register relationships
import src.services.relationship_definitions  # noqa: F401

# Initialize database
init_db()

st.set_page_config(page_title="Aulas", page_icon="🏛️", layout="wide")


def _render_materias_compatibles_editor(session, aula_id: str, key_prefix: str):
    """Editor de materias compatibles con un laboratorio (relacion M:N).

    Espejo de _render_laboratorios_editor en la pagina de Materias:
    el efecto de agregar una materia desde aca es identico a asignar
    el lab desde la pagina de Materias.
    """
    materias = list(session.exec(
        select(MateriaDB)
        .where(MateriaDB.active == True)
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
        "'laboratorio' en este lab. Es la misma relacion M:N que se "
        "edita desde la pagina de Materias."
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


def _render_aula_edit_form(session, aula: AulaDB, key_prefix: str) -> bool:
    """Editor inline de campos basicos de un aula. Devuelve True si guardo."""
    st.markdown("### \u270f\ufe0f Editar aula")
    _c1, _c2 = st.columns(2)
    with _c1:
        new_nombre = st.text_input(
            "Nombre", value=aula.nombre, key=f"{key_prefix}_nombre",
        )
        new_sede = st.text_input(
            "Sede", value=aula.sede, key=f"{key_prefix}_sede",
        )
        new_capacidad = st.number_input(
            "Capacidad",
            min_value=1, value=int(aula.capacidad),
            step=1, key=f"{key_prefix}_capacidad",
        )
    with _c2:
        _tipos = ["teorica", "practica", "laboratorio", "anfiteatro"]
        _idx = _tipos.index(aula.tipo) if aula.tipo in _tipos else 0
        new_tipo = st.selectbox(
            "Tipo", options=_tipos, index=_idx, key=f"{key_prefix}_tipo",
            help=(
                "Si cambias a/desde 'laboratorio', record\u00e1 que la "
                "relaci\u00f3n M:N con materias se mantiene; revisarla "
                "abajo si es necesario."
            ),
        )
        new_descripcion = st.text_area(
            "Descripci\u00f3n",
            value=aula.descripcion or "",
            key=f"{key_prefix}_descripcion",
            height=100,
        )

    _changed = (
        new_nombre.strip() != aula.nombre
        or new_sede.strip() != aula.sede
        or int(new_capacidad) != aula.capacidad
        or new_tipo != aula.tipo
        or (new_descripcion or "") != (aula.descripcion or "")
    )
    if not _changed:
        st.caption("Sin cambios.")
        return False

    if st.button("Guardar cambios", type="primary", key=f"{key_prefix}_save"):
        aula.nombre = new_nombre.strip()
        aula.sede = new_sede.strip()
        aula.capacidad = int(new_capacidad)
        aula.tipo = new_tipo
        aula.descripcion = new_descripcion or ""
        session.add(aula)
        session.commit()
        st.toast(f"Aula '{aula.id}' actualizada.")
        st.rerun()
        return True
    return False


def _render_labs_overview(session):
    """Resumen read-only por laboratorio con sus materias asociadas."""
    labs = list(session.exec(
        select(AulaDB)
        .where(AulaDB.tipo == "laboratorio")
        .order_by(col(AulaDB.sede), col(AulaDB.nombre))
    ).all())

    if not labs:
        return

    st.divider()
    st.subheader("🔬 Laboratorios y materias compatibles")
    st.caption(
        "Vista inversa: para cada laboratorio, las materias que pueden "
        "dictar clases de tipo 'laboratorio' en él. Para editar, ir a "
        "la pestaña 'Ver Detalle' y seleccionar el laboratorio."
    )

    materias_all = list(session.exec(select(MateriaDB)).all())
    nombre_por_codigo = {m.codigo: m.nombre for m in materias_all}

    for lab in labs:
        rows = list(session.exec(
            select(MateriaLaboratorioDB.materia_codigo)
            .where(MateriaLaboratorioDB.aula_id == lab.id)
        ).all())
        n = len(rows)
        with st.expander(
            f"**{lab.id}** — {lab.nombre} ({lab.sede}) — {n} materia(s)"
        ):
            if not rows:
                st.caption("Sin materias asociadas.")
            else:
                for mc in sorted(rows):
                    st.write(f"- **{mc}** — {nombre_por_codigo.get(mc, '?')}")


# Configure the entity page
config = EntityPageConfig(
    model=Aula,
    service=aula_service,
    page_title="Gestión de Aulas",
    page_icon="🏛️",
    display_fields=["id", "sede", "nombre", "capacidad", "tipo", "descripcion"],
    custom_labels={
        "id": "ID",
        "sede": "Sede",
        "nombre": "Nombre",
        "capacidad": "Capacidad",
        "tipo": "Tipo",
        "descripcion": "Descripción",
    },
    id_field="id",
    display_field="nombre",
    enable_cascading=False,  # Aulas don't have cascading children
    enable_hierarchy_view=False,  # Aulas don't have hierarchical children
    exclude_from_create=[],
)

# Render the page using EntityPageTemplate, but with custom additions for labs
st.title(f"{config.page_icon} {config.page_title}")

tab_list, tab_create, tab_view = st.tabs([
    "📋 Listado", "➕ Crear", "👁️ Ver Detalle",
])

with next(get_session()) as session:
    with tab_list:
        EntityPageTemplate.render_list_tab(config, session)
        _render_labs_overview(session)

    with tab_create:
        EntityPageTemplate.render_create_tab(config, session)

    with tab_view:
        EntityPageTemplate.render_detail_tab(config, session)

        # Si hay un aula seleccionada, permitir editar sus campos basicos
        # y, si es laboratorio, gestionar materias compatibles.
        selected_id = st.session_state.get(f"view_{config.model.__name__}")
        if selected_id:
            aula = session.get(AulaDB, selected_id)
            if aula:
                st.divider()
                _render_aula_edit_form(
                    session=session,
                    aula=aula,
                    key_prefix=f"aula_edit_{aula.id}",
                )
                if aula.tipo == "laboratorio":
                    st.divider()
                    _render_materias_compatibles_editor(
                        session=session,
                        aula_id=aula.id,
                        key_prefix=f"aula_detail_{aula.id}",
                    )
