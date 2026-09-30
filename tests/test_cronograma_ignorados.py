"""Tests de los conflictos ignorados a nivel cronograma (2026-09-30).

Hasta ahora sólo el plan de cursada podía marcar un par de materias
como "conflicto ignorado" (`IgnoredConflictDB`, RF-PLAN-08). El
cronograma no tenía dónde guardarlos, así que en la pestaña Validar
del módulo Cronogramas un conflicto conocido y aceptado (por ejemplo
materias homónimas de años distintos) bloqueaba el plan sin remedio.
`ScheduleIgnoredConflictDB` cubre ese hueco con la misma semántica:
granularidad por par, par ordenado lexicográficamente, razón libre.
"""

from __future__ import annotations

import uuid
from datetime import date

from sqlmodel import select

from src.database.models import PlanEstudioDB, ScheduleDB, ScheduleIgnoredConflictDB
from src.services.cronograma_validation_service import (
    add_ignored_pair_cronograma,
    compute_validation_status,
    conflictos_por_materia_cronograma,
    get_ignored_pairs_cronograma,
    get_latest_validation,
    is_validation_stale,
    list_ignored_conflicts_cronograma,
    persist_validation,
    remove_ignored_pair_cronograma,
    validar_cronograma,
)
from src.services.dictado_service import (
    create_dictados_for_ciclo,
    has_dictados_for_ciclo,
)
from tests.test_cronograma_validation_service import (  # noqa: F401 (fixtures)
    _make_schedule_with_entries,
    engine_fixture,
    session_fixture,
    setup_basic,
)


def _crono_en_conflicto(session, setup_basic):
    """MAT101 y FIS101, mismo grupo (ING 1° 1C), ambas lunes 8-11.
    Crea los dictados del ciclo (sin ellos `validar_cronograma` corta
    con error antes de calcular conflictos)."""
    if not has_dictados_for_ciclo(session, setup_basic["ciclo"].id):
        create_dictados_for_ciclo(session, setup_basic["ciclo"].id)
    return _make_schedule_with_entries(
        session, setup_basic["ciclo"].id, ["MAT101", "FIS101"],
    )


class TestCrudIgnorados:
    def test_agregar_normaliza_el_orden_del_par(self, session, setup_basic):
        sched = _crono_en_conflicto(session, setup_basic)
        add_ignored_pair_cronograma(
            session, sched.id, "MAT101", "FIS101", razon="homónimas",
        )
        assert get_ignored_pairs_cronograma(session, sched.id) == {
            ("FIS101", "MAT101"),
        }
        rec = session.get(
            ScheduleIgnoredConflictDB, (sched.id, "FIS101", "MAT101"),
        )
        assert rec.razon == "homónimas"

    def test_agregar_dos_veces_no_duplica_y_actualiza_razon(
        self, session, setup_basic,
    ):
        sched = _crono_en_conflicto(session, setup_basic)
        add_ignored_pair_cronograma(session, sched.id, "FIS101", "MAT101")
        add_ignored_pair_cronograma(
            session, sched.id, "MAT101", "FIS101", razon="nueva",
        )
        filas = session.exec(select(ScheduleIgnoredConflictDB)).all()
        assert len(filas) == 1
        assert filas[0].razon == "nueva"

    def test_quitar(self, session, setup_basic):
        sched = _crono_en_conflicto(session, setup_basic)
        add_ignored_pair_cronograma(session, sched.id, "FIS101", "MAT101")
        assert remove_ignored_pair_cronograma(
            session, sched.id, "MAT101", "FIS101",
        ) is True
        assert get_ignored_pairs_cronograma(session, sched.id) == set()
        assert remove_ignored_pair_cronograma(
            session, sched.id, "MAT101", "FIS101",
        ) is False


