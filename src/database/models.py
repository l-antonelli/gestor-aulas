"""
SQLModel database models.

These models mirror the domain entities but add database persistence.
They use SQLModel which combines Pydantic validation with SQLAlchemy ORM.
"""

from sqlmodel import SQLModel, Field, Relationship
from typing import Optional
from datetime import date, datetime, time
import uuid


# =============================================================================
# Configuration Models
# =============================================================================

class ConfiguracionHoraria(SQLModel, table=True):
    """Configuración global de parámetros horarios."""
    __tablename__ = "configuracion_horaria"

    id: int = Field(default=1, primary_key=True)
    granularidad_minutos: int = Field(default=15, ge=5, le=60)
    hora_inicio_operativo: time = Field(default=time(7, 0))
    hora_fin_operativo: time = Field(default=time(23, 0))
    dias_operativos: str = Field(default="Lunes,Martes,Miércoles,Jueves,Viernes,Sábado")


# =============================================================================
# Link Tables (for M:M relationships)
# =============================================================================

class PlanCarreraVersionDB(SQLModel, table=True):
    """Version de un plan de estudios para una carrera."""
    __tablename__ = "plan_carrera_version"

    id: str = Field(primary_key=True)  # UUID
    carrera_codigo: str = Field(foreign_key="carreras.codigo", index=True)
    nombre: str  # e.g., "Plan Original", "Plan 2025"
    descripcion: str = Field(default="")
    fecha_creacion: date


class CicloPlanVersionDB(SQLModel, table=True):
    """Bridge: que versiones de plan aplican a un ciclo."""
    __tablename__ = "ciclo_plan_version"

    ciclo_id: str = Field(foreign_key="ciclos.id", primary_key=True)
    plan_version_id: str = Field(foreign_key="plan_carrera_version.id", primary_key=True)


class PlanEstudioDB(SQLModel, table=True):
    """Relacion M:M entre Materia y Carrera con ubicacion curricular, versionada."""
    __tablename__ = "plan_estudio"

    id: str = Field(default_factory=lambda: str(uuid.uuid4()), primary_key=True)
    plan_version_id: str = Field(foreign_key="plan_carrera_version.id", index=True)
    materia_codigo: str = Field(foreign_key="materias.codigo", index=True)
    carrera_codigo: str = Field(foreign_key="carreras.codigo", index=True)
    anio_plan: Optional[int] = Field(default=None, ge=1, le=6)
    cuatrimestre_plan: Optional[str] = Field(default=None)  # "1C", "2C", "Anual", or None
    correlativas: str = Field(default="")
    optativa: bool = Field(default=False)


class CorrelativaDB(SQLModel, table=True):
    """Correlativas: materias que deben aprobarse antes de cursar otra."""
    __tablename__ = "correlativas"

    carrera_codigo: str = Field(foreign_key="carreras.codigo", primary_key=True)
    materia_codigo: str = Field(foreign_key="materias.codigo", primary_key=True)
    materia_correlativa_codigo: str = Field(foreign_key="materias.codigo", primary_key=True)


class DictadoCicloDB(SQLModel, table=True):
    """Bridge table: links Dictado to Ciclo (M:N for anuales spanning 2 ciclos)."""
    __tablename__ = "dictado_ciclo"

    dictado_id: str = Field(foreign_key="dictados.id", primary_key=True)
    ciclo_id: str = Field(foreign_key="ciclos.id", primary_key=True)


# =============================================================================
# Solution Domain Models - Temporal
# =============================================================================

class CicloDB(SQLModel, table=True):
    """
    Período lectivo (cuatrimestre).
    Ejemplo: 2024-1C, 2024-2C
    """
    __tablename__ = "ciclos"

    id: str = Field(primary_key=True)  # Ej: "2024-1C", "2024-2C"
    anio: int = Field(ge=2020, le=2100)
    numero: int = Field(ge=1, le=2)  # 1 = primer cuatri, 2 = segundo cuatri
    fecha_inicio: date
    fecha_fin: date
    descripcion: str = Field(default="")

    # Relationships
    dictados: list["DictadoDB"] = Relationship(
        back_populates="ciclos",
        link_model=DictadoCicloDB
    )
    plan_versions: list["PlanCarreraVersionDB"] = Relationship(
        link_model=CicloPlanVersionDB
    )
    schedules: list["ScheduleDB"] = Relationship(back_populates="ciclo")
    planificaciones: list["PlanificacionCursadaDB"] = Relationship(back_populates="ciclo")


