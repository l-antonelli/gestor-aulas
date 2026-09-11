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
class UbicacionCurricular:
    """Aparición de una materia en el plan vigente de una carrera:
    ``(carrera_codigo, anio, cuatri)``. Una misma materia puede
    tener múltiples ubicaciones si aparece en varios planes."""
    carrera_codigo: str
    anio: Optional[int]
    cuatri: Optional[str]


@dataclass
class MateriaFaltante:
    """Materia detectada por ``chequear_consistencia_grupo`` como
    candidata a agregarse al grupo: aparece en el plan vigente de al
    menos una carrera asociada y **no aparece** en el plan vigente de
    ninguna carrera no asociada.

    ``ubicaciones`` lista todas las apariciones en planes vigentes
    de carreras asociadas — util para mostrar 'aparece en X 2°2C, en
    E 3°1C' en una sola fila.
    """
    codigo: str
    nombre: str
    ubicaciones: list[UbicacionCurricular]
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
    chequear_pertenencia_asociadas: bool = True,
    chequear_exclusividad_no_asociadas: bool = True,
    chequear_completitud: bool = True,
) -> GrupoMateriaDB:
    """Crea un grupo con las dos configuraciones de sede + carreras
    asociadas + flags de chequeo.

    Validaciones:
    - Nombre único.
    - Sólo un grupo con ``es_sin_clasificar=True``.
    - Las sedes referenciadas deben existir (FK).

    Los tres ``chequear_*`` gobiernan qué ejes evalúa
    ``chequear_consistencia_grupo``. Ver docstring del modelo
    ``GrupoMateriaDB`` para la semántica de cada uno. Default: los
    tres activados.
    """
    if get_grupo_por_nombre(session, nombre) is not None:
        raise ValueError(f"Ya existe un grupo con nombre '{nombre}'.")
    if es_sin_clasificar:
        _validar_unico_sin_clasificar(session, excluir_id=None)

    grupo = GrupoMateriaDB(
        nombre=nombre,
        descripcion=descripcion,
        es_sin_clasificar=es_sin_clasificar,
        chequear_pertenencia_asociadas=chequear_pertenencia_asociadas,
        chequear_exclusividad_no_asociadas=chequear_exclusividad_no_asociadas,
        chequear_completitud=chequear_completitud,
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
    chequear_pertenencia_asociadas: Optional[bool] = None,
    chequear_exclusividad_no_asociadas: Optional[bool] = None,
    chequear_completitud: Optional[bool] = None,
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

    if (
        chequear_pertenencia_asociadas is not None
        and chequear_pertenencia_asociadas != grupo.chequear_pertenencia_asociadas
    ):
        grupo.chequear_pertenencia_asociadas = chequear_pertenencia_asociadas
        session.add(grupo)
    if (
        chequear_exclusividad_no_asociadas is not None
        and chequear_exclusividad_no_asociadas != grupo.chequear_exclusividad_no_asociadas
    ):
        grupo.chequear_exclusividad_no_asociadas = chequear_exclusividad_no_asociadas
        session.add(grupo)
    if (
        chequear_completitud is not None
        and chequear_completitud != grupo.chequear_completitud
    ):
        grupo.chequear_completitud = chequear_completitud
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


def sedes_admisibles_set_por_materia(
    session: Session,
    materia_codigo: str,
    modos_por_grupo: Optional[dict[str, str]] = None,
) -> Optional[set[str]]:
    """Devuelve el set de sedes admisibles para el LP dada una materia
    y el mapa de modos por grupo — la versión "legacy-friendly"
    usada por chequeos y heatmaps que necesitan el mismo filtro que
    el LP aplica.

    Semántica (idéntica al bloque R10 de ``build_inputs``):

    - Modo **DURO** con lista no vacía → ``set(sedes_ordenadas)``.
    - Modo **DURO** con lista vacía → ``None`` (fallback permisivo).
    - Modo **BLANDO** → ``None`` (todas admisibles, distinto costo).
    - Materia sin grupo → ``None``.

    ``None`` significa "sin restricción de sede" — es lo que interpreta
    ``compute_heatmap_por_sede`` como "cualquier sede vale".

    ``modos_por_grupo`` es opcional; si se omite, se asume DURO para
    todo grupo (el modo más restrictivo — coincide con el fallback
    del LP cuando ``LPConfig.modos_por_grupo`` no tiene entrada
    explícita).
    """
    grupo = resolver_grupo_de_materia(session, materia_codigo)
    if grupo is None:
        return None
    modo: Modo = (
        (modos_por_grupo or {}).get(grupo.id, "DURO")  # type: ignore[assignment]
    )
    sedes_ord, modo_eff = resolver_config_sedes_por_materia(
        session, materia_codigo, modo,
    )
    if modo_eff != "DURO":
        return None
    if not sedes_ord:
        return None
    return set(sedes_ord)


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

    La lógica se controla con los 3 flags del grupo (ver
    ``GrupoMateriaDB``):

    - ``chequear_pertenencia_asociadas``: eje "toda materia del grupo
      pertenece a las asociadas". En régimen transversal (≥2 asociadas)
      la interpretación es más fuerte: exige aparecer en al menos 2
      asociadas — si aparece en 1 sola, corresponde al específico de
      esa carrera.
    - ``chequear_exclusividad_no_asociadas``: eje "no aparece en no
      asociadas".
    - ``chequear_completitud``: si OFF, no se computan faltantes.

    Devuelve ``(faltantes, ajenas, warnings)``:

    - **faltantes**: materias que aparecen en al menos una carrera
      asociada, respetan los umbrales activos (pertenencia y
      exclusividad, si están ON) y están en otro grupo (o sin grupo).
      Vacío si ``chequear_completitud=False``.
    - **ajenas**: materias del grupo que violan alguno de los ejes
      activos. Si ambos flags de ajena están OFF, siempre vacío.
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

    # Umbral de pertenencia para régimen transversal (≥2 asociadas):
    # cuando `chequear_pertenencia_asociadas` está ON, se requiere que
    # la materia aparezca en al menos 2 asociadas (interpretación
    # transversal: una materia en 1 sola asociada pertenece al
    # específico de esa carrera, no al grupo transversal). Cuando
    # está OFF, basta con aparecer en 1 (relaja el umbral).
    modo_transversal = len(carreras_asociadas) >= 2
    umbral_pertenencia = (
        2 if (
            modo_transversal
            and grupo.chequear_pertenencia_asociadas
        ) else 1
    )

    # Índice: materia_codigo → { carrera → PlanEstudioDB } para las
    # carreras asociadas del grupo.
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

    # Índice inverso: materia_codigo → lista de carreras asociadas
    # donde aparece.
    materia_a_asociadas: dict[str, list[str]] = {}
    for cod, mat_map in materias_por_carrera_grupo.items():
        for mc in mat_map:
            materia_a_asociadas.setdefault(mc, []).append(cod)

    # Planes vigentes de las OTRAS carreras (no asociadas al grupo).
    todas_carreras = list(session.exec(
        select(CarreraDB.codigo)
    ).all())
    carreras_no_asociadas = [
        c for c in todas_carreras if c not in carreras_asociadas
    ]
    materia_a_no_asociadas: dict[str, list[str]] = {}
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
            materia_a_no_asociadas.setdefault(mc, []).append(cod)

    # -----------------------------------------------------------------
    # Faltantes: sólo si `chequear_completitud=True`. Una materia es
    # faltante si aparece en las asociadas cumpliendo:
    #   * `umbral_pertenencia`: nº mínimo de asociadas donde aparece.
    #   * Si `chequear_exclusividad_no_asociadas=True`, no aparece en
    #     ninguna no-asociada.
    # Y además está en otro grupo (o sin grupo).
    # -----------------------------------------------------------------
    dedup: list[MateriaFaltante] = []
    if grupo.chequear_completitud:
        ubicaciones_por_faltante: dict[
            str, list[tuple[str, PlanEstudioDB]],
        ] = {}
        for cod, mat_map in materias_por_carrera_grupo.items():
            for mc, pe in mat_map.items():
                asoc = materia_a_asociadas.get(mc, [])
                no_asoc = materia_a_no_asociadas.get(mc, [])
                if len(asoc) < umbral_pertenencia:
                    continue
                if grupo.chequear_exclusividad_no_asociadas and no_asoc:
                    continue
                materia = session.get(MateriaDB, mc)
                if materia is None:
                    continue
                if materia.grupo_id == grupo_id:
                    continue
                ubicaciones_por_faltante.setdefault(mc, []).append((cod, pe))

        for mc in sorted(ubicaciones_por_faltante):
            materia = session.get(MateriaDB, mc)
            if materia is None:
                continue
            grupo_actual = (
                session.get(GrupoMateriaDB, materia.grupo_id)
                if materia.grupo_id else None
            )
            # Ordenar ubicaciones por (carrera, año, cuatri) para
            # display estable.
            ubicaciones_ord = sorted(
                ubicaciones_por_faltante[mc],
                key=lambda t: (
                    t[0],
                    t[1].anio_plan if t[1].anio_plan is not None else 99,
                    t[1].cuatrimestre_plan or "",
                ),
            )
            dedup.append(MateriaFaltante(
                codigo=mc,
                nombre=materia.nombre,
                ubicaciones=[
                    UbicacionCurricular(
                        carrera_codigo=cod,
                        anio=pe.anio_plan,
                        cuatri=pe.cuatrimestre_plan,
                    )
                    for cod, pe in ubicaciones_ord
                ],
                grupo_actual_id=grupo_actual.id if grupo_actual else None,
                grupo_actual_nombre=(
                    grupo_actual.nombre if grupo_actual else None
                ),
            ))

    # -----------------------------------------------------------------
    # Ajenas: se reportan si al menos uno de los flags de ajena
    # dispara. Cada flag agrega un motivo:
    #
    # - `chequear_pertenencia_asociadas=True`: si la materia aparece
    #   en < `umbral_pertenencia` asociadas, viola pertenencia.
    # - `chequear_exclusividad_no_asociadas=True`: si la materia
    #   aparece en al menos una no-asociada, viola exclusividad.
    #
    # Si ambos flags están OFF, no se reportan ajenas.
    # -----------------------------------------------------------------
    materias_del_grupo = list(session.exec(
        select(MateriaDB).where(MateriaDB.grupo_id == grupo_id)
    ).all())

    ajenas: list[MateriaAjena] = []
    check_pert = grupo.chequear_pertenencia_asociadas
    check_excl = grupo.chequear_exclusividad_no_asociadas
    if check_pert or check_excl:
        for m in materias_del_grupo:
            asoc = materia_a_asociadas.get(m.codigo, [])
            no_asoc = materia_a_no_asociadas.get(m.codigo, [])
            viola_pert = check_pert and len(asoc) < umbral_pertenencia
            viola_excl = check_excl and bool(no_asoc)
            if not (viola_pert or viola_excl):
                continue
            # `carreras_donde_aparece`: reportar las carreras que
            # explican el diagnóstico.
            if viola_excl and viola_pert:
                # Ambos ejes fallan: mostrar las asociadas donde
                # sí aparece (para el usuario ver dónde queda) y
                # las no-asociadas (destino natural). Priorizamos
                # las no-asociadas si son las únicas donde aparece
                # — se preserva el comportamiento por-carrera anterior.
                if not asoc:
                    carreras_donde_aparece = sorted(no_asoc)
                else:
                    carreras_donde_aparece = sorted(set(asoc) | set(no_asoc))
            elif viola_excl:
                # Pertenencia OK pero contamina: reporta las no
                # asociadas donde aparece.
                carreras_donde_aparece = sorted(no_asoc)
            else:
                # viola_pert sólo: reporta dónde aparece (asoc + no
                # asoc), para que el usuario vea a qué carrera
                # pertenece la materia.
                carreras_donde_aparece = sorted(set(asoc) | set(no_asoc))

            if not carreras_donde_aparece:
                # No aparece en ningún plan vigente. Puede ser una
                # materia optativa, archivada o desconectada. La
                # saltamos para no confundir.
                continue

            # Sugerencia de grupo destino cuando es unívoca: existe un
            # único grupo (distinto al actual) asociado a alguna de las
            # carreras donde aparece la materia.
            sugerencia_id: Optional[str] = None
            sugerencia_nombre: Optional[str] = None
            if len(carreras_donde_aparece) == 1:
                unica = carreras_donde_aparece[0]
                candidatos = list(session.exec(
                    select(GrupoMateriaCarreraDB.grupo_id).where(
                        GrupoMateriaCarreraDB.carrera_codigo == unica,
                    )
                ).all())
                candidatos = [gid for gid in candidatos if gid != grupo_id]
                if len(candidatos) == 1:
                    g_dest = session.get(GrupoMateriaDB, candidatos[0])
                    if g_dest is not None:
                        sugerencia_id = g_dest.id
                        sugerencia_nombre = g_dest.nombre

            ajenas.append(MateriaAjena(
                codigo=m.codigo,
                nombre=m.nombre,
                carreras_donde_aparece=carreras_donde_aparece,
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
