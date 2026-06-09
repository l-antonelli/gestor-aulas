"""Tests for dictado_service."""

import uuid
import pytest
from datetime import date

from sqlmodel import Session, SQLModel, create_engine
from sqlalchemy.pool import StaticPool

from src.database.models import (
    CicloDB, MateriaDB, CarreraDB, DictadoDB,
    PlanCarreraVersionDB, PlanEstudioDB, CicloPlanVersionDB,
)
from src.services.dictado_service import (
    create_dictado_for_materia,
    create_dictados_for_ciclo,
    get_dictados_for_ciclo,
    get_skipped_materias_for_ciclo,
    recompute_activo_for_ciclo,
    set_activo_for_materias_in_ciclo,
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

    def test_exclusive_materia_created_inactive_when_no_recursado(self, session):
        """A cuatrimestral materia exclusive to one carrera with dicta_recursado=False
        and assigned to 2C should be created with activo=False when creating
        dictados for 1C (no longer skipped — registered for on-the-fly editing)."""
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

        # Ahora se crea pero inactivo
        assert result.created == 1
        assert result.created_inactive == 1
        assert result.skipped_recursado == 0  # deprecated

        dictados = get_dictados_for_ciclo(session, "2025-1C-LIC")
        assert len(dictados) == 1
        assert dictados[0].activo is False

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
        assert result.created_inactive == 0  # quedo activo por override

        d = get_dictados_for_ciclo(session, "2025-1C-OVR1")[0]
        assert d.activo is True

    def test_materia_override_recursado_false_beats_carrera_true(self, session):
        """Si MateriaDB.dicta_recursado=False y el cuatri es opuesto,
        se crea inactivo aunque la carrera sea dicta_recursado=True."""
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
        assert result.created == 1
        assert result.created_inactive == 1  # inactivo por override
        d = get_dictados_for_ciclo(session, "2025-1C-OVR2")[0]
        assert d.activo is False

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
    """Tests for virtual flag inheritance from materia to dictado."""

    def test_virtual_materia_creates_virtual_dictado(self, session):
        """A materia with virtual=True should produce a dictado with virtual=True."""
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
        assert dictados[0].virtual is True

    def test_non_virtual_materia_creates_non_virtual_dictado(self, session, ciclo_1c, materias):
        """A materia with virtual=False (default) should produce a dictado with virtual=False."""
        create_dictados_for_ciclo(session, "2025-1C")

        dictados = get_dictados_for_ciclo(session, "2025-1C")
        for d in dictados:
            assert d.virtual is False

    def test_virtual_anual_materia_inherits(self, session):
        """An annual virtual materia should create a virtual dictado."""
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
        assert dictados[0].virtual is True


class TestGetSkippedMaterias:
    """Tests for get_skipped_materias_for_ciclo."""

    def test_no_skipped_after_create_creates_all(self, session):
        """Despues de la nueva logica de creacion, ninguna materia queda
        sin dictado: las que antes se skipeaban ahora se crean inactivas."""
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

        # Ya no se considera "skipped" — quedo creado pero inactivo
        skipped = get_skipped_materias_for_ciclo(session, "2025-1C-SKP")
        assert len(skipped) == 0
        dictados = get_dictados_for_ciclo(session, "2025-1C-SKP")
        assert len(dictados) == 1
        assert dictados[0].activo is False

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

        # Manual creation produces an active dictado (sin pasar por auto-creator)
        d = create_dictado_for_materia(session, "2025-1C-LIC", "QUI201")
        assert d is not None
        assert d.materia_codigo == "QUI201"
        assert d.activo is True

        # Idempotente: segunda llamada devuelve el mismo
        d2 = create_dictado_for_materia(session, "2025-1C-LIC", "QUI201")
        assert d2 is not None
        assert d2.id == d.id

    def test_returns_none_for_invalid_ciclo_or_materia(self, session, ciclo_1c, materias):
        assert create_dictado_for_materia(session, "NONEXISTENT", "MAT101") is None
        assert create_dictado_for_materia(session, "2025-1C", "NOPE") is None


class TestRecomputeActivo:
    """Tests for `recompute_activo_for_ciclo`."""

    def test_preview_does_not_persist(self, session):
        """`apply=False` devuelve diff sin tocar la DB."""
        carrera = CarreraDB(
            codigo="REC", nombre="Recompute Test", dicta_recursado=False,
        )
        session.add(carrera)
        session.flush()
        pv = PlanCarreraVersionDB(
            id=str(uuid.uuid4()), carrera_codigo="REC",
            nombre="Plan REC", fecha_creacion=date(2025, 1, 1),
        )
        session.add(pv)
        session.flush()
        mat = MateriaDB(
            codigo="REC01", nombre="Recompute Materia",
            periodo="cuatrimestral", active=True,
        )
        session.add(mat)
        session.flush()
        session.add(PlanEstudioDB(
            plan_version_id=pv.id, materia_codigo="REC01",
            carrera_codigo="REC", anio_plan=1, cuatrimestre_plan="2C",
        ))
        ciclo = CicloDB(
            id="2025-1C-REC", anio=2025, numero=1,
            fecha_inicio=date(2025, 3, 10), fecha_fin=date(2025, 7, 5),
        )
        session.add(ciclo)
        session.flush()
        session.add(CicloPlanVersionDB(
            ciclo_id=ciclo.id, plan_version_id=pv.id,
        ))
        session.commit()

        # Crea inactivo
        create_dictados_for_ciclo(session, "2025-1C-REC")

        # Cambiar la carrera a dicta_recursado=True
        carrera.dicta_recursado = True
        session.add(carrera)
        session.commit()

        # Preview: debe sugerir activar REC01
        preview = recompute_activo_for_ciclo(session, "2025-1C-REC", apply=False)
        assert preview.applied is False
        # Cada item es ahora un dict enriquecido. Buscamos por materia.
        materias_activate = {
            it["materia_codigo"] for it in preview.to_activate
        }
        assert "REC01" in materias_activate
        assert preview.n_changes == 1

        # DB sin cambios
        d = get_dictados_for_ciclo(session, "2025-1C-REC")[0]
        assert d.activo is False

    def test_apply_persists_changes(self, session):
        """`apply=True` persiste y refleja activo segun reglas."""
        carrera = CarreraDB(
            codigo="REC2", nombre="R2", dicta_recursado=False,
        )
        session.add(carrera)
        session.flush()
        pv = PlanCarreraVersionDB(
            id=str(uuid.uuid4()), carrera_codigo="REC2",
            nombre="Plan REC2", fecha_creacion=date(2025, 1, 1),
        )
        session.add(pv)
        session.flush()
        mat = MateriaDB(
            codigo="REC02", nombre="R2 Mat",
            periodo="cuatrimestral", active=True,
        )
        session.add(mat)
        session.flush()
        session.add(PlanEstudioDB(
            plan_version_id=pv.id, materia_codigo="REC02",
            carrera_codigo="REC2", anio_plan=1, cuatrimestre_plan="2C",
        ))
        ciclo = CicloDB(
            id="2025-1C-REC2", anio=2025, numero=1,
            fecha_inicio=date(2025, 3, 10), fecha_fin=date(2025, 7, 5),
        )
        session.add(ciclo)
        session.flush()
        session.add(CicloPlanVersionDB(
            ciclo_id=ciclo.id, plan_version_id=pv.id,
        ))
        session.commit()

        create_dictados_for_ciclo(session, "2025-1C-REC2")
        carrera.dicta_recursado = True
        session.add(carrera)
        session.commit()

        result = recompute_activo_for_ciclo(session, "2025-1C-REC2", apply=True)
        assert result.applied is True
        assert result.n_changes == 1
        d = get_dictados_for_ciclo(session, "2025-1C-REC2")[0]
        assert d.activo is True


class TestSetActivoForMaterias:
    """Tests for `set_activo_for_materias_in_ciclo`."""

    def test_deactivate_existing(self, session, ciclo_1c, materias):
        create_dictados_for_ciclo(session, "2025-1C")
        n = set_activo_for_materias_in_ciclo(
            session, "2025-1C", ["MAT101", "FIS101"], activo=False,
        )
        assert n == 2
        ds = get_dictados_for_ciclo(session, "2025-1C")
        for d in ds:
            assert d.activo is False

    def test_activate_creates_if_missing(self, session, ciclo_1c, materias):
        # No corremos create_dictados_for_ciclo a proposito.
        n = set_activo_for_materias_in_ciclo(
            session, "2025-1C", ["MAT101"], activo=True,
        )
        assert n == 1
        ds = get_dictados_for_ciclo(session, "2025-1C")
        assert len(ds) == 1
        assert ds[0].materia_codigo == "MAT101"
        assert ds[0].activo is True

    def test_idempotent_when_already_set(self, session, ciclo_1c, materias):
        create_dictados_for_ciclo(session, "2025-1C")
        # Ya estan activos por defecto
        n = set_activo_for_materias_in_ciclo(
            session, "2025-1C", ["MAT101"], activo=True,
        )
        assert n == 0


class TestUpdateDictado:
    """Tests for update_dictado."""

    def test_update_activo(self, session, ciclo_1c, materias):
        create_dictados_for_ciclo(session, "2025-1C")
        dictados = get_dictados_for_ciclo(session, "2025-1C")
        d = dictados[0]

        updated = update_dictado(session, d.id, activo=False)
        assert updated is not None
        assert updated.activo is False

    def test_update_virtual(self, session, ciclo_1c, materias):
        create_dictados_for_ciclo(session, "2025-1C")
        dictados = get_dictados_for_ciclo(session, "2025-1C")
        d = dictados[0]

        updated = update_dictado(session, d.id, virtual=True)
        assert updated is not None
        assert updated.virtual is True

    def test_update_nonexistent_returns_none(self, session):
        result = update_dictado(session, "nonexistent-id", activo=False)
        assert result is None


class TestActivoOverrideManual:
    """Tests para `set_activo_manual`, `clear_activo_override` y la
    interaccion con `recompute_activo_for_ciclo` (Fase override)."""

    def test_set_activo_manual_persiste_ambos_campos(
        self, session, ciclo_1c, materias,
    ):
        from src.services.dictado_service import set_activo_manual
        create_dictados_for_ciclo(session, "2025-1C")
        d = get_dictados_for_ciclo(session, "2025-1C")[0]
        # Inicialmente activo=True, override=None
        assert d.activo is True
        assert d.activo_override_manual is None

        updated = set_activo_manual(session, d.id, False)
        assert updated is not None
        assert updated.activo is False
        assert updated.activo_override_manual is False

    def test_recompute_respeta_override_por_default(self, session):
        """Override que difiere de la regla → queda en
        overrides_respetados."""
        from src.services.dictado_service import (
            recompute_activo_for_ciclo, set_activo_manual,
        )
        # Setup: carrera dicta_recursado=True (regla → activo), pero
        # el usuario forzo desactivado manualmente.
        carrera = CarreraDB(codigo="OV1", nombre="OV1", dicta_recursado=True)
        session.add(carrera)
        session.flush()
        pv = PlanCarreraVersionDB(
            id=str(uuid.uuid4()), carrera_codigo="OV1",
            nombre="P", fecha_creacion=date(2025, 1, 1),
        )
        session.add(pv)
        session.flush()
        materia = MateriaDB(
            codigo="OV01", nombre="OV01", periodo="cuatrimestral",
            horas_semanales=4, horas_teoria=4, horas_laboratorio=0,
        )
        session.add(materia)
        session.add(PlanEstudioDB(
            plan_version_id=pv.id, materia_codigo="OV01",
            carrera_codigo="OV1", anio_plan=1, cuatrimestre_plan="1C",
        ))
        ciclo = CicloDB(
            id="2025-1C-OV", anio=2025, numero=1,
            fecha_inicio=date(2025, 3, 1), fecha_fin=date(2025, 7, 31),
        )
        session.add(ciclo)
        session.flush()
        session.add(CicloPlanVersionDB(
            ciclo_id=ciclo.id, plan_version_id=pv.id,
        ))
        session.commit()
        create_dictados_for_ciclo(session, ciclo.id)
        d = get_dictados_for_ciclo(session, ciclo.id)[0]
        assert d.activo is True

        # Override manual: forzar inactivo.
        set_activo_manual(session, d.id, False)

        # Recalcular en modo default: respeta override.
        preview = recompute_activo_for_ciclo(session, ciclo.id, apply=False)
        assert preview.unchanged == 0
        assert preview.n_changes == 0
        assert len(preview.overrides_respetados) == 1
        item = preview.overrides_respetados[0]
        assert item["materia_codigo"] == "OV01"
        assert item["tiene_override"] is True

    def test_recompute_pisa_overrides_si_flag_on(self, session):
        """Con pisar_overrides=True, el override se borra y la regla
        aplica."""
        from src.services.dictado_service import (
            recompute_activo_for_ciclo, set_activo_manual,
        )
        carrera = CarreraDB(codigo="OV2", nombre="OV2", dicta_recursado=True)
        session.add(carrera)
        session.flush()
        pv = PlanCarreraVersionDB(
            id=str(uuid.uuid4()), carrera_codigo="OV2",
            nombre="P", fecha_creacion=date(2025, 1, 1),
        )
        session.add(pv)
        session.flush()
        materia = MateriaDB(
            codigo="OV02", nombre="OV02", periodo="cuatrimestral",
            horas_semanales=4, horas_teoria=4, horas_laboratorio=0,
        )
        session.add(materia)
        session.add(PlanEstudioDB(
            plan_version_id=pv.id, materia_codigo="OV02",
            carrera_codigo="OV2", anio_plan=1, cuatrimestre_plan="1C",
        ))
        ciclo = CicloDB(
            id="2025-1C-OV2", anio=2025, numero=1,
            fecha_inicio=date(2025, 3, 1), fecha_fin=date(2025, 7, 31),
        )
        session.add(ciclo)
        session.flush()
        session.add(CicloPlanVersionDB(
            ciclo_id=ciclo.id, plan_version_id=pv.id,
        ))
        session.commit()
        create_dictados_for_ciclo(session, ciclo.id)
        d = get_dictados_for_ciclo(session, ciclo.id)[0]
        set_activo_manual(session, d.id, False)

        # Recalcular pisando overrides.
        result = recompute_activo_for_ciclo(
            session, ciclo.id, apply=True, pisar_overrides=True,
        )
        assert result.applied is True
        # El dictado pasa a activo=True (regla manda) y el override
        # se borra.
        d2 = get_dictados_for_ciclo(session, ciclo.id)[0]
        assert d2.activo is True
        assert d2.activo_override_manual is None
        assert len(result.overrides_respetados) == 0
        assert len(result.to_activate) == 1

    def test_recompute_items_tienen_contexto_completo(self, session):
        """Cada item del preview debe traer materia_nombre, carrera,
        anio_plan, cuatrimestre_plan, razon."""
        from src.services.dictado_service import recompute_activo_for_ciclo
        carrera = CarreraDB(codigo="CTX", nombre="Carrera CTX", dicta_recursado=False)
        session.add(carrera)
        session.flush()
        pv = PlanCarreraVersionDB(
            id=str(uuid.uuid4()), carrera_codigo="CTX",
            nombre="Plan CTX", fecha_creacion=date(2025, 1, 1),
        )
        session.add(pv)
        session.flush()
        materia = MateriaDB(
            codigo="CTX01", nombre="Materia Contextualizada",
            periodo="cuatrimestral",
            horas_semanales=4, horas_teoria=4, horas_laboratorio=0,
        )
        session.add(materia)
        session.add(PlanEstudioDB(
            plan_version_id=pv.id, materia_codigo="CTX01",
            carrera_codigo="CTX", anio_plan=2, cuatrimestre_plan="2C",
        ))
        ciclo = CicloDB(
            id="2025-1C-CTX", anio=2025, numero=1,
            fecha_inicio=date(2025, 3, 1), fecha_fin=date(2025, 7, 31),
        )
        session.add(ciclo)
        session.flush()
        session.add(CicloPlanVersionDB(
            ciclo_id=ciclo.id, plan_version_id=pv.id,
        ))
        session.commit()
        create_dictados_for_ciclo(session, ciclo.id)

        # Materia es 2C en plan, ciclo es 1C, carrera no recursa
        # → debe figurar en to_deactivate (si arrancó activa) o ya
        # estar inactiva.
        # Como create_dictados_for_ciclo aplica la regla en creación,
        # arranca inactiva. Forzamos activarla y recalcular.
        d = get_dictados_for_ciclo(session, ciclo.id)[0]
        d.activo = True
        session.add(d)
        session.commit()

        preview = recompute_activo_for_ciclo(session, ciclo.id, apply=False)
        assert len(preview.to_deactivate) == 1
        item = preview.to_deactivate[0]
        assert item["materia_codigo"] == "CTX01"
        assert item["materia_nombre"] == "Materia Contextualizada"
        assert item["carrera_codigo"] == "CTX"
        assert item["carrera_nombre"] == "Carrera CTX"
        assert item["anio_plan"] == 2
        assert item["cuatrimestre_plan"] == "2C"
        assert item["estado_actual"] is True
        assert item["estado_nuevo"] is False
        assert "no dicta recursado" in item["razon"]
        assert item["tiene_override"] is False
