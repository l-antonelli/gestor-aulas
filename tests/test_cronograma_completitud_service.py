"""Tests para cronograma_completitud_service.

Fase D del rediseño 2026-09-15. Cubre las dos vistas desagregadas de
completitud (por grupo de materias y por carrera-año).
"""

from __future__ import annotations

import uuid
from datetime import date, time

import pytest
from sqlalchemy.pool import StaticPool
from sqlmodel import Session, SQLModel, create_engine, select

from src.database.models import (
    CarreraDB,
    CicloDB,
    CicloPlanVersionDB,
    GrupoMateriaDB,
    MateriaDB,
    PlanCarreraVersionDB,
    PlanEstudioDB,
    ScheduleDB,
    ScheduleEntryDB,
)
from src.services.cronograma_completitud_service import (
    completitud_por_carrera_anio,
    completitud_por_grupo_materia,
)
from src.services.dictado_service import create_dictados_for_ciclo


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


@pytest.fixture
def setup_2_carreras_2_grupos(session):
    """Setup rico: 2 carreras (ING, LIC) con 2 años (1° y 2°), 4
    materias distribuidas en 2 grupos (F básico, Específicas).

    Ciclo 2025-1C con dictados de todas las materias.
    Cronograma vacío al inicio.
    """
    # Carreras
    session.add(CarreraDB(codigo="ING", nombre="Ingeniería"))
    session.add(CarreraDB(codigo="LIC", nombre="Licenciatura"))
    session.flush()

    # Grupos de materias
    g_f = GrupoMateriaDB(
        id=str(uuid.uuid4()), nombre="F", descripcion="Ciclo básico",
        es_sin_clasificar=False,
    )
    g_ing = GrupoMateriaDB(
        id=str(uuid.uuid4()), nombre="Específicas ING",
        descripcion="Materias exclusivas de ingeniería",
        es_sin_clasificar=False,
    )
    session.add_all([g_f, g_ing])
    session.flush()

    # Materias
    session.add(MateriaDB(
        codigo="F101", nombre="Física I",
        periodo="cuatrimestral", active=True, horas_semanales=6,
        grupo_id=g_f.id,
    ))
    session.add(MateriaDB(
        codigo="F201", nombre="Física II",
        periodo="cuatrimestral", active=True, horas_semanales=6,
        grupo_id=g_f.id,
    ))
    session.add(MateriaDB(
        codigo="ING101", nombre="Análisis Estructural",
        periodo="cuatrimestral", active=True, horas_semanales=6,
        grupo_id=g_ing.id,
    ))
    session.add(MateriaDB(
        codigo="ING201", nombre="Diseño Mecánico",
        periodo="cuatrimestral", active=True, horas_semanales=6,
        grupo_id=g_ing.id,
    ))
    session.flush()

    # Planes de estudio: F101 y F201 comunes a ambas; ING* sólo en ING
    pv_ing = PlanCarreraVersionDB(
        id=str(uuid.uuid4()), carrera_codigo="ING",
        nombre="Plan ING", fecha_creacion=date(2025, 1, 1),
    )
    pv_lic = PlanCarreraVersionDB(
        id=str(uuid.uuid4()), carrera_codigo="LIC",
        nombre="Plan LIC", fecha_creacion=date(2025, 1, 1),
    )
    session.add_all([pv_ing, pv_lic])
    session.flush()

    # Año 1: F101 en ambas
    for pv, car in [(pv_ing, "ING"), (pv_lic, "LIC")]:
        session.add(PlanEstudioDB(
            plan_version_id=pv.id, materia_codigo="F101",
            carrera_codigo=car, anio_plan=1, cuatrimestre_plan="1C",
        ))
    # Año 2: F201 en ambas
    for pv, car in [(pv_ing, "ING"), (pv_lic, "LIC")]:
        session.add(PlanEstudioDB(
            plan_version_id=pv.id, materia_codigo="F201",
            carrera_codigo=car, anio_plan=2, cuatrimestre_plan="1C",
        ))
    # ING101 sólo en ING año 1
    session.add(PlanEstudioDB(
        plan_version_id=pv_ing.id, materia_codigo="ING101",
        carrera_codigo="ING", anio_plan=1, cuatrimestre_plan="1C",
    ))
    # ING201 sólo en ING año 2
    session.add(PlanEstudioDB(
        plan_version_id=pv_ing.id, materia_codigo="ING201",
        carrera_codigo="ING", anio_plan=2, cuatrimestre_plan="1C",
    ))

    # Ciclo + link
    ciclo = CicloDB(
        id="2025-1C", anio=2025, numero=1,
        fecha_inicio=date(2025, 3, 10), fecha_fin=date(2025, 7, 5),
    )
    session.add(ciclo)
    session.flush()
    session.add(CicloPlanVersionDB(ciclo_id=ciclo.id, plan_version_id=pv_ing.id))
    session.add(CicloPlanVersionDB(ciclo_id=ciclo.id, plan_version_id=pv_lic.id))
    session.commit()
    create_dictados_for_ciclo(session, ciclo.id)

    # Cronograma vacío
    sched = ScheduleDB(
        id=str(uuid.uuid4()), ciclo_id=ciclo.id,
        nombre="test", fecha_upload=date(2025, 3, 1),
    )
    session.add(sched)
    session.commit()

    return {
        "ciclo": ciclo, "sched": sched, "g_f": g_f, "g_ing": g_ing,
    }


