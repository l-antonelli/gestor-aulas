"""Tests para asignacion_aulas_service.

Fase 1 (R1, R4, R7): TestBuildInputs + TestRunLPDry.
Fase 2 (persistencia, re-run, LPRunDB): TestApply, TestRunLP.
"""

import json
import uuid
from datetime import date, time

import pytest
from sqlalchemy.pool import StaticPool
from sqlmodel import Session, SQLModel, create_engine, select

from src.database.models import (
    AulaDB,
    CicloDB,
    ClaseDB,
    ComisionDB,
    DictadoCicloDB,
    DictadoDB,
    HorarioDB,
    InscripcionHistoricaDB,
    MateriaDB,
    PlanificacionCursadaDB,
    SedeDB,
)
from src.services.asignacion_aulas_service import (
    LPConfig,
    build_inputs,
    get_latest_run,
    run_lp,
    run_lp_dry,
)
from src.services.clase_generation_service import generate_clases_for_plan


# =============================================================================
# Fixtures
# =============================================================================

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


def _seed_basic(session: Session) -> dict:
    """Crea ciclo, dictado y plan vacío. Devuelve refs útiles.

    Adicionalmente crea una `SedeDB` con id "S1" para poder usarse desde
    los `AulaDB(sede_id="S1", ...)` que arman los tests inline.
    """
    ciclo = CicloDB(
        id="2026-1C", anio=2026, numero=1,
        fecha_inicio=date(2026, 3, 9), fecha_fin=date(2026, 7, 3),
    )
    plan = PlanificacionCursadaDB(
        id="plan-1", nombre="Plan Test",
        ciclo_id="2026-1C", activo=True,
    )
    sede = SedeDB(id="S1", nombre="Sede Test")
    session.add_all([ciclo, plan, sede])
    session.commit()
    return {"ciclo": ciclo, "plan": plan, "sede": sede}


def _add_materia_con_serie(
    session: Session, codigo: str, ciclo: CicloDB, esperados: int,
    horas_semanales: float = 4, tipo_clase: str | None = "teorica",
):
    """Crea materia + dictado + comisión + horario + serie histórica para
    que el forecast resuelva."""
    materia = MateriaDB(
        codigo=codigo, nombre=f"Materia {codigo}",
        horas_semanales=horas_semanales,
        horas_teoria=horas_semanales, horas_laboratorio=0,
    )
    dictado = DictadoDB(
        id=f"dict-{codigo}", materia_codigo=codigo,
        dictado_codigo=f"{codigo}-{ciclo.anio}-{ciclo.numero}C",
        inicio_dictado=ciclo.fecha_inicio, fin_dictado=ciclo.fecha_fin,
    )
    bridge = DictadoCicloDB(dictado_id=f"dict-{codigo}", ciclo_id=ciclo.id)
    # Serie histórica para que resolve_metodo no falle.
    serie = [
        InscripcionHistoricaDB(
            materia_codigo=codigo, anio=ciclo.anio - 1,
            cuatrimestre=f"{ciclo.numero}C", inscriptos=esperados,
        ),
    ]
    session.add(materia)
    session.add(dictado)
    session.add(bridge)
    for s in serie:
        session.add(s)
    session.commit()
    return materia


def _add_comision_horario(
    session: Session, plan_id: str, materia_codigo: str, dia: str,
    hi: int, hf: int, tipo_clase: str | None = "teorica",
    coef: float = 1.0,
):
    """Agrega una comisión y un horario para esa comisión. Devuelve
    el horario."""
    com_id = str(uuid.uuid4())
    comision = ComisionDB(
        id=com_id,
        materia_codigo=materia_codigo,
        plan_cursada_id=plan_id,
        comision_key=f"{materia_codigo}-001",
        nombre="Comisión 1",
        numero=1,
        cupo=30,
        coef_asignacion=coef,
    )
    hor_id = str(uuid.uuid4())
    horario = HorarioDB(
        id=hor_id,
        comision_id=com_id,
        codigo_materia=materia_codigo,
        dia=dia,
        hora_inicio=time(hi, 0),
        hora_fin=time(hf, 0),
        tipo_clase=tipo_clase,
    )
    session.add(comision)
    session.add(horario)
    session.commit()
    return horario


# =============================================================================
# Tests
# =============================================================================

