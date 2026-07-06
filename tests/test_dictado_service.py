"""Tests for dictado_service."""

import uuid
import pytest
from datetime import date

from sqlmodel import Session, SQLModel, create_engine, select
from sqlalchemy.pool import StaticPool

from src.database.models import (
    CicloDB, MateriaDB, CarreraDB, DictadoDB,
    PlanCarreraVersionDB, PlanEstudioDB, CicloPlanVersionDB,
)
from src.services.dictado_service import (
    aceptar_materias_en_ciclo,
    borrar_dictado_de_ciclo,
    create_dictado_for_materia,
    create_dictados_for_ciclo,
    get_dictados_for_ciclo,
    get_skipped_materias_for_ciclo,
    promover_a_regla,
    sync_dictados_para_ciclo,
    update_dictado,
)


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
def carrera(session):
    c = CarreraDB(codigo="ING", nombre="Ingenieria", duracion_anios=5)
    session.add(c)
    session.commit()
    return c


@pytest.fixture
def plan_version(session, carrera):
    v = PlanCarreraVersionDB(
        id=str(uuid.uuid4()),
        carrera_codigo=carrera.codigo,
        nombre="Plan Original",
        fecha_creacion=date(2025, 1, 1),
    )
    session.add(v)
    session.commit()
    return v


@pytest.fixture
def ciclo_1c(session, plan_version):
    ciclo = CicloDB(
        id="2025-1C", anio=2025, numero=1,
        fecha_inicio=date(2025, 3, 10), fecha_fin=date(2025, 7, 5),
    )
    session.add(ciclo)
    session.flush()
    # Assign plan version to ciclo
    link = CicloPlanVersionDB(ciclo_id=ciclo.id, plan_version_id=plan_version.id)
    session.add(link)
    session.commit()
    return ciclo


@pytest.fixture
def ciclo_2c(session, plan_version):
    ciclo = CicloDB(
        id="2025-2C", anio=2025, numero=2,
        fecha_inicio=date(2025, 8, 11), fecha_fin=date(2025, 12, 5),
    )
    session.add(ciclo)
    session.flush()
    link = CicloPlanVersionDB(ciclo_id=ciclo.id, plan_version_id=plan_version.id)
    session.add(link)
    session.commit()
    return ciclo


@pytest.fixture
def materias(session, plan_version):
    m1 = MateriaDB(
        codigo="MAT101", nombre="Calculo I",
        periodo="cuatrimestral", active=True,
    )
    m2 = MateriaDB(
        codigo="FIS101", nombre="Fisica I",
        periodo="anual", active=True,
    )
    m3 = MateriaDB(
        codigo="HIS101", nombre="Historia",
        periodo="cuatrimestral", active=False,
    )
    session.add_all([m1, m2, m3])
    session.flush()

    # Add active materias to plan version (HIS101 intentionally excluded)
    for m in [m1, m2]:
        pe = PlanEstudioDB(
            plan_version_id=plan_version.id,
            materia_codigo=m.codigo,
            carrera_codigo=plan_version.carrera_codigo,
            anio_plan=1,
            cuatrimestre_plan="1C",
        )
        session.add(pe)
    session.commit()
    return [m1, m2, m3]