class TestValidacionConIgnorados:
    def test_sin_ignorar_el_conflicto_bloquea(self, session, setup_basic):
        sched = _crono_en_conflicto(session, setup_basic)
        summary = validar_cronograma(session, sched.id, setup_basic["ciclo"].id)
        assert summary.n_conflictos_horarios == 1
        assert summary.conflictos_ignorados == []

    def test_conflicto_ignorado_no_cuenta_y_se_lista_aparte(
        self, session, setup_basic,
    ):
        sched = _crono_en_conflicto(session, setup_basic)
        add_ignored_pair_cronograma(session, sched.id, "FIS101", "MAT101")

        summary = validar_cronograma(session, sched.id, setup_basic["ciclo"].id)

        assert summary.n_conflictos_horarios == 0
        assert summary.conflictos_horarios == []
        assert summary.n_conflictos_ignorados == 1
        (c,) = summary.conflictos_ignorados
        assert {c["materia_a"], c["materia_b"]} == {"FIS101", "MAT101"}

    def test_conflicto_ignorado_no_bloquea_el_plan(self, session, setup_basic):
        sched = _crono_en_conflicto(session, setup_basic)
        ciclo_id = setup_basic["ciclo"].id
        persist_validation(session, validar_cronograma(session, sched.id, ciclo_id))
        assert any(
            "conflictos de horario" in p
            for p in compute_validation_status(session, sched.id, ciclo_id).problemas
        )

        add_ignored_pair_cronograma(session, sched.id, "FIS101", "MAT101")
        persist_validation(session, validar_cronograma(session, sched.id, ciclo_id))
        status = compute_validation_status(session, sched.id, ciclo_id)
        assert not any("conflictos de horario" in p for p in status.problemas)

    def test_ignorar_vuelve_stale_la_validacion(self, session, setup_basic):
        """Ignorar o dejar de ignorar cambia el resultado: la última
        validación persistida tiene que marcarse desactualizada."""
        sched = _crono_en_conflicto(session, setup_basic)
        ciclo_id = setup_basic["ciclo"].id
        persist_validation(session, validar_cronograma(session, sched.id, ciclo_id))
        latest = get_latest_validation(session, sched.id, ciclo_id)
        assert latest is not None
        assert is_validation_stale(session, latest) is False

        add_ignored_pair_cronograma(session, sched.id, "FIS101", "MAT101")
        assert is_validation_stale(session, latest) is True

    def test_ver_editar_no_muestra_el_ignorado(self, session, setup_basic):
        sched = _crono_en_conflicto(session, setup_basic)
        add_ignored_pair_cronograma(session, sched.id, "FIS101", "MAT101")
        assert conflictos_por_materia_cronograma(session, sched.id) == {}


class TestLimpiezaDeIgnoradosStale:
    def test_par_que_ya_no_comparte_grupo_se_elimina(self, session, setup_basic):
        """Misma regla que RF-PLAN-09: si las dos materias dejan de
        convivir en algún grupo curricular del ciclo, la excepción ya no
        se aplica a nada y se limpia al validar (reportándolo)."""
        sched = _crono_en_conflicto(session, setup_basic)
        add_ignored_pair_cronograma(
            session, sched.id, "FIS101", "MAT101", razon="vieja",
        )
        pe = session.exec(
            select(PlanEstudioDB).where(PlanEstudioDB.materia_codigo == "FIS101")
        ).one()
        pe.anio_plan = 2
        session.add(pe)
        session.commit()

        summary = validar_cronograma(session, sched.id, setup_basic["ciclo"].id)

        assert get_ignored_pairs_cronograma(session, sched.id) == set()
        assert summary.excepciones_stale_removidas == [{
            "materia_a": "FIS101", "materia_b": "MAT101", "razon": "vieja",
        }]


class TestShadowUsaLosIgnoradosDelDestino:
    def test_preview_del_importer_respeta_ignorados_del_destino(
        self, session, setup_basic,
    ):
        """La vista previa del importer valida un shadow; los ignorados
        viven en el cronograma destino (el shadow se descarta al
        confirmar), así que la validación del shadow tiene que leerlos
        del destino."""
        destino = _crono_en_conflicto(session, setup_basic)
        add_ignored_pair_cronograma(session, destino.id, "FIS101", "MAT101")
        shadow = _crono_en_conflicto(session, setup_basic)
        shadow.es_shadow_import = True
        shadow.shadow_target_schedule_id = destino.id
        session.add(shadow)
        session.commit()

        summary = validar_cronograma(session, shadow.id, setup_basic["ciclo"].id)

        assert summary.n_conflictos_horarios == 0
        assert summary.n_conflictos_ignorados == 1
        assert conflictos_por_materia_cronograma(session, shadow.id) == {}


