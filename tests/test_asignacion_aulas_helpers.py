"""Tests para asignacion_aulas_helpers (funciones puras)."""

from datetime import time

from src.services.asignacion_aulas_helpers import (
    AulaSlot,
    HorarioSlot,
    compute_compat,
    compute_heatmap_demanda_oferta,
    compute_heatmap_por_sede,
    compute_heatmap_total_sin_sede,
    compute_impacto_r10,
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


class TestSaturacionPorTipo:
    """Cota refinada de pigeonhole: por tipo de aula."""

    def test_saturacion_teoricas_estrictas(self):
        """5 horarios teóricos simultáneos, sólo 4 aulas teóricas → falla."""
        hs = [
            _h(f"h{i}", "Lunes", 8, 10, materia=f"M{i}", tipo="teorica")
            for i in range(5)
        ]
        aulas = [_a(f"a{i}", tipo="teorica") for i in range(4)]
        # No labs, no anfiteatros.
        sim = [{f"h{i}" for i in range(5)}]
        diag = diagnose_infeasibility(hs, aulas, {}, sim)
        assert len(diag.saturacion_por_tipo) == 1
        item = diag.saturacion_por_tipo[0]
        assert item["tipo"] == "teórica"
        assert item["n_necesarias"] == 5
        assert item["n_disponibles"] == 4

    def test_anfiteatro_cuenta_como_teorica(self):
        """3 teóricas, 2 aulas teóricas + 1 anfiteatro: alcanzan."""
        hs = [
            _h("h1", "Lunes", 8, 10, materia="A", tipo="teorica"),
            _h("h2", "Lunes", 8, 10, materia="B", tipo="teorica"),
            _h("h3", "Lunes", 8, 10, materia="C", tipo="teorica"),
        ]
        aulas = [
            _a("t1", tipo="teorica"),
            _a("t2", tipo="teorica"),
            _a("anf", tipo="anfiteatro"),
        ]
        sim = [{"h1", "h2", "h3"}]
        diag = diagnose_infeasibility(hs, aulas, {}, sim)
        assert diag.saturacion_por_tipo == []

    def test_none_optimista_no_cuenta_a_teorica_si_hay_lab(self):
        """horario tipo_clase=None pero la materia tiene lab compatible:
        NO debe contarse contra el pool teórico (el LP la mandará a lab).
        """
        hs = [
            _h("h1", "Lunes", 8, 10, materia="A", tipo="teorica"),
            _h("h2", "Lunes", 8, 10, materia="B", tipo="teorica"),
            _h("h3", "Lunes", 8, 10, materia="LAB", tipo=None),
        ]
        aulas = [
            _a("t1", tipo="teorica"),
            _a("t2", tipo="teorica"),  # 2 teóricas
            _a("L", tipo="laboratorio"),  # 1 lab para materia LAB
        ]
        materia_lab_map = {"LAB": {"L"}}
        sim = [{"h1", "h2", "h3"}]
        diag = diagnose_infeasibility(hs, aulas, materia_lab_map, sim)
        # 2 teóricas estrictas vs 2 disponibles → no satura.
        # h3 puede ir al lab → no se cuenta como teórica.
        assert diag.saturacion_por_tipo == []

    def test_none_se_fuerza_teorica_si_no_hay_lab(self):
        """Sin lab para la materia, una clase None DEBE ir a teórica
        (R6) y entonces sí cuenta contra el pool teórico."""
        hs = [
            _h("h1", "Lunes", 8, 10, materia="A", tipo="teorica"),
            _h("h2", "Lunes", 8, 10, materia="B", tipo="teorica"),
            _h("h3", "Lunes", 8, 10, materia="C", tipo=None),
        ]
        aulas = [
            _a("t1", tipo="teorica"),
            _a("t2", tipo="teorica"),
        ]
        # C no tiene labs → forzosamente teórica.
        sim = [{"h1", "h2", "h3"}]
        diag = diagnose_infeasibility(hs, aulas, {}, sim)
        # 3 teóricas forzadas vs 2 disponibles → satura.
        assert len(diag.saturacion_por_tipo) == 1
        assert diag.saturacion_por_tipo[0]["tipo"] == "teórica"
        assert diag.saturacion_por_tipo[0]["n_necesarias"] == 3

    def test_saturacion_lab_por_materia(self):
        """Materia QUI tiene 3 horarios de lab simultáneos pero sólo
        1 lab compatible → falla."""
        hs = [
            _h("h1", "Lunes", 8, 10, materia="QUI", tipo="laboratorio"),
            _h("h2", "Lunes", 8, 10, materia="QUI", tipo="laboratorio"),
            _h("h3", "Lunes", 8, 10, materia="QUI", tipo="laboratorio"),
        ]
        aulas = [_a("L", tipo="laboratorio")]
        materia_lab_map = {"QUI": {"L"}}
        sim = [{"h1", "h2", "h3"}]
        diag = diagnose_infeasibility(hs, aulas, materia_lab_map, sim)
        items_lab = [
            i for i in diag.saturacion_por_tipo if i["tipo"] == "laboratorio"
        ]
        assert len(items_lab) == 1
        assert items_lab[0]["materia"] == "QUI"
        assert items_lab[0]["n_necesarias"] == 3
        assert items_lab[0]["n_disponibles"] == 1

    def test_saturacion_lab_separa_por_materia(self):
        """Dos materias distintas con labs diferentes: una sí satura,
        la otra no."""
        hs = [
            _h("h1", "Lunes", 8, 10, materia="QUI", tipo="laboratorio"),
            _h("h2", "Lunes", 8, 10, materia="QUI", tipo="laboratorio"),
            _h("h3", "Lunes", 8, 10, materia="FIS", tipo="laboratorio"),
        ]
        aulas = [_a("LQ", tipo="laboratorio"), _a("LF", tipo="laboratorio")]
        materia_lab_map = {"QUI": {"LQ"}, "FIS": {"LF"}}
        sim = [{"h1", "h2", "h3"}]
        diag = diagnose_infeasibility(hs, aulas, materia_lab_map, sim)
        # QUI: 2 horarios vs 1 lab → satura. FIS: 1 horario vs 1 lab → ok.
        items_lab = [
            i for i in diag.saturacion_por_tipo if i["tipo"] == "laboratorio"
        ]
        assert len(items_lab) == 1
        assert items_lab[0]["materia"] == "QUI"


class TestHallViolators:
    """Test del teorema de Hall (matching bipartito) por grupo."""

    def test_no_violation_caso_simple(self):
        """3 clases, 3 aulas, todas compatibles → matching trivial."""
        hs = [
            _h(f"h{i}", "Lunes", 8, 10, materia=f"M{i}", tipo="teorica")
            for i in range(3)
        ]
        aulas = [_a(f"a{i}", tipo="teorica") for i in range(3)]
        sim = [{"h0", "h1", "h2"}]
        diag = diagnose_infeasibility(hs, aulas, {}, sim)
        assert diag.hall_violators == []

    def test_pigeonhole_falla_y_hall_tambien(self):
        """3 horarios pero 2 aulas teóricas: ambos detectan."""
        hs = [
            _h(f"h{i}", "Lunes", 8, 10, materia=f"M{i}", tipo="teorica")
            for i in range(3)
        ]
        aulas = [_a("t1"), _a("t2")]
        sim = [{"h0", "h1", "h2"}]
        diag = diagnose_infeasibility(hs, aulas, {}, sim)
        assert diag.franjas_saturadas  # pigeonhole detecta
        assert diag.hall_violators  # hall también detecta
        v = diag.hall_violators[0]
        assert v["n_horarios"] >= 2
        assert v["n_aulas"] < v["n_horarios"]

    def test_hall_detecta_caso_que_pigeonhole_no(self):
        """Caso clásico: pigeonhole pasa pero Hall falla.

        h1 va a {a, b, c}. h2, h3 van solo a {a}. Pigeonhole sobre la
        unión total: 3 horarios, 3 aulas, |union|=3 ≥ 3 ✓.
        Pero el subconjunto {h2, h3} sólo conecta a {a}: Hall falla.
        Modelado: h1 = lab de M1 que admite a/b/c; h2, h3 = labs de
        M2 que sólo admite el lab `a`.
        """
        hs = [
            _h("h1", "Lunes", 8, 10, materia="M1", tipo="laboratorio"),
            _h("h2", "Lunes", 8, 10, materia="M2", tipo="laboratorio"),
            _h("h3", "Lunes", 8, 10, materia="M2", tipo="laboratorio"),
        ]
        aulas = [
            _a("a", tipo="laboratorio"),
            _a("b", tipo="laboratorio"),
            _a("c", tipo="laboratorio"),
        ]
        materia_lab_map = {
            "M1": {"a", "b", "c"},
            "M2": {"a"},
        }
        sim = [{"h1", "h2", "h3"}]
        diag = diagnose_infeasibility(hs, aulas, materia_lab_map, sim)
        # Pigeonhole pasa (3 ≥ 3).
        assert diag.franjas_saturadas == []
        # Hall detecta el subconjunto {h2,h3} con N(S)={a}.
        assert diag.hall_violators
        v = diag.hall_violators[0]
        assert v["n_horarios"] == 2
        assert v["n_aulas"] == 1
        assert "M2" in v["materias"]

    def test_grupo_grande_usa_matching_no_explota(self):
        """Sanity: con grupo de 12 horarios (>8) usa matching y no
        revienta. Caso factible."""
        hs = [
            _h(f"h{i}", "Lunes", 8, 10, materia=f"M{i}", tipo="teorica")
            for i in range(12)
        ]
        aulas = [_a(f"a{i}", tipo="teorica") for i in range(12)]
        sim = [{f"h{i}" for i in range(12)}]
        diag = diagnose_infeasibility(hs, aulas, {}, sim)
        assert diag.hall_violators == []  # matching perfecto


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


# =============================================================================
# Heatmap demanda vs oferta
# =============================================================================


def _build_compat_R3(
    horarios: list[HorarioSlot],
    aulas: list[AulaSlot],
    materia_lab_map: dict[str, set[str]] | None = None,
) -> dict[tuple[str, str], bool]:
    """Helper: arma compat usando solo R3 (sin R10)."""
    materia_lab_map = materia_lab_map or {}
    out: dict[tuple[str, str], bool] = {}
    for h in horarios:
        lab = materia_lab_map.get(h.materia_codigo, set())
        for a in aulas:
            out[(h.id, a.id)] = compute_compat(h, a, lab)
    return out


class TestHeatmapDemandaOferta:

    def test_celda_sin_demanda_es_cero(self):
        h = _h("h1", "Lunes", 8, 10, tipo="teorica")
        aulas = [_a("a1"), _a("a2")]
        compat = _build_compat_R3([h], aulas)
        out = compute_heatmap_demanda_oferta([h], aulas, compat)
        # Lunes 14:00-14:15 no debería tener demanda.
        slot_idx = out["slots"].index("14:00-14:15")
        dia_idx = out["dias"].index("Lunes")
        assert out["demanda"][slot_idx][dia_idx] == 0
        assert out["ratio"][slot_idx][dia_idx] == 0.0

    def test_demanda_uno_oferta_dos_ratio_05(self):
        h = _h("h1", "Lunes", 8, 10, tipo="teorica")
        aulas = [_a("a1"), _a("a2")]
        compat = _build_compat_R3([h], aulas)
        out = compute_heatmap_demanda_oferta([h], aulas, compat)
        slot_idx = out["slots"].index("08:00-08:15")
        dia_idx = out["dias"].index("Lunes")
        assert out["demanda"][slot_idx][dia_idx] == 1
        assert out["oferta"][slot_idx][dia_idx] == 2
        assert out["ratio"][slot_idx][dia_idx] == 0.5

    def test_saturacion_3_horarios_2_aulas(self):
        h1 = _h("h1", "Lunes", 8, 10, tipo="teorica")
        h2 = _h("h2", "Lunes", 8, 10, materia="OTRA", tipo="teorica")
        h3 = _h("h3", "Lunes", 8, 10, materia="TERC", tipo="teorica")
        aulas = [_a("a1"), _a("a2")]
        compat = _build_compat_R3([h1, h2, h3], aulas)
        out = compute_heatmap_demanda_oferta([h1, h2, h3], aulas, compat)
        slot_idx = out["slots"].index("08:00-08:15")
        dia_idx = out["dias"].index("Lunes")
        assert out["demanda"][slot_idx][dia_idx] == 3
        assert out["oferta"][slot_idx][dia_idx] == 2
        assert out["ratio"][slot_idx][dia_idx] == 1.5
        assert out["categoria"][slot_idx][dia_idx] == "teorica"

    def test_lab_se_cuenta_por_materia(self):
        # Dos labs simultáneos pero de materias distintas: cada uno
        # tiene su pool propio. Si cada pool tiene 1 aula y hay 1
        # demanda para cada materia, ratio = 1.0 (no saturado).
        h1 = _h("h1", "Lunes", 8, 10, materia="QUIM", tipo="laboratorio")
        h2 = _h("h2", "Lunes", 8, 10, materia="FIS", tipo="laboratorio")
        aulas = [_a("L1", tipo="laboratorio"), _a("L2", tipo="laboratorio")]
        materia_lab_map = {"QUIM": {"L1"}, "FIS": {"L2"}}
        compat = _build_compat_R3([h1, h2], aulas, materia_lab_map)
        out = compute_heatmap_demanda_oferta([h1, h2], aulas, compat)
        slot_idx = out["slots"].index("08:00-08:15")
        dia_idx = out["dias"].index("Lunes")
        # Peor caso: cualquiera de las dos categorías. Ratio = 1.0.
        assert out["ratio"][slot_idx][dia_idx] == 1.0
        assert out["demanda"][slot_idx][dia_idx] == 1
        assert out["oferta"][slot_idx][dia_idx] == 1

    def test_horarios_filtrados_recorta_demanda(self):
        h1 = _h("h1", "Lunes", 8, 10, tipo="teorica")
        h2 = _h("h2", "Lunes", 8, 10, materia="OTRA", tipo="teorica")
        aulas = [_a("a1"), _a("a2")]
        compat = _build_compat_R3([h1, h2], aulas)
        # Filtramos sólo h1: demanda baja a 1, oferta sigue siendo 2.
        out = compute_heatmap_demanda_oferta(
            [h1, h2], aulas, compat, horarios_filtrados=[h1],
        )
        slot_idx = out["slots"].index("08:00-08:15")
        dia_idx = out["dias"].index("Lunes")
        assert out["demanda"][slot_idx][dia_idx] == 1
        assert out["ratio"][slot_idx][dia_idx] == 0.5

    def test_detalle_incluye_materias_y_aulas(self):
        h1 = _h("h1", "Lunes", 8, 10, materia="MAT_A", tipo="teorica")
        h2 = _h("h2", "Lunes", 8, 10, materia="MAT_B", tipo="teorica")
        aulas = [_a("a1"), _a("a2")]
        compat = _build_compat_R3([h1, h2], aulas)
        out = compute_heatmap_demanda_oferta([h1, h2], aulas, compat)
        slot_idx = out["slots"].index("08:00-08:15")
        dia_idx = out["dias"].index("Lunes")
        det = out["detalle"][slot_idx][dia_idx]
        assert set(det["materias"]) == {"MAT_A", "MAT_B"}
        assert set(det["aulas_disponibles_ids"]) == {"a1", "a2"}


# =============================================================================
# Impacto de R10
# =============================================================================


class TestImpactoR10:

    def test_sin_r10_no_hay_excluidas(self):
        h1 = _h("h1", "Lunes", 8, 10, tipo="teorica")
        aulas = [_a("a1"), _a("a2")]
        compat = _build_compat_R3([h1], aulas)
        out = compute_impacto_r10([h1], aulas, {}, compat)
        assert len(out) == 1
        row = out[0]
        assert row["materia_codigo"] == "MAT"
        assert row["aulas_admisibles_pre_r10"] == 2
        assert row["aulas_admisibles_post_r10"] == 2
        assert row["aulas_excluidas_por_r10"] == 0

    def test_r10_excluye_aulas(self):
        h1 = _h("h1", "Lunes", 8, 10, tipo="teorica")
        aulas = [_a("a1"), _a("a2"), _a("a3")]
        # compat post-R10: solo a1 admite a h1.
        compat = {
            ("h1", "a1"): True,
            ("h1", "a2"): False,
            ("h1", "a3"): False,
        }
        out = compute_impacto_r10([h1], aulas, {}, compat)
        row = out[0]
        assert row["aulas_admisibles_pre_r10"] == 3
        assert row["aulas_admisibles_post_r10"] == 1
        assert row["aulas_excluidas_por_r10"] == 2
        assert set(row["ids_excluidas"]) == {"a2", "a3"}

    def test_orden_por_mayor_impacto(self):
        h1 = _h("h1", "Lunes", 8, 10, materia="MAT_A", tipo="teorica")
        h2 = _h("h2", "Lunes", 8, 10, materia="MAT_B", tipo="teorica")
        aulas = [_a("a1"), _a("a2"), _a("a3")]
        # MAT_B excluye más aulas que MAT_A.
        compat = {
            ("h1", "a1"): True,
            ("h1", "a2"): True,
            ("h1", "a3"): False,
            ("h2", "a1"): True,
            ("h2", "a2"): False,
            ("h2", "a3"): False,
        }
        out = compute_impacto_r10([h1, h2], aulas, {}, compat)
        # Primero MAT_B (excluye 2), después MAT_A (excluye 1).
        assert out[0]["materia_codigo"] == "MAT_B"
        assert out[0]["aulas_excluidas_por_r10"] == 2
        assert out[1]["materia_codigo"] == "MAT_A"
        assert out[1]["aulas_excluidas_por_r10"] == 1


# =============================================================================
# Heatmap por sede
# =============================================================================


class TestHeatmapPorSede:

    def _build_aulas_dos_sedes(self):
        """Sede S1: 2 aulas teóricas + 1 lab. Sede S2: 1 teórica + 1 lab."""
        return [
            AulaSlot(id="t1_S1", tipo="teorica", capacidad=30),
            AulaSlot(id="t2_S1", tipo="teorica", capacidad=30),
            AulaSlot(id="L_S1", tipo="laboratorio", capacidad=30),
            AulaSlot(id="t1_S2", tipo="teorica", capacidad=30),
            AulaSlot(id="L_S2", tipo="laboratorio", capacidad=30),
        ]

    def _aula_sede_id(self):
        return {
            "t1_S1": "S1", "t2_S1": "S1", "L_S1": "S1",
            "t1_S2": "S2", "L_S2": "S2",
        }

    def _sede_nombre(self):
        return {"S1": "Sede 1", "S2": "Sede 2"}

    def test_sede_sin_demanda_aparece_en_meta(self):
        # Un horario en S1 (sólo admite S1). S2 no recibe demanda.
        h = _h("h1", "Lunes", 8, 10, materia="M1", tipo="teorica")
        aulas = self._build_aulas_dos_sedes()
        out = compute_heatmap_por_sede(
            horarios=[h], aulas=aulas, materia_lab_map={},
            sedes_admisibles_por_materia={"M1": {"S1"}},
            aula_sede_id=self._aula_sede_id(),
            sede_nombre=self._sede_nombre(),
        )
        meta = {s["sede_id"]: s for s in out["sedes"]}
        assert meta["S1"]["tiene_demanda"] is True
        assert meta["S2"]["tiene_demanda"] is False
        assert meta["S1"]["n_aulas_teoricas"] == 2
        assert meta["S1"]["n_aulas_laboratorio"] == 1

    def test_demanda_teorica_en_sede_admisible(self):
        h1 = _h("h1", "Lunes", 8, 10, materia="M1", tipo="teorica")
        h2 = _h("h2", "Lunes", 8, 10, materia="M2", tipo="teorica")
        h3 = _h("h3", "Lunes", 8, 10, materia="M3", tipo="teorica")
        aulas = self._build_aulas_dos_sedes()
        out = compute_heatmap_por_sede(
            horarios=[h1, h2, h3], aulas=aulas, materia_lab_map={},
            sedes_admisibles_por_materia={
                "M1": {"S1"}, "M2": {"S1"}, "M3": {"S1"},
            },
            aula_sede_id=self._aula_sede_id(),
            sede_nombre=self._sede_nombre(),
        )
        # En S1 lunes 08:00-08:15, demanda teórica = 3 (h1, h2, h3),
        # oferta = 2 → ratio 1.5.
        slot_idx = out["slots"].index("08:00-08:15")
        dia_idx = out["dias"].index("Lunes")
        s1 = out["data"]["S1"]
        assert s1["teorica"]["demanda"][slot_idx][dia_idx] == 3
        assert s1["teorica"]["oferta"][slot_idx][dia_idx] == 2
        assert s1["teorica"]["ratio"][slot_idx][dia_idx] == 1.5
        # S2 no tiene demanda.
        s2 = out["data"]["S2"]
        assert s2["teorica"]["demanda"][slot_idx][dia_idx] == 0

    def test_lab_solo_cuenta_si_sede_tiene_lab_compatible(self):
        # M1 lab: lab compatible solo en S2.
        h = _h("h1", "Lunes", 8, 10, materia="M1", tipo="laboratorio")
        aulas = self._build_aulas_dos_sedes()
        out = compute_heatmap_por_sede(
            horarios=[h], aulas=aulas,
            materia_lab_map={"M1": {"L_S2"}},
            # M1 en teoría solo admite S1 según R10, pero el lab está
            # en S2: la sede S2 cuenta como admisible vía lab compatible.
            sedes_admisibles_por_materia={"M1": {"S1"}},
            aula_sede_id=self._aula_sede_id(),
            sede_nombre=self._sede_nombre(),
        )
        slot_idx = out["slots"].index("08:00-08:15")
        dia_idx = out["dias"].index("Lunes")
        # En S2 hay demanda de lab (1 horario, 1 aula → ratio 1).
        s2_lab = out["data"]["S2"]["laboratorio"]
        assert s2_lab["demanda"][slot_idx][dia_idx] == 1
        assert s2_lab["oferta"][slot_idx][dia_idx] == 1
        # En S1 la materia es admisible por R10 pero NO tiene lab
        # compatible con M1, así que no aparece como demanda de lab.
        s1_lab = out["data"]["S1"]["laboratorio"]
        assert s1_lab["demanda"][slot_idx][dia_idx] == 0

    def test_peor_caso_es_max_de_categorias(self):
        # En S1: 1 teórica con demanda 3/2=1.5 y 1 lab con demanda 1/1=1.
        # peor = 1.5.
        h_teo1 = _h("h1", "Lunes", 8, 10, materia="MT1", tipo="teorica")
        h_teo2 = _h("h2", "Lunes", 8, 10, materia="MT2", tipo="teorica")
        h_teo3 = _h("h3", "Lunes", 8, 10, materia="MT3", tipo="teorica")
        h_lab = _h("h4", "Lunes", 8, 10, materia="ML", tipo="laboratorio")
        aulas = self._build_aulas_dos_sedes()
        out = compute_heatmap_por_sede(
            horarios=[h_teo1, h_teo2, h_teo3, h_lab], aulas=aulas,
            materia_lab_map={"ML": {"L_S1"}},
            sedes_admisibles_por_materia={
                "MT1": {"S1"}, "MT2": {"S1"}, "MT3": {"S1"},
                "ML": {"S1"},
            },
            aula_sede_id=self._aula_sede_id(),
            sede_nombre=self._sede_nombre(),
        )
        slot_idx = out["slots"].index("08:00-08:15")
        dia_idx = out["dias"].index("Lunes")
        s1_peor = out["data"]["S1"]["peor"]
        assert s1_peor["ratio"][slot_idx][dia_idx] == 1.5

    def test_admisibles_none_significa_todas_las_sedes(self):
        # Sin restricción de sede: el horario aparece en todas las sedes.
        h = _h("h1", "Lunes", 8, 10, materia="M1", tipo="teorica")
        aulas = self._build_aulas_dos_sedes()
        out = compute_heatmap_por_sede(
            horarios=[h], aulas=aulas, materia_lab_map={},
            sedes_admisibles_por_materia={"M1": None},
            aula_sede_id=self._aula_sede_id(),
            sede_nombre=self._sede_nombre(),
        )
        slot_idx = out["slots"].index("08:00-08:15")
        dia_idx = out["dias"].index("Lunes")
        # Demanda = 1 en ambas sedes (fallback cuando no hay sede
        # preferida ni restricción — típicamente materias comunes sin
        # sede default configurada).
        assert out["data"]["S1"]["teorica"]["demanda"][slot_idx][dia_idx] == 1
        assert out["data"]["S2"]["teorica"]["demanda"][slot_idx][dia_idx] == 1

    def test_teorica_no_duplica_conteo_si_lab_esta_en_otra_sede(self):
        # Caso A5: materia cuya carrera vive en S1 pero cuyos labs
        # compatibles están físicamente en S2. La teórica debe contarse
        # UNA sola vez, en la sede del lab (S2). Antes del fix se
        # contaba en ambas.
        h_teo = _h("h1", "Lunes", 8, 10, materia="MLAB", tipo="teorica")
        aulas = self._build_aulas_dos_sedes()
        out = compute_heatmap_por_sede(
            horarios=[h_teo], aulas=aulas,
            materia_lab_map={"MLAB": {"L_S2"}},
            sedes_admisibles_por_materia={"MLAB": {"S1"}},
            aula_sede_id=self._aula_sede_id(),
            sede_nombre=self._sede_nombre(),
        )
        slot_idx = out["slots"].index("08:00-08:15")
        dia_idx = out["dias"].index("Lunes")
        s1_teo = out["data"]["S1"]["teorica"]["demanda"][slot_idx][dia_idx]
        s2_teo = out["data"]["S2"]["teorica"]["demanda"][slot_idx][dia_idx]
        # La teórica se contabiliza sólo en S2 (donde vive el lab):
        # coherente con "las teóricas deberían darse donde está el lab".
        assert s2_teo == 1
        assert s1_teo == 0

    def test_teorica_va_a_sede_de_carrera_cuando_no_hay_lab(self):
        # Sin labs compatibles: la sede preferida cae en el set de
        # sedes admisibles por carrera.
        h = _h("h1", "Lunes", 8, 10, materia="M1", tipo="teorica")
        aulas = self._build_aulas_dos_sedes()
        out = compute_heatmap_por_sede(
            horarios=[h], aulas=aulas, materia_lab_map={},
            sedes_admisibles_por_materia={"M1": {"S1"}},
            aula_sede_id=self._aula_sede_id(),
            sede_nombre=self._sede_nombre(),
        )
        slot_idx = out["slots"].index("08:00-08:15")
        dia_idx = out["dias"].index("Lunes")
        assert out["data"]["S1"]["teorica"]["demanda"][slot_idx][dia_idx] == 1
        assert out["data"]["S2"]["teorica"]["demanda"][slot_idx][dia_idx] == 0

    def test_lab_no_cambia_su_conteo_por_el_fix_de_teoricas(self):
        # Los labs se cuentan sólo en la sede donde vive el lab
        # compatible, con o sin fix. Nos aseguramos de no haber roto
        # ese conteo.
        h_lab = _h("h1", "Lunes", 8, 10, materia="MLAB", tipo="laboratorio")
        aulas = self._build_aulas_dos_sedes()
        out = compute_heatmap_por_sede(
            horarios=[h_lab], aulas=aulas,
            materia_lab_map={"MLAB": {"L_S2"}},
            sedes_admisibles_por_materia={"MLAB": {"S1"}},
            aula_sede_id=self._aula_sede_id(),
            sede_nombre=self._sede_nombre(),
        )
        slot_idx = out["slots"].index("08:00-08:15")
        dia_idx = out["dias"].index("Lunes")
        # El lab se cuenta sólo en la sede que tiene un aula
        # compatible (S2), como siempre.
        assert out["data"]["S2"]["laboratorio"]["demanda"][slot_idx][dia_idx] == 1
        assert out["data"]["S1"]["laboratorio"]["demanda"][slot_idx][dia_idx] == 0

    def test_materia_con_lab_en_misma_sede_que_carrera(self):
        # Caso feliz: la carrera y el lab conviven en la misma sede.
        # La teórica se cuenta ahí, como es de esperar.
        h_teo = _h("h1", "Lunes", 8, 10, materia="MOK", tipo="teorica")
        aulas = self._build_aulas_dos_sedes()
        out = compute_heatmap_por_sede(
            horarios=[h_teo], aulas=aulas,
            materia_lab_map={"MOK": {"L_S1"}},
            sedes_admisibles_por_materia={"MOK": {"S1"}},
            aula_sede_id=self._aula_sede_id(),
            sede_nombre=self._sede_nombre(),
        )
        slot_idx = out["slots"].index("08:00-08:15")
        dia_idx = out["dias"].index("Lunes")
        assert out["data"]["S1"]["teorica"]["demanda"][slot_idx][dia_idx] == 1
        assert out["data"]["S2"]["teorica"]["demanda"][slot_idx][dia_idx] == 0


class TestSedePreferidaParaHorario:
    """Tests para `sede_preferida_para_horario` (regla usada en el fix)."""

    def _setup(self):
        aula_sede_id = {
            "aula_S1": "S1", "aula_S2": "S2",
            "lab_S1": "S1", "lab_S2": "S2",
        }
        return aula_sede_id

    def test_sin_lab_devuelve_primera_sede_admisible(self):
        from src.services.asignacion_aulas_helpers import (
            sede_preferida_para_horario,
        )
        aula_sede_id = self._setup()
        sede = sede_preferida_para_horario(
            materia_codigo="M1",
            materia_lab_map={},
            sedes_admisibles_por_materia={"M1": {"S2", "S1"}},
            aula_sede_id=aula_sede_id,
        )
        # Determinístico por sede_id: S1 antes que S2.
        assert sede == "S1"

    def test_con_lab_en_una_sede_devuelve_esa(self):
        from src.services.asignacion_aulas_helpers import (
            sede_preferida_para_horario,
        )
        aula_sede_id = self._setup()
        sede = sede_preferida_para_horario(
            materia_codigo="MLAB",
            materia_lab_map={"MLAB": {"lab_S2"}},
            sedes_admisibles_por_materia={"MLAB": {"S1"}},  # carrera vive en S1
            aula_sede_id=aula_sede_id,
        )
        # Lab manda: prefiere S2 aunque la carrera esté en S1.
        assert sede == "S2"

    def test_lab_en_varias_sedes_prefiere_interseccion_con_carrera(self):
        from src.services.asignacion_aulas_helpers import (
            sede_preferida_para_horario,
        )
        aula_sede_id = self._setup()
        sede = sede_preferida_para_horario(
            materia_codigo="MLAB",
            materia_lab_map={"MLAB": {"lab_S1", "lab_S2"}},
            sedes_admisibles_por_materia={"MLAB": {"S2"}},
            aula_sede_id=aula_sede_id,
        )
        # Ambas sedes tienen lab; la carrera restringe a S2 → gana S2.
        assert sede == "S2"

    def test_lab_en_varias_sedes_sin_interseccion_orden_determinista(self):
        from src.services.asignacion_aulas_helpers import (
            sede_preferida_para_horario,
        )
        aula_sede_id = self._setup()
        sede = sede_preferida_para_horario(
            materia_codigo="MLAB",
            materia_lab_map={"MLAB": {"lab_S1", "lab_S2"}},
            # Restricción por carrera apunta a una sede sin lab: no
            # hay intersección, se elige por orden.
            sedes_admisibles_por_materia={"MLAB": {"S3"}},
            aula_sede_id=aula_sede_id,
        )
        assert sede == "S1"

    def test_sin_restriccion_ni_lab_devuelve_none(self):
        from src.services.asignacion_aulas_helpers import (
            sede_preferida_para_horario,
        )
        aula_sede_id = self._setup()
        sede = sede_preferida_para_horario(
            materia_codigo="MCOMUN",
            materia_lab_map={},
            sedes_admisibles_por_materia={"MCOMUN": None},
            aula_sede_id=aula_sede_id,
        )
        # Sin sede preferida: caller decide (heatmap contará en todas).
        assert sede is None


class TestHeatmapVistasMultiples:
    """Fase 3.5: el heatmap por sede expone 3 vistas paralelas
    (`demanda_dura`, `demanda_preferida`, `demanda_maxima`) además del
    alias `demanda` que sigue reflejando la vista preferida."""

    def _build_aulas_dos_sedes(self):
        return [
            AulaSlot(id="t1_S1", tipo="teorica", capacidad=30),
            AulaSlot(id="t2_S1", tipo="teorica", capacidad=30),
            AulaSlot(id="L_S1", tipo="laboratorio", capacidad=30),
            AulaSlot(id="t1_S2", tipo="teorica", capacidad=30),
            AulaSlot(id="L_S2", tipo="laboratorio", capacidad=30),
        ]

    def _aula_sede_id(self):
        return {
            "t1_S1": "S1", "t2_S1": "S1", "L_S1": "S1",
            "t1_S2": "S2", "L_S2": "S2",
        }

    def _sede_nombre(self):
        return {"S1": "Sede 1", "S2": "Sede 2"}

    def test_dura_solo_cuando_hay_unica_sede_admisible(self):
        """Materia con `admis={S1}` y sin lab en otro lado → aporta a
        `demanda_dura[S1]`. Materia con admis={S1,S2} no aporta a dura."""
        h_solo = _h("h1", "Lunes", 8, 10, materia="M_SOLO", tipo="teorica")
        h_amb = _h("h2", "Lunes", 8, 10, materia="M_AMB", tipo="teorica")
        aulas = self._build_aulas_dos_sedes()
        out = compute_heatmap_por_sede(
            horarios=[h_solo, h_amb], aulas=aulas, materia_lab_map={},
            sedes_admisibles_por_materia={
                "M_SOLO": {"S1"}, "M_AMB": {"S1", "S2"},
            },
            aula_sede_id=self._aula_sede_id(),
            sede_nombre=self._sede_nombre(),
        )
        si = out["slots"].index("08:00-08:15")
        di = out["dias"].index("Lunes")
        s1_teo = out["data"]["S1"]["teorica"]
        # Vista dura: sólo M_SOLO (única sede) aporta.
        assert s1_teo["demanda_dura"][si][di] == 1
        # Preferida: M_SOLO va a S1 (única) y M_AMB va a S1 (menor id).
        assert s1_teo["demanda_preferida"][si][di] == 2
        # Máxima: ambos aparecen en S1 (ambos la admiten).
        assert s1_teo["demanda_maxima"][si][di] == 2
        # En S2 sólo M_AMB entra como máxima.
        s2_teo = out["data"]["S2"]["teorica"]
        assert s2_teo["demanda_dura"][si][di] == 0
        assert s2_teo["demanda_preferida"][si][di] == 0
        assert s2_teo["demanda_maxima"][si][di] == 1

    def test_maxima_incluye_sede_alcanzable_por_lab(self):
        """Caso A5: carrera en S1 pero lab en S2. La sede S2 aparece
        como demanda_maxima (por el lab) aunque la preferida es S2
        (Fase 2) y la dura no aplica (hay 2 sedes admisibles).
        """
        h = _h("h1", "Lunes", 8, 10, materia="MLAB", tipo="teorica")
        aulas = self._build_aulas_dos_sedes()
        out = compute_heatmap_por_sede(
            horarios=[h], aulas=aulas,
            materia_lab_map={"MLAB": {"L_S2"}},
            sedes_admisibles_por_materia={"MLAB": {"S1"}},
            aula_sede_id=self._aula_sede_id(),
            sede_nombre=self._sede_nombre(),
        )
        si = out["slots"].index("08:00-08:15")
        di = out["dias"].index("Lunes")
        s1 = out["data"]["S1"]["teorica"]
        s2 = out["data"]["S2"]["teorica"]
        # Preferida (Fase 2): la teórica va a S2 (donde está el lab).
        assert s2["demanda_preferida"][si][di] == 1
        assert s1["demanda_preferida"][si][di] == 0
        # Máxima: ambas sedes son admisibles (S1 por carrera, S2 por lab).
        assert s1["demanda_maxima"][si][di] == 1
        assert s2["demanda_maxima"][si][di] == 1
        # Dura: hay 2 sedes admisibles → 0 en ambas.
        assert s1["demanda_dura"][si][di] == 0
        assert s2["demanda_dura"][si][di] == 0

    def test_coherencia_dura_pref_maxima(self):
        """Invariante: en cada celda × sede × cat, dura ≤ preferida ≤ maxima."""
        h1 = _h("h1", "Lunes", 8, 10, materia="M1", tipo="teorica")
        h2 = _h("h2", "Lunes", 8, 10, materia="M2", tipo="teorica")
        h3 = _h("h3", "Lunes", 8, 10, materia="M3", tipo="teorica")
        aulas = self._build_aulas_dos_sedes()
        out = compute_heatmap_por_sede(
            horarios=[h1, h2, h3], aulas=aulas, materia_lab_map={},
            sedes_admisibles_por_materia={
                "M1": {"S1"}, "M2": {"S1", "S2"}, "M3": None,
            },
            aula_sede_id=self._aula_sede_id(),
            sede_nombre=self._sede_nombre(),
        )
        for meta in out["sedes"]:
            for cat in ("teorica", "laboratorio"):
                d = out["data"][meta["sede_id"]][cat]
                for si in range(len(out["slots"])):
                    for di in range(len(out["dias"])):
                        dura = d["demanda_dura"][si][di]
                        pref = d["demanda_preferida"][si][di]
                        max_ = d["demanda_maxima"][si][di]
                        assert dura <= pref <= max_, (
                            f"cat={cat} si={si} di={di} "
                            f"dura={dura} pref={pref} max={max_}"
                        )

    def test_alias_demanda_igual_a_preferida(self):
        """El campo `demanda` sigue siendo alias de `demanda_preferida`
        para no romper calleres previos a Fase 3.5."""
        h = _h("h1", "Lunes", 8, 10, materia="M1", tipo="teorica")
        aulas = self._build_aulas_dos_sedes()
        out = compute_heatmap_por_sede(
            horarios=[h], aulas=aulas, materia_lab_map={},
            sedes_admisibles_por_materia={"M1": {"S1"}},
            aula_sede_id=self._aula_sede_id(),
            sede_nombre=self._sede_nombre(),
        )
        for meta in out["sedes"]:
            for cat in ("teorica", "laboratorio"):
                d = out["data"][meta["sede_id"]][cat]
                for si in range(len(out["slots"])):
                    for di in range(len(out["dias"])):
                        assert (
                            d["demanda"][si][di]
                            == d["demanda_preferida"][si][di]
                        )


class TestHeatmapTotalSinSede:
    """Fase 3.5: cota inferior de factibilidad global."""

    def test_suma_ignora_sede(self):
        """3 horarios teóricos solapan en la misma franja: total=3
        aunque cada uno prefiera una sede distinta."""
        h1 = _h("h1", "Lunes", 8, 10, materia="M1", tipo="teorica")
        h2 = _h("h2", "Lunes", 8, 10, materia="M2", tipo="teorica")
        h3 = _h("h3", "Lunes", 8, 10, materia="M3", tipo="teorica")
        aulas = [
            AulaSlot(id="t1", tipo="teorica", capacidad=30),
            AulaSlot(id="t2", tipo="teorica", capacidad=30),
            AulaSlot(id="anf", tipo="anfiteatro", capacidad=100),
        ]
        out = compute_heatmap_total_sin_sede(
            horarios=[h1, h2, h3], aulas=aulas, materia_lab_map={},
        )
        si = out["slots"].index("08:00-08:15")
        di = out["dias"].index("Lunes")
        assert out["data"]["teorica"]["demanda"][si][di] == 3
        # Oferta agregada: 2 teóricas + 1 anfiteatro = 3.
        assert out["oferta_total"]["teorica"] == 3
        assert out["data"]["teorica"]["oferta"][si][di] == 3
        assert out["data"]["teorica"]["ratio"][si][di] == 1.0

    def test_infactibilidad_global_ratio_supera_1(self):
        """Cuando la suma total supera la oferta agregada, el ratio > 1."""
        hs = [
            _h(f"h{i}", "Lunes", 8, 10, materia=f"M{i}", tipo="teorica")
            for i in range(5)
        ]
        aulas = [
            AulaSlot(id="t1", tipo="teorica", capacidad=30),
            AulaSlot(id="t2", tipo="teorica", capacidad=30),
        ]
        out = compute_heatmap_total_sin_sede(
            horarios=hs, aulas=aulas, materia_lab_map={},
        )
        si = out["slots"].index("08:00-08:15")
        di = out["dias"].index("Lunes")
        # 5 horarios simultáneos, 2 aulas totales → ratio 2.5.
        assert out["data"]["teorica"]["demanda"][si][di] == 5
        assert out["data"]["teorica"]["ratio"][si][di] == 2.5

    def test_laboratorio_usa_pool_maximo_por_materia(self):
        """Para labs, la oferta agregada es el mayor pool disponible
        entre las materias con lab presentes en el plan."""
        h_lab = _h("h1", "Lunes", 8, 10, materia="MLAB", tipo="laboratorio")
        aulas = [
            AulaSlot(id="L1", tipo="laboratorio", capacidad=30),
            AulaSlot(id="L2", tipo="laboratorio", capacidad=30),
            AulaSlot(id="L3", tipo="laboratorio", capacidad=30),
        ]
        # MLAB tiene sólo 2 labs compatibles → oferta = 2 (no 3).
        out = compute_heatmap_total_sin_sede(
            horarios=[h_lab], aulas=aulas,
            materia_lab_map={"MLAB": {"L1", "L2"}},
        )
        assert out["oferta_total"]["laboratorio"] == 2
        si = out["slots"].index("08:00-08:15")
        di = out["dias"].index("Lunes")
        assert out["data"]["laboratorio"]["demanda"][si][di] == 1
        assert out["data"]["laboratorio"]["oferta"][si][di] == 2