class TestCreateDictadosForCiclo:

    def test_creates_cuatrimestral_dictados(self, session, ciclo_1c, materias):
        result = create_dictados_for_ciclo(session, "2025-1C")

        # MAT101 (cuatrimestral) + FIS101 (anual, 1C creates)
        assert result.created == 2
        assert result.skipped == 0
        assert result.errors == []

        dictados = get_dictados_for_ciclo(session, "2025-1C")
        assert len(dictados) == 2

        codigos = {d.dictado_codigo for d in dictados}
        assert "MAT101-2025-1C" in codigos
        assert "FIS101-2025" in codigos

    def test_materia_not_in_plan_skipped(self, session, ciclo_1c, materias):
        """HIS101 is not in the plan version, so it should not get a dictado."""
        result = create_dictados_for_ciclo(session, "2025-1C")

        dictados = get_dictados_for_ciclo(session, "2025-1C")
        materia_codigos = {d.materia_codigo for d in dictados}
        assert "HIS101" not in materia_codigos

    def test_idempotent(self, session, ciclo_1c, materias):
        result1 = create_dictados_for_ciclo(session, "2025-1C")
        result2 = create_dictados_for_ciclo(session, "2025-1C")

        assert result2.created == 0
        assert result2.skipped == 2  # MAT101 + FIS101

    def test_anual_2c_links_existing(self, session, ciclo_1c, ciclo_2c, materias):
        result_1c = create_dictados_for_ciclo(session, "2025-1C")
        assert result_1c.created == 2

        result_2c = create_dictados_for_ciclo(session, "2025-2C")

        assert result_2c.created == 1  # MAT101 cuatrimestral
        assert result_2c.linked == 1  # FIS101 anual

        dictados_1c = get_dictados_for_ciclo(session, "2025-1C")
        dictados_2c = get_dictados_for_ciclo(session, "2025-2C")

        fis_1c = [d for d in dictados_1c if d.materia_codigo == "FIS101"]
        fis_2c = [d for d in dictados_2c if d.materia_codigo == "FIS101"]

        assert len(fis_1c) == 1
        assert len(fis_2c) == 1
        assert fis_1c[0].id == fis_2c[0].id
        assert fis_2c[0].fin_dictado == date(2025, 12, 5)

    def test_anual_2c_without_1c_creates_new(self, session, ciclo_2c, materias):
        result = create_dictados_for_ciclo(session, "2025-2C")

        assert result.created == 2
        assert result.linked == 0

    def test_invalid_ciclo(self, session):
        result = create_dictados_for_ciclo(session, "NONEXISTENT")
        assert len(result.errors) == 1
        assert "no encontrado" in result.errors[0]

    def test_ciclo_without_plan_versions_errors(self, session):
        """A ciclo with no plan versions assigned should return an error."""
        ciclo = CicloDB(
            id="2025-1C-NOPLAN", anio=2025, numero=1,
            fecha_inicio=date(2025, 3, 10), fecha_fin=date(2025, 7, 5),
        )
        session.add(ciclo)
        session.commit()

        result = create_dictados_for_ciclo(session, "2025-1C-NOPLAN")
        assert len(result.errors) == 1
        assert "versiones de plan" in result.errors[0]
        assert result.created == 0


