"""Servicio de gestión de comisiones (``ComisionDB``).

Una ``ComisionDB`` representa una división de una materia para
distribuir alumnos. En este proyecto una comisión pertenece a:

- **Un cronograma** (``schedule_id`` seteado): comisión "template" que
  define atributos (nombre, cupo, carrera_asignada, descripción) para
  las entries de ese cronograma. Al generar un plan desde el
  cronograma, estas comisiones se **clonan** al plan (nuevos IDs)
  preservando atributos.
- **Un plan de cursada** (``plan_cursada_id`` seteado): entidad viva
  del plan. Los ``HorarioDB`` del plan apuntan aca.

El XOR "exactamente uno de los dos FKs seteado" no es un constraint de
DB (SQLite no soporta CHECK con OR facilmente); se valida al crear /
actualizar en este servicio.

El campo ``carrera_asignada`` sobreescribe la restriccion de sede del
LP (ver RF-LP-15).
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from typing import Optional

from sqlmodel import Session, select

from src.database.models import (
    ComisionDB,
    HorarioDB,
    MateriaDB,
    ScheduleEntryDB,
)


# =============================================================================
# Errores tipados
# =============================================================================

@dataclass
class ValidationResult:
    """Resultado de una operación con validaciones."""
    ok: bool = True
    errores: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)


# =============================================================================
# Creación
# =============================================================================

def _resolve_default_cupo(session: Session, materia_codigo: str) -> int:
    """Devuelve el cupo default de la materia, o 30 si no está definido."""
    mat = session.get(MateriaDB, materia_codigo)
    if mat is not None and mat.cupo:
        return int(mat.cupo)
    return 30


def _next_numero_libre(
    session: Session,
    materia_codigo: str,
    *,
    schedule_id: Optional[str] = None,
    plan_cursada_id: Optional[str] = None,
) -> int:
    """Devuelve el siguiente `numero` libre para una materia dentro
    de un scope (cronograma o plan)."""
    query = select(ComisionDB.numero).where(
        ComisionDB.materia_codigo == materia_codigo,
    )
    if schedule_id is not None:
        query = query.where(ComisionDB.schedule_id == schedule_id)
    elif plan_cursada_id is not None:
        query = query.where(ComisionDB.plan_cursada_id == plan_cursada_id)
    else:
        raise ValueError("Debe especificar schedule_id o plan_cursada_id.")
    usados = {int(n) for n in session.exec(query).all()}
    n = 1
    while n in usados:
        n += 1
    return n


def create_comision_for_schedule(
    session: Session,
    schedule_id: str,
    materia_codigo: str,
    *,
    nombre: str = "",
    numero: Optional[int] = None,
    cupo: Optional[int] = None,
    descripcion: str = "",
    carrera_asignada: Optional[str] = None,
) -> ComisionDB:
    """Crea una ``ComisionDB`` asociada a un cronograma.

    Si ``numero`` no se especifica, autoderiva el próximo libre para la
    materia en ese cronograma. Si ``cupo`` no se especifica, usa
    ``MateriaDB.cupo`` (o 30 como fallback).
    """
    if numero is None:
        numero = _next_numero_libre(
            session, materia_codigo, schedule_id=schedule_id,
        )
    if cupo is None:
        cupo = _resolve_default_cupo(session, materia_codigo)
    if not nombre:
        nombre = f"Comisión {numero}"

    com = ComisionDB(
        id=str(uuid.uuid4()),
        materia_codigo=materia_codigo,
        schedule_id=schedule_id,
        plan_cursada_id=None,
        comision_key=f"{materia_codigo}-{numero:03d}",
        nombre=nombre,
        numero=numero,
        cupo=cupo,
        descripcion=descripcion,
        coef_asignacion=1.0,
        carrera_asignada=carrera_asignada,
    )
    session.add(com)
    session.commit()
    session.refresh(com)
    return com


def create_comision_for_plan(
    session: Session,
    plan_cursada_id: str,
    materia_codigo: str,
    *,
    nombre: str = "",
    numero: Optional[int] = None,
    cupo: Optional[int] = None,
    descripcion: str = "",
    carrera_asignada: Optional[str] = None,
    dictado_id: Optional[str] = None,
    coef_asignacion: float = 1.0,
) -> ComisionDB:
    """Crea una ``ComisionDB`` asociada a un plan de cursada."""
    if numero is None:
        numero = _next_numero_libre(
            session, materia_codigo, plan_cursada_id=plan_cursada_id,
        )
    if cupo is None:
        cupo = _resolve_default_cupo(session, materia_codigo)
    if not nombre:
        nombre = f"Comisión {numero}"

    com = ComisionDB(
        id=str(uuid.uuid4()),
        materia_codigo=materia_codigo,
        schedule_id=None,
        plan_cursada_id=plan_cursada_id,
        dictado_id=dictado_id,
        comision_key=f"{materia_codigo}-{numero:03d}",
        nombre=nombre,
        numero=numero,
        cupo=cupo,
        descripcion=descripcion,
        coef_asignacion=coef_asignacion,
        carrera_asignada=carrera_asignada,
    )
    session.add(com)
    session.commit()
    session.refresh(com)
    return com


# =============================================================================
# Lectura
# =============================================================================

def list_comisiones_for_schedule_materia(
    session: Session,
    schedule_id: str,
    materia_codigo: str,
) -> list[ComisionDB]:
    """Comisiones de una materia en un cronograma, ordenadas por número."""
    return list(session.exec(
        select(ComisionDB)
        .where(ComisionDB.schedule_id == schedule_id)
        .where(ComisionDB.materia_codigo == materia_codigo)
        .order_by(ComisionDB.numero)  # type: ignore[arg-type]
    ).all())


def list_comisiones_for_schedule(
    session: Session, schedule_id: str,
) -> list[ComisionDB]:
    """Todas las comisiones de un cronograma."""
    return list(session.exec(
        select(ComisionDB)
        .where(ComisionDB.schedule_id == schedule_id)
        .order_by(ComisionDB.materia_codigo, ComisionDB.numero)  # type: ignore[arg-type]
    ).all())


def list_comisiones_for_plan_materia(
    session: Session, plan_cursada_id: str, materia_codigo: str,
) -> list[ComisionDB]:
    """Comisiones de una materia en un plan, ordenadas por número."""
    return list(session.exec(
        select(ComisionDB)
        .where(ComisionDB.plan_cursada_id == plan_cursada_id)
        .where(ComisionDB.materia_codigo == materia_codigo)
        .order_by(ComisionDB.numero)  # type: ignore[arg-type]
    ).all())


# =============================================================================
# Actualización
# =============================================================================

def update_comision(
    session: Session, comision_id: str, **campos,
) -> ComisionDB:
    """Actualiza campos de una comisión existente.

    Campos aceptados: ``nombre``, ``numero``, ``cupo``, ``descripcion``,
    ``carrera_asignada``, ``coef_asignacion``, ``dictado_id``.
    """
    com = session.get(ComisionDB, comision_id)
    if com is None:
        raise ValueError(f"Comisión '{comision_id}' no encontrada.")

    allowed = {
        "nombre", "numero", "cupo", "descripcion",
        "carrera_asignada", "coef_asignacion", "dictado_id",
    }
    for key, val in campos.items():
        if key not in allowed:
            raise ValueError(f"Campo '{key}' no permitido en update_comision")
        setattr(com, key, val)

    # Regenerar comision_key si cambia numero.
    if "numero" in campos:
        com.comision_key = f"{com.materia_codigo}-{com.numero:03d}"

    session.add(com)
    session.commit()
    session.refresh(com)
    return com


# =============================================================================
# Borrado (con guardas)
# =============================================================================

def delete_comision(
    session: Session, comision_id: str,
) -> ValidationResult:
    """Borra una comisión. Bloqueado si tiene entries u horarios
    asociados — el usuario debe reasignarlos primero.
    """
    res = ValidationResult(ok=True)
    com = session.get(ComisionDB, comision_id)
    if com is None:
        res.ok = False
        res.errores.append(f"Comisión '{comision_id}' no encontrada.")
        return res

    n_entries = session.exec(
        select(ScheduleEntryDB.id).where(
            ScheduleEntryDB.comision_id == comision_id,
        )
    ).first()
    if n_entries:
        res.ok = False
        res.errores.append(
            "No se puede borrar: la comisión tiene entries asociadas "
            "en el cronograma. Reasignalos o borrá las entries primero."
        )
        return res

    n_horarios = session.exec(
        select(HorarioDB.id).where(HorarioDB.comision_id == comision_id)
    ).first()
    if n_horarios:
        res.ok = False
        res.errores.append(
            "No se puede borrar: la comisión tiene horarios asociados "
            "en el plan. Reasignalos o borrá los horarios primero."
        )
        return res

    session.delete(com)
    session.commit()
    return res


# =============================================================================
# Clonado cronograma -> plan
# =============================================================================

def clone_comisiones_for_plan(
    session: Session,
    schedule_id: str,
    plan_cursada_id: str,
    *,
    solo_materias: Optional[set[str]] = None,
) -> dict[str, str]:
    """Clona todas las comisiones "template" de un cronograma como
    comisiones del plan (nuevos IDs, ``plan_cursada_id`` seteado,
    ``schedule_id=None``).

    Devuelve el mapa ``{comision_id_original: comision_id_clon}`` para
    que el caller pueda reasignar entries/horarios.

    Si ``solo_materias`` se especifica, sólo clona comisiones de esas
    materias.
    """
    origen = list_comisiones_for_schedule(session, schedule_id)
    if solo_materias is not None:
        origen = [c for c in origen if c.materia_codigo in solo_materias]

    mapa: dict[str, str] = {}
    for c in origen:
        clon = ComisionDB(
            id=str(uuid.uuid4()),
            materia_codigo=c.materia_codigo,
            plan_cursada_id=plan_cursada_id,
            schedule_id=None,
            dictado_id=c.dictado_id,
            comision_key=c.comision_key,
            nombre=c.nombre,
            numero=c.numero,
            cupo=c.cupo,
            descripcion=c.descripcion,
            coef_asignacion=c.coef_asignacion,
            carrera_asignada=c.carrera_asignada,
        )
        session.add(clon)
        mapa[c.id] = clon.id
    session.commit()
    return mapa


# =============================================================================
# Helper: obtener o crear una comisión "por número" (compat con flujos
# viejos donde el usuario ingresa un int).
# =============================================================================

def get_or_create_comision_by_numero(
    session: Session,
    materia_codigo: str,
    numero: int,
    *,
    schedule_id: Optional[str] = None,
    plan_cursada_id: Optional[str] = None,
) -> ComisionDB:
    """Busca una comisión con ese ``numero`` en el scope
    (cronograma o plan) y la crea con defaults si no existe.

    Sirve para flujos legacy y para autoderivación en preview.
    """
    query = select(ComisionDB).where(
        ComisionDB.materia_codigo == materia_codigo,
    ).where(ComisionDB.numero == numero)
    if schedule_id is not None:
        query = query.where(ComisionDB.schedule_id == schedule_id)
    elif plan_cursada_id is not None:
        query = query.where(ComisionDB.plan_cursada_id == plan_cursada_id)
    else:
        raise ValueError("Debe especificar schedule_id o plan_cursada_id.")
    existente = session.exec(query).first()
    if existente is not None:
        return existente

    if schedule_id is not None:
        return create_comision_for_schedule(
            session, schedule_id, materia_codigo, numero=numero,
        )
    assert plan_cursada_id is not None
    return create_comision_for_plan(
        session, plan_cursada_id, materia_codigo, numero=numero,
    )
