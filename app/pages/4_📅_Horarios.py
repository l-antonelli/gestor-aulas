"""Gestión de Horarios y Cronograma."""

import streamlit as st
from datetime import time, timedelta, datetime
from src.database.connection import get_session
from src.database.models import HorarioCronogramaDB, ClaseDB, ComisionDB, ConfiguracionHoraria
from src.database.crud import (
    horario_crud, clase_crud, comision_crud, materia_crud,
    get_or_create_config, update_config
)
import uuid

st.set_page_config(page_title="Horarios", page_icon="📅", layout="wide")
st.title("📅 Gestión de Horarios y Cronograma")

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
tab_config, tab_horarios, tab_clases, tab_grilla = st.tabs([
    "⚙️ Configuración", 
    "🕐 Franjas Horarias", 
    "📚 Asignar Clases",
    "📊 Vista Grilla"
])

# =============================================================================
# Tab 1: Configuración Global
# =============================================================================
with tab_config:
    st.subheader("Configuración de Parámetros Horarios")
    
    with next(get_session()) as session:
        config = get_or_create_config(session)
    
    with st.form("config_form"):
        col1, col2 = st.columns(2)
        
        with col1:
            granularidad = st.selectbox(
                "Granularidad (minutos)",
                options=[15, 20, 30, 45, 60],
                index=[15, 20, 30, 45, 60].index(config.granularidad_minutos),
                help="Unidad mínima de tiempo para asignación"
            )
            
            hora_inicio = st.time_input(
                "Hora inicio operativo",
                value=config.hora_inicio_operativo
            )
        
        with col2:
            dias_actuales = config.dias_operativos.split(",")
            dias_seleccionados = st.multiselect(
                "Días operativos",
                options=DIAS_SEMANA,
                default=[d for d in dias_actuales if d in DIAS_SEMANA]
            )
            
            hora_fin = st.time_input(
                "Hora fin operativo", 
                value=config.hora_fin_operativo
            )
        
        if st.form_submit_button("💾 Guardar Configuración", type="primary"):
            new_config = ConfiguracionHoraria(
                id=1,
                granularidad_minutos=granularidad,
                hora_inicio_operativo=hora_inicio,
                hora_fin_operativo=hora_fin,
                dias_operativos=",".join(dias_seleccionados)
            )
            with next(get_session()) as session:
                update_config(session, new_config)
            st.success("Configuración guardada")
            st.rerun()
    
    st.info(f"Los horarios válidos son: :00, :15, :30, :45 (cada {config.granularidad_minutos} min)")

# =============================================================================
# Tab 2: Franjas Horarias
# =============================================================================
with tab_horarios:
    st.subheader("Definir Franjas Horarias")
    
    with next(get_session()) as session:
        config = get_or_create_config(session)
        horarios = horario_crud.get_all(session)
    
    col_list, col_create = st.columns([2, 1])
    
    with col_list:
        if not horarios:
            st.info("No hay franjas horarias definidas.")
        else:
            data = [
                {
                    "ID": h.id,
                    "Día": h.dia_semana,
                    "Inicio": h.hora_inicio.strftime("%H:%M"),
                    "Fin": h.hora_fin.strftime("%H:%M"),
                }
                for h in horarios
            ]
            day_order = {d: i for i, d in enumerate(DIAS_SEMANA)}
            data.sort(key=lambda x: (day_order.get(x["Día"], 99), x["Inicio"]))
            st.dataframe(data, use_container_width=True, hide_index=True)
    
    with col_create:
        st.markdown("**Nueva Franja**")
        time_slots = generate_time_slots(config)
        
        with st.form("create_horario"):
            dias_config = config.dias_operativos.split(",")
            dia = st.selectbox("Día", options=[d for d in DIAS_SEMANA if d in dias_config])
            
            hora_inicio = st.selectbox(
                "Hora inicio",
                options=time_slots[:-1],
                format_func=lambda t: t.strftime("%H:%M")
            )
            hora_fin = st.selectbox(
                "Hora fin",
                options=time_slots[1:],
                index=min(3, len(time_slots)-2),  # Default ~1 hour later
                format_func=lambda t: t.strftime("%H:%M")
            )
            
            if st.form_submit_button("➕ Crear"):
                if hora_fin <= hora_inicio:
                    st.error("Hora fin debe ser posterior a hora inicio")
                else:
                    horario_id = f"{dia[:3].upper()}-{hora_inicio.strftime('%H%M')}"
                    horario = HorarioCronogramaDB(
                        id=horario_id,
                        dia_semana=dia,
                        hora_inicio=hora_inicio,
                        hora_fin=hora_fin
                    )
                    try:
                        with next(get_session()) as session:
                            horario_crud.create(session, horario)
                        st.success(f"Franja '{horario_id}' creada")
                        st.rerun()
                    except Exception as e:
                        st.error(f"Error: {e}")
    
    # Delete section
    if horarios:
        st.divider()
        col1, col2 = st.columns([3, 1])
        with col1:
            id_delete = st.selectbox("Eliminar franja", options=[h.id for h in horarios])
        with col2:
            st.write("")  # Spacing
            st.write("")
            if st.button("🗑️ Eliminar"):
                with next(get_session()) as session:
                    horario_crud.delete(session, id_delete)
                st.rerun()


