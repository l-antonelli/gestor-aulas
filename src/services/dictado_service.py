"""Service for creating and managing Dictados for academic cycles."""

import uuid
from dataclasses import dataclass, field
from typing import Optional

from sqlmodel import Session, select

from src.database.models import (
    CarreraDB, CicloDB, DictadoDB, DictadoCicloDB, MateriaDB,
    CicloPlanVersionDB, PlanEstudioDB,
)
from src.database.crud import ciclo_crud, materia_crud, dictado_crud


@dataclass
class DictadoCreationResult:
    """Result of creating dictados for a ciclo."""
    created: int = 0
    linked: int = 0
    skipped: int = 0
    skipped_recursado: int = 0
    errors: list[str] = field(default_factory=list)


@dataclass
class SkippedMateria:
    """A materia that was skipped during dictado creation, with the reason."""
    materia_codigo: str
    materia_nombre: str
    razon: str


def _should_skip_for_recursado(
    session: Session,
    materia: MateriaDB,
    ciclo: CicloDB,
    plan_version_ids: list[str],
) -> bool:
    """Check if a cuatrimestral materia should be skipped due to dicta_recursado=False.

    Logic:
    1. Find all carreras that include this materia via PlanEstudioDB within
       the plan versions assigned to this ciclo.
    2. If the materia appears in multiple carreras → it's shared → never skip.
    3. If it's exclusive to one carrera and that carrera has dicta_recursado=False:
       - Get the cuatrimestre_plan from PlanEstudioDB
       - If cuatrimestre_plan doesn't match the ciclo's cuatrimestre and isn't "Anual" → skip.
    """
    # Get the plan_estudio entries for this materia within the ciclo's plan versions
    entries = session.exec(
        select(PlanEstudioDB)
        .where(PlanEstudioDB.materia_codigo == materia.codigo)
        .where(PlanEstudioDB.plan_version_id.in_(plan_version_ids))
    ).all()

    # Collect unique carreras
    carrera_codigos = list({e.carrera_codigo for e in entries})

    if len(carrera_codigos) != 1:
        # Shared across multiple carreras → always create dictado
        return False

    # Exclusive to one carrera — check dicta_recursado
    carrera = session.get(CarreraDB, carrera_codigos[0])
    if carrera is None or carrera.dicta_recursado:
        # carrera allows recursado or not found → don't skip
        return False

    # carrera.dicta_recursado == False — check cuatrimestre_plan
    cuatrimestre_ciclo = f"{ciclo.numero}C"

    for entry in entries:
        cuatri = entry.cuatrimestre_plan
        if cuatri is None or cuatri.lower() == "anual" or cuatri == cuatrimestre_ciclo:
            # Matches current ciclo or is annual → don't skip
            return False

    # All entries are for the opposite cuatrimestre → skip
    return True