def _add_entry(session, sched_id, materia_codigo, dia="Lunes"):
    session.add(ScheduleEntryDB(
        id=str(uuid.uuid4()), schedule_id=sched_id,
        codigo_materia=materia_codigo, dia=dia,
        hora_inicio=time(8, 0), hora_fin=time(11, 0),
    ))
    session.commit()


# =============================================================================
# Tests: por grupo
# =============================================================================


class TestPorGrupoMateria:
    def test_cronograma_vacio_todo_faltante(self, session, setup_2_carreras_2_grupos):
        s = setup_2_carreras_2_grupos
        breakdown = completitud_por_grupo_materia(
            session, s["sched"].id, s["ciclo"].id,
        )
        # 2 grupos, cada uno con 2 materias esperadas
        assert len(breakdown) == 2
        nombres = {b.grupo_nombre for b in breakdown}
        assert nombres == {"F", "Específicas ING"}
        for b in breakdown:
            assert b.n_esperadas == 2
            assert b.n_cubiertas == 0
            assert b.pct_completitud == 0.0

    def test_cronograma_parcial(self, session, setup_2_carreras_2_grupos):
        """Cargar F101 → grupo F queda al 50%, específicas ING sigue en 0."""
        s = setup_2_carreras_2_grupos
        _add_entry(session, s["sched"].id, "F101")
        breakdown = completitud_por_grupo_materia(
            session, s["sched"].id, s["ciclo"].id,
        )
        by_name = {b.grupo_nombre: b for b in breakdown}
        assert by_name["F"].n_cubiertas == 1
        assert by_name["F"].pct_completitud == 50.0
        assert by_name["F"].materias_faltantes == [("F201", "Física II")]
        assert by_name["Específicas ING"].n_cubiertas == 0
        assert by_name["Específicas ING"].n_faltantes == 2

    def test_cronograma_completo(self, session, setup_2_carreras_2_grupos):
        s = setup_2_carreras_2_grupos
        for mc in ("F101", "F201", "ING101", "ING201"):
            _add_entry(session, s["sched"].id, mc)
        breakdown = completitud_por_grupo_materia(
            session, s["sched"].id, s["ciclo"].id,
        )
        for b in breakdown:
            assert b.n_cubiertas == b.n_esperadas
            assert b.pct_completitud == 100.0
            assert b.materias_faltantes == []


