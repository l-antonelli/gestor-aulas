"""Gestión de Materias - Refactored to use UI components."""

import streamlit as st
from src.database.connection import get_session, init_db
from src.database.crud import materia_crud, comision_crud
from src.database.converters import to_domain, to_db
from src.domain.problem.materia import Materia
from src.domain.problem.comision import Comision
from src.ui.crud_form_renderer import CRUDFormRenderer
from src.ui.nested_entity_display import NestedEntityDisplay

# Import relationship definitions to register relationships
import src.services.relationship_definitions  # noqa: F401

# Initialize database
init_db()

st.set_page_config(page_title="Materias", page_icon="📚", layout="wide")
st.title("📚 Gestión de Materias")

# Initialize session state for success messages
if "materia_created" not in st.session_state:
    st.session_state.materia_created = None

tab_list, tab_create, tab_view = st.tabs(["📋 Listado", "➕ Nueva Materia", "👁️ Ver Detalle"])


# CRUD wrapper functions for Materia
def create_materia_with_cascading(session, instance: Materia) -> tuple:
    """Create a new materia using cascading operations.
    
    Returns:
        Tuple of (created_materia, created_children)
    """
    from src.services.cascading_operations import CascadingOperations
    
    db_instance = to_db(instance)
    created, children = CascadingOperations.create_with_cascading(
        parent_instance=db_instance,
        parent_crud_func=materia_crud.create,
        session=session,
    )
    return to_domain(created), children


def create_materia(session, instance: Materia) -> Materia:
    """Create a new materia using cascading operations."""
    created, _ = create_materia_with_cascading(session, instance)
    return created


def read_materia(entity_id: str, **kwargs) -> Materia:
    """Read a materia by codigo."""
    for session in get_session():
        db_instance = materia_crud.get(session, entity_id)
        if db_instance:
            return to_domain(db_instance)
    return None


def update_materia(session, instance: Materia) -> Materia:
    """Update an existing materia."""
    db_instance = to_db(instance)
    updated = materia_crud.update(session, db_instance)
    return to_domain(updated)


def delete_materia(session, entity_id: str) -> bool:
    """Delete a materia by codigo."""
    return materia_crud.delete(session, entity_id)


with tab_list:
    with next(get_session()) as session:
        materias = materia_crud.get_all(session, limit=500)
        # Count comisiones per materia
        materias_data = []
        for m in materias:
            comisiones = [c for c in comision_crud.get_all(session, limit=500) if c.materia_codigo == m.codigo]
            materias_data.append({
                "Código": m.codigo,
                "Nombre": m.nombre,
                "Período": m.periodo,
                "Año": m.anio_carrera,
                "Cuatri": m.cuatrimestre_carrera,
                "Cupo": m.cupo,
                "Hs/Sem": m.horas_semanales,
                "Comisiones": len(comisiones),
            })
    
    if not materias_data:
        st.info("No hay materias registradas. Crea una en la pestaña 'Nueva Materia'.")
    else:
        st.dataframe(materias_data, use_container_width=True, hide_index=True)
        st.caption(f"Total: {len(materias_data)} materias")
        
        # Delete section using CRUDFormRenderer
        st.divider()
        st.subheader("Eliminar Materia")
        col1, col2 = st.columns([3, 1])
        with col1:
            codigo_delete = st.selectbox(
                "Seleccionar materia a eliminar",
                options=[m["Código"] for m in materias_data],
                format_func=lambda x: f"{x} - {next((m['Nombre'] for m in materias_data if m['Código'] == x), '')}",
                key="delete_materia"
            )
        with col2:
            st.write("")
            st.write("")
            if st.button("🗑️ Eliminar", type="secondary"):
                if delete_materia(codigo_delete):
                    st.success(f"Materia {codigo_delete} eliminada")
                    st.rerun()
                else:
                    st.error("Error al eliminar la materia")

with tab_create:
    st.info("💡 Al crear una materia se genera automáticamente una 'Comisión Única' asociada.")
    
    # Show success message if materia was just created
    if st.session_state.materia_created:
        created_info = st.session_state.materia_created
        st.success(f"✅ Materia '{created_info['nombre']}' ({created_info['codigo']}) creada exitosamente")
        if created_info.get('children'):
            st.info(f"🔗 Se creó automáticamente {len(created_info['children'])} comisión(es) asociada(s):")
            for child in created_info['children']:
                st.write(f"  • **{child['nombre']}** (ID: {child['id']}, Cupo: {child['cupo']})")
        st.balloons()
        # Clear the message after showing
        st.session_state.materia_created = None
    
    # Form for creating a new Materia
    with st.form("create_materia_form"):
        codigo = st.text_input("Código *", placeholder="Ej: MAT101")
        nombre = st.text_input("Nombre *", placeholder="Ej: Cálculo I")
        cupo = st.number_input("Cupo máximo *", min_value=1, value=30)
        horas_semanales = st.number_input("Horas semanales *", min_value=1, value=4)
        
        submitted = st.form_submit_button("💾 Guardar", type="primary")
        
        if submitted:
            if not codigo or not nombre:
                st.error("❌ Por favor complete todos los campos obligatorios")
            else:
                try:
                    with next(get_session()) as session:
                        # Create the Materia instance
                        materia = Materia(
                            codigo=codigo,
                            nombre=nombre,
                            cupo=cupo,
                            horas_semanales=horas_semanales,
                        )
                        
                        # Create with cascading
                        created, children = create_materia_with_cascading(session, materia)
                        
                        # Store success info in session state
                        st.session_state.materia_created = {
                            'codigo': created.codigo,
                            'nombre': created.nombre,
                            'children': [
                                {'id': c.id, 'nombre': c.nombre, 'cupo': c.cupo}
                                for c in children
                            ] if children else []
                        }
                        
                        st.rerun()
                        
                except Exception as e:
                    st.error(f"❌ Error al crear la materia: {str(e)}")

with tab_view:
    with next(get_session()) as session:
        materias = materia_crud.get_all(session, limit=500)
    
    if not materias:
        st.info("No hay materias para ver.")
    else:
        codigo_view = st.selectbox(
            "Seleccionar materia",
            options=[m.codigo for m in materias],
            format_func=lambda x: f"{x} - {next((m.nombre for m in materias if m.codigo == x), '')}",
            key="view_materia"
        )
        
        if codigo_view:
            # Use CRUDFormRenderer for read operation
            materia = read_materia(codigo_view)
            
            if materia:
                CRUDFormRenderer.render_read_form(
                    model=Materia,
                    entity_id=codigo_view,
                    crud_read_func=read_materia,
                    custom_labels={
                        "codigo": "Código",
                        "nombre": "Nombre",
                        "cupo": "Cupo máximo",
                        "horas_semanales": "Horas semanales",
                    },
                    title=f"Detalle de Materia: {codigo_view}",
                )
                
                # Display nested Comisiones
                st.divider()
                with next(get_session()) as session:
                    NestedEntityDisplay.render_nested_entities(
                        parent_instance=materia,
                        parent_model=Materia,
                        child_model=Comision,
                        child_crud_func=lambda s: comision_crud.get_all(s, limit=500),
                        session=session,
                    )
