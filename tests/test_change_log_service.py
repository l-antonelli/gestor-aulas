"""Tests para change_log_service (Fase 3).

Cubre:
- Hooks automaticos: alta, edicion (con campo tracked), baja.
- Filtro por campos: cambios en campos no-trackeados no generan log.
- Bridges (DictadoCicloDB): solo alta/baja, sin updates.
- emit_event explicito con reason/origin.
- change_context: propaga origin/reason a los hooks automaticos.
- Query helpers: get_log_for_entity, get_recent_log.
"""

import json

import pytest
from sqlalchemy.pool import StaticPool
from sqlmodel import Session, SQLModel, create_engine

# El import fuerza el registro de hooks antes de create_all.
from src.services import change_log_service  # noqa: F401
from src.services.change_log_service import (
    change_context,
    emit_event,
    get_log_for_entity,
    get_recent_log,
)
from src.database.models import (
    CarreraDB,
    ChangeLogDB,
    ComisionDB,
    DictadoCicloDB,
    DictadoDB,
    CicloDB,
    HorarioDB,
    MateriaDB,
    PlanificacionCursadaDB,
    ScheduleDB,
    ScheduleEntryDB,
    SedeDB,
)


@pytest.fixture(name="session")
def session_fixture():
    from datetime import date
    eng = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    SQLModel.metadata.create_all(eng)
    with Session(eng) as s:
        yield s


class TestHooksAutomaticos:

    def test_alta_materia_genera_created(self, session):
        m = MateriaDB(codigo="M1", nombre="Mat 1")
        session.add(m)
        session.commit()

        log = get_log_for_entity(session, "MateriaDB", "M1")
        assert len(log) == 1
        assert log[0].action == "created"
        assert log[0].entity_label == "M1 - Mat 1"
        assert log[0].field is None

    def test_edicion_campo_trackeado_genera_updated(self, session):
        m = MateriaDB(codigo="M1", nombre="Mat 1", virtual=False)
        session.add(m)
        session.commit()

        # Cambiar virtual → debe generar 1 log de "updated".
        m.virtual = True
        session.add(m)
        session.commit()

        log = get_log_for_entity(session, "MateriaDB", "M1")
        # Uno para el created + uno para el updated.
        assert len(log) == 2
        # El mas reciente primero.
        updated = log[0]
        assert updated.action == "updated"
        assert updated.field == "virtual"
        # `old_value` puede ser None cuando SQLAlchemy no tiene el
        # valor previo cargado en memoria (history.deleted vacio).
        # Lo importante es que `new_value` refleje el cambio.
        assert json.loads(updated.new_value) is True

    def test_edicion_campo_no_trackeado_no_genera_log(self, session):
        m = MateriaDB(codigo="M1", nombre="Mat 1")
        session.add(m)
        session.commit()

        # `nombre` no esta en la whitelist de trackeados.
        m.nombre = "Mat 1 modificada"
        session.add(m)
        session.commit()

        log = get_log_for_entity(session, "MateriaDB", "M1")
        assert len(log) == 1  # solo el created

    def test_baja_materia_genera_deleted(self, session):
        m = MateriaDB(codigo="M1", nombre="Mat 1")
        session.add(m)
        session.commit()
        session.delete(m)
        session.commit()

        log = get_log_for_entity(session, "MateriaDB", "M1")
        # created + deleted
        assert len(log) == 2
        assert log[0].action == "deleted"
        # Se preserva el label aunque la entidad ya no exista.
        assert log[0].entity_label == "M1 - Mat 1"

    def test_edicion_dicta_recursado_materia(self, session):
        m = MateriaDB(codigo="M1", nombre="Mat 1", dicta_recursado=None)
        session.add(m)
        session.commit()
        m.dicta_recursado = True
        session.add(m)
        session.commit()

        log = get_log_for_entity(session, "MateriaDB", "M1")
        updated = log[0]
        assert updated.field == "dicta_recursado"
        assert json.loads(updated.new_value) is True

    def test_edicion_dicta_recursado_carrera(self, session):
        c = CarreraDB(codigo="ING", nombre="Ing", dicta_recursado=True)
        session.add(c)
        session.commit()
        c.dicta_recursado = False
        session.add(c)
        session.commit()

        log = get_log_for_entity(session, "CarreraDB", "ING")
        assert len(log) == 2
        updated = log[0]
        assert updated.field == "dicta_recursado"

    def test_alta_dictado(self, session):
        m = MateriaDB(codigo="M1", nombre="Mat 1")
        session.add(m)
        session.commit()
        d = DictadoDB(
            id="d1", materia_codigo="M1", dictado_codigo="M1-2025-1C",
        )
        session.add(d)
        session.commit()

        log = get_log_for_entity(session, "DictadoDB", "d1")
        assert len(log) == 1
        assert log[0].action == "created"

    def test_bridge_dictado_ciclo_solo_alta_baja(self, session):
        """DictadoCicloDB tiene fields=None: no genera updates."""
        from datetime import date
        m = MateriaDB(codigo="M1", nombre="Mat 1")
        session.add(m)
        c = CicloDB(
            id="2025-1C", anio=2025, numero=1,
            fecha_inicio=date(2025, 3, 1), fecha_fin=date(2025, 7, 1),
        )
        session.add(c)
        d = DictadoDB(id="d1", materia_codigo="M1", dictado_codigo="M1-1C")
        session.add(d)
        session.commit()
        b = DictadoCicloDB(dictado_id="d1", ciclo_id="2025-1C")
        session.add(b)
        session.commit()

        log = get_log_for_entity(session, "DictadoCicloDB", "d1+2025-1C")
        assert len(log) == 1
        assert log[0].action == "created"


