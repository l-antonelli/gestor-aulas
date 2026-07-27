"""Tests para carrera_sede_service.py (R10: restriccion de sede por carrera)."""

import uuid
from datetime import date

import pytest
from sqlalchemy.pool import StaticPool
from sqlmodel import Session, SQLModel, create_engine, select

from src.database.models import (
    CarreraDB,
    CarreraSedeDB,
    MateriaDB,
    PlanCarreraVersionDB,
    PlanEstudioDB,
    SedeDB,
)
from src.services.carrera_sede_service import (
    get_sede_default_comunes,
    get_sedes_de_carrera,
    materia_es_comun,
    sedes_admisibles_para_carrera,
    sedes_admisibles_para_materia,
    set_sede_default_comunes,
    set_sedes_de_carrera,
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


def _seed_carreras_y_sedes(session: Session) -> dict:
    """Seed con 2 carreras (A y B) y 3 sedes (S1, S2, S3)."""
    car_a = CarreraDB(codigo="A", nombre="Carrera A")
    car_b = CarreraDB(codigo="B", nombre="Carrera B")
    s1 = SedeDB(id="S1", nombre="Sede 1")
    s2 = SedeDB(id="S2", nombre="Sede 2")
    s3 = SedeDB(id="S3", nombre="Sede 3 - Pellegrini")
    session.add_all([car_a, car_b, s1, s2, s3])
    session.commit()
    return {"car_a": car_a, "car_b": car_b, "s1": s1, "s2": s2, "s3": s3}


def _add_materia_a_carrera(
    session: Session, materia_codigo: str, carrera_codigo: str,
) -> None:
    """Crea la materia (si no existe) y la liga a la carrera via PlanEstudioDB."""
    if session.get(MateriaDB, materia_codigo) is None:
        session.add(MateriaDB(codigo=materia_codigo, nombre=f"Mat {materia_codigo}"))
    pv_id = f"pv-{carrera_codigo}"
    if session.get(PlanCarreraVersionDB, pv_id) is None:
        session.add(PlanCarreraVersionDB(
            id=pv_id,
            carrera_codigo=carrera_codigo,
            nombre=f"Plan {carrera_codigo}",
            fecha_creacion=date(2026, 1, 1),
        ))
    session.add(PlanEstudioDB(
        id=str(uuid.uuid4()),
        plan_version_id=pv_id,
        materia_codigo=materia_codigo,
        carrera_codigo=carrera_codigo,
    ))
    session.commit()


class TestSetSedesDeCarrera:

    def test_set_replace_anade_y_borra(self, session):
        ctx = _seed_carreras_y_sedes(session)
        set_sedes_de_carrera(session, "A", ["S1", "S2"])
        assert get_sedes_de_carrera(session, "A") == {"S1", "S2"}
        # Reemplazar por uno nuevo y uno previo.
        set_sedes_de_carrera(session, "A", ["S2", "S3"])
        assert get_sedes_de_carrera(session, "A") == {"S2", "S3"}

    def test_set_vacio_limpia(self, session):
        ctx = _seed_carreras_y_sedes(session)
        set_sedes_de_carrera(session, "A", ["S1"])
        set_sedes_de_carrera(session, "A", [])
        assert get_sedes_de_carrera(session, "A") == set()

    def test_set_idempotente(self, session):
        ctx = _seed_carreras_y_sedes(session)
        set_sedes_de_carrera(session, "A", ["S1", "S2"])
        set_sedes_de_carrera(session, "A", ["S1", "S2"])
        # No deberia haber duplicados; sigue siendo el mismo set.
        rows = list(session.exec(
            select(CarreraSedeDB).where(CarreraSedeDB.carrera_codigo == "A")
        ).all())
        assert len(rows) == 2


class TestSedeDefaultComunes:

    def test_set_default_unico(self, session):
        ctx = _seed_carreras_y_sedes(session)
        set_sede_default_comunes(session, "S3")
        default = get_sede_default_comunes(session)
        assert default is not None
        assert default.id == "S3"

    def test_set_default_baja_el_anterior(self, session):
        ctx = _seed_carreras_y_sedes(session)
        set_sede_default_comunes(session, "S3")
        set_sede_default_comunes(session, "S1")
        # S3 ya no es default; solo S1.
        default = get_sede_default_comunes(session)
        assert default is not None and default.id == "S1"
        s3 = session.get(SedeDB, "S3")
        assert s3 is not None and s3.es_default_comunes is False

    def test_set_default_none_desactiva(self, session):
        ctx = _seed_carreras_y_sedes(session)
        set_sede_default_comunes(session, "S3")
        set_sede_default_comunes(session, None)
        assert get_sede_default_comunes(session) is None

    def test_set_default_sede_inexistente(self, session):
        _seed_carreras_y_sedes(session)
        with pytest.raises(ValueError):
            set_sede_default_comunes(session, "noexiste")


class TestMateriaEsComun:

    def test_no_es_comun_si_una_carrera(self, session):
        _seed_carreras_y_sedes(session)
        _add_materia_a_carrera(session, "M1", "A")
        assert materia_es_comun(session, "M1") is False

    def test_es_comun_si_dos_carreras(self, session):
        _seed_carreras_y_sedes(session)
        _add_materia_a_carrera(session, "M1", "A")
        _add_materia_a_carrera(session, "M1", "B")
        assert materia_es_comun(session, "M1") is True

    def test_no_es_comun_si_no_esta_en_planes(self, session):
        _seed_carreras_y_sedes(session)
        assert materia_es_comun(session, "M_FANTASMA") is False


class TestSedesAdmisiblesParaMateria:

    def test_exclusiva_con_sedes_configuradas(self, session):
        _seed_carreras_y_sedes(session)
        _add_materia_a_carrera(session, "M1", "A")
        set_sedes_de_carrera(session, "A", ["S1", "S2"])
        assert sedes_admisibles_para_materia(session, "M1") == {"S1", "S2"}

    def test_exclusiva_sin_sedes_configuradas_devuelve_none(self, session):
        _seed_carreras_y_sedes(session)
        _add_materia_a_carrera(session, "M1", "A")
        # sin set_sedes_de_carrera para A
        assert sedes_admisibles_para_materia(session, "M1") is None

    def test_comun_con_sede_default(self, session):
        _seed_carreras_y_sedes(session)
        _add_materia_a_carrera(session, "M1", "A")
        _add_materia_a_carrera(session, "M1", "B")
        set_sede_default_comunes(session, "S3")
        assert sedes_admisibles_para_materia(session, "M1") == {"S3"}

    def test_comun_sin_sede_default_devuelve_none(self, session):
        _seed_carreras_y_sedes(session)
        _add_materia_a_carrera(session, "M1", "A")
        _add_materia_a_carrera(session, "M1", "B")
        assert sedes_admisibles_para_materia(session, "M1") is None

    def test_materia_sin_carrera_devuelve_none(self, session):
        _seed_carreras_y_sedes(session)
        # M1 nunca se asocio a un PlanEstudioDB
        assert sedes_admisibles_para_materia(session, "M1") is None


class TestSedesAdmisiblesParaCarrera:
    """Cubre la funcion usada por el override
    `HorarioDB.carrera_asignada` (comisiones orientadas a una carrera)."""

    def test_devuelve_sedes_configuradas(self, session):
        _seed_carreras_y_sedes(session)
        set_sedes_de_carrera(session, "A", ["S1", "S2"])
        assert sedes_admisibles_para_carrera(session, "A") == {"S1", "S2"}

    def test_sin_sedes_configuradas_devuelve_none(self, session):
        _seed_carreras_y_sedes(session)
        assert sedes_admisibles_para_carrera(session, "A") is None

    def test_carrera_inexistente_devuelve_none(self, session):
        _seed_carreras_y_sedes(session)
        assert sedes_admisibles_para_carrera(session, "FANTASMA") is None