class TestBuildInputs:

    def test_build_inputs_basico(self, session):
        ctx = _seed_basic(session)
        _add_materia_con_serie(session, "MAT", ctx["ciclo"], esperados=20)
        h = _add_comision_horario(session, "plan-1", "MAT", "Lunes", 8, 10)
        session.add(AulaDB(id="a1", sede_id="S1", codigo_aula="a1", nombre="Aula 1", capacidad=30))
        session.commit()

        inputs = build_inputs(session, "plan-1", LPConfig())

        assert len(inputs.horarios) == 1
        assert inputs.horarios[0].id == h.id
        assert len(inputs.aulas) == 1
        assert inputs.dur[h.id] == pytest.approx(2.0)
        assert inputs.insc[h.id] == pytest.approx(20.0)
        assert inputs.compat[(h.id, "a1")] is True
        assert inputs.sim_groups == []  # un solo horario, sin grupos

    def test_filtra_materias_virtuales(self, session):
        ctx = _seed_basic(session)
        m_vir = MateriaDB(
            codigo="VIR", nombre="Virtual", virtual=True,
            horas_semanales=4, horas_teoria=4, horas_laboratorio=0,
        )
        session.add(m_vir)
        session.add(DictadoDB(
            id="d-vir", materia_codigo="VIR", dictado_codigo="VIR-2026-1C",
        ))
        session.add(DictadoCicloDB(dictado_id="d-vir", ciclo_id=ctx["ciclo"].id))
        session.commit()
        _add_comision_horario(session, "plan-1", "VIR", "Lunes", 8, 10)
        session.add(AulaDB(id="a1", sede_id="S1", codigo_aula="a1", nombre="Aula 1", capacidad=30))
        session.commit()

        inputs = build_inputs(session, "plan-1", LPConfig())

        assert len(inputs.horarios) == 0
        assert any("virtual" in w for w in inputs.warnings)


class TestRunLPDry:

    def test_minimo_clase_grande_va_a_aula_grande(self, session):
        """3 horarios, 3 aulas con cap distinta. El penalty asimétrico
        debería privilegiar que el horario grande vaya al aula grande."""
        ctx = _seed_basic(session)
        ciclo = ctx["ciclo"]
        _add_materia_con_serie(session, "M_BIG", ciclo, esperados=80)
        _add_materia_con_serie(session, "M_MED", ciclo, esperados=50)
        _add_materia_con_serie(session, "M_SML", ciclo, esperados=20)
        h_big = _add_comision_horario(session, "plan-1", "M_BIG", "Lunes", 8, 10)
        h_med = _add_comision_horario(session, "plan-1", "M_MED", "Lunes", 14, 16)
        h_sml = _add_comision_horario(session, "plan-1", "M_SML", "Martes", 10, 12)
        session.add_all([
            AulaDB(id="big", sede_id="S1", codigo_aula="big", nombre="Big", capacidad=100),
            AulaDB(id="med", sede_id="S1", codigo_aula="med", nombre="Med", capacidad=60),
            AulaDB(id="sml", sede_id="S1", codigo_aula="sml", nombre="Small", capacidad=30),
        ])
        session.commit()

        _, sol = run_lp_dry(session, "plan-1")

        assert sol.status == "optimal"
        # No hay restricción de no doble-booking entre los 3 (todos en
        # franjas/días distintos), pero el penalty tira hacia ajuste.
        # Con λ_over=10, λ_under=1, tol_under=0.20:
        # - M_BIG (80): cap=100 → under ≈ 0 (100·0.8=80, 80-80=0). Va a "big".
        # - M_MED (50): cap=60 → under ≈ 0 (60·0.8=48, 48-50<0 → under=0). Va a "med".
        # - M_SML (20): cap=30 → under ≈ 0+ (30·0.8=24, 24-20=4 → under=4). Va a "sml".
        # Cualquier asignación que mande BIG a med o sml genera over alto.
        assert sol.x_assignments[h_big.id] == "big"
        assert sol.over[h_big.id] == pytest.approx(0.0, abs=1e-3)

    def test_conflicto_temporal_infactible(self, session):
        """2 horarios mismo slot, 1 aula → infactible."""
        ctx = _seed_basic(session)
        ciclo = ctx["ciclo"]
        _add_materia_con_serie(session, "M1", ciclo, esperados=20)
        _add_materia_con_serie(session, "M2", ciclo, esperados=20)
        _add_comision_horario(session, "plan-1", "M1", "Lunes", 8, 10)
        _add_comision_horario(session, "plan-1", "M2", "Lunes", 8, 10)
        session.add(AulaDB(id="a1", sede_id="S1", codigo_aula="a1", nombre="Única", capacidad=30))
        session.commit()

        _, sol = run_lp_dry(session, "plan-1")

        assert sol.status == "infeasible"

    def test_sobreocupacion_reportada_en_over(self, session):
        """1 horario insc=100, aulas cap=80, 60. Va a 80, over=20."""
        ctx = _seed_basic(session)
        ciclo = ctx["ciclo"]
        _add_materia_con_serie(session, "M1", ciclo, esperados=100)
        h = _add_comision_horario(session, "plan-1", "M1", "Lunes", 8, 10)
        session.add_all([
            AulaDB(id="big", sede_id="S1", codigo_aula="big", nombre="Big", capacidad=80),
            AulaDB(id="med", sede_id="S1", codigo_aula="med", nombre="Med", capacidad=60),
        ])
        session.commit()

        _, sol = run_lp_dry(session, "plan-1")

        assert sol.status == "optimal"
        assert sol.x_assignments[h.id] == "big"
        # over = insc - cap*(1+tol_over) = 100 - 80*1 = 20
        assert sol.over[h.id] == pytest.approx(20.0, abs=1e-3)


