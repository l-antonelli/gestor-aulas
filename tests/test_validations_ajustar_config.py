"""Tests para `ajustar_horarios_a_config` (Fase I.1 del rediseño
2026-09-21) — casos de borde detectados en la auditoría 2026-09-22.

Cover:
- Task #338: entries fuera del rango operativo que hacían quedar
  `hora_fin == hora_inicio` (clase de duración cero), rompiendo
  validaciones posteriores. El fix empuja `hora_inicio` un slot hacia
  atrás para garantizar al menos una franja válida.
"""

from __future__ import annotations

import uuid
from datetime import date, time

import pytest
from sqlalchemy.pool import StaticPool
from sqlmodel import Session, SQLModel, create_engine

from src.database.models import (
    ConfiguracionHoraria,
    ScheduleDB,
    ScheduleEntryDB,
)
from src.services.validations import ajustar_horarios_a_config


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


def _mk_schedule(session: Session) -> str:
    sched_id = str(uuid.uuid4())
    session.add(ScheduleDB(
        id=sched_id, ciclo_id=None, nombre="test",
        fecha_upload=date(2026, 9, 22), source_filename="test.xlsx",
    ))
    session.commit()
    return sched_id


def _mk_config(
    session: Session,
    *,
    inicio: time = time(7, 0),
    fin: time = time(23, 0),
    gran: int = 15,
    dias: str = "Lunes,Martes,Miércoles,Jueves,Viernes,Sábado",
) -> None:
    session.add(ConfiguracionHoraria(
        id=1,
        hora_inicio_operativo=inicio,
        hora_fin_operativo=fin,
        granularidad_minutos=gran,
        dias_operativos=dias,
    ))
    session.commit()


def _mk_entry(
    session: Session, schedule_id: str, *,
    dia: str, hi: time, hf: time, codigo: str = "MAT101",
) -> ScheduleEntryDB:
    e = ScheduleEntryDB(
        id=str(uuid.uuid4()),
        schedule_id=schedule_id,
        codigo_materia=codigo,
        dia=dia,
        hora_inicio=hi,
        hora_fin=hf,
    )
    session.add(e)
    session.commit()
    session.refresh(e)
    return e


class TestBugFin23Config:
    """Task #338 (2026-09-22): entries fuera de `fin_op` no debe dejar
    la franja con duración cero.
    """

    def test_entry_pasada_fin_op_queda_franja_valida(self, session):
        """Entry `23:30-23:45` con `fin_op=23:00` debe quedar como
        `22:45-23:00` (empujar inicio hacia atrás), no `23:00-23:00`.
        """
        _mk_config(session, fin=time(23, 0), gran=15)
        sid = _mk_schedule(session)
        e = _mk_entry(
            session, sid,
            dia="Lunes",
            hi=time(23, 30), hf=time(23, 45),
        )

        n_aj, n_sk, msgs = ajustar_horarios_a_config(session, sid)
        session.refresh(e)

        assert e.hora_fin > e.hora_inicio, (
            f"hora_fin ({e.hora_fin}) debe ser > hora_inicio ({e.hora_inicio})"
        )
        # Debe estar dentro del rango operativo.
        assert e.hora_fin <= time(23, 0)
        assert e.hora_inicio >= time(7, 0)
        assert n_aj == 1
        assert n_sk == 0

    def test_entry_dentro_de_rango_no_cambia(self, session):
        _mk_config(session, fin=time(23, 0), gran=15)
        sid = _mk_schedule(session)
        e = _mk_entry(
            session, sid,
            dia="Lunes",
            hi=time(8, 0), hf=time(11, 0),
        )

        n_aj, n_sk, msgs = ajustar_horarios_a_config(session, sid)
        session.refresh(e)

        assert e.hora_inicio == time(8, 0)
        assert e.hora_fin == time(11, 0)
        assert n_aj == 0
        assert n_sk == 0

    def test_entry_dia_no_operativo_se_skippea(self, session):
        _mk_config(session, fin=time(23, 0), gran=15, dias="Lunes,Martes")
        sid = _mk_schedule(session)
        e = _mk_entry(
            session, sid,
            dia="Domingo",
            hi=time(8, 0), hf=time(11, 0),
        )

        n_aj, n_sk, msgs = ajustar_horarios_a_config(session, sid)
        session.refresh(e)

        # No se toca.
        assert e.hora_inicio == time(8, 0)
        assert e.hora_fin == time(11, 0)
        assert n_aj == 0
        assert n_sk == 1
        assert any("Domingo" in m for m in msgs)

    def test_redondea_al_slot_mas_cercano(self, session):
        _mk_config(session, gran=15)
        sid = _mk_schedule(session)
        e = _mk_entry(
            session, sid,
            dia="Lunes",
            hi=time(8, 7),   # → redondea a 08:00 (empate hacia arriba pero 7 < 8, va a 8)
            hf=time(11, 22),  # → redondea al 15 más cercano (11:15 vs 11:30)
        )

        n_aj, _, _ = ajustar_horarios_a_config(session, sid)
        session.refresh(e)

        # Duración positiva y ambos son múltiplos de 15 min desde 07:00.
        assert e.hora_fin > e.hora_inicio
        assert (e.hora_inicio.minute % 15) == 0
        assert (e.hora_fin.minute % 15) == 0
        assert n_aj == 1

    def test_config_ausente_es_no_op(self, session):
        """Sin `ConfiguracionHoraria` no hay reglas — devolver 0/0/[]."""
        sid = _mk_schedule(session)
        _mk_entry(
            session, sid,
            dia="Lunes",
            hi=time(8, 0), hf=time(11, 0),
        )

        n_aj, n_sk, msgs = ajustar_horarios_a_config(session, sid)
        assert n_aj == 0
        assert n_sk == 0
        assert msgs == []
