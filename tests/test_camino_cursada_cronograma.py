"""Tests para el chequeo de camino de cursada a nivel cronograma.

Cubre `check_camino_cursada_cronograma` (Fase B del rediseño
2026-09-15), la contraparte de `check_camino_cursada` pero operando
sobre `ScheduleDB` + `ScheduleEntryDB` en lugar de sobre un plan de
cursada persistido. Reusa `preview_plan_from_schedule` para derivar
comisiones sintéticas.

Casos cubiertos:

- **Sin conflictos**: dos materias del mismo grupo curricular en
  días distintos → chequeo devuelve lista vacía.
- **Bloqueo por solapamiento irresoluble**: dos materias obligatorias
  del mismo (carrera, año, cuatri) con una sola comisión cada una y
  horarios pisándose → bloqueo `R13-camino-cronograma`.
- **Rescatado por alternativa**: la misma configuración pero una de
  las materias tiene una segunda comisión en otro día → el DFS
  encuentra la combinación factible y no bloquea.
- **Optativas ignoradas**: una materia optativa no participa del
  chequeo aunque se solape.
- **Integración con `validar_cronograma`**: `summary.n_camino_bloqueos`
  refleja los bloqueos detectados y `_describir_problemas` los
  reporta en la política del badge.
"""

from __future__ import annotations

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
from src.services.factibilidad_service import (
    check_camino_cursada_cronograma,
)
from src.services.cronograma_validation_service import (
    compute_validation_status,
    persist_validation,
    validar_cronograma,
)
from src.services.dictado_service import create_dictados_for_ciclo


# =============================================================================
# Fixtures
# =============================================================================

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
def setup_ing_1c_2mats(session):
    """Carrera ING con plan que tiene MAT101 y FIS101 en (1° año, 1C).

    Es la topología mínima para gatillar el chequeo de camino de
    cursada: dos materias obligatorias del mismo grupo curricular.
    """
    carrera = CarreraDB(codigo="ING", nombre="Ingeniería")
    session.add(carrera)
    session.flush()

    pv = PlanCarreraVersionDB(
        id=str(uuid.uuid4()),
        carrera_codigo="ING",
        nombre="Plan A",
        fecha_creacion=date(2025, 1, 1),
    )
    session.add(pv)
    session.flush()

    m_mat = MateriaDB(
        codigo="MAT101", nombre="Análisis I",
        periodo="cuatrimestral", active=True, horas_semanales=6,
    )
    m_fis = MateriaDB(
        codigo="FIS101", nombre="Física I",
        periodo="cuatrimestral", active=True, horas_semanales=6,
    )
    session.add_all([m_mat, m_fis])
    session.flush()

    for m in (m_mat, m_fis):
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

    return {"ciclo": ciclo, "pv": pv, "m_mat": m_mat, "m_fis": m_fis}


def _add_entry(
    session: Session, schedule_id: str, materia: str,
    dia: str, hi: time, hf: time,
) -> ScheduleEntryDB:
    e = ScheduleEntryDB(
        id=str(uuid.uuid4()), schedule_id=schedule_id,
        codigo_materia=materia, dia=dia,
        hora_inicio=hi, hora_fin=hf,
    )
    session.add(e)
    return e


def _make_schedule(session: Session, ciclo_id: str) -> ScheduleDB:
    sched = ScheduleDB(
        id=str(uuid.uuid4()), ciclo_id=ciclo_id,
        nombre="Cronograma test", fecha_upload=date(2025, 3, 1),
    )
    session.add(sched)
    session.flush()
    return sched


# =============================================================================
# Tests
# =============================================================================