# =============================================================================
# Fase 2 — apply, persist, run_lp, fecha_desde, respetar_manuales
# =============================================================================

def _seed_plan_con_clases(session: Session) -> tuple[ClaseDB, ClaseDB]:
    """Seed estándar para tests de Fase 2: plan con 1 horario lunes 8-10
    en un ciclo de 2 semanas, generando 2 ClaseDB.

    Devuelve la (clase_semana_1, clase_semana_2) ordenadas por fecha.
    """
    ctx = _seed_basic(session)
    ciclo = ctx["ciclo"]
    # Acortar el ciclo a 2 semanas exactas para tener 2 lunes nada más.
    ciclo.fecha_inicio = date(2026, 3, 9)   # lunes
    ciclo.fecha_fin = date(2026, 3, 22)     # domingo siguiente
    session.add(ciclo)
    session.commit()

    _add_materia_con_serie(session, "M1", ciclo, esperados=20)
    _add_comision_horario(session, "plan-1", "M1", "Lunes", 8, 10)
    session.add_all([
        AulaDB(id="a1", sede_id="S1", codigo_aula="a1", nombre="A1", capacidad=30),
        AulaDB(id="a2", sede_id="S1", codigo_aula="a2", nombre="A2", capacidad=30),
    ])
    session.commit()

    res = generate_clases_for_plan(session, "plan-1")
    assert res.clases_created == 2

    clases = list(session.exec(
        select(ClaseDB).order_by(ClaseDB.fecha)  # type: ignore[attr-defined]
    ).all())
    return clases[0], clases[1]


class TestRunLPPersistencia:

    def test_persiste_lp_run_con_resumen(self, session):
        c1, c2 = _seed_plan_con_clases(session)

        run = run_lp(session, "plan-1")

        assert run.status == "optimal"
        assert run.n_horarios_total == 1
        assert run.n_horarios_asignados == 1
        assert run.n_clases_actualizadas == 2
        assert run.n_ediciones_manuales_respetadas == 0
        # round-trip: get_latest_run devuelve la misma fila
        latest = get_latest_run(session, "plan-1")
        assert latest is not None and latest.id == run.id

    def test_apply_propaga_aula_a_clases(self, session):
        c1, c2 = _seed_plan_con_clases(session)

        run_lp(session, "plan-1")

        session.refresh(c1)
        session.refresh(c2)
        assert c1.aula_id is not None
        assert c1.aula_id == c2.aula_id  # mismo horario → misma aula
        assert c1.aula_asignada_manualmente is False
        assert c2.aula_asignada_manualmente is False

    def test_details_json_serializa(self, session):
        _seed_plan_con_clases(session)

        run = run_lp(session, "plan-1")

        details = json.loads(run.details_json)
        assert "horarios" in details
        assert len(details["horarios"]) == 1
        assert details["horarios"][0]["aula_id"] in ("a1", "a2")