class TestDictaRecursado:
    """Tests for dicta_recursado logic in dictado creation."""

    def test_exclusive_materia_skipped_when_no_recursado(self, session):
        """A cuatrimestral materia exclusive to one carrera with dicta_recursado=False
        and assigned to 2C should be SKIPPED (no dictado created) when creating
        dictados for 1C. La ausencia del dictado ES la afirmacion "no se dicta"."""
        # Carrera that does NOT dicta recursado
        carrera = CarreraDB(
            codigo="LIC", nombre="Licenciatura", duracion_anios=4,
            dicta_recursado=False,
        )
        session.add(carrera)
        session.flush()

        pv = PlanCarreraVersionDB(
            id=str(uuid.uuid4()), carrera_codigo="LIC",
            nombre="Plan LIC", fecha_creacion=date(2025, 1, 1),
        )
        session.add(pv)
        session.flush()

        # Materia assigned to 2C in this carrera
        mat = MateriaDB(
            codigo="QUI201", nombre="Quimica II",
            periodo="cuatrimestral", active=True,
        )
        session.add(mat)
        session.flush()

        pe = PlanEstudioDB(
            plan_version_id=pv.id, materia_codigo="QUI201",
            carrera_codigo="LIC", anio_plan=2, cuatrimestre_plan="2C",
        )
        session.add(pe)

        # Ciclo 1C with this plan version
        ciclo = CicloDB(
            id="2025-1C-LIC", anio=2025, numero=1,
            fecha_inicio=date(2025, 3, 10), fecha_fin=date(2025, 7, 5),
        )
        session.add(ciclo)
        session.flush()
        link = CicloPlanVersionDB(ciclo_id=ciclo.id, plan_version_id=pv.id)
        session.add(link)
        session.commit()

        result = create_dictados_for_ciclo(session, "2025-1C-LIC")

        # No se crea: la regla dice skippear.
        assert result.created == 0
        assert result.skipped_recursado == 1

        dictados = get_dictados_for_ciclo(session, "2025-1C-LIC")
        assert len(dictados) == 0

    def test_exclusive_materia_not_skipped_when_same_cuatrimestre(self, session):
        """A materia assigned to 1C should NOT be skipped in 1C even when
        dicta_recursado=False."""
        carrera = CarreraDB(
            codigo="LIC2", nombre="Licenciatura 2", duracion_anios=4,
            dicta_recursado=False,
        )
        session.add(carrera)
        session.flush()

        pv = PlanCarreraVersionDB(
            id=str(uuid.uuid4()), carrera_codigo="LIC2",
            nombre="Plan LIC2", fecha_creacion=date(2025, 1, 1),
        )
        session.add(pv)
        session.flush()

        mat = MateriaDB(
            codigo="QUI101", nombre="Quimica I",
            periodo="cuatrimestral", active=True,
        )
        session.add(mat)
        session.flush()

        pe = PlanEstudioDB(
            plan_version_id=pv.id, materia_codigo="QUI101",
            carrera_codigo="LIC2", anio_plan=1, cuatrimestre_plan="1C",
        )
        session.add(pe)

        ciclo = CicloDB(
            id="2025-1C-LIC2", anio=2025, numero=1,
            fecha_inicio=date(2025, 3, 10), fecha_fin=date(2025, 7, 5),
        )
        session.add(ciclo)
        session.flush()
        link = CicloPlanVersionDB(ciclo_id=ciclo.id, plan_version_id=pv.id)
        session.add(link)
        session.commit()

        result = create_dictados_for_ciclo(session, "2025-1C-LIC2")

        assert result.created == 1
        assert result.skipped_recursado == 0

    def test_shared_materia_never_skipped(self, session):
        """A materia shared across two carreras is never skipped,
        even if one carrera has dicta_recursado=False."""
        c1 = CarreraDB(
            codigo="C1", nombre="Carrera 1", dicta_recursado=False,
        )
        c2 = CarreraDB(
            codigo="C2", nombre="Carrera 2", dicta_recursado=True,
        )
        session.add_all([c1, c2])
        session.flush()

        pv1 = PlanCarreraVersionDB(
            id=str(uuid.uuid4()), carrera_codigo="C1",
            nombre="Plan C1", fecha_creacion=date(2025, 1, 1),
        )
        pv2 = PlanCarreraVersionDB(
            id=str(uuid.uuid4()), carrera_codigo="C2",
            nombre="Plan C2", fecha_creacion=date(2025, 1, 1),
        )
        session.add_all([pv1, pv2])
        session.flush()

        mat = MateriaDB(
            codigo="SHARED01", nombre="Materia Compartida",
            periodo="cuatrimestral", active=True,
        )
        session.add(mat)
        session.flush()

        # Shared materia in both carreras, assigned to 2C
        pe1 = PlanEstudioDB(
            plan_version_id=pv1.id, materia_codigo="SHARED01",
            carrera_codigo="C1", anio_plan=1, cuatrimestre_plan="2C",
        )
        pe2 = PlanEstudioDB(
            plan_version_id=pv2.id, materia_codigo="SHARED01",
            carrera_codigo="C2", anio_plan=1, cuatrimestre_plan="2C",
        )
        session.add_all([pe1, pe2])

        ciclo = CicloDB(
            id="2025-1C-SHARED", anio=2025, numero=1,
            fecha_inicio=date(2025, 3, 10), fecha_fin=date(2025, 7, 5),
        )
        session.add(ciclo)
        session.flush()
        session.add(CicloPlanVersionDB(ciclo_id=ciclo.id, plan_version_id=pv1.id))
        session.add(CicloPlanVersionDB(ciclo_id=ciclo.id, plan_version_id=pv2.id))
        session.commit()

        result = create_dictados_for_ciclo(session, "2025-1C-SHARED")

        assert result.created == 1
        assert result.skipped_recursado == 0

    def test_materia_override_recursado_true_beats_carrera_false(self, session):
        """Si MateriaDB.dicta_recursado=True, se crea activo aunque la
        carrera sea dicta_recursado=False y el cuatri sea opuesto."""
        carrera = CarreraDB(
            codigo="OVR1", nombre="Override 1", dicta_recursado=False,
        )
        session.add(carrera)
        session.flush()
        pv = PlanCarreraVersionDB(
            id=str(uuid.uuid4()), carrera_codigo="OVR1",
            nombre="Plan OVR1", fecha_creacion=date(2025, 1, 1),
        )
        session.add(pv)
        session.flush()
        mat = MateriaDB(
            codigo="OVR01", nombre="Override M",
            periodo="cuatrimestral", active=True,
            dicta_recursado=True,  # override explicito
        )
        session.add(mat)
        session.flush()
        session.add(PlanEstudioDB(
            plan_version_id=pv.id, materia_codigo="OVR01",
            carrera_codigo="OVR1", anio_plan=1, cuatrimestre_plan="2C",
        ))
        ciclo = CicloDB(
            id="2025-1C-OVR1", anio=2025, numero=1,
            fecha_inicio=date(2025, 3, 10), fecha_fin=date(2025, 7, 5),
        )
        session.add(ciclo)
        session.flush()
        session.add(CicloPlanVersionDB(
            ciclo_id=ciclo.id, plan_version_id=pv.id,
        ))
        session.commit()

        result = create_dictados_for_ciclo(session, "2025-1C-OVR1")
        assert result.created == 1
        assert result.skipped_recursado == 0  # se creo (override materia gana)

        d = get_dictados_for_ciclo(session, "2025-1C-OVR1")[0]
        assert d is not None  # existe → se dicta

    def test_materia_override_recursado_false_beats_carrera_true(self, session):
        """Si MateriaDB.dicta_recursado=False y el cuatri es opuesto,
        NO se crea el dictado aunque la carrera sea dicta_recursado=True.
        El override a nivel materia gana (regla "nivel mas especifico manda").
        """
        carrera = CarreraDB(
            codigo="OVR2", nombre="Override 2", dicta_recursado=True,
        )
        session.add(carrera)
        session.flush()
        pv = PlanCarreraVersionDB(
            id=str(uuid.uuid4()), carrera_codigo="OVR2",
            nombre="Plan OVR2", fecha_creacion=date(2025, 1, 1),
        )
        session.add(pv)
        session.flush()
        mat = MateriaDB(
            codigo="OVR02", nombre="Override M2",
            periodo="cuatrimestral", active=True,
            dicta_recursado=False,
        )
        session.add(mat)
        session.flush()
        session.add(PlanEstudioDB(
            plan_version_id=pv.id, materia_codigo="OVR02",
            carrera_codigo="OVR2", anio_plan=1, cuatrimestre_plan="2C",
        ))
        ciclo = CicloDB(
            id="2025-1C-OVR2", anio=2025, numero=1,
            fecha_inicio=date(2025, 3, 10), fecha_fin=date(2025, 7, 5),
        )
        session.add(ciclo)
        session.flush()
        session.add(CicloPlanVersionDB(
            ciclo_id=ciclo.id, plan_version_id=pv.id,
        ))
        session.commit()

        result = create_dictados_for_ciclo(session, "2025-1C-OVR2")
        assert result.created == 0
        assert result.skipped_recursado == 1
        assert len(get_dictados_for_ciclo(session, "2025-1C-OVR2")) == 0

    def test_dicta_recursado_true_never_skips(self, session):
        """When dicta_recursado=True (default), opposite-cuatrimestre materias
        still get dictados."""
        carrera = CarreraDB(
            codigo="RECT", nombre="Carrera Recursado True",
            dicta_recursado=True,
        )
        session.add(carrera)
        session.flush()

        pv = PlanCarreraVersionDB(
            id=str(uuid.uuid4()), carrera_codigo="RECT",
            nombre="Plan RECT", fecha_creacion=date(2025, 1, 1),
        )
        session.add(pv)
        session.flush()

        mat = MateriaDB(
            codigo="REC01", nombre="Recursado Test",
            periodo="cuatrimestral", active=True,
        )
        session.add(mat)
        session.flush()

        pe = PlanEstudioDB(
            plan_version_id=pv.id, materia_codigo="REC01",
            carrera_codigo="RECT", anio_plan=1, cuatrimestre_plan="2C",
        )
        session.add(pe)

        ciclo = CicloDB(
            id="2025-1C-RECT", anio=2025, numero=1,
            fecha_inicio=date(2025, 3, 10), fecha_fin=date(2025, 7, 5),
        )
        session.add(ciclo)
        session.flush()
        session.add(CicloPlanVersionDB(ciclo_id=ciclo.id, plan_version_id=pv.id))
        session.commit()

        result = create_dictados_for_ciclo(session, "2025-1C-RECT")

        assert result.created == 1
        assert result.skipped_recursado == 0


