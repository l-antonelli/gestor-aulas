"""Problem Domain Entities.

Contains: Alumno, Materia, Comision, Clase, Aula, HorarioCronograma
"""

from src.domain.problem.alumno import Alumno
from src.domain.problem.materia import Materia
from src.domain.problem.comision import Comision
from src.domain.problem.horario_cronograma import HorarioCronograma
from src.domain.problem.aula import Aula, TipoAula
from src.domain.problem.clase import Clase

__all__ = [
    "Alumno",
    "Materia",
    "Comision",
    "HorarioCronograma",
    "Aula",
    "TipoAula",
    "Clase",
]