class TestSinConflictos:
    def test_dos_materias_en_dias_distintos(self, session, setup_ing_1c_2mats):
        """MAT y FIS en distintos días → sin bloqueos."""
        ciclo = setup_ing_1c_2mats["ciclo"]
        create_dictados_for_ciclo(session, ciclo.id)

        sched = _make_schedule(session, ciclo.id)
        _add_entry(session, sched.id, "MAT101", "Lunes", time(8, 0), time(11, 0))
        _add_entry(session, sched.id, "FIS101", "Martes", time(8, 0), time(11, 0))
        session.commit()

        bloqueos = check_camino_cursada_cronograma(session, sched.id, ciclo.id)
        assert bloqueos == []


class TestBloqueoIrresoluble:
    def test_dos_materias_solapadas_una_comision_cada_una(
        self, session, setup_ing_1c_2mats,
    ):
        """MAT y FIS con una sola comisión cada una, pisándose → bloqueo."""
        ciclo = setup_ing_1c_2mats["ciclo"]
        create_dictados_for_ciclo(session, ciclo.id)

        sched = _make_schedule(session, ciclo.id)
        _add_entry(session, sched.id, "MAT101", "Lunes", time(8, 0), time(11, 0))
        _add_entry(session, sched.id, "FIS101", "Lunes", time(9, 0), time(12, 0))
        session.commit()

        bloqueos = check_camino_cursada_cronograma(session, sched.id, ciclo.id)
        assert len(bloqueos) == 1
        b = bloqueos[0]
        assert b.codigo_regla == "R13-camino-cronograma"
        assert b.severidad == "bloqueante"
        assert "MAT101" in b.contexto["par_materias"]
        assert "FIS101" in b.contexto["par_materias"]
        assert b.contexto["carrera"] == "ING"
        assert b.contexto["anio"] == 1
        assert b.contexto["cuatri"] == "1C"


class TestRescatadoPorAlternativa:
    def test_segunda_comision_evita_bloqueo(self, session):
        """Cronograma con 2 comisiones para MAT en horarios distintos
        (una choca con FIS, la otra no). El DFS elige la combinación
        que evita el pisón → sin bloqueo.

        Para que `preview_plan_from_schedule` derive 2 comisiones sin
        paralelismo se aprovecha la regla 3 del deriver: **materia
        compartida entre ≥ 2 carreras con `total_horas /
        horas_semanales = 2`**. Además la asignación balanceada por
        horas separa las entries de distintos días en comisiones
        distintas, quedando com 1 = lunes, com 2 = miércoles.
        """
        # Setup con 2 carreras para que MAT sea "compartida"
        for cod in ("ING", "LIC"):
            session.add(CarreraDB(codigo=cod, nombre=cod))
        session.flush()
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

        # MAT101 compartida entre las 2, total_hours = 6h => 2 comisiones
        session.add(MateriaDB(
            codigo="MAT101", nombre="Mat",
            periodo="cuatrimestral", active=True, horas_semanales=3,
        ))
        # FIS101 sólo en ING
        session.add(MateriaDB(
            codigo="FIS101", nombre="Fis",
            periodo="cuatrimestral", active=True, horas_semanales=3,
        ))
        session.flush()
        # PlanEstudio: MAT en ambas carreras, FIS solo en ING
        for carrera, pv in (("ING", pv_ing), ("LIC", pv_lic)):
            session.add(PlanEstudioDB(
                plan_version_id=pv.id, materia_codigo="MAT101",
                carrera_codigo=carrera, anio_plan=1, cuatrimestre_plan="1C",
            ))
        session.add(PlanEstudioDB(
            plan_version_id=pv_ing.id, materia_codigo="FIS101",
            carrera_codigo="ING", anio_plan=1, cuatrimestre_plan="1C",
        ))
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

        # Cronograma: MAT con 2 horarios en días distintos (compartida
        # con 2 carreras + 6h / 3h = 2 comisiones), FIS un solo horario
        # que se pisa con la MAT del lunes.
        sched = _make_schedule(session, ciclo.id)
        _add_entry(session, sched.id, "MAT101", "Lunes", time(8, 0), time(11, 0))
        _add_entry(session, sched.id, "MAT101", "Miércoles", time(8, 0), time(11, 0))
        _add_entry(session, sched.id, "FIS101", "Lunes", time(9, 0), time(12, 0))
        session.commit()

        bloqueos = check_camino_cursada_cronograma(session, sched.id, ciclo.id)
        # MAT com 1 (lunes) choca con FIS, MAT com 2 (miércoles) no
        # → hay combinación factible → sin bloqueo
        assert bloqueos == []