class TestPorGrupoConOptativas:
    def test_excluir_optativas_por_default(self, session, setup_2_carreras_2_grupos):
        """Fase D: por default exclude_optativas=True. Una optativa
        agregada al plan no debería aparecer en el breakdown.
        """
        s = setup_2_carreras_2_grupos
        # Agregar OPT101 como optativa del grupo F
        opt = MateriaDB(
            codigo="OPT101", nombre="Optativa I",
            periodo="cuatrimestral", active=True, horas_semanales=3,
            grupo_id=s["g_f"].id,
        )
        session.add(opt)
        session.flush()
        # Marcarla como optativa en el plan ING
        pv_ing = session.exec(select(PlanCarreraVersionDB).where(
            PlanCarreraVersionDB.carrera_codigo == "ING",
        )).first() if False else None  # noop
        # Buscar plan version via join más simple:
        from sqlmodel import select
        pv = session.exec(
            select(PlanCarreraVersionDB).where(
                PlanCarreraVersionDB.carrera_codigo == "ING"
            )
        ).first()
        assert pv is not None
        session.add(PlanEstudioDB(
            plan_version_id=pv.id, materia_codigo="OPT101",
            carrera_codigo="ING", anio_plan=4, cuatrimestre_plan="1C",
            optativa=True,
        ))
        session.commit()
        create_dictados_for_ciclo(session, s["ciclo"].id)

        # Default: excluir optativas
        breakdown = completitud_por_grupo_materia(
            session, s["sched"].id, s["ciclo"].id,
        )
        by_name = {b.grupo_nombre: b for b in breakdown}
        # Grupo F: sigue con 2 esperadas (F101, F201), OPT101 no cuenta
        assert by_name["F"].n_esperadas == 2

        # Con exclude_optativas=False: OPT101 sí cuenta
        breakdown_all = completitud_por_grupo_materia(
            session, s["sched"].id, s["ciclo"].id, exclude_optativas=False,
        )
        by_name_all = {b.grupo_nombre: b for b in breakdown_all}
        assert by_name_all["F"].n_esperadas == 3


class TestOrdenamiento:
    def test_sin_clasificar_va_al_final(self, session, setup_2_carreras_2_grupos):
        s = setup_2_carreras_2_grupos
        # Marcar g_f como sin_clasificar y agregar otra materia
        s["g_f"].es_sin_clasificar = True
        session.add(s["g_f"])
        # Crear un tercer grupo "AAA" (alfabéticamente antes de F pero
        # no sin_clasificar → debería aparecer primero)
        g_aaa = GrupoMateriaDB(
            id=str(uuid.uuid4()), nombre="AAA",
            es_sin_clasificar=False,
        )
        session.add(g_aaa)
        session.flush()
        # Reasignar una materia al grupo AAA
        mat = session.exec(select(MateriaDB).where(
            MateriaDB.codigo == "ING101",
        )).first()
        assert mat is not None
        mat.grupo_id = g_aaa.id
        session.commit()

        breakdown = completitud_por_grupo_materia(
            session, s["sched"].id, s["ciclo"].id,
        )
        nombres = [b.grupo_nombre for b in breakdown]
        # F (sin_clasificar=True) va al final
        assert nombres[-1] == "F"


# =============================================================================
# Tests: por carrera-año
# =============================================================================


