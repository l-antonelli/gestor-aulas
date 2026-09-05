"""Tests para el servicio de métricas de calidad (Fase 6)."""

import uuid
from datetime import date, time

import pytest
from sqlalchemy.pool import StaticPool
from sqlmodel import Session, SQLModel, create_engine, select

from src.database.models import (
    AulaDB,
    CicloDB,
    ComisionDB,
    DictadoCicloDB,
    DictadoDB,
    HorarioDB,
    InscripcionHistoricaDB,
    MateriaDB,
    PlanificacionCursadaDB,
    SedeDB,
)
from src.services.asignacion_aulas_service import LPConfig, run_lp
from src.services.metricas_calidad_service import compute_metricas_calidad


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


def _seed_plan(session: Session) -> dict:
    """Seed: 1 ciclo, 1 sede S1, 1 aula, 1 materia M1 con 1 comisión y
    1 horario Lunes 8-10, forecast=20."""
    ciclo = CicloDB(
        id="2026-1C", anio=2026, numero=1,
        fecha_inicio=date(2026, 3, 9), fecha_fin=date(2026, 7, 3),
    )
    plan = PlanificacionCursadaDB(
        id="plan-1", nombre="Plan Test", ciclo_id="2026-1C",
    )
    sede = SedeDB(id="S1", nombre="Sede 1")
    session.add_all([ciclo, plan, sede])
    session.commit()

    materia = MateriaDB(
        codigo="M1", nombre="Mat 1",
        horas_semanales=2, horas_teoria=2, horas_laboratorio=0,
    )
    dictado = DictadoDB(
        id="d-M1", materia_codigo="M1",
        dictado_codigo="M1-2026-1C",
        inicio_dictado=date(2026, 3, 9), fin_dictado=date(2026, 7, 3),
    )
    bridge = DictadoCicloDB(dictado_id="d-M1", ciclo_id="2026-1C")
    session.add(materia)
    session.add(dictado)
    session.add(bridge)
    session.add(InscripcionHistoricaDB(
        materia_codigo="M1", anio=2025, cuatrimestre="1C", inscriptos=20,
    ))
    session.commit()

    aula = AulaDB(
        id="a1", sede_id="S1", codigo_aula="A1", nombre="A1",
        capacidad=30, tipo="teorica",
    )
    session.add(aula)
    session.commit()

    com_id = str(uuid.uuid4())
    com = ComisionDB(
        id=com_id, materia_codigo="M1", plan_cursada_id="plan-1",
        comision_key="M1-001", nombre="Com 1", numero=1, cupo=30,
        coef_asignacion=1.0,
    )
    hor = HorarioDB(
        id=str(uuid.uuid4()), comision_id=com_id, codigo_materia="M1",
        dia="Lunes", hora_inicio=time(8, 0), hora_fin=time(10, 0),
        tipo_clase="teorica",
    )
    session.add(com)
    session.add(hor)
    session.commit()
    return {"com_id": com_id, "horario_id": hor.id}


