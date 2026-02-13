"""Gestion de Horarios - Carga por archivo y manual."""

import streamlit as st
from datetime import time, timedelta, datetime
from src.database.connection import get_session, init_db
from src.database.models import ConfiguracionHoraria
from src.database.crud import (
    horario_crud, comision_crud, materia_crud,
    get_or_create_config, update_config
)
from src.services.horario_loading_service import HorarioInput, load_horarios_from_data
from src.services.horario_file_parser import parse_horarios_file

init_db()

st.set_page_config(page_title="Horarios", page_icon="📅", layout="wide")
st.title("📅 Gestion de Horarios")

DIAS_SEMANA = ["Lunes", "Martes", "Miércoles", "Jueves", "Viernes", "Sábado"]


def generate_time_slots(config: ConfiguracionHoraria) -> list[time]:
    """Generate valid time slots based on configuration."""
    slots = []
    current = datetime.combine(datetime.today(), config.hora_inicio_operativo)
    end = datetime.combine(datetime.today(), config.hora_fin_operativo)
    delta = timedelta(minutes=config.granularidad_minutos)
    while current <= end:
        slots.append(current.time())
        current += delta
    return slots


# Tabs
tab_config, tab_cargar, tab_horarios, tab_grilla = st.tabs([
    "⚙️ Configuracion",
    "📥 Cargar Horarios",
    "📋 Horarios Cargados",
    "📊 Vista Grilla"
])

# =============================================================================
# Tab 1: Configuracion Global
# =============================================================================
with tab_config:
    st.subheader("Configuracion de Parametros Horarios")

    with next(get_session()) as session:
        config = get_or_create_config(session)

    with st.form("config_form"):
        col1, col2 = st.columns(2)

        with col1:
            granularidad = st.selectbox(
                "Granularidad (minutos)",
                options=[15, 20, 30, 45, 60],
                index=[15, 20, 30, 45, 60].index(config.granularidad_minutos),
                help="Unidad minima de tiempo para asignacion"
            )
            hora_inicio = st.time_input(
                "Hora inicio operativo",
                value=config.hora_inicio_operativo
            )

        with col2:
            dias_actuales = config.dias_operativos.split(",")
            dias_seleccionados = st.multiselect(
                "Dias operativos",
                options=DIAS_SEMANA,
                default=[d for d in dias_actuales if d in DIAS_SEMANA]
            )
            hora_fin = st.time_input(
                "Hora fin operativo",
                value=config.hora_fin_operativo
            )

        if st.form_submit_button("💾 Guardar Configuracion", type="primary"):
            new_config = ConfiguracionHoraria(
                id=1,
                granularidad_minutos=granularidad,
                hora_inicio_operativo=hora_inicio,
                hora_fin_operativo=hora_fin,
                dias_operativos=",".join(dias_seleccionados)
            )
            with next(get_session()) as session:
                update_config(session, new_config)
            st.success("Configuracion guardada")
            st.rerun()

    st.info(f"Granularidad: cada {config.granularidad_minutos} min")