class TestVirtualInheritance:
    """Tests for virtual flag inheritance from materia to dictado.

    Nueva semantica: el dictado se crea con `virtual=None` (heredar del
    materia via `resolve_virtual`). Solo se setea explicito si el
    usuario hace un override desde la UI.
    """

    def test_virtual_materia_creates_dictado_hereda_null(self, session):
        """A materia with virtual=True should produce a dictado with
        virtual=None (heredar), no `virtual=True` explicito."""
        carrera = CarreraDB(codigo="VIR", nombre="Virtual Test")
        session.add(carrera)
        session.flush()

        pv = PlanCarreraVersionDB(
            id=str(uuid.uuid4()), carrera_codigo="VIR",
            nombre="Plan VIR", fecha_creacion=date(2025, 1, 1),
        )
        session.add(pv)
        session.flush()

        mat = MateriaDB(
            codigo="VIR01", nombre="Materia Virtual",
            periodo="cuatrimestral", active=True, virtual=True,
        )
        session.add(mat)
        session.flush()

        pe = PlanEstudioDB(
            plan_version_id=pv.id, materia_codigo="VIR01",
            carrera_codigo="VIR", anio_plan=1, cuatrimestre_plan="1C",
        )
        session.add(pe)

        ciclo = CicloDB(
            id="2025-1C-VIR", anio=2025, numero=1,
            fecha_inicio=date(2025, 3, 10), fecha_fin=date(2025, 7, 5),
        )
        session.add(ciclo)
        session.flush()
        session.add(CicloPlanVersionDB(ciclo_id=ciclo.id, plan_version_id=pv.id))
        session.commit()

        create_dictados_for_ciclo(session, "2025-1C-VIR")

        dictados = get_dictados_for_ciclo(session, "2025-1C-VIR")
        assert len(dictados) == 1
        # virtual queda en None (heredar de materia).
        assert dictados[0].virtual is None

    def test_non_virtual_materia_creates_dictado_hereda_null(self, session, ciclo_1c, materias):
        """A materia with virtual=False (default) should also produce a
        dictado with virtual=None (heredar). No hay diferencia estructural
        entre materia virtual y no-virtual a nivel del dictado creado."""
        create_dictados_for_ciclo(session, "2025-1C")

        dictados = get_dictados_for_ciclo(session, "2025-1C")
        for d in dictados:
            assert d.virtual is None

    def test_virtual_anual_materia_hereda_null(self, session):
        """An annual virtual materia should also create a dictado with
        virtual=None (heredar)."""
        carrera = CarreraDB(codigo="VAN", nombre="Virtual Anual")
        session.add(carrera)
        session.flush()

        pv = PlanCarreraVersionDB(
            id=str(uuid.uuid4()), carrera_codigo="VAN",
            nombre="Plan VAN", fecha_creacion=date(2025, 1, 1),
        )
        session.add(pv)
        session.flush()

        mat = MateriaDB(
            codigo="VAN01", nombre="Anual Virtual",
            periodo="anual", active=True, virtual=True,
        )
        session.add(mat)
        session.flush()

        pe = PlanEstudioDB(
            plan_version_id=pv.id, materia_codigo="VAN01",
            carrera_codigo="VAN", anio_plan=1, cuatrimestre_plan="Anual",
        )
        session.add(pe)

        ciclo = CicloDB(
            id="2025-1C-VAN", anio=2025, numero=1,
            fecha_inicio=date(2025, 3, 10), fecha_fin=date(2025, 7, 5),
        )
        session.add(ciclo)
        session.flush()
        session.add(CicloPlanVersionDB(ciclo_id=ciclo.id, plan_version_id=pv.id))
        session.commit()

        create_dictados_for_ciclo(session, "2025-1C-VAN")

        dictados = get_dictados_for_ciclo(session, "2025-1C-VAN")
        assert len(dictados) == 1
        assert dictados[0].virtual is None


