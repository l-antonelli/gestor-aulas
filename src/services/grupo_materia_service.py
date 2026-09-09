"""Servicio para la entidad ``GrupoMateriaDB``.

Encapsula la config de sedes admisibles del LP (R10/R12) via grupos de
materias. Cada materia pertenece a un unico grupo (partición estricta);
cada grupo tiene un modo (``DURO``/``BLANDO``) y una lista ordenada de
sedes.

**Semántica del modo**:

- ``DURO``: las sedes de la lista son las unicas admisibles. Lista vacia
  = fallback permisivo ("todas las sedes"), solo esperable para el
  grupo "Sin clasificar" durante la transición.
- ``BLANDO``: todas las sedes son admisibles pero la primera (``orden=0``)
  es la preferida a nivel objetivo. Alternativas suman ``λ_sede_pref``
  al costo por horario desplazado.

**Unicidad**:

- ``nombre`` es unico globalmente.
- Solo un grupo puede tener ``es_sin_clasificar=True`` a la vez.
"""

from __future__ import annotations

from typing import Literal, Optional

from sqlmodel import Session, select

from src.database.models import (
    GrupoMateriaDB,
    GrupoMateriaSedeDB,
    HorarioDB,
    MateriaDB,
)


Modo = Literal["DURO", "BLANDO"]


# =============================================================================
# CRUD basico
# =============================================================================


def list_grupos(session: Session) -> list[GrupoMateriaDB]:
    """Devuelve todos los grupos, ordenados por nombre."""
    return list(session.exec(
        select(GrupoMateriaDB).order_by(GrupoMateriaDB.nombre)  # type: ignore[arg-type]
    ).all())


def get_grupo(session: Session, grupo_id: str) -> GrupoMateriaDB:
    """Devuelve un grupo por ID. Levanta ``ValueError`` si no existe."""
    grupo = session.get(GrupoMateriaDB, grupo_id)
    if grupo is None:
        raise ValueError(f"Grupo de materias '{grupo_id}' no encontrado.")
    return grupo


def get_grupo_por_nombre(
    session: Session, nombre: str,
) -> Optional[GrupoMateriaDB]:
    """Devuelve el grupo por nombre exacto, o None si no existe."""
    return session.exec(
        select(GrupoMateriaDB).where(GrupoMateriaDB.nombre == nombre).limit(1)
    ).first()


def get_grupo_sin_clasificar(session: Session) -> GrupoMateriaDB:
    """Devuelve el grupo marcado como ``es_sin_clasificar=True``.

    Levanta ``ValueError`` si no existe (la migración lo crea al
    arranque, asi que no deberia pasar en runtime normal).
    """
    grupo = session.exec(
        select(GrupoMateriaDB).where(
            GrupoMateriaDB.es_sin_clasificar == True,  # noqa: E712
        ).limit(1)
    ).first()
    if grupo is None:
        raise ValueError(
            "No existe un grupo marcado como 'Sin clasificar'. "
            "Reiniciar la app para forzar la migración inicial."
        )
    return grupo


def create_grupo(
    session: Session,
    nombre: str,
    modo: Modo,
    sedes_ordenadas: list[str],
    es_sin_clasificar: bool = False,
) -> GrupoMateriaDB:
    """Crea un grupo con las sedes indicadas en el orden dado.

    Valida que:
    - El nombre no exista.
    - ``modo`` sea ``DURO`` o ``BLANDO``.
    - Si ``es_sin_clasificar=True``, no exista otro con ese flag.
    """
    if modo not in ("DURO", "BLANDO"):
        raise ValueError(f"modo debe ser 'DURO' o 'BLANDO', no {modo!r}")
    if get_grupo_por_nombre(session, nombre) is not None:
        raise ValueError(f"Ya existe un grupo con nombre '{nombre}'.")
    if es_sin_clasificar:
        _validar_unico_sin_clasificar(session, excluir_id=None)

    grupo = GrupoMateriaDB(
        nombre=nombre, modo=modo, es_sin_clasificar=es_sin_clasificar,
    )
    session.add(grupo)
    session.flush()  # necesario para tener grupo.id
    for orden, sede_id in enumerate(sedes_ordenadas):
        session.add(GrupoMateriaSedeDB(
            grupo_id=grupo.id, sede_id=sede_id, orden=orden,
        ))
    session.commit()
    session.refresh(grupo)
    return grupo


