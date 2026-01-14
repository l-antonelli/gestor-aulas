"""
🚧 PÁGINA DEPRECADA - Gestión de Profesores

Esta página ha sido deprecada en la primera iteración del sistema.

Razón: Los profesores no afectan la asignación de aulas. El problema de
optimización se centra en capacidad de aulas vs cantidad de alumnos,
no en la disponibilidad o preferencias de docentes.

Las entidades Profesor permanecen en el modelo de datos para futuras iteraciones.
"""

import streamlit as st

st.set_page_config(page_title="Profesores (Deprecado)", page_icon="👨‍🏫", layout="wide")

st.title("👨‍🏫 Gestión de Profesores")
st.warning("🚧 **Página Deprecada**")

st.markdown("""
### Esta funcionalidad no está disponible en la primera iteración

**Razón:** Los profesores no son una variable relevante para el problema de 
asignación óptima de aulas en esta primera iteración.

El algoritmo de asignación se enfoca en:
- ✅ Capacidad de aulas vs cantidad de alumnos inscriptos
- ✅ Disponibilidad horaria de aulas
- ✅ Restricciones de tipo de aula (teórica, laboratorio, etc.)
- ❌ ~~Preferencias o disponibilidad de docentes~~

### Próximos pasos
Las entidades `Profesor` permanecen en el modelo de datos y podrán ser 
habilitadas en futuras iteraciones si se requiere:
- Asignación de docentes a comisiones
- Restricciones de disponibilidad horaria por profesor
- Preferencias de aulas por docente
""")

st.info("ℹ️ La asignación de profesores a clases puede gestionarse fuera del sistema en esta iteración.")