class TestRunLPFechaDesde:

    def test_fecha_desde_no_pisa_clases_anteriores(self, session):
        c1, c2 = _seed_plan_con_clases(session)
        # Pre-asignar c1 a un aula distinta para verificar que no se pise.
        c1.aula_id = "a2"
        session.add(c1)
        session.commit()
        # Re-correr con fecha_desde después de c1.
        cfg = LPConfig(fecha_desde=c2.fecha)
        run_lp(session, "plan-1", config=cfg)

        session.refresh(c1)
        session.refresh(c2)
        # c1 quedó como estaba (a2), c2 fue asignada por el LP (lo que sea).
        assert c1.aula_id == "a2"
        assert c2.aula_id is not None


class TestRunLPRespetarManuales:

    def test_respetar_manuales_no_pisa(self, session):
        c1, c2 = _seed_plan_con_clases(session)
        # Marcar c1 como editada a mano con un aula específica.
        c1.aula_id = "a2"
        c1.aula_asignada_manualmente = True
        session.add(c1)
        session.commit()

        cfg = LPConfig(respetar_ediciones_manuales=True)
        run = run_lp(session, "plan-1", config=cfg)

        session.refresh(c1)
        session.refresh(c2)
        assert c1.aula_id == "a2"  # respetada
        assert c1.aula_asignada_manualmente is True
        assert run.n_ediciones_manuales_respetadas == 1

    def test_lab_split_decide_tipo(self, session):
        """Comisión con hteo=2, hlab=2, dos horarios sin tipo. El LP debe
        decidir uno como lab y otro como teoría. La pre-validación debe
        marcarlo como factible."""
        from src.database.models import (
            AulaDB, MateriaLaboratorioDB,
        )
        from src.services.asignacion_aulas_service import diagnose
        ctx = _seed_basic(session)
        ciclo = ctx["ciclo"]
        # Materia con horas mixtas.
        materia = MateriaDB(
            codigo="LAB", nombre="Materia Lab",
            horas_semanales=4, horas_teoria=2, horas_laboratorio=2,
        )
        dictado = DictadoDB(
            id="dict-LAB", materia_codigo="LAB",
            dictado_codigo="LAB-2026-1C",
            inicio_dictado=ciclo.fecha_inicio, fin_dictado=ciclo.fecha_fin,
        )
        bridge = DictadoCicloDB(dictado_id="dict-LAB", ciclo_id=ciclo.id)
        serie = InscripcionHistoricaDB(
            materia_codigo="LAB", anio=ciclo.anio - 1,
            cuatrimestre=f"{ciclo.numero}C", inscriptos=20,
        )
        session.add_all([materia, dictado, bridge, serie])
        session.commit()
        # Horarios sin tipo fijado: lunes 8-10 y miércoles 14-16.
        com_id = str(uuid.uuid4())
        comision = ComisionDB(
            id=com_id, materia_codigo="LAB", plan_cursada_id="plan-1",
            comision_key="LAB-001", nombre="Com 1", numero=1, cupo=30,
        )
        session.add(comision)
        h1 = HorarioDB(
            id="h_lab_1", comision_id=com_id, codigo_materia="LAB",
            dia="Lunes", hora_inicio=time(8, 0), hora_fin=time(10, 0),
            tipo_clase=None,
        )
        h2 = HorarioDB(
            id="h_lab_2", comision_id=com_id, codigo_materia="LAB",
            dia="Miércoles", hora_inicio=time(14, 0), hora_fin=time(16, 0),
            tipo_clase=None,
        )
        session.add_all([h1, h2])
        session.add_all([
            AulaDB(id="aT", sede_id="S1", codigo_aula="aT", nombre="Teo", capacidad=30, tipo="teorica"),
            AulaDB(id="aL", sede_id="S1", codigo_aula="aL", nombre="Lab", capacidad=30, tipo="laboratorio"),
        ])
        # Compatibilidad lab para LAB.
        session.add(MateriaLaboratorioDB(materia_codigo="LAB", aula_id="aL"))
        session.commit()

        # Pre-validación: factible.
        from src.services.asignacion_aulas_service import build_inputs as _bi
        inputs = _bi(session, "plan-1", LPConfig())
        diag = diagnose(inputs)
        assert diag.particion_problemas == []

        # LP: resuelve, una clase termina lab, la otra teoría.
        _, sol = run_lp_dry(session, "plan-1")
        assert sol.status == "optimal"
        # Ambos horarios asignados.
        assert h1.id in sol.x_assignments and h2.id in sol.x_assignments
        # El que va al lab tiene t=1; el otro t=0.
        tipos = sol.tipo_resuelto
        assert set(tipos.values()) == {"teorica", "laboratorio"}

    def test_no_respetar_manuales_pisa(self, session):
        c1, c2 = _seed_plan_con_clases(session)
        c1.aula_id = "a2"
        c1.aula_asignada_manualmente = True
        session.add(c1)
        session.commit()

        cfg = LPConfig(respetar_ediciones_manuales=False)
        run_lp(session, "plan-1", config=cfg)

        session.refresh(c1)
        session.refresh(c2)
        # Ambas deberían quedar con la aula que eligió el LP, y el flag
        # bajado a False (el LP retomó el control).
        assert c1.aula_id == c2.aula_id
        assert c1.aula_asignada_manualmente is False