class TestGetSkippedMaterias:
    """Tests for get_skipped_materias_for_ciclo."""

    def test_skipped_por_recursado_no_tiene_dictado(self, session):
        """Una materia cuya regla de recursado dice skippear NO tiene
        dictado en el ciclo. Aparece como skipped en
        `get_skipped_materias_for_ciclo`."""
        carrera = CarreraDB(
            codigo="SKP", nombre="Skip Test", dicta_recursado=False,
        )
        session.add(carrera)
        session.flush()

        pv = PlanCarreraVersionDB(
            id=str(uuid.uuid4()), carrera_codigo="SKP",
            nombre="Plan SKP", fecha_creacion=date(2025, 1, 1),
        )
        session.add(pv)
        session.flush()

        mat = MateriaDB(
            codigo="SKP01", nombre="Skip Materia",
            periodo="cuatrimestral", active=True,
        )
        session.add(mat)
        session.flush()

        session.add(PlanEstudioDB(
            plan_version_id=pv.id, materia_codigo="SKP01",
            carrera_codigo="SKP", anio_plan=1, cuatrimestre_plan="2C",
        ))

        ciclo = CicloDB(
            id="2025-1C-SKP", anio=2025, numero=1,
            fecha_inicio=date(2025, 3, 10), fecha_fin=date(2025, 7, 5),
        )
        session.add(ciclo)
        session.flush()
        session.add(CicloPlanVersionDB(ciclo_id=ciclo.id, plan_version_id=pv.id))
        session.commit()

        create_dictados_for_ciclo(session, "2025-1C-SKP")

        # No se creo dictado — aparece como skipped.
        skipped = get_skipped_materias_for_ciclo(session, "2025-1C-SKP")
        codigos_skipped = {m.materia_codigo for m in skipped}
        assert "SKP01" in codigos_skipped
        assert len(get_dictados_for_ciclo(session, "2025-1C-SKP")) == 0

    def test_empty_when_all_materias_have_dictados(self, session, ciclo_1c, materias):
        """No skipped materias when all plan materias have dictados."""
        create_dictados_for_ciclo(session, "2025-1C")
        skipped = get_skipped_materias_for_ciclo(session, "2025-1C")
        assert len(skipped) == 0


