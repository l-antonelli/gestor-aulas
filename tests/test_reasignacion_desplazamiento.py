"""Tests para la reasignación de aulas con desplazamiento.

Feature: al editar el aula de un horario, el usuario puede elegir un
aula ocupada (no sólo las libres) y decidir qué pasa con el horario
desplazado — swap, reasignar a otra libre o dejar sin aula.

Fuentes: `src/services/asignacion_aulas_service.py` (nuevos):
- `get_ocupante_de_aula_en_franja`
- `get_aulas_todas_para_horario`
- `preview_reasignacion_con_desplazamiento`
- `reasignar_con_desplazamiento`
"""

import uuid
from datetime import date, time

import pytest
from sqlalchemy.pool import StaticPool
from sqlmodel import Session, SQLModel, create_engine, select

from src.database.models import (
    AulaDB,
    CicloDB,
    ComisionDB,
    DictadoCicloDB,
    DictadoDB,
    HorarioDB,
    InscripcionHistoricaDB,
    MateriaDB,
    MateriaLaboratorioDB,
    PlanificacionCursadaDB,
    SedeDB,
)
from src.services.asignacion_aulas_service import (
    AulaCandidata,
    PreviewReasignacion,
    get_aulas_todas_para_horario,
    get_ocupante_de_aula_en_franja,
    preview_reasignacion_con_desplazamiento,
    reasignar_con_desplazamiento,
)


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


def _seed_dos_horarios_dos_aulas(session: Session):
    """Escenario base:
    - Ciclo + Plan.
    - Sede S1.
    - Aulas: A1, A2, A3, LAB1 (laboratorio).
    - Materia MAT + comisión + horario Lu 14-16 (teórica) → aula A1.
    - Materia FIS + comisión + horario Lu 14-16 (teórica) → aula A2.

    Devuelve dict con refs por nombre.
    """
    ciclo = CicloDB(
        id="2026-1C", anio=2026, numero=1,
        fecha_inicio=date(2026, 3, 9), fecha_fin=date(2026, 7, 3),
    )
    plan = PlanificacionCursadaDB(
        id="plan-1", nombre="Plan Test", ciclo_id="2026-1C",
    )
    sede = SedeDB(id="S1", nombre="Sede Test")
    session.add_all([ciclo, plan, sede])

    for m in ("MAT", "FIS"):
        session.add(MateriaDB(
            codigo=m, nombre=f"Materia {m}",
            horas_semanales=2, horas_teoria=2, horas_laboratorio=0,
        ))
        session.add(DictadoDB(
            id=f"dict-{m}", materia_codigo=m,
            dictado_codigo=f"{m}-2026-1C",
        ))
        session.add(DictadoCicloDB(dictado_id=f"dict-{m}", ciclo_id="2026-1C"))

    session.add(AulaDB(id="A1", sede_id="S1", codigo_aula="A1", nombre="Aula 1", capacidad=30, tipo="teorica"))
    session.add(AulaDB(id="A2", sede_id="S1", codigo_aula="A2", nombre="Aula 2", capacidad=30, tipo="teorica"))
    session.add(AulaDB(id="A3", sede_id="S1", codigo_aula="A3", nombre="Aula 3", capacidad=30, tipo="teorica"))
    session.add(AulaDB(id="LAB1", sede_id="S1", codigo_aula="LAB1", nombre="Lab 1", capacidad=20, tipo="laboratorio"))

    session.commit()

    com_mat_id = str(uuid.uuid4())
    hor_mat_id = str(uuid.uuid4())
    session.add(ComisionDB(
        id=com_mat_id, materia_codigo="MAT",
        plan_cursada_id="plan-1", comision_key="MAT-001",
        nombre="Comisión 1", numero=1, cupo=30,
    ))
    session.add(HorarioDB(
        id=hor_mat_id, comision_id=com_mat_id, codigo_materia="MAT",
        dia="Lunes", hora_inicio=time(14, 0), hora_fin=time(16, 0),
        tipo_clase="teorica", aula_id="A1",
    ))

    com_fis_id = str(uuid.uuid4())
    hor_fis_id = str(uuid.uuid4())
    session.add(ComisionDB(
        id=com_fis_id, materia_codigo="FIS",
        plan_cursada_id="plan-1", comision_key="FIS-001",
        nombre="Comisión 1", numero=1, cupo=30,
    ))
    session.add(HorarioDB(
        id=hor_fis_id, comision_id=com_fis_id, codigo_materia="FIS",
        dia="Lunes", hora_inicio=time(14, 0), hora_fin=time(16, 0),
        tipo_clase="teorica", aula_id="A2",
    ))
    session.commit()

    return {
        "hor_mat": hor_mat_id,
        "hor_fis": hor_fis_id,
        "com_mat": com_mat_id,
        "com_fis": com_fis_id,
    }


