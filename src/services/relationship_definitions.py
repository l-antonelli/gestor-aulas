"""Define all entity relationships in the system."""

from src.domain.problem.materia import Materia
from src.domain.problem.comision import Comision
from src.domain.problem.clase import Clase
from src.domain.problem.alumno import Alumno
from src.domain.solution.inscripcion import Inscripcion
from src.domain.solution.asistencia import Asistencia
from src.domain.solution.asignacion_aula import AsignacionAula

from src.services.relationship_metadata import RelationshipMetadata
from src.services.relationship_registry import RelationshipRegistry


def register_all_relationships() -> None:
    """
    Register all entity relationships in the system.
    
    This function defines and registers all one-to-many relationships
    between domain entities, including cascading behavior and display configuration.
    """
    
    # Materia → Comisión relationship
    materia_comision = RelationshipMetadata(
        parent_model=Materia,
        child_model=Comision,
        foreign_key_field="materia_codigo",
        display_fields=["id", "nombre", "numero", "cupo"],
        search_fields=["nombre", "numero"],
        cascading_create=True,
        cascading_create_defaults={
            "nombre": "Comisión Única",
            "numero": 1,
        },
        delete_behavior="cascade",
        validation_rules=[],
    )
    RelationshipRegistry.register_relationship(materia_comision)
    
    # Comisión → Clase relationship
    comision_clase = RelationshipMetadata(
        parent_model=Comision,
        child_model=Clase,
        foreign_key_field="comision_id",
        display_fields=["id", "dia", "horario_id"],
        search_fields=["dia"],
        cascading_create=False,
        cascading_create_defaults={},
        delete_behavior="cascade",
        validation_rules=[],
    )
    RelationshipRegistry.register_relationship(comision_clase)
    
    # Alumno → Inscripción relationship
    alumno_inscripcion = RelationshipMetadata(
        parent_model=Alumno,
        child_model=Inscripcion,
        foreign_key_field="alumno_legajo",
        display_fields=["id", "comision_id", "fecha_inscripcion", "activa"],
        search_fields=["comision_id"],
        cascading_create=False,
        cascading_create_defaults={},
        delete_behavior="cascade",
        validation_rules=[],
    )
    RelationshipRegistry.register_relationship(alumno_inscripcion)
    
    # Clase → Asistencia relationship
    clase_asistencia = RelationshipMetadata(
        parent_model=Clase,
        child_model=Asistencia,
        foreign_key_field="clase_id",
        display_fields=["id", "alumno_legajo", "fecha", "presente"],
        search_fields=["alumno_legajo"],
        cascading_create=False,
        cascading_create_defaults={},
        delete_behavior="cascade",
        validation_rules=[],
    )
    RelationshipRegistry.register_relationship(clase_asistencia)
    
    # Clase → AsignacionAula relationship
    clase_asignacion = RelationshipMetadata(
        parent_model=Clase,
        child_model=AsignacionAula,
        foreign_key_field="clase_id",
        display_fields=["id", "aula_id", "fecha_asignacion", "vigente"],
        search_fields=["aula_id"],
        cascading_create=False,
        cascading_create_defaults={},
        delete_behavior="cascade",
        validation_rules=[],
    )
    RelationshipRegistry.register_relationship(clase_asignacion)


# Auto-register relationships when module is imported
register_all_relationships()