class TestCompteMetricasCoberturaBasica:

    def test_plan_vacio_devuelve_metricas_ceros(self, session):
        """Plan sin comisiones: métricas todas en 0, no rompe."""
        ciclo = CicloDB(
            id="2026-1C", anio=2026, numero=1,
            fecha_inicio=date(2026, 3, 9), fecha_fin=date(2026, 7, 3),
        )
        plan = PlanificacionCursadaDB(
            id="plan-vacio", nombre="Vacío", ciclo_id="2026-1C",
        )
        session.add_all([ciclo, plan])
        session.commit()
        m = compute_metricas_calidad(session, "plan-vacio")
        assert m.cobertura.n_horarios_total == 0
        assert m.cobertura.n_comisiones_total == 0

    def test_horario_sin_aula_va_a_sin_aula(self, session):
        """Horario con aula_id None se cuenta en n_horarios_sin_aula."""
        _seed_plan(session)
        m = compute_metricas_calidad(session, "plan-1")
        assert m.cobertura.n_horarios_total == 1
        assert m.cobertura.n_horarios_asignados == 0
        assert m.cobertura.n_horarios_sin_aula == 1
        assert m.cobertura.n_comisiones_completas == 0

    def test_horario_asignado_a_sede_preferida(self, session):
        """Horario asignado a la única aula: entra en 'sede preferida' o
        'sin sede preferida' según la config de sedes admisibles.
        En este seed no hay `carrera_sede_service` configurado, así que
        `sedes_admisibles_para_materia` devuelve `None` → sede pref None.
        """
        ctx = _seed_plan(session)
        hor = session.get(HorarioDB, ctx["horario_id"])
        hor.aula_id = "a1"
        session.add(hor)
        session.commit()

        m = compute_metricas_calidad(session, "plan-1")
        assert m.cobertura.n_horarios_asignados == 1
        assert m.cobertura.n_horarios_sin_aula == 0
        # Sin restricción → sede preferida = None → cae en la categoría
        # residual "sin sede preferida".
        total_por_categoria = (
            m.cobertura.n_horarios_en_sede_preferida
            + m.cobertura.n_horarios_en_sede_alternativa
            + m.cobertura.n_horarios_sin_sede_preferida
        )
        assert total_por_categoria == 1
        assert m.cobertura.n_comisiones_completas == 1


class TestSobreSubOcupacion:

    def test_aula_grande_registra_subutilizacion(self, session):
        """Aula de 30 con 20 esperados (67% de ocupación) → subutilizado."""
        ctx = _seed_plan(session)
        hor = session.get(HorarioDB, ctx["horario_id"])
        hor.aula_id = "a1"
        session.add(hor)
        session.commit()
        m = compute_metricas_calidad(session, "plan-1")
        # 20/30 = 0.67, tol_under_default = 0.20 → cap*(1-tol) = 24.
        # 20 < 24 → subutilizado.
        assert m.ocupacion.n_subutilizados == 1
        assert m.ocupacion.subutilizacion_total_asientos == 10
        assert m.ocupacion.peor_subutilizado is not None
        assert m.ocupacion.peor_subutilizado["ociosos"] == 10

    def test_aula_chica_registra_sobreocupacion(self, session):
        """Aula de 15 con 20 esperados → sobreocupado con 5 faltantes."""
        _seed_plan(session)
        aula = session.get(AulaDB, "a1")
        aula.capacidad = 15
        session.add(aula)
        # Aplicar aula al horario.
        hor = session.exec(select(HorarioDB)).first()
        hor.aula_id = "a1"
        session.add(hor)
        session.commit()

        m = compute_metricas_calidad(session, "plan-1")
        assert m.ocupacion.n_sobreocupados == 1
        assert m.ocupacion.sobrecupo_total_asientos == 5
        assert m.ocupacion.peor_sobreocupado["faltantes"] == 5

    def test_aula_justa_es_ok(self, session):
        """Aula de 22 con 20 esperados: 20/22 = 0.91, no sobre ni sub."""
        _seed_plan(session)
        aula = session.get(AulaDB, "a1")
        aula.capacidad = 22
        session.add(aula)
        hor = session.exec(select(HorarioDB)).first()
        hor.aula_id = "a1"
        session.add(hor)
        session.commit()

        m = compute_metricas_calidad(session, "plan-1")
        assert m.ocupacion.n_ok == 1
        assert m.ocupacion.n_sobreocupados == 0
        assert m.ocupacion.n_subutilizados == 0


