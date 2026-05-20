"""
Specialized form renderer for Materia entities with carrera relationship handling.

This module provides custom form rendering for Materia entities that includes
many-to-many carrera selection and validation.
"""

from typing import Any, Dict, List, Optional

import streamlit as st
from sqlmodel import Session

from src.domain.problem.materia import Materia
from src.ui.form_input_renderer import FormInputRenderer
from src.ui.many_to_many_selector import ManyToManySelector
from src.services.crud_services import materia_service


class MateriaFormRenderer:
    """Specialized form renderer for Materia entities."""

    @staticmethod
    def render_materia_create_form(
        session: Session,
        key: str = None,
        exclude_fields: List[str] = None,
        custom_labels: Dict[str, str] = None,
    ) -> Optional[Dict[str, Any]]:
        """
        Render create form for Materia with carrera selection including year/semester.
        
        Args:
            session: Database session
            key: Streamlit form key
            exclude_fields: Fields to exclude from form
            custom_labels: Custom labels for fields
            
        Returns:
            Dictionary with form data including carreras with year/semester, or None if not submitted
        """
        form_key = key or "create_materia_form"
        
        with st.form(key=form_key):
            st.subheader("Crear Materia")
            
            # Render standard materia fields
            all_exclude = list(exclude_fields or [])
            
            form_data = FormInputRenderer.render_form_input(
                model=Materia,
                key=f"{form_key}_input",
                exclude_fields=all_exclude,
                custom_labels=custom_labels,
            )
            
            # Add carrera selection with year/semester using data_editor
            st.markdown("### Asignación de Carreras")
            st.caption("Debe asignar al menos una carrera especificando año y cuatrimestre")
            
            # Get all carreras and plan versions
            from src.services.crud_services import carrera_service
            from src.database.models import PlanCarreraVersionDB
            from sqlmodel import select
            import pandas as pd

            all_carreras = carrera_service.get_all(session)

            if not all_carreras:
                st.warning("No hay carreras disponibles. Cree una carrera primero.")
                return None

            # Build plan version options per carrera
            all_plan_versions = session.exec(
                select(PlanCarreraVersionDB)
                .order_by(PlanCarreraVersionDB.fecha_creacion.desc())
            ).all()
            plan_names_unique = sorted(set(pv.nombre for pv in all_plan_versions))
            # Default: nombre del plan mas reciente (primera por orden desc)
            default_plan_name = all_plan_versions[0].nombre if all_plan_versions else ""

            # Check if materia is annual based on form data
            is_anual = form_data.get("periodo") == "anual"

            if is_anual:
                st.info("Materia anual: El cuatrimestre se establece automaticamente en 0 (anual).")

            # Create initial dataframe for carreras
            if f"{form_key}_carrera_data" not in st.session_state:
                st.session_state[f"{form_key}_carrera_data"] = pd.DataFrame({
                    "Carrera": [],
                    "Año": [],
                    "Cuatrimestre": [],
                    "Plan": [],
                })

            # Configure column settings based on periodo
            carrera_options = [f"{c.codigo} - {c.nombre}" for c in all_carreras]
            base_columns = {
                "Carrera": st.column_config.SelectboxColumn(
                    "Carrera",
                    options=carrera_options,
                    required=True,
                    width="large"
                ),
                "Año": st.column_config.NumberColumn(
                    "Año",
                    min_value=1,
                    max_value=6,
                    default=1,
                    required=True,
                    width="small"
                ),
            }
            if is_anual:
                base_columns["Cuatrimestre"] = st.column_config.TextColumn(
                    "Cuatrimestre",
                    default="Anual",
                    disabled=True,
                    width="small"
                )
            else:
                base_columns["Cuatrimestre"] = st.column_config.SelectboxColumn(
                    "Cuatrimestre",
                    options=["1C", "2C"],
                    default="1C",
                    required=True,
                    width="small"
                )
            base_columns["Plan"] = st.column_config.SelectboxColumn(
                "Plan",
                options=plan_names_unique,
                default=default_plan_name,
                required=True,
                width="medium",
                help="Version del plan de estudios"
            )
            column_config = base_columns

            # Render editable dataframe
            edited_df = st.data_editor(
                st.session_state[f"{form_key}_carrera_data"],
                column_config=column_config,
                num_rows="dynamic",
                use_container_width=True,
                key=f"{form_key}_carreras_editor",
                hide_index=True,
            )

            # Update session state
            st.session_state[f"{form_key}_carrera_data"] = edited_df
            
            submitted = st.form_submit_button("Crear Materia", type="primary")
            
            if submitted:
                # Validate form data
                is_valid, errors = FormInputRenderer.validate_form_data(form_data, Materia)
                
                # Process carrera data
                carrera_details = []
                if not edited_df.empty:
                    for _, row in edited_df.iterrows():
                        if pd.notna(row["Carrera"]):
                            # Extract codigo from "CODIGO - Nombre" format
                            carrera_codigo = row["Carrera"].split(" - ")[0]
                            anio = int(row["Año"]) if pd.notna(row["Año"]) else 1
                            plan_nombre = str(row["Plan"]) if pd.notna(row.get("Plan")) else default_plan_name

                            if is_anual:
                                cuatri = "anual"
                            else:
                                cuatri = str(row["Cuatrimestre"]) if pd.notna(row["Cuatrimestre"]) else "1C"

                            carrera_details.append({
                                "carrera_codigo": carrera_codigo,
                                "anio_plan": anio,
                                "cuatrimestre_plan": cuatri,
                                "plan_nombre": plan_nombre,
                            })
                
                # Validate carrera selection
                if not carrera_details:
                    if "carreras" not in errors:
                        errors["carreras"] = []
                    errors["carreras"].append("Debe asignar al menos una carrera")
                    is_valid = False
                
                if not is_valid:
                    FormInputRenderer.display_validation_errors(errors)
                    return None

                _hs = form_data.get("horas_semanales")
                _ht = form_data.get("horas_teoria") or 0
                _hl = form_data.get("horas_laboratorio") or 0
                if _hs and (_ht + _hl) != _hs:
                    st.warning(
                        f"Hs Teoría ({_ht}) + Hs Lab ({_hl}) "
                        f"= {_ht + _hl} ≠ Hs/Sem ({_hs}). "
                        "Corregí antes de guardar."
                    )
                    return None

                # Clear session state
                if f"{form_key}_carrera_data" in st.session_state:
                    del st.session_state[f"{form_key}_carrera_data"]

                # Add carreras with details to form data
                form_data["carrera_details"] = carrera_details
                return form_data
        
        return None
    
    @staticmethod
    def render_materia_update_form(
        materia_codigo: str,
        session: Session,
        key: str = None,
        exclude_fields: List[str] = None,
        custom_labels: Dict[str, str] = None,
    ) -> Optional[Dict[str, Any]]:
        """
        Render update form for Materia with carrera selection.
        
        Args:
            materia_codigo: The materia codigo to update
            session: Database session
            key: Streamlit form key
            exclude_fields: Fields to exclude from form
            custom_labels: Custom labels for fields
            
        Returns:
            Dictionary with form data including selected carreras, or None if not submitted
        """
        form_key = key or f"update_materia_{materia_codigo}_form"
        
        # Get existing materia
        try:
            existing_materia = materia_service.get(session, materia_codigo)
            if existing_materia is None:
                st.error(f"Materia con código '{materia_codigo}' no encontrada")
                return None
        except Exception as e:
            st.error(f"Error al cargar materia: {str(e)}")
            return None
        
        # Get current carreras
        try:
            current_carreras = materia_service.get_carreras(session, materia_codigo)
            current_carrera_codigos = [c.codigo for c in current_carreras]
        except Exception as e:
            st.error(f"Error al cargar carreras: {str(e)}")
            current_carrera_codigos = []
        
        # Extract default values from existing materia
        if hasattr(existing_materia, "model_dump"):
            default_values = existing_materia.model_dump()
        else:
            default_values = dict(existing_materia)
        
        # Determine fields to exclude (including codigo field)
        all_exclude = list(exclude_fields or [])
        if "codigo" not in all_exclude:
            all_exclude.append("codigo")
        
        with st.form(key=form_key):
            st.subheader("Editar Materia")
            
            # Show codigo as read-only
            st.text_input(
                "Código",
                value=materia_codigo,
                disabled=True,
                key=f"{form_key}_codigo_display",
            )
            
            # Render standard materia fields
            form_data = FormInputRenderer.render_form_input(
                model=Materia,
                key=f"{form_key}_input",
                exclude_fields=all_exclude,
                custom_labels=custom_labels,
                default_values=default_values,
            )
            
            # Add carrera selection
            st.markdown("### Asignación de Carreras")
            selected_carreras = ManyToManySelector.render_carrera_selector_for_materia(
                session=session,
                current_carrera_codigos=current_carrera_codigos,
                key=f"{form_key}_carreras",
            )
            
            submitted = st.form_submit_button("Actualizar Materia")
            
            if submitted:
                # Add back the codigo field
                form_data["codigo"] = materia_codigo
                
                # Validate form data
                is_valid, errors = FormInputRenderer.validate_form_data(form_data, Materia)
                
                # Validate carrera selection
                if not selected_carreras:
                    if "carreras" not in errors:
                        errors["carreras"] = []
                    errors["carreras"].append("Debe seleccionar al menos una carrera")
                    is_valid = False
                
                if not is_valid:
                    FormInputRenderer.display_validation_errors(errors)
                    return None
                
                # Add carreras to form data
                form_data["carreras"] = selected_carreras
                return form_data
        
        return None
    
    @staticmethod
    def create_materia_with_carreras(
        form_data: Dict[str, Any],
        session: Session,
    ) -> Optional[Materia]:
        """
        Create a materia with carrera associations including year/semester.

        Args:
            form_data: Form data including carrera_details
            session: Database session

        Returns:
            Created Materia instance or None if failed
        """
        from src.database.models import PlanCarreraVersionDB
        from sqlmodel import select

        try:
            # Extract carrera details from form data
            carrera_details = form_data.pop("carrera_details", [])

            # Create materia instance
            materia = Materia(**form_data)

            # Create materia in database
            created_materia = materia_service.create(session, materia)

            # Set carrera associations with year/semester
            for detail in carrera_details:
                carrera_codigo = detail["carrera_codigo"]
                plan_nombre = detail.get("plan_nombre")

                # Resolve plan_version_id by (carrera_codigo, plan_nombre)
                query = select(PlanCarreraVersionDB).where(
                    PlanCarreraVersionDB.carrera_codigo == carrera_codigo
                )
                if plan_nombre:
                    query = query.where(PlanCarreraVersionDB.nombre == plan_nombre)
                # Prefer the most recent
                query = query.order_by(PlanCarreraVersionDB.fecha_creacion.desc())
                plan_version = session.exec(query).first()

                if plan_version is None:
                    st.error(
                        f"No se encontro plan de estudios para la carrera "
                        f"'{carrera_codigo}'"
                        + (f" con nombre '{plan_nombre}'" if plan_nombre else "")
                    )
                    return None

                materia_service.add_carrera(
                    session,
                    created_materia.codigo,
                    carrera_codigo,
                    plan_version.id,
                    anio_plan=detail["anio_plan"],
                    cuatrimestre_plan=detail["cuatrimestre_plan"],
                )

            return created_materia

        except Exception as e:
            st.error(f"Error al crear materia: {str(e)}")
            return None
    
    @staticmethod
    def update_materia_with_carreras(
        form_data: Dict[str, Any],
        session: Session,
    ) -> Optional[Materia]:
        """
        Update a materia with carrera associations.

        Uses the latest plan version for each carrera when updating
        associations via set_carreras.

        Args:
            form_data: Form data including carreras
            session: Database session

        Returns:
            Updated Materia instance or None if failed
        """
        from src.database.models import PlanCarreraVersionDB
        from sqlmodel import select

        try:
            # Extract carreras from form data
            carrera_codigos = form_data.pop("carreras", [])
            materia_codigo = form_data["codigo"]

            # Create materia instance
            materia = Materia(**form_data)

            # Update materia in database
            updated_materia = materia_service.update(session, materia)

            # Update carrera associations per plan version
            if carrera_codigos:
                for carrera_codigo in carrera_codigos:
                    # Get latest plan version for this carrera
                    plan_version = session.exec(
                        select(PlanCarreraVersionDB)
                        .where(PlanCarreraVersionDB.carrera_codigo == carrera_codigo)
                        .order_by(PlanCarreraVersionDB.fecha_creacion.desc())
                    ).first()

                    if plan_version is None:
                        st.error(
                            f"No se encontro plan de estudios para la carrera "
                            f"'{carrera_codigo}'"
                        )
                        return None

                    materia_service.add_carrera(
                        session,
                        materia_codigo,
                        carrera_codigo,
                        plan_version.id,
                    )

            return updated_materia

        except Exception as e:
            st.error(f"Error al actualizar materia: {str(e)}")
            return None