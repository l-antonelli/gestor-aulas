"""Service for creating and managing Dictados for academic cycles."""

import uuid
from dataclasses import dataclass, field
from typing import Optional

from sqlmodel import Session, col, select, func

from src.database.models import (
    CarreraDB, CicloDB, DictadoDB, DictadoCicloDB, MateriaDB,
    CicloPlanVersionDB, PlanCarreraVersionDB, PlanEstudioDB,
)
from src.database.crud import ciclo_crud, materia_crud, dictado_crud


@dataclass
class DictadoCreationResult:
    """Result of creating dictados for a ciclo.

    Notas:
    - `created`: total de dictados nuevos (cualquier estado).
    - `created_inactive`: subset de `created` que arranco con `activo=False`
      por aplicar la regla de `dicta_recursado`. Quedan persistidos para que
      el usuario pueda activarlos manualmente o re-correr `recompute_activo`.
    - `linked`: anuales reutilizados desde el 1C.
    - `skipped`: ya existian (idempotencia).
    - `skipped_recursado`: deprecated, queda en 0; conservamos el campo por
      compat. Las que antes caian aca ahora son `created_inactive`.
    """
    created: int = 0
    created_inactive: int = 0
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


@dataclass
class DriftSummary:
    """Diagnostico del estado del set de dictados de un ciclo vs el plan
    + reglas vigentes. Usado para mostrar un indicador de "cambios pendientes"
    al lado del boton de Recalcular.

    - `recompute_to_activate` / `recompute_to_deactivate`: dictados que
      quedarian `activo=True/False` si se corre Recalcular ahora. Surgen
      cuando se cambio `dicta_recursado` (carrera o materia) sin alinear.
    - `missing_materias`: materias del plan que NO tienen dictado linkeado.
      Surgen al swap de plan o al agregar materias al plan despues de
      "Crear Dictados".
    - `orphan_dictados`: dictados que existen para materias que ya NO estan
      en ningun plan asignado al ciclo. Surgen al swap de plan a otra
      version sin las mismas materias.
    """
    recompute_to_activate: list[tuple[str, str]] = field(default_factory=list)
    recompute_to_deactivate: list[tuple[str, str]] = field(default_factory=list)
    missing_materias: list[tuple[str, str]] = field(default_factory=list)
    orphan_dictados: list[tuple[str, str]] = field(default_factory=list)

    @property
    def n_total(self) -> int:
        return (
            len(self.recompute_to_activate)
            + len(self.recompute_to_deactivate)
            + len(self.missing_materias)
            + len(self.orphan_dictados)
        )

    @property
    def is_clean(self) -> bool:
        return self.n_total == 0


@dataclass
class RecomputeResult:
    """Diff de un recompute de `activo` segun reglas de recursado.

    Cada lista es una tupla `(materia_codigo, dictado_codigo)`. El total se
    obtiene sumando ambas listas. `applied=True` si el cambio fue persistido.
    """
    to_activate: list[tuple[str, str]] = field(default_factory=list)
    to_deactivate: list[tuple[str, str]] = field(default_factory=list)
    unchanged: int = 0
    applied: bool = False

    @property
    def n_changes(self) -> int:
        return len(self.to_activate) + len(self.to_deactivate)


def _is_opposite_cuatrimestre(
    session: Session,
    materia: MateriaDB,
    ciclo: CicloDB,
    plan_version_ids: list[str],
) -> bool:
    """True si TODAS las apariciones de la materia en los planes del ciclo
    son del cuatrimestre opuesto (ni anual ni del mismo cuatri).
    """
    entries = session.exec(
        select(PlanEstudioDB)
        .where(PlanEstudioDB.materia_codigo == materia.codigo)
        .where(PlanEstudioDB.plan_version_id.in_(plan_version_ids))
    ).all()
    cuatrimestre_ciclo = f"{ciclo.numero}C"
    for entry in entries:
        cuatri = entry.cuatrimestre_plan
        if cuatri is None or cuatri.lower() == "anual" or cuatri == cuatrimestre_ciclo:
            return False
    return bool(entries)


