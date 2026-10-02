"""Aulas desactivadas: el asignador no las usa, pero no se borran.

Un aula puede quedar fuera de uso (obras, cambio de destino) sin
borrarla, porque planes viejos pueden tenerla asignada. Un aula inactiva:

- no entra en el modelo del asignador (no genera variables);
- no se ofrece como candidata en la reasignación manual, y la
  validación del cambio la rechaza;
- conserva sus asignaciones existentes en los planes hasta que el
  asignador se vuelva a correr.
"""

from __future__ import annotations

import pytest
from sqlalchemy.pool import StaticPool
from sqlmodel import Session, SQLModel, create_engine

from src.database.models import AulaDB, HorarioDB
from src.services.asignacion_aulas_service import (
    LPConfig,
    build_inputs,
    cambiar_aula_horario,
    get_aulas_disponibles_para_horario,
    get_aulas_todas_para_horario,
)
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
    ctx = _seed_basic(session)
    _add_materia_con_serie(session, "MAT", ctx["ciclo"], esperados=20)
    h = _add_comision_horario(session, "plan-1", "MAT", "Lunes", 8, 10)
    session.add_all([
        AulaDB(id="activa", sede_id="S1", codigo_aula="activa", nombre="Activa", capacidad=30),
        AulaDB(id="inactiva", sede_id="S1", codigo_aula="inactiva", nombre="Inactiva", capacidad=30,
               activa=False),
    ])
    session.commit()
    return {"horario_id": h.id}


def test_por_defecto_un_aula_esta_activa():
    assert AulaDB(sede_id="S1", codigo_aula="x", nombre="x", capacidad=10).activa is True


def test_el_asignador_no_usa_aulas_inactivas(session, ctx):
    inputs = build_inputs(session, "plan-1", LPConfig())
    assert {a.id for a in inputs.aulas} == {"activa"}
    assert not any(aid == "inactiva" for (_h, aid) in inputs.compat)


def test_la_reasignacion_manual_no_ofrece_aulas_inactivas(session, ctx):
    disponibles = get_aulas_disponibles_para_horario(session, "plan-1", ctx["horario_id"])
    assert [a.id for a in disponibles] == ["activa"]
    todas = get_aulas_todas_para_horario(session, "plan-1", ctx["horario_id"])
    assert "inactiva" not in {c.aula.id for c in todas}


def test_la_reasignacion_manual_rechaza_un_aula_inactiva(session, ctx):
    res = cambiar_aula_horario(session, ctx["horario_id"], "inactiva")
    assert res.ok is False
    assert any("desactivada" in e.lower() for e in res.errores)


def test_desactivar_no_toca_las_asignaciones_existentes(session, ctx):
    assert cambiar_aula_horario(session, ctx["horario_id"], "activa").ok
    aula = session.get(AulaDB, "activa")
    aula.activa = False
    session.add(aula)
    session.commit()
    assert session.get(HorarioDB, ctx["horario_id"]).aula_id == "activa"
