"""Tests para cronograma_validation_service.

Foco: que las "materias esperadas" salgan de DictadoDB activos del ciclo
(no del JOIN viejo contra PlanEstudioDB), y que la staleness considere
cambios en el set de dictados activos.
"""

import uuid
from datetime import date, time

import pytest
from sqlalchemy.pool import StaticPool
from sqlmodel import Session, SQLModel, create_engine, select

from src.database.models import (
    CarreraDB,
    CicloDB,
    CicloPlanVersionDB,
    MateriaDB,
    PlanCarreraVersionDB,
    PlanEstudioDB,
    ScheduleDB,
    ScheduleEntryDB,
)
from src.services.cronograma_validation_service import (
    is_validation_stale,
    persist_validation,
    validar_cronograma,
)
from src.services.dictado_service import (
    create_dictados_for_ciclo,
    get_dictados_for_ciclo,
    update_dictado,
)


# -----------------------------------------------------------------------------
# Fixtures
# -----------------------------------------------------------------------------

@pytest.fixture(name="engine")
def engine_fixture():
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    SQLModel.metadata.create_all(engine)
    return engine


@pytest.fixture(name="session")
def session_fixture(engine):
    with Session(engine) as session:
        yield session


@pytest.fixture
def setup_basic(session):
    """Carrera + plan version + 2 materias + ciclo con plan asignado."""
    carrera = CarreraDB(codigo="ING", nombre="Ingenieria")
    session.add(carrera)
    session.flush()

    pv = PlanCarreraVersionDB(
        id=str(uuid.uuid4()),
        carrera_codigo="ING",
        nombre="Plan Original",
        fecha_creacion=date(2025, 1, 1),
    )
    session.add(pv)
    session.flush()

    m1 = MateriaDB(
        codigo="MAT101", nombre="Calculo I",
        periodo="cuatrimestral", active=True, horas_semanales=6,
    )
    m2 = MateriaDB(
        codigo="FIS101", nombre="Fisica I",
        periodo="cuatrimestral", active=True, horas_semanales=6,
    )
    session.add_all([m1, m2])
    session.flush()

    for m in (m1, m2):
        session.add(PlanEstudioDB(
            plan_version_id=pv.id, materia_codigo=m.codigo,
            carrera_codigo="ING", anio_plan=1, cuatrimestre_plan="1C",
        ))

    ciclo = CicloDB(
        id="2025-1C", anio=2025, numero=1,
        fecha_inicio=date(2025, 3, 10), fecha_fin=date(2025, 7, 5),
    )
    session.add(ciclo)
    session.flush()
    session.add(CicloPlanVersionDB(ciclo_id=ciclo.id, plan_version_id=pv.id))
    session.commit()

    return {"ciclo": ciclo, "pv": pv, "m1": m1, "m2": m2}


def _make_schedule_with_entries(
    session: Session, ciclo_id: str, materia_codigos: list[str],
) -> ScheduleDB:
    sched = ScheduleDB(
        id=str(uuid.uuid4()), ciclo_id=ciclo_id,
        nombre="Test Schedule", fecha_upload=date(2025, 3, 1),
    )
    session.add(sched)
    session.flush()
    for mc in materia_codigos:
        session.add(ScheduleEntryDB(
            id=str(uuid.uuid4()), schedule_id=sched.id,
            codigo_materia=mc, dia="Lunes",
            hora_inicio=time(8, 0), hora_fin=time(11, 0),
            comision=1,
        ))
    session.commit()
    return sched


# -----------------------------------------------------------------------------
# Tests
# -----------------------------------------------------------------------------

class TestSinDictados:
    def test_validar_cronograma_sin_dictados_devuelve_error(
        self, session, setup_basic,
    ):
        """Si el ciclo no tiene dictados, el summary debe traer error
        poblado y no computar el resto."""
        ciclo = setup_basic["ciclo"]
        sched = _make_schedule_with_entries(session, ciclo.id, ["MAT101"])

        summary = validar_cronograma(session, sched.id, ciclo.id)

        assert summary.error is not None
        assert "dictados" in summary.error.lower()
        # No se debe haber computado nada del resumen
        assert summary.n_esperadas == 0
        assert summary.n_clases == 0


