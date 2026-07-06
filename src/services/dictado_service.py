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
    - `created`: total de dictados nuevos.
    - `linked`: anuales reutilizados desde el 1C.
    - `skipped`: ya existian (idempotencia).
    - `skipped_recursado`: materias omitidas porque la regla de
      recursado dice que no se dictan en este ciclo. Aparecen en
      `get_skipped_materias_for_ciclo` con la razon; si el usuario
      quiere activarlas puede hacerlo desde la UI.
    """
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


@dataclass
class DriftSummary:
    """Diagnostico del set de dictados de un ciclo vs el plan + reglas
    vigentes. Usado para mostrar un indicador de "cambios pendientes" al
    lado del boton de Sincronizar.

    Semantica nueva: los dictados existen (se dictan) o no existen.
    - `to_create`: materias del plan cuyo dictado NO existe y la regla
      de recursado dice que deberia existir. Sync proponemos crearlos.
    - `to_delete`: dictados existentes cuya materia YA NO esta en
      ningun plan del ciclo (huerfanos). Sync propone borrarlos.
    - `rule_says_skip_but_exists`: dictados existentes cuya regla de
      recursado dice que NO deberian existir. El usuario los creo a
      mano (override implicito). Sync no los toca por defecto; los
      lista como divergencia.
    """
    to_create: list[dict] = field(default_factory=list)
    to_delete: list[dict] = field(default_factory=list)
    rule_says_skip_but_exists: list[dict] = field(default_factory=list)

    @property
    def n_total(self) -> int:
        return (
            len(self.to_create)
            + len(self.to_delete)
            + len(self.rule_says_skip_but_exists)
        )

    @property
    def is_clean(self) -> bool:
        return self.n_total == 0


@dataclass
class SyncResult:
    """Resultado de `sync_dictados_para_ciclo`.

    Contiene el mismo diff que `DriftSummary` mas metadata de la
    operacion. Si `apply=False`, `applied=False` y nada se persistio.
    """
    to_create: list[dict] = field(default_factory=list)
    to_delete: list[dict] = field(default_factory=list)
    rule_says_skip_but_exists: list[dict] = field(default_factory=list)
    applied: bool = False

    @property
    def n_changes(self) -> int:
        return len(self.to_create) + len(self.to_delete)


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

    Aplica la regla "nivel más específico manda" para
    ``dicta_recursado`` (materia > carrera, ver
    ``resolve_dicta_recursado``), con dos matices propios del contexto
    de creación de dictados:

    1. Si la materia es compartida por múltiples carreras, nunca se
       skippea (no hay una "carrera dueña" para heredar).
    2. El flag ``dicta_recursado=False`` (sea heredado o explícito)
       solo skippea si el cuatrimestre del plan de la materia es
       *opuesto* al del ciclo. Si coincide o es anual, se dicta.
    """
    from src.services.resolucion_jerarquica import resolve_dicta_recursado

    # Get the plan_estudio entries for this materia within the ciclo's plan versions
    entries = session.exec(
        select(PlanEstudioDB)
        .where(PlanEstudioDB.materia_codigo == materia.codigo)
        .where(PlanEstudioDB.plan_version_id.in_(plan_version_ids))
    ).all()

    # Collect unique carreras
    carrera_codigos = list({e.carrera_codigo for e in entries})

    # Compartida por múltiples carreras → nunca skip.
    if len(carrera_codigos) != 1:
        return False

    # Exclusiva de una carrera — resolver `dicta_recursado` con jerarquía.
    carrera = session.get(CarreraDB, carrera_codigos[0])
    carrera_flag = carrera.dicta_recursado if carrera is not None else True
    dicta = resolve_dicta_recursado(materia.dicta_recursado, carrera_flag)
    if dicta:
        return False

    # dicta_recursado=False resuelto → evaluar cuatrimestre del plan
    # contra el del ciclo. Si es opuesto, skippear.
    cuatrimestre_ciclo = f"{ciclo.numero}C"
    for entry in entries:
        cuatri = entry.cuatrimestre_plan
        if cuatri is None or cuatri.lower() == "anual" or cuatri == cuatrimestre_ciclo:
            return False

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

        # Recursado: si la regla dice omitir, NO se crea el dictado.
        # La existencia del dictado en el ciclo ES la afirmacion "esta
        # materia se dicta este ciclo". Si despues aparecen horarios en
        # el plan para esta materia, van a saltar como "divergencia"
        # (dictado inexistente) y el usuario puede crearlo desde ahi.
        if materia.periodo == "cuatrimestral" and _should_skip_for_recursado(
            session, materia, ciclo, plan_version_ids,
        ):
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
    """Create a cuatrimestral dictado and link it to the ciclo.

    `virtual` queda en `None` (heredar de la materia via
    `resolve_virtual`). Solo se setea explicito cuando el usuario hace
    un override desde la UI del ciclo.
    """
    dictado_codigo = f"{materia.codigo}-{ciclo.anio}-{ciclo.numero}C"
    dictado_id = str(uuid.uuid4())

    dictado = DictadoDB(
        id=dictado_id,
        materia_codigo=materia.codigo,
        dictado_codigo=dictado_codigo,
        inicio_dictado=ciclo.fecha_inicio,
        fin_dictado=ciclo.fecha_fin,
        virtual=None,
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
    """Create an annual dictado in 1C (fin_dictado=None until 2C links it).

    `virtual` queda en `None` (heredar de la materia).
    """
    dictado_codigo = f"{materia.codigo}-{ciclo.anio}"
    dictado_id = str(uuid.uuid4())

    dictado = DictadoDB(
        id=dictado_id,
        materia_codigo=materia.codigo,
        dictado_codigo=dictado_codigo,
        inicio_dictado=ciclo.fecha_inicio,
        fin_dictado=None,
        virtual=None,
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
        # No 1C dictado found — create a fresh one.
        # `virtual` queda en None (heredar de la materia).
        dictado_id = str(uuid.uuid4())
        dictado = DictadoDB(
            id=dictado_id,
            materia_codigo=materia.codigo,
            dictado_codigo=dictado_codigo_anual,
            inicio_dictado=ciclo.fecha_inicio,
            fin_dictado=ciclo.fecha_fin,
            virtual=None,
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


def _razon_para_dictado(
    session: Session,
    materia: MateriaDB,
    ciclo: CicloDB,
    plan_version_ids: list[str],
) -> str:
    """Devuelve una razón humana del estado esperado de un dictado.

    Verbaliza la lógica de ``_should_skip_for_recursado`` + el caso anual
    para que la UI de "Recalcular según reglas" muestre el motivo legible
    detrás de cada cambio.
    """
    if materia.periodo == "anual":
        return "Materia anual → siempre activa"
    if materia.dicta_recursado is True:
        return "Override de la materia: dicta_recursado=Sí → activa"
    if materia.dicta_recursado is False:
        if _is_opposite_cuatrimestre(session, materia, ciclo, plan_version_ids):
            return (
                "Override de la materia: dicta_recursado=No y la materia "
                "es del cuatrimestre opuesto al ciclo → inactiva"
            )
        return (
            "Override de la materia: dicta_recursado=No pero el ciclo "
            "coincide con su cuatrimestre del plan → activa"
        )
    entries = list(session.exec(
        select(PlanEstudioDB)
        .where(PlanEstudioDB.materia_codigo == materia.codigo)
        .where(PlanEstudioDB.plan_version_id.in_(plan_version_ids))  # type: ignore[attr-defined]
    ).all())
    carrera_codigos = sorted({e.carrera_codigo for e in entries})
    if len(carrera_codigos) > 1:
        return (
            f"Materia compartida entre {len(carrera_codigos)} carreras "
            f"({', '.join(carrera_codigos)}) → activa"
        )
    if not carrera_codigos:
        return "Materia sin entradas en planes asignados al ciclo"
    carrera = session.get(CarreraDB, carrera_codigos[0])
    if carrera is None:
        return f"Carrera {carrera_codigos[0]} no encontrada → activa"
    if carrera.dicta_recursado:
        return f"Carrera {carrera.codigo} dicta recursado → activa"
    cuatri_ciclo = f"{ciclo.numero}C"
    cuatris_plan = sorted({e.cuatrimestre_plan or "?" for e in entries})
    if any(c == cuatri_ciclo or c.lower() == "anual" for c in cuatris_plan):
        return (
            f"Carrera {carrera.codigo} no dicta recursado pero la materia "
            f"figura en el cuatri actual ({cuatri_ciclo}) → activa"
        )
    return (
        f"Carrera {carrera.codigo} no dicta recursado y la materia es del "
        f"cuatri opuesto ({', '.join(cuatris_plan)} vs ciclo {cuatri_ciclo}) "
        f"→ inactiva"
    )


def _build_dictado_item(
    session: Session,
    dictado: Optional[DictadoDB],
    materia: MateriaDB,
    plan_version_ids: list[str],
    ciclo: CicloDB,
    accion: str,
) -> dict:
    """Arma el dict de detalle para una entrada de SyncResult/DriftSummary.

    Args:
        dictado: la fila existente (None si `accion='create'`).
        accion: "create" | "delete" | "keep_but_rule_says_skip".
    """
    entries = list(session.exec(
        select(PlanEstudioDB)
        .where(PlanEstudioDB.materia_codigo == materia.codigo)
        .where(PlanEstudioDB.plan_version_id.in_(plan_version_ids))  # type: ignore[attr-defined]
    ).all())
    carrera_codigos = sorted({e.carrera_codigo for e in entries})
    if len(carrera_codigos) == 1:
        carr = session.get(CarreraDB, carrera_codigos[0])
        carrera_codigo = carrera_codigos[0]
        carrera_nombre = carr.nombre if carr else carrera_codigos[0]
    elif len(carrera_codigos) > 1:
        carrera_codigo = "compartida"
        carrera_nombre = f"Compartida ({', '.join(carrera_codigos)})"
    else:
        carrera_codigo = "—"
        carrera_nombre = "—"
    anio_plan = entries[0].anio_plan if entries else None
    cuatri_plan = entries[0].cuatrimestre_plan if entries else None
    razon = _razon_para_dictado(session, materia, ciclo, plan_version_ids)
    return {
        "dictado_id": dictado.id if dictado else None,
        "materia_codigo": materia.codigo,
        "materia_nombre": materia.nombre,
        "dictado_codigo": (
            dictado.dictado_codigo if dictado
            else f"{materia.codigo}-{ciclo.anio}-{ciclo.numero}C"
        ),
        "carrera_codigo": carrera_codigo,
        "carrera_nombre": carrera_nombre,
        "anio_plan": anio_plan,
        "cuatrimestre_plan": cuatri_plan,
        "accion": accion,
        "razon": razon,
    }


def sync_dictados_para_ciclo(
    session: Session,
    ciclo_id: str,
    apply: bool = False,
) -> SyncResult:
    """Sincroniza el set de dictados del ciclo con el plan + reglas
    vigentes. Semantica nueva: los dictados existen (se dictan) o no
    existen (no se dictan).

    Diff que computa:
    - `to_create`: materias del plan sin dictado en el ciclo y cuya
      regla de recursado dice que deberian existir. `apply=True` los
      crea.
    - `to_delete`: dictados huerfanos (su materia ya NO esta en ningun
      plan del ciclo). `apply=True` los borra.
    - `rule_says_skip_but_exists`: dictados existentes cuya regla dice
      que NO deberian existir (override implicito del usuario). NUNCA
      se borran automaticamente; siempre se listan para revisar.

    Si ``apply=False`` solo devuelve el diff (preview).
    """
    result = SyncResult()

    ciclo = ciclo_crud.get(session, ciclo_id)
    if ciclo is None:
        return result

    plan_version_ids = list(session.exec(
        select(CicloPlanVersionDB.plan_version_id)
        .where(CicloPlanVersionDB.ciclo_id == ciclo_id)
    ).all())
    if not plan_version_ids:
        return result

    # Set de materias del plan.
    materias_plan = list(session.exec(
        select(MateriaDB)
        .join(PlanEstudioDB, MateriaDB.codigo == PlanEstudioDB.materia_codigo)
        .where(PlanEstudioDB.plan_version_id.in_(plan_version_ids))  # type: ignore[attr-defined]
        .distinct()
    ).all())
    materias_plan_by_codigo = {m.codigo: m for m in materias_plan}

    # Set de dictados existentes en el ciclo.
    dictados_existentes = list(session.exec(
        select(DictadoDB)
        .join(DictadoCicloDB, DictadoDB.id == DictadoCicloDB.dictado_id)
        .where(DictadoCicloDB.ciclo_id == ciclo_id)
    ).all())
    dictados_by_codigo = {d.materia_codigo: d for d in dictados_existentes}

    # to_create: en el plan, sin dictado, y regla no dice skippear.
    for materia in materias_plan:
        if materia.codigo in dictados_by_codigo:
            continue
        if materia.periodo == "cuatrimestral" and _should_skip_for_recursado(
            session, materia, ciclo, plan_version_ids,
        ):
            continue
        result.to_create.append(_build_dictado_item(
            session, None, materia, plan_version_ids, ciclo, "create",
        ))

    # to_delete: dictado existe pero la materia ya no esta en el plan.
    # rule_says_skip_but_exists: dictado existe y esta en el plan pero
    # la regla dice skippear.
    for d in dictados_existentes:
        materia = session.get(MateriaDB, d.materia_codigo)
        if materia is None:
            continue
        if d.materia_codigo not in materias_plan_by_codigo:
            result.to_delete.append(_build_dictado_item(
                session, d, materia, plan_version_ids, ciclo, "delete",
            ))
            continue
        if materia.periodo == "cuatrimestral" and _should_skip_for_recursado(
            session, materia, ciclo, plan_version_ids,
        ):
            result.rule_says_skip_but_exists.append(_build_dictado_item(
                session, d, materia, plan_version_ids, ciclo,
                "keep_but_rule_says_skip",
            ))

    if apply:
        # Crear los faltantes.
        for item in result.to_create:
            create_dictado_for_materia(
                session, ciclo_id, item["materia_codigo"],
            )
        # Borrar los huerfanos.
        for item in result.to_delete:
            d_id = item["dictado_id"]
            if d_id is None:
                continue
            # Borrar el bridge primero (FK).
            bridges = list(session.exec(
                select(DictadoCicloDB).where(
                    DictadoCicloDB.dictado_id == d_id,
                )
            ).all())
            for b in bridges:
                session.delete(b)
            # Nullificar clases huerfanas.
            from src.database.models import ClaseDB
            for cl in session.exec(
                select(ClaseDB).where(ClaseDB.dictado_id == d_id)
            ).all():
                cl.dictado_id = None
                session.add(cl)
            d = session.get(DictadoDB, d_id)
            if d is not None:
                session.delete(d)
        session.commit()
        result.applied = True

    return result


def aceptar_materias_en_ciclo(
    session: Session,
    ciclo_id: str,
    materia_codigos: list[str],
    *,
    marcar_virtual: Optional[bool] = None,
) -> int:
    """Crea (o linkea) dictados para las materias indicadas en el ciclo.

    Uso principal: aceptar materias que aparecieron como "extras" en la
    prevalidacion de cronograma. La existencia del dictado indica que
    esa materia se dicta este ciclo.

    Args:
        marcar_virtual: si se pasa, tambien setea `DictadoDB.virtual` con
            ese valor (override explicito). None (default) = no toca el
            flag virtual del dictado creado (queda None → hereda de la
            materia via `resolve_virtual`).

    Returns:
        Cantidad de dictados creados o modificados.
    """
    if not materia_codigos:
        return 0

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
            created = create_dictado_for_materia(session, ciclo_id, mc)
            if created is not None:
                if marcar_virtual is not None:
                    created.virtual = marcar_virtual
                    session.add(created)
                n_changed += 1
        else:
            if marcar_virtual is not None and d.virtual != marcar_virtual:
                d.virtual = marcar_virtual
                session.add(d)
                n_changed += 1

    if n_changed > 0:
        session.commit()
    return n_changed


def borrar_dictado_de_ciclo(
    session: Session, ciclo_id: str, dictado_id: str,
) -> bool:
    """Borra un dictado del ciclo (bridge + fila), nullificando las
    clases huerfanas.

    Uso principal: sync/limpieza de divergencias desde la UI. Es
    idempotente: si el dictado no existe o no esta linkeado al ciclo,
    devuelve False.
    """
    from src.database.models import ClaseDB

    d = session.get(DictadoDB, dictado_id)
    if d is None:
        return False

    # Borrar el bridge (si existe).
    bridges = list(session.exec(
        select(DictadoCicloDB).where(
            DictadoCicloDB.dictado_id == dictado_id,
            DictadoCicloDB.ciclo_id == ciclo_id,
        )
    ).all())
    if not bridges:
        return False
    for b in bridges:
        session.delete(b)

    # Nullificar clases apuntando a este dictado.
    for cl in session.exec(
        select(ClaseDB).where(ClaseDB.dictado_id == dictado_id)
    ).all():
        cl.dictado_id = None
        session.add(cl)

    # Si no queda ningun bridge (el dictado no aparece en otros ciclos),
    # borrar la fila `dictados`.
    otros_bridges = list(session.exec(
        select(DictadoCicloDB).where(
            DictadoCicloDB.dictado_id == dictado_id,
        )
    ).all())
    if not otros_bridges:
        session.delete(d)

    session.commit()
    return True


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
    """Devuelve un diagnostico de divergencias del ciclo vs el plan +
    reglas vigentes.

    Wrapper thin sobre `sync_dictados_para_ciclo(apply=False)`: la
    logica esta ahi. Este helper solo re-empaqueta al shape DriftSummary
    para consumo por la UI.
    """
    summary = DriftSummary()
    sync = sync_dictados_para_ciclo(session, ciclo_id, apply=False)
    summary.to_create = list(sync.to_create)
    summary.to_delete = list(sync.to_delete)
    summary.rule_says_skip_but_exists = list(sync.rule_says_skip_but_exists)
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
    """Return {materia_codigo: materia_nombre} de dictados del ciclo.

    Fuente de verdad de "materias esperadas" para la prevalidacion de
    cronogramas. Nueva semantica: la existencia del dictado en el ciclo
    ES la afirmacion "esta materia se dicta este ciclo".
    """
    statement = (
        select(MateriaDB.codigo, MateriaDB.nombre)
        .join(DictadoDB, MateriaDB.codigo == DictadoDB.materia_codigo)
        .join(DictadoCicloDB, DictadoDB.id == DictadoCicloDB.dictado_id)
        .where(DictadoCicloDB.ciclo_id == ciclo_id)
        .distinct()
    )
    rows = session.exec(statement).all()
    return {codigo: nombre for codigo, nombre in rows}


def get_dictado_codigos_for_ciclo(
    session: Session, ciclo_id: str,
) -> dict[str, str]:
    """Return {materia_codigo: dictado_codigo} para los dictados del ciclo."""
    statement = (
        select(DictadoDB.materia_codigo, DictadoDB.dictado_codigo)
        .join(DictadoCicloDB, DictadoDB.id == DictadoCicloDB.dictado_id)
        .where(DictadoCicloDB.ciclo_id == ciclo_id)
    )
    rows = session.exec(statement).all()
    return {mat_cod: dic_cod for mat_cod, dic_cod in rows}


def count_active_dictados_for_ciclo(session: Session, ciclo_id: str) -> int:
    """Count of dictados linkeados al ciclo (todos existen → activos)."""
    statement = (
        select(func.count(DictadoDB.id))
        .join(DictadoCicloDB, DictadoDB.id == DictadoCicloDB.dictado_id)
        .where(DictadoCicloDB.ciclo_id == ciclo_id)
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