class DictadoDB(SQLModel, table=True):
    """
    Instancia de una materia ofrecida en un periodo.
    dictado_codigo es la display key: "MAT101-2025-2C" (cuatrimestral) o "MAT101-2025" (anual).
    Linked to ciclos via DictadoCicloDB bridge table.
    """
    __tablename__ = "dictados"

    id: str = Field(primary_key=True)  # UUID
    materia_codigo: str = Field(foreign_key="materias.codigo", index=True)
    dictado_codigo: str = Field(default="", index=True)  # Display key, e.g. "MAT101-2025-2C"
    inicio_dictado: Optional[date] = Field(default=None)
    fin_dictado: Optional[date] = Field(default=None)
    activo: bool = Field(default=True)
    # Override manual del flag `activo`. Cuando es None, el dictado se
    # alinea con la regla de recursado al apretar "Recalcular según
    # reglas". Cuando es True/False, fuerza el valor manualmente y la
    # ejecucion default de `recompute_activo_for_ciclo` lo respeta
    # (sólo se borra cuando el usuario activa el toggle "Pisar overrides
    # manuales").
    activo_override_manual: Optional[bool] = Field(default=None)
    virtual: bool = Field(default=False)

    # Relationships
    materia: Optional["MateriaDB"] = Relationship(back_populates="dictados")
    ciclos: list[CicloDB] = Relationship(
        back_populates="dictados",
        link_model=DictadoCicloDB
    )


# =============================================================================
# Problem Domain Models
# =============================================================================

class CarreraDB(SQLModel, table=True):
    """Carrera universitaria."""
    __tablename__ = "carreras"

    codigo: str = Field(primary_key=True, min_length=1)
    nombre: str = Field(min_length=1)
    titulo_otorgado: str = Field(default="")
    duracion_anios: int = Field(default=5, ge=1)
    cantidad_materias: Optional[int] = Field(default=None, ge=1)
    dicta_recursado: bool = Field(default=True)

    # Relationships
    materias: list["MateriaDB"] = Relationship(
        back_populates="carreras",
        link_model=PlanEstudioDB
    )
    plan_versions: list["PlanCarreraVersionDB"] = Relationship(
        sa_relationship_kwargs={"foreign_keys": "[PlanCarreraVersionDB.carrera_codigo]"}
    )


class MateriaDB(SQLModel, table=True):
    """Asignatura académica."""
    __tablename__ = "materias"

    codigo: str = Field(primary_key=True, min_length=1)
    nombre: str = Field(min_length=1)
    codigo_guarani: Optional[str] = Field(default=None)
    cupo: Optional[int] = Field(default=None, gt=0)
    horas_semanales: Optional[float] = Field(default=None, gt=0)
    horas_teoria: Optional[float] = Field(default=None, ge=0)
    horas_laboratorio: Optional[float] = Field(default=None, ge=0)
    periodo: str = Field(default="cuatrimestral")  # "anual" o "cuatrimestral"
    active: bool = Field(default=True)
    virtual: bool = Field(default=False)
    optativa: bool = Field(default=False)
    # Override del flag de recursado de la carrera. None = usar el de la
    # carrera (default). True/False fuerza el comportamiento para esta
    # materia, sin importar lo que diga la carrera.
    dicta_recursado: Optional[bool] = Field(default=None)

    # Relationships
    comisiones: list["ComisionDB"] = Relationship(back_populates="materia")
    carreras: list[CarreraDB] = Relationship(
        back_populates="materias",
        link_model=PlanEstudioDB
    )
    dictados: list[DictadoDB] = Relationship(back_populates="materia")