class TestEsperadas:
    def test_esperadas_incluye_solo_dictados_activos(
        self, session, setup_basic,
    ):
        """Toggle de activo=False excluye la materia de las esperadas."""
        ciclo = setup_basic["ciclo"]
        # Crear dictados para todas las materias del plan
        create_dictados_for_ciclo(session, ciclo.id)

        # Cronograma con MAT101 (FIS101 sin horarios)
        sched = _make_schedule_with_entries(session, ciclo.id, ["MAT101"])

        summary = validar_cronograma(session, sched.id, ciclo.id)
        assert summary.error is None
        assert summary.n_esperadas == 2  # ambas activas
        assert "MAT101" in summary.esperadas
        assert "FIS101" in summary.esperadas
        assert summary.n_faltantes == 1  # FIS101

        # Borrar el dictado de FIS101 → debe salir de esperadas
        # (semantica nueva: si no existe el dictado, no se dicta).
        from src.services.dictado_service import borrar_dictado_de_ciclo
        dictados = get_dictados_for_ciclo(session, ciclo.id)
        d_fis = next(d for d in dictados if d.materia_codigo == "FIS101")
        borrar_dictado_de_ciclo(session, ciclo.id, d_fis.id)

        summary2 = validar_cronograma(session, sched.id, ciclo.id)
        assert summary2.error is None
        assert summary2.n_esperadas == 1
        assert "FIS101" not in summary2.esperadas
        assert summary2.n_faltantes == 0


class TestFaltantes:
    def test_faltantes_referencia_dictado_codigo(
        self, session, setup_basic,
    ):
        """La razon de un faltante menciona el dictado_codigo."""
        ciclo = setup_basic["ciclo"]
        create_dictados_for_ciclo(session, ciclo.id)

        # Cronograma vacio → todas las materias son faltantes
        sched = _make_schedule_with_entries(session, ciclo.id, [])

        summary = validar_cronograma(session, sched.id, ciclo.id)
        assert summary.n_faltantes == 2

        # Verificar razon
        all_materias = [
            mf
            for grupo in summary.faltantes_por_carrera
            for mf in grupo["materias"]
        ]
        assert len(all_materias) == 2
        for mf in all_materias:
            assert "dictado_codigo" in mf
            # Cuatrimestral → "{materia}-2025-1C"
            assert mf["dictado_codigo"].endswith("-2025-1C")
            assert mf["dictado_codigo"] in mf["razon"]
            assert "sin horarios" in mf["razon"].lower()


class TestExcluirOptativas:
    def test_validar_cronograma_excluir_optativas(
        self, session, setup_basic,
    ):
        """Toggle exclude_optativas filtra SOLO optativas; las virtuales
        siguen contando en la cobertura."""
        ciclo = setup_basic["ciclo"]
        pv = setup_basic["pv"]

        # Marcar FIS101 como virtual (sigue contando)
        fis = setup_basic["m2"]
        fis.virtual = True
        session.add(fis)
        # Agregar materia OPTATIVA
        opt = MateriaDB(
            codigo="OPT101", nombre="Optativa I",
            periodo="cuatrimestral", active=True, horas_semanales=3,
        )
        session.add(opt)
        session.flush()
        session.add(PlanEstudioDB(
            plan_version_id=pv.id, materia_codigo="OPT101",
            carrera_codigo="ING", anio_plan=4, cuatrimestre_plan="1C",
            optativa=True,
        ))
        session.commit()

        create_dictados_for_ciclo(session, ciclo.id)
        sched = _make_schedule_with_entries(session, ciclo.id, ["MAT101"])

        # Sin toggle: 3 esperadas (MAT, FIS virtual, OPT)
        s_off = validar_cronograma(
            session, sched.id, ciclo.id, exclude_optativas=False,
        )
        assert s_off.error is None
        assert s_off.n_esperadas == 3
        assert s_off.excluir_optativas is False
        assert "OPT101" in s_off.esperadas
        assert "FIS101" in s_off.esperadas

        # Con toggle: OPT101 sale; FIS101 (virtual) sigue
        s_on = validar_cronograma(
            session, sched.id, ciclo.id, exclude_optativas=True,
        )
        assert s_on.error is None
        assert s_on.n_esperadas == 2
        assert s_on.excluir_optativas is True
        assert "OPT101" not in s_on.esperadas
        assert "FIS101" in s_on.esperadas


