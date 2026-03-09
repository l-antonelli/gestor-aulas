"""Service for creating and managing Dictados for academic cycles."""

import uuid
from dataclasses import dataclass, field
from typing import Optional

from sqlmodel import Session, select

from src.database.models import (
    CicloDB, DictadoDB, DictadoCicloDB, MateriaDB,
    CicloPlanVersionDB, PlanEstudioDB,
)
from src.database.crud import ciclo_crud, materia_crud, dictado_crud


@dataclass
class DictadoCreationResult:
    """Result of creating dictados for a ciclo."""
    created: int = 0
    linked: int = 0
    skipped: int = 0
    errors: list[str] = field(default_factory=list)


def create_dictados_for_ciclo(session: Session, ciclo_id: str) -> DictadoCreationResult:
    """
    Create Dictados for all active materias in a ciclo.

    - Cuatrimestrales: always create a new Dictado + DictadoCiclo link.
    - Anuales in 1C: create a new Dictado + DictadoCiclo link (fin_dictado=None).
    - Anuales in 2C: find the existing annual Dictado from 1C of the same year,
      link it with DictadoCiclo, and set fin_dictado.
    - Idempotent: skips materias that already have a dictado linked to this ciclo.
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
