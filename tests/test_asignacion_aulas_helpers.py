"""Tests para asignacion_aulas_helpers (funciones puras)."""

from datetime import time

from src.services.asignacion_aulas_helpers import (
    AulaSlot,
    HorarioSlot,
    compute_compat,
    compute_simultaneidad_groups,
    diagnose_infeasibility,
    validar_particion_factible,
)


# Helpers para construir slots con menos boilerplate.
def _h(hid: str, dia: str, hi: int, hf: int, materia="MAT", tipo=None):
    return HorarioSlot(
        id=hid, dia=dia, hora_inicio=time(hi, 0), hora_fin=time(hf, 0),
        materia_codigo=materia, tipo_clase=tipo,
    )


def _a(aid: str, tipo: str = "teorica", cap: int = 30):
    return AulaSlot(id=aid, tipo=tipo, capacidad=cap)


class TestSimultaneidadGroups:

    def test_sin_solapamiento_ningun_grupo(self):
        # 3 horarios consecutivos en distintas franjas → ningún grupo.
        hs = [
            _h("h1", "Lunes", 8, 10),
            _h("h2", "Lunes", 10, 12),
            _h("h3", "Lunes", 14, 16),
        ]
        grupos = compute_simultaneidad_groups(hs)
        assert grupos == []

    def test_dos_clases_simultaneas(self):
        hs = [
            _h("h1", "Lunes", 8, 10),
            _h("h2", "Lunes", 8, 10),
        ]
        grupos = compute_simultaneidad_groups(hs)
        assert len(grupos) == 1
        assert grupos[0] == {"h1", "h2"}

    def test_tres_clases_simultaneas(self):
        hs = [
            _h("h1", "Lunes", 8, 12),
            _h("h2", "Lunes", 9, 11),
            _h("h3", "Lunes", 10, 12),
        ]
        # En el instante 10-11 las 3 están activas → grupo maximal {h1,h2,h3}.
        grupos = compute_simultaneidad_groups(hs)
        assert len(grupos) == 1
        assert grupos[0] == {"h1", "h2", "h3"}

    def test_dos_grupos_distintos(self):
        hs = [
            # Grupo Lunes 8-10
            _h("h1", "Lunes", 8, 10),
            _h("h2", "Lunes", 8, 10),
            # Grupo Martes 8-10
            _h("h3", "Martes", 8, 10),
            _h("h4", "Martes", 8, 10),
        ]
        grupos = compute_simultaneidad_groups(hs)
        assert len(grupos) == 2
        sets = [frozenset(g) for g in grupos]
        assert frozenset({"h1", "h2"}) in sets
        assert frozenset({"h3", "h4"}) in sets

    def test_clase_que_termina_donde_empieza_otra_NO_solapa(self):
        # h1 termina a las 10, h2 empieza a las 10 → no se solapan.
        hs = [
            _h("h1", "Lunes", 8, 10),
            _h("h2", "Lunes", 10, 12),
        ]
        grupos = compute_simultaneidad_groups(hs)
        assert grupos == []

    def test_grupos_solapados_emiten_solo_maximal(self):
        # h1: 8-12, h2: 9-11, h3: 13-15
        # Solo {h1, h2} es grupo (maximal); h3 está en otra franja.
        hs = [
            _h("h1", "Lunes", 8, 12),
            _h("h2", "Lunes", 9, 11),
            _h("h3", "Lunes", 13, 15),
        ]
        grupos = compute_simultaneidad_groups(hs)
        assert len(grupos) == 1
        assert grupos[0] == {"h1", "h2"}


class TestCompat:

    def test_teorica_va_a_aula_teorica(self):
        h = _h("h1", "Lunes", 8, 10, tipo="teorica")
        a_teo = _a("a1", tipo="teorica")
        a_lab = _a("a2", tipo="laboratorio")
        assert compute_compat(h, a_teo, set()) is True
        assert compute_compat(h, a_lab, set()) is False

    def test_teorica_va_a_anfiteatro(self):
        h = _h("h1", "Lunes", 8, 10, tipo="teorica")
        a_anfi = _a("a3", tipo="anfiteatro")
        assert compute_compat(h, a_anfi, set()) is True

    def test_laboratorio_solo_aulas_compatibles(self):
        h = _h("h1", "Lunes", 8, 10, tipo="laboratorio")
        a_lab_ok = _a("a1", tipo="laboratorio")
        a_lab_no = _a("a2", tipo="laboratorio")
        a_teo = _a("a3", tipo="teorica")
        # Sólo a1 está en la lista de labs compatibles para la materia.
        compat_set = {"a1"}
        assert compute_compat(h, a_lab_ok, compat_set) is True
        assert compute_compat(h, a_lab_no, compat_set) is False
        assert compute_compat(h, a_teo, compat_set) is False

    def test_tipo_None_acepta_todas(self):
        # Sin tipo fijado, R3 deja todas las aulas en el dominio (la
        # decisión final la hace t[h] junto con R6, no R3).
        h = _h("h1", "Lunes", 8, 10, tipo=None)
        a_teo = _a("a1", tipo="teorica")
        a_lab = _a("a2", tipo="laboratorio")
        assert compute_compat(h, a_teo, set()) is True
        assert compute_compat(h, a_lab, {"a2"}) is True