def _should_skip_for_recursado(
    session: Session,
    materia: MateriaDB,
    ciclo: CicloDB,
    plan_version_ids: list[str],
) -> bool:
    """Check if a cuatrimestral materia should be skipped due to dicta_recursado=False.

    Logic (override jerarquico):
    1. `MateriaDB.dicta_recursado` — si esta seteado (True/False), gana
       sobre el flag de la carrera. None = caer al default de carrera.
    2. Si la materia aparece en multiples carreras → nunca skip (compartida).
    3. Si es exclusiva de una carrera y esa carrera tiene
       `dicta_recursado=False`, evalua el cuatrimestre_plan:
       - matches al cuatri del ciclo o "Anual" → no skip.
       - opuesto → skip.
    """
    # Override por materia (gana sobre todo)
    if materia.dicta_recursado is True:
        return False
    # Si la materia explicitamente NO recursa, evaluamos cuatrimestre vs ciclo
    if materia.dicta_recursado is False:
        return _is_opposite_cuatrimestre(
            session, materia, ciclo, plan_version_ids,
        )

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

        # Recursado: si la regla dice omitir, igual creamos el dictado pero
        # con activo=False. Ya no skipea; quedan registrados para edicion
        # on-the-fly desde la UI.
        _should_be_inactive = (
            materia.periodo == "cuatrimestral"
            and _should_skip_for_recursado(
                session, materia, ciclo, plan_version_ids,
            )
        )
        _initial_activo = not _should_be_inactive

        if materia.periodo == "cuatrimestral":
            _create_cuatrimestral_dictado(
                session, materia, ciclo, result, activo=_initial_activo,
            )
        elif materia.periodo == "anual":
            if ciclo.numero == 1:
                _create_anual_dictado_1c(
                    session, materia, ciclo, result, activo=_initial_activo,
                )
            else:
                _link_anual_dictado_2c(session, materia, ciclo, result)

        if _should_be_inactive:
            result.created_inactive += 1

    session.commit()
    return result


