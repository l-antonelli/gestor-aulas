"""Tests para comision_service.py (comisiones como entidades reales,
usadas tanto por cronogramas como por planes).
"""

from datetime import date, time

import pytest
from sqlalchemy.pool import StaticPool
from sqlmodel import Session, SQLModel, create_engine

from src.database.models import (
    CarreraDB,
    CicloDB,
    ComisionDB,
    HorarioDB,
    MateriaDB,
    PlanificacionCursadaDB,
    ScheduleDB,
    ScheduleEntryDB,
)
from src.services.comision_service import (
    clone_comisiones_for_plan,
    create_comision_for_plan,
    create_comision_for_schedule,
    delete_comision,
    get_or_create_comision_by_numero,
    list_comisiones_for_plan_materia,
    list_comisiones_for_schedule,
    list_comisiones_for_schedule_materia,
    update_comision,
)


@pytest.fixture(name="engine")
def engine_fixture():
    eng = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    SQLModel.metadata.create_all(eng)
    return eng


@pytest.fixture(name="session")
def session_fixture(engine):
    with Session(engine) as session:
        yield session


def _seed(session: Session) -> dict:
    """Seed con una materia, una carrera, un ciclo, un schedule y un plan."""
    mat = MateriaDB(codigo="M1", nombre="Materia 1", cupo=25)
    car = CarreraDB(codigo="A", nombre="Carrera A")
    ciclo = CicloDB(
        id="c1", anio=2026, numero=1,
        fecha_inicio=date(2026, 3, 1),
        fecha_fin=date(2026, 7, 1),
    )
    sched = ScheduleDB(
        id="s1", ciclo_id="c1", nombre="Sched 1", fecha_upload=date.today(),
    )
    plan = PlanificacionCursadaDB(
        id="p1", nombre="Plan 1", ciclo_id="c1",
    )
    session.add_all([mat, car, ciclo, sched, plan])
    session.commit()
    return {"mat": mat, "car": car, "ciclo": ciclo, "sched": sched, "plan": plan}


class TestCreacion:

    def test_create_for_schedule_autoderiva_numero(self, session):
        _seed(session)
        c1 = create_comision_for_schedule(
            session, schedule_id="s1", materia_codigo="M1",
        )
        assert c1.numero == 1
        assert c1.cupo == 25  # de la materia
        assert c1.nombre == "Comisión 1"
        c2 = create_comision_for_schedule(
            session, schedule_id="s1", materia_codigo="M1",
        )
        assert c2.numero == 2

    def test_create_for_plan_autoderiva_numero(self, session):
        _seed(session)
        c1 = create_comision_for_plan(
            session, plan_cursada_id="p1", materia_codigo="M1",
        )
        assert c1.numero == 1
        c2 = create_comision_for_plan(
            session, plan_cursada_id="p1", materia_codigo="M1",
        )
        assert c2.numero == 2

    def test_carrera_asignada_se_persiste(self, session):
        _seed(session)
        c = create_comision_for_schedule(
            session, schedule_id="s1", materia_codigo="M1",
            carrera_asignada="A",
        )
        assert c.carrera_asignada == "A"

    def test_get_or_create_devuelve_existente(self, session):
        _seed(session)
        c1 = create_comision_for_schedule(
            session, schedule_id="s1", materia_codigo="M1", numero=5,
        )
        c2 = get_or_create_comision_by_numero(
            session, "M1", 5, schedule_id="s1",
        )
        assert c1.id == c2.id


class TestUpdate:

    def test_update_regenera_comision_key(self, session):
        _seed(session)
        c = create_comision_for_schedule(
            session, schedule_id="s1", materia_codigo="M1", numero=1,
        )
        assert c.comision_key == "M1-001"
        update_comision(session, c.id, numero=7)
        session.refresh(c)
        assert c.numero == 7
        assert c.comision_key == "M1-007"

    def test_update_carrera_asignada(self, session):
        _seed(session)
        c = create_comision_for_schedule(
            session, schedule_id="s1", materia_codigo="M1",
        )
        update_comision(session, c.id, carrera_asignada="A")
        session.refresh(c)
        assert c.carrera_asignada == "A"


