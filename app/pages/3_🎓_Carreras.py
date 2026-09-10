"""Gestión de Carreras - Enhanced with materia completeness tracking.

Requirements: 7.1, 7.2, 7.4, 7.5, 8.1
"""

import streamlit as st
from sqlmodel import Session, select

from src.database.connection import get_session, init_db
from src.database.models import PlanCarreraVersionDB
from src.services.crud_services import carrera_service, materia_service
from src.domain.problem.carrera import Carrera
from src.ui.carrera_status_widget import CarreraStatusWidget
from src.ui.form_input_renderer import FormInputRenderer

# Import relationship definitions to register relationships
import src.services.relationship_definitions  # noqa: F401

# Initialize database
init_db()

st.set_page_config(page_title="Carreras", page_icon="🎓", layout="wide")


def _render_plan_activo_y_grupos(
    session: Session, carrera,
) -> None:
    """Renderiza dos bloques con borde para cada carrera:

    1. **Plan de estudio activo**: lista todas las versiones del plan
       de la carrera, permite marcar cuál está activa (radio + botón
       Guardar). Solo puede haber uno activo por carrera.
    2. **Grupos de materias asociados**: lista los grupos que tienen
       a esta carrera en su asociación M:N, con link a Materias →
       Grupos para editar.
    """
    from src.services.grupo_materia_service import (
        get_plan_activo,
        list_grupos_de_carrera,
        set_plan_activo,
    )

    # --- Plan activo ------------------------------------------
    with st.container(border=True):
        st.markdown("**📄 Plan de estudio activo**")
        st.caption(
            "El **plan activo** es la versión vigente de la carrera. "
            "Los filtros por ubicación curricular y los chequeos de "
            "consistencia por grupo lo usan como referencia. Los "
            "planes inactivos se conservan para poder seguir "
            "referenciando ciclos de años anteriores."
        )
        versiones = list(session.exec(
            select(PlanCarreraVersionDB).where(
                PlanCarreraVersionDB.carrera_codigo == carrera.codigo,
            ).order_by(
                PlanCarreraVersionDB.fecha_creacion.desc(),  # type: ignore[attr-defined]
            )
        ).all())
        if not versiones:
            st.info(
                "Esta carrera todavía no tiene versiones de plan "
                "creadas. Se crean automáticamente cuando se carga "
                "un plan de estudio para esta carrera."
            )
        else:
            activa = get_plan_activo(session, carrera.codigo)
            opciones = ["(Ninguna)"] + [
                f"{v.nombre} — {v.fecha_creacion}"
                for v in versiones
            ]
            id_por_opcion = ["__NONE__"] + [v.id for v in versiones]
            default_idx = 0
            if activa is not None:
                for i, v in enumerate(versiones):
                    if v.id == activa.id:
                        default_idx = i + 1
                        break

            # Modo edición: selectbox deshabilitado hasta que se
            # apriete 'Editar'. Al guardar o cancelar vuelve a
            # deshabilitado.
            edit_key = f"plan_activo_editando_{carrera.codigo}"
            editando = st.session_state.get(edit_key, False)

            col_select, col_actions = st.columns([4, 2])
            with col_select:
                sel_idx = st.selectbox(
                    "Versión activa",
                    options=list(range(len(opciones))),
                    format_func=lambda i: opciones[i],
                    index=default_idx,
                    key=f"plan_activo_sel_{carrera.codigo}",
                    disabled=not editando,
                    label_visibility="collapsed",
                )
            sel_id = id_por_opcion[sel_idx]
            actual_id = activa.id if activa is not None else "__NONE__"

            with col_actions:
                if not editando:
                    if st.button(
                        "✏️ Editar",
                        key=f"edit_plan_activo_{carrera.codigo}",
                        use_container_width=True,
                    ):
                        st.session_state[edit_key] = True
                        st.rerun()
                else:
                    c_save, c_cancel = st.columns(2)
                    with c_save:
                        if st.button(
                            "💾",
                            key=f"save_plan_activo_{carrera.codigo}",
                            type="primary",
                            use_container_width=True,
                            help="Guardar cambio de plan activo",
                            disabled=(sel_id == actual_id),
                        ):
                            try:
                                set_plan_activo(
                                    session, carrera.codigo,
                                    None if sel_id == "__NONE__" else sel_id,
                                )
                                st.session_state.pop(edit_key, None)
                                st.toast("Plan activo actualizado.")
                                st.rerun()
                            except ValueError as e:
                                st.error(str(e))
                    with c_cancel:
                        if st.button(
                            "✕",
                            key=f"cancel_plan_activo_{carrera.codigo}",
                            use_container_width=True,
                            help="Cancelar",
                        ):
                            st.session_state.pop(edit_key, None)
                            st.rerun()

    # --- Grupos de materias asociados -------------------------
    with st.container(border=True):
        st.markdown("**📦 Grupos de materias asociados**")
        grupos_asoc = list_grupos_de_carrera(session, carrera.codigo)
        if not grupos_asoc:
            st.caption(
                "Ningún grupo tiene a esta carrera asociada. "
                "La asociación se maneja desde **Materias → 📦 "
                "Grupos de materias** en el campo 'Carreras asociadas' "
                "de cada grupo."
            )
        else:
            st.caption(
                "Grupos que declaran a esta carrera como asociada. Se "
                "usan para el chequeo de consistencia (comparan las "
                "materias del grupo con las exclusivas de esta carrera "
                "en su plan activo)."
            )
            for g in grupos_asoc:
                st.markdown(
                    f"- 📦 **{g.nombre}**"
                    + (" · ⚠️ Sin clasificar" if g.es_sin_clasificar else "")
                )
        st.caption(
            "_Editá las asociaciones desde Materias → 📦 Grupos de materias._"
        )


