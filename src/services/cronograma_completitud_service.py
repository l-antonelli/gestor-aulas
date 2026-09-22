"""Métricas de completitud del cronograma por grupo de materias y por (carrera, año).

Fase D del rediseño 2026-09-15. Complementa el resumen agregado de
``cronograma_validation_service`` (que sólo tiene totales globales)
con dos vistas desagregadas que el usuario pidió explícitamente:

- **Por grupo de materias** (``GrupoMateriaDB``): útil para saber
  qué familia de materias todavía tiene datos faltantes en las
  cátedras (ej: "cargamos todos los FB, faltan las CE").
- **Por (carrera, año)**: útil para el operador que arma el
  cronograma con los profesores de una carrera puntual (ej: "el año
  1° de Electrónica ya está listo, falta 2°").

Ambas vistas se computan **on-the-fly** desde el estado actual del
cronograma; no se persisten en ``ScheduleValidationDB``. Cambiar
esto en una fase futura requeriría migrar el modelo — hoy la
consulta es barata (sólo agregación sobre ``ScheduleEntryDB`` +
``PlanEstudioDB`` + ``GrupoMateriaDB``).

**Optativas**: la vista respeta el toggle ``excluir_optativas`` para
que sea consistente con el resto del panel. Por default (Fase D)
las optativas se **excluyen**, siguiendo la preferencia explícita
del usuario para este panel.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional

from sqlmodel import Session, col, select

from src.database.models import (
    CarreraDB,
    GrupoMateriaDB,
    MateriaDB,
    PlanEstudioDB,
    ScheduleEntryDB,
)
from src.services.dictado_service import (
    get_materias_esperadas_from_dictados,
)
from src.services.validations import build_grupos_curriculares_del_ciclo


# =============================================================================
# Dataclasses
# =============================================================================


@dataclass
class GrupoCompletitud:
    """Estado de completitud de un grupo de materias en un cronograma.

    ``esperadas`` viene del set global "materias del ciclo con dictado
    activo" restringido a las que pertenecen al grupo. ``cubiertas``
    es el subset que tiene al menos una entry en el cronograma.
    """
    grupo_id: str
    grupo_nombre: str
    grupo_descripcion: str
    es_sin_clasificar: bool
    n_esperadas: int
    n_cubiertas: int
    materias_faltantes: list[tuple[str, str]] = field(default_factory=list)
    # (codigo, nombre) — no se listan las cubiertas para no inflar el payload.

    @property
    def n_faltantes(self) -> int:
        return self.n_esperadas - self.n_cubiertas

    @property
    def pct_completitud(self) -> float:
        if self.n_esperadas == 0:
            return 100.0
        return 100.0 * self.n_cubiertas / self.n_esperadas


@dataclass
class CarreraAnioCompletitud:
    """Estado de completitud de un (carrera, año) en un cronograma.

    ``esperadas`` sale de los grupos curriculares del ciclo: para el
    cuatri del ciclo se suman las anuales del mismo (carrera, año).
    Filtra optativas y respeta el toggle ``excluir_optativas``.
    """
    carrera_codigo: str
    carrera_nombre: str
    anio: int
    cuatri: str
    n_esperadas: int
    n_cubiertas: int
    materias_faltantes: list[tuple[str, str]] = field(default_factory=list)

    @property
    def n_faltantes(self) -> int:
        return self.n_esperadas - self.n_cubiertas

    @property
    def pct_completitud(self) -> float:
        if self.n_esperadas == 0:
            return 100.0
        return 100.0 * self.n_cubiertas / self.n_esperadas


# =============================================================================
# Cómputo
# =============================================================================


def _materias_del_schedule(
    session: Session, schedule_id: str,
) -> set[str]:
    """Set de codigo_materia con al menos una entry en el schedule."""
    rows = session.exec(
        select(ScheduleEntryDB.codigo_materia)
        .where(ScheduleEntryDB.schedule_id == schedule_id)
        .distinct()
    ).all()
    return {r for r in rows if r}


def _codigos_optativas(
    session: Session, codigos: list[str],
) -> set[str]:
    """Codigos que aparecen marcados como optativa en algún PlanEstudioDB.

    Es el mismo criterio que usa ``validar_cronograma`` para el
    toggle ``exclude_optativas``: si al menos un PlanEstudio marca la
    materia como optativa, se considera optativa (interpretación
    conservadora).
    """
    if not codigos:
        return set()
    rows = session.exec(
        select(PlanEstudioDB.materia_codigo)
        .where(col(PlanEstudioDB.materia_codigo).in_(codigos))
        .where(PlanEstudioDB.optativa == True)  # noqa: E712
        .distinct()
    ).all()
    return {r for r in rows if r}


def completitud_por_grupo_materia(
    session: Session,
    schedule_id: str,
    ciclo_id: str,
    *,
    exclude_optativas: bool = True,
) -> list[GrupoCompletitud]:
    """Devuelve la completitud por grupo de materias del cronograma.

    Args:
        session: sesión activa.
        schedule_id, ciclo_id: alcance.
        exclude_optativas: default True (Fase D). Si False, las
            optativas se cuentan tanto en esperadas como en cubiertas.

    Returns:
        Lista ordenada por nombre del grupo, con el grupo
        "Sin clasificar" al final (si tiene esperadas).
        Se descartan grupos sin materias esperadas (nada para mostrar).
    """
    esperadas = get_materias_esperadas_from_dictados(session, ciclo_id)
    if not esperadas:
        return []

    cod_esperadas = list(esperadas.keys())
    optativas_excluidas: set[str] = set()
    if exclude_optativas:
        optativas_excluidas = _codigos_optativas(session, cod_esperadas)
        cod_esperadas = [c for c in cod_esperadas if c not in optativas_excluidas]

    if not cod_esperadas:
        return []

    materias_en_sched = _materias_del_schedule(session, schedule_id)
    if exclude_optativas:
        materias_en_sched = materias_en_sched - optativas_excluidas

    # Cargar materias esperadas con su grupo_id + nombre para render.
    mats_esperadas = list(session.exec(
        select(MateriaDB)
        .where(col(MateriaDB.codigo).in_(cod_esperadas))
    ).all())

    # Cache: grupo_id -> GrupoMateriaDB (sólo los que aparecen).
    grupo_ids_presentes: set[str] = {
        m.grupo_id for m in mats_esperadas if m.grupo_id
    }
    grupos_map: dict[str, GrupoMateriaDB] = {}
    if grupo_ids_presentes:
        gs = list(session.exec(
            select(GrupoMateriaDB)
            .where(col(GrupoMateriaDB.id).in_(list(grupo_ids_presentes)))
        ).all())
        grupos_map = {g.id: g for g in gs}

    # Agrupar por grupo_id (o "__sin_grupo__" cuando la materia no tiene).
    por_grupo: dict[Optional[str], list[MateriaDB]] = {}
    for m in mats_esperadas:
        por_grupo.setdefault(m.grupo_id, []).append(m)

    resultado: list[GrupoCompletitud] = []
    for gid, mats in por_grupo.items():
        if gid is not None and gid in grupos_map:
            g = grupos_map[gid]
            nombre = g.nombre
            desc = g.descripcion or ""
            es_sc = g.es_sin_clasificar
        else:
            # Materias sin grupo asignado — no debería pasar en runtime
            # normal (la migración de grupos las asigna al de "Sin
            # clasificar"), pero se soporta por defensa. Se muestran
            # bajo una fila virtual "(sin grupo)".
            nombre = "(sin grupo asignado)"
            desc = "Materias que no fueron asignadas a ningún grupo."
            es_sc = False

        cod_esperadas_g = [m.codigo for m in mats]
        n_esp = len(cod_esperadas_g)
        cubiertas_g = set(cod_esperadas_g) & materias_en_sched
        faltantes_g = [
            (m.codigo, m.nombre) for m in mats
            if m.codigo not in cubiertas_g
        ]
        faltantes_g.sort(key=lambda t: t[0])
        resultado.append(GrupoCompletitud(
            grupo_id=(gid or "__sin_grupo__"),
            grupo_nombre=nombre,
            grupo_descripcion=desc,
            es_sin_clasificar=es_sc,
            n_esperadas=n_esp,
            n_cubiertas=len(cubiertas_g),
            materias_faltantes=faltantes_g,
        ))

    # Orden: alfabético por nombre, con "Sin clasificar" al final.
    resultado.sort(key=lambda g: (g.es_sin_clasificar, g.grupo_nombre))
    return resultado


def completitud_por_carrera_anio(
    session: Session,
    schedule_id: str,
    ciclo_id: str,
    *,
    exclude_optativas: bool = True,
) -> list[CarreraAnioCompletitud]:
    """Devuelve la completitud por (carrera, año, cuatri) del cronograma.

    Reusa ``build_grupos_curriculares_del_ciclo`` para no duplicar la
    lógica de "materias del cuatri del ciclo + anuales del mismo
    (carrera, año)". El helper ya filtra optativas — si el toggle
    está en False, se re-inflan las optativas leyendo PlanEstudioDB.
    """
    grupos = build_grupos_curriculares_del_ciclo(session, ciclo_id)
    if not grupos:
        return []

    materias_en_sched = _materias_del_schedule(session, schedule_id)

    # Si el usuario quiere INCLUIR optativas, agregar las materias
    # optativas del ciclo a cada grupo (carrera, año, cuatri).
    # `build_grupos_curriculares_del_ciclo` ya las filtró.
    if not exclude_optativas:
        pe_rows = list(session.exec(
            select(
                PlanEstudioDB.carrera_codigo,
                PlanEstudioDB.anio_plan,
                PlanEstudioDB.cuatrimestre_plan,
                PlanEstudioDB.materia_codigo,
                PlanEstudioDB.optativa,
            )
        ).all())
        # Sólo agregar optativas cuyo (carrera, año, cuatri) ya está
        # en el mapa de grupos (para no inventar grupos nuevos).
        for car, an, cu, mc, opt in pe_rows:
            if not opt or an is None or cu is None:
                continue
            key = (car, an, cu)
            if key in grupos:
                grupos[key] = grupos[key] | {mc}
            # También propagar a grupos enriquecidos: si la materia
            # optativa es Anual, se suma al mismo (carrera, año) del
            # cuatri del ciclo. build_grupos ya hizo el enriched para
            # obligatorias; extendemos para optativas Anual.
            if cu == "Anual":
                for (car2, an2, cu2), mats in list(grupos.items()):
                    if car2 == car and an2 == an:
                        grupos[(car2, an2, cu2)] = mats | {mc}

    # Nombres de carreras (batch fetch).
    carreras_cod = sorted({car for (car, _, _) in grupos.keys()})
    carreras_nombre = {
        c.codigo: c.nombre
        for c in session.exec(
            select(CarreraDB).where(col(CarreraDB.codigo).in_(carreras_cod))
        ).all()
    }

    # Nombres de materias faltantes (batch fetch de todo lo que aparece).
    todas_las_mats = {mc for mats in grupos.values() for mc in mats}
    materias_nombre = {
        m.codigo: m.nombre
        for m in session.exec(
            select(MateriaDB).where(col(MateriaDB.codigo).in_(list(todas_las_mats)))
        ).all()
    } if todas_las_mats else {}

    resultado: list[CarreraAnioCompletitud] = []
    for (car, an, cu), mats in sorted(
        grupos.items(),
        key=lambda kv: (kv[0][0], kv[0][1], kv[0][2]),
    ):
        n_esp = len(mats)
        cubiertas = mats & materias_en_sched
        faltantes = [
            (mc, materias_nombre.get(mc, mc))
            for mc in sorted(mats - cubiertas)
        ]
        resultado.append(CarreraAnioCompletitud(
            carrera_codigo=car,
            carrera_nombre=carreras_nombre.get(car, car),
            anio=an,
            cuatri=cu,
            n_esperadas=n_esp,
            n_cubiertas=len(cubiertas),
            materias_faltantes=faltantes,
        ))
    return resultado