class TestPorCarreraAnio:
    def test_cronograma_vacio(self, session, setup_2_carreras_2_grupos):
        s = setup_2_carreras_2_grupos
        breakdown = completitud_por_carrera_anio(
            session, s["sched"].id, s["ciclo"].id,
        )
        # Debería tener 4 grupos: ING año 1, ING año 2, LIC año 1, LIC año 2
        # (todos son 1C, coincidiendo con el ciclo)
        assert len(breakdown) == 4
        for b in breakdown:
            assert b.n_cubiertas == 0
            assert b.n_esperadas > 0

    def test_carga_parcial_solo_actualiza_carreras_afectadas(
        self, session, setup_2_carreras_2_grupos,
    ):
        """Cargar F101 → ambas carreras año 1 tienen esa materia
        cubierta.
        """
        s = setup_2_carreras_2_grupos
        _add_entry(session, s["sched"].id, "F101")
        breakdown = completitud_por_carrera_anio(
            session, s["sched"].id, s["ciclo"].id,
        )
        by_key = {(b.carrera_codigo, b.anio): b for b in breakdown}

        # ING año 1: espera F101 + ING101 → 2 esperadas, 1 cubierta
        assert by_key[("ING", 1)].n_esperadas == 2
        assert by_key[("ING", 1)].n_cubiertas == 1
        assert by_key[("ING", 1)].materias_faltantes == [
            ("ING101", "Análisis Estructural"),
        ]

        # LIC año 1: espera sólo F101 → 1 esperada, 1 cubierta
        assert by_key[("LIC", 1)].n_esperadas == 1
        assert by_key[("LIC", 1)].n_cubiertas == 1
        assert by_key[("LIC", 1)].pct_completitud == 100.0

        # ING año 2: F201 + ING201, ambas faltan
        assert by_key[("ING", 2)].n_cubiertas == 0

    def test_carrera_nombre_populated(self, session, setup_2_carreras_2_grupos):
        s = setup_2_carreras_2_grupos
        breakdown = completitud_por_carrera_anio(
            session, s["sched"].id, s["ciclo"].id,
        )
        nombres = {b.carrera_nombre for b in breakdown}
        assert nombres == {"Ingeniería", "Licenciatura"}


class TestPorCarreraAnioSinDictados:
    def test_ciclo_sin_dictados_devuelve_vacio(self, session):
        c = CicloDB(
            id="2025-2C", anio=2025, numero=2,
            fecha_inicio=date(2025, 8, 1), fecha_fin=date(2025, 11, 30),
        )
        session.add(c)
        session.commit()
        # Sin CicloPlanVersion → build_grupos_curriculares_del_ciclo
        # devuelve {} → resultado []
        sched = ScheduleDB(
            id=str(uuid.uuid4()), ciclo_id=c.id,
            nombre="t", fecha_upload=date(2025, 8, 1),
        )
        session.add(sched)
        session.commit()
        breakdown = completitud_por_carrera_anio(session, sched.id, c.id)
        assert breakdown == []


class TestExcluirOptativasCarreraAnio:
    def test_optativa_no_cuenta_por_default(
        self, session, setup_2_carreras_2_grupos,
    ):
        s = setup_2_carreras_2_grupos
        # Agregar OPT101 optativa a ING año 1
        opt = MateriaDB(
            codigo="OPT101", nombre="Optativa I",
            periodo="cuatrimestral", active=True, horas_semanales=3,
            grupo_id=s["g_f"].id,
        )
        session.add(opt)
        session.flush()
        from sqlmodel import select
        pv = session.exec(
            select(PlanCarreraVersionDB).where(
                PlanCarreraVersionDB.carrera_codigo == "ING"
            )
        ).first()
        assert pv is not None
        session.add(PlanEstudioDB(
            plan_version_id=pv.id, materia_codigo="OPT101",
            carrera_codigo="ING", anio_plan=1, cuatrimestre_plan="1C",
            optativa=True,
        ))
        session.commit()
        create_dictados_for_ciclo(session, s["ciclo"].id)

        # Por default (excluir): ING año 1 sigue en 2 esperadas
        # (F101 + ING101), sin la optativa.
        breakdown = completitud_por_carrera_anio(
            session, s["sched"].id, s["ciclo"].id,
        )
        by_key = {(b.carrera_codigo, b.anio): b for b in breakdown}
        assert by_key[("ING", 1)].n_esperadas == 2

        # Incluyendo optativas: 3 esperadas
        breakdown_all = completitud_por_carrera_anio(
            session, s["sched"].id, s["ciclo"].id, exclude_optativas=False,
        )
        by_key_all = {(b.carrera_codigo, b.anio): b for b in breakdown_all}
        assert by_key_all[("ING", 1)].n_esperadas == 3