# =============================================================================
# Tab 2: Cargar Horarios (archivo + manual)
# =============================================================================
with tab_cargar:
    st.subheader("Cargar Horarios")
    st.caption("Las comisiones se crean automaticamente al cargar horarios")

    subtab_file, subtab_manual = st.tabs(["📄 Desde Archivo", "✏️ Entrada Manual"])

    # --- File upload ---
    with subtab_file:
        st.markdown("Suba un archivo CSV o Excel con columnas: "
                     "`codigo_materia`, `comision`, `dia`, `hora_inicio`, `hora_fin`")

        uploaded_file = st.file_uploader(
            "Seleccionar archivo",
            type=["csv", "xlsx", "xls"],
            key="horario_file_upload"
        )

        if uploaded_file is not None:
            entries, parse_errors = parse_horarios_file(uploaded_file)

            if parse_errors:
                st.warning("Errores de parseo:")
                for err in parse_errors:
                    st.text(f"  - {err}")

            if entries:
                st.markdown(f"**{len(entries)} horarios detectados:**")
                preview = [
                    {
                        "Materia": e.codigo_materia,
                        "Comision": e.comision_nombre,
                        "Dia": e.dia,
                        "Inicio": e.hora_inicio.strftime("%H:%M"),
                        "Fin": e.hora_fin.strftime("%H:%M"),
                    }
                    for e in entries
                ]
                st.dataframe(preview, use_container_width=True, hide_index=True)

                if st.button("Confirmar Carga", type="primary", key="confirm_upload"):
                    with next(get_session()) as session:
                        result = load_horarios_from_data(session, entries)

                    st.success(
                        f"Carga completada: {result.horarios_created} horarios creados, "
                        f"{result.comisiones_created} comisiones nuevas"
                    )
                    if result.errors:
                        st.warning("Errores durante la carga:")
                        for err in result.errors:
                            st.text(f"  - {err}")
                    st.rerun()

    # --- Manual entry ---
    with subtab_manual:
        with next(get_session()) as session:
            config = get_or_create_config(session)
            all_materias = materia_crud.get_all(session)

        if not all_materias:
            st.warning("No hay materias. Cree materias primero.")
        else:
            with st.form("manual_horario_form"):
                materia_sel = st.selectbox(
                    "Materia",
                    options=[m.codigo for m in all_materias],
                    format_func=lambda x: f"{x} - {next((m.nombre for m in all_materias if m.codigo == x), '')}",
                )
                comision_nombre = st.text_input("Nombre de Comision", value="Comision Unica")

                dias_config = config.dias_operativos.split(",")
                dia = st.selectbox("Dia", options=[d for d in DIAS_SEMANA if d in dias_config])

                time_slots = generate_time_slots(config)
                hora_inicio_sel = st.selectbox(
                    "Hora inicio",
                    options=time_slots[:-1],
                    format_func=lambda t: t.strftime("%H:%M")
                )
                hora_fin_sel = st.selectbox(
                    "Hora fin",
                    options=time_slots[1:],
                    index=min(3, len(time_slots) - 2),
                    format_func=lambda t: t.strftime("%H:%M")
                )

                if st.form_submit_button("Crear Horario"):
                    if hora_fin_sel <= hora_inicio_sel:
                        st.error("Hora fin debe ser posterior a hora inicio")
                    else:
                        entry = HorarioInput(
                            codigo_materia=materia_sel,
                            comision_nombre=comision_nombre.strip() or "Comision Unica",
                            dia=dia,
                            hora_inicio=hora_inicio_sel,
                            hora_fin=hora_fin_sel,
                        )
                        with next(get_session()) as session:
                            result = load_horarios_from_data(session, [entry])

                        if result.errors:
                            for err in result.errors:
                                st.error(err)
                        else:
                            msg = f"Horario creado"
                            if result.comisiones_created:
                                msg += f" (comision '{comision_nombre}' creada automaticamente)"
                            st.success(msg)
                            st.rerun()


# =============================================================================
# Tab 3: Horarios Cargados
# =============================================================================
with tab_horarios:
    st.subheader("Horarios Cargados")

    with next(get_session()) as session:
        horarios = horario_crud.get_all(session)

        if not horarios:
            st.info("No hay horarios cargados.")
        else:
            horarios_data = []
            for h in horarios:
                materia = materia_crud.get(session, h.codigo_materia) if h.codigo_materia else None
                horarios_data.append({
                    "ID": h.id,
                    "Materia": materia.nombre if materia else h.codigo_materia,
                    "Comision": h.comision_id,
                    "Dia": h.dia,
                    "Horario": f"{h.hora_inicio.strftime('%H:%M')}-{h.hora_fin.strftime('%H:%M')}",
                })

            day_order = {d: i for i, d in enumerate(DIAS_SEMANA)}
            horarios_data.sort(key=lambda x: (day_order.get(x["Dia"], 99), x["Horario"]))
            st.dataframe(horarios_data, use_container_width=True, hide_index=True)

            # Delete section
            st.divider()
            col1, col2 = st.columns([3, 1])
            with col1:
                id_delete = st.selectbox(
                    "Eliminar horario",
                    options=[h.id for h in horarios],
                    key="del_horario"
                )
            with col2:
                st.write("")
                st.write("")
                if st.button("🗑️ Eliminar", key="btn_del_horario"):
                    horario_crud.delete(session, id_delete)
                    st.rerun()


# =============================================================================
# Tab 4: Vista Grilla Semanal
# =============================================================================
with tab_grilla:
    st.subheader("Cronograma Semanal")

    with next(get_session()) as session:
        config = get_or_create_config(session)
        horarios = horario_crud.get_all(session)

        if not horarios:
            st.info("No hay horarios para mostrar.")
        else:
            dias_config = config.dias_operativos.split(",")
            grid_data = {dia: [] for dia in dias_config}

            for h in horarios:
                materia = materia_crud.get(session, h.codigo_materia) if h.codigo_materia else None
                if h.dia in grid_data:
                    grid_data[h.dia].append({
                        "hora": h.hora_inicio,
                        "texto": (
                            f"{h.hora_inicio.strftime('%H:%M')}-{h.hora_fin.strftime('%H:%M')}\n"
                            f"{materia.nombre if materia else 'N/A'}\n({h.comision_id})"
                        )
                    })

            for dia in grid_data:
                grid_data[dia].sort(key=lambda x: x["hora"])

            cols = st.columns(len(dias_config))
            for i, dia in enumerate(dias_config):
                with cols[i]:
                    st.markdown(f"**{dia}**")
                    if grid_data[dia]:
                        for item in grid_data[dia]:
                            st.code(item["texto"], language=None)
                    else:
                        st.caption("Sin horarios")