class TestCreateDictadoForMateria:
    """Tests for the on-demand `create_dictado_for_materia` helper used
    when the user activates a materia from the UI even though the
    auto-creator skipped it."""

    def test_creates_dictado_ignoring_recursado_skip(self, session):
        """Si por algun motivo una materia no tuviera dictado todavia,
        create_dictado_for_materia lo crea con activo=True (override
        explicito del usuario, sin importar la regla de recursado)."""
        carrera = CarreraDB(
            codigo="LIC", nombre="Licenciatura", dicta_recursado=False,
        )
        session.add(carrera)
        session.flush()

        pv = PlanCarreraVersionDB(
            id=str(uuid.uuid4()), carrera_codigo="LIC",
            nombre="Plan LIC", fecha_creacion=date(2025, 1, 1),
        )
        session.add(pv)
        session.flush()

        mat = MateriaDB(
            codigo="QUI201", nombre="Quimica II",
            periodo="cuatrimestral", active=True,
        )
        session.add(mat)
        session.flush()
        session.add(PlanEstudioDB(
            plan_version_id=pv.id, materia_codigo="QUI201",
            carrera_codigo="LIC", anio_plan=2, cuatrimestre_plan="2C",
        ))

        ciclo = CicloDB(
            id="2025-1C-LIC", anio=2025, numero=1,
            fecha_inicio=date(2025, 3, 10), fecha_fin=date(2025, 7, 5),
        )
        session.add(ciclo)
        session.flush()
        session.add(CicloPlanVersionDB(
            ciclo_id=ciclo.id, plan_version_id=pv.id,
        ))
        session.commit()

        # Manual creation produces a dictado (todos existen → todos activos)
        d = create_dictado_for_materia(session, "2025-1C-LIC", "QUI201")
        assert d is not None
        assert d.materia_codigo == "QUI201"

        # Idempotente: segunda llamada devuelve el mismo
        d2 = create_dictado_for_materia(session, "2025-1C-LIC", "QUI201")
        assert d2 is not None
        assert d2.id == d.id

    def test_returns_none_for_invalid_ciclo_or_materia(self, session, ciclo_1c, materias):
        assert create_dictado_for_materia(session, "NONEXISTENT", "MAT101") is None
        assert create_dictado_for_materia(session, "2025-1C", "NOPE") is None




class TestUpdateDictado:
    """Tests for update_dictado."""


    def test_update_virtual(self, session, ciclo_1c, materias):
        create_dictados_for_ciclo(session, "2025-1C")
        dictados = get_dictados_for_ciclo(session, "2025-1C")
        d = dictados[0]

        updated = update_dictado(session, d.id, virtual=True)
        assert updated is not None
        assert updated.virtual is True

    def test_update_nonexistent_returns_none(self, session):
        result = update_dictado(session, "nonexistent-id", virtual=True)
        assert result is None