class TestStaleness:
    def test_is_validation_stale_por_cambio_de_dictados(
        self, session, setup_basic,
    ):
        """Si se desactiva un dictado, is_validation_stale = True
        aunque el entry_count del cronograma no haya cambiado."""
        ciclo = setup_basic["ciclo"]
        create_dictados_for_ciclo(session, ciclo.id)

        sched = _make_schedule_with_entries(session, ciclo.id, ["MAT101"])

        summary = validar_cronograma(session, sched.id, ciclo.id)
        record = persist_validation(session, summary)

        # Justo despues de validar, no debe ser stale.
        assert is_validation_stale(session, record) is False

        # Borrar un dictado → debe pasar a stale
        from src.services.dictado_service import borrar_dictado_de_ciclo
        dictados = get_dictados_for_ciclo(session, ciclo.id)
        d_fis = next(d for d in dictados if d.materia_codigo == "FIS101")
        borrar_dictado_de_ciclo(session, ciclo.id, d_fis.id)

        # Re-leer el record (la sesion puede haber cacheado)
        session.refresh(record)
        assert is_validation_stale(session, record) is True

    def test_is_validation_stale_por_cambio_de_entries(
        self, session, setup_basic,
    ):
        """Comportamiento heredado: cambio en entry_count tambien marca stale."""
        ciclo = setup_basic["ciclo"]
        create_dictados_for_ciclo(session, ciclo.id)

        sched = _make_schedule_with_entries(session, ciclo.id, ["MAT101"])
        summary = validar_cronograma(session, sched.id, ciclo.id)
        record = persist_validation(session, summary)

        assert is_validation_stale(session, record) is False

        # Agregar una entry → stale
        session.add(ScheduleEntryDB(
            id=str(uuid.uuid4()), schedule_id=sched.id,
            codigo_materia="FIS101", dia="Martes",
            hora_inicio=time(9, 0), hora_fin=time(11, 0),
            comision=1,
        ))
        session.commit()

        assert is_validation_stale(session, record) is True

    def test_is_validation_stale_por_cambio_de_contenido_mismo_count(
        self, session, setup_basic,
    ):
        """Regresion Fase A: mover una entry de dia (mismo count) tiene
        que disparar staleness. Antes solo se comparaba entry_count, asi
        que este caso pasaba desapercibido y el badge quedaba en verde
        con datos podridos.
        """
        ciclo = setup_basic["ciclo"]
        create_dictados_for_ciclo(session, ciclo.id)

        sched = _make_schedule_with_entries(session, ciclo.id, ["MAT101"])
        summary = validar_cronograma(session, sched.id, ciclo.id)
        record = persist_validation(session, summary)

        assert is_validation_stale(session, record) is False
        assert record.content_hash  # se persistio

        # Mover la entry de Lunes a Martes — mismo count, distinto contenido
        entry = session.exec(
            select(ScheduleEntryDB).where(ScheduleEntryDB.schedule_id == sched.id)
        ).first()
        assert entry is not None
        entry.dia = "Martes"
        session.add(entry)
        session.commit()

        assert is_validation_stale(session, record) is True

    def test_is_validation_stale_por_cambio_de_optativa_flag(
        self, session, setup_basic,
    ):
        """Regresion Fase A: cambiar PlanEstudioDB.optativa cambia el set
        esperado cuando el toggle esta ON, entonces tiene que disparar
        staleness. Antes solo counts entraban en la comparacion.
        """
        ciclo = setup_basic["ciclo"]
        create_dictados_for_ciclo(session, ciclo.id)

        sched = _make_schedule_with_entries(session, ciclo.id, ["MAT101"])
        summary = validar_cronograma(
            session, sched.id, ciclo.id, exclude_optativas=True,
        )
        record = persist_validation(session, summary)
        assert is_validation_stale(session, record) is False

        # Marcar FIS101 como optativa en PlanEstudio → cambia el set
        # esperado con toggle ON (pasa de 2 a 1 esperadas).
        pe = session.exec(
            select(PlanEstudioDB)
            .where(PlanEstudioDB.materia_codigo == "FIS101")
        ).first()
        assert pe is not None
        pe.optativa = True
        session.add(pe)
        session.commit()

        assert is_validation_stale(session, record) is True

    def test_is_validation_stale_fallback_snapshot_historico_sin_hash(
        self, session, setup_basic,
    ):
        """Fase A: snapshots viejos sin content_hash caen al comportamiento
        legado (comparacion por counts) para no romper la UI de historicos.
        """
        ciclo = setup_basic["ciclo"]
        create_dictados_for_ciclo(session, ciclo.id)

        sched = _make_schedule_with_entries(session, ciclo.id, ["MAT101"])
        summary = validar_cronograma(session, sched.id, ciclo.id)
        record = persist_validation(session, summary)

        # Simular snapshot historico: borrar el hash
        record.content_hash = ""
        session.add(record)
        session.commit()

        # Sin cambios reales, no debe ser stale (fallback: counts iguales)
        assert is_validation_stale(session, record) is False

        # Cambio que SI cambia el count → detecta stale por fallback
        session.add(ScheduleEntryDB(
            id=str(uuid.uuid4()), schedule_id=sched.id,
            codigo_materia="FIS101", dia="Miercoles",
            hora_inicio=time(9, 0), hora_fin=time(11, 0),
            comision=1,
        ))
        session.commit()
        assert is_validation_stale(session, record) is True


