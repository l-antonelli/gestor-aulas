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
    NodoCascada,
    PlanEjecucion,
    PreviewReasignacion,
    aplicar_cascada,
    get_aulas_todas_para_horario,
    get_horarios_afectados,
    get_ocupante_de_aula_en_franja,
    preview_reasignacion_con_desplazamiento,
    reasignar_con_desplazamiento,
    solapamiento_franjas,
    tipo_solapamiento,
    validar_y_planificar_cascada,
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


# =============================================================================
# Fase A1: AulaCandidata.ocupantes (lista) + get_horarios_afectados
# =============================================================================

def _seed_multi_ocupantes(session: Session):
    """Escenario: MAT Lu 8-11 (edito este), aula X ocupada por FIS Lu
    8-10 y QUI Lu 9-11 (dos horarios que solapan parcialmente con MAT).

    - Aula X (donde queremos poner MAT).
    - Aula Y libre.
    - Aula Z ocupada por BIO Lu 8-11 (franja idéntica a MAT).
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
    for m in ("MAT", "FIS", "QUI", "BIO"):
        session.add(MateriaDB(
            codigo=m, nombre=f"Materia {m}",
            horas_semanales=3, horas_teoria=3, horas_laboratorio=0,
        ))
        session.add(DictadoDB(
            id=f"dict-{m}", materia_codigo=m,
            dictado_codigo=f"{m}-2026-1C",
        ))
        session.add(DictadoCicloDB(dictado_id=f"dict-{m}", ciclo_id="2026-1C"))
    for aid in ("X", "Y", "Z"):
        session.add(AulaDB(
            id=aid, sede_id="S1", codigo_aula=aid, nombre=f"Aula {aid}",
            capacidad=30, tipo="teorica",
        ))
    session.commit()

    # MAT Lu 8-11 en Y (donde está)
    com_mat = str(uuid.uuid4())
    hor_mat = str(uuid.uuid4())
    session.add(ComisionDB(
        id=com_mat, materia_codigo="MAT",
        plan_cursada_id="plan-1", comision_key="MAT-001",
        nombre="Comisión 1", numero=1, cupo=30,
    ))
    session.add(HorarioDB(
        id=hor_mat, comision_id=com_mat, codigo_materia="MAT",
        dia="Lunes", hora_inicio=time(8, 0), hora_fin=time(11, 0),
        tipo_clase="teorica", aula_id="Y",
    ))

    # FIS Lu 8-10 en X
    com_fis = str(uuid.uuid4())
    hor_fis = str(uuid.uuid4())
    session.add(ComisionDB(
        id=com_fis, materia_codigo="FIS",
        plan_cursada_id="plan-1", comision_key="FIS-001",
        nombre="Comisión 1", numero=1, cupo=30,
    ))
    session.add(HorarioDB(
        id=hor_fis, comision_id=com_fis, codigo_materia="FIS",
        dia="Lunes", hora_inicio=time(8, 0), hora_fin=time(10, 0),
        tipo_clase="teorica", aula_id="X",
    ))

    # QUI Lu 9-11 en X (parcial vs MAT y contigua con FIS)
    com_qui = str(uuid.uuid4())
    hor_qui = str(uuid.uuid4())
    session.add(ComisionDB(
        id=com_qui, materia_codigo="QUI",
        plan_cursada_id="plan-1", comision_key="QUI-001",
        nombre="Comisión 1", numero=1, cupo=30,
    ))
    session.add(HorarioDB(
        id=hor_qui, comision_id=com_qui, codigo_materia="QUI",
        dia="Lunes", hora_inicio=time(9, 0), hora_fin=time(11, 0),
        tipo_clase="teorica", aula_id="X",
    ))

    # BIO Lu 8-11 en Z (franja idéntica a MAT)
    com_bio = str(uuid.uuid4())
    hor_bio = str(uuid.uuid4())
    session.add(ComisionDB(
        id=com_bio, materia_codigo="BIO",
        plan_cursada_id="plan-1", comision_key="BIO-001",
        nombre="Comisión 1", numero=1, cupo=30,
    ))
    session.add(HorarioDB(
        id=hor_bio, comision_id=com_bio, codigo_materia="BIO",
        dia="Lunes", hora_inicio=time(8, 0), hora_fin=time(11, 0),
        tipo_clase="teorica", aula_id="Z",
    ))

    session.commit()
    return {
        "hor_mat": hor_mat, "hor_fis": hor_fis,
        "hor_qui": hor_qui, "hor_bio": hor_bio,
    }


class TestAulaCandidataOcupantesList:
    """Nuevo campo AulaCandidata.ocupantes: contiene TODOS los horarios
    que solapan con la franja del editado en esa aula (no solo el de
    franja idéntica). Base para la lógica de cascada."""

    def test_aula_libre_ocupantes_vacio(self, session):
        refs = _seed_multi_ocupantes(session)
        cands = get_aulas_todas_para_horario(
            session, "plan-1", refs["hor_mat"],
        )
        by_id = {c.aula.id: c for c in cands}
        # Y es la propia aula del editado — vacía.
        assert by_id["Y"].ocupantes == []
        assert by_id["Y"].libre_en_franja is True

    def test_aula_con_dos_solapamientos_parciales(self, session):
        refs = _seed_multi_ocupantes(session)
        cands = get_aulas_todas_para_horario(
            session, "plan-1", refs["hor_mat"],
        )
        by_id = {c.aula.id: c for c in cands}
        # X tiene FIS Lu 8-10 y QUI Lu 9-11 (ambos solapan con MAT Lu 8-11)
        oc_ids = {oc.id for oc in by_id["X"].ocupantes}
        assert oc_ids == {refs["hor_fis"], refs["hor_qui"]}
        # Ninguno tiene franja idéntica a MAT (Lu 8-11)
        assert by_id["X"].ocupante_franja_identica is False
        assert by_id["X"].ocupante is None  # API vieja: sólo franja idéntica
        assert by_id["X"].libre_en_franja is False

    def test_aula_con_ocupante_identico(self, session):
        refs = _seed_multi_ocupantes(session)
        cands = get_aulas_todas_para_horario(
            session, "plan-1", refs["hor_mat"],
        )
        by_id = {c.aula.id: c for c in cands}
        # Z tiene BIO Lu 8-11 (franja idéntica)
        assert len(by_id["Z"].ocupantes) == 1
        assert by_id["Z"].ocupantes[0].id == refs["hor_bio"]
        assert by_id["Z"].ocupante_franja_identica is True
        assert by_id["Z"].ocupante is not None
        assert by_id["Z"].ocupante.id == refs["hor_bio"]


class TestGetHorariosAfectados:
    """get_horarios_afectados debe devolver TODOS los horarios que
    solapan (incluye franja idéntica, contenida, contenedora y
    parcialmente superpuesta)."""

    def test_aula_libre_devuelve_lista_vacia(self, session):
        refs = _seed_multi_ocupantes(session)
        afectados = get_horarios_afectados(
            session, "plan-1", refs["hor_mat"], "Y",
        )
        # Y es la propia aula del editado, otros horarios en Y = ninguno
        assert afectados == []

    def test_aula_con_dos_parciales(self, session):
        refs = _seed_multi_ocupantes(session)
        afectados = get_horarios_afectados(
            session, "plan-1", refs["hor_mat"], "X",
        )
        ids = {h.id for h in afectados}
        assert ids == {refs["hor_fis"], refs["hor_qui"]}

    def test_aula_con_franja_identica(self, session):
        refs = _seed_multi_ocupantes(session)
        afectados = get_horarios_afectados(
            session, "plan-1", refs["hor_mat"], "Z",
        )
        assert len(afectados) == 1
        assert afectados[0].id == refs["hor_bio"]

    def test_no_incluye_horario_propio(self, session):
        refs = _seed_multi_ocupantes(session)
        # MAT en Y con franja Lu 8-11 — si preguntamos por Y desde el
        # propio MAT, no debería salir MAT.
        afectados = get_horarios_afectados(
            session, "plan-1", refs["hor_mat"], "Y",
        )
        assert refs["hor_mat"] not in {h.id for h in afectados}

    def test_horarios_de_otro_plan_no_aparecen(self, session):
        refs = _seed_multi_ocupantes(session)
        # Creo otro plan con un horario en X. No debe aparecer.
        plan2 = PlanificacionCursadaDB(
            id="plan-2", nombre="Otro plan", ciclo_id="2026-1C",
        )
        session.add(plan2)
        com_x = str(uuid.uuid4())
        session.add(ComisionDB(
            id=com_x, materia_codigo="FIS",
            plan_cursada_id="plan-2", comision_key="FIS-plan2",
            nombre="Otra", numero=1, cupo=30,
        ))
        session.add(HorarioDB(
            id="h-p2", comision_id=com_x, codigo_materia="FIS",
            dia="Lunes", hora_inicio=time(8, 0), hora_fin=time(10, 0),
            tipo_clase="teorica", aula_id="X",
        ))
        session.commit()

        afectados = get_horarios_afectados(
            session, "plan-1", refs["hor_mat"], "X",
        )
        # Solo FIS y QUI del plan-1
        assert "h-p2" not in {h.id for h in afectados}


class TestSolapamientoHelpers:
    """Helpers de cálculo de solapamiento entre franjas."""

    def test_franjas_identicas(self):
        rango = solapamiento_franjas(
            "Lunes", time(8, 0), time(11, 0),
            "Lunes", time(8, 0), time(11, 0),
        )
        assert rango == (time(8, 0), time(11, 0))
        assert tipo_solapamiento(
            "Lunes", time(8, 0), time(11, 0),
            "Lunes", time(8, 0), time(11, 0),
        ) == "identico"

    def test_franja_parcial(self):
        rango = solapamiento_franjas(
            "Lunes", time(8, 0), time(11, 0),
            "Lunes", time(10, 0), time(13, 0),
        )
        assert rango == (time(10, 0), time(11, 0))
        assert tipo_solapamiento(
            "Lunes", time(8, 0), time(11, 0),
            "Lunes", time(10, 0), time(13, 0),
        ) == "parcial"

    def test_franja_contenida(self):
        # 9-10 dentro de 8-11
        rango = solapamiento_franjas(
            "Lunes", time(8, 0), time(11, 0),
            "Lunes", time(9, 0), time(10, 0),
        )
        assert rango == (time(9, 0), time(10, 0))
        # 9-10 no es idéntico a 8-11, por lo tanto parcial
        assert tipo_solapamiento(
            "Lunes", time(8, 0), time(11, 0),
            "Lunes", time(9, 0), time(10, 0),
        ) == "parcial"

    def test_franjas_disjuntas(self):
        # 8-10 y 10-12 son contiguas pero no solapan (rango semi-abierto)
        rango = solapamiento_franjas(
            "Lunes", time(8, 0), time(10, 0),
            "Lunes", time(10, 0), time(12, 0),
        )
        assert rango is None
        assert tipo_solapamiento(
            "Lunes", time(8, 0), time(10, 0),
            "Lunes", time(10, 0), time(12, 0),
        ) == "sin_solape"

    def test_dias_distintos(self):
        rango = solapamiento_franjas(
            "Lunes", time(8, 0), time(11, 0),
            "Martes", time(8, 0), time(11, 0),
        )
        assert rango is None
        assert tipo_solapamiento(
            "Lunes", time(8, 0), time(11, 0),
            "Martes", time(8, 0), time(11, 0),
        ) == "sin_solape"


# =============================================================================
# Fase A2: NodoCascada + validar_y_planificar_cascada + aplicar_cascada
# =============================================================================

class TestValidarYPlanificarCascada:

    def test_cascada_trivial_editado_a_aula_libre(self, session):
        refs = _seed_multi_ocupantes(session)
        cascada = NodoCascada(
            horario_id=refs["hor_mat"],
            aula_elegida="Y",  # ya está en Y, "libre" desde su propia
            accion="libre",
        )
        plan = validar_y_planificar_cascada(session, "plan-1", cascada)
        assert plan.ok is True
        assert len(plan.efectos) == 1
        assert plan.efectos[0].horario_id == refs["hor_mat"]
        assert plan.efectos[0].aula_futura == "Y"
        assert plan.efectos[0].nivel == 0

    def test_cascada_reassign_a_aula_con_un_ocupante_parcial(self, session):
        """MAT (Lu 8-11) va a X, que tiene FIS (Lu 8-10) parcial. Un
        solo hijo bajo la raíz. FIS se manda a "sin_aula"."""
        refs = _seed_multi_ocupantes(session)
        # Sólo tomo el ocupante FIS para simplificar el ejemplo (QUI se
        # ignora por ahora — la UI iterará ambos).
        cascada = NodoCascada(
            horario_id=refs["hor_mat"],
            aula_elegida="X",
            accion="reassign",
            hijos=[
                NodoCascada(
                    horario_id=refs["hor_fis"],
                    aula_elegida=None,
                    accion="sin_aula",
                ),
            ],
        )
        plan = validar_y_planificar_cascada(session, "plan-1", cascada)
        assert plan.ok is True
        assert len(plan.efectos) == 2
        # Raíz
        raiz = plan.efectos[0]
        assert raiz.horario_id == refs["hor_mat"]
        assert raiz.aula_futura == "X"
        # Hijo
        hijo = plan.efectos[1]
        assert hijo.horario_id == refs["hor_fis"]
        assert hijo.aula_futura is None
        assert hijo.nivel == 1
        # Warning por franja parcial
        assert hijo.tipo_solapamiento_con_padre == "parcial"
        assert hijo.solapamiento_con_padre is not None
        assert any("parcial" in w.lower() for w in hijo.warnings)

    def test_cascada_reassign_a_aula_libre_no_dispara_hijos(self, session):
        """Reasignar FIS a un aula libre (Y no está usada porque MAT
        se movió). El hijo no tiene sub-hijos."""
        refs = _seed_multi_ocupantes(session)
        cascada = NodoCascada(
            horario_id=refs["hor_mat"],
            aula_elegida="X",
            accion="reassign",
            hijos=[
                NodoCascada(
                    horario_id=refs["hor_fis"],
                    aula_elegida="Y",  # asumo libre porque MAT se movió
                    accion="reassign",
                ),
            ],
        )
        plan = validar_y_planificar_cascada(session, "plan-1", cascada)
        assert plan.ok is True
        efectos_por_id = {e.horario_id: e for e in plan.efectos}
        assert efectos_por_id[refs["hor_fis"]].aula_futura == "Y"
        assert efectos_por_id[refs["hor_fis"]].ok is True

    def test_cascada_profundidad_dos_niveles(self, session):
        """MAT→X (parcial FIS), FIS→Z (idéntico BIO), BIO→Y."""
        refs = _seed_multi_ocupantes(session)
        cascada = NodoCascada(
            horario_id=refs["hor_mat"],
            aula_elegida="X",
            accion="reassign",
            hijos=[
                NodoCascada(
                    horario_id=refs["hor_fis"],
                    aula_elegida="Z",
                    accion="reassign",
                    hijos=[
                        NodoCascada(
                            horario_id=refs["hor_bio"],
                            aula_elegida="Y",
                            accion="reassign",
                        ),
                    ],
                ),
            ],
        )
        plan = validar_y_planificar_cascada(session, "plan-1", cascada)
        assert plan.ok is True
        assert len(plan.efectos) == 3
        assert plan.efectos[0].nivel == 0
        assert plan.efectos[1].nivel == 1
        assert plan.efectos[2].nivel == 2

    def test_ciclo_directo_es_bloqueado(self, session):
        """A→B, B→A: ciclo de 2 pasos."""
        refs = _seed_multi_ocupantes(session)
        cascada = NodoCascada(
            horario_id=refs["hor_mat"],
            aula_elegida="X",
            accion="reassign",
            hijos=[
                NodoCascada(
                    horario_id=refs["hor_fis"],
                    aula_elegida="Y",
                    accion="reassign",
                    hijos=[
                        # Ciclo: MAT vuelve a aparecer
                        NodoCascada(
                            horario_id=refs["hor_mat"],
                            aula_elegida="X",
                            accion="reassign",
                        ),
                    ],
                ),
            ],
        )
        plan = validar_y_planificar_cascada(session, "plan-1", cascada)
        assert plan.ok is False
        assert any("ciclo" in e.lower() for e in plan.errores_globales)

    def test_swap_en_nivel_interno_falla(self, session):
        """Swap sólo válido en raíz."""
        refs = _seed_multi_ocupantes(session)
        cascada = NodoCascada(
            horario_id=refs["hor_mat"],
            aula_elegida="X",
            accion="reassign",
            hijos=[
                NodoCascada(
                    horario_id=refs["hor_fis"],
                    aula_elegida="Y",
                    accion="swap",  # inválido en nivel > 0
                ),
            ],
        )
        plan = validar_y_planificar_cascada(session, "plan-1", cascada)
        assert plan.ok is False
        efectos_por_id = {e.horario_id: e for e in plan.efectos}
        assert not efectos_por_id[refs["hor_fis"]].ok
        assert any(
            "swap" in err.lower() and "raíz" in err.lower()
            for err in efectos_por_id[refs["hor_fis"]].errores
        )

    def test_incompatibilidad_tipo_bloquea(self, session):
        """FIS marcada laboratorio compatible sólo con LAB1. Al asignarle
        Y (teórica), el efecto es not ok."""
        refs = _seed_multi_ocupantes(session)
        # Convierto FIS en laboratorio con lab compatible LAB1 (que no
        # existe todavía en este fixture — la agrego)
        session.add(AulaDB(
            id="LAB1", sede_id="S1", codigo_aula="LAB1", nombre="Lab 1",
            capacidad=20, tipo="laboratorio",
        ))
        h_fis = session.get(HorarioDB, refs["hor_fis"])
        h_fis.tipo_clase = "laboratorio"
        session.add(h_fis)
        session.add(MateriaLaboratorioDB(materia_codigo="FIS", aula_id="LAB1"))
        session.commit()

        cascada = NodoCascada(
            horario_id=refs["hor_mat"],
            aula_elegida="X",
            accion="reassign",
            hijos=[
                NodoCascada(
                    horario_id=refs["hor_fis"],
                    aula_elegida="Y",  # teórica, no lab
                    accion="reassign",
                ),
            ],
        )
        plan = validar_y_planificar_cascada(session, "plan-1", cascada)
        assert plan.ok is False


class TestAplicarCascada:

    def test_aplicar_simple_editado_a_aula_libre(self, session):
        refs = _seed_multi_ocupantes(session)
        cascada = NodoCascada(
            horario_id=refs["hor_mat"],
            aula_elegida="X",
            accion="reassign",
            hijos=[
                NodoCascada(
                    horario_id=refs["hor_fis"],
                    aula_elegida="Y",
                    accion="reassign",
                ),
                NodoCascada(
                    horario_id=refs["hor_qui"],
                    aula_elegida=None,
                    accion="sin_aula",
                ),
            ],
        )
        res = aplicar_cascada(session, "plan-1", cascada)
        assert res.ok is True
        assert session.get(HorarioDB, refs["hor_mat"]).aula_id == "X"
        assert session.get(HorarioDB, refs["hor_fis"]).aula_id == "Y"
        assert session.get(HorarioDB, refs["hor_qui"]).aula_id is None

    def test_aplicar_cascada_de_dos_niveles(self, session):
        refs = _seed_multi_ocupantes(session)
        cascada = NodoCascada(
            horario_id=refs["hor_mat"],
            aula_elegida="X",
            accion="reassign",
            hijos=[
                NodoCascada(
                    horario_id=refs["hor_fis"],
                    aula_elegida="Z",
                    accion="reassign",
                    hijos=[
                        NodoCascada(
                            horario_id=refs["hor_bio"],
                            aula_elegida="Y",
                            accion="reassign",
                        ),
                    ],
                ),
                NodoCascada(
                    horario_id=refs["hor_qui"],
                    aula_elegida=None,
                    accion="sin_aula",
                ),
            ],
        )
        res = aplicar_cascada(session, "plan-1", cascada)
        assert res.ok is True
        assert session.get(HorarioDB, refs["hor_mat"]).aula_id == "X"
        assert session.get(HorarioDB, refs["hor_fis"]).aula_id == "Z"
        assert session.get(HorarioDB, refs["hor_bio"]).aula_id == "Y"
        assert session.get(HorarioDB, refs["hor_qui"]).aula_id is None

    def test_rollback_completo_si_falla(self, session):
        """Si algún efecto falla, ningún horario debería quedar
        modificado (rollback)."""
        refs = _seed_multi_ocupantes(session)
        # Guardo estado original
        mat_orig = session.get(HorarioDB, refs["hor_mat"]).aula_id
        fis_orig = session.get(HorarioDB, refs["hor_fis"]).aula_id
        bio_orig = session.get(HorarioDB, refs["hor_bio"]).aula_id

        # Fabrico un caso que valide OK pero falle en aplicación:
        # convierto BIO en laboratorio SIN aula compatible → la validación
        # inicial ya lo detecta y devuelve error.
        h_bio = session.get(HorarioDB, refs["hor_bio"])
        h_bio.tipo_clase = "laboratorio"
        session.add(h_bio)
        session.commit()

        cascada = NodoCascada(
            horario_id=refs["hor_mat"],
            aula_elegida="X",
            accion="reassign",
            hijos=[
                NodoCascada(
                    horario_id=refs["hor_fis"],
                    aula_elegida="Z",
                    accion="reassign",
                    hijos=[
                        NodoCascada(
                            horario_id=refs["hor_bio"],
                            aula_elegida="Y",  # teórica, BIO ya no matchea
                            accion="reassign",
                        ),
                    ],
                ),
            ],
        )
        res = aplicar_cascada(session, "plan-1", cascada)
        assert res.ok is False
        # Nada cambió
        assert session.get(HorarioDB, refs["hor_mat"]).aula_id == mat_orig
        assert session.get(HorarioDB, refs["hor_fis"]).aula_id == fis_orig
        assert session.get(HorarioDB, refs["hor_bio"]).aula_id == bio_orig

    def test_ciclo_bloquea_aplicacion(self, session):
        refs = _seed_multi_ocupantes(session)
        cascada = NodoCascada(
            horario_id=refs["hor_mat"],
            aula_elegida="X",
            accion="reassign",
            hijos=[
                NodoCascada(
                    horario_id=refs["hor_fis"],
                    aula_elegida="Y",
                    accion="reassign",
                    hijos=[
                        NodoCascada(
                            horario_id=refs["hor_mat"],
                            aula_elegida="X",
                            accion="reassign",
                        ),
                    ],
                ),
            ],
        )
        res = aplicar_cascada(session, "plan-1", cascada)
        assert res.ok is False
        assert any("ciclo" in e.lower() for e in res.errores)
