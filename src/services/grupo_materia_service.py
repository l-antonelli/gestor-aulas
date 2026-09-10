"""Servicio para la entidad ``GrupoMateriaDB``.

Cada grupo declara AMBAS configuraciones de sede (set DURO y lista
BLANDA) al mismo tiempo. La elección del modo por-grupo se hace en el
panel del asignador (``LPConfig.modos_por_grupo``); el grupo declara
qué sedes admite en cada modo, el LP decide cuál usar en cada corrida.

**Semántica del modo (recordatorio)**:

- Modo ``DURO``: sólo las sedes del **set DURO** del grupo son
  admisibles. Set vacío = fallback permisivo (todas admisibles).
- Modo ``BLANDO``: todas las sedes admisibles, pero la primera de la
  **lista BLANDA ordenada** es la preferida (cost 0). Resto son
  alternativas con costo ``λ_sede_pref``.

Cada ``MateriaDB`` pertenece a exactamente un grupo (partición
estricta enforzada por schema + service). Sólo un grupo tiene
``es_sin_clasificar=True`` (fallback donde caen materias sin
clasificar).

**Chequeo de consistencia**: cada grupo puede asociarse con 0, 1 o
varias carreras (M:N vía ``GrupoMateriaCarreraDB``). La asociación
no dispara sync automático; se usa para revisar manualmente si las
materias exclusivas de las carreras asociadas están todas en el
grupo (via ``chequear_consistencia_grupo``).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal, Optional

from sqlmodel import Session, select

from src.database.models import (
    CarreraDB,
    GrupoMateriaCarreraDB,
    GrupoMateriaDB,
    GrupoMateriaSedeDB,
    HorarioDB,
    MateriaDB,
    PlanCarreraVersionDB,
    PlanEstudioDB,
)


Modo = Literal["DURO", "BLANDO"]


@dataclass
class ConfigGrupo:
    """Configuración completa de un grupo, con AMBOS sets de sede."""
    sedes_duras: list[str] = field(default_factory=list)
    sedes_blandas_ordenadas: list[str] = field(default_factory=list)
    carreras_asociadas: list[str] = field(default_factory=list)


@dataclass
class MateriaFaltante:
    """Materia detectada por ``chequear_consistencia_grupo`` como
    candidata a agregarse al grupo: aparece en el plan vigente de al
    menos una carrera asociada y **no aparece** en el plan vigente de
    ninguna carrera no asociada."""
    codigo: str
    nombre: str
    carrera_codigo: str
    anio: Optional[int]
    cuatri: Optional[str]
    grupo_actual_id: Optional[str]
    grupo_actual_nombre: Optional[str]


@dataclass
class MateriaAjena:
    """Materia que está en el grupo pero aparece en el plan vigente
    de al menos una carrera **no asociada** al grupo, y **no aparece**
    en el plan vigente de ninguna carrera asociada.

    Semánticamente indica un error de clasificación: la materia
    probablemente pertenece a otro grupo (transversal como FB/CE/FI,
    o específicas de otra carrera).
    """
    codigo: str
    nombre: str
    # Carreras (no asociadas al grupo) donde SÍ aparece la materia
    # en su plan vigente. Da pistas al operador sobre a qué grupo
    # correspondería.
    carreras_donde_aparece: list[str]
    # Sugerencia de grupo destino, si es unívoca (aparece en el
    # plan de una única carrera, y esa carrera tiene un grupo
    # asociado que la contendría). None si no hay sugerencia clara.
    sugerencia_grupo_id: Optional[str]
    sugerencia_grupo_nombre: Optional[str]


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
    """Devuelve el grupo marcado como ``es_sin_clasificar=True``."""
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
    sedes_duras: Optional[list[str]] = None,
    sedes_blandas_ordenadas: Optional[list[str]] = None,
    carreras_asociadas: Optional[list[str]] = None,
    es_sin_clasificar: bool = False,
    descripcion: str = "",
) -> GrupoMateriaDB:
    """Crea un grupo con las dos configuraciones de sede + carreras
    asociadas.

    Validaciones:
    - Nombre único.
    - Sólo un grupo con ``es_sin_clasificar=True``.
    - Las sedes referenciadas deben existir (FK).
    """
    if get_grupo_por_nombre(session, nombre) is not None:
        raise ValueError(f"Ya existe un grupo con nombre '{nombre}'.")
    if es_sin_clasificar:
        _validar_unico_sin_clasificar(session, excluir_id=None)

    grupo = GrupoMateriaDB(
        nombre=nombre,
        descripcion=descripcion,
        es_sin_clasificar=es_sin_clasificar,
    )
    session.add(grupo)
    session.flush()

    _replace_sedes_grupo(
        session, grupo.id,
        sedes_duras=sedes_duras or [],
        sedes_blandas_ordenadas=sedes_blandas_ordenadas or [],
    )
    _replace_carreras_grupo(
        session, grupo.id, carreras_asociadas or [],
    )

    session.commit()
    session.refresh(grupo)
    return grupo


def update_grupo(
    session: Session,
    grupo_id: str,
    nombre: Optional[str] = None,
    sedes_duras: Optional[list[str]] = None,
    sedes_blandas_ordenadas: Optional[list[str]] = None,
    carreras_asociadas: Optional[list[str]] = None,
    descripcion: Optional[str] = None,
) -> None:
    """Actualiza el grupo. Los args con ``None`` se ignoran (dejan la
    configuración previa intacta); los que se pasan (aunque sean
    listas vacías) reemplazan atómicamente."""
    grupo = get_grupo(session, grupo_id)

    if nombre is not None and nombre != grupo.nombre:
        otro = get_grupo_por_nombre(session, nombre)
        if otro is not None and otro.id != grupo.id:
            raise ValueError(f"Ya existe otro grupo con nombre '{nombre}'.")
        grupo.nombre = nombre
        session.add(grupo)

    if descripcion is not None and descripcion != grupo.descripcion:
        grupo.descripcion = descripcion
        session.add(grupo)

    if sedes_duras is not None or sedes_blandas_ordenadas is not None:
        # Si sólo se pasa uno de los dos, dejamos el otro intacto.
        actuales_duras, actuales_blandas = _get_sedes_grupo(session, grupo_id)
        duras_final = (
            sedes_duras if sedes_duras is not None else actuales_duras
        )
        blandas_final = (
            sedes_blandas_ordenadas if sedes_blandas_ordenadas is not None
            else actuales_blandas
        )
        _replace_sedes_grupo(
            session, grupo_id,
            sedes_duras=duras_final,
            sedes_blandas_ordenadas=blandas_final,
        )

    if carreras_asociadas is not None:
        _replace_carreras_grupo(session, grupo_id, carreras_asociadas)

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

    # Borrar filas dependientes primero (FK).
    for row in list(session.exec(
        select(GrupoMateriaSedeDB).where(
            GrupoMateriaSedeDB.grupo_id == grupo_id,
        )
    ).all()):
        session.delete(row)
    for row in list(session.exec(
        select(GrupoMateriaCarreraDB).where(
            GrupoMateriaCarreraDB.grupo_id == grupo_id,
        )
    ).all()):
        session.delete(row)
    session.delete(grupo)
    session.commit()


# =============================================================================
# Config de sedes del grupo
# =============================================================================


def get_config_grupo(session: Session, grupo_id: str) -> ConfigGrupo:
    """Devuelve la configuración completa del grupo:
    ``sedes_duras``, ``sedes_blandas_ordenadas``,
    ``carreras_asociadas``."""
    get_grupo(session, grupo_id)  # validación de existencia
    duras, blandas = _get_sedes_grupo(session, grupo_id)
    carreras = list(session.exec(
        select(GrupoMateriaCarreraDB.carrera_codigo).where(
            GrupoMateriaCarreraDB.grupo_id == grupo_id,
        )
    ).all())
    return ConfigGrupo(
        sedes_duras=duras,
        sedes_blandas_ordenadas=blandas,
        carreras_asociadas=sorted(carreras),
    )


def _get_sedes_grupo(
    session: Session, grupo_id: str,
) -> tuple[list[str], list[str]]:
    """Devuelve ``(sedes_duras, sedes_blandas_ordenadas)`` como listas.

    ``sedes_duras`` viene sin orden semántico (ordenada por ``orden``
    para estabilidad visual). ``sedes_blandas_ordenadas`` respeta
    ``orden`` (0 = preferida)."""
    rows = list(session.exec(
        select(GrupoMateriaSedeDB).where(
            GrupoMateriaSedeDB.grupo_id == grupo_id,
        ).order_by(
            GrupoMateriaSedeDB.tipo,  # type: ignore[arg-type]
            GrupoMateriaSedeDB.orden,  # type: ignore[arg-type]
        )
    ).all())
    duras = [r.sede_id for r in rows if r.tipo == "DURO"]
    blandas = [r.sede_id for r in rows if r.tipo == "BLANDO"]
    return (duras, blandas)


def _replace_sedes_grupo(
    session: Session,
    grupo_id: str,
    sedes_duras: list[str],
    sedes_blandas_ordenadas: list[str],
) -> None:
    """Reemplaza atómicamente los dos sets de sedes del grupo."""
    existentes = list(session.exec(
        select(GrupoMateriaSedeDB).where(
            GrupoMateriaSedeDB.grupo_id == grupo_id,
        )
    ).all())
    for row in existentes:
        session.delete(row)
    session.flush()
    for orden, sede_id in enumerate(sedes_duras):
        session.add(GrupoMateriaSedeDB(
            grupo_id=grupo_id, sede_id=sede_id,
            tipo="DURO", orden=orden,
        ))
    for orden, sede_id in enumerate(sedes_blandas_ordenadas):
        session.add(GrupoMateriaSedeDB(
            grupo_id=grupo_id, sede_id=sede_id,
            tipo="BLANDO", orden=orden,
        ))


def _replace_carreras_grupo(
    session: Session,
    grupo_id: str,
    carreras_codigos: list[str],
) -> None:
    """Reemplaza atómicamente las carreras asociadas al grupo."""
    existentes = list(session.exec(
        select(GrupoMateriaCarreraDB).where(
            GrupoMateriaCarreraDB.grupo_id == grupo_id,
        )
    ).all())
    for row in existentes:
        session.delete(row)
    session.flush()
    for cod in carreras_codigos:
        session.add(GrupoMateriaCarreraDB(
            grupo_id=grupo_id, carrera_codigo=cod,
        ))


# =============================================================================
# Materias → grupo
# =============================================================================


def asignar_materia_a_grupo(
    session: Session, materia_codigo: str, grupo_id: str,
) -> None:
    """Reasigna una materia a un grupo. Falla si la materia o el grupo
    no existen. Partición estricta (una materia = un grupo) garantizada
    por schema."""
    materia = session.get(MateriaDB, materia_codigo)
    if materia is None:
        raise ValueError(f"Materia '{materia_codigo}' no encontrada.")
    get_grupo(session, grupo_id)
    materia.grupo_id = grupo_id
    session.add(materia)
    session.commit()


def list_materias_por_grupo(
    session: Session, grupo_id: str,
) -> list[MateriaDB]:
    return list(session.exec(
        select(MateriaDB).where(MateriaDB.grupo_id == grupo_id).order_by(
            MateriaDB.codigo,  # type: ignore[arg-type]
        )
    ).all())


def list_materias_sin_clasificar(session: Session) -> list[MateriaDB]:
    grupo = get_grupo_sin_clasificar(session)
    return list_materias_por_grupo(session, grupo.id)


def contar_materias_por_grupo(session: Session) -> dict[str, int]:
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


# =============================================================================
# Resolución LP-friendly
# =============================================================================


def resolver_grupo_de_materia(
    session: Session, materia_codigo: str,
) -> Optional[GrupoMateriaDB]:
    """Devuelve el grupo asignado a una materia. Reasigna a
    "Sin clasificar" si no tiene grupo y ese grupo existe."""
    materia = session.get(MateriaDB, materia_codigo)
    if materia is None:
        raise ValueError(f"Materia '{materia_codigo}' no encontrada.")
    if materia.grupo_id:
        grupo = session.get(GrupoMateriaDB, materia.grupo_id)
        if grupo is not None:
            return grupo
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


def resolver_config_sedes_por_materia(
    session: Session,
    materia_codigo: str,
    modo: Modo,
) -> tuple[list[str], Modo]:
    """Devuelve ``(sedes_ordenadas, modo_efectivo)`` para el LP.

    Args:
        materia_codigo: código de la materia a resolver.
        modo: modo elegido por el LP para el grupo de esta materia
            (``DURO`` o ``BLANDO``).

    Semántica:

    - Si ``modo = DURO``: devuelve el set duro del grupo. Si está
      vacío → lista vacía (el LP interpreta como fallback permisivo).
    - Si ``modo = BLANDO``: devuelve la lista blanda ordenada del
      grupo. Si está vacía → lista vacía (el LP no aplica R12 para
      esta materia).
    """
    grupo = resolver_grupo_de_materia(session, materia_codigo)
    if grupo is None:
        return ([], modo)
    duras, blandas = _get_sedes_grupo(session, grupo.id)
    if modo == "DURO":
        return (duras, "DURO")
    return (blandas, "BLANDO")


def resolver_config_sedes_por_horario(
    session: Session,
    horario_id: str,
    modo: Modo,
) -> tuple[list[str], Modo]:
    horario = session.get(HorarioDB, horario_id)
    if horario is None:
        raise ValueError(f"Horario '{horario_id}' no encontrado.")
    return resolver_config_sedes_por_materia(
        session, horario.codigo_materia, modo,
    )


# =============================================================================
# Adaptador de compatibilidad para call sites viejos
# =============================================================================


def resolver_sedes_admisibles_por_materia(
    session: Session, materia_codigo: str,
) -> tuple[list[str], Modo]:
    """DEPRECATED — mantenido para compatibilidad con call sites que
    todavía no pasan el modo desde ``LPConfig.modos_por_grupo``.

    Asume ``modo = DURO`` como default seguro (el más restrictivo).
    Los call sites nuevos deben usar
    ``resolver_config_sedes_por_materia(session, materia, modo)``
    pasando el modo elegido por el LP.
    """
    return resolver_config_sedes_por_materia(
        session, materia_codigo, "DURO",
    )


# =============================================================================
# Chequeo de consistencia
# =============================================================================


def get_plan_activo(
    session: Session, carrera_codigo: str,
) -> Optional[PlanCarreraVersionDB]:
    """Devuelve la versión de plan **marcada** como ``active=True``
    para la carrera, o ``None`` si no hay ninguna activa.

    Diferencia contra ``get_plan_vigente``: esta función devuelve
    literalmente lo que dice el schema (``active=True``). Se usa
    donde importa distinguir "marcado" de "efectivo" — por ejemplo,
    el radio de plan activo en el módulo Carreras, o el
    preselector de planes de un ciclo nuevo (donde el usuario ve
    exactamente lo que va a quedar guardado).
    """
    return session.exec(
        select(PlanCarreraVersionDB).where(
            PlanCarreraVersionDB.carrera_codigo == carrera_codigo,
            PlanCarreraVersionDB.active == True,  # noqa: E712
        ).limit(1)
    ).first()


def get_plan_vigente(
    session: Session, carrera_codigo: str,
) -> Optional[PlanCarreraVersionDB]:
    """Devuelve la versión de plan **vigente** de la carrera aplicando
    la política global del sistema:

    1. Si la carrera tiene una versión marcada como ``active=True`` →
       esa.
    2. Si no, **fallback al más reciente por ``fecha_creacion``** —
       para que los filtros globales fuera del contexto de un plan
       de cursada sigan funcionando aunque el usuario no haya
       marcado ninguna versión como activa.
    3. Si la carrera no tiene ninguna versión → ``None``.

    **Regla operativa** (para no confundir con casos contextuales):

    - **Filtros globales de materias, chequeos de consistencia,
      preselección de ciclos nuevos** → usan ``get_plan_vigente``.
    - **Validaciones o filtros DENTRO del contexto de un plan de
      cursada / ciclo** → NO usan esta función; leen directamente
      las versiones asociadas al ciclo vía ``CicloPlanVersionDB``.
      Esto permite que ciclos antiguos conserven las versiones con
      las que se armaron aunque después se marque otra como activa.
    """
    activo = get_plan_activo(session, carrera_codigo)
    if activo is not None:
        return activo
    return session.exec(
        select(PlanCarreraVersionDB).where(
            PlanCarreraVersionDB.carrera_codigo == carrera_codigo,
        ).order_by(
            PlanCarreraVersionDB.fecha_creacion.desc(),  # type: ignore[attr-defined]
        ).limit(1)
    ).first()


def list_grupos_de_carrera(
    session: Session, carrera_codigo: str,
) -> list[GrupoMateriaDB]:
    """Devuelve los grupos asociados a una carrera (M:N vía
    ``GrupoMateriaCarreraDB``). Ordenados por nombre."""
    rows = list(session.exec(
        select(GrupoMateriaCarreraDB.grupo_id).where(
            GrupoMateriaCarreraDB.carrera_codigo == carrera_codigo,
        )
    ).all())
    if not rows:
        return []
    grupos = list(session.exec(
        select(GrupoMateriaDB).where(
            GrupoMateriaDB.id.in_(rows),  # type: ignore[attr-defined]
        )
    ).all())
    return sorted(grupos, key=lambda g: g.nombre.lower())


def set_plan_activo(
    session: Session,
    carrera_codigo: str,
    plan_version_id: Optional[str],
) -> None:
    """Marca ``plan_version_id`` como la versión activa de la carrera.

    Garantiza unicidad: baja el flag ``active`` en todas las otras
    versiones de la misma carrera. Si ``plan_version_id`` es ``None``,
    deja a la carrera sin plan activo.

    Levanta ``ValueError`` si el ``plan_version_id`` provisto no
    existe o no pertenece a la carrera indicada.
    """
    versiones = list(session.exec(
        select(PlanCarreraVersionDB).where(
            PlanCarreraVersionDB.carrera_codigo == carrera_codigo,
        )
    ).all())
    if plan_version_id is not None:
        target = next(
            (v for v in versiones if v.id == plan_version_id), None,
        )
        if target is None:
            raise ValueError(
                f"El plan '{plan_version_id}' no existe para la carrera "
                f"'{carrera_codigo}'."
            )
    for v in versiones:
        v.active = (v.id == plan_version_id)
        session.add(v)
    session.commit()


def chequear_consistencia_grupo(
    session: Session,
    grupo_id: str,
) -> tuple[list[MateriaFaltante], list["MateriaAjena"], list[str]]:
    """Chequea la consistencia bidireccional del grupo contra los
    planes vigentes de sus carreras asociadas.

    Devuelve ``(faltantes, ajenas, warnings)``:

    - **faltantes**: materias que corresponderían al grupo pero
      están en otro (o sin grupo). Detectadas por: aparecen en el
      plan vigente de una carrera asociada, no aparecen en planes
      vigentes de carreras no asociadas, y no están ya en el grupo.
    - **ajenas**: materias que están en el grupo pero probablemente
      no deberían — no aparecen en el plan vigente de ninguna
      carrera asociada, y sí aparecen en el plan vigente de al
      menos una carrera no asociada. Sugerencia de destino cuando
      es unívoca.
    - **warnings**: mensajes útiles para la UI (por ej. "la carrera
      X no tiene plan activo, se usa fallback").
    """
    grupo = get_grupo(session, grupo_id)
    carreras_asociadas = list(session.exec(
        select(GrupoMateriaCarreraDB.carrera_codigo).where(
            GrupoMateriaCarreraDB.grupo_id == grupo_id,
        )
    ).all())

    warnings: list[str] = []
    if not carreras_asociadas:
        warnings.append(
            "El grupo no tiene carreras asociadas. "
            "Asocialo a al menos una para poder chequear consistencia."
        )
        return ([], [], warnings)

    # Política global: usar el plan **vigente** (activo o, en su
    # defecto, el más reciente) — mismo criterio que aplican los
    # filtros globales de materias. Ver `get_plan_vigente`.
    planes_vigentes: dict[str, str] = {}  # carrera → plan_version_id
    for cod in carreras_asociadas:
        pv = get_plan_vigente(session, cod)
        if pv is None:
            warnings.append(
                f"La carrera '{cod}' no tiene ninguna versión de plan cargada."
            )
            continue
        planes_vigentes[cod] = pv.id
        if not pv.active:
            warnings.append(
                f"La carrera '{cod}' no tiene plan marcado como activo; "
                f"se usa el más reciente ('{pv.nombre}') como fallback."
            )

    if not planes_vigentes:
        return ([], [], warnings)

    # Índice: materia_codigo → set de carreras del grupo que la tienen
    # en su plan vigente.
    materias_por_carrera_grupo: dict[str, dict[str, PlanEstudioDB]] = {}
    for cod, pv_id in planes_vigentes.items():
        entries = list(session.exec(
            select(PlanEstudioDB).where(
                PlanEstudioDB.plan_version_id == pv_id,
            )
        ).all())
        materias_por_carrera_grupo[cod] = {
            e.materia_codigo: e for e in entries
        }

    # Necesitamos también los planes vigentes de las OTRAS carreras
    # para el filtro "exclusiva de las asociadas": una materia
    # exclusiva es la que no aparece en ningún plan vigente de otra
    # carrera.
    todas_carreras = list(session.exec(
        select(CarreraDB.codigo)
    ).all())
    carreras_no_asociadas = [
        c for c in todas_carreras if c not in carreras_asociadas
    ]
    materias_en_otras: set[str] = set()
    for cod in carreras_no_asociadas:
        pv = get_plan_vigente(session, cod)
        if pv is None:
            continue
        entries = list(session.exec(
            select(PlanEstudioDB.materia_codigo).where(
                PlanEstudioDB.plan_version_id == pv.id,
            )
        ).all())
        materias_en_otras.update(entries)

    faltantes: list[MateriaFaltante] = []
    for cod, mat_map in materias_por_carrera_grupo.items():
        for mc, pe in mat_map.items():
            # Filtro exclusivo: no está en el plan activo de ninguna
            # otra carrera fuera del set de asociadas.
            if mc in materias_en_otras:
                continue
            materia = session.get(MateriaDB, mc)
            if materia is None:
                continue
            # Si ya está en el grupo, no es faltante.
            if materia.grupo_id == grupo_id:
                continue
            grupo_actual = (
                session.get(GrupoMateriaDB, materia.grupo_id)
                if materia.grupo_id else None
            )
            faltantes.append(MateriaFaltante(
                codigo=mc,
                nombre=materia.nombre,
                carrera_codigo=cod,
                anio=pe.anio_plan,
                cuatri=pe.cuatrimestre_plan,
                grupo_actual_id=grupo_actual.id if grupo_actual else None,
                grupo_actual_nombre=(
                    grupo_actual.nombre if grupo_actual else None
                ),
            ))

    # Dedup por código (una materia puede aparecer en múltiples
    # carreras asociadas al grupo — la contamos una sola vez).
    vistas: set[str] = set()
    dedup: list[MateriaFaltante] = []
    for m in sorted(faltantes, key=lambda x: (x.codigo, x.carrera_codigo)):
        if m.codigo in vistas:
            continue
        vistas.add(m.codigo)
        dedup.append(m)

    # -----------------------------------------------------------------
    # Materias AJENAS: están asignadas al grupo pero:
    #   1. NO aparecen en el plan vigente de ninguna carrera asociada.
    #   2. SÍ aparecen en el plan vigente de al menos una carrera no
    #      asociada.
    # Semánticamente indican que la materia está mal clasificada.
    # -----------------------------------------------------------------
    # Índice: materia_codigo → lista de carreras no asociadas donde
    # aparece en el plan vigente. Reusa la query de arriba enriquecida
    # con el detalle por carrera.
    materia_a_carreras_no_asociadas: dict[str, list[str]] = {}
    for cod in carreras_no_asociadas:
        pv = get_plan_vigente(session, cod)
        if pv is None:
            continue
        mcodigos = list(session.exec(
            select(PlanEstudioDB.materia_codigo).where(
                PlanEstudioDB.plan_version_id == pv.id,
            )
        ).all())
        for mc in mcodigos:
            materia_a_carreras_no_asociadas.setdefault(mc, []).append(cod)

    # Set de materias del grupo asociadas: aparecen en plan vigente
    # de al menos una carrera asociada.
    materias_en_asociadas: set[str] = set()
    for mat_map in materias_por_carrera_grupo.values():
        materias_en_asociadas.update(mat_map.keys())

    # Materias actualmente en el grupo (sin importar plan).
    materias_del_grupo = list(session.exec(
        select(MateriaDB).where(MateriaDB.grupo_id == grupo_id)
    ).all())

    ajenas: list[MateriaAjena] = []
    for m in materias_del_grupo:
        # Si aparece en plan vigente de una carrera asociada → OK.
        if m.codigo in materias_en_asociadas:
            continue
        carreras_donde_aparece = materia_a_carreras_no_asociadas.get(
            m.codigo, [],
        )
        if not carreras_donde_aparece:
            # No aparece en ningún plan vigente. Puede ser una materia
            # optativa, archivada o desconectada. No la marcamos como
            # ajena para no confundir: quedará al criterio del operador.
            continue

        # Sugerencia de grupo destino cuando es unívoco: sólo aparece
        # en el plan de una única carrera y esa carrera tiene un
        # grupo asociado que la aceptaría (por asociación explícita).
        sugerencia_id: Optional[str] = None
        sugerencia_nombre: Optional[str] = None
        if len(carreras_donde_aparece) == 1:
            unica = carreras_donde_aparece[0]
            candidatos = list(session.exec(
                select(GrupoMateriaCarreraDB.grupo_id).where(
                    GrupoMateriaCarreraDB.carrera_codigo == unica,
                )
            ).all())
            # Filtrar el grupo actual y el propio grupo del chequeo.
            candidatos = [
                gid for gid in candidatos if gid != grupo_id
            ]
            if len(candidatos) == 1:
                g_dest = session.get(GrupoMateriaDB, candidatos[0])
                if g_dest is not None:
                    sugerencia_id = g_dest.id
                    sugerencia_nombre = g_dest.nombre

        ajenas.append(MateriaAjena(
            codigo=m.codigo,
            nombre=m.nombre,
            carreras_donde_aparece=sorted(carreras_donde_aparece),
            sugerencia_grupo_id=sugerencia_id,
            sugerencia_grupo_nombre=sugerencia_nombre,
        ))
    ajenas.sort(key=lambda x: x.codigo)

    return (dedup, ajenas, warnings)


# =============================================================================
# Helpers privados
# =============================================================================


def _validar_unico_sin_clasificar(
    session: Session, excluir_id: Optional[str],
) -> None:
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