class TestBadgeUnificado:
    """Regresion Fase A: el badge de la Lista de Cronogramas y el wizard
    del Plan comparten la misma politica. Antes cada consumidor tenia una
    logica distinta — la Lista ignoraba n_conflictos_horarios y n_extra,
    el wizard ignoraba todo excepto staleness.
    """

    def test_badge_rojo_si_conflictos_horarios(self, session, setup_basic):
        """Un cronograma con conflictos horarios pero sin faltantes ni
        particion invalida tiene que dar badge 🔴, no 🟢.
        """
        from src.services.cronograma_validation_service import (
            compute_validation_status,
        )
        ciclo = setup_basic["ciclo"]
        create_dictados_for_ciclo(session, ciclo.id)

        sched = _make_schedule_with_entries(session, ciclo.id, ["MAT101"])
        summary = validar_cronograma(session, sched.id, ciclo.id)
        # Simular conflictos horarios detectados
        summary.n_conflictos_horarios = 2
        summary.n_faltantes = 0
        summary.particion_valid = True
        record = persist_validation(session, summary)
        assert record.n_conflictos_horarios == 2

        status = compute_validation_status(session, sched.id, ciclo.id)
        assert status.listo_para_plan is False
        assert "🔴" in status.badge
        assert any("conflicto" in p for p in status.problemas)

    def test_badge_rojo_si_extras(self, session, setup_basic):
        """Un cronograma con materias extras (sin dictado) tiene que dar 🔴."""
        from src.services.cronograma_validation_service import (
            compute_validation_status,
        )
        ciclo = setup_basic["ciclo"]
        create_dictados_for_ciclo(session, ciclo.id)

        sched = _make_schedule_with_entries(session, ciclo.id, ["MAT101"])
        summary = validar_cronograma(session, sched.id, ciclo.id)
        summary.n_extra = 1
        summary.n_faltantes = 0
        summary.particion_valid = True
        summary.n_conflictos_horarios = 0
        persist_validation(session, summary)

        status = compute_validation_status(session, sched.id, ciclo.id)
        assert status.listo_para_plan is False
        assert "🔴" in status.badge
        assert any("sin dictado" in p for p in status.problemas)

    def test_badge_verde_si_todo_ok(self, session, setup_basic):
        """Cronograma sin faltantes, sin conflictos, particion OK → 🟢."""
        from src.services.cronograma_validation_service import (
            compute_validation_status,
        )
        ciclo = setup_basic["ciclo"]
        create_dictados_for_ciclo(session, ciclo.id)

        # Dos entries en dias distintos para evitar conflicto intra-grupo
        # (ambas materias van a (ING, 1, 1C)).
        sched = ScheduleDB(
            id=str(uuid.uuid4()), ciclo_id=ciclo.id,
            nombre="ok", fecha_upload=date(2025, 3, 1),
        )
        session.add(sched)
        session.flush()
        session.add(ScheduleEntryDB(
            id=str(uuid.uuid4()), schedule_id=sched.id,
            codigo_materia="MAT101", dia="Lunes",
            hora_inicio=time(8, 0), hora_fin=time(11, 0),
        ))
        session.add(ScheduleEntryDB(
            id=str(uuid.uuid4()), schedule_id=sched.id,
            codigo_materia="FIS101", dia="Martes",
            hora_inicio=time(8, 0), hora_fin=time(11, 0),
        ))
        session.commit()

        summary = validar_cronograma(session, sched.id, ciclo.id)
        assert summary.n_faltantes == 0
        assert summary.n_conflictos_horarios == 0
        persist_validation(session, summary)

        status = compute_validation_status(session, sched.id, ciclo.id)
        assert status.listo_para_plan is True
        assert "🟢" in status.badge
        assert status.problemas == []

    def test_badge_amarillo_si_stale(self, session, setup_basic):
        """Snapshot stale → 🟡 aunque no haya problemas en el snapshot."""
        from src.services.cronograma_validation_service import (
            compute_validation_status,
        )
        ciclo = setup_basic["ciclo"]
        create_dictados_for_ciclo(session, ciclo.id)

        # Dos entries en dias distintos para evitar conflicto intra-grupo.
        sched = ScheduleDB(
            id=str(uuid.uuid4()), ciclo_id=ciclo.id,
            nombre="stale", fecha_upload=date(2025, 3, 1),
        )
        session.add(sched)
        session.flush()
        session.add(ScheduleEntryDB(
            id=str(uuid.uuid4()), schedule_id=sched.id,
            codigo_materia="MAT101", dia="Lunes",
            hora_inicio=time(8, 0), hora_fin=time(11, 0),
        ))
        session.add(ScheduleEntryDB(
            id=str(uuid.uuid4()), schedule_id=sched.id,
            codigo_materia="FIS101", dia="Martes",
            hora_inicio=time(8, 0), hora_fin=time(11, 0),
        ))
        session.commit()

        summary = validar_cronograma(session, sched.id, ciclo.id)
        persist_validation(session, summary)

        # Mutar el schedule → stale
        session.add(ScheduleEntryDB(
            id=str(uuid.uuid4()), schedule_id=sched.id,
            codigo_materia="MAT101", dia="Viernes",
            hora_inicio=time(14, 0), hora_fin=time(16, 0),
        ))
        session.commit()

        status = compute_validation_status(session, sched.id, ciclo.id)
        assert status.stale is True
        assert status.listo_para_plan is False
        assert "🟡" in status.badge

    def test_badge_gris_si_nunca_validado(self, session, setup_basic):
        """Sin validaciones persistidas → ⚪."""
        from src.services.cronograma_validation_service import (
            compute_validation_status,
        )
        ciclo = setup_basic["ciclo"]
        sched = _make_schedule_with_entries(session, ciclo.id, [])

        status = compute_validation_status(session, sched.id, ciclo.id)
        assert status.validation is None
        assert status.listo_para_plan is False
        assert "⚪" in status.badge