class ComisionDB(SQLModel, table=True):
    """División de una materia para distribuir alumnos."""
    __tablename__ = "comisiones"

    id: str = Field(primary_key=True)
    materia_codigo: str = Field(foreign_key="materias.codigo", index=True)
    dictado_id: Optional[str] = Field(default=None, foreign_key="dictados.id", index=True)
    plan_cursada_id: Optional[str] = Field(default=None, foreign_key="planificaciones_cursada.id", index=True)
    comision_key: str = Field(default="")  # "{dictado_codigo}-{numero:03d}"
    nombre: str = Field(default="Comisión Única")
    numero: int = Field(ge=1, default=1)
    cupo: int = Field(gt=0)
    descripcion: str = Field(default="")
    # Coeficiente de distribucion de inscriptos esperados entre comisiones
    # del mismo dictado. La suma de coef de comisiones de un mismo dictado
    # deberia ser ~1.0 (validacion en service layer, no constraint de DB).
    # Default 1.0 para que sea consistente cuando hay una sola comision.
    coef_asignacion: float = Field(default=1.0, ge=0, le=1)

    # Relationships
    materia: Optional[MateriaDB] = Relationship(back_populates="comisiones")
    plan_cursada: Optional["PlanificacionCursadaDB"] = Relationship(
        back_populates="comisiones",
        sa_relationship_kwargs={"foreign_keys": "[ComisionDB.plan_cursada_id]"}
    )
    horarios: list["HorarioDB"] = Relationship(back_populates="comision")


class SedeDB(SQLModel, table=True):
    """Sede física donde se ubican las aulas.

    Modelada como entidad propia (en vez de un string libre en `AulaDB.sede`)
    para permitir referenciarla desde otras entidades (por ejemplo, futuras
    restricciones del LP del tipo "esta materia solo se puede cursar en estas
    sedes"). El nombre es único globalmente.
    """
    __tablename__ = "sedes"

    id: str = Field(default_factory=lambda: str(uuid.uuid4()), primary_key=True)
    nombre: str = Field(min_length=1, unique=True, index=True)


class AulaDB(SQLModel, table=True):
    """Espacio físico donde se dictan las clases."""
    __tablename__ = "aulas"

    # ID opaco autogenerado. No se ingresa manualmente desde la UI.
    id: str = Field(default_factory=lambda: str(uuid.uuid4()), primary_key=True)
    sede_id: str = Field(foreign_key="sedes.id", index=True)
    # Código display editable. Único globalmente. Si el usuario no lo provee
    # al crear el aula, se autoderiva como "{sede.nombre}-{nombre}" con
    # espacios reemplazados por guiones.
    codigo_aula: str = Field(min_length=1, unique=True, index=True)
    nombre: str = Field(min_length=1)
    capacidad: int = Field(gt=0)
    tipo: str = Field(default="teorica")
    descripcion: str = Field(default="")

    # Relationships (none currently active)


class HorarioDB(SQLModel, table=True):
    """Horario de dictado: asocia una comisión con un día y rango horario."""
    __tablename__ = "horarios"

    id: str = Field(primary_key=True)
    comision_id: str = Field(foreign_key="comisiones.id", index=True)
    codigo_materia: str = Field(foreign_key="materias.codigo", index=True)
    dia: str = Field(index=True)
    hora_inicio: time
    hora_fin: time
    tipo_clase: Optional[str] = Field(default=None)  # "teorica", "laboratorio" o None (sin determinar)

    # Relationships
    comision: Optional[ComisionDB] = Relationship(back_populates="horarios")



# NOTE: AsignacionAulaDB has been removed. Aula assignments are now done
# via ClaseDB.aula_id field.


# =============================================================================
# Schedule & Planning Models
# =============================================================================

class ScheduleDB(SQLModel, table=True):
    """A schedule upload: represents a set of horario entries from a file."""
    __tablename__ = "schedules"

    id: str = Field(primary_key=True)  # UUID
    ciclo_id: Optional[str] = Field(default=None, foreign_key="ciclos.id", index=True)
    nombre: str
    fecha_upload: date
    source_filename: str = Field(default="")

    # Relationships
    ciclo: Optional[CicloDB] = Relationship(back_populates="schedules")
    entries: list["ScheduleEntryDB"] = Relationship(back_populates="schedule")


class ScheduleEntryDB(SQLModel, table=True):
    """A single row from a schedule file: materia + dia + hora + comision opcional."""
    __tablename__ = "schedule_entries"

    id: str = Field(primary_key=True)  # UUID
    schedule_id: str = Field(foreign_key="schedules.id", index=True)
    codigo_materia: str = Field(foreign_key="materias.codigo", index=True)
    dia: str
    hora_inicio: time
    hora_fin: time
    comision: Optional[int] = Field(default=None)
    tipo_clase: Optional[str] = Field(default=None)  # "teorica", "laboratorio" o None (sin determinar)

    # Relationships
    schedule: Optional[ScheduleDB] = Relationship(back_populates="entries")