# =============================================================================
# Tab 3: Asignar Clases a Horarios
# =============================================================================
with tab_clases:
    st.subheader("Asignar Comisiones a Franjas Horarias")
    st.caption("Cada asignación crea una Clase (instancia de dictado)")
    
    with next(get_session()) as session:
        comisiones = comision_crud.get_all(session)
        horarios = horario_crud.get_all(session)
        clases = clase_crud.get_all(session)
        
        # Build display data
        clases_data = []
        for c in clases:
            comision = comision_crud.get(session, c.comision_id)
            materia = materia_crud.get(session, comision.materia_codigo) if comision else None
            horario = horario_crud.get(session, c.horario_id)
            clases_data.append({
                "ID": c.id,
                "Materia": materia.nombre if materia else "N/A",
                "Comisión": c.comision_id,
                "Día": c.dia,
                "Horario": f"{horario.hora_inicio.strftime('%H:%M')}-{horario.hora_fin.strftime('%H:%M')}" if horario else "N/A",
            })
    
    col_list, col_create = st.columns([2, 1])
    
    with col_list:
        if not clases_data:
            st.info("No hay clases asignadas.")
        else:
            day_order = {d: i for i, d in enumerate(DIAS_SEMANA)}
            clases_data.sort(key=lambda x: (day_order.get(x["Día"], 99), x["Horario"]))
            st.dataframe(clases_data, use_container_width=True, hide_index=True)
    
    with col_create:
        st.markdown("**Nueva Clase**")
        
        if not comisiones:
            st.warning("Primero creá comisiones")
        elif not horarios:
            st.warning("Primero creá franjas horarias")
        else:
            with st.form("create_clase"):
                # Build comision options with materia name
                with next(get_session()) as session:
                    comision_options = []
                    for c in comisiones:
                        materia = materia_crud.get(session, c.materia_codigo)
                        label = f"{c.id} ({materia.nombre if materia else c.materia_codigo})"
                        comision_options.append((c.id, label))
                
                comision_id = st.selectbox(
                    "Comisión",
                    options=[c[0] for c in comision_options],
                    format_func=lambda x: next((c[1] for c in comision_options if c[0] == x), x)
                )
                
                horario_id = st.selectbox(
                    "Franja horaria",
                    options=[h.id for h in horarios],
                    format_func=lambda x: next(
                        (f"{h.dia_semana} {h.hora_inicio.strftime('%H:%M')}-{h.hora_fin.strftime('%H:%M')}" 
                         for h in horarios if h.id == x), x
                    )
                )
                
                # Get dia from horario
                horario_sel = next((h for h in horarios if h.id == horario_id), None)
                dia = horario_sel.dia_semana if horario_sel else "Lunes"
                
                if st.form_submit_button("➕ Crear Clase"):
                    clase_id = f"CLS-{uuid.uuid4().hex[:8].upper()}"
                    clase = ClaseDB(
                        id=clase_id,
                        comision_id=comision_id,
                        horario_id=horario_id,
                        dia=dia
                    )
                    try:
                        with next(get_session()) as session:
                            clase_crud.create(session, clase)
                        st.success(f"Clase '{clase_id}' creada")
                        st.rerun()
                    except Exception as e:
                        st.error(f"Error: {e}")
    
    # Delete section
    if clases:
        st.divider()
        col1, col2 = st.columns([3, 1])
        with col1:
            id_delete = st.selectbox("Eliminar clase", options=[c.id for c in clases], key="del_clase")
        with col2:
            st.write("")
            st.write("")
            if st.button("🗑️ Eliminar", key="btn_del_clase"):
                with next(get_session()) as session:
                    clase_crud.delete(session, id_delete)
                st.rerun()

# =============================================================================
# Tab 4: Vista Grilla Semanal
# =============================================================================
with tab_grilla:
    st.subheader("Cronograma Semanal")
    
    with next(get_session()) as session:
        config = get_or_create_config(session)
        clases = clase_crud.get_all(session)
        
        if not clases:
            st.info("No hay clases para mostrar. Asigná comisiones a horarios en la pestaña anterior.")
        else:
            # Build grid data
            dias_config = config.dias_operativos.split(",")
            grid_data = {dia: [] for dia in dias_config}
            
            for c in clases:
                horario = horario_crud.get(session, c.horario_id)
                comision = comision_crud.get(session, c.comision_id)
                materia = materia_crud.get(session, comision.materia_codigo) if comision else None
                
                if horario and c.dia in grid_data:
                    grid_data[c.dia].append({
                        "hora": horario.hora_inicio,
                        "texto": f"{horario.hora_inicio.strftime('%H:%M')}-{horario.hora_fin.strftime('%H:%M')}\n{materia.nombre if materia else 'N/A'}\n({c.comision_id})"
                    })
            
            # Sort by time
            for dia in grid_data:
                grid_data[dia].sort(key=lambda x: x["hora"])
            
            # Display as columns
            cols = st.columns(len(dias_config))
            for i, dia in enumerate(dias_config):
                with cols[i]:
                    st.markdown(f"**{dia}**")
                    if grid_data[dia]:
                        for item in grid_data[dia]:
                            st.code(item["texto"], language=None)
                    else:
                        st.caption("Sin clases")
