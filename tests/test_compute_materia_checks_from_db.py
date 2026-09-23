"""Tests para `compute_materia_checks_from_db` (Fase I.3, 2026-09-23).

El helper es la puerta que reusa el tab "Ver / Editar" del cronograma
para mostrar los mismos chequeos estructurales que el editor por
materia y el panel Validar, sin duplicar la lógica.

Cover:
- Materia con entries válidas → estado OK, `checks` completos.
- Materia sin entries → check único `materia_faltante`, estado
  `Faltante`.
- Materia fuera del catálogo → estado `Sin datos` (guard defensivo).
"""

from __future__ import annotations

import uuid
from datetime import date, time

import pytest
from sqlalchemy.pool import StaticPool
from sqlmodel import Session, SQLModel, create_engine

from src.database.models import (
    ComisionDB,
    ConfiguracionHoraria,
    MateriaDB,
    ScheduleDB,
    ScheduleEntryDB,
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


@pytest.fixture(name="patched_session")
def patched_session_fixture(engine, monkeypatch):
    """Patch `get_session` para que devuelva sesiones del engine en memoria."""

    def get_session_gen():
        with Session(engine) as sess:
            yield sess

    monkeypatch.setattr(
        "src.database.connection.get_session",
        get_session_gen,
    )
    monkeypatch.setattr(
        "src.ui.schedule_materia_editor.get_session",
        get_session_gen,
    )
    return engine


@pytest.fixture
def catalog(patched_session):
    """Catálogo mínimo: config horaria + 2 materias + 1 schedule + 1
    comisión con 2 entries (una por día) para MAT101.
    """
    with Session(patched_session) as s:
        s.add(ConfiguracionHoraria(
            id=1,
            hora_inicio_operativo=time(7, 0),
            hora_fin_operativo=time(23, 0),
            granularidad_minutos=15,
            dias_operativos="Lunes,Martes,Miércoles,Jueves,Viernes,Sábado",
        ))
        s.add(MateriaDB(
            codigo="MAT101", nombre="Análisis I",
            periodo="cuatrimestral", active=True, horas_semanales=6,
        ))
        s.add(MateriaDB(
            codigo="MAT_NULL", nombre="Sin horas",
            periodo="cuatrimestral", active=True, horas_semanales=None,
        ))

        sched_id = str(uuid.uuid4())
        s.add(ScheduleDB(
            id=sched_id, ciclo_id=None, nombre="Cronograma test",
            fecha_upload=date(2026, 9, 23), source_filename="test.xlsx",
        ))
        s.flush()

        com_id = str(uuid.uuid4())
        s.add(ComisionDB(
            id=com_id, materia_codigo="MAT101", nombre="1", numero=1,
            cupo=40,
            schedule_id=sched_id, plan_cursada_id=None,
        ))
        s.add(ScheduleEntryDB(
            id=str(uuid.uuid4()), schedule_id=sched_id,
            codigo_materia="MAT101", dia="Lunes",
            hora_inicio=time(8, 0), hora_fin=time(11, 0),
            comision_id=com_id,
        ))
        s.add(ScheduleEntryDB(
            id=str(uuid.uuid4()), schedule_id=sched_id,
            codigo_materia="MAT101", dia="Martes",
            hora_inicio=time(8, 0), hora_fin=time(11, 0),
            comision_id=com_id,
        ))
        s.commit()
    return {"schedule_id": sched_id}


class TestComputeMateriaChecksFromDb:
    def test_materia_con_entries_valida(self, catalog):
        from src.ui.schedule_materia_editor import compute_materia_checks_from_db

        result = compute_materia_checks_from_db(
            catalog["schedule_id"], "MAT101",
        )
        assert result["estado"] == "OK"
        assert result["worst"] == "ok"
        assert result["n_entries"] == 2
        assert result["n_comisiones"] == 1
        # No debería aparecer el check `materia_faltante`.
        assert not any(
            c["id"] == "materia_faltante" for c in result["checks"]
        )
        # Al menos el h/sem × comisiones = total debería estar OK.
        assert any(
            c["id"] == "hsem_x_com" and c["status"] == "ok"
            for c in result["checks"]
        )

    def test_materia_sin_entries(self, catalog):
        """Materia del catálogo sin entries en este schedule: se
        reporta con check `materia_faltante` (mismo layout que el
        editor por materia).
        """
        from src.ui.schedule_materia_editor import compute_materia_checks_from_db

        result = compute_materia_checks_from_db(
            catalog["schedule_id"], "MAT_NULL",
        )
        assert result["estado"] == "Faltante"
        assert result["worst"] == "faltante"
        assert result["n_entries"] == 0
        assert len(result["checks"]) == 1
        assert result["checks"][0]["id"] == "materia_faltante"

    def test_materia_fuera_de_catalogo(self, catalog):
        """Guard defensivo: si el código no está en `MateriaDB`, el
        helper devuelve un estado "Sin datos" con un check `error`.
        """
        from src.ui.schedule_materia_editor import compute_materia_checks_from_db

        result = compute_materia_checks_from_db(
            catalog["schedule_id"], "NO_EXISTE",
        )
        assert result["estado"] == "Sin datos"
        assert result["worst"] == "error"
        assert result["checks"][0]["id"] == "materia_no_catalogo"

    def test_materia_horas_none_con_entries_es_sin_datos(self, catalog):
        """Si `horas_semanales is None` pero la materia tiene entries,
        `estado` es "Sin datos" — prioridad sobre Revisión (mismo
        criterio que `_estado_de_materia` en `validation_ui`).
        """
        from src.database.connection import get_session
        from src.ui.schedule_materia_editor import compute_materia_checks_from_db

        with next(get_session()) as _s:
            com_id = str(uuid.uuid4())
            _s.add(ComisionDB(
                id=com_id, materia_codigo="MAT_NULL",
                nombre="1", numero=1, cupo=30,
                schedule_id=catalog["schedule_id"], plan_cursada_id=None,
            ))
            _s.add(ScheduleEntryDB(
                id=str(uuid.uuid4()),
                schedule_id=catalog["schedule_id"],
                codigo_materia="MAT_NULL", dia="Miércoles",
                hora_inicio=time(9, 0), hora_fin=time(12, 0),
                comision_id=com_id,
            ))
            _s.commit()

        result = compute_materia_checks_from_db(
            catalog["schedule_id"], "MAT_NULL",
        )
        assert result["estado"] == "Sin datos"
        assert result["n_entries"] == 1
