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
    DictadoCicloDB,
    DictadoDB,
    CicloDB,
    MateriaDB,
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