def create_dictados_for_ciclo(session: Session, ciclo_id: str) -> DictadoCreationResult:
    """
    Create Dictados for all active materias in a ciclo.

    - Cuatrimestrales: always create a new Dictado + DictadoCiclo link.
    - Anuales in 1C: create a new Dictado + DictadoCiclo link (fin_dictado=None).
    - Anuales in 2C: find the existing annual Dictado from 1C of the same year,
      link it with DictadoCiclo, and set fin_dictado.
    - Idempotent: skips materias that already have a dictado linked to this ciclo.
    - dicta_recursado: if a carrera has dicta_recursado=False and the materia is
      exclusive to that carrera, skip materias from the opposite cuatrimestre.
    - virtual: dictado.virtual inherits from materia.virtual.
    """
    result = DictadoCreationResult()

    ciclo = ciclo_crud.get(session, ciclo_id)
    if ciclo is None:
        result.errors.append(f"Ciclo '{ciclo_id}' no encontrado")
        return result

    # Get plan versions assigned to this ciclo
    plan_version_ids = session.exec(
        select(CicloPlanVersionDB.plan_version_id)
        .where(CicloPlanVersionDB.ciclo_id == ciclo_id)
    ).all()

    if not plan_version_ids:
        result.errors.append(
            f"Ciclo '{ciclo_id}' no tiene versiones de plan asignadas. "
            "Asigne versiones de plan en la pestana de Ciclos antes de crear dictados."
        )
        return result

    # Get unique materias from assigned plan versions
    materias = session.exec(
        select(MateriaDB)
        .join(PlanEstudioDB, MateriaDB.codigo == PlanEstudioDB.materia_codigo)
        .where(PlanEstudioDB.plan_version_id.in_(plan_version_ids))
        .distinct()
    ).all()

    for materia in materias:
        # Check if this materia already has a dictado linked to this ciclo
        existing_link = session.exec(
            select(DictadoCicloDB)
            .join(DictadoDB, DictadoDB.id == DictadoCicloDB.dictado_id)
            .where(DictadoCicloDB.ciclo_id == ciclo_id)
            .where(DictadoDB.materia_codigo == materia.codigo)
        ).first()

        if existing_link is not None:
            result.skipped += 1
            continue

        # Check dicta_recursado skip logic (only for cuatrimestrales)
        if materia.periodo == "cuatrimestral":
            if _should_skip_for_recursado(session, materia, ciclo, plan_version_ids):
                result.skipped_recursado += 1
                continue

        if materia.periodo == "cuatrimestral":
            _create_cuatrimestral_dictado(session, materia, ciclo, result)
        elif materia.periodo == "anual":
            if ciclo.numero == 1:
                _create_anual_dictado_1c(session, materia, ciclo, result)
            else:
                _link_anual_dictado_2c(session, materia, ciclo, result)

    session.commit()
    return result


def _create_cuatrimestral_dictado(
    session: Session,
    materia: MateriaDB,
    ciclo: CicloDB,
    result: DictadoCreationResult,
) -> None:
    """Create a cuatrimestral dictado and link it to the ciclo."""
    dictado_codigo = f"{materia.codigo}-{ciclo.anio}-{ciclo.numero}C"
    dictado_id = str(uuid.uuid4())

    dictado = DictadoDB(
        id=dictado_id,
        materia_codigo=materia.codigo,
        dictado_codigo=dictado_codigo,
        inicio_dictado=ciclo.fecha_inicio,
        fin_dictado=ciclo.fecha_fin,
        activo=True,
        virtual=materia.virtual,
    )
    session.add(dictado)
    session.flush()

    link = DictadoCicloDB(dictado_id=dictado_id, ciclo_id=ciclo.id)
    session.add(link)
    result.created += 1


def _create_anual_dictado_1c(
    session: Session,
    materia: MateriaDB,
    ciclo: CicloDB,
    result: DictadoCreationResult,
) -> None:
    """Create an annual dictado in 1C (fin_dictado=None until 2C links it)."""
    dictado_codigo = f"{materia.codigo}-{ciclo.anio}"
    dictado_id = str(uuid.uuid4())

    dictado = DictadoDB(
        id=dictado_id,
        materia_codigo=materia.codigo,
        dictado_codigo=dictado_codigo,
        inicio_dictado=ciclo.fecha_inicio,
        fin_dictado=None,
        activo=True,
        virtual=materia.virtual,
    )
    session.add(dictado)
    session.flush()

    link = DictadoCicloDB(dictado_id=dictado_id, ciclo_id=ciclo.id)
    session.add(link)
    result.created += 1


