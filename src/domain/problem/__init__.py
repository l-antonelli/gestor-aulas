"""Problem Domain Entities.

Contains: Materia, Comision, Horario, Aula, Carrera
"""

from src.domain.problem.materia import Materia
from src.domain.problem.comision import Comision
from src.domain.problem.horario import Horario
from src.domain.problem.aula import Aula, TipoAula
from src.domain.problem.carrera import Carrera

__all__ = [
    "Materia",
    "Comision",
    "Horario",
    "Aula",
    "TipoAula",
    "Carrera",
]