def _create_cuatrimestral_dictado(
    session: Session,
    materia: MateriaDB,
    ciclo: CicloDB,
    result: DictadoCreationResult,
    activo: bool = True,
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
        activo=activo,
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
    activo: bool = True,
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
        activo=activo,
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


def recompute_activo_for_ciclo(
    session: Session, ciclo_id: str, apply: bool = False,
) -> RecomputeResult:
    """Recalcula `activo` de cada dictado del ciclo segun las reglas vigentes.

    Para cada dictado del ciclo:
    - cuatrimestrales con `_should_skip_for_recursado` → activo=False (esperado)
    - resto → activo=True (esperado)

    Si `apply=False` solo devuelve el diff (preview). Si `apply=True` persiste
    los cambios. Materias dadas de baja por el usuario manualmente seran
    re-activadas si la regla actual lo dicta — quien aprieta "Recalcular"
    confirma que quiere alinear todo a las reglas. Para overrides puntuales,
    el usuario puede tocar el toggle a mano despues.

    Returns:
        RecomputeResult con `to_activate`, `to_deactivate`, `unchanged`,
        y `applied=True` si se persistio.
    """
    result = RecomputeResult()

    ciclo = ciclo_crud.get(session, ciclo_id)
    if ciclo is None:
        return result

    plan_version_ids = list(session.exec(
        select(CicloPlanVersionDB.plan_version_id)
        .where(CicloPlanVersionDB.ciclo_id == ciclo_id)
    ).all())
    if not plan_version_ids:
        return result

    dictados = list(session.exec(
        select(DictadoDB)
        .join(DictadoCicloDB, DictadoDB.id == DictadoCicloDB.dictado_id)
        .where(DictadoCicloDB.ciclo_id == ciclo_id)
    ).all())

    for d in dictados:
        materia = session.get(MateriaDB, d.materia_codigo)
        if materia is None:
            continue
        # Anuales no se ven afectadas por la regla de recursado
        if materia.periodo == "anual":
            expected_activo = True
        else:
            expected_activo = not _should_skip_for_recursado(
                session, materia, ciclo, plan_version_ids,
            )

        if expected_activo == d.activo:
            result.unchanged += 1
        elif expected_activo:
            result.to_activate.append((d.materia_codigo, d.dictado_codigo))
            if apply:
                d.activo = True
                session.add(d)
        else:
            result.to_deactivate.append((d.materia_codigo, d.dictado_codigo))
            if apply:
                d.activo = False
                session.add(d)

    if apply and result.n_changes > 0:
        session.commit()
        result.applied = True

    return result


def set_activo_for_materias_in_ciclo(
    session: Session, ciclo_id: str, materia_codigos: list[str], activo: bool,
) -> int:
    """Setear `activo` en bulk para los dictados de las materias indicadas
    dentro de un ciclo. Crea el dictado si no existe (cuando `activo=True`
    y la materia es del plan).

    Returns:
        cantidad de dictados efectivamente actualizados/creados.
    """
    if not materia_codigos:
        return 0

    # Pull dictados existentes para esas materias en el ciclo
    existing = list(session.exec(
        select(DictadoDB)
        .join(DictadoCicloDB, DictadoDB.id == DictadoCicloDB.dictado_id)
        .where(DictadoCicloDB.ciclo_id == ciclo_id)
        .where(col(DictadoDB.materia_codigo).in_(materia_codigos))
    ).all())
    existing_by_mat = {d.materia_codigo: d for d in existing}

    n_changed = 0
    for mc in materia_codigos:
        d = existing_by_mat.get(mc)
        if d is None:
            if activo:
                # Crear on-the-fly
                created = create_dictado_for_materia(session, ciclo_id, mc)
                if created is not None:
                    n_changed += 1
            # Si activo=False y no existe, no hacemos nada
            continue
        if d.activo != activo:
            d.activo = activo
            session.add(d)
            n_changed += 1

    if n_changed > 0:
        session.commit()
    return n_changed


def create_dictado_for_materia(
    session: Session, ciclo_id: str, materia_codigo: str,
) -> Optional[DictadoDB]:
    """Crear (o linkear) un dictado para una materia puntual en un ciclo.

    Decision explicita del usuario: a diferencia de `create_dictados_for_ciclo`,
    NO aplica el skip por dicta_recursado — si el usuario aprieta "Activar"
    sobre una materia sin dictado, asumimos que quiere ofrecerla en este
    ciclo aunque la heuristica por defecto haya sugerido omitirla.

    Returns:
        El DictadoDB recien creado/linkeado. None si la materia o el ciclo
        no existen, o si ya hay un dictado linkeado para esta materia en
        este ciclo (idempotente).
    """
    ciclo = ciclo_crud.get(session, ciclo_id)
    if ciclo is None:
        return None

    materia = session.get(MateriaDB, materia_codigo)
    if materia is None:
        return None

    # Idempotencia: si ya hay link, devolver el dictado existente.
    existing_link = session.exec(
        select(DictadoCicloDB)
        .join(DictadoDB, DictadoDB.id == DictadoCicloDB.dictado_id)
        .where(DictadoCicloDB.ciclo_id == ciclo_id)
        .where(DictadoDB.materia_codigo == materia_codigo)
    ).first()
    if existing_link is not None:
        return session.get(DictadoDB, existing_link.dictado_id)

    result = DictadoCreationResult()
    if materia.periodo == "anual" and ciclo.numero == 2:
        _link_anual_dictado_2c(session, materia, ciclo, result)
    elif materia.periodo == "anual":
        _create_anual_dictado_1c(session, materia, ciclo, result)
    else:
        _create_cuatrimestral_dictado(session, materia, ciclo, result)
    session.commit()

    # Recuperar el dictado recien linkeado
    link = session.exec(
        select(DictadoCicloDB)
        .join(DictadoDB, DictadoDB.id == DictadoCicloDB.dictado_id)
        .where(DictadoCicloDB.ciclo_id == ciclo_id)
        .where(DictadoDB.materia_codigo == materia_codigo)
    ).first()
    if link is None:
        return None
    return session.get(DictadoDB, link.dictado_id)


def get_drift_summary(session: Session, ciclo_id: str) -> DriftSummary:
    """Devuelve un diagnostico de cambios pendientes para los dictados del ciclo.

    Combina tres chequeos:
    1. Recompute pendiente: corre `recompute_activo_for_ciclo(apply=False)`
       y reporta los flips esperados.
    2. Materias del plan sin dictado linkeado.
    3. Dictados huerfanos (linkeados al ciclo pero la materia ya no esta
       en ningun plan asignado).
    """
    summary = DriftSummary()

    # 1) recompute drift
    rec = recompute_activo_for_ciclo(session, ciclo_id, apply=False)
    summary.recompute_to_activate = list(rec.to_activate)
    summary.recompute_to_deactivate = list(rec.to_deactivate)

    # Plan version ids del ciclo
    plan_version_ids = list(session.exec(
        select(CicloPlanVersionDB.plan_version_id)
        .where(CicloPlanVersionDB.ciclo_id == ciclo_id)
    ).all())
    if not plan_version_ids:
        return summary

    # Materias del plan
    plan_mat_codigos = set(session.exec(
        select(PlanEstudioDB.materia_codigo)
        .where(col(PlanEstudioDB.plan_version_id).in_(plan_version_ids))
        .distinct()
    ).all())

    # Dictados linkeados al ciclo
    linked_dicts = list(session.exec(
        select(DictadoDB)
        .join(DictadoCicloDB, DictadoDB.id == DictadoCicloDB.dictado_id)
        .where(DictadoCicloDB.ciclo_id == ciclo_id)
    ).all())
    linked_mat_codigos = {d.materia_codigo for d in linked_dicts}

    # 2) materias del plan sin dictado
    missing = plan_mat_codigos - linked_mat_codigos
    if missing:
        nombre_map = {
            m.codigo: m.nombre for m in session.exec(
                select(MateriaDB).where(col(MateriaDB.codigo).in_(list(missing)))
            ).all()
        }
        summary.missing_materias = sorted(
            (mc, nombre_map.get(mc, "?")) for mc in missing
        )

    # 3) dictados huerfanos (existen pero la materia no esta en ningun plan)
    orphans = [d for d in linked_dicts if d.materia_codigo not in plan_mat_codigos]
    summary.orphan_dictados = sorted(
        (d.materia_codigo, d.dictado_codigo) for d in orphans
    )

    return summary


def swap_plan_version_for_ciclo(
    session: Session,
    ciclo_id: str,
    carrera_codigo: str,
    new_plan_version_id: str,
) -> bool:
    """Cambia la plan version asignada al ciclo para una carrera puntual.

    Borra el `CicloPlanVersionDB` de la version vieja (de esa carrera en
    ese ciclo) y crea uno nuevo apuntando a `new_plan_version_id`. Si la
    nueva version no pertenece a la carrera indicada, no hace nada y
    devuelve False.

    No toca dictados existentes — el usuario deberia apretar "Recalcular
    segun reglas" despues para alinear con las materias del nuevo plan.

    Returns:
        True si se aplico el cambio, False si no fue valido o no hubo cambio.
    """
    new_pv = session.get(PlanCarreraVersionDB, new_plan_version_id)
    if new_pv is None or new_pv.carrera_codigo != carrera_codigo:
        return False

    # Buscar links existentes para esa carrera en ese ciclo
    existing_links = list(session.exec(
        select(CicloPlanVersionDB)
        .join(
            PlanCarreraVersionDB,
            CicloPlanVersionDB.plan_version_id == PlanCarreraVersionDB.id,
        )
        .where(CicloPlanVersionDB.ciclo_id == ciclo_id)
        .where(PlanCarreraVersionDB.carrera_codigo == carrera_codigo)
    ).all())

    # Si ya esta el target linkeado, nada que hacer
    if any(l.plan_version_id == new_plan_version_id for l in existing_links):
        return False

    for link in existing_links:
        session.delete(link)
    session.add(CicloPlanVersionDB(
        ciclo_id=ciclo_id, plan_version_id=new_plan_version_id,
    ))
    session.commit()
    return True


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


def get_materias_esperadas_from_dictados(
    session: Session, ciclo_id: str,
) -> dict[str, str]:
    """Return {materia_codigo: materia_nombre} de dictados ACTIVOS para el ciclo.

    Esta es la fuente de verdad de "materias esperadas" para la prevalidacion
    de cronogramas. Solo considera dictados con activo=True linkeados al ciclo
    via DictadoCicloDB.
    """
    statement = (
        select(MateriaDB.codigo, MateriaDB.nombre)
        .join(DictadoDB, MateriaDB.codigo == DictadoDB.materia_codigo)
        .join(DictadoCicloDB, DictadoDB.id == DictadoCicloDB.dictado_id)
        .where(DictadoCicloDB.ciclo_id == ciclo_id)
        .where(DictadoDB.activo == True)  # noqa: E712
        .distinct()
    )
    rows = session.exec(statement).all()
    return {codigo: nombre for codigo, nombre in rows}


def get_dictado_codigos_for_ciclo(
    session: Session, ciclo_id: str, only_active: bool = True,
) -> dict[str, str]:
    """Return {materia_codigo: dictado_codigo} para los dictados del ciclo."""
    statement = (
        select(DictadoDB.materia_codigo, DictadoDB.dictado_codigo)
        .join(DictadoCicloDB, DictadoDB.id == DictadoCicloDB.dictado_id)
        .where(DictadoCicloDB.ciclo_id == ciclo_id)
    )
    if only_active:
        statement = statement.where(DictadoDB.activo == True)  # noqa: E712
    rows = session.exec(statement).all()
    return {mat_cod: dic_cod for mat_cod, dic_cod in rows}


def count_active_dictados_for_ciclo(session: Session, ciclo_id: str) -> int:
    """Count of active dictados linkeados al ciclo."""
    statement = (
        select(func.count(DictadoDB.id))
        .join(DictadoCicloDB, DictadoDB.id == DictadoCicloDB.dictado_id)
        .where(DictadoCicloDB.ciclo_id == ciclo_id)
        .where(DictadoDB.activo == True)  # noqa: E712
    )
    return session.exec(statement).one()


def has_dictados_for_ciclo(session: Session, ciclo_id: str) -> bool:
    """True si existe al menos un dictado (activo o no) linkeado al ciclo."""
    statement = (
        select(func.count(DictadoCicloDB.dictado_id))
        .where(DictadoCicloDB.ciclo_id == ciclo_id)
    )
    return session.exec(statement).one() > 0


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