class ScheduleValidationDB(SQLModel, table=True):
    """Snapshot historico de una validacion de cronograma contra un ciclo.

    Cada vez que el usuario corre 'Prevalidar cronograma contra ciclo' se
    inserta una fila. La UI por defecto muestra la mas reciente para el par
    (schedule_id, ciclo_id), pero se mantienen todas para auditoria.

    El snapshot de detalle (faltantes_por_carrera, extras, particion_details,
    etc.) se guarda como JSON serializado en `details_json` para reconstruir
    la vista sin recomputar.
    """
    __tablename__ = "schedule_validations"

    id: str = Field(default_factory=lambda: str(uuid.uuid4()), primary_key=True)
    schedule_id: str = Field(foreign_key="schedules.id", index=True)
    ciclo_id: str = Field(foreign_key="ciclos.id", index=True)
    validated_at: datetime = Field(default_factory=datetime.utcnow)

    # Snapshot del cronograma al momento de validar (para detectar staleness)
    entry_count_at_validation: int = Field(ge=0)
    # Snapshot del set de dictados activos del ciclo (para detectar staleness
    # cuando cambian los dictados sin que cambie el cronograma).
    dictado_count_at_validation: int = Field(default=0, ge=0)

    # Resumen general
    n_materias: int = Field(ge=0)
    n_clases: int = Field(ge=0)
    total_horas: float = Field(ge=0)

    # Cobertura vs ciclo
    n_esperadas: int = Field(ge=0)
    n_cubiertas: int = Field(ge=0)
    n_faltantes: int = Field(ge=0)
    n_extra: int = Field(default=0, ge=0)

    # Resumen de laboratorios
    n_con_lab_asignado: int = Field(default=0, ge=0)
    n_lab_fijo: int = Field(default=0, ge=0)
    n_lab_reserva: int = Field(default=0, ge=0)
    n_lab_pendiente: int = Field(default=0, ge=0)

    # Particion teoria/lab
    particion_valid: bool = Field(default=True)
    particion_n_infactibles: int = Field(default=0, ge=0)
    # Conflictos de horario detectados con comisiones auto-derivadas del
    # cronograma (mismas reglas que `preview_plan_from_schedule`). Si > 0,
    # generar el plan probablemente arroje los mismos conflictos en el tab
    # Detalle. El detalle estructurado va en `details_json["conflictos"]`.
    n_conflictos_horarios: int = Field(default=0, ge=0)

    # Config aplicada a la validacion (toggle "excluir optativas").
    # Si cambia entre runs, la validacion queda stale.
    # Las virtuales SI cuentan para cobertura/conflictos (no necesitan aula
    # pero estructuralmente deben ser consistentes); solo las optativas
    # se excluyen completamente del computo cuando esta activo.
    # `excluir_virtuales_optativas` queda como columna legacy (snapshots
    # historicos); el campo activo es `excluir_optativas`.
    excluir_virtuales_optativas: bool = Field(default=False)
    excluir_optativas: bool = Field(default=False)

    # Snapshot de detalle (JSON-serialized para reconstruccion de la UI)
    details_json: str = Field(default="{}")


class PlanValidationDB(SQLModel, table=True):
    """Snapshot historico de una validacion de un plan de cursada.

    Espejo de ScheduleValidationDB pero sobre PlanificacionCursadaDB. Las
    "materias del set" salen de ComisionDB del plan; los conflictos usan
    `validar_conflictos_horarios_plan` con los pares ignorados de
    IgnoredConflictDB filtrados.

    Cada vez que el usuario corre "Validar plan" se inserta una fila. La UI
    por defecto muestra la mas reciente; se mantienen todas para auditoria.
    """
    __tablename__ = "plan_validations"

    id: str = Field(default_factory=lambda: str(uuid.uuid4()), primary_key=True)
    plan_cursada_id: str = Field(
        foreign_key="planificaciones_cursada.id", index=True,
    )
    validated_at: datetime = Field(default_factory=datetime.utcnow)

    # Snapshots para staleness
    comision_count_at_validation: int = Field(ge=0)
    horario_count_at_validation: int = Field(ge=0)
    dictado_count_at_validation: int = Field(default=0, ge=0)

    # Config aplicada (toggle "excluir optativas"). Las virtuales cuentan;
    # solo optativas se descartan cuando esta activo. El campo viejo
    # `excluir_virtuales_optativas` queda como legacy.
    excluir_virtuales_optativas: bool = Field(default=False)
    excluir_optativas: bool = Field(default=False)

    # Resumen general (espejo de ScheduleValidationDB, sin lab breakdown
    # porque los labs viven a nivel cronograma)
    n_materias: int = Field(ge=0)
    n_clases: int = Field(ge=0)
    total_horas: float = Field(ge=0)
    n_esperadas: int = Field(ge=0)
    n_cubiertas: int = Field(ge=0)
    n_faltantes: int = Field(ge=0)
    n_extra: int = Field(default=0, ge=0)

    # Particion teoria/lab
    particion_valid: bool = Field(default=True)
    particion_n_infactibles: int = Field(default=0, ge=0)

    # Conflictos
    n_conflictos_horarios: int = Field(default=0, ge=0)
    n_conflictos_ignorados: int = Field(default=0, ge=0)

    # Snapshot detalle JSON
    details_json: str = Field(default="{}")


