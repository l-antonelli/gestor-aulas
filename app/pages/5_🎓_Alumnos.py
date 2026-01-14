"""
🚧 PÁGINA DEPRECADA - Gestión de Alumnos

Esta página ha sido deprecada en la primera iteración del sistema.

Razón: Para el objetivo de asignación de aulas, no es necesario registrar
alumnos individuales. Se utilizará un dataset agregado con la cantidad de
inscriptos por materia/comisión por ciclo lectivo.

Las entidades Alumno permanecen en el modelo de datos para futuras iteraciones.
"""

import streamlit as st

st.set_page_config(page_title="Alumnos (Deprecado)", page_icon="🎓", layout="wide")

st.title("🎓 Gestión de Alumnos")
st.warning("🚧 **Página Deprecada**")

st.markdown("""
### Esta funcionalidad no está disponible en la primera iteración

**Razón:** Para el objetivo de asignación óptima de aulas, no es necesario 
registrar cada alumno individualmente. 

En su lugar, el sistema utilizará:
- Datos agregados de inscriptos por materia/comisión
- Dataset provisto con totales de inscripción por ciclo lectivo

### Próximos pasos
Las entidades `Alumno` permanecen en el modelo de datos y podrán ser 
habilitadas en futuras iteraciones si se requiere:
- Tracking individual de asistencia
- Predicción de ocupación basada en historial personal
- Integración con sistemas de gestión académica (SIU Guaraní)
""")

st.info("📊 Para gestionar datos de inscripción agregados, utilice la sección de **Comisiones** donde puede especificar el cupo esperado.")