def update_grupo(
    session: Session,
    grupo_id: str,
    nombre: str,
    modo: Modo,
    sedes_ordenadas: list[str],
) -> None:
    """Reemplaza atómicamente nombre, modo y lista de sedes de un grupo.

    Preserva el flag ``es_sin_clasificar`` (no se puede editar via esta
    función). Valida:
    - Nombre unico (permitido si es el nombre actual del mismo grupo).
    - Modo válido.
    """
    if modo not in ("DURO", "BLANDO"):
        raise ValueError(f"modo debe ser 'DURO' o 'BLANDO', no {modo!r}")
    grupo = get_grupo(session, grupo_id)
    otro = get_grupo_por_nombre(session, nombre)
    if otro is not None and otro.id != grupo.id:
        raise ValueError(f"Ya existe otro grupo con nombre '{nombre}'.")

    grupo.nombre = nombre
    grupo.modo = modo
    session.add(grupo)

    # Reemplazar sedes: borrar todas y reinsertar en orden.
    existentes = list(session.exec(
        select(GrupoMateriaSedeDB).where(
            GrupoMateriaSedeDB.grupo_id == grupo_id,
        )
    ).all())
    for row in existentes:
        session.delete(row)
    session.flush()
    for orden, sede_id in enumerate(sedes_ordenadas):
        session.add(GrupoMateriaSedeDB(
            grupo_id=grupo_id, sede_id=sede_id, orden=orden,
        ))
    session.commit()


def delete_grupo(session: Session, grupo_id: str) -> None:
    """Borra un grupo. Falla si tiene materias asignadas o si es el
    grupo ``es_sin_clasificar``."""
    grupo = get_grupo(session, grupo_id)
    if grupo.es_sin_clasificar:
        raise ValueError(
            "No se puede borrar el grupo 'Sin clasificar'. "
            "Reasignar las materias primero si querés reorganizar."
        )
    n_materias = session.exec(
        select(MateriaDB).where(MateriaDB.grupo_id == grupo_id).limit(1)
    ).first()
    if n_materias is not None:
        raise ValueError(
            f"El grupo '{grupo.nombre}' tiene materias asignadas. "
            "Reasignar todas las materias antes de borrarlo."
        )

    # Borrar filas de sedes primero (FK).
    sedes = list(session.exec(
        select(GrupoMateriaSedeDB).where(
            GrupoMateriaSedeDB.grupo_id == grupo_id,
        )
    ).all())
    for row in sedes:
        session.delete(row)
    session.delete(grupo)
    session.commit()


# =============================================================================
# Config de sedes del grupo
# =============================================================================


def get_config_grupo(
    session: Session, grupo_id: str,
) -> tuple[list[str], Modo]:
    """Devuelve ``(sedes_ordenadas, modo)`` del grupo.

    Sedes ordenadas por el campo ``orden`` ascendente. La lista puede
    estar vacia (fallback permisivo si DURO).
    """
    grupo = get_grupo(session, grupo_id)
    rows = list(session.exec(
        select(GrupoMateriaSedeDB).where(
            GrupoMateriaSedeDB.grupo_id == grupo_id,
        ).order_by(GrupoMateriaSedeDB.orden)  # type: ignore[arg-type]
    ).all())
    sede_ids = [r.sede_id for r in rows]
    modo: Modo = "BLANDO" if grupo.modo == "BLANDO" else "DURO"
    return (sede_ids, modo)


# =============================================================================
# Materias → grupo
# =============================================================================


def asignar_materia_a_grupo(
    session: Session, materia_codigo: str, grupo_id: str,
) -> None:
    """Reasigna una materia a un grupo. Falla si la materia o el grupo
    no existen."""
    materia = session.get(MateriaDB, materia_codigo)
    if materia is None:
        raise ValueError(f"Materia '{materia_codigo}' no encontrada.")
    get_grupo(session, grupo_id)  # valida existencia
    materia.grupo_id = grupo_id
    session.add(materia)
    session.commit()


def list_materias_por_grupo(
    session: Session, grupo_id: str,
) -> list[MateriaDB]:
    """Devuelve las materias asignadas a un grupo, ordenadas por
    codigo."""
    return list(session.exec(
        select(MateriaDB).where(MateriaDB.grupo_id == grupo_id).order_by(
            MateriaDB.codigo,  # type: ignore[arg-type]
        )
    ).all())


def list_materias_sin_clasificar(session: Session) -> list[MateriaDB]:
    """Devuelve las materias asignadas al grupo ``Sin clasificar``.

    Es el atajo mas usado desde la UI para encontrar materias que
    todavia no fueron organizadas.
    """
    grupo = get_grupo_sin_clasificar(session)
    return list_materias_por_grupo(session, grupo.id)