class TestEmitEvent:

    def test_emit_event_explicito(self, session):
        m = MateriaDB(codigo="M1", nombre="Mat 1")
        session.add(m)
        session.commit()

        # Emitir un evento adicional con reason.
        emit_event(
            session,
            entity_type="MateriaDB",
            entity_id="M1",
            entity_label="M1 - Mat 1",
            action="updated",
            field="dicta_recursado",
            old_value=None,
            new_value=True,
            reason="Promovido a regla desde el ciclo 2025-1C",
            origin="ui:ciclos",
        )
        session.commit()

        log = get_log_for_entity(session, "MateriaDB", "M1")
        # created (hook) + emitido explicito
        assert len(log) == 2
        emitted = log[0]
        assert emitted.reason.startswith("Promovido")
        assert emitted.origin == "ui:ciclos"

    def test_emit_event_accion_invalida_raises(self, session):
        with pytest.raises(ValueError, match="Action invalida"):
            emit_event(
                session, entity_type="MateriaDB", entity_id="X",
                action="foo",
            )


class TestChangeContext:

    def test_propaga_origin_y_reason_a_hook(self, session):
        with change_context(origin="ui:ciclos", reason="cambio de politica"):
            m = MateriaDB(codigo="M1", nombre="Mat 1")
            session.add(m)
            session.commit()

        log = get_log_for_entity(session, "MateriaDB", "M1")
        assert log[0].origin == "ui:ciclos"
        assert log[0].reason == "cambio de politica"

    def test_restaura_defaults_al_salir(self, session):
        with change_context(origin="ui:foo", reason="X"):
            m1 = MateriaDB(codigo="M1", nombre="Mat 1")
            session.add(m1)
            session.commit()
        # Fuera del context, otro cambio no hereda origin/reason.
        m2 = MateriaDB(codigo="M2", nombre="Mat 2")
        session.add(m2)
        session.commit()

        log2 = get_log_for_entity(session, "MateriaDB", "M2")
        assert log2[0].origin == "auto"
        assert log2[0].reason == ""


