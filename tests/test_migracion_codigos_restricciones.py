"""Test de la migración de los códigos de restricción del programa lineal.

Contexto (2026-10-01): las restricciones del asignador se numeraban R1,
R3–R7 y R9–R14; R2 y R8 eran restricciones reformuladas que dejaron
huecos. Se renumeraron en forma correlativa (R1–R12) en el código, la
interfaz y la documentación. Las corridas y validaciones ya guardadas
tienen los códigos viejos en JSON y en mensajes de error: sin migrarlas,
una "R5" vieja (reparto teoría-laboratorio) se leería como la nueva R5
(coherencia de tipo), que es otra restricción.

Equivalencias: R3→R2, R4→R3, R5→R4, R6→R5, R7→R6, R9→R7, R10→R8,
R11→R9, R12→R10, R13→R11, R14→R12 (R1 no cambia).
"""

from __future__ import annotations

import json

import pytest
from sqlalchemy.pool import StaticPool
from sqlmodel import create_engine

from src.database.connection import (
    EQUIVALENCIAS_CODIGOS_RESTRICCIONES,
    _migrate_codigos_restricciones,
    renumerar_codigos_restricciones,
)


@pytest.fixture(name="engine_viejo")
def engine_viejo_fixture():
    eng = create_engine(
        "sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool,
    )
    with eng.connect() as conn:
        conn.exec_driver_sql(
            "CREATE TABLE lp_runs (id VARCHAR PRIMARY KEY, details_json TEXT, error_message TEXT)"
        )
        conn.exec_driver_sql("CREATE TABLE schedule_validations (id VARCHAR PRIMARY KEY, details_json TEXT)")
        conn.exec_driver_sql("CREATE TABLE plan_validations (id VARCHAR PRIMARY KEY, details_json TEXT)")
        detalle = {
            "bloqueos": [
                {"codigo_regla": "R13-camino", "titulo": "Camino inviable"},
                {"codigo_regla": "R1", "titulo": "Sin aula"},
            ],
            "detalles": {"R10": {"grupo": "Básicas"}, "R5": {"materias": ["MAT101"]}},
            "orden": ["R10", "R14", "R13", "R4", "R5", "R6"],
        }
        conn.exec_driver_sql(
            "INSERT INTO lp_runs VALUES ('c1', ?, ?)",
            (json.dumps(detalle), "Infactible por R4 y R13-camino"),
        )
        conn.exec_driver_sql(
            "INSERT INTO schedule_validations VALUES ('v1', ?)",
            (json.dumps({"camino_bloqueos": [{"codigo_regla": "R13-camino-cronograma"}]}),),
        )
        conn.exec_driver_sql(
            "INSERT INTO plan_validations VALUES ('p1', ?)",
            (json.dumps({"camino_bloqueos": [{"codigo_regla": "R13-camino"}]}),),
        )
        conn.commit()
    return eng


def _fila(eng, sql):
    with eng.connect() as conn:
        return conn.exec_driver_sql(sql).fetchone()


def test_equivalencias_son_correlativas():
    viejos = sorted(EQUIVALENCIAS_CODIGOS_RESTRICCIONES, key=lambda c: int(c[1:]))
    nuevos = [EQUIVALENCIAS_CODIGOS_RESTRICCIONES[c] for c in viejos]
    assert viejos == ["R3", "R4", "R5", "R6", "R7", "R9", "R10", "R11", "R12", "R13", "R14"]
    assert nuevos == [f"R{i}" for i in range(2, 13)]


def test_renumerar_aplica_todas_las_equivalencias_a_la_vez():
    # R13 → R11, y no luego R11 → R9; R10 → R8 sin tocar R1.
    assert renumerar_codigos_restricciones("R13 R11 R10 R1 R5") == "R11 R9 R8 R1 R4"
    assert renumerar_codigos_restricciones("R13-camino-cronograma") == "R11-camino-cronograma"
    # No toca identificadores que no son códigos de restricción.
    assert renumerar_codigos_restricciones("RF-LP-18 R2D2 R100 AR10") == "RF-LP-18 R2D2 R100 AR10"


def test_migra_corridas_y_validaciones(engine_viejo):
    _migrate_codigos_restricciones(engine_viejo)

    det, err = _fila(engine_viejo, "SELECT details_json, error_message FROM lp_runs")
    det = json.loads(det)
    assert [b["codigo_regla"] for b in det["bloqueos"]] == ["R11-camino", "R1"]
    assert set(det["detalles"]) == {"R8", "R4"}
    assert det["orden"] == ["R8", "R12", "R11", "R3", "R4", "R5"]
    assert err == "Infactible por R3 y R11-camino"
    (sv,) = _fila(engine_viejo, "SELECT details_json FROM schedule_validations")
    assert json.loads(sv)["camino_bloqueos"][0]["codigo_regla"] == "R11-camino-cronograma"
    (pv,) = _fila(engine_viejo, "SELECT details_json FROM plan_validations")
    assert json.loads(pv)["camino_bloqueos"][0]["codigo_regla"] == "R11-camino"


def test_es_idempotente(engine_viejo):
    _migrate_codigos_restricciones(engine_viejo)
    _migrate_codigos_restricciones(engine_viejo)  # no vuelve a correr R11 → R9

    det, err = _fila(engine_viejo, "SELECT details_json, error_message FROM lp_runs")
    assert set(json.loads(det)["detalles"]) == {"R8", "R4"}
    assert err == "Infactible por R3 y R11-camino"


def test_base_sin_tablas_no_falla():
    eng = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    _migrate_codigos_restricciones(eng)
    _migrate_codigos_restricciones(eng)
