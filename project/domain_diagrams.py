"""
Diagramas de Entidad-Relación para el Sistema de Asignación de Aulas
=====================================================================

Este script genera los diagramas UML del dominio del problema y la solución
usando graphviz. Ejecutar este script para generar los diagramas PNG.

Uso:
    python domain_diagrams.py
"""

from graphviz import Digraph
from IPython.display import Image, display

# =============================================================================
# DOMINIO DEL PROBLEMA (COMPLETO)
# =============================================================================
# Todas las entidades de existencia real y sus relaciones

def crear_diagrama_problema_completo():
    """
    Diagrama de Entidad Relación (ER) Del Dominio del PROBLEMA
    
    Incluye todas las entidades de existencia real, incluyendo aquellas
    que no son directamente relevantes para el problema de asignación
    pero que forman parte del ecosistema universitario.
    """
    dot = Digraph(
        comment="Diagrama ER - Dominio del PROBLEMA (Completo)", 
        format="png"
    )
    dot.attr(rankdir="LR", fontsize="10")

    entidades = {
        "alumno": ["legajo", "email", "nombre", "dni"],
        "materia": ["codigo", "nombre", "cupo", "horas_semanales"],
        "profesor": ["id", "nombre", "email", "dni"],
        "aula": ["codigo", "capacidad", "tipo"],
        "horario_cronograma": ["dia_semana", "hora_inicio", "hora_fin"],
        "facultad": ["nombre", "direccion", "telefono"],
        "carrera": ["codigo", "nombre", "titulo_otorgado"],
        "clase": ["id", "comision_id", "horario_id", "dia"],
        "comision": ["id", "materia_codigo", "nombre", "numero", "cupo"]
    }

    # Agregar nodos
    for e, attrs in entidades.items():
        label = f"{e}|{{" + "|".join(attrs) + "}}"
        dot.node(e, label=label, shape="record")

    # Relaciones con cardinalidades
    # Relaciones M:M (problemáticas - causa de la complejidad)
    dot.edge("alumno", "materia", label="M ↔ M")  # Inscripciones
    dot.edge("materia", "profesor", label="M ↔ M")  # Dictado
    dot.edge("profesor", "clase", label="M ↔ M")  # Profesores por clase
    dot.edge("materia", "aula", label="M ↔ M")  # Uso de aulas (derivada)
    dot.edge("materia", "horario_cronograma", label="M ↔ M")  # Horarios (derivada)
    dot.edge("carrera", "materia", label="M ↔ M")  # Plan de estudios
    dot.edge("carrera", "alumno", label="M ↔ M")  # Inscripción a carrera
    dot.edge("horario_cronograma", "aula", label="M ↔ M")  # Disponibilidad
    dot.edge("facultad", "horario_cronograma", label="M ↔ M")  # Horarios de apertura
    dot.edge("comision", "profesor", label="M ↔ M")  # Profesores por comisión

    # Relaciones 1:M
    dot.edge("materia", "comision", label="1 ↔ M")  # División en comisiones
    dot.edge("comision", "clase", label="1 ↔ M")  # Clases de una comisión
    dot.edge("clase", "horario_cronograma", label="M ↔ 1")  # Horario de clase
    dot.edge("clase", "aula", label="M ↔ 1")  # Aula asignada
    dot.edge("aula", "facultad", label="M ↔ 1")  # Ubicación del aula

    return dot


# =============================================================================
# DOMINIO DEL PROBLEMA (DELIMITADO)
# =============================================================================
# Solo las entidades relevantes para el problema de asignación de aulas

