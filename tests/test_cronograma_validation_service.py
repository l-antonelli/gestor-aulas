"""Tests para cronograma_validation_service.

Foco: que las "materias esperadas" salgan de DictadoDB activos del ciclo
(no del JOIN viejo contra PlanEstudioDB), y que la staleness considere
cambios en el set de dictados activos.
"""

import uuid
from datetime import date, time

import pytest
from sqlalchemy.pool import StaticPool
from sqlmodel import Session, SQLModel, create_engine

from src.database.models import (
    CarreraDB,
    CicloDB,
    CicloPlanVersionDB,
    MateriaDB,
    PlanCarreraVersionDB,
    PlanEstudioDB,
    ScheduleDB,
    ScheduleEntryDB,
)
from src.services.cronograma_validation_service import (
    is_validation_stale,
    persist_validation,
    validar_cronograma,
)
from src.services.dictado_service import (
    create_dictados_for_ciclo,
    get_dictados_for_ciclo,
    update_dictado,
)


# -----------------------------------------------------------------------------
# Fixtures
# -----------------------------------------------------------------------------

@pytest.fixture(name="engine")
def engine_fixture():
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    SQLModel.metadata.create_all(engine)
    return engine


@pytest.fixture(name="session")
def session_fixture(engine):
    with Session(engine) as session:
        yield session


@pytest.fixture
def setup_basic(session):
    """Carrera + plan version + 2 materias + ciclo con plan asignado."""
    carrera = CarreraDB(codigo="ING", nombre="Ingenieria")
    session.add(carrera)
    session.flush()

    pv = PlanCarreraVersionDB(
        id=str(uuid.uuid4()),
        carrera_codigo="ING",
        nombre="Plan Original",
        fecha_creacion=date(2025, 1, 1),
    )
    session.add(pv)
    session.flush()

    m1 = MateriaDB(
        codigo="MAT101", nombre="Calculo I",
        periodo="cuatrimestral", active=True, horas_semanales=6,
    )
    m2 = MateriaDB(
        codigo="FIS101", nombre="Fisica I",
        periodo="cuatrimestral", active=True, horas_semanales=6,
    )
    session.add_all([m1, m2])
    session.flush()

    for m in (m1, m2):
        session.add(PlanEstudioDB(
            plan_version_id=pv.id, materia_codigo=m.codigo,
            carrera_codigo="ING", anio_plan=1, cuatrimestre_plan="1C",
        ))

    ciclo = CicloDB(
        id="2025-1C", anio=2025, numero=1,
        fecha_inicio=date(2025, 3, 10), fecha_fin=date(2025, 7, 5),
    )
    session.add(ciclo)
    session.flush()
    session.add(CicloPlanVersionDB(ciclo_id=ciclo.id, plan_version_id=pv.id))
    session.commit()

    return {"ciclo": ciclo, "pv": pv, "m1": m1, "m2": m2}


def _make_schedule_with_entries(
    session: Session, ciclo_id: str, materia_codigos: list[str],
) -> ScheduleDB:
    sched = ScheduleDB(
        id=str(uuid.uuid4()), ciclo_id=ciclo_id,
        nombre="Test Schedule", fecha_upload=date(2025, 3, 1),
    )
    session.add(sched)
    session.flush()
    for mc in materia_codigos:
        session.add(ScheduleEntryDB(
            id=str(uuid.uuid4()), schedule_id=sched.id,
            codigo_materia=mc, dia="Lunes",
            hora_inicio=time(8, 0), hora_fin=time(11, 0),
            comision=1,
        ))
    session.commit()
    return sched


# -----------------------------------------------------------------------------
# Tests
# -----------------------------------------------------------------------------

class TestSinDictados:
    def test_validar_cronograma_sin_dictados_devuelve_error(
        self, session, setup_basic,
    ):
        """Si el ciclo no tiene dictados, el summary debe traer error
        poblado y no computar el resto."""
        ciclo = setup_basic["ciclo"]
        sched = _make_schedule_with_entries(session, ciclo.id, ["MAT101"])

        summary = validar_cronograma(session, sched.id, ciclo.id)

        assert summary.error is not None
        assert "dictados" in summary.error.lower()
        # No se debe haber computado nada del resumen
        assert summary.n_esperadas == 0
        assert summary.n_clases == 0


class TestEsperadas:
    def test_esperadas_incluye_solo_dictados_activos(
        self, session, setup_basic,
    ):
        """Toggle de activo=False excluye la materia de las esperadas."""
        ciclo = setup_basic["ciclo"]
        # Crear dictados para todas las materias del plan
        create_dictados_for_ciclo(session, ciclo.id)

        # Cronograma con MAT101 (FIS101 sin horarios)
        sched = _make_schedule_with_entries(session, ciclo.id, ["MAT101"])

        summary = validar_cronograma(session, sched.id, ciclo.id)
        assert summary.error is None
        assert summary.n_esperadas == 2  # ambas activas
        assert "MAT101" in summary.esperadas
        assert "FIS101" in summary.esperadas
        assert summary.n_faltantes == 1  # FIS101

        # Desactivar el dictado de FIS101 → debe salir de esperadas
        dictados = get_dictados_for_ciclo(session, ciclo.id)
        d_fis = next(d for d in dictados if d.materia_codigo == "FIS101")
        update_dictado(session, d_fis.id, activo=False)

        summary2 = validar_cronograma(session, sched.id, ciclo.id)
        assert summary2.error is None
        assert summary2.n_esperadas == 1
        assert "FIS101" not in summary2.esperadas
        assert summary2.n_faltantes == 0