class TestQueryHelpers:

    def test_get_recent_log_orden_descendente(self, session):
        # Crear 3 materias.
        for i in range(3):
            session.add(MateriaDB(codigo=f"M{i}", nombre=f"Mat {i}"))
            session.commit()

        recent = get_recent_log(session, limit=100)
        # 3 filas, mas reciente primero.
        assert len(recent) == 3
        codes_in_order = [e.entity_id for e in recent]
        assert codes_in_order == ["M2", "M1", "M0"]

    def test_get_recent_log_filtro_por_entity_type(self, session):
        session.add(MateriaDB(codigo="M1", nombre="Mat 1"))
        session.add(CarreraDB(codigo="ING", nombre="Ing"))
        session.commit()

        recent = get_recent_log(session, entity_types=["MateriaDB"])
        assert len(recent) == 1
        assert recent[0].entity_type == "MateriaDB"

    def test_get_log_for_entity_limit(self, session):
        m = MateriaDB(codigo="M1", nombre="Mat 1")
        session.add(m)
        session.commit()
        for i in range(5):
            m.virtual = i % 2 == 0
            session.add(m)
            session.commit()

        log = get_log_for_entity(session, "MateriaDB", "M1", limit=3)
        assert len(log) == 3


class TestNuevasEntidadesDelPlan:
    """Fase 1 del tracker de plan: HorarioDB, ComisionDB,
    PlanificacionCursadaDB, ScheduleDB, ScheduleEntryDB. Estas
    entidades pertenecen a la superficie 'nivel plan' (o pre-plan,
    en el caso de los schedules) y son el foco de la auditoría
    manual iterada. Los cambios masivos del LP quedan fuera del
    scope de esta fase (se atienden por rollup vía LPRunDB).
    """

    def _seed_plan_completo(self, session):
        """Setup mínimo para tests: ciclo + materia + plan + comisión
        + horario + schedule + entry. Devuelve refs para tocar en
        los tests. Después de este setup, cada entidad ya emitió su
        evento 'created', así que los tests filtran por 'updated' o
        cuentan >=2 filas cuando corresponde."""
        from datetime import date, time
        ciclo = CicloDB(
            id="ciclo-1", anio=2026, numero=1,
            fecha_inicio=date(2026, 3, 1), fecha_fin=date(2026, 7, 1),
        )
        materia = MateriaDB(codigo="M1", nombre="Mat 1")
        session.add_all([ciclo, materia])
        session.commit()

        plan = PlanificacionCursadaDB(
            id="plan-1", nombre="Plan Test", ciclo_id="ciclo-1",
        )
        session.add(plan)
        session.commit()

        comision = ComisionDB(
            id="com-1", materia_codigo="M1", plan_cursada_id="plan-1",
            nombre="Com 1", numero=1, cupo=30, coef_asignacion=1.0,
        )
        session.add(comision)
        session.commit()

        horario = HorarioDB(
            id="hor-1", comision_id="com-1", codigo_materia="M1",
            dia="Lunes",
            hora_inicio=time(8, 0), hora_fin=time(10, 0),
        )
        session.add(horario)
        session.commit()

        schedule = ScheduleDB(
            id="sch-1", nombre="Cronograma Test",
            fecha_upload=date(2026, 2, 1),
        )
        session.add(schedule)
        session.commit()

        entry = ScheduleEntryDB(
            id="ent-1", schedule_id="sch-1", codigo_materia="M1",
            dia="Lunes",
            hora_inicio=time(8, 0), hora_fin=time(10, 0),
        )
        session.add(entry)
        session.commit()

        return {
            "plan": plan, "comision": comision, "horario": horario,
            "schedule": schedule, "entry": entry,
        }

    def test_horario_cambio_aula_genera_updated(self, session):
        ctx = self._seed_plan_completo(session)
        h = ctx["horario"]

        # Preparar aula (referenced FK) — no hace falta que exista para
        # el trigger, sólo seteamos el string.
        h.aula_id = "aula-x"
        session.add(h)
        session.commit()

        log = get_log_for_entity(session, "HorarioDB", "hor-1")
        # created + updated(aula_id)
        assert len(log) == 2
        upd = log[0]
        assert upd.action == "updated"
        assert upd.field == "aula_id"
        assert json.loads(upd.new_value) == "aula-x"

    def test_horario_flag_manual_se_trackea(self, session):
        ctx = self._seed_plan_completo(session)
        h = ctx["horario"]
        h.aula_asignada_manualmente = True
        session.add(h)
        session.commit()

        log = get_log_for_entity(session, "HorarioDB", "hor-1")
        assert any(
            e.action == "updated" and e.field == "aula_asignada_manualmente"
            for e in log
        )

    def test_horario_cambio_dia_hora_se_trackea(self, session):
        from datetime import time
        ctx = self._seed_plan_completo(session)
        h = ctx["horario"]
        h.dia = "Martes"
        h.hora_inicio = time(14, 0)
        session.add(h)
        session.commit()

        log = get_log_for_entity(session, "HorarioDB", "hor-1")
        campos = {e.field for e in log if e.action == "updated"}
        assert "dia" in campos
        assert "hora_inicio" in campos

    def test_comision_cambio_cupo_coef_se_trackea(self, session):
        ctx = self._seed_plan_completo(session)
        c = ctx["comision"]
        c.cupo = 50
        c.coef_asignacion = 0.5
        session.add(c)
        session.commit()

        log = get_log_for_entity(session, "ComisionDB", "com-1")
        campos = {e.field for e in log if e.action == "updated"}
        assert "cupo" in campos
        assert "coef_asignacion" in campos

    def test_plan_cambio_forecast_metodo_se_trackea(self, session):
        ctx = self._seed_plan_completo(session)
        p = ctx["plan"]
        p.forecast_metodo_default = "drift"
        session.add(p)
        session.commit()

        log = get_log_for_entity(session, "PlanificacionCursadaDB", "plan-1")
        assert any(
            e.action == "updated" and e.field == "forecast_metodo_default"
            for e in log
        )

    def test_schedule_cambio_nombre_se_trackea(self, session):
        ctx = self._seed_plan_completo(session)
        s = ctx["schedule"]
        s.nombre = "Cronograma Renombrado"
        session.add(s)
        session.commit()

        log = get_log_for_entity(session, "ScheduleDB", "sch-1")
        assert any(
            e.action == "updated" and e.field == "nombre" for e in log
        )

    def test_schedule_entry_cambio_dia_se_trackea(self, session):
        ctx = self._seed_plan_completo(session)
        e = ctx["entry"]
        e.dia = "Martes"
        session.add(e)
        session.commit()

        log = get_log_for_entity(session, "ScheduleEntryDB", "ent-1")
        assert any(
            evt.action == "updated" and evt.field == "dia" for evt in log
        )

    def test_alta_baja_de_las_5_entidades_genera_logs(self, session):
        """Sanity: alta y baja de cada entidad genera created/deleted."""
        ctx = self._seed_plan_completo(session)
        for tipo, key in [
            ("PlanificacionCursadaDB", "plan-1"),
            ("ComisionDB", "com-1"),
            ("HorarioDB", "hor-1"),
            ("ScheduleDB", "sch-1"),
            ("ScheduleEntryDB", "ent-1"),
        ]:
            log = get_log_for_entity(session, tipo, key)
            assert any(e.action == "created" for e in log), tipo

        # Baja en orden inverso a las FKs.
        session.delete(ctx["entry"])
        session.delete(ctx["schedule"])
        session.delete(ctx["horario"])
        session.delete(ctx["comision"])
        session.delete(ctx["plan"])
        session.commit()

        for tipo, key in [
            ("PlanificacionCursadaDB", "plan-1"),
            ("ComisionDB", "com-1"),
            ("HorarioDB", "hor-1"),
            ("ScheduleDB", "sch-1"),
            ("ScheduleEntryDB", "ent-1"),
        ]:
            log = get_log_for_entity(session, tipo, key)
            assert any(e.action == "deleted" for e in log), tipo
