"""Tests para src.services.resolucion_jerarquica.

Valida que se cumpla la regla "nivel más específico manda" para todos
los atributos jerárquicos del sistema.
"""

import pytest

from src.services.resolucion_jerarquica import (
    resolve_dicta_recursado,
    resolve_virtual,
)


class TestResolveVirtual:
    """Regla: HorarioDB.virtual > DictadoDB.virtual > MateriaDB.virtual."""

    def test_solo_materia_virtual_true(self):
        # Sin overrides en dictado ni horario → hereda de materia.
        assert resolve_virtual(None, None, True) is True

    def test_solo_materia_virtual_false(self):
        assert resolve_virtual(None, None, False) is False

    def test_dictado_override_true_sobre_materia_false(self):
        # Materia presencial pero dictado marcado virtual → virtual.
        assert resolve_virtual(None, True, False) is True

    def test_dictado_override_false_sobre_materia_true(self):
        # Materia virtual pero dictado forzado presencial → presencial.
        assert resolve_virtual(None, False, True) is False

    def test_horario_override_true_sobre_dictado_false(self):
        # Un horario específico virtual dentro de un dictado presencial.
        assert resolve_virtual(True, False, False) is True

    def test_horario_override_false_sobre_todo(self):
        # Todo hacia arriba dice virtual, pero este horario específico
        # es presencial.
        assert resolve_virtual(False, True, True) is False

    def test_horario_none_dictado_none_hereda_de_materia(self):
        # Cadena sin overrides → cascada completa hasta la raíz.
        assert resolve_virtual(None, None, False) is False
        assert resolve_virtual(None, None, True) is True


class TestResolveDictaRecursado:
    """Regla: MateriaDB.dicta_recursado > CarreraDB.dicta_recursado."""

    def test_materia_none_hereda_carrera_true(self):
        assert resolve_dicta_recursado(None, True) is True

    def test_materia_none_hereda_carrera_false(self):
        assert resolve_dicta_recursado(None, False) is False

    def test_materia_true_sobre_carrera_false(self):
        # Carrera no dicta recursado pero esta materia sí.
        assert resolve_dicta_recursado(True, False) is True

    def test_materia_false_sobre_carrera_true(self):
        # Carrera dicta recursado pero esta materia no.
        assert resolve_dicta_recursado(False, True) is False


class TestPropiedadesGenerales:
    """Propiedades que se cumplen para toda cadena de resolución
    jerárquica."""

    @pytest.mark.parametrize("materia", [True, False])
    def test_null_null_null_hereda_de_materia(self, materia):
        # Cuando todos los niveles específicos son None, el resultado
        # es el valor de la raíz.
        assert resolve_virtual(None, None, materia) is materia

    @pytest.mark.parametrize("valor", [True, False])
    def test_valor_en_horario_gana_siempre(self, valor):
        # HorarioDB.virtual concreto siempre gana, sin importar los
        # niveles superiores.
        for d in (None, True, False):
            for m in (True, False):
                assert resolve_virtual(valor, d, m) is valor

    @pytest.mark.parametrize("valor", [True, False])
    def test_valor_en_dictado_gana_sobre_materia(self, valor):
        # DictadoDB.virtual concreto gana sobre MateriaDB.virtual
        # cuando no hay override en horario.
        for m in (True, False):
            assert resolve_virtual(None, valor, m) is valor