# =============================================================================
# get_ocupante_de_aula_en_franja
# =============================================================================

class TestGetOcupante:

    def test_aula_libre_devuelve_none(self, session):
        refs = _seed_dos_horarios_dos_aulas(session)
        # A3 no está usada por nadie
        oc = get_ocupante_de_aula_en_franja(
            session, "plan-1", refs["hor_mat"], "A3",
        )
        assert oc is None

    def test_aula_ocupada_por_franja_identica(self, session):
        refs = _seed_dos_horarios_dos_aulas(session)
        # A2 está usada por FIS en Lu 14-16 (misma franja que MAT)
        oc = get_ocupante_de_aula_en_franja(
            session, "plan-1", refs["hor_mat"], "A2",
        )
        assert oc is not None
        assert oc.id == refs["hor_fis"]

    def test_aula_ocupada_por_franja_diferente_devuelve_none(self, session):
        """Si el aula está ocupada pero por un horario con franja
        parcial (no idéntica), no permite swap directo → devolvemos
        None (equivalente a 'no aplica swap simple')."""
        refs = _seed_dos_horarios_dos_aulas(session)
        # Agrego otro horario FIS2 en Lu 15-17 usando A3 (franja parcial vs MAT)
        com_id = str(uuid.uuid4())
        session.add(ComisionDB(
            id=com_id, materia_codigo="FIS",
            plan_cursada_id="plan-1", comision_key="FIS-002",
            nombre="Comisión 2", numero=2, cupo=30,
        ))
        session.add(HorarioDB(
            id="h-otro", comision_id=com_id, codigo_materia="FIS",
            dia="Lunes", hora_inicio=time(15, 0), hora_fin=time(17, 0),
            tipo_clase="teorica", aula_id="A3",
        ))
        session.commit()

        oc = get_ocupante_de_aula_en_franja(
            session, "plan-1", refs["hor_mat"], "A3",
        )
        assert oc is None

    def test_aula_ocupada_por_el_propio_horario_devuelve_none(self, session):
        """El horario que se edita no puede ser su propio ocupante."""
        refs = _seed_dos_horarios_dos_aulas(session)
        # MAT ya tiene A1, ver A1 desde el mismo horario no debería
        # marcarlo como ocupante.
        oc = get_ocupante_de_aula_en_franja(
            session, "plan-1", refs["hor_mat"], "A1",
        )
        assert oc is None


# =============================================================================
# get_aulas_todas_para_horario
# =============================================================================

class TestGetAulasTodas:

    def test_devuelve_libres_y_ocupadas_con_metadata(self, session):
        refs = _seed_dos_horarios_dos_aulas(session)
        # Para MAT (Lu 14-16, teórica): A1 (propio), A2 (ocupada FIS),
        # A3 (libre), LAB1 no matchea porque MAT no está en
        # MateriaLaboratorioDB y el tipo es teórica → LAB1 filtrada por tipo.
        cands = get_aulas_todas_para_horario(
            session, "plan-1", refs["hor_mat"],
        )
        # LAB1 no debería aparecer (es laboratorio, MAT es teórica)
        aulas_ids = {c.aula.id for c in cands}
        assert "LAB1" not in aulas_ids
        # A1 (actual), A2 (ocupada), A3 (libre) sí
        assert aulas_ids == {"A1", "A2", "A3"}

        # Verifico metadata
        by_id = {c.aula.id: c for c in cands}
        assert by_id["A2"].libre_en_franja is False
        assert by_id["A2"].ocupante is not None
        assert by_id["A2"].ocupante.id == refs["hor_fis"]
        assert by_id["A2"].ocupante_franja_identica is True

        assert by_id["A3"].libre_en_franja is True
        assert by_id["A3"].ocupante is None

    def test_aula_actual_es_libre_en_su_franja(self, session):
        """El aula actualmente asignada al horario que se edita se
        reporta como 'libre en franja' — porque desde su propio punto
        de vista, no hay choque."""
        refs = _seed_dos_horarios_dos_aulas(session)
        cands = get_aulas_todas_para_horario(
            session, "plan-1", refs["hor_mat"],
        )
        by_id = {c.aula.id: c for c in cands}
        assert by_id["A1"].libre_en_franja is True
        assert by_id["A1"].ocupante is None