# =============================================================================
# Resolución LP-friendly
# =============================================================================


def resolver_grupo_de_materia(
    session: Session, materia_codigo: str,
) -> Optional[GrupoMateriaDB]:
    """Devuelve el grupo asignado a una materia, o ``None`` si la
    materia no tiene grupo y tampoco existe un grupo "Sin clasificar"
    en el que caer.

    Cuando la materia no tiene ``grupo_id`` seteado (edge case:
    entrada manual pre-migración o test que no bootstrapea grupos), se
    intenta caer en el grupo ``Sin clasificar`` — si existe, se
    reasigna la materia ahí y se devuelve el grupo. Si no existe, se
    devuelve ``None`` (los callers interpretan ``None`` como
    "fallback permisivo": lista vacía, modo DURO).
    """
    materia = session.get(MateriaDB, materia_codigo)
    if materia is None:
        raise ValueError(f"Materia '{materia_codigo}' no encontrada.")
    if materia.grupo_id:
        grupo = session.get(GrupoMateriaDB, materia.grupo_id)
        if grupo is not None:
            return grupo
    # Fallback: intentar reasignar a Sin clasificar si existe.
    grupo_sc = session.exec(
        select(GrupoMateriaDB).where(
            GrupoMateriaDB.es_sin_clasificar == True,  # noqa: E712
        ).limit(1)
    ).first()
    if grupo_sc is None:
        return None
    materia.grupo_id = grupo_sc.id
    session.add(materia)
    session.commit()
    return grupo_sc


def resolver_sedes_admisibles_por_horario(
    session: Session, horario_id: str,
) -> tuple[list[str], Modo]:
    """Devuelve ``(sedes_ordenadas, modo)`` del grupo de la materia del
    horario.

    Ignora ``ComisionDB.carrera_asignada`` (que quedó como etiqueta
    visual). El grupo se resuelve exclusivamente por la materia del
    horario.

    Con lista vacia (grupo sin sedes configuradas o materia sin grupo)
    y modo ``DURO``, el caller debe interpretar como "todas las sedes
    admisibles" (fallback permisivo).
    """
    horario = session.get(HorarioDB, horario_id)
    if horario is None:
        raise ValueError(f"Horario '{horario_id}' no encontrado.")
    grupo = resolver_grupo_de_materia(session, horario.codigo_materia)
    if grupo is None:
        return ([], "DURO")
    return get_config_grupo(session, grupo.id)


def resolver_sedes_admisibles_por_materia(
    session: Session, materia_codigo: str,
) -> tuple[list[str], Modo]:
    """Igual que ``resolver_sedes_admisibles_por_horario`` pero directo
    desde la materia. Util para call sites que no tienen horario
    (validaciones, previews de UI, etc.)."""
    grupo = resolver_grupo_de_materia(session, materia_codigo)
    if grupo is None:
        return ([], "DURO")
    return get_config_grupo(session, grupo.id)


# =============================================================================
# Helpers privados
# =============================================================================


def _validar_unico_sin_clasificar(
    session: Session, excluir_id: Optional[str],
) -> None:
    """Valida que ningun otro grupo tenga ``es_sin_clasificar=True``."""
    q = select(GrupoMateriaDB).where(
        GrupoMateriaDB.es_sin_clasificar == True,  # noqa: E712
    )
    if excluir_id is not None:
        q = q.where(GrupoMateriaDB.id != excluir_id)
    otro = session.exec(q.limit(1)).first()
    if otro is not None:
        raise ValueError(
            f"Ya existe un grupo 'Sin clasificar' ({otro.nombre!r}). "
            "Solo puede haber uno con este flag activado."
        )


# =============================================================================
# Info util para debugging / UI
# =============================================================================


def contar_materias_por_grupo(session: Session) -> dict[str, int]:
    """Devuelve ``{grupo_id: cantidad_materias}`` para todos los grupos.

    Grupos sin materias no aparecen (usar 0 como default en el caller).
    """
    rows = session.exec(
        select(MateriaDB.grupo_id).where(  # type: ignore[arg-type]
            MateriaDB.grupo_id.is_not(None),  # type: ignore[union-attr]
        )
    ).all()
    counts: dict[str, int] = {}
    for grupo_id in rows:
        if not grupo_id:
            continue
        counts[grupo_id] = counts.get(grupo_id, 0) + 1
    return counts