class TestSyncDictadosParaCiclo:
    """Tests para `sync_dictados_para_ciclo`, la nueva API de divergencias."""

    def _setup_ciclo_con_plan(self, session, *, cuatri_mat="1C", ciclo_num=1):
        """Ciclo + carrera + materia + plan_version. No crea dictado."""
        carrera = CarreraDB(codigo="SC", nombre="Sync Test")
        session.add(carrera)
        session.flush()
        pv = PlanCarreraVersionDB(
            id=str(uuid.uuid4()), carrera_codigo="SC",
            nombre="Plan SC", fecha_creacion=date(2025, 1, 1),
        )
        session.add(pv)
        session.flush()
        mat = MateriaDB(
            codigo="SC01", nombre="Sync Mat",
            periodo="cuatrimestral", active=True,
        )
        session.add(mat)
        session.flush()
        session.add(PlanEstudioDB(
            plan_version_id=pv.id, materia_codigo="SC01",
            carrera_codigo="SC", anio_plan=1, cuatrimestre_plan=cuatri_mat,
        ))
        ciclo = CicloDB(
            id=f"2025-{ciclo_num}C-SC", anio=2025, numero=ciclo_num,
            fecha_inicio=date(2025, 3, 10), fecha_fin=date(2025, 7, 5),
        )
        session.add(ciclo)
        session.flush()
        session.add(CicloPlanVersionDB(
            ciclo_id=ciclo.id, plan_version_id=pv.id,
        ))
        session.commit()
        return ciclo, mat, carrera

    def test_preview_to_create_sin_dictado(self, session):
        """Materia del plan sin dictado y regla no dice skippear →
        aparece en to_create."""
        ciclo, mat, _ = self._setup_ciclo_con_plan(session)
        # NO llamamos create_dictados_for_ciclo → dictado ausente.
        sync = sync_dictados_para_ciclo(session, ciclo.id, apply=False)
        assert len(sync.to_create) == 1
        assert sync.to_create[0]["materia_codigo"] == "SC01"
        assert sync.applied is False
        # No se creo nada (apply=False).
        assert len(get_dictados_for_ciclo(session, ciclo.id)) == 0

    def test_apply_crea_faltantes(self, session):
        """apply=True crea los dictados de to_create."""
        ciclo, mat, _ = self._setup_ciclo_con_plan(session)
        sync = sync_dictados_para_ciclo(session, ciclo.id, apply=True)
        assert sync.applied is True
        assert len(get_dictados_for_ciclo(session, ciclo.id)) == 1

    def test_to_delete_dictado_huerfano(self, session):
        """Dictado existe pero la materia no esta en ningun plan del
        ciclo → aparece en to_delete."""
        ciclo, _, carrera = self._setup_ciclo_con_plan(session)
        # Creamos el dictado normalmente.
        create_dictados_for_ciclo(session, ciclo.id)
        assert len(get_dictados_for_ciclo(session, ciclo.id)) == 1
        # Ahora sacamos la materia del plan (borro PE row).
        pe = session.exec(
            select(PlanEstudioDB).where(
                PlanEstudioDB.materia_codigo == "SC01",
            )
        ).first()
        session.delete(pe)
        session.commit()

        sync = sync_dictados_para_ciclo(session, ciclo.id, apply=False)
        assert len(sync.to_delete) == 1
        assert sync.to_delete[0]["materia_codigo"] == "SC01"

    def test_apply_borra_huerfanos(self, session):
        """apply=True borra los dictados de to_delete."""
        ciclo, _, _ = self._setup_ciclo_con_plan(session)
        create_dictados_for_ciclo(session, ciclo.id)
        pe = session.exec(
            select(PlanEstudioDB).where(
                PlanEstudioDB.materia_codigo == "SC01",
            )
        ).first()
        session.delete(pe)
        session.commit()

        sync_dictados_para_ciclo(session, ciclo.id, apply=True)
        assert len(get_dictados_for_ciclo(session, ciclo.id)) == 0

    def test_rule_says_skip_but_exists_no_se_borra(self, session):
        """Dictado existe pero la regla dice skippear → aparece en
        rule_says_skip_but_exists y NO se borra en apply."""
        # Ciclo 1C con materia de 2C (cuatri opuesto) y carrera que no
        # dicta recursado. La regla dice skippear pero el dictado existe.
        ciclo, mat, carrera = self._setup_ciclo_con_plan(
            session, cuatri_mat="2C",
        )
        carrera.dicta_recursado = False
        session.add(carrera)
        session.commit()
        # Creamos el dictado a mano (create_dictados no lo crearia).
        create_dictado_for_materia(session, ciclo.id, mat.codigo)
        assert len(get_dictados_for_ciclo(session, ciclo.id)) == 1

        sync = sync_dictados_para_ciclo(session, ciclo.id, apply=True)
        # No lo borro (no aparece en to_delete).
        assert len(sync.to_delete) == 0
        assert len(sync.rule_says_skip_but_exists) == 1
        # El dictado sigue existiendo.
        assert len(get_dictados_for_ciclo(session, ciclo.id)) == 1