class TestEdicionManual:

    def test_validar_y_aplicar_puntual(self, session):
        from src.services.asignacion_aulas_service import (
            aplicar_edicion_manual, validar_edicion_manual,
        )
        c1, c2 = _seed_plan_con_clases(session)
        # Inicialmente sin aula. Ponerle una manual al primero.
        c1.tipo_clase = "teorica"
        c2.tipo_clase = "teorica"
        session.add_all([c1, c2])
        session.commit()
        res = validar_edicion_manual(session, [c1.id], "a1")
        assert res.ok is True
        n = aplicar_edicion_manual(session, [c1.id], "a1")
        assert n == 1
        session.refresh(c1)
        session.refresh(c2)
        assert c1.aula_id == "a1"
        assert c1.aula_asignada_manualmente is True
        # c2 no se tocó.
        assert c2.aula_id is None

    def test_validar_doble_booking_rechaza(self, session):
        from src.services.asignacion_aulas_service import (
            aplicar_edicion_manual, validar_edicion_manual,
        )
        c1, c2 = _seed_plan_con_clases(session)
        # c1 asignada a a1; c2 ahora se quiere asignar a a1 también
        # (mismo día por construcción del seed: no, c2 es el lunes
        # siguiente). Para forzar choque, creo otra clase del mismo día
        # de c1 con horario solapado y aula a1.
        from src.database.models import (
            ClaseDB as _C, ComisionDB as _Com, HorarioDB as _Hor,
        )
        c1.tipo_clase = "teorica"
        c1.aula_id = "a1"
        c1.aula_asignada_manualmente = True
        session.add(c1)
        session.commit()
        # Otra clase mismo día, mismo horario, otra comisión, asignada a a2.
        # Editamos para mandarla a a1 → debe rechazar.
        com_id = str(uuid.uuid4())
        otra_com = _Com(
            id=com_id, materia_codigo="M1", plan_cursada_id="plan-1",
            comision_key="M1-002", nombre="C2", numero=2, cupo=30,
        )
        hor_id = str(uuid.uuid4())
        otro_hor = _Hor(
            id=hor_id, comision_id=com_id, codigo_materia="M1",
            dia="Lunes", hora_inicio=time(8, 0), hora_fin=time(10, 0),
        )
        clase_otra = _C(
            id=str(uuid.uuid4()), horario_id=hor_id, comision_id=com_id,
            plan_cursada_id="plan-1", fecha=c1.fecha,
            hora_inicio=time(8, 0), hora_fin=time(10, 0),
            tipo_clase="teorica", aula_id="a2",
        )
        session.add_all([otra_com, otro_hor, clase_otra])
        session.commit()
        # Quiero mover clase_otra a a1 (donde está c1) → choque.
        res = validar_edicion_manual(session, [clase_otra.id], "a1")
        assert res.ok is False
        assert any("ocupada" in e for e in res.errores)

    def test_validar_tipo_incompatible(self, session):
        from src.services.asignacion_aulas_service import (
            validar_edicion_manual,
        )
        from src.database.models import AulaDB as _Aula
        c1, c2 = _seed_plan_con_clases(session)
        # Marcar c1 como teórica.
        c1.tipo_clase = "teorica"
        session.add(c1)
        # Crear aula laboratorio.
        session.add(_Aula(
            id="aL", sede_id="S1", codigo_aula="aL",
            nombre="Lab", capacidad=30, tipo="laboratorio",
        ))
        session.commit()
        # Intento mandar la clase teórica a un lab.
        res = validar_edicion_manual(session, [c1.id], "aL")
        assert res.ok is False
        assert any("teórica" in e for e in res.errores)

    def test_clases_del_rango(self, session):
        from src.services.asignacion_aulas_service import clases_del_rango
        c1, c2 = _seed_plan_con_clases(session)
        # c1, c2 son del mismo horario (lunes 8-10) en semanas distintas.
        # Rango incluyendo c1 y c2.
        rango = clases_del_rango(
            session, c1.id, fecha_desde=c1.fecha, fecha_hasta=c2.fecha,
        )
        ids = {c.id for c in rango}
        assert ids == {c1.id, c2.id}
        # Rango sólo c1.
        rango = clases_del_rango(
            session, c1.id, fecha_desde=c1.fecha, fecha_hasta=c1.fecha,
        )
        assert {c.id for c in rango} == {c1.id}

    def test_re_run_respeta_aula_manual_seteada(self, session):
        from src.services.asignacion_aulas_service import (
            aplicar_edicion_manual, validar_edicion_manual,
        )
        c1, c2 = _seed_plan_con_clases(session)
        c1.tipo_clase = "teorica"
        session.add(c1)
        session.commit()
        # Edición manual de c1 a a1.
        res = validar_edicion_manual(session, [c1.id], "a1")
        assert res.ok is True
        aplicar_edicion_manual(session, [c1.id], "a1")
        # Re-correr LP con respetar_manuales=True.
        cfg = LPConfig(respetar_ediciones_manuales=True)
        run_lp(session, "plan-1", config=cfg)
        session.refresh(c1)
        # La edición sobrevive.
        assert c1.aula_id == "a1"
        assert c1.aula_asignada_manualmente is True


