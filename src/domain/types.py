"""Common type aliases for the domain model."""

from typing import NewType

# Problem Domain Type Aliases
Codigo = NewType("Codigo", str)  # Generic code identifier
CodigoMateria = NewType("CodigoMateria", str)  # Subject code (e.g., "MAT101")
CodigoAula = NewType("CodigoAula", str)  # Classroom code (e.g., "AULA-101")

# Solution Domain Type Aliases
AsignacionId = NewType("AsignacionId", str)
ComisionId = NewType("ComisionId", str)
HorarioId = NewType("HorarioId", str)

# Enum-like constants for days of the week
DiaSemana = NewType("DiaSemana", str)

DIAS_SEMANA = frozenset([
    "Lunes",
    "Martes",
    "Miércoles",
    "Jueves",
    "Viernes",
    "Sábado",
])
