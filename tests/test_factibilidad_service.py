"""Tests para el chequeo de factibilidad estructural (Fase 7)."""

import uuid
from datetime import date, time

import pytest
from sqlalchemy.pool import StaticPool
from sqlmodel import Session, SQLModel, create_engine, select

from src.database.models import (
    AulaDB,
    CarreraDB,
    CicloDB,
    ComisionDB,
    DictadoCicloDB,
    DictadoDB,
    HorarioDB,
    InscripcionHistoricaDB,
    MateriaDB,
    MateriaLaboratorioDB,
    PlanCarreraVersionDB,
    PlanEstudioDB,
    PlanificacionCursadaDB,
    SedeDB,
)
from src.services.carrera_sede_service import set_sedes_de_carrera
from src.services.factibilidad_service import (
    check_factibilidad_estructural,
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


@pytest.fixture(name="session")
def session_fixture(engine):
    with Session(engine) as session:
        yield session


def _seed_plan_basico(
    session: Session, *, hteo: float = 2, hlab: float = 0,
) -> dict:
    """Ciclo + 1 sede + 1 aula teórica + M1 con 1 comisión y 1 horario
    Lunes 8-10. Devuelve refs."""
    ciclo = CicloDB(
        id="2026-1C", anio=2026, numero=1,
        fecha_inicio=date(2026, 3, 9), fecha_fin=date(2026, 7, 3),
    )
    plan = PlanificacionCursadaDB(
        id="plan-1", nombre="P1", ciclo_id="2026-1C",
    )
    sede = SedeDB(id="S1", nombre="Sede 1")
    aula = AulaDB(
        id="a1", sede_id="S1", codigo_aula="A1", nombre="A1",
        capacidad=30, tipo="teorica",
    )
    session.add_all([ciclo, plan, sede, aula])
    session.commit()

    materia = MateriaDB(
        codigo="M1", nombre="Mat 1",
        horas_semanales=hteo + hlab,
        horas_teoria=hteo, horas_laboratorio=hlab,
    )
    dictado = DictadoDB(
        id="d-M1", materia_codigo="M1",
        dictado_codigo="M1-2026-1C",
        inicio_dictado=date(2026, 3, 9), fin_dictado=date(2026, 7, 3),
    )
    bridge = DictadoCicloDB(dictado_id="d-M1", ciclo_id="2026-1C")
    session.add(materia)
    session.add(dictado)
    session.add(bridge)
    session.add(InscripcionHistoricaDB(
        materia_codigo="M1", anio=2025, cuatrimestre="1C", inscriptos=20,
    ))
    session.commit()

    com_id = str(uuid.uuid4())
    com = ComisionDB(
        id=com_id, materia_codigo="M1", plan_cursada_id="plan-1",
        comision_key="M1-001", nombre="Com 1", numero=1, cupo=30,
        coef_asignacion=1.0,
    )
    hor = HorarioDB(
        id=str(uuid.uuid4()), comision_id=com_id, codigo_materia="M1",
        dia="Lunes", hora_inicio=time(8, 0), hora_fin=time(10, 0),
        tipo_clase="teorica",
    )
    session.add(com)
    session.add(hor)
    session.commit()
    return {"com_id": com_id, "hor_id": hor.id}


class TestPlanFactibleBasico:

    def test_plan_basico_es_factible(self, session):
        _seed_plan_basico(session)
        r = check_factibilidad_estructural(session, "plan-1")
        assert r.factible is True
        assert r.bloqueos == []


class TestR1SinAulaCompatible:

    def test_materia_lab_sin_labs_compatibles_bloquea(self, session):
        """Materia con horario tipo=laboratorio y ningún lab compatible."""
        _seed_plan_basico(session, hteo=0, hlab=2)
        hor = session.exec(select(HorarioDB)).first()
        hor.tipo_clase = "laboratorio"
        session.add(hor)
        session.commit()

        r = check_factibilidad_estructural(session, "plan-1")
        assert r.factible is False
        assert any(b.codigo_regla == "R1" for b in r.bloqueos)


class TestR5ParticionImposible:

    def test_horas_no_cierran_bloquea(self, session):
        """Materia 2h teoría + 6h lab = 8h total, pero 1 horario de 2h."""
        _seed_plan_basico(session, hteo=2, hlab=6)
        r = check_factibilidad_estructural(session, "plan-1")
        assert any(b.codigo_regla == "R5" for b in r.bloqueos)

    def test_materia_sin_lab_horas_incompletas_no_bloquea(self, session):
        """Materia con hlab=0: R5 no se aplica al LP, así que no debe
        reportar bloqueo aunque suma_horarios < hteo (regresión: bug
        de falso positivo detectado 2026-09-07)."""
        # Materia con hteo=4, hlab=0 pero un solo horario de 2h.
        # Esto NO es infactible para el LP (R5 no se materializa).
        _seed_plan_basico(session, hteo=4, hlab=0)
        r = check_factibilidad_estructural(session, "plan-1")
        assert not any(b.codigo_regla == "R5" for b in r.bloqueos), (
            "R5 no debe reportar bloqueo cuando la materia no tiene "
            "laboratorio: la ecuación de partición no se instancia "
            "en el LP para esas materias."
        )

    def test_horarios_virtuales_cuentan_para_hteo(self, session):
        """Con hlab>0, los horarios virtuales SÍ cuentan hacia hteo.
        Un horario teórico virtual + uno teórico presencial suman
        contra hteo. Si el total (incluyendo virtuales) cierra
        contra hteo+hlab, no debe haber bloqueo."""
        # Materia: hteo=4, hlab=2, total 6h.
        _seed_plan_basico(session, hteo=4, hlab=2)
        com = session.exec(select(ComisionDB)).first()
        # Cambio el horario existente a lab presencial 2h y agrego:
        # - teoria presencial 2h
        # - teoria virtual 2h
        hor_orig = session.exec(select(HorarioDB)).first()
        hor_orig.tipo_clase = "laboratorio"
        session.add(hor_orig)
        session.add(HorarioDB(
            id=str(uuid.uuid4()), comision_id=com.id, codigo_materia="M1",
            dia="Martes", hora_inicio=time(8, 0), hora_fin=time(10, 0),
            tipo_clase="teorica", virtual=False,
        ))
        session.add(HorarioDB(
            id=str(uuid.uuid4()), comision_id=com.id, codigo_materia="M1",
            dia="Miércoles", hora_inicio=time(8, 0), hora_fin=time(10, 0),
            tipo_clase="teorica", virtual=True,
        ))
        # Agrego lab compatible para que R1 no falle.
        session.add(AulaDB(
            id="l1", sede_id="S1", codigo_aula="L1", nombre="L1",
            capacidad=30, tipo="laboratorio",
        ))
        session.add(MateriaLaboratorioDB(materia_codigo="M1", aula_id="l1"))
        session.commit()

        r = check_factibilidad_estructural(session, "plan-1")
        # Total = 2 (lab) + 2 (teo pres) + 2 (teo virt) = 6 = hteo+hlab.
        # R5 debe pasar aunque uno de los horarios sea virtual.
        assert not any(b.codigo_regla == "R5" for b in r.bloqueos), (
            "Los horarios virtuales deben contar hacia hteo/hlab. "
            "Bloqueos: "
            + str([(b.codigo_regla, b.titulo) for b in r.bloqueos])
        )

    def test_horarios_virtuales_no_tapan_falta_real_de_horas(self, session):
        """Contra-prueba: si aun contando virtuales la suma no cierra,
        R5 debe reportar bloqueo."""
        # Materia hteo=4, hlab=2 (total 6h), pero sólo 2 horarios de
        # 2h cada uno (1 lab + 1 teo virt) = 4h. Faltan 2h.
        _seed_plan_basico(session, hteo=4, hlab=2)
        hor_orig = session.exec(select(HorarioDB)).first()
        hor_orig.tipo_clase = "laboratorio"
        session.add(hor_orig)
        com = session.exec(select(ComisionDB)).first()
        session.add(HorarioDB(
            id=str(uuid.uuid4()), comision_id=com.id, codigo_materia="M1",
            dia="Miércoles", hora_inicio=time(8, 0), hora_fin=time(10, 0),
            tipo_clase="teorica", virtual=True,
        ))
        # Lab compatible para descartar R1.
        session.add(AulaDB(
            id="l1", sede_id="S1", codigo_aula="L1", nombre="L1",
            capacidad=30, tipo="laboratorio",
        ))
        session.add(MateriaLaboratorioDB(materia_codigo="M1", aula_id="l1"))
        session.commit()

        r = check_factibilidad_estructural(session, "plan-1")
        assert any(b.codigo_regla == "R5" for b in r.bloqueos)


class TestCompatHall:

    def test_hall_violation_reportada(self, session):
        """Dos materias que sólo pueden ir al mismo único lab."""
        ciclo = CicloDB(
            id="2026-1C", anio=2026, numero=1,
            fecha_inicio=date(2026, 3, 9), fecha_fin=date(2026, 7, 3),
        )
        plan = PlanificacionCursadaDB(
            id="plan-1", nombre="P1", ciclo_id="2026-1C",
        )
        sede = SedeDB(id="S1", nombre="Sede 1")
        # Sólo 1 lab en el catálogo.
        lab = AulaDB(
            id="L1", sede_id="S1", codigo_aula="L1", nombre="L1",
            capacidad=30, tipo="laboratorio",
        )
        session.add_all([ciclo, plan, sede, lab])
        session.commit()

        # 2 materias tipo lab, ambas usan sólo L1.
        for mc, esperados in (("M1", 20), ("M2", 20)):
            m = MateriaDB(
                codigo=mc, nombre=f"Mat {mc}",
                horas_semanales=2, horas_teoria=0, horas_laboratorio=2,
            )
            d = DictadoDB(
                id=f"d-{mc}", materia_codigo=mc,
                dictado_codigo=f"{mc}-2026-1C",
                inicio_dictado=date(2026, 3, 9),
                fin_dictado=date(2026, 7, 3),
            )
            bridge = DictadoCicloDB(dictado_id=f"d-{mc}", ciclo_id="2026-1C")
            session.add_all([m, d, bridge])
            session.add(InscripcionHistoricaDB(
                materia_codigo=mc, anio=2025, cuatrimestre="1C",
                inscriptos=esperados,
            ))
            session.add(MateriaLaboratorioDB(
                materia_codigo=mc, aula_id="L1",
            ))
        session.commit()

        # Comisiones + horarios simultáneos (mismo día y franja).
        for mc, num in (("M1", 1), ("M2", 1)):
            cid = str(uuid.uuid4())
            session.add(ComisionDB(
                id=cid, materia_codigo=mc, plan_cursada_id="plan-1",
                comision_key=f"{mc}-001", nombre="Com 1", numero=num,
                cupo=30, coef_asignacion=1.0,
            ))
            session.add(HorarioDB(
                id=str(uuid.uuid4()), comision_id=cid, codigo_materia=mc,
                dia="Lunes", hora_inicio=time(8, 0), hora_fin=time(10, 0),
                tipo_clase="laboratorio",
            ))
        session.commit()

        r = check_factibilidad_estructural(session, "plan-1")
        # Dos horarios de lab simultáneos, 1 lab sólo → pigeonhole falla
        # (demanda 2 > oferta compatible 1).
        assert r.factible is False
        assert any(
            b.codigo_regla in ("compat-pigeonhole", "compat-hall")
            for b in r.bloqueos
        )


class TestR11PinManualIncompatible:

    def test_pin_manual_apuntando_a_aula_incompatible(self, session):
        _seed_plan_basico(session)
        # Agrego un aula tipo laboratorio y la pineo al horario teórico.
        session.add(AulaDB(
            id="a_lab", sede_id="S1", codigo_aula="A_LAB", nombre="A_LAB",
            capacidad=20, tipo="laboratorio",
        ))
        session.commit()
        hor = session.exec(select(HorarioDB)).first()
        hor.aula_id = "a_lab"
        hor.aula_asignada_manualmente = True
        session.add(hor)
        session.commit()

        r = check_factibilidad_estructural(session, "plan-1")
        assert any(b.codigo_regla == "R11" for b in r.bloqueos)


class TestPlanInexistente:

    def test_plan_no_existe(self, session):
        r = check_factibilidad_estructural(session, "no-existe")
        assert r.factible is False
        assert r.bloqueos[0].codigo_regla == "input"