# =============================================================================
# Fase 8 — Toggle α
# =============================================================================

def _seed_dos_comisiones_desbalanceadas(session: Session) -> dict:
    """Seed con un dictado, dos comisiones del mismo dictado, total
    esperado=120, coef inicial [1.0, 0.0], dos aulas iguales cap=60.

    El caso clásico donde α=OFF deja over=60+under=60 y α=ON debería
    redistribuir a [0.5, 0.5] con over=under=0.
    """
    from src.database.models import (
        AulaDB as _Aula, MateriaLaboratorioDB as _ML,
    )
    ctx = _seed_basic(session)
    ciclo = ctx["ciclo"]
    # Acortar el ciclo a 1 semana.
    ciclo.fecha_inicio = date(2026, 3, 9)
    ciclo.fecha_fin = date(2026, 3, 15)
    session.add(ciclo)
    session.commit()

    # Materia con total=120 (vía serie histórica).
    _add_materia_con_serie(session, "ALFA", ciclo, esperados=120)

    # Dos comisiones del mismo dictado, distinto día/hora.
    dictado_id = "dict-ALFA"
    com1_id = str(uuid.uuid4())
    com2_id = str(uuid.uuid4())
    com1 = ComisionDB(
        id=com1_id, materia_codigo="ALFA", plan_cursada_id="plan-1",
        dictado_id=dictado_id, comision_key="ALFA-001",
        nombre="Com 1", numero=1, cupo=30, coef_asignacion=1.0,
    )
    com2 = ComisionDB(
        id=com2_id, materia_codigo="ALFA", plan_cursada_id="plan-1",
        dictado_id=dictado_id, comision_key="ALFA-002",
        nombre="Com 2", numero=2, cupo=30, coef_asignacion=0.0,
    )
    h1 = HorarioDB(
        id="h_a1", comision_id=com1_id, codigo_materia="ALFA",
        dia="Lunes", hora_inicio=time(8, 0), hora_fin=time(10, 0),
        tipo_clase="teorica",
    )
    h2 = HorarioDB(
        id="h_a2", comision_id=com2_id, codigo_materia="ALFA",
        dia="Martes", hora_inicio=time(8, 0), hora_fin=time(10, 0),
        tipo_clase="teorica",
    )
    session.add_all([com1, com2, h1, h2])
    # Dos aulas iguales cap=60.
    session.add_all([
        _Aula(id="a60_1", sede_id="S1", codigo_aula="a60_1",
              nombre="A 60-1", capacidad=60, tipo="teorica"),
        _Aula(id="a60_2", sede_id="S1", codigo_aula="a60_2",
              nombre="A 60-2", capacidad=60, tipo="teorica"),
    ])
    session.commit()
    return {"com1_id": com1_id, "com2_id": com2_id}


