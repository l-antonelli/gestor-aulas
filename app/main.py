"""
Sistema de Asignación de Aulas - Main Streamlit App

Run with: streamlit run app/main.py
"""

import streamlit as st
from src.database.connection import init_db

# Initialize database on first run
init_db()

st.set_page_config(
    page_title="Sistema de Asignación de Aulas",
    page_icon="🏫",
    layout="wide",
)

st.title("🏫 Sistema de Asignación de Aulas")
st.markdown("### FCEIA - Universidad Nacional de Rosario")

st.divider()

st.markdown("""
## Bienvenido

Este sistema permite gestionar la asignación óptima de aulas para el dictado de clases.

### Módulos disponibles

Usa el menú lateral para navegar entre las secciones:

- **📚 Materias**: Gestión de asignaturas académicas
- **👥 Comisiones**: División de materias en comisiones
- **🏛️ Aulas**: Gestión de espacios físicos
- **📅 Horarios**: Franjas horarias del cronograma
- **🎓 Alumnos**: Gestión de estudiantes
- **📝 Inscripciones**: Inscripción de alumnos a comisiones

### Estado del Sistema
""")

# Show quick stats
from src.database.connection import get_session
from src.database.models import MateriaDB, AulaDB, AlumnoDB, ComisionDB
from sqlmodel import select

with next(get_session()) as session:
    n_materias = len(list(session.exec(select(MateriaDB)).all()))
    n_aulas = len(list(session.exec(select(AulaDB)).all()))
    n_alumnos = len(list(session.exec(select(AlumnoDB)).all()))
    n_comisiones = len(list(session.exec(select(ComisionDB)).all()))

col1, col2, col3, col4 = st.columns(4)
col1.metric("Materias", n_materias)
col2.metric("Aulas", n_aulas)
col3.metric("Alumnos", n_alumnos)
col4.metric("Comisiones", n_comisiones)
