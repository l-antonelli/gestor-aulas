"""Gestión de Comisiones."""

import streamlit as st
from src.database.connection import get_session
from src.database.models import ComisionDB, MateriaDB
from src.database.crud import comision_crud, materia_crud
from src.database.converters import to_domain, to_db
from src.domain.problem.comision import Comision
from src.domain.problem.materia import Materia
from src.ui.crud_form_renderer import CRUDFormRenderer
from src.ui.form_input_renderer import FormInputRenderer
from src.ui.relationship_selector import RelationshipSelector

st.set_page_config(page_title="Comisiones", page_icon="👥", layout="wide")
st.title("👥 Gestión de Comisiones")

tab_list, tab_create = st.tabs(["📋 Listado", "➕ Nueva Comisión"])


# CRUD wrapper functions for Comision
def create_comision(session, instance: Comision) -> Comision:
    """Create a new comision."""
    db_instance = to_db(instance)
    created = comision_crud.create(session, db_instance)
    return to_domain(created)


def read_comision(entity_id: str, **kwargs) -> Comision:
    """Read a comision by id."""
    for session in get_session():
        db_instance = comision_crud.get(session, entity_id)
        if db_instance:
            return to_domain(db_instance)
    return None


def update_comision(session, instance: Comision) -> Comision:
    """Update an existing comision."""
    db_instance = to_db(instance)
    updated = comision_crud.update(session, db_instance)
    return to_domain(updated)


def delete_comision(session, entity_id: str) -> bool:
    """Delete a comision by id."""
    return comision_crud.delete(session, entity_id)

with tab_list:
    with next(get_session()) as session:
        comisiones = comision_crud.get_all(session)
        # Eager load materia names
        comisiones_data = []
        for c in comisiones:
            materia = materia_crud.get(session, c.materia_codigo)
            comisiones_data.append({
                "ID": c.id,
                "Materia": f"{c.materia_codigo} - {materia.nombre if materia else 'N/A'}",
                "Número": c.numero,
                "Cupo": c.cupo,
                "Descripción": c.descripcion or "-",
            })
    
    if not comisiones_data:
        st.info("No hay comisiones registradas.")
    else:
        st.dataframe(comisiones_data, use_container_width=True, hide_index=True)
        
        st.subheader("Eliminar Comisión")
        id_delete = st.selectbox(
            "Seleccionar comisión a eliminar",
            options=[c.id for c in comisiones],
            key="delete_comision"
        )
        if st.button("🗑️ Eliminar", type="secondary"):
            with next(get_session()) as session:
                if comision_crud.delete(session, id_delete):
                    st.success(f"Comisión {id_delete} eliminada")
                    st.rerun()

with tab_create:
    with next(get_session()) as session:
        materias = materia_crud.get_all(session)
    
    if not materias:
        st.warning("Primero debes crear al menos una materia.")
    else:
        st.info("💡 El sistema validará que la suma de cupos de todas las comisiones no exceda el cupo de la materia.")
        
        with st.form("create_comision"):
            st.subheader("Crear Nueva Comisión")
            
            # Use relationship selector for materia_codigo
            with next(get_session()) as session:
                materia_codigo = RelationshipSelector.render_searchable_selector(
                    field_name="materia_codigo",
                    parent_model=Materia,
                    child_model=Comision,
                    crud_func=lambda s: materia_crud.get_all(s, limit=500),
                    session=session,
                    search_fields=["codigo", "nombre"],
                    key="comision_materia_selector",
                    label="Materia",
                )
            
            numero = st.number_input("Número de comisión", min_value=1, value=1)
            nombre = st.text_input("Nombre", value=f"Comisión {numero}")
            cupo = st.number_input("Cupo", min_value=1, value=30)
            descripcion = st.text_input("Descripción (opcional)", placeholder="Turno mañana")
            
            submitted = st.form_submit_button("💾 Guardar", type="primary")
            
            if submitted:
                if not materia_codigo:
                    st.error("Debe seleccionar una materia")
                else:
                    comision_id = f"{materia_codigo}-C{numero}"
                    comision = Comision(
                        id=comision_id,
                        materia_codigo=materia_codigo,
                        nombre=nombre,
                        numero=numero,
                        cupo=cupo,
                        descripcion=descripcion
                    )
                    
                    # Validate cross-entity constraints before creating
                    with next(get_session()) as session:
                        # Get parent materia
                        materia_db = materia_crud.get(session, materia_codigo)
                        if not materia_db:
                            st.error(f"Materia '{materia_codigo}' no encontrada")
                        else:
                            # Get all existing comisiones for this materia
                            all_comisiones = comision_crud.get_all(session, limit=500)
                            existing_comisiones = [c for c in all_comisiones if c.materia_codigo == materia_codigo]
                            
                            # Add the new comision to the list for validation
                            from src.database.converters import to_db
                            comision_db = to_db(comision)
                            all_comisiones_for_validation = existing_comisiones + [comision_db]
                            
                            # Validate sum constraint
                            from src.services.cross_entity_validator import CrossEntityValidator
                            is_valid, error_msg = CrossEntityValidator.validate_sum_constraint(
                                parent_instance=materia_db,
                                child_instances=all_comisiones_for_validation,
                                parent_field="cupo",
                                child_field="cupo",
                            )
                            
                            if not is_valid:
                                st.error(f"❌ {error_msg}")
                                # Show suggestions
                                suggestions = CrossEntityValidator.get_constraint_suggestions(
                                    parent_instance=materia_db,
                                    child_instances=all_comisiones_for_validation,
                                    validation_error=error_msg,
                                )
                                for suggestion in suggestions:
                                    st.info(f"💡 {suggestion}")
                            else:
                                # Create the comision
                                try:
                                    created = create_comision(session, comision)
                                    st.success(f"✅ Comisión '{comision_id}' creada exitosamente")
                                    st.rerun()
                                except Exception as e:
                                    st.error(f"❌ Error al crear comisión: {e}")