# =============================================================================
# preview_reasignacion_con_desplazamiento
# =============================================================================

class TestPreviewReasignacion:

    def test_libre_es_asignacion_directa(self, session):
        refs = _seed_dos_horarios_dos_aulas(session)
        prev = preview_reasignacion_con_desplazamiento(
            session, "plan-1", refs["hor_mat"], "A3",
            accion="libre",
        )
        assert prev.editado_ok is True
        assert prev.editado_aula_futura == "A3"
        assert prev.desplazado_horario_id is None
        # No persiste
        h = session.get(HorarioDB, refs["hor_mat"])
        assert h.aula_id == "A1"

    def test_swap_valida_ambas_direcciones(self, session):
        refs = _seed_dos_horarios_dos_aulas(session)
        prev = preview_reasignacion_con_desplazamiento(
            session, "plan-1", refs["hor_mat"], "A2",
            accion="swap",
        )
        # MAT → A2, FIS → A1
        assert prev.editado_ok is True
        assert prev.editado_aula_futura == "A2"
        assert prev.desplazado_horario_id == refs["hor_fis"]
        assert prev.desplazado_aula_futura == "A1"
        assert prev.desplazado_ok is True
        # No persiste
        h = session.get(HorarioDB, refs["hor_mat"])
        assert h.aula_id == "A1"

    def test_reassign_valida_ambas(self, session):
        refs = _seed_dos_horarios_dos_aulas(session)
        prev = preview_reasignacion_con_desplazamiento(
            session, "plan-1", refs["hor_mat"], "A2",
            accion="reassign",
            aula_para_desplazado="A3",
        )
        assert prev.editado_ok is True
        assert prev.editado_aula_futura == "A2"
        assert prev.desplazado_aula_futura == "A3"
        assert prev.desplazado_ok is True

    def test_unassign_deja_desplazado_sin_aula(self, session):
        refs = _seed_dos_horarios_dos_aulas(session)
        prev = preview_reasignacion_con_desplazamiento(
            session, "plan-1", refs["hor_mat"], "A2",
            accion="unassign",
        )
        assert prev.editado_ok is True
        assert prev.editado_aula_futura == "A2"
        assert prev.desplazado_horario_id == refs["hor_fis"]
        assert prev.desplazado_aula_futura is None
        assert prev.desplazado_ok is True

    def test_swap_bloquea_si_desplazado_queda_incompat_tipo(self, session):
        """Si el aula original del editado no matchea el tipo del
        desplazado, el swap debería fallar (bloquear)."""
        refs = _seed_dos_horarios_dos_aulas(session)
        # Cambio FIS a laboratorio y compatible sólo con LAB1
        h_fis = session.get(HorarioDB, refs["hor_fis"])
        h_fis.tipo_clase = "laboratorio"
        session.add(h_fis)
        session.add(MateriaLaboratorioDB(materia_codigo="FIS", aula_id="LAB1"))
        session.commit()

        # Ahora MAT quiere pasar a A2. Pero eso empuja FIS a A1 (teórica).
        # FIS es laboratorio → A1 no lo cubre. Swap debería fallar.
        prev = preview_reasignacion_con_desplazamiento(
            session, "plan-1", refs["hor_mat"], "A2",
            accion="swap",
        )
        assert prev.editado_ok is False or prev.desplazado_ok is False
        assert any(
            "laboratorio" in e.lower() or "no admite" in e.lower()
            for e in prev.errores
        )


# =============================================================================
# reasignar_con_desplazamiento (persistencia)
# =============================================================================