class TestDistribucionAulas:

    def test_aula_no_usada_se_reporta_como_ociosa(self, session):
        """Aula del catálogo sin horarios asignados aparece en aulas_ociosas."""
        _seed_plan(session)
        # Agrego una segunda aula que nadie usa.
        session.add(AulaDB(
            id="a2", sede_id="S1", codigo_aula="A2", nombre="A2",
            capacidad=30, tipo="teorica",
        ))
        session.commit()

        m = compute_metricas_calidad(session, "plan-1")
        assert m.aulas.n_aulas_catalogo == 2
        # Nadie tiene aula asignada → ambas ociosas.
        assert m.aulas.n_aulas_ociosas == 2
        nombres_ociosas = {x["aula_nombre"] for x in m.aulas.aulas_ociosas}
        assert nombres_ociosas == {"A1", "A2"}

    def test_concentracion_por_sede_suma_100(self, session):
        """La concentración por sede suma 100% (cuando hay ocupación)."""
        ctx = _seed_plan(session)
        hor = session.get(HorarioDB, ctx["horario_id"])
        hor.aula_id = "a1"
        session.add(hor)
        session.commit()

        m = compute_metricas_calidad(session, "plan-1")
        total = sum(s["porcentaje"] for s in m.aulas.concentracion_por_sede)
        assert abs(total - 100.0) < 0.01


class TestTrasladosIntersede:

    def _seed_dos_horarios_dos_sedes(self, session):
        _seed_plan(session)
        # Segunda sede + aula.
        session.add(SedeDB(id="S2", nombre="Sede 2"))
        session.add(AulaDB(
            id="a2", sede_id="S2", codigo_aula="A2", nombre="A2",
            capacidad=30, tipo="teorica",
        ))
        # Segundo horario contiguo en la misma comisión (Lunes 10-12).
        com_id = session.exec(select(ComisionDB)).first().id
        h2 = HorarioDB(
            id=str(uuid.uuid4()), comision_id=com_id, codigo_materia="M1",
            dia="Lunes", hora_inicio=time(10, 0), hora_fin=time(12, 0),
            tipo_clase="teorica",
        )
        session.add(h2)
        session.commit()
        return h2

    def test_dos_horarios_misma_sede_no_generan_traslado(self, session):
        h2 = self._seed_dos_horarios_dos_sedes(session)
        # Asigno ambos a la sede S1.
        for h in session.exec(select(HorarioDB)).all():
            h.aula_id = "a1"
            session.add(h)
        session.commit()
        m = compute_metricas_calidad(session, "plan-1")
        assert m.lp.n_comisiones_con_traslado_intersede == 0

    def test_dos_horarios_sedes_distintas_gap_corto_genera_traslado(self, session):
        h2 = self._seed_dos_horarios_dos_sedes(session)
        # h1 → S1, h2 → S2, gap = 0 min → traslado.
        h1 = session.exec(
            select(HorarioDB).where(HorarioDB.hora_inicio == time(8, 0))
        ).first()
        h1.aula_id = "a1"
        h2 = session.exec(
            select(HorarioDB).where(HorarioDB.hora_inicio == time(10, 0))
        ).first()
        h2.aula_id = "a2"
        session.add(h1); session.add(h2)
        session.commit()

        m = compute_metricas_calidad(session, "plan-1")
        assert m.lp.n_comisiones_con_traslado_intersede == 1
        assert len(m.lp.detalle_traslados) == 1
        t = m.lp.detalle_traslados[0]
        assert t["gap_minutos"] == 0
        assert t["sede_1"] != t["sede_2"]


class TestIntegracionConLPReal:
    """Corre el LP real y verifica que las métricas resulten coherentes."""

    def test_lp_optimal_produce_metricas_lp_pobladas(self, session):
        ctx = _seed_plan(session)
        run_lp(session, "plan-1", LPConfig())

        m = compute_metricas_calidad(session, "plan-1")
        assert m.lp.objetivo is not None
        assert m.lp.tiempo_solve_segundos is not None
        assert m.lp.tiempo_solve_segundos >= 0
        assert m.lp.status_ultima_corrida == "optimal"
        assert m.lp.fecha_ultima_corrida is not None
        # Después del LP, el horario tiene aula.
        assert m.cobertura.n_horarios_asignados == 1