def crear_diagrama_problema_delimitado():
    """
    Diagrama de Entidad Relación (ER) Del Dominio del PROBLEMA (Delimitado)
    
    Contiene únicamente las entidades relevantes para el problema de 
    asignación de aulas. Se excluyen:
    - Profesor: No afecta la capacidad ni disponibilidad de aulas
    - Carrera: La asignación es por Clase, no por Carrera
    - Facultad: Asumimos sede única (Pellegrini)
    - Relación Materia-Aula: Redundante, la asignación real es Clase-Aula
    """
    dot = Digraph(
        comment="Diagrama ER - Dominio del PROBLEMA (Delimitado)", 
        format="png"
    )
    dot.attr(rankdir="LR", fontsize="12")

    entidades = {
        "alumno": ["legajo", "email", "nombre", "dni"],
        "materia": ["codigo", "nombre", "cupo", "horas_semanales"],
        "comision": ["id", "materia_codigo", "nombre", "numero", "cupo"],
        "aula": ["codigo", "capacidad", "tipo"],
        "horario_cronograma": ["id", "dia_semana", "hora_inicio", "hora_fin"],
        "clase": ["id", "comision_id", "horario_id", "dia"],
    }

    # Agregar nodos con estilo
    for e, attrs in entidades.items():
        label = f"{e}|{{" + "|".join(attrs) + "}}"
        dot.node(e, label=label, shape="record", style="filled", fillcolor="lightblue")

    # Relaciones del dominio delimitado
    dot.edge("alumno", "materia", label="M ↔ M", color="red", fontcolor="red")  # Problemática
    dot.edge("materia", "comision", label="1 ↔ M")
    dot.edge("comision", "clase", label="1 ↔ M")
    dot.edge("clase", "horario_cronograma", label="M ↔ 1")
    dot.edge("clase", "aula", label="M ↔ 1", style="dashed")  # Asignación pendiente
    dot.edge("horario_cronograma", "aula", label="M ↔ M", color="red", fontcolor="red")  # Disponibilidad

    return dot


# =============================================================================
# DOMINIO DE LA SOLUCIÓN
# =============================================================================
# Entidades abstractas que resuelven las relaciones M:M

def crear_diagrama_solucion():
    """
    Diagrama de Entidad Relación (ER) Del Dominio de la SOLUCIÓN
    
    Las entidades del dominio de la solución son abstracciones que permiten
    gestionar las relaciones M:M del dominio del problema de manera efectiva.
    
    Derivación:
    - Inscripcion: Resuelve Alumno ↔ Materia/Comision
    - Asistencia: Resuelve Alumno ↔ Clase (para tracking)
    - AsignacionAula: Resuelve Clase ↔ Aula (el objetivo principal)
    """
    dot = Digraph(
        comment="Diagrama ER - Dominio de la SOLUCIÓN", 
        format="png"
    )
    dot.attr(rankdir="TB", fontsize="10")
    
    # Subgrafo para entidades del problema (referenciadas)
    with dot.subgraph(name='cluster_problema') as c:
        c.attr(label='Entidades del Problema (Delimitado)', style='dashed')
        c.node("alumno", "alumno|{legajo|...}", shape="record", style="filled", fillcolor="lightgray")
        c.node("materia", "materia|{codigo|...}", shape="record", style="filled", fillcolor="lightgray")
        c.node("comision", "comision|{id|materia_codigo|...}", shape="record", style="filled", fillcolor="lightgray")
        c.node("clase", "clase|{id|comision_id|horario_id|dia}", shape="record", style="filled", fillcolor="lightgray")
        c.node("aula", "aula|{codigo|capacidad|tipo}", shape="record", style="filled", fillcolor="lightgray")
        c.node("horario", "horario_cronograma|{id|dia_semana|...}", shape="record", style="filled", fillcolor="lightgray")
    
    # Subgrafo para entidades de la solución
    with dot.subgraph(name='cluster_solucion') as c:
        c.attr(label='Entidades de la Solución', style='solid', color='blue')
        c.node("inscripcion", 
               "inscripcion|{id|alumno_legajo|comision_id|fecha_inscripcion|activa}", 
               shape="record", style="filled", fillcolor="lightgreen")
        c.node("asistencia", 
               "asistencia|{id|alumno_legajo|clase_id|fecha|presente}", 
               shape="record", style="filled", fillcolor="lightgreen")
        c.node("asignacion_aula", 
               "asignacion_aula|{id|clase_id|aula_codigo|fecha_asignacion|vigente}", 
               shape="record", style="filled", fillcolor="lightyellow")

    # Relaciones de la solución
    dot.edge("inscripcion", "alumno", label="alumno_legajo")
    dot.edge("inscripcion", "comision", label="comision_id")
    dot.edge("asistencia", "alumno", label="alumno_legajo")
    dot.edge("asistencia", "clase", label="clase_id")
    dot.edge("asignacion_aula", "clase", label="clase_id", color="blue", penwidth="2")
    dot.edge("asignacion_aula", "aula", label="aula_codigo", color="blue", penwidth="2")
    
    # Relaciones del problema (contexto)
    dot.edge("materia", "comision", label="1:M", style="dotted")
    dot.edge("comision", "clase", label="1:M", style="dotted")
    dot.edge("clase", "horario", label="M:1", style="dotted")

    return dot