class TestFaltantes:
    def test_faltantes_referencia_dictado_codigo(
        self, session, setup_basic,
    ):
        """La razon de un faltante menciona el dictado_codigo."""
        ciclo = setup_basic["ciclo"]
        create_dictados_for_ciclo(session, ciclo.id)

        # Cronograma vacio → todas las materias son faltantes
        sched = _make_schedule_with_entries(session, ciclo.id, [])

        summary = validar_cronograma(session, sched.id, ciclo.id)
        assert summary.n_faltantes == 2

        # Verificar razon
        all_materias = [
            mf
            for grupo in summary.faltantes_por_carrera
            for mf in grupo["materias"]
        ]
        assert len(all_materias) == 2
        for mf in all_materias:
            assert "dictado_codigo" in mf
            # Cuatrimestral → "{materia}-2025-1C"
            assert mf["dictado_codigo"].endswith("-2025-1C")
            assert mf["dictado_codigo"] in mf["razon"]
            assert "sin horarios" in mf["razon"].lower()


class TestExcluirOptativas:
    def test_validar_cronograma_excluir_optativas(
        self, session, setup_basic,
    ):
        """Toggle exclude_optativas filtra SOLO optativas; las virtuales
        siguen contando en la cobertura."""
        ciclo = setup_basic["ciclo"]
        pv = setup_basic["pv"]

        # Marcar FIS101 como virtual (sigue contando)
        fis = setup_basic["m2"]
        fis.virtual = True
        session.add(fis)
        # Agregar materia OPTATIVA
        opt = MateriaDB(
            codigo="OPT101", nombre="Optativa I",
            periodo="cuatrimestral", active=True, horas_semanales=3,
        )
        session.add(opt)
        session.flush()
        session.add(PlanEstudioDB(
            plan_version_id=pv.id, materia_codigo="OPT101",
            carrera_codigo="ING", anio_plan=4, cuatrimestre_plan="1C",
            optativa=True,
        ))
        session.commit()

        create_dictados_for_ciclo(session, ciclo.id)
        sched = _make_schedule_with_entries(session, ciclo.id, ["MAT101"])

        # Sin toggle: 3 esperadas (MAT, FIS virtual, OPT)
        s_off = validar_cronograma(
            session, sched.id, ciclo.id, exclude_optativas=False,
        )
        assert s_off.error is None
        assert s_off.n_esperadas == 3
        assert s_off.excluir_optativas is False
        assert "OPT101" in s_off.esperadas
        assert "FIS101" in s_off.esperadas

        # Con toggle: OPT101 sale; FIS101 (virtual) sigue
        s_on = validar_cronograma(
            session, sched.id, ciclo.id, exclude_optativas=True,
        )
        assert s_on.error is None
        assert s_on.n_esperadas == 2
        assert s_on.excluir_optativas is True
        assert "OPT101" not in s_on.esperadas
        assert "FIS101" in s_on.esperadas


class TestStaleness:
    def test_is_validation_stale_por_cambio_de_dictados(
        self, session, setup_basic,
    ):
        """Si se desactiva un dictado, is_validation_stale = True
        aunque el entry_count del cronograma no haya cambiado."""
        ciclo = setup_basic["ciclo"]
        create_dictados_for_ciclo(session, ciclo.id)

        sched = _make_schedule_with_entries(session, ciclo.id, ["MAT101"])

        summary = validar_cronograma(session, sched.id, ciclo.id)
        record = persist_validation(session, summary)

        # Justo despues de validar, no debe ser stale.
        assert is_validation_stale(session, record) is False

        # Desactivar un dictado → debe pasar a stale
        dictados = get_dictados_for_ciclo(session, ciclo.id)
        d_fis = next(d for d in dictados if d.materia_codigo == "FIS101")
        update_dictado(session, d_fis.id, activo=False)

        # Re-leer el record (la sesion puede haber cacheado)
        session.refresh(record)
        assert is_validation_stale(session, record) is True

    def test_is_validation_stale_por_cambio_de_entries(
        self, session, setup_basic,
    ):
        """Comportamiento heredado: cambio en entry_count tambien marca stale."""
        ciclo = setup_basic["ciclo"]
        create_dictados_for_ciclo(session, ciclo.id)

        sched = _make_schedule_with_entries(session, ciclo.id, ["MAT101"])
        summary = validar_cronograma(session, sched.id, ciclo.id)
        record = persist_validation(session, summary)

        assert is_validation_stale(session, record) is False

        # Agregar una entry → stale
        session.add(ScheduleEntryDB(
            id=str(uuid.uuid4()), schedule_id=sched.id,
            codigo_materia="FIS101", dia="Martes",
            hora_inicio=time(9, 0), hora_fin=time(11, 0),
            comision=1,
        ))
        session.commit()

        assert is_validation_stale(session, record) is True
