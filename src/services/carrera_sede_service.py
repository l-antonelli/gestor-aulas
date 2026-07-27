"""Servicio para la restriccion de sede por carrera (R10 del LP).

Encapsula tres operaciones principales:

1. ``set_sedes_de_carrera``: setea (replace) el conjunto de sedes
   habilitadas para una carrera.
2. ``get_sedes_de_carrera``: devuelve las sede_ids configuradas para
   una carrera.
3. ``set_sede_default_comunes``: marca a una sede como destino default
   de las materias comunes, garantizando que **a lo sumo una** sede
   tenga el flag activado a la vez.

Tambien expone helpers de lectura usados por el LP:

- ``materia_es_comun``: True si la materia aparece en >= 2 carreras.
- ``sedes_admisibles_para_materia``: devuelve el set de ``sede_id``
  donde la materia puede dictarse, segun la regla R10.
"""

from __future__ import annotations

from sqlmodel import Session, select

from src.database.models import (
    CarreraSedeDB,
    PlanEstudioDB,
    SedeDB,
)


def get_sedes_de_carrera(session: Session, carrera_codigo: str) -> set[str]:
    """Devuelve el set de sede_ids habilitadas para una carrera."""
    rows = session.exec(
        select(CarreraSedeDB.sede_id).where(
            CarreraSedeDB.carrera_codigo == carrera_codigo,
        )
    ).all()
    return set(rows)


def set_sedes_de_carrera(
    session: Session,
    carrera_codigo: str,
    sede_ids: list[str] | set[str],
) -> int:
    """Reemplaza el conjunto de sedes habilitadas para una carrera.

    Borra las filas previas en ``carrera_sede`` para esa carrera y
    inserta las nuevas. Devuelve la cantidad final de filas.
    """
    target = set(sede_ids)
    existentes = list(session.exec(
        select(CarreraSedeDB).where(
            CarreraSedeDB.carrera_codigo == carrera_codigo,
        )
    ).all())
    actuales = {row.sede_id for row in existentes}
    a_borrar = actuales - target
    a_agregar = target - actuales
    for row in existentes:
        if row.sede_id in a_borrar:
            session.delete(row)
    for sede_id in a_agregar:
        session.add(CarreraSedeDB(
            carrera_codigo=carrera_codigo, sede_id=sede_id,
        ))
    session.commit()
    return len(target)


def get_sede_default_comunes(session: Session) -> SedeDB | None:
    """Devuelve la sede marcada como default de comunes, o None si
    ninguna lo es."""
    return session.exec(
        select(SedeDB).where(
            SedeDB.es_default_comunes == True,  # noqa: E712
        ).limit(1)
    ).first()


def set_sede_default_comunes(
    session: Session, sede_id: str | None,
) -> SedeDB | None:
    """Marca a ``sede_id`` como sede default de materias comunes.

    Si otra sede tenia el flag activado, se le baja primero
    (garantia de unicidad). Si ``sede_id`` es None, simplemente
    desactiva el flag de cualquier sede que lo tenga.

    Devuelve la sede que quedo activada (o None si se desactivo todo).
    """
    # Bajar el flag en cualquier sede que lo tenga.
    actuales = list(session.exec(
        select(SedeDB).where(
            SedeDB.es_default_comunes == True,  # noqa: E712
        )
    ).all())
    for s in actuales:
        if s.id != sede_id:
            s.es_default_comunes = False
            session.add(s)

    if sede_id is None:
        session.commit()
        return None

    sede = session.get(SedeDB, sede_id)
    if sede is None:
        session.rollback()
        raise ValueError(f"Sede '{sede_id}' no encontrada.")
    sede.es_default_comunes = True
    session.add(sede)
    session.commit()
    session.refresh(sede)
    return sede


def materia_es_comun(session: Session, materia_codigo: str) -> bool:
    """True si la materia aparece en al menos 2 carreras distintas
    (definicion de 'comun' usada en el resto del sistema)."""
    carreras = session.exec(
        select(PlanEstudioDB.carrera_codigo).where(
            PlanEstudioDB.materia_codigo == materia_codigo,
        ).distinct()
    ).all()
    return len({c for c in carreras}) >= 2


def sedes_admisibles_para_carrera(
    session: Session, carrera_codigo: str,
) -> set[str] | None:
    """Devuelve el set de ``sede_id`` admisibles para una carrera.

    Se usa cuando un horario tiene el override ``carrera_asignada``
    (comision organizada para una carrera puntual): el LP resuelve la
    sede admisible via esta funcion en vez de
    ``sedes_admisibles_para_materia``.

    Reglas:

    - Si la carrera tiene sedes configuradas via ``CarreraSedeDB``,
      devuelve ese set.
    - Si no tiene ninguna sede configurada, devuelve None (fallback
      "todas las sedes", coherente con la rama exclusiva de
      ``sedes_admisibles_para_materia``).

    El valor None significa "sin restriccion de sede".
    """
    sedes = get_sedes_de_carrera(session, carrera_codigo)
    if not sedes:
        return None
    return sedes


def sedes_admisibles_para_materia(
    session: Session, materia_codigo: str,
) -> set[str] | None:
    """Devuelve el set de ``sede_id`` admisibles para la materia segun R10.

    Reglas:

    - **Materia comun (>= 2 carreras)**: solo la sede marcada como
      default de comunes (``SedeDB.es_default_comunes = True``). Si no
      hay ninguna sede default configurada, devuelve None (= todas
      admitidas).
    - **Materia exclusiva (1 carrera)**: las sedes asociadas a esa
      carrera via ``CarreraSedeDB``. Si la carrera no tiene sedes
      configuradas, devuelve None (fallback "todas las sedes").
    - **Materia sin carrera (no esta en ningun plan)**: None
      (no hay restriccion).

    El valor None significa "no hay restriccion de sede para esta
    materia". El caller debe interpretar None como "cualquier sede vale".
    """
    carreras = list(session.exec(
        select(PlanEstudioDB.carrera_codigo).where(
            PlanEstudioDB.materia_codigo == materia_codigo,
        ).distinct()
    ).all())
    carreras_set = {c for c in carreras}

    if not carreras_set:
        return None

    if len(carreras_set) >= 2:
        # Materia comun.
        default = get_sede_default_comunes(session)
        if default is None:
            return None
        return {default.id}

    # Materia exclusiva.
    (carrera_codigo,) = tuple(carreras_set)
    sedes = get_sedes_de_carrera(session, carrera_codigo)
    if not sedes:
        return None
    return sedes