class TestDeleteConGuarda:

    def test_delete_bloqueado_si_hay_entries(self, session):
        _seed(session)
        c = create_comision_for_schedule(
            session, schedule_id="s1", materia_codigo="M1",
        )
        session.add(ScheduleEntryDB(
            id="e1", schedule_id="s1", codigo_materia="M1",
            dia="Lunes", hora_inicio=time(8, 0), hora_fin=time(10, 0),
            comision_id=c.id,
        ))
        session.commit()
        res = delete_comision(session, c.id)
        assert res.ok is False
        assert "entries" in res.errores[0].lower()
        # La comisión sigue existiendo
        assert session.get(ComisionDB, c.id) is not None

    def test_delete_bloqueado_si_hay_horarios(self, session):
        _seed(session)
        c = create_comision_for_plan(
            session, plan_cursada_id="p1", materia_codigo="M1",
        )
        session.add(HorarioDB(
            id="h1", comision_id=c.id, codigo_materia="M1",
            dia="Lunes", hora_inicio=time(8, 0), hora_fin=time(10, 0),
        ))
        session.commit()
        res = delete_comision(session, c.id)
        assert res.ok is False
        assert "horarios" in res.errores[0].lower()

    def test_delete_ok_si_no_hay_dependencias(self, session):
        _seed(session)
        c = create_comision_for_schedule(
            session, schedule_id="s1", materia_codigo="M1",
        )
        res = delete_comision(session, c.id)
        assert res.ok is True
        assert session.get(ComisionDB, c.id) is None


class TestListing:

    def test_list_for_schedule_materia_orden_por_numero(self, session):
        _seed(session)
        create_comision_for_schedule(
            session, schedule_id="s1", materia_codigo="M1", numero=3,
        )
        create_comision_for_schedule(
            session, schedule_id="s1", materia_codigo="M1", numero=1,
        )
        create_comision_for_schedule(
            session, schedule_id="s1", materia_codigo="M1", numero=2,
        )
        result = list_comisiones_for_schedule_materia(session, "s1", "M1")
        assert [c.numero for c in result] == [1, 2, 3]

    def test_list_for_plan_no_incluye_las_del_schedule(self, session):
        _seed(session)
        create_comision_for_schedule(
            session, schedule_id="s1", materia_codigo="M1",
        )
        c_plan = create_comision_for_plan(
            session, plan_cursada_id="p1", materia_codigo="M1",
        )
        result = list_comisiones_for_plan_materia(session, "p1", "M1")
        assert [c.id for c in result] == [c_plan.id]


class TestClone:

    def test_clone_preserva_atributos(self, session):
        _seed(session)
        origen = create_comision_for_schedule(
            session, schedule_id="s1", materia_codigo="M1",
            nombre="Comisión Especial", cupo=15,
            descripcion="Prueba", carrera_asignada="A", numero=2,
        )
        mapa = clone_comisiones_for_plan(
            session, schedule_id="s1", plan_cursada_id="p1",
        )
        # El id original quedó como key
        assert origen.id in mapa
        clon_id = mapa[origen.id]
        clon = session.get(ComisionDB, clon_id)
        assert clon is not None
        assert clon.plan_cursada_id == "p1"
        assert clon.schedule_id is None
        assert clon.numero == 2
        assert clon.nombre == "Comisión Especial"
        assert clon.cupo == 15
        assert clon.descripcion == "Prueba"
        assert clon.carrera_asignada == "A"

    def test_clone_solo_materias_filtrado(self, session):
        _seed(session)
        # Materia extra
        session.add(MateriaDB(codigo="M2", nombre="Materia 2", cupo=20))
        session.commit()
        c1 = create_comision_for_schedule(
            session, schedule_id="s1", materia_codigo="M1",
        )
        c2 = create_comision_for_schedule(
            session, schedule_id="s1", materia_codigo="M2",
        )
        mapa = clone_comisiones_for_plan(
            session, schedule_id="s1", plan_cursada_id="p1",
            solo_materias={"M1"},
        )
        assert c1.id in mapa
        assert c2.id not in mapa

    def test_clone_no_toca_comisiones_originales(self, session):
        _seed(session)
        c1 = create_comision_for_schedule(
            session, schedule_id="s1", materia_codigo="M1",
        )
        clone_comisiones_for_plan(
            session, schedule_id="s1", plan_cursada_id="p1",
        )
        # Original sigue con schedule_id, sin plan_cursada_id
        session.refresh(c1)
        assert c1.schedule_id == "s1"
        assert c1.plan_cursada_id is None


class TestListScheduleAll:

    def test_list_for_schedule(self, session):
        _seed(session)
        create_comision_for_schedule(session, "s1", "M1")
        create_comision_for_schedule(session, "s1", "M1", numero=2)
        result = list_comisiones_for_schedule(session, "s1")
        assert len(result) == 2
