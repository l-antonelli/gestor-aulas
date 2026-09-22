"""Tests unitarios de `_estado_de_materia` (fase F del rediseño
2026-09-21). Cover: la matriz de flags que decide qué badge mostrar
en la tabla "Detalle por materia" del panel Validar.

Estado extendido con "Revisión" — antes los warnings del editor
por-materia (h/sem × comisiones no divisible, distribución
desequilibrada, mismatch h/sem × comisiones ≠ total) no gatillaban
nada en el badge externo, generando drift entre la máquina interna y
el resumen agregado. Ahora `_estado_de_materia` los mapea a
"Revisión" cuando la materia no cae en un estado peor (Faltante, No
esperada, Conflictiva, Sin datos).
"""

from __future__ import annotations

from src.ui.validation_ui import _estado_de_materia


class TestPrioridadDeEstados:
    """Orden de precedencia: Faltante > No esperada > Conflictiva >
    Sin datos > Revisión > OK.
    """

    def test_ok_por_default(self):
        assert _estado_de_materia({}) == "OK"

    def test_faltante_gana_a_todo(self):
        data = {
            "es_faltante": True,
            "es_no_esperada": True,
            "tiene_conflicto": True,
            "falta_horas": True,
            "mismatch_hsem_com": True,
        }
        assert _estado_de_materia(data) == "Faltante"

    def test_no_esperada_gana_a_conflictiva(self):
        assert _estado_de_materia({
            "es_no_esperada": True, "tiene_conflicto": True,
        }) == "No esperada"

    def test_conflictiva_gana_a_sin_datos(self):
        assert _estado_de_materia({
            "tiene_conflicto": True, "falta_horas": True,
        }) == "Conflictiva"

    def test_sin_datos_gana_a_revision(self):
        assert _estado_de_materia({
            "falta_horas": True, "mismatch_hsem_com": True,
        }) == "Sin datos"


class TestEstadoRevision:
    """El nuevo estado "Revisión" se activa por cualquiera de los 3
    flags del editor por-materia — pero sólo si la materia no cayó en
    un estado peor.
    """

    def test_mismatch_hsem_com(self):
        assert _estado_de_materia({"mismatch_hsem_com": True}) == "Revisión"

    def test_no_divisible(self):
        assert _estado_de_materia({"no_divisible": True}) == "Revisión"

    def test_desequilibrado(self):
        assert _estado_de_materia({"desequilibrado": True}) == "Revisión"

    def test_combinacion_de_flags(self):
        assert _estado_de_materia({
            "mismatch_hsem_com": True,
            "no_divisible": True,
            "desequilibrado": True,
        }) == "Revisión"

    def test_flag_falsy_no_dispara(self):
        assert _estado_de_materia({
            "mismatch_hsem_com": False,
            "no_divisible": False,
            "desequilibrado": False,
        }) == "OK"