class IgnoredConflictDB(SQLModel, table=True):
    """Par de materias cuyo conflicto de horarios el usuario decidio ignorar.

    Granularidad por par (no por slot horario): si una vez se ignoro,
    queda ignorado aunque cambien los horarios. Se almacena con
    materia_a < materia_b lexicograficamente para deduplicacion.
    """
    __tablename__ = "ignored_conflicts"

    plan_cursada_id: str = Field(
        foreign_key="planificaciones_cursada.id", primary_key=True,
    )
    materia_a: str = Field(primary_key=True)  # ordenado lexicograficamente
    materia_b: str = Field(primary_key=True)  # > materia_a
    razon: str = Field(default="")
    fecha_creacion: datetime = Field(default_factory=datetime.utcnow)


class PlanificacionCursadaDB(SQLModel, table=True):
    """A coursework plan: generated from a schedule, contains comisiones and horarios."""
    __tablename__ = "planificaciones_cursada"

    id: str = Field(primary_key=True)  # UUID
    nombre: str
    descripcion: str = Field(default="")
    ciclo_id: str = Field(foreign_key="ciclos.id", index=True)
    activo: bool = Field(default=False)
    schedule_id: Optional[str] = Field(default=None, foreign_key="schedules.id")
    # Metodo de forecast por defecto que se aplica a todas las materias del
    # plan, salvo override en `MateriaForecastConfigDB`. Valores:
    # "media_movil" | "drift" | "ses".
    forecast_metodo_default: str = Field(default="media_movil")

    # Relationships
    ciclo: Optional[CicloDB] = Relationship(back_populates="planificaciones")
    comisiones: list["ComisionDB"] = Relationship(
        back_populates="plan_cursada",
        sa_relationship_kwargs={"foreign_keys": "[ComisionDB.plan_cursada_id]"}
    )
    clases: list["ClaseDB"] = Relationship(back_populates="plan_cursada")


class ClaseDB(SQLModel, table=True):
    """An individual class session on a specific date, generated from a horario."""
    __tablename__ = "clases"

    id: str = Field(primary_key=True)  # UUID
    horario_id: str = Field(foreign_key="horarios.id", index=True)
    comision_id: str = Field(foreign_key="comisiones.id", index=True)
    plan_cursada_id: str = Field(foreign_key="planificaciones_cursada.id", index=True)
    dictado_id: Optional[str] = Field(default=None, foreign_key="dictados.id")
    fecha: date
    hora_inicio: time
    hora_fin: time
    executed: bool = Field(default=False)
    aula_id: Optional[str] = Field(default=None, foreign_key="aulas.id")
    tipo_clase: Optional[str] = Field(default=None)  # "teorica", "laboratorio" o None (sin determinar)
    # True si la aula fue asignada por una edicion manual del usuario.
    # El re-run del LP por default respeta estas asignaciones (no las pisa)
    # salvo que el usuario active el toggle "sobreescribir todo".
    aula_asignada_manualmente: bool = Field(default=False)

    # Relationships
    plan_cursada: Optional[PlanificacionCursadaDB] = Relationship(back_populates="clases")


class MateriaLaboratorioDB(SQLModel, table=True):
    """Tabla link M:N entre materias y laboratorios compatibles para dictar clases de lab."""
    __tablename__ = "materia_laboratorio"

    materia_codigo: str = Field(foreign_key="materias.codigo", primary_key=True)
    aula_id: str = Field(foreign_key="aulas.id", primary_key=True)