def _render_carrera_readonly(session: Session, carrera) -> None:
    """Vista read-only de la carrera dentro de su expander: dos columnas
    con datos + plan activo + grupos + botones Editar/Eliminar."""
    col1, col2 = st.columns(2)
    with col1:
        st.write(f"**Código:** {carrera.codigo}")
        st.write(f"**Nombre:** {carrera.nombre}")
        st.write(f"**Título Otorgado:** {carrera.titulo_otorgado}")
    with col2:
        st.write(f"**Duración:** {carrera.duracion_anios} años")
        cantidad_text = (
            str(carrera.cantidad_materias)
            if carrera.cantidad_materias else "No definida"
        )
        st.write(f"**Cantidad de Materias:** {cantidad_text}")
        dicta_text = "Si" if carrera.dicta_recursado else "No"
        st.write(f"**Dicta recursado:** {dicta_text}")
        try:
            CarreraStatusWidget.render_inline_status(session, carrera.codigo)
        except Exception as e:
            st.error(f"Error al cargar estado: {str(e)}")

    st.divider()
    _render_plan_activo_y_grupos(session, carrera)

    st.markdown("")
    _spacer, col_edit, col_delete = st.columns([3, 1, 1])
    with col_edit:
        if st.button(
            "✏️ Editar",
            key=f"edit_{carrera.codigo}",
            use_container_width=True,
        ):
            st.session_state["edit_carrera"] = carrera.codigo
            st.rerun()
    with col_delete:
        if st.button(
            "🗑️ Eliminar",
            key=f"delete_{carrera.codigo}",
            use_container_width=True,
        ):
            st.session_state["delete_carrera"] = carrera.codigo
            st.rerun()