def _link_anual_dictado_2c(
    session: Session,
    materia: MateriaDB,
    ciclo: CicloDB,
    result: DictadoCreationResult,
) -> None:
    """Link an existing annual dictado from 1C to 2C and set fin_dictado."""
    # Find the annual dictado from 1C of the same year
    dictado_codigo_anual = f"{materia.codigo}-{ciclo.anio}"

    existing_dictado = session.exec(
        select(DictadoDB)
        .where(DictadoDB.materia_codigo == materia.codigo)
        .where(DictadoDB.dictado_codigo == dictado_codigo_anual)
    ).first()

    if existing_dictado is None:
        # No 1C dictado found — create a fresh one
        dictado_id = str(uuid.uuid4())
        dictado = DictadoDB(
            id=dictado_id,
            materia_codigo=materia.codigo,
            dictado_codigo=dictado_codigo_anual,
            inicio_dictado=ciclo.fecha_inicio,
            fin_dictado=ciclo.fecha_fin,
            activo=True,
            virtual=materia.virtual,
        )
        session.add(dictado)
        session.flush()

        link = DictadoCicloDB(dictado_id=dictado_id, ciclo_id=ciclo.id)
        session.add(link)
        result.created += 1
        return

    # Link existing dictado to this 2C ciclo
    existing_dictado.fin_dictado = ciclo.fecha_fin
    session.add(existing_dictado)

    link = DictadoCicloDB(dictado_id=existing_dictado.id, ciclo_id=ciclo.id)
    session.add(link)
    result.linked += 1


def get_dictados_for_ciclo(session: Session, ciclo_id: str) -> list[DictadoDB]:
    """Get all dictados linked to a ciclo."""
    statement = (
        select(DictadoDB)
        .join(DictadoCicloDB, DictadoDB.id == DictadoCicloDB.dictado_id)
        .where(DictadoCicloDB.ciclo_id == ciclo_id)
    )
    return list(session.exec(statement).all())


def get_skipped_materias_for_ciclo(
    session: Session, ciclo_id: str
) -> list[SkippedMateria]:
    """Get materias from the plan that don't have a dictado for this ciclo, with reasons.

    Returns a list of SkippedMateria for each materia in the plan versions
    assigned to this ciclo that does NOT have a corresponding dictado link.
    """
    ciclo = ciclo_crud.get(session, ciclo_id)
    if ciclo is None:
        return []

    plan_version_ids = session.exec(
        select(CicloPlanVersionDB.plan_version_id)
        .where(CicloPlanVersionDB.ciclo_id == ciclo_id)
    ).all()

    if not plan_version_ids:
        return []

    # All materias in the plan
    materias = session.exec(
        select(MateriaDB)
        .join(PlanEstudioDB, MateriaDB.codigo == PlanEstudioDB.materia_codigo)
        .where(PlanEstudioDB.plan_version_id.in_(plan_version_ids))
        .distinct()
    ).all()

    # Materias that already have a dictado for this ciclo
    dictado_materia_codigos = set(session.exec(
        select(DictadoDB.materia_codigo)
        .join(DictadoCicloDB, DictadoDB.id == DictadoCicloDB.dictado_id)
        .where(DictadoCicloDB.ciclo_id == ciclo_id)
    ).all())

    skipped = []
    for materia in materias:
        if materia.codigo in dictado_materia_codigos:
            continue

        # Determine reason
        if _should_skip_for_recursado(session, materia, ciclo, plan_version_ids):
            razon = "Materia exclusiva de carrera sin recursado (cuatrimestre opuesto)"
        else:
            razon = "Sin dictado creado"

        skipped.append(SkippedMateria(
            materia_codigo=materia.codigo,
            materia_nombre=materia.nombre,
            razon=razon,
        ))

    return skipped


def update_dictado(
    session: Session,
    dictado_id: str,
    activo: Optional[bool] = None,
    virtual: Optional[bool] = None,
) -> Optional[DictadoDB]:
    """Update activo and/or virtual flags on a dictado."""
    dictado = session.get(DictadoDB, dictado_id)
    if dictado is None:
        return None

    if activo is not None:
        dictado.activo = activo
    if virtual is not None:
        dictado.virtual = virtual

    session.add(dictado)
    session.commit()
    session.refresh(dictado)
    return dictado