class TestHorariosVsConfig:
    """Fase H.1 del rediseño 2026-09-15: validar que los ScheduleEntryDB
    respeten `ConfiguracionHoraria` (día operativo, rango, granularidad).
    """

    def _crear_config(self, session, *, granularidad=15,
                       inicio=time(7, 0), fin=time(23, 0),
                       dias="Lunes,Martes,Miércoles,Jueves,Viernes,Sábado"):
        from src.database.models import ConfiguracionHoraria
        existing = session.exec(select(ConfiguracionHoraria).limit(1)).first()
        if existing is None:
            session.add(ConfiguracionHoraria(
                id=1,
                granularidad_minutos=granularidad,
                hora_inicio_operativo=inicio,
                hora_fin_operativo=fin,
                dias_operativos=dias,
            ))
        else:
            existing.granularidad_minutos = granularidad
            existing.hora_inicio_operativo = inicio
            existing.hora_fin_operativo = fin
            existing.dias_operativos = dias
            session.add(existing)
        session.commit()

    def test_todo_ok_no_reporta_nada(self, session, setup_basic):
        from src.services.validations import validar_horarios_vs_config
        self._crear_config(session)  # 15 min, 07:00-23:00, Lun-Sab
        ciclo = setup_basic["ciclo"]
        sched = _make_schedule_with_entries(session, ciclo.id, ["MAT101"])
        # La entry base es Lunes 8:00-11:00 → OK
        result = validar_horarios_vs_config(session, sched.id)
        assert result == []

    def test_dia_no_operativo(self, session, setup_basic):
        from src.services.validations import validar_horarios_vs_config
        self._crear_config(session, dias="Lunes,Martes,Miércoles,Jueves,Viernes")
        # Sábado excluido de dias operativos.
        ciclo = setup_basic["ciclo"]
        sched = ScheduleDB(
            id=str(uuid.uuid4()), ciclo_id=ciclo.id,
            nombre="t", fecha_upload=date(2025, 3, 1),
        )
        session.add(sched)
        session.flush()
        session.add(ScheduleEntryDB(
            id=str(uuid.uuid4()), schedule_id=sched.id,
            codigo_materia="MAT101", dia="Sábado",
            hora_inicio=time(8, 0), hora_fin=time(11, 0),
        ))
        session.commit()

        result = validar_horarios_vs_config(session, sched.id)
        assert len(result) == 1
        assert any("día" in r.lower() for r in result[0].razones)

    def test_hora_fuera_del_rango_operativo(self, session, setup_basic):
        from src.services.validations import validar_horarios_vs_config
        self._crear_config(session, inicio=time(8, 0), fin=time(20, 0))
        ciclo = setup_basic["ciclo"]
        sched = ScheduleDB(
            id=str(uuid.uuid4()), ciclo_id=ciclo.id,
            nombre="t", fecha_upload=date(2025, 3, 1),
        )
        session.add(sched)
        session.flush()
        # Antes de las 08:00
        session.add(ScheduleEntryDB(
            id=str(uuid.uuid4()), schedule_id=sched.id,
            codigo_materia="MAT101", dia="Lunes",
            hora_inicio=time(7, 0), hora_fin=time(10, 0),
        ))
        # Después de las 20:00
        session.add(ScheduleEntryDB(
            id=str(uuid.uuid4()), schedule_id=sched.id,
            codigo_materia="MAT101", dia="Lunes",
            hora_inicio=time(19, 0), hora_fin=time(21, 0),
        ))
        session.commit()

        result = validar_horarios_vs_config(session, sched.id)
        assert len(result) == 2
        razones_all = [r for row in result for r in row.razones]
        assert any("anterior al horario operativo" in r for r in razones_all)
        assert any("posterior al horario operativo" in r for r in razones_all)

    def test_granularidad_no_respetada(self, session, setup_basic):
        from src.services.validations import validar_horarios_vs_config
        self._crear_config(session, granularidad=15, inicio=time(7, 0))
        # 8:07 no es múltiplo de 15 desde 07:00 (offset 7 min).
        ciclo = setup_basic["ciclo"]
        sched = ScheduleDB(
            id=str(uuid.uuid4()), ciclo_id=ciclo.id,
            nombre="t", fecha_upload=date(2025, 3, 1),
        )
        session.add(sched)
        session.flush()
        session.add(ScheduleEntryDB(
            id=str(uuid.uuid4()), schedule_id=sched.id,
            codigo_materia="MAT101", dia="Lunes",
            hora_inicio=time(8, 7), hora_fin=time(10, 0),
        ))
        session.commit()

        result = validar_horarios_vs_config(session, sched.id)
        assert len(result) == 1
        assert any("granularidad" in r for r in result[0].razones)

    def test_granularidad_media_hora(self, session, setup_basic):
        """Con granularidad 30 min, 8:30 sí es válido, 8:15 no."""
        from src.services.validations import validar_horarios_vs_config
        self._crear_config(session, granularidad=30, inicio=time(7, 0))
        ciclo = setup_basic["ciclo"]
        sched = ScheduleDB(
            id=str(uuid.uuid4()), ciclo_id=ciclo.id,
            nombre="t", fecha_upload=date(2025, 3, 1),
        )
        session.add(sched)
        session.flush()
        # 8:30 OK
        session.add(ScheduleEntryDB(
            id=str(uuid.uuid4()), schedule_id=sched.id,
            codigo_materia="MAT101", dia="Lunes",
            hora_inicio=time(8, 30), hora_fin=time(10, 0),
        ))
        # 8:15 NO
        session.add(ScheduleEntryDB(
            id=str(uuid.uuid4()), schedule_id=sched.id,
            codigo_materia="MAT101", dia="Martes",
            hora_inicio=time(8, 15), hora_fin=time(10, 0),
        ))
        session.commit()

        result = validar_horarios_vs_config(session, sched.id)
        assert len(result) == 1
        assert result[0].dia == "Martes"

    def test_integracion_con_validar_cronograma(self, session, setup_basic):
        """`validar_cronograma` popula `n_horarios_fuera_config` y el
        detalle en `horarios_fuera_config`.
        """
        self._crear_config(session, granularidad=15, inicio=time(7, 0))
        ciclo = setup_basic["ciclo"]
        create_dictados_for_ciclo(session, ciclo.id)

        sched = ScheduleDB(
            id=str(uuid.uuid4()), ciclo_id=ciclo.id,
            nombre="t", fecha_upload=date(2025, 3, 1),
        )
        session.add(sched)
        session.flush()
        # Una fila OK y una rota.
        session.add(ScheduleEntryDB(
            id=str(uuid.uuid4()), schedule_id=sched.id,
            codigo_materia="MAT101", dia="Lunes",
            hora_inicio=time(8, 0), hora_fin=time(11, 0),
        ))
        session.add(ScheduleEntryDB(
            id=str(uuid.uuid4()), schedule_id=sched.id,
            codigo_materia="FIS101", dia="Martes",
            hora_inicio=time(8, 7), hora_fin=time(10, 0),  # granularidad rota
        ))
        session.commit()

        summary = validar_cronograma(session, sched.id, ciclo.id)
        assert summary.n_horarios_fuera_config == 1
        assert len(summary.horarios_fuera_config) == 1
        assert summary.horarios_fuera_config[0]["codigo_materia"] == "FIS101"

    def test_fuera_config_no_bloquea_listo_para_plan(
        self, session, setup_basic,
    ):
        """Bugfix task #342 (2026-09-22): `n_horarios_fuera_config` es
        un warning, no un bloqueante. Antes ponía el badge en 🔴 y
        `listo_para_plan=False`, contradiciendo la doc de Fase H.1.
        Ahora un cronograma con horarios fuera de config pero sin otros
        problemas debe quedar 🟢 listo para plan; la sección de config
        horaria de la UI sigue mostrando el warning con su botón
        "Ajustar automáticamente".
        """
        from src.services.cronograma_validation_service import (
            compute_validation_status,
        )
        self._crear_config(session, granularidad=15, inicio=time(7, 0))
        ciclo = setup_basic["ciclo"]
        create_dictados_for_ciclo(session, ciclo.id)

        sched = ScheduleDB(
            id=str(uuid.uuid4()), ciclo_id=ciclo.id,
            nombre="t", fecha_upload=date(2025, 3, 1),
        )
        session.add(sched)
        session.flush()
        session.add(ScheduleEntryDB(
            id=str(uuid.uuid4()), schedule_id=sched.id,
            codigo_materia="MAT101", dia="Lunes",
            hora_inicio=time(8, 0), hora_fin=time(11, 0),
        ))
        session.add(ScheduleEntryDB(
            id=str(uuid.uuid4()), schedule_id=sched.id,
            codigo_materia="FIS101", dia="Martes",
            hora_inicio=time(8, 7), hora_fin=time(10, 0),
        ))
        session.commit()

        summary = validar_cronograma(session, sched.id, ciclo.id)
        assert summary.n_horarios_fuera_config >= 1
        persist_validation(session, summary)

        status = compute_validation_status(session, sched.id, ciclo.id)
        # El horario fuera de config no bloquea el plan.
        assert status.listo_para_plan is True, (
            f"Con solo fuera-de-config debe estar listo. Problemas: "
            f"{status.problemas}"
        )
        assert not any(
            "fuera de la config" in p for p in status.problemas
        )