class InscripcionHistoricaDB(SQLModel, table=True):
    """Registro historico de inscriptos por materia, año y cuatrimestre."""
    __tablename__ = "inscripciones_historicas"

    materia_codigo: str = Field(foreign_key="materias.codigo", primary_key=True)
    anio: int = Field(primary_key=True)
    cuatrimestre: str = Field(primary_key=True)  # "1C", "2C", "Anual"
    inscriptos: int = Field(ge=0)


class MateriaForecastConfigDB(SQLModel, table=True):
    """Override de configuracion de forecast por (plan, materia, cuatri).

    Dos overrides posibles, ambos opcionales:

    - `metodo`: que metodo usar para calcular el forecast (override del
      default del plan). Default por plan vive en
      `PlanificacionCursadaDB.forecast_metodo_default`. La resolucion final
      es: override si existe, sino default de plan.
    - `valor_override`: si esta seteado, FUERZA un valor manual de inscriptos
      esperados, sobreescribiendo cualquier resultado del forecast historico.
      Util cuando el usuario tiene info externa (preinscripcion, datos no
      historicos) o no hay serie historica disponible.

    Cuando `valor_override` es None, `get_forecast_for_materia` calcula
    desde la serie historica usando el metodo resuelto. El valor calculado
    NO se persiste — se recomputa on-demand.
    """
    __tablename__ = "materia_forecast_config"

    plan_cursada_id: str = Field(
        foreign_key="planificaciones_cursada.id", primary_key=True,
    )
    materia_codigo: str = Field(foreign_key="materias.codigo", primary_key=True)
    cuatrimestre: str = Field(primary_key=True)  # "1C" | "2C" | "Anual"
    metodo: Optional[str] = Field(default=None)  # "media_movil"|"drift"|"ses"|None
    valor_override: Optional[float] = Field(default=None, ge=0)


# =============================================================================
# LP de Asignacion de Aulas
# =============================================================================

class LPRunDB(SQLModel, table=True):
    """Snapshot de una corrida del LP de asignacion de aulas.

    Cada vez que el usuario corre el LP se inserta una fila. La UI por
    default muestra la mas reciente (`get_latest_run`). Las anteriores se
    conservan para auditoria y comparacion entre corridas.

    El detalle por horario (gap, aula asignada, t[h] resuelto, alpha[k] si
    aplica) se guarda serializado en `details_json` para reconstruccion sin
    recomputar.
    """
    __tablename__ = "lp_runs"

    id: str = Field(default_factory=lambda: str(uuid.uuid4()), primary_key=True)
    plan_cursada_id: str = Field(
        foreign_key="planificaciones_cursada.id", index=True,
    )
    run_at: datetime = Field(default_factory=datetime.utcnow)

    # Rango temporal aplicado a ClaseDB.
    fecha_desde: date

    # Configuracion aplicada al LP.
    lambda_over: float = Field(default=10.0, ge=0)
    lambda_under: float = Field(default=1.0, ge=0)
    tol_over: float = Field(default=0.0, ge=0)
    tol_under: float = Field(default=0.20, ge=0)
    activar_alpha: bool = Field(default=False)
    respetar_ediciones_manuales: bool = Field(default=True)
    timeout_seconds: int = Field(default=300, ge=1)

    # Resultado.
    status: str = Field(default="error")  # "optimal" | "infeasible" | "timeout" | "error"
    objective_value: Optional[float] = Field(default=None)
    n_horarios_total: int = Field(default=0, ge=0)
    n_horarios_asignados: int = Field(default=0, ge=0)
    n_clases_actualizadas: int = Field(default=0, ge=0)
    n_clases_sobreocupadas: int = Field(default=0, ge=0)
    n_clases_subutilizadas: int = Field(default=0, ge=0)
    n_ediciones_manuales_respetadas: int = Field(default=0, ge=0)
    solver_seconds: Optional[float] = Field(default=None, ge=0)
    error_message: str = Field(default="")

    # Snapshot detalle JSON. Estructura:
    # {
    #   "horarios": [
    #     {"horario_id": str, "aula_id": str|None, "tipo_clase": str|None,
    #      "insc": float, "cap": int, "delta": float,
    #      "over": float, "under": float, "estado": "ok"|"sobre"|"sub"},
    #     ...
    #   ],
    #   "alpha": {comision_id: float}    # solo si activar_alpha=True
    # }
    details_json: str = Field(default="{}")
