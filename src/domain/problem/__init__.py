"""Problem Domain Entities.

Contains: Alumno, Materia, Comision, Clase, Aula, HorarioCronograma, Carrera
"""

from src.domain.problem.alumno import Alumno
from src.domain.problem.materia import Materia
from src.domain.problem.comision import Comision
from src.domain.problem.horario_cronograma import HorarioCronograma
from src.domain.problem.aula import Aula, TipoAula
from src.domain.problem.clase import Clase
from src.domain.problem.carrera import Carrera

__all__ = [
    "Alumno",
    "Materia",
    "Comision",
    "HorarioCronograma",
    "Aula",
    "TipoAula",
    "Clase",
    "Carrera",
]