def _render_carrera_edit_inline(
    session: Session,
    carrera_codigo: str,
    custom_labels: dict[str, str],
) -> None:
    """Formulario de edición renderizado DENTRO del expander de la
    carrera (reemplaza el bloque legacy al fondo de la página)."""
    try:
        existing_carrera = carrera_service.get(session, carrera_codigo)
        if existing_carrera is None:
            st.error(
                f"Carrera con código '{carrera_codigo}' no encontrada"
            )
            st.session_state.pop("edit_carrera", None)
            st.rerun()
            return
    except Exception as e:
        st.error(f"Error al cargar carrera: {str(e)}")
        st.session_state.pop("edit_carrera", None)
        st.rerun()
        return

    default_values = (
        existing_carrera.model_dump()
        if hasattr(existing_carrera, "model_dump")
        else dict(existing_carrera)
    )

    st.markdown(f"**✏️ Editar carrera `{carrera_codigo}`**")
    with st.form(key=f"edit_carrera_{carrera_codigo}_form"):
        st.text_input(
            "Código",
            value=carrera_codigo,
            disabled=True,
            key=f"edit_{carrera_codigo}_codigo_display",
        )
        form_data = FormInputRenderer.render_form_input(
            model=Carrera,
            key=f"edit_{carrera_codigo}_input",
            exclude_fields=["codigo"],
            custom_labels=custom_labels,
            default_values=default_values,
        )
        col_submit, col_cancel = st.columns(2)
        with col_submit:
            submitted = st.form_submit_button(
                "💾 Guardar cambios",
                type="primary",
                use_container_width=True,
            )
        with col_cancel:
            cancelled = st.form_submit_button(
                "✕ Cancelar",
                use_container_width=True,
            )

        if cancelled:
            st.session_state.pop("edit_carrera", None)
            st.rerun()

        if submitted:
            form_data["codigo"] = carrera_codigo
            is_valid, errors = FormInputRenderer.validate_form_data(
                form_data, Carrera,
            )
            if not is_valid:
                FormInputRenderer.display_validation_errors(errors)
            else:
                try:
                    carrera_actualizada = Carrera(**form_data)
                    updated_carrera = carrera_service.update(
                        session, carrera_actualizada,
                    )
                    if updated_carrera:
                        st.toast("✅ Carrera actualizada.")
                        st.session_state.pop("edit_carrera", None)
                        st.rerun()
                    else:
                        st.error("❌ No se pudo actualizar la carrera")
                except Exception as e:
                    st.error(f"❌ Error al actualizar: {str(e)}")