# =============================================================================
# DIAGRAMA INTEGRADO
# =============================================================================

def crear_diagrama_integrado():
    """
    Diagrama integrado mostrando la derivación del dominio del problema
    al dominio de la solución.
    """
    dot = Digraph(
        comment="Diagrama Integrado - Problema → Solución", 
        format="png"
    )
    dot.attr(rankdir="LR", fontsize="10", compound="true")
    
    # Entidades del problema
    with dot.subgraph(name='cluster_0') as c:
        c.attr(label='Dominio del Problema', style='rounded', bgcolor='lightyellow')
        c.node("p_alumno", "Alumno", shape="box")
        c.node("p_materia", "Materia", shape="box")
        c.node("p_comision", "Comision", shape="box")
        c.node("p_clase", "Clase", shape="box", style="bold")
        c.node("p_aula", "Aula", shape="box")
        c.node("p_horario", "HorarioCronograma", shape="box")
        
        c.edge("p_materia", "p_comision", label="1:M")
        c.edge("p_comision", "p_clase", label="1:M")
        c.edge("p_clase", "p_horario", label="M:1")
    
    # Entidades de la solución
    with dot.subgraph(name='cluster_1') as c:
        c.attr(label='Dominio de la Solución', style='rounded', bgcolor='lightgreen')
        c.node("s_inscripcion", "Inscripcion", shape="box", style="filled", fillcolor="white")
        c.node("s_asistencia", "Asistencia", shape="box", style="filled", fillcolor="white")
        c.node("s_asignacion", "AsignacionAula", shape="box", style="filled,bold", fillcolor="white")
    
    # Derivaciones (flechas de derivación)
    dot.edge("p_alumno", "s_inscripcion", label="resuelve\nAlumno↔Materia", style="dashed", color="blue")
    dot.edge("p_comision", "s_inscripcion", style="dashed", color="blue")
    
    dot.edge("p_alumno", "s_asistencia", label="resuelve\nAlumno↔Clase", style="dashed", color="blue")
    dot.edge("p_clase", "s_asistencia", style="dashed", color="blue")
    
    dot.edge("p_clase", "s_asignacion", label="resuelve\nClase↔Aula", style="dashed", color="red", penwidth="2")
    dot.edge("p_aula", "s_asignacion", style="dashed", color="red", penwidth="2")

    return dot


# =============================================================================
# MAIN
# =============================================================================

if __name__ == "__main__":
    import os
    
    output_dir = "project/diagrams"
    os.makedirs(output_dir, exist_ok=True)
    
    print("Generando diagramas...")
    
    # Generar cada diagrama
    diagramas = [
        ("problema_completo", crear_diagrama_problema_completo()),
        ("problema_delimitado", crear_diagrama_problema_delimitado()),
        ("solucion", crear_diagrama_solucion()),
        ("integrado", crear_diagrama_integrado()),
    ]
    
    for nombre, diagrama in diagramas:
        filepath = f"{output_dir}/{nombre}"
        diagrama.render(filepath, cleanup=True)
        print(f"  ✓ {filepath}.png")
    
    print("\n¡Diagramas generados exitosamente!")
    print(f"Ubicación: {output_dir}/")