class TestReasignarPersistencia:

    def test_swap_persiste_ambos(self, session):
        refs = _seed_dos_horarios_dos_aulas(session)
        res = reasignar_con_desplazamiento(
            session, "plan-1", refs["hor_mat"], "A2",
            accion="swap",
        )
        assert res.ok is True

        # MAT ahora tiene A2, FIS ahora tiene A1
        h_mat = session.get(HorarioDB, refs["hor_mat"])
        h_fis = session.get(HorarioDB, refs["hor_fis"])
        assert h_mat.aula_id == "A2"
        assert h_fis.aula_id == "A1"

    def test_reassign_persiste_ambos(self, session):
        refs = _seed_dos_horarios_dos_aulas(session)
        res = reasignar_con_desplazamiento(
            session, "plan-1", refs["hor_mat"], "A2",
            accion="reassign",
            aula_para_desplazado="A3",
        )
        assert res.ok is True
        h_mat = session.get(HorarioDB, refs["hor_mat"])
        h_fis = session.get(HorarioDB, refs["hor_fis"])
        assert h_mat.aula_id == "A2"
        assert h_fis.aula_id == "A3"

    def test_unassign_persiste_ambos(self, session):
        refs = _seed_dos_horarios_dos_aulas(session)
        res = reasignar_con_desplazamiento(
            session, "plan-1", refs["hor_mat"], "A2",
            accion="unassign",
        )
        assert res.ok is True
        h_mat = session.get(HorarioDB, refs["hor_mat"])
        h_fis = session.get(HorarioDB, refs["hor_fis"])
        assert h_mat.aula_id == "A2"
        assert h_fis.aula_id is None

    def test_libre_equivalente_a_cambiar_directo(self, session):
        refs = _seed_dos_horarios_dos_aulas(session)
        res = reasignar_con_desplazamiento(
            session, "plan-1", refs["hor_mat"], "A3",
            accion="libre",
        )
        assert res.ok is True
        h_mat = session.get(HorarioDB, refs["hor_mat"])
        h_fis = session.get(HorarioDB, refs["hor_fis"])
        assert h_mat.aula_id == "A3"
        # FIS no se toca
        assert h_fis.aula_id == "A2"

    def test_falla_no_persiste_nada(self, session):
        refs = _seed_dos_horarios_dos_aulas(session)
        # Fuerzo el caso del test anterior: FIS es lab, A1 no lo cubre
        h_fis = session.get(HorarioDB, refs["hor_fis"])
        h_fis.tipo_clase = "laboratorio"
        session.add(h_fis)
        session.add(MateriaLaboratorioDB(materia_codigo="FIS", aula_id="LAB1"))
        session.commit()

        res = reasignar_con_desplazamiento(
            session, "plan-1", refs["hor_mat"], "A2",
            accion="swap",
        )
        assert res.ok is False
        # Nada se persistió — MAT sigue en A1, FIS sigue en A2
        h_mat = session.get(HorarioDB, refs["hor_mat"])
        h_fis = session.get(HorarioDB, refs["hor_fis"])
        assert h_mat.aula_id == "A1"
        assert h_fis.aula_id == "A2"


class TestReasignarValidaciones:

    def test_accion_invalida(self, session):
        refs = _seed_dos_horarios_dos_aulas(session)
        with pytest.raises(ValueError, match="accion"):
            reasignar_con_desplazamiento(
                session, "plan-1", refs["hor_mat"], "A2",
                accion="chachacha",  # type: ignore[arg-type]
            )

    def test_swap_sin_ocupante_falla(self, session):
        refs = _seed_dos_horarios_dos_aulas(session)
        # A3 está libre — swap no aplica
        res = reasignar_con_desplazamiento(
            session, "plan-1", refs["hor_mat"], "A3",
            accion="swap",
        )
        assert res.ok is False
        assert any("no hay ocupante" in e.lower() or "libre" in e.lower()
                   for e in res.errores)

    def test_reassign_sin_aula_para_desplazado_falla(self, session):
        refs = _seed_dos_horarios_dos_aulas(session)
        with pytest.raises(ValueError, match="aula_para_desplazado"):
            reasignar_con_desplazamiento(
                session, "plan-1", refs["hor_mat"], "A2",
                accion="reassign",
                aula_para_desplazado=None,
            )

    def test_reassign_a_misma_aula_que_editado_falla(self, session):
        """No tiene sentido reasignar el desplazado al aula original
        del editado y NO hacer swap — sería equivalente a swap, hay que
        pedir swap. Fail seguro."""
        refs = _seed_dos_horarios_dos_aulas(session)
        # aula_para_desplazado=A1 (la del editado) con accion=reassign
        # es semánticamente igual a swap. Lo forzamos a que use swap.
        res = reasignar_con_desplazamiento(
            session, "plan-1", refs["hor_mat"], "A2",
            accion="reassign",
            aula_para_desplazado="A1",
        )
        # Aceptamos que devuelva ok=False con mensaje o que igual haga
        # el swap correctamente. Lo importante: no debe romper.
        # Elegimos exigir: si el aula_para_desplazado coincide con la
        # aula original del editado, exigir accion="swap" y bloquear.
        assert res.ok is False
        assert any("swap" in e.lower() for e in res.errores)
