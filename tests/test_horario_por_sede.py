"""Horario operativo por sede.

Una sede puede tener su propio horario de apertura y cierre. Si no lo
tiene (los dos campos vacíos), no hay ninguna restricción adicional: es
el comportamiento de siempre. Si lo tiene, un horario que empieza antes
de la apertura o termina después del cierre no puede ir a ningún aula
de esa sede: ni en el asignador, ni en la reasignación manual.
"""

from __future__ import annotations

from datetime import time

import pytest
from sqlalchemy.pool import StaticPool
from sqlmodel import Session, SQLModel, create_engine

from src.database.models import AulaDB, SedeDB
from src.services.asignacion_aulas_helpers import dentro_del_horario_de_sede
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


def test_sin_horario_propio_la_sede_no_restringe():
    assert dentro_del_horario_de_sede(time(7, 0), time(23, 0), None, None)


def test_respeta_apertura_y_cierre():
    assert dentro_del_horario_de_sede(time(8, 0), time(10, 0), time(8, 0), time(22, 0))
    assert not dentro_del_horario_de_sede(time(7, 30), time(9, 0), time(8, 0), time(22, 0))
    assert not dentro_del_horario_de_sede(time(21, 0), time(23, 0), time(8, 0), time(22, 0))
    # Sólo uno de los dos límites cargado.
    assert not dentro_del_horario_de_sede(time(7, 0), time(9, 0), time(8, 0), None)
    assert dentro_del_horario_de_sede(time(7, 0), time(23, 0), None, time(23, 0))


@pytest.fixture(name="session")
def session_fixture():
    eng = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    SQLModel.metadata.create_all(eng)
    with Session(eng) as s:
        yield s


@pytest.fixture(name="ctx")
def ctx_fixture(session):
    """Un horario de 21 a 23 y dos sedes: S1 sin horario propio y S2 que
    cierra a las 22."""
    ctx = _seed_basic(session)
    session.add(SedeDB(id="S2", nombre="Cierra temprano", hora_apertura=time(8, 0), hora_cierre=time(22, 0)))
    _add_materia_con_serie(session, "MAT", ctx["ciclo"], esperados=20)
    h = _add_comision_horario(session, "plan-1", "MAT", "Lunes", 21, 23)
    session.add_all([
        AulaDB(id="abierta", sede_id="S1", codigo_aula="abierta", nombre="Abierta", capacidad=30),
        AulaDB(id="cerrada", sede_id="S2", codigo_aula="cerrada", nombre="Cerrada", capacidad=30),
    ])
    session.commit()
    return {"horario_id": h.id}


def test_por_defecto_la_sede_no_tiene_horario_propio():
    s = SedeDB(nombre="x")
    assert s.hora_apertura is None and s.hora_cierre is None


def test_el_asignador_no_usa_aulas_de_una_sede_cerrada_en_esa_franja(session, ctx):
    inputs = build_inputs(session, "plan-1", LPConfig())
    assert inputs.compat[(ctx["horario_id"], "abierta")] is True
    assert inputs.compat[(ctx["horario_id"], "cerrada")] is False


def test_la_reasignacion_manual_no_ofrece_aulas_de_una_sede_cerrada(session, ctx):
    disponibles = get_aulas_disponibles_para_horario(session, "plan-1", ctx["horario_id"])
    assert [a.id for a in disponibles] == ["abierta"]
    todas = get_aulas_todas_para_horario(session, "plan-1", ctx["horario_id"])
    assert "cerrada" not in {c.aula.id for c in todas}


def test_la_reasignacion_manual_rechaza_un_aula_de_una_sede_cerrada(session, ctx):
    res = cambiar_aula_horario(session, ctx["horario_id"], "cerrada")
    assert res.ok is False
    assert any("horario de la sede" in e.lower() for e in res.errores)
