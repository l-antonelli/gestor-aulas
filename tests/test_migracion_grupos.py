"""Tests para `_migrate_grupos_materia`.

Cubre el bootstrap inicial de grupos + asignación de materias por
prefijo y por carrera única. Idempotencia. Fallback a "Sin clasificar".
"""

from __future__ import annotations

import uuid
from datetime import date

import pytest
from sqlalchemy.pool import StaticPool
from sqlmodel import Session, SQLModel, create_engine, select

from src.database.connection import _migrate_grupos_materia
from src.database.models import (
    CarreraDB,
    CarreraSedeDB,
    GrupoMateriaDB,
    GrupoMateriaSedeDB,
    MateriaDB,
    PlanCarreraVersionDB,
    PlanEstudioDB,
    SedeDB,
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


def _seed_carreras_sedes_planes(session: Session) -> dict:
    """Seed base: 2 sedes (Pellegrini, Siberia), 2 carreras (A, B) con
    sedes asignadas, 1 plan version por carrera."""
    sede_pell = SedeDB(id="sp", nombre="Pellegrini")
    sede_sib = SedeDB(id="ss", nombre="Siberia")
    session.add_all([sede_pell, sede_sib])
    car_a = CarreraDB(codigo="A", nombre="Carrera A")
    car_b = CarreraDB(codigo="B", nombre="Carrera B")
    session.add_all([car_a, car_b])
    session.commit()
    # Asignar sedes: A → siberia, B → pellegrini.
    session.add(CarreraSedeDB(carrera_codigo="A", sede_id="ss"))
    session.add(CarreraSedeDB(carrera_codigo="B", sede_id="sp"))
    pv_a = PlanCarreraVersionDB(
        id="pv-a", carrera_codigo="A", nombre="Plan A",
        fecha_creacion=date(2026, 1, 1),
    )
    pv_b = PlanCarreraVersionDB(
        id="pv-b", carrera_codigo="B", nombre="Plan B",
        fecha_creacion=date(2026, 1, 1),
    )
    session.add_all([pv_a, pv_b])
    session.commit()
    return {"sede_pell_id": "sp", "sede_sib_id": "ss"}


def _add_materia_en_carrera(
    session: Session, codigo: str, carrera_codigo: str,
) -> None:
    if session.get(MateriaDB, codigo) is None:
        session.add(MateriaDB(codigo=codigo, nombre=f"Materia {codigo}"))
    session.add(PlanEstudioDB(
        id=str(uuid.uuid4()),
        plan_version_id=f"pv-{carrera_codigo.lower()}",
        materia_codigo=codigo,
        carrera_codigo=carrera_codigo,
    ))
    session.commit()


class TestMigracionInicial:

    def test_crea_grupo_sin_clasificar(self, engine, session):
        _seed_carreras_sedes_planes(session)
        _migrate_grupos_materia(engine)
        sc = session.exec(
            select(GrupoMateriaDB).where(
                GrupoMateriaDB.es_sin_clasificar == True,  # noqa: E712
            )
        ).all()
        assert len(sc) == 1
        assert sc[0].nombre == "Sin clasificar"
        # Sedes registradas como DURO (fallback permisivo con todas
        # las sedes activas).
        sedes = list(session.exec(
            select(GrupoMateriaSedeDB).where(
                GrupoMateriaSedeDB.grupo_id == sc[0].id,
            )
        ).all())
        assert all(s.tipo == "DURO" for s in sedes)
        assert len(sedes) == 2

    def test_crea_grupos_base_por_prefijo(self, engine, session):
        _seed_carreras_sedes_planes(session)
        _migrate_grupos_materia(engine)
        nombres = {g.nombre for g in session.exec(select(GrupoMateriaDB)).all()}
        assert {"FB", "FI", "CE", "F"}.issubset(nombres)

    def test_grupo_fb_apunta_a_pellegrini(self, engine, session):
        _seed_carreras_sedes_planes(session)
        _migrate_grupos_materia(engine)
        fb = session.exec(
            select(GrupoMateriaDB).where(GrupoMateriaDB.nombre == "FB")
        ).first()
        assert fb is not None
        sedes = list(session.exec(
            select(GrupoMateriaSedeDB).where(
                GrupoMateriaSedeDB.grupo_id == fb.id,
            )
        ).all())
        assert [s.sede_id for s in sedes] == ["sp"]

    def test_grupo_f_apunta_a_siberia(self, engine, session):
        _seed_carreras_sedes_planes(session)
        _migrate_grupos_materia(engine)
        gf = session.exec(
            select(GrupoMateriaDB).where(GrupoMateriaDB.nombre == "F")
        ).first()
        assert gf is not None
        sedes = list(session.exec(
            select(GrupoMateriaSedeDB).where(
                GrupoMateriaSedeDB.grupo_id == gf.id,
            )
        ).all())
        assert [s.sede_id for s in sedes] == ["ss"]

    def test_crea_grupos_especificas_por_carrera(self, engine, session):
        _seed_carreras_sedes_planes(session)
        _migrate_grupos_materia(engine)
        esp_a = session.exec(
            select(GrupoMateriaDB).where(
                GrupoMateriaDB.nombre == "Específicas de Carrera A",
            )
        ).first()
        assert esp_a is not None
        # Sedes: las de CarreraSedeDB para A → ss.
        sedes = list(session.exec(
            select(GrupoMateriaSedeDB).where(
                GrupoMateriaSedeDB.grupo_id == esp_a.id,
            )
        ).all())
        assert [s.sede_id for s in sedes] == ["ss"]


class TestAsignacionMaterias:

    def test_materia_prefijo_fb_va_a_grupo_fb(self, engine, session):
        _seed_carreras_sedes_planes(session)
        _add_materia_en_carrera(session, "FB01", "A")
        _migrate_grupos_materia(engine)
        m = session.get(MateriaDB, "FB01")
        assert m is not None and m.grupo_id is not None
        g = session.get(GrupoMateriaDB, m.grupo_id)
        assert g is not None and g.nombre == "FB"

    def test_materia_prefijo_fi(self, engine, session):
        _seed_carreras_sedes_planes(session)
        _add_materia_en_carrera(session, "FI2", "A")
        _migrate_grupos_materia(engine)
        m = session.get(MateriaDB, "FI2")
        assert m is not None
        g = session.get(GrupoMateriaDB, m.grupo_id)
        assert g is not None and g.nombre == "FI"

    def test_materia_prefijo_ce(self, engine, session):
        _seed_carreras_sedes_planes(session)
        _add_materia_en_carrera(session, "CE10", "A")
        _migrate_grupos_materia(engine)
        m = session.get(MateriaDB, "CE10")
        g = session.get(GrupoMateriaDB, m.grupo_id) if m else None
        assert g is not None and g.nombre == "CE"

    def test_materia_prefijo_f_no_fb_ni_fi(self, engine, session):
        _seed_carreras_sedes_planes(session)
        _add_materia_en_carrera(session, "F5", "A")
        _migrate_grupos_materia(engine)
        m = session.get(MateriaDB, "F5")
        g = session.get(GrupoMateriaDB, m.grupo_id) if m else None
        assert g is not None and g.nombre == "F"

    def test_materia_especifica_carrera_unica(self, engine, session):
        _seed_carreras_sedes_planes(session)
        # M1 solo en A, no matchea prefijo conocido.
        _add_materia_en_carrera(session, "M1", "A")
        _migrate_grupos_materia(engine)
        m = session.get(MateriaDB, "M1")
        g = session.get(GrupoMateriaDB, m.grupo_id) if m else None
        assert g is not None and g.nombre == "Específicas de Carrera A"

    def test_materia_comun_en_dos_carreras_sin_prefijo_va_a_sin_clasificar(
        self, engine, session,
    ):
        _seed_carreras_sedes_planes(session)
        # M1 en A y B, sin prefijo → sin clasificar.
        _add_materia_en_carrera(session, "M1", "A")
        _add_materia_en_carrera(session, "M1", "B")
        _migrate_grupos_materia(engine)
        m = session.get(MateriaDB, "M1")
        g = session.get(GrupoMateriaDB, m.grupo_id) if m else None
        assert g is not None and g.es_sin_clasificar is True

    def test_materia_sin_carrera_va_a_sin_clasificar(self, engine, session):
        _seed_carreras_sedes_planes(session)
        # M1 no pertenece a ningún plan y no matchea prefijo.
        session.add(MateriaDB(codigo="M1", nombre="Materia 1"))
        session.commit()
        _migrate_grupos_materia(engine)
        m = session.get(MateriaDB, "M1")
        g = session.get(GrupoMateriaDB, m.grupo_id) if m else None
        assert g is not None and g.es_sin_clasificar is True

    def test_materia_prefijo_lowercase_tambien_matchea(self, engine, session):
        """Los códigos vienen del Excel con capitalización variable — el
        matching es case-insensitive."""
        _seed_carreras_sedes_planes(session)
        _add_materia_en_carrera(session, "fb42", "A")
        _migrate_grupos_materia(engine)
        m = session.get(MateriaDB, "fb42")
        g = session.get(GrupoMateriaDB, m.grupo_id) if m else None
        assert g is not None and g.nombre == "FB"


class TestIdempotencia:

    def test_re_run_no_duplica_grupos(self, engine, session):
        _seed_carreras_sedes_planes(session)
        _add_materia_en_carrera(session, "FB01", "A")
        _migrate_grupos_materia(engine)
        n_grupos_1 = len(list(session.exec(select(GrupoMateriaDB)).all()))
        _migrate_grupos_materia(engine)
        _migrate_grupos_materia(engine)
        session.expire_all()
        n_grupos_final = len(list(session.exec(select(GrupoMateriaDB)).all()))
        assert n_grupos_final == n_grupos_1

    def test_re_run_no_reasigna_materia_movida_manualmente(
        self, engine, session,
    ):
        """Si el usuario reasigna una materia después de la migración,
        una re-run de la migración no la mueve devuelta al grupo
        original."""
        _seed_carreras_sedes_planes(session)
        _add_materia_en_carrera(session, "FB01", "A")
        _migrate_grupos_materia(engine)
        # Movemos manualmente FB01 a "Específicas de Carrera A".
        session.expire_all()
        esp_a = session.exec(
            select(GrupoMateriaDB).where(
                GrupoMateriaDB.nombre == "Específicas de Carrera A",
            )
        ).first()
        assert esp_a is not None
        m = session.get(MateriaDB, "FB01")
        assert m is not None
        m.grupo_id = esp_a.id
        session.add(m)
        session.commit()

        # Re-run.
        _migrate_grupos_materia(engine)
        session.expire_all()
        m = session.get(MateriaDB, "FB01")
        assert m is not None and m.grupo_id == esp_a.id


class TestBootstrapSinSedes:
    """Casos límite: sedes faltantes o carreras sin config."""

    def test_sin_pellegrini_grupos_fb_fi_ce_quedan_vacios(
        self, engine, session,
    ):
        # Solo Siberia — no Pellegrini.
        session.add(SedeDB(id="ss", nombre="Siberia"))
        session.add(CarreraDB(codigo="A", nombre="Carrera A"))
        session.commit()
        _migrate_grupos_materia(engine)
        fb = session.exec(
            select(GrupoMateriaDB).where(GrupoMateriaDB.nombre == "FB")
        ).first()
        assert fb is not None
        sedes = list(session.exec(
            select(GrupoMateriaSedeDB).where(
                GrupoMateriaSedeDB.grupo_id == fb.id,
            )
        ).all())
        assert sedes == []

    def test_carrera_sin_carrera_sede_deja_grupo_especificas_vacio(
        self, engine, session,
    ):
        session.add(SedeDB(id="sp", nombre="Pellegrini"))
        session.add(SedeDB(id="ss", nombre="Siberia"))
        session.add(CarreraDB(codigo="Z", nombre="Carrera Z"))
        session.commit()
        _migrate_grupos_materia(engine)
        gz = session.exec(
            select(GrupoMateriaDB).where(
                GrupoMateriaDB.nombre == "Específicas de Carrera Z",
            )
        ).first()
        assert gz is not None
        sedes = list(session.exec(
            select(GrupoMateriaSedeDB).where(
                GrupoMateriaSedeDB.grupo_id == gz.id,
            )
        ).all())
        assert sedes == []
