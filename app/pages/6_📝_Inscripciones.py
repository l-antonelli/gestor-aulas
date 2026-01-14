"""
🚧 PÁGINA DEPRECADA - Gestión de Inscripciones

Esta página ha sido deprecada en la primera iteración del sistema.

Razón: Para el objetivo de asignación de aulas, no es necesario registrar
inscripciones individuales. Se utilizará un dataset agregado con la cantidad
de inscriptos por materia/comisión por ciclo lectivo.

Las entidades Inscripcion permanecen en el modelo de datos para futuras iteraciones.
"""

import streamlit as st

st.set_page_config(page_title="Inscripciones (Deprecado)", page_icon="📝", layout="wide")

st.title("📝 Gestión de Inscripciones")
st.warning("🚧 **Página Deprecada**")

st.markdown("""
### Esta funcionalidad no está disponible en la primera iteración

**Razón:** Para el objetivo de asignación óptima de aulas, no es necesario 
registrar cada inscripción individualmente.

En su lugar, el sistema utilizará:
- El campo `cupo` en cada **Comisión** para indicar la cantidad esperada de alumnos
- Datos agregados importados desde el sistema de gestión académica

### Próximos pasos
Las entidades `Inscripcion` permanecen en el modelo de datos y podrán ser 
habilitadas en futuras iteraciones si se requiere:
- Tracking detallado de inscripciones por alumno
- Análisis de patrones de inscripción
- Integración bidireccional con SIU Guaraní
""")

st.info("📊 Para especificar la cantidad de alumnos esperados, edite el campo **cupo** en cada Comisión.")