def test_cronograma_sin_ignorados_no_tiene_filas(session):
    sched = ScheduleDB(
        id=str(uuid.uuid4()), ciclo_id=None,
        nombre="x", fecha_upload=date(2025, 3, 1),
    )
    session.add(sched)
    session.commit()
    assert get_ignored_pairs_cronograma(session, sched.id) == set()


class TestCicloDeVida:
    """Los ignorados acompañan al cronograma: se heredan al generar un
    plan (decisión 2026-09-29), se copian al duplicar el cronograma o
    al clonar un plan a cronograma, y se borran con él."""

    def _plan_desde(self, session, sched, ciclo_id):
        from src.services.plan_generation_service import (
            generate_plan_from_preview,
            preview_plan_from_schedule,
        )

        preview = preview_plan_from_schedule(session, sched.id)
        result = generate_plan_from_preview(
            session, sched.id, "Plan test", ciclo_id, preview.materias,
        )
        assert result.plan is not None
        return result.plan

    def test_generar_plan_hereda_los_ignorados(self, session, setup_basic):
        from src.database.models import IgnoredConflictDB

        sched = _crono_en_conflicto(session, setup_basic)
        add_ignored_pair_cronograma(
            session, sched.id, "FIS101", "MAT101", razon="homónimas",
        )
        plan = self._plan_desde(session, sched, setup_basic["ciclo"].id)

        filas = session.exec(
            select(IgnoredConflictDB)
            .where(IgnoredConflictDB.plan_cursada_id == plan.id)
        ).all()
        assert [(f.materia_a, f.materia_b, f.razon) for f in filas] == [
            ("FIS101", "MAT101", "homónimas"),
        ]

    def test_generate_plan_from_schedule_tambien_hereda(
        self, session, setup_basic,
    ):
        from src.services.plan_generation_service import (
            generate_plan_from_schedule,
        )
        from src.services.plan_validation_service import get_ignored_pairs

        sched = _crono_en_conflicto(session, setup_basic)
        add_ignored_pair_cronograma(session, sched.id, "FIS101", "MAT101")
        result = generate_plan_from_schedule(
            session, sched.id, "Plan", setup_basic["ciclo"].id,
        )
        assert get_ignored_pairs(session, result.plan.id) == {
            ("FIS101", "MAT101"),
        }

    def test_duplicar_cronograma_copia_los_ignorados(self, session, setup_basic):
        from src.services.schedule_service import duplicate_schedule

        sched = _crono_en_conflicto(session, setup_basic)
        add_ignored_pair_cronograma(
            session, sched.id, "FIS101", "MAT101", razon="r",
        )
        copia = duplicate_schedule(session, sched.id, "Copia")
        assert get_ignored_pairs_cronograma(session, copia.id) == {
            ("FIS101", "MAT101"),
        }

    def test_clonar_plan_a_cronograma_copia_los_ignorados_del_plan(
        self, session, setup_basic,
    ):
        from src.services.plan_validation_service import add_ignored_pair
        from src.services.schedule_service import clonar_plan_a_cronograma

        sched = _crono_en_conflicto(session, setup_basic)
        plan = self._plan_desde(session, sched, setup_basic["ciclo"].id)
        add_ignored_pair(session, plan.id, "MAT101", "FIS101", razon="del plan")

        nuevo = clonar_plan_a_cronograma(session, plan.id, "Desde plan")

        (fila,) = list_ignored_conflicts_cronograma(session, nuevo.id)
        assert (fila.materia_a, fila.materia_b, fila.razon) == (
            "FIS101", "MAT101", "del plan",
        )

    def test_borrar_cronograma_borra_sus_ignorados(self, session, setup_basic):
        from src.services.schedule_service import delete_schedule

        sched = _crono_en_conflicto(session, setup_basic)
        add_ignored_pair_cronograma(session, sched.id, "FIS101", "MAT101")
        delete_schedule(session, sched.id)
        assert session.exec(select(ScheduleIgnoredConflictDB)).all() == []


