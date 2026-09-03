"""Tests para los filtros del panel de Gestión de Asignaciones
(``aula_cronograma_view``).

Cubre el bug del filtro combinado carrera+año+cuatri: antes cada
dimensión filtraba con intersección independiente y una materia con
ubicaciones (A,1,1C), (E,2,1C), (M,5,1C) pasaba el filtro
(carrera=A, año=5, cuatri=1C) porque cada dimensión coincidía por su
cuenta, aunque la tupla exacta no existiera. Ahora se filtra por
tupla completa.
"""

from src.ui.aula_cronograma_view import _aplicar_filtros_horarios_v2


def _mk_row(
    materia_codigo: str,
    ubicaciones: set[tuple[str, int | None, str | None]],
    aula_id: str | None = "a1",
    tipo_clase: str | None = "teorica",
    dia: str = "Lunes",
    es_virtual: bool = False,
) -> dict:
    """Construye una row con la forma que produce ``_build_rows_por_horario``."""
    carreras_codigos = {u[0] for u in ubicaciones}
    anios = {u[1] for u in ubicaciones if u[1] is not None}
    cuatris = {u[2] for u in ubicaciones if u[2] is not None}
    return {
        "horario_id": f"h_{materia_codigo}",
        "dia": dia,
        "materia_codigo": materia_codigo,
        "materia_nombre": materia_codigo,
        "tipo_clase": tipo_clase,
        "aula_id": aula_id,
        "aula_obj": None,
        "es_virtual": es_virtual,
        "carreras_codigos": carreras_codigos,
        "carreras_nombres": [],
        "anios": anios,
        "cuatris": cuatris,
        "ubicaciones": ubicaciones,
        "label": "—",
    }


class TestFiltroCombinadoEstricto:

    def test_f14_no_aparece_en_electronica_5_1c(self):
        """Regression del bug reportado: F14 tiene ubicaciones
        (A,1,1C), (E,2,1C), (M,5,1C). Al filtrar Electrónica (A) 5º
        1C, no debe aparecer porque la tupla (A,5,1C) no existe —
        aunque A, 5 y 1C existan por separado."""
        rows = [_mk_row("F14", {("A", 1, "1C"), ("E", 2, "1C"), ("M", 5, "1C")})]
        filtros = {"carreras": ["A"], "anios": [5], "cuatris": ["1C"]}
        out = _aplicar_filtros_horarios_v2(rows, filtros, sede_map={})
        assert out == []

    def test_materia_con_tupla_exacta_pasa(self):
        """Sanity: si la tupla exacta existe, la materia pasa."""
        rows = [_mk_row("A20", {("A", 5, "1C")})]
        filtros = {"carreras": ["A"], "anios": [5], "cuatris": ["1C"]}
        out = _aplicar_filtros_horarios_v2(rows, filtros, sede_map={})
        assert len(out) == 1
        assert out[0]["materia_codigo"] == "A20"

    def test_dimension_vacia_es_wildcard(self):
        """Si el usuario deja una dimensión sin filtrar, cualquier valor
        de esa dimensión es válido siempre que las otras coincidan."""
        # F14 en (A,1,1C): con carrera=A y cuatri=1C, sin filtrar año,
        # debería aparecer.
        rows = [_mk_row("F14", {("A", 1, "1C"), ("E", 2, "1C"), ("M", 5, "1C")})]
        filtros = {"carreras": ["A"], "anios": [], "cuatris": ["1C"]}
        out = _aplicar_filtros_horarios_v2(rows, filtros, sede_map={})
        assert len(out) == 1

    def test_solo_carrera_filtrada(self):
        """Filtrar sólo por carrera: pasa si la materia está en esa
        carrera en cualquier año/cuatri."""
        rows = [
            _mk_row("F14", {("A", 1, "1C")}),
            _mk_row("F17", {("E", 5, "1C")}),
        ]
        filtros = {"carreras": ["A"], "anios": [], "cuatris": []}
        out = _aplicar_filtros_horarios_v2(rows, filtros, sede_map={})
        codes = {r["materia_codigo"] for r in out}
        assert codes == {"F14"}

    def test_sin_filtros_pasan_todos(self):
        rows = [
            _mk_row("A", {("A", 1, "1C")}),
            _mk_row("B", {("E", 2, "2C")}),
        ]
        filtros: dict = {}
        out = _aplicar_filtros_horarios_v2(rows, filtros, sede_map={})
        assert len(out) == 2

    def test_multiseleccion_carreras(self):
        """Con carreras=[A, E], una materia sólo en M no pasa."""
        rows = [
            _mk_row("F14", {("A", 1, "1C"), ("E", 2, "1C"), ("M", 5, "1C")}),
            _mk_row("SOLO_M", {("M", 5, "1C")}),
        ]
        filtros = {"carreras": ["A", "E"], "anios": [], "cuatris": []}
        out = _aplicar_filtros_horarios_v2(rows, filtros, sede_map={})
        codes = {r["materia_codigo"] for r in out}
        assert codes == {"F14"}

    def test_materia_sin_ubicaciones_no_pasa_si_hay_filtro(self):
        """Materia sin filas en PlanEstudioDB (ubicaciones vacías) no
        pasa un filtro estricto."""
        rows = [_mk_row("HUERFANA", set())]
        filtros = {"carreras": ["A"], "anios": [], "cuatris": []}
        out = _aplicar_filtros_horarios_v2(rows, filtros, sede_map={})
        assert out == []

    def test_otros_filtros_siguen_funcionando(self):
        """Sanity: los filtros no relacionados (aula, tipo, dia,
        excluir_virtuales) siguen aplicándose como siempre."""
        rows = [
            _mk_row("A20", {("A", 5, "1C")}, tipo_clase="teorica", dia="Lunes"),
            _mk_row("A21", {("A", 5, "1C")}, tipo_clase="laboratorio", dia="Martes"),
        ]
        # Filtrar sólo teoría.
        filtros = {"tipos": ["teorica"], "carreras": [], "anios": [], "cuatris": []}
        out = _aplicar_filtros_horarios_v2(rows, filtros, sede_map={})
        assert [r["materia_codigo"] for r in out] == ["A20"]