class TestDiagnoseInfeasibility:

    def test_no_infactibilidad_caso_normal(self):
        hs = [_h("h1", "Lunes", 8, 10, tipo="teorica")]
        aulas = [_a("a1", tipo="teorica", cap=30)]
        diag = diagnose_infeasibility(hs, aulas, {}, [])
        assert diag.is_infeasible() is False

    def test_lab_sin_aulas_compatibles(self):
        # Horario lab pero MateriaLaboratorioDB vacío para la materia.
        hs = [_h("h1", "Lunes", 8, 10, materia="QUI", tipo="laboratorio")]
        aulas = [_a("a1", tipo="laboratorio", cap=30)]
        diag = diagnose_infeasibility(hs, aulas, {}, [])
        assert diag.is_infeasible() is True
        assert len(diag.horarios_sin_aula_compatible) == 1
        item = diag.horarios_sin_aula_compatible[0]
        assert item["materia_codigo"] == "QUI"
        assert "MateriaLaboratorioDB" in item["razon"]

    def test_teorica_sin_aulas_teoricas(self):
        hs = [_h("h1", "Lunes", 8, 10, tipo="teorica")]
        aulas = [_a("a1", tipo="laboratorio", cap=30)]
        diag = diagnose_infeasibility(hs, aulas, {}, [])
        assert diag.is_infeasible() is True
        assert "teóricas" in diag.horarios_sin_aula_compatible[0]["razon"]

    def test_franja_saturada_pigeonhole(self):
        # 3 clases solapadas, sólo 2 aulas → infactible por R4.
        hs = [
            _h("h1", "Lunes", 8, 10, tipo="teorica"),
            _h("h2", "Lunes", 8, 10, tipo="teorica"),
            _h("h3", "Lunes", 8, 10, tipo="teorica"),
        ]
        aulas = [_a("a1", tipo="teorica"), _a("a2", tipo="teorica")]
        sim = compute_simultaneidad_groups(hs)
        diag = diagnose_infeasibility(hs, aulas, {}, sim)
        assert diag.is_infeasible() is True
        assert len(diag.franjas_saturadas) == 1
        assert diag.franjas_saturadas[0]["n_clases"] == 3
        assert diag.franjas_saturadas[0]["n_aulas_compatibles"] == 2

    def test_franja_no_saturada_si_alcanzan(self):
        hs = [
            _h("h1", "Lunes", 8, 10, tipo="teorica"),
            _h("h2", "Lunes", 8, 10, tipo="teorica"),
        ]
        aulas = [_a("a1", tipo="teorica"), _a("a2", tipo="teorica")]
        sim = compute_simultaneidad_groups(hs)
        diag = diagnose_infeasibility(hs, aulas, {}, sim)
        assert diag.is_infeasible() is False

    def test_messages_son_legibles(self):
        hs = [_h("h1", "Lunes", 8, 10, materia="QUI", tipo="laboratorio")]
        aulas = [_a("a1", tipo="laboratorio")]
        diag = diagnose_infeasibility(hs, aulas, {}, [])
        msgs = diag.to_messages()
        assert len(msgs) == 1
        assert "QUI" in msgs[0]
        assert "Lunes" in msgs[0]


class TestValidarParticion:

    def test_particion_factible_sin_tipo_fijado(self):
        # Materia con hteo=2, hlab=2; dos horarios de 2h sin tipo fijado.
        problemas = validar_particion_factible(
            horarios_por_comision={
                "k1": [("h1", 2.0, None), ("h2", 2.0, None)],
            },
            hteo={"M": 2.0},
            hlab={"M": 2.0},
            materia_de_comision={"k1": "M"},
        )
        assert problemas == []

    def test_particion_infactible_subset_sum(self):
        # hteo=3, hlab=1; horarios de 2h cada uno. No hay subset que
        # sume 1h.
        problemas = validar_particion_factible(
            horarios_por_comision={
                "k1": [("h1", 2.0, None), ("h2", 2.0, None)],
            },
            hteo={"M": 3.0},
            hlab={"M": 1.0},
            materia_de_comision={"k1": "M"},
        )
        # Ojo: la suma total (4h) NO iguala hteo+hlab (4h sí cuadra
        # en este caso). El problema es subset-sum: no puedo llegar
        # a 1h con piezas de 2h.
        assert len(problemas) == 1
        assert "combinación" in problemas[0]["razon"]

    def test_particion_factible_con_tipo_fijado(self):
        # 3 horarios; uno fijo lab, dos libres; hteo=4, hlab=2.
        problemas = validar_particion_factible(
            horarios_por_comision={
                "k1": [
                    ("h1", 2.0, "laboratorio"),
                    ("h2", 2.0, None),
                    ("h3", 2.0, None),
                ],
            },
            hteo={"M": 4.0},
            hlab={"M": 2.0},
            materia_de_comision={"k1": "M"},
        )
        assert problemas == []

    def test_suma_total_no_coincide(self):
        # hteo+hlab = 4 pero horarios suman 5.
        problemas = validar_particion_factible(
            horarios_por_comision={
                "k1": [("h1", 3.0, None), ("h2", 2.0, None)],
            },
            hteo={"M": 2.0},
            hlab={"M": 2.0},
            materia_de_comision={"k1": "M"},
        )
        assert len(problemas) == 1
        assert "no coincide" in problemas[0]["razon"]

    def test_lab_fijado_excede(self):
        # Fijado 4h de lab pero la materia sólo tiene hlab=2 (y hteo=2,
        # así que la suma total cuadra y entra al check de exceso).
        problemas = validar_particion_factible(
            horarios_por_comision={
                "k1": [
                    ("h1", 2.0, "laboratorio"),
                    ("h2", 2.0, "laboratorio"),
                ],
            },
            hteo={"M": 2.0},
            hlab={"M": 2.0},
            materia_de_comision={"k1": "M"},
        )
        assert len(problemas) == 1
        assert "fijadas como laboratorio" in problemas[0]["razon"]