class TestPromoverARegla:
    """Tests para `promover_a_regla`."""

    def _setup_materia(self, session):
        mat = MateriaDB(
            codigo="PR01", nombre="Promover Test",
            periodo="cuatrimestral", active=True,
        )
        session.add(mat)
        session.commit()
        return mat

    def test_crear_en_regla_setea_dicta_recursado_true(self, session):
        mat = self._setup_materia(session)
        assert mat.dicta_recursado is None
        result = promover_a_regla(
            session, "PR01", "2025-1C", accion="crear-en-regla",
        )
        assert result is True
        session.refresh(mat)
        assert mat.dicta_recursado is True

    def test_omitir_en_regla_setea_dicta_recursado_false(self, session):
        mat = self._setup_materia(session)
        result = promover_a_regla(
            session, "PR01", "2025-1C", accion="omitir-en-regla",
        )
        assert result is True
        session.refresh(mat)
        assert mat.dicta_recursado is False

    def test_no_toca_si_ya_esta_en_valor(self, session):
        mat = self._setup_materia(session)
        mat.dicta_recursado = True
        session.add(mat)
        session.commit()
        result = promover_a_regla(
            session, "PR01", "2025-1C", accion="crear-en-regla",
        )
        assert result is False  # ya estaba en ese valor

    def test_falla_si_materia_no_existe(self, session):
        result = promover_a_regla(
            session, "NOEXISTE", "2025-1C", accion="crear-en-regla",
        )
        assert result is False

    def test_accion_invalida_raises(self, session):
        self._setup_materia(session)
        with pytest.raises(ValueError, match="Accion invalida"):
            promover_a_regla(
                session, "PR01", "2025-1C", accion="foobar",
            )


class TestBorrarDictadoDeCiclo:
    """Tests para `borrar_dictado_de_ciclo` (helper que apoya la UI)."""

    def _setup_ciclo_con_dictado(self, session):
        carrera = CarreraDB(codigo="BD", nombre="Borrar Test")
        session.add(carrera)
        session.flush()
        pv = PlanCarreraVersionDB(
            id=str(uuid.uuid4()), carrera_codigo="BD",
            nombre="Plan BD", fecha_creacion=date(2025, 1, 1),
        )
        session.add(pv)
        session.flush()
        mat = MateriaDB(
            codigo="BD01", nombre="Borrar Mat",
            periodo="cuatrimestral", active=True,
        )
        session.add(mat)
        session.flush()
        session.add(PlanEstudioDB(
            plan_version_id=pv.id, materia_codigo="BD01",
            carrera_codigo="BD", anio_plan=1, cuatrimestre_plan="1C",
        ))
        ciclo = CicloDB(
            id="2025-1C-BD", anio=2025, numero=1,
            fecha_inicio=date(2025, 3, 10), fecha_fin=date(2025, 7, 5),
        )
        session.add(ciclo)
        session.flush()
        session.add(CicloPlanVersionDB(
            ciclo_id=ciclo.id, plan_version_id=pv.id,
        ))
        session.commit()
        create_dictados_for_ciclo(session, ciclo.id)
        return ciclo

    def test_borra_dictado_del_ciclo(self, session):
        ciclo = self._setup_ciclo_con_dictado(session)
        d = get_dictados_for_ciclo(session, ciclo.id)[0]
        assert borrar_dictado_de_ciclo(session, ciclo.id, d.id) is True
        assert len(get_dictados_for_ciclo(session, ciclo.id)) == 0
        # La fila DictadoDB tambien se borro (no queda en otros ciclos).
        assert session.get(DictadoDB, d.id) is None

    def test_borrar_nullifica_clases_huerfanas(self, session):
        from src.database.models import (
            ClaseDB, ComisionDB, HorarioDB,
            PlanificacionCursadaDB,
        )
        from datetime import time
        ciclo = self._setup_ciclo_con_dictado(session)
        d = get_dictados_for_ciclo(session, ciclo.id)[0]
        # Simulamos que hay clases del dictado (via un plan + comision).
        plan = PlanificacionCursadaDB(
            id="pl-1", nombre="P", ciclo_id=ciclo.id,
        )
        session.add(plan)
        com = ComisionDB(
            id="c-1", materia_codigo="BD01", dictado_id=d.id,
            plan_cursada_id="pl-1", comision_key="BD01-001",
            nombre="C1", numero=1, cupo=30,
        )
        session.add(com)
        h = HorarioDB(
            id="h-1", comision_id="c-1", codigo_materia="BD01",
            dia="Lunes", hora_inicio=time(8, 0), hora_fin=time(10, 0),
        )
        session.add(h)
        cl = ClaseDB(
            id="cl-1", horario_id="h-1", comision_id="c-1",
            plan_cursada_id="pl-1", dictado_id=d.id,
            fecha=date(2025, 3, 10),
            hora_inicio=time(8, 0), hora_fin=time(10, 0),
        )
        session.add(cl)
        session.commit()

        borrar_dictado_de_ciclo(session, ciclo.id, d.id)
        session.refresh(cl)
        # La clase sobrevive pero con dictado_id=None.
        assert cl.dictado_id is None

    def test_idempotente_si_dictado_no_existe(self, session):
        ciclo = self._setup_ciclo_con_dictado(session)
        result = borrar_dictado_de_ciclo(session, ciclo.id, "NOEXISTE")
        assert result is False
