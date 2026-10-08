"""Diagnóstico de infactibilidad por sedes y verificación previa con los
modos de la corrida.

Caso real (2026-10-03): con los grupos de las carreras de la Siberia en
modo duro, el diagnóstico no podía probar la relajación de sedes (R8)
porque la búsqueda de grupos que conviene pasar a modo blando fallaba
con un NameError, y el error quedaba oculto. Además, la verificación
previa calculaba las sedes admisibles suponiendo modo duro para todos
los grupos, en lugar de usar los modos elegidos para la corrida.
"""

from __future__ import annotations

import pytest
from sqlalchemy.pool import StaticPool
from sqlmodel import Session, SQLModel, create_engine

from src.database.models import AulaDB, GrupoMateriaDB, GrupoMateriaSedeDB, MateriaDB, SedeDB
from src.services.asignacion_aulas_service import (
    LPConfig,
    _iss_combinaciones_rescate,
    _iss_r10_grupos_rescate,
)
from src.services.factibilidad_service import check_factibilidad_estructural
from tests.test_asignacion_aulas_service import (
    _add_comision_horario,
    _add_materia_con_serie,
    _seed_basic,
)


@pytest.fixture(name="session")
def session_fixture():
    eng = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    SQLModel.metadata.create_all(eng)
    with Session(eng) as s:
        yield s


@pytest.fixture(name="ctx")
def ctx_fixture(session):
    """Una materia de un grupo cuya sede dura es S2 (sin aulas) y cuya
    sede blanda es S1 (con un aula): en modo duro es infactible, en modo
    blando no."""
    ctx = _seed_basic(session)
    session.add(SedeDB(id="S2", nombre="Sede sin aulas"))
    grupo = GrupoMateriaDB(id="G1", nombre="Grupo de prueba")
    session.add(grupo)
    session.add_all([
        GrupoMateriaSedeDB(grupo_id="G1", sede_id="S2", tipo="DURO", orden=0),
        GrupoMateriaSedeDB(grupo_id="G1", sede_id="S1", tipo="BLANDO", orden=0),
    ])
    session.commit()
    _add_materia_con_serie(session, "MAT", ctx["ciclo"], esperados=20)
    mat = session.get(MateriaDB, "MAT")
    mat.grupo_id = "G1"
    session.add(mat)
    session.add(AulaDB(id="a1", sede_id="S1", codigo_aula="a1", nombre="Aula 1", capacidad=30))
    session.commit()
    _add_comision_horario(session, "plan-1", "MAT", "Lunes", 8, 10)
    return ctx


def test_la_busqueda_de_grupos_a_flexibilizar_no_falla(session, ctx):
    rescate = _iss_r10_grupos_rescate(
        session=session, plan_id="plan-1",
        base_config=LPConfig(modos_por_grupo={"G1": "DURO"}, timeout_seconds=30),
    )
    assert [r["grupo_id"] for r in rescate] == ["G1"]


def test_la_busqueda_de_combinaciones_no_falla(session, ctx):
    # Basta con que no falle (antes, NameError por `func` sin importar).
    _iss_combinaciones_rescate(
        session=session, plan_id="plan-1",
        base_config=LPConfig(modos_por_grupo={"G1": "DURO"}, timeout_seconds=30),
    )


def test_la_verificacion_previa_usa_los_modos_de_la_corrida(session, ctx):
    duro = check_factibilidad_estructural(session, "plan-1", modos_por_grupo={"G1": "DURO"})
    blando = check_factibilidad_estructural(session, "plan-1", modos_por_grupo={"G1": "BLANDO"})
    assert not duro.factible  # en modo duro sólo admite S2, que no tiene aulas
    assert blando.factible    # en modo blando cualquier sede vale


@pytest.fixture(name="ctx_r11")
def ctx_r11_fixture(session):
    """Dos materias del mismo año de una carrera, en horarios seguidos
    del lunes, cuyos grupos tienen sedes duras distintas: los alumnos no
    pueden trasladarse entre una clase y la otra."""
    from datetime import date

    from src.database.models import (
        CarreraDB, CicloPlanVersionDB, PlanCarreraVersionDB, PlanEstudioDB,
    )

    ctx = _seed_basic(session)
    session.add(SedeDB(id="S2", nombre="Otra sede"))
    session.add_all([
        GrupoMateriaDB(id="GA", nombre="Grupo A"),
        GrupoMateriaDB(id="GB", nombre="Grupo B"),
        GrupoMateriaSedeDB(grupo_id="GA", sede_id="S1", tipo="DURO", orden=0),
        GrupoMateriaSedeDB(grupo_id="GB", sede_id="S2", tipo="DURO", orden=0),
        CarreraDB(codigo="C1", nombre="Carrera 1"),
        PlanCarreraVersionDB(id="pv1", carrera_codigo="C1", nombre="Plan",
                             fecha_creacion=date(2026, 1, 1), active=True),
        CicloPlanVersionDB(ciclo_id=ctx["ciclo"].id, plan_version_id="pv1"),
        AulaDB(id="a1", sede_id="S1", codigo_aula="a1", nombre="Aula 1", capacidad=30),
        AulaDB(id="a2", sede_id="S2", codigo_aula="a2", nombre="Aula 2", capacidad=30),
    ])
    session.commit()
    for codigo, grupo in (("MA", "GA"), ("MB", "GB")):
        _add_materia_con_serie(session, codigo, ctx["ciclo"], esperados=20)
        mat = session.get(MateriaDB, codigo)
        mat.grupo_id = grupo
        session.add(mat)
        session.add(PlanEstudioDB(plan_version_id="pv1", materia_codigo=codigo,
                                  carrera_codigo="C1", anio_plan=1, cuatrimestre_plan="1C"))
    session.commit()
    _add_comision_horario(session, "plan-1", "MA", "Lunes", 8, 10)
    _add_comision_horario(session, "plan-1", "MB", "Lunes", 10, 12)
    return ctx


def test_la_verificacion_previa_revisa_el_margen_entre_materias_del_mismo_anio(session, ctx_r11):
    # Mismos pares que el modelo: los alumnos de primer año de C1 cursan
    # MA y MB seguidas, sin tiempo para cambiar de sede.
    duro = check_factibilidad_estructural(
        session, "plan-1", modos_por_grupo={"GA": "DURO", "GB": "DURO"})
    blando = check_factibilidad_estructural(
        session, "plan-1", modos_por_grupo={"GA": "BLANDO", "GB": "BLANDO"})
    (r11,) = [b for b in duro.bloqueos if b.codigo_regla == "R11"]
    assert r11.titulo.startswith("Alumnos de 1.º año de Carrera 1 · MA/MB")
    assert blando.factible


def test_las_pruebas_del_diagnostico_solo_buscan_factibilidad(session, ctx):
    # El diagnóstico sólo necesita saber si existe alguna asignación: con
    # objetivo nulo el resolutor para en la primera solución que
    # encuentra, en lugar de optimizar hasta el tiempo límite.
    from src.services.asignacion_aulas_service import build_inputs, build_model, es_factible

    for modo, esperado in (("BLANDO", True), ("DURO", False)):
        cfg = LPConfig(modos_por_grupo={"G1": modo}, timeout_seconds=30)
        prob, _ = build_model(build_inputs(session, "plan-1", cfg), cfg)
        assert es_factible(prob, cfg) is esperado
        assert all(c == 0 for c in prob.objective.values())  # objetivo nulo
