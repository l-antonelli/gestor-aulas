"""
Component for managing Materia-Carrera associations with year and semester.

This component provides an editable table interface for managing the many-to-many
relationship between Materia and Carrera, including curriculum placement (year/semester).
"""

import streamlit as st
import pandas as pd
from sqlmodel import Session, select
from typing import List, Dict, Any

from src.services.crud_services import materia_service, carrera_service
from src.database.models import PlanEstudioDB


class MateriaCarreraEditor:
    """Editor component for Materia-Carrera associations (version-aware)."""

    @staticmethod
    def render_associations_editor(
        session: Session,
        materia_codigo: str,
        plan_version_id: str = None,
        key: str = "materia_carrera_editor",
    ) -> None:
        """
        Render an editable table for materia-carrera associations.

        When plan_version_id is None, shows associations across ALL plan
        versions (useful when editing a materia that spans multiple carreras).

        Args:
            session: Database session
            materia_codigo: The materia's codigo
            plan_version_id: Optional plan version to filter by. None = all.
            key: Unique key for the component
        """
        st.markdown("### Carreras Asociadas")

        materia = materia_service.get(session, materia_codigo)
        is_anual = materia and materia.periodo == "anual"

        if is_anual:
            st.info("Esta es una materia **anual**. El cuatrimestre se establece automaticamente.")

        associations = MateriaCarreraEditor._get_associations(
            session, materia_codigo, plan_version_id,
        )

        if not associations:
            st.info("Esta materia no esta asociada a ninguna carrera.")
        else:
            df = pd.DataFrame(associations)

            if is_anual:
                df["cuatrimestre_display"] = "Anual"
            else:
                df["cuatrimestre_display"] = df["cuatrimestre_plan"]

            column_config = {
                "carrera_codigo": st.column_config.TextColumn(
                    "Carrera", disabled=True, width="small",
                ),
                "carrera_nombre": st.column_config.TextColumn(
                    "Nombre Carrera", disabled=True, width="medium",
                ),
                "plan_nombre": st.column_config.TextColumn(
                    "Plan", disabled=True, width="medium",
                ),
                "anio_plan": st.column_config.NumberColumn(
                    "Anio", min_value=1, max_value=6, step=1, width="small",
                ),
                "cuatrimestre_display": (
                    st.column_config.TextColumn(
                        "Cuatrimestre", disabled=True, width="small",
                    )
                    if is_anual
                    else st.column_config.SelectboxColumn(
                        "Cuatrimestre", options=["1C", "2C"], width="small",
                    )
                ),
            }

            display_cols = [
                "carrera_codigo", "carrera_nombre", "plan_nombre",
                "anio_plan", "cuatrimestre_display",
            ]

            edited_df = st.data_editor(
                df[display_cols],
                column_config=column_config,
                use_container_width=True,
                num_rows="fixed",
                key=f"{key}_table",
                hide_index=True,
            )

            if not df[display_cols].equals(edited_df):
                col1, col2 = st.columns([1, 4])
                with col1:
                    if st.button("Guardar Cambios", key=f"{key}_save"):
                        try:
                            if is_anual:
                                edited_df["cuatrimestre_plan"] = "anual"
                            else:
                                edited_df["cuatrimestre_plan"] = edited_df["cuatrimestre_display"]

                            edited_df["carrera_codigo"] = df["carrera_codigo"]
                            edited_df["plan_estudio_id"] = df["plan_estudio_id"]

                            MateriaCarreraEditor._save_changes(session, edited_df)
                            st.success("Cambios guardados")
                            st.rerun()
                        except Exception as e:
                            st.error(f"Error al guardar: {str(e)}")
                with col2:
                    st.caption("Se detectaron cambios en anio o cuatrimestre")

            st.markdown("#### Desasociar Carrera")
            # Use plan_estudio_id as option key to handle same carrera in
            # different plan versions correctly.
            remove_options = {
                row["plan_estudio_id"]: (
                    f"{row['carrera_codigo']} - {row['carrera_nombre']}"
                    f" ({row['plan_nombre']})"
                )
                for _, row in df.iterrows()
            }
            ids_to_remove = st.multiselect(
                "Seleccione carreras para desasociar",
                options=list(remove_options.keys()),
                format_func=lambda x: remove_options[x],
                key=f"{key}_remove",
            )

            if ids_to_remove:
                if st.button("Desasociar Seleccionadas", key=f"{key}_remove_btn"):
                    try:
                        for pe_id in ids_to_remove:
                            row = df[df["plan_estudio_id"] == pe_id].iloc[0]
                            materia_service.remove_carrera(
                                session, materia_codigo,
                                row["carrera_codigo"],
                                plan_version_id=row["plan_version_id"],
                            )
                        st.success(f"{len(ids_to_remove)} carrera(s) desasociada(s)")
                        st.rerun()
                    except Exception as e:
                        st.error(f"Error: {str(e)}")

        st.markdown("#### Asociar Nueva Carrera")
        MateriaCarreraEditor._render_add_association(
            session, materia_codigo, plan_version_id, key,
        )

    @staticmethod
    def _get_associations(
        session: Session,
        materia_codigo: str,
        plan_version_id: str = None,
    ) -> List[Dict[str, Any]]:
        """Get current associations with carrera details.

        If plan_version_id is None, returns associations across all plan
        versions.
        """
        from src.database.models import CarreraDB, PlanCarreraVersionDB

        statement = (
            select(
                PlanEstudioDB.id,
                PlanEstudioDB.carrera_codigo,
                CarreraDB.nombre,
                PlanEstudioDB.anio_plan,
                PlanEstudioDB.cuatrimestre_plan,
                PlanCarreraVersionDB.id,
                PlanCarreraVersionDB.nombre,
            )
            .join(CarreraDB, PlanEstudioDB.carrera_codigo == CarreraDB.codigo)
            .join(
                PlanCarreraVersionDB,
                PlanEstudioDB.plan_version_id == PlanCarreraVersionDB.id,
            )
            .where(PlanEstudioDB.materia_codigo == materia_codigo)
        )
        if plan_version_id is not None:
            statement = statement.where(
                PlanEstudioDB.plan_version_id == plan_version_id,
            )
        statement = statement.order_by(
            PlanEstudioDB.carrera_codigo,
            PlanEstudioDB.anio_plan,
            PlanEstudioDB.cuatrimestre_plan,
        )

        results = session.exec(statement).all()

        return [
            {
                "plan_estudio_id": pe_id,
                "carrera_codigo": carrera_codigo,
                "carrera_nombre": carrera_nombre,
                "anio_plan": anio,
                "cuatrimestre_plan": cuatri,
                "plan_version_id": pv_id,
                "plan_nombre": pv_nombre,
            }
            for pe_id, carrera_codigo, carrera_nombre, anio, cuatri, pv_id, pv_nombre
            in results
        ]

    @staticmethod
    def _save_changes(session: Session, edited_df: pd.DataFrame) -> None:
        """Save changes to associations using the PlanEstudioDB surrogate id."""
        for _, row in edited_df.iterrows():
            link = session.get(PlanEstudioDB, row["plan_estudio_id"])
            if link:
                link.anio_plan = int(row["anio_plan"])
                link.cuatrimestre_plan = str(row["cuatrimestre_plan"])
                session.add(link)
        session.commit()

    @staticmethod
    def _render_add_association(
        session: Session,
        materia_codigo: str,
        plan_version_id: str = None,
        key: str = "materia_carrera_editor",
    ) -> None:
        """Render form to add new association.

        If plan_version_id is None, auto-selects the most recent plan
        version for the chosen carrera.
        """
        from src.database.models import PlanCarreraVersionDB

        materia = materia_service.get(session, materia_codigo)
        is_anual = materia and materia.periodo == "anual"

        all_carreras = carrera_service.get_all(session)
        current_carreras = materia_service.get_carreras(session, materia_codigo)
        current_codigos = {c.codigo for c in current_carreras}

        available_carreras = [c for c in all_carreras if c.codigo not in current_codigos]

        if not available_carreras:
            st.info("Todas las carreras ya estan asociadas a esta materia.")
            return

        with st.form(key=f"{key}_add_form"):
            if is_anual:
                col1, col2 = st.columns([3, 1])
            else:
                col1, col2, col3 = st.columns([2, 1, 1])

            with col1:
                selected_carrera = st.selectbox(
                    "Carrera",
                    options=[c.codigo for c in available_carreras],
                    format_func=lambda x: f"{x} - {next((c.nombre for c in available_carreras if c.codigo == x), '')}",
                )

            with col2:
                anio = st.number_input("Anio", min_value=1, max_value=6, value=1, step=1)

            if is_anual:
                cuatrimestre = "anual"
                st.caption("Cuatrimestre: Anual")
            else:
                with col3:
                    cuatrimestre = st.selectbox("Cuatrimestre", options=["1C", "2C"])

            submitted = st.form_submit_button("Asociar")

            if submitted:
                try:
                    # Resolve plan_version_id if not provided
                    pv_id = plan_version_id
                    if pv_id is None:
                        pv = session.exec(
                            select(PlanCarreraVersionDB)
                            .where(
                                PlanCarreraVersionDB.carrera_codigo
                                == selected_carrera,
                            )
                            .order_by(
                                PlanCarreraVersionDB.fecha_creacion.desc(),
                            )
                        ).first()
                        if pv is None:
                            st.error(
                                f"No se encontro plan de estudios para "
                                f"la carrera '{selected_carrera}'"
                            )
                            return
                        pv_id = pv.id

                    materia_service.add_carrera(
                        session, materia_codigo, selected_carrera,
                        plan_version_id=pv_id,
                        anio_plan=anio,
                        cuatrimestre_plan=cuatrimestre,
                    )
                    st.success(f"Carrera {selected_carrera} asociada")
                    st.rerun()
                except Exception as e:
                    st.error(f"Error: {str(e)}")