class TestHallazgosRevision:
    """Hallazgos de la revisión de código 2026-09-30."""

    def test_ignorar_desbloquea_tambien_el_camino_de_cursada(
        self, session, setup_basic,
    ):
        """El chequeo de camino de cursada del cronograma tiene que
        saltear los pares ignorados, igual que el del plan: si no, el
        plan sigue bloqueado por 'bloqueos de camino de cursada'."""
        sched = _crono_en_conflicto(session, setup_basic)
        ciclo_id = setup_basic["ciclo"].id
        assert validar_cronograma(session, sched.id, ciclo_id).n_camino_bloqueos >= 1

        add_ignored_pair_cronograma(session, sched.id, "FIS101", "MAT101")
        summary = validar_cronograma(session, sched.id, ciclo_id)

        assert summary.n_camino_bloqueos == 0
        persist_validation(session, summary)
        status = compute_validation_status(session, sched.id, ciclo_id)
        assert not any("camino" in p for p in status.problemas)

    def test_ignorado_con_optativa_no_se_limpia_como_obsoleto(
        self, session, setup_basic,
    ):
        """La detección de conflictos incluye optativas; la limpieza de
        ignorados obsoletos tiene que usar los mismos grupos."""
        pe = session.exec(
            select(PlanEstudioDB).where(PlanEstudioDB.materia_codigo == "FIS101")
        ).one()
        pe.optativa = True
        session.add(pe)
        session.commit()
        sched = _crono_en_conflicto(session, setup_basic)
        add_ignored_pair_cronograma(session, sched.id, "FIS101", "MAT101")

        summary = validar_cronograma(session, sched.id, setup_basic["ciclo"].id)

        assert summary.excepciones_stale_removidas == []
        assert get_ignored_pairs_cronograma(session, sched.id) == {
            ("FIS101", "MAT101"),
        }

    def test_validar_un_shadow_no_modifica_los_ignorados_del_destino(
        self, session, setup_basic,
    ):
        """La vista previa del importer no puede tocar datos reales:
        validar el shadow no ejecuta la limpieza sobre el destino."""
        destino = _crono_en_conflicto(session, setup_basic)
        add_ignored_pair_cronograma(session, destino.id, "FIS101", "MAT101")
        pe = session.exec(
            select(PlanEstudioDB).where(PlanEstudioDB.materia_codigo == "FIS101")
        ).one()
        pe.anio_plan = 2  # el par deja de convivir: quedaría obsoleto
        session.add(pe)
        session.commit()
        shadow = _crono_en_conflicto(session, setup_basic)
        shadow.es_shadow_import = True
        shadow.shadow_target_schedule_id = destino.id
        session.add(shadow)
        session.commit()

        validar_cronograma(session, shadow.id, setup_basic["ciclo"].id)

        assert session.get(
            ScheduleIgnoredConflictDB, (destino.id, "FIS101", "MAT101"),
        ) is not None


def test_plan_ignorado_con_optativa_no_se_limpia(session, setup_basic):
    """Mismo defecto en el plan (helper compartido
    `grupos_curriculares_activos`)."""
    from src.services.plan_validation_service import (
        add_ignored_pair,
        cleanup_stale_ignored_pairs,
        get_ignored_pairs,
    )

    sched = _crono_en_conflicto(session, setup_basic)
    plan = TestCicloDeVida()._plan_desde(session, sched, setup_basic["ciclo"].id)
    pe = session.exec(
        select(PlanEstudioDB).where(PlanEstudioDB.materia_codigo == "FIS101")
    ).one()
    pe.optativa = True
    session.add(pe)
    session.commit()
    add_ignored_pair(session, plan.id, "FIS101", "MAT101")

    assert cleanup_stale_ignored_pairs(session, plan.id) == []
    assert get_ignored_pairs(session, plan.id) == {("FIS101", "MAT101")}
