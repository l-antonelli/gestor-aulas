"""Tests de los helpers puros de conteo de `validation_ui`
(auditoría H6, 2026-09-23).

El bug reproducido: la tabla "Resumen por carrera" contaba una materia
común N×M veces (N = ubicaciones curriculares de la materia, M =
carreras de su `carreras_set`), porque el loop iteraba las filas de
`_filtered` (una por ubicación) y cada fila arrastra el set COMPLETO
de carreras de la materia. Una carrera con 2 materias reales mostraba
3. Y la fila "Total (únicas)" usaba `len(_filtered)` — contaba filas,
no materias distintas, mintiendo el propio rótulo.

Los helpers se extrajeron como funciones puras justamente para poder
fijar esta aritmética sin instanciar Streamlit ni la base de datos.
"""

from __future__ import annotations

from src.ui.validation_ui import (
    _contar_por_carrera,
    _contar_totales_unicos,
)


def _fila(codigo: str, estado: str, carreras: set[str]) -> dict:
    return {"codigo": codigo, "estado": estado, "carreras_set": carreras}


class TestContarPorCarrera:
    def test_materia_comun_cuenta_una_vez_por_carrera(self):
        """M1 es común a A y B (2 filas, una por ubicación). Antes:
        A=2 y B=2. Correcto: A=1 y B=1.
        """
        filtered = [
            _fila("M1", "OK", {"A", "B"}),   # ubicación en A
            _fila("M1", "OK", {"A", "B"}),   # ubicación en B
        ]
        counts = _contar_por_carrera(filtered)
        assert sum(counts["A"].values()) == 1
        assert sum(counts["B"].values()) == 1

    def test_mezcla_comun_y_exclusiva(self):
        """A tiene {M1 común, M2 exclusiva} = 2 materias; B tiene
        {M1} = 1. Antes la tabla decía A=3, B=2.
        """
        filtered = [
            _fila("M1", "OK", {"A", "B"}),
            _fila("M1", "OK", {"A", "B"}),
            _fila("M2", "Revisión", {"A"}),
        ]
        counts = _contar_por_carrera(filtered)
        assert sum(counts["A"].values()) == 2
        assert counts["A"]["OK"] == 1
        assert counts["A"]["Revisión"] == 1
        assert sum(counts["B"].values()) == 1

    def test_materia_sin_carreras_no_aparece(self):
        """Materias sin `PlanEstudioDB` (carreras_set vacío) no entran
        en ninguna fila de carrera — sí en el total de únicas.
        """
        filtered = [_fila("M9", "No esperada", set())]
        assert _contar_por_carrera(filtered) == {}

    def test_todos_los_estados_estan_en_el_bucket(self):
        filtered = [_fila("M1", "Conflictiva", {"A"})]
        counts = _contar_por_carrera(filtered)
        assert counts["A"]["Conflictiva"] == 1
        # Bucket completo, con ceros.
        assert set(counts["A"].keys()) == {
            "OK", "Faltante", "No esperada",
            "Conflictiva", "Sin datos", "Revisión",
        }


class TestContarTotalesUnicos:
    def test_cuenta_codigos_unicos_no_filas(self):
        """El rótulo "(únicas)" ahora es verdad: M1 con 2 ubicaciones
        cuenta 1. Antes `len(_filtered)` daba 3.
        """
        filtered = [
            _fila("M1", "OK", {"A", "B"}),
            _fila("M1", "OK", {"A", "B"}),
            _fila("M2", "Faltante", {"A"}),
        ]
        tot = _contar_totales_unicos(filtered)
        assert tot["total"] == 2
        assert tot["ok"] == 1
        assert tot["faltantes"] == 1
        assert tot["no_esperadas"] == 0
        assert tot["revision"] == 0

    def test_revision_agrupa_conflictiva_sin_datos_y_revision(self):
        filtered = [
            _fila("M1", "Conflictiva", {"A"}),
            _fila("M2", "Sin datos", {"A"}),
            _fila("M3", "Revisión", {"A"}),
        ]
        tot = _contar_totales_unicos(filtered)
        assert tot["revision"] == 3
        assert tot["total"] == 3

    def test_consistencia_con_metrica_mostrando(self):
        """`total` debe coincidir con la métrica "Mostrando"
        (`len({codigos})`) — antes divergían en la misma pantalla.
        """
        filtered = [
            _fila("M1", "OK", {"A", "B"}),
            _fila("M1", "OK", {"A", "B"}),
        ]
        tot = _contar_totales_unicos(filtered)
        assert tot["total"] == len({r["codigo"] for r in filtered})