class TestToggleAlpha:

    def test_alpha_off_no_redistribuye_y_genera_desajuste(self, session):
        """Sin α activo, los pesos [1.0, 0.0] obligan a sobrecargar el
        aula de la comisión 1 (esperados 120, cap 60) y vaciar la otra
        (esperados 0, cap 60).
        """
        ctx = _seed_dos_comisiones_desbalanceadas(session)
        cfg = LPConfig(activar_alpha=False, lambda_over=10, lambda_under=1)
        _, sol = run_lp_dry(session, "plan-1", cfg)
        assert sol.status == "optimal"
        total_over = sum(sol.over.values())
        total_under = sum(sol.under.values())
        # over >= 120 - 60*1 = 60 (sobre-ocupación por comisión 1).
        # under >= 60*0.8 - 0 = 48 (sub-utilización tolerada).
        assert total_over == pytest.approx(60.0, abs=1e-3)
        # alpha_resuelto vacío cuando toggle OFF.
        assert sol.alpha_resuelto == {}

    def test_alpha_on_redistribuye_a_50_50(self, session):
        """Con α activo, el LP encuentra α=[0.5, 0.5] y elimina
        over+under (las dos aulas de cap=60 calzan exacto con 60
        esperados c/u)."""
        ctx = _seed_dos_comisiones_desbalanceadas(session)
        cfg = LPConfig(activar_alpha=True, lambda_over=10, lambda_under=1)
        _, sol = run_lp_dry(session, "plan-1", cfg)
        assert sol.status == "optimal"
        # α propuesto ~ 0.5 / 0.5
        a1 = sol.alpha_resuelto[ctx["com1_id"]]
        a2 = sol.alpha_resuelto[ctx["com2_id"]]
        assert a1 == pytest.approx(0.5, abs=0.05)
        assert a2 == pytest.approx(0.5, abs=0.05)
        assert a1 + a2 == pytest.approx(1.0, abs=1e-6)
        # over y under cero (con tol_under=0.20 default, 60·0.8=48; 60-48=12
        # de under residual aceptable). El total importa: bajó muchísimo
        # respecto al caso OFF.
        total_over = sum(sol.over.values())
        assert total_over == pytest.approx(0.0, abs=1e-3)

    def test_aplicar_alpha_no_persiste_automaticamente(self, session):
        """run_lp con α activo NO debe modificar coef_asignacion en la DB.
        Ese cambio requiere confirmación explícita vía
        aplicar_alpha_propuesto."""
        ctx = _seed_dos_comisiones_desbalanceadas(session)
        cfg = LPConfig(activar_alpha=True)
        run_lp(session, "plan-1", config=cfg)
        com1 = session.get(ComisionDB, ctx["com1_id"])
        com2 = session.get(ComisionDB, ctx["com2_id"])
        assert com1 is not None and com2 is not None
        # Los pesos siguen siendo los originales.
        assert com1.coef_asignacion == pytest.approx(1.0)
        assert com2.coef_asignacion == pytest.approx(0.0)

    def test_aplicar_alpha_propuesto_persiste(self, session):
        from src.services.asignacion_aulas_service import (
            aplicar_alpha_propuesto,
        )
        ctx = _seed_dos_comisiones_desbalanceadas(session)
        n = aplicar_alpha_propuesto(
            session, "plan-1",
            {ctx["com1_id"]: 0.5, ctx["com2_id"]: 0.5},
        )
        assert n == 2
        com1 = session.get(ComisionDB, ctx["com1_id"])
        com2 = session.get(ComisionDB, ctx["com2_id"])
        assert com1 is not None and com2 is not None
        assert com1.coef_asignacion == pytest.approx(0.5)
        assert com2.coef_asignacion == pytest.approx(0.5)