class TestOptativasIgnoradas:
    def test_optativa_solapada_no_bloquea(self, session, setup_ing_1c_2mats):
        """Una materia optativa que se solapa con una obligatoria no
        genera bloqueo — el chequeo sólo considera obligatorias.
        """
        ciclo = setup_ing_1c_2mats["ciclo"]
        pv = setup_ing_1c_2mats["pv"]

        # Agregar una optativa que se pisa con MAT101
        opt = MateriaDB(
            codigo="OPT101", nombre="Optativa I",
            periodo="cuatrimestral", active=True, horas_semanales=3,
        )
        session.add(opt)
        session.flush()
        session.add(PlanEstudioDB(
            plan_version_id=pv.id, materia_codigo="OPT101",
            carrera_codigo="ING", anio_plan=1, cuatrimestre_plan="1C",
            optativa=True,
        ))
        session.commit()

        create_dictados_for_ciclo(session, ciclo.id)

        sched = _make_schedule(session, ciclo.id)
        _add_entry(session, sched.id, "MAT101", "Lunes", time(8, 0), time(11, 0))
        _add_entry(session, sched.id, "FIS101", "Martes", time(8, 0), time(11, 0))
        # OPT se pisa con MAT — no debe bloquear
        _add_entry(session, sched.id, "OPT101", "Lunes", time(9, 0), time(12, 0))
        session.commit()

        bloqueos = check_camino_cursada_cronograma(session, sched.id, ciclo.id)
        assert bloqueos == []


class TestIntegracionValidarCronograma:
    def test_n_camino_bloqueos_populated(self, session, setup_ing_1c_2mats):
        """`validar_cronograma` puebla `n_camino_bloqueos` con lo que
        detectó el chequeo de Fase B.
        """
        ciclo = setup_ing_1c_2mats["ciclo"]
        create_dictados_for_ciclo(session, ciclo.id)

        sched = _make_schedule(session, ciclo.id)
        _add_entry(session, sched.id, "MAT101", "Lunes", time(8, 0), time(11, 0))
        _add_entry(session, sched.id, "FIS101", "Lunes", time(9, 0), time(12, 0))
        session.commit()

        summary = validar_cronograma(session, sched.id, ciclo.id)
        assert summary.n_camino_bloqueos == 1
        assert len(summary.camino_bloqueos) == 1
        assert (
            summary.camino_bloqueos[0]["codigo_regla"]
            == "R13-camino-cronograma"
        )

    def test_badge_rojo_por_camino(self, session, setup_ing_1c_2mats):
        """Un cronograma con bloqueo de camino de cursada tiene que
        aparecer en 🔴 en `compute_validation_status`, aunque no haya
        faltantes ni particiones inválidas.
        """
        ciclo = setup_ing_1c_2mats["ciclo"]
        create_dictados_for_ciclo(session, ciclo.id)

        sched = _make_schedule(session, ciclo.id)
        _add_entry(session, sched.id, "MAT101", "Lunes", time(8, 0), time(11, 0))
        _add_entry(session, sched.id, "FIS101", "Lunes", time(9, 0), time(12, 0))
        session.commit()

        summary = validar_cronograma(session, sched.id, ciclo.id)
        persist_validation(session, summary)

        status = compute_validation_status(session, sched.id, ciclo.id)
        assert status.listo_para_plan is False
        assert "🔴" in status.badge
        assert any("camino" in p for p in status.problemas)