def render_custom_carrera_page():
    """Render the carrera page with custom editing functionality."""
    
    # Custom labels for form fields
    custom_labels = {
        "codigo": "Código",
        "nombre": "Nombre",
        "titulo_otorgado": "Título Otorgado",
        "duracion_anios": "Duración (años)",
        "cantidad_materias": "Cantidad de Materias",
        "dicta_recursado": "Dicta recursado",
    }
    
    st.title("🎓 Carreras")
    st.caption(
        "Catálogo de carreras del sistema. Cada carrera tiene sus "
        "datos generales, sedes habilitadas para dictar sus "
        "materias específicas y el plan de estudio (qué materias se "
        "cursan en qué año y cuatrimestre)."
    )

    tab1, tab2, tab3 = st.tabs([
        "📋 Lista de carreras",
        "➕ Nueva carrera",
        "📚 Plan de estudio",
    ])
    
    with next(get_session()) as session:
        
        with tab1:
            st.subheader("Lista de carreras")

            try:
                carreras = carrera_service.get_all(session)

                if not carreras:
                    st.info(
                        "No hay carreras registradas. Creá una desde "
                        "la pestaña **➕ Nueva carrera**."
                    )
                else:
                    # Display carreras
                    for carrera in carreras:
                        _en_edicion = (
                            st.session_state.get("edit_carrera")
                            == carrera.codigo
                        )
                        _titulo_expander = (
                            f"🎓 {carrera.codigo} - {carrera.nombre}"
                            + (" · ✏️ editando" if _en_edicion else "")
                        )
                        with st.expander(
                            _titulo_expander,
                            expanded=_en_edicion,
                        ):
                            if _en_edicion:
                                _render_carrera_edit_inline(
                                    session, carrera.codigo, custom_labels,
                                )
                            else:
                                _render_carrera_readonly(
                                    session, carrera,
                                )
                    # NOTE: se retiró el bloque "Editar Carrera" al fondo
                    # de la página — la edición ahora vive dentro del
                    # expander de cada carrera. La condición
                    # ``st.session_state.get("edit_carrera")`` la maneja
                    # `_render_carrera_edit_inline`.
                    
                    # Handle delete action
                    if "delete_carrera" in st.session_state:
                        carrera_codigo = st.session_state["delete_carrera"]
                        st.subheader(f"Eliminar Carrera: {carrera_codigo}")
                        
                        st.warning("⚠️ ¿Está seguro que desea eliminar esta carrera? Esta acción no se puede deshacer.")
                        
                        # Check if carrera has materias
                        try:
                            materias = carrera_service.get_materias(session, carrera_codigo)
                            if materias:
                                st.error(f"❌ No se puede eliminar: la carrera tiene {len(materias)} materia(s) asociada(s)")
                                st.info("💡 Primero debe desasociar todas las materias de esta carrera.")
                        except Exception:
                            pass
                        
                        col_confirm, col_cancel = st.columns(2)
                        
                        with col_confirm:
                            if st.button("🗑️ Confirmar Eliminación", type="primary"):
                                try:
                                    success = carrera_service.delete(session, carrera_codigo)
                                    if success:
                                        st.success("✅ Carrera eliminada exitosamente")
                                        del st.session_state["delete_carrera"]
                                        st.rerun()
                                    else:
                                        st.error("❌ No se pudo eliminar la carrera")
                                except Exception as e:
                                    st.error(f"❌ Error al eliminar: {str(e)}")
                        
                        with col_cancel:
                            if st.button("❌ Cancelar"):
                                del st.session_state["delete_carrera"]
                                st.rerun()
            
            except Exception as e:
                st.error(f"Error al cargar carreras: {str(e)}")
        
        with tab2:
            st.subheader("Nueva carrera")
            st.caption(
                "Completá los datos generales de la carrera. Después "
                "de crearla vas a poder cargar su plan de estudio "
                "desde la pestaña **📚 Plan de estudio**."
            )
            
            with st.form(key="create_carrera_form"):
                form_data = FormInputRenderer.render_form_input(
                    model=Carrera,
                    key="create_carrera_input",
                    custom_labels=custom_labels,
                )
                
                submitted = st.form_submit_button("Crear Carrera", type="primary")
                
                if submitted:
                    # Validate form data
                    is_valid, errors = FormInputRenderer.validate_form_data(form_data, Carrera)
                    
                    if not is_valid:
                        FormInputRenderer.display_validation_errors(errors)
                    else:
                        try:
                            # Create carrera instance
                            carrera = Carrera(**form_data)
                            created_carrera = carrera_service.create(session, carrera)
                            
                            if created_carrera:
                                st.success("✅ Carrera creada exitosamente")
                                st.rerun()
                            else:
                                st.error("❌ No se pudo crear la carrera")
                        except Exception as e:
                            st.error(f"❌ Error al crear: {str(e)}")
        
        with tab3:
            st.subheader("Plan de estudio")
            st.caption(
                "Definí qué materias corresponden a cada carrera, "
                "año y cuatrimestre. Podés tener varias versiones "
                "del plan (para reflejar cambios curriculares con "
                "el paso del tiempo) — la versión activa es la que "
                "usan los cronogramas y la asignación de aulas."
            )

            carreras = carrera_service.get_all(session)

            if not carreras:
                st.info(
                    "No hay carreras registradas. Creá una primero "
                    "desde la pestaña **➕ Nueva carrera**."
                )
            else:
                carrera_options = [(c.codigo, c.nombre) for c in carreras]

                selected_carrera = st.selectbox(
                    "Carrera",
                    options=[opt[0] for opt in carrera_options],
                    format_func=lambda x: (
                        f"{x} — {next((opt[1] for opt in carrera_options if opt[0] == x), '')}"
                    ),
                    key="carrera_materias_view",
                )

                if selected_carrera:
                    # --- Version selector ---
                    plan_versions = carrera_service.get_plan_versions(session, selected_carrera)

                    if not plan_versions:
                        st.warning(
                            "Esta carrera todavía no tiene ninguna "
                            "versión de plan de estudio. Creá una "
                            "para empezar a asociarle materias."
                        )
                    else:
                        version_options = {
                            v.id: f"{v.nombre} ({v.fecha_creacion})"
                            for v in plan_versions
                        }

                        with st.container(border=True):
                            st.markdown("**📄 Versión del plan**")
                            col_ver, col_new = st.columns([3, 1])
                            with col_ver:
                                selected_version_id = st.selectbox(
                                    "Versión activa",
                                    options=list(version_options.keys()),
                                    format_func=lambda x: (
                                        version_options[x]
                                    ),
                                    key="plan_version_select",
                                    help=(
                                        "Elegí la versión sobre la "
                                        "que querés trabajar. Cada "
                                        "versión mantiene su propia "
                                        "lista de materias por año."
                                    ),
                                )
                            with col_new:
                                st.write("")
                                st.write("")
                                if st.button(
                                    "➕ Nueva versión",
                                    key="btn_new_version",
                                    width="stretch",
                                ):
                                    st.session_state[
                                        "creating_version"
                                    ] = True

                        # Create new version form
                        if st.session_state.get("creating_version"):
                            with st.form("create_version_form"):
                                st.markdown(
                                    "**Crear nueva versión del plan**"
                                )
                                new_name = st.text_input(
                                    "Nombre de la nueva versión",
                                    placeholder="Ej: Plan 2026",
                                )
                                new_desc = st.text_input(
                                    "Descripción (opcional)",
                                )
                                copy_from = st.checkbox(
                                    "Copiar las materias de la "
                                    "versión actual",
                                    value=True,
                                    help=(
                                        "Si tildás, la nueva "
                                        "versión arranca con las "
                                        "mismas materias que la "
                                        "actual — así podés "
                                        "modificarlas sin perder "
                                        "el trabajo hecho."
                                    ),
                                )
                                if st.form_submit_button("Crear"):
                                    if new_name.strip():
                                        carrera_service.create_plan_version(
                                            session,
                                            selected_carrera,
                                            new_name.strip(),
                                            descripcion=new_desc.strip(),
                                            copy_from_version_id=(
                                                selected_version_id
                                                if copy_from else None
                                            ),
                                        )
                                        st.session_state.pop(
                                            "creating_version", None,
                                        )
                                        st.success(
                                            f"Versión '{new_name}' "
                                            f"creada"
                                        )
                                        st.rerun()
                                    else:
                                        st.error(
                                            "El nombre no puede "
                                            "estar vacío."
                                        )

                        # Edit version name/description
                        selected_version = next(
                            (v for v in plan_versions
                             if v.id == selected_version_id),
                            None,
                        )
                        if selected_version:
                            with st.expander(
                                "✏️ Renombrar / editar versión",
                            ):
                                edit_name = st.text_input(
                                    "Nombre",
                                    value=selected_version.nombre,
                                    key="edit_ver_name",
                                )
                                edit_desc = st.text_input(
                                    "Descripción",
                                    value=(
                                        selected_version.descripcion
                                    ),
                                    key="edit_ver_desc",
                                )
                                if st.button(
                                    "💾 Guardar",
                                    key="btn_save_version",
                                ):
                                    carrera_service.update_plan_version(
                                        session, selected_version_id,
                                        nombre=(
                                            edit_name.strip() or None
                                        ),
                                        descripcion=edit_desc.strip(),
                                    )
                                    st.success("Versión actualizada.")
                                    st.rerun()

                        st.divider()

                        # Widget de completitud del plan.
                        st.markdown("### 📊 Estado del plan")
                        CarreraStatusWidget.render_inline_status(
                            session, selected_carrera,
                        )

                        st.divider()

                        # Selector de año para asociar materias.
                        st.markdown("### 📚 Materias por año")
                        st.caption(
                            "Elegí el año y agregá las materias que "
                            "se cursan en cada cuatrimestre."
                        )
                        selected_year = st.selectbox(
                            "Año",
                            options=[1, 2, 3, 4, 5, 6],
                            format_func=lambda x: f"{x}º año",
                            key="selected_year",
                        )

                        st.divider()

                        # Get all materias for this carrera, year, and version
                        materias_anuales = carrera_service.get_materias_by_year_and_semester(
                            session, selected_carrera, selected_year,
                            plan_version_id=selected_version_id,
                        )

                        anuales = [(m, a, c) for m, a, c in materias_anuales if c == "anual"]
                        primer_cuatri = [(m, a, c) for m, a, c in materias_anuales if c == "1C"]
                        segundo_cuatri = [(m, a, c) for m, a, c in materias_anuales if c == "2C"]

                        col1, col2, col3 = st.columns(3)

                        # Helper to render a column
                        def _render_period_column(title, materias_list, period_key, cuatrimestre_plan_value, periodo_filter):
                            with st.expander(f"{title} ({len(materias_list)})", expanded=True):
                                if materias_list:
                                    for materia, anio, cuatri in materias_list:
                                        col_mat, col_del = st.columns([4, 1])
                                        with col_mat:
                                            st.markdown(f"**{materia.codigo}**")
                                            st.caption(f"{materia.nombre}")
                                        with col_del:
                                            if st.button("X", key=f"del_{period_key}_{materia.codigo}", help="Desasociar"):
                                                try:
                                                    carrera_service.remove_materia(
                                                        session, selected_carrera, materia.codigo,
                                                        plan_version_id=selected_version_id,
                                                    )
                                                    st.success("Desasociada")
                                                    st.rerun()
                                                except Exception as e:
                                                    st.error(f"Error: {e}")
                                else:
                                    st.info(f"Sin materias {period_key}")

                                st.markdown("---")
                                st.markdown(f"**Asociar Materia {period_key}**")

                                all_materias = materia_service.get_all(session, limit=10000)
                                associated_codigos = {m.codigo for m, _, _ in materias_anuales}
                                available = [m for m in all_materias if m.codigo not in associated_codigos and m.periodo == periodo_filter]

                                if available:
                                    materia_to_add = st.selectbox(
                                        "Materia",
                                        options=[m.codigo for m in available],
                                        format_func=lambda x: f"{x} - {next((m.nombre for m in available if m.codigo == x), '')}",
                                        key=f"add_{period_key}_{selected_year}",
                                        label_visibility="collapsed",
                                    )
                                    if st.button("Asociar", key=f"btn_add_{period_key}_{selected_year}"):
                                        try:
                                            carrera_service.add_materia(
                                                session, selected_carrera, materia_to_add,
                                                plan_version_id=selected_version_id,
                                                anio_plan=selected_year,
                                                cuatrimestre_plan=cuatrimestre_plan_value,
                                            )
                                            st.success("Asociada")
                                            st.rerun()
                                        except Exception as e:
                                            st.error(f"Error: {e}")
                                else:
                                    st.caption(f"No hay materias disponibles")

                        with col1:
                            _render_period_column("Anuales", anuales, "anual", "anual", "anual")
                        with col2:
                            _render_period_column("1er Cuatrimestre", primer_cuatri, "1C", "1C", "cuatrimestral")
                        with col3:
                            _render_period_column("2do Cuatrimestre", segundo_cuatri, "2C", "2C", "cuatrimestral")


# Render the custom page
render_custom_carrera_page()
