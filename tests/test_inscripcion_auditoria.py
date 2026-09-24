"""Tests de auditoría mínima y alias de códigos.

Fase E2 del rediseño 2026-09-15. Cubre:

- `InscripcionHistoricaDB.updated_at` y `origen` populados por los
  services de guardado (manual y por import masivo).
- `CodigoAliasDB` como fuente de resolución persistente para códigos
  externos que no matchean directamente.
- `preview_import` resuelve vía alias antes de vía guaraní.
"""

from __future__ import annotations

import io
from datetime import datetime, timedelta

import pandas as pd
import pytest
from sqlalchemy.pool import StaticPool
from sqlmodel import Session, SQLModel, create_engine, select

from src.database.models import (
    CodigoAliasDB,
    InscripcionHistoricaDB,
    MateriaDB,
)
from src.services.inscripcion_import_service import (
    commit_import,
    delete_alias,
    list_aliases,
    preview_import,
    registrar_alias,
    resolver_via_alias,
)
from src.services.inscripcion_service import (
    RegistroInscripcion,
    guardar_registros_materia,
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


@pytest.fixture
def catalogo(session):
    session.add(MateriaDB(
        codigo="MAT101", nombre="Análisis I",
        periodo="cuatrimestral", active=True, horas_semanales=6,
    ))
    session.add(MateriaDB(
        codigo="FIS101", nombre="Física I",
        periodo="cuatrimestral", active=True, horas_semanales=6,
    ))
    session.commit()


def _fake_excel(df: pd.DataFrame) -> io.BytesIO:
    buf = io.BytesIO()
    df.to_excel(buf, index=False)
    buf.seek(0)
    buf.name = "test.xlsx"  # type: ignore[attr-defined]
    return buf


# =============================================================================
# Auditoría en guardar_registros_materia (canal manual)
# =============================================================================


class TestAuditoriaManual:
    def test_insert_manual_pobla_campos_de_auditoria(
        self, session, catalogo,
    ):
        antes = datetime.utcnow() - timedelta(seconds=1)
        guardar_registros_materia(
            session, "MAT101",
            [RegistroInscripcion(anio=2024, cuatrimestre="1C", inscriptos=100)],
            cuatris_visibles={"1C"},
        )
        row = session.exec(select(InscripcionHistoricaDB)).one()
        assert row.updated_at is not None
        assert row.updated_at >= antes
        assert row.origen == "manual"

    def test_update_manual_refresca_updated_at(self, session, catalogo):
        guardar_registros_materia(
            session, "MAT101",
            [RegistroInscripcion(anio=2024, cuatrimestre="1C", inscriptos=100)],
            cuatris_visibles={"1C"},
        )
        first_ts = session.exec(select(InscripcionHistoricaDB)).one().updated_at
        assert first_ts is not None

        # Segunda pasada — mismo PK, valor distinto → update
        guardar_registros_materia(
            session, "MAT101",
            [RegistroInscripcion(anio=2024, cuatrimestre="1C", inscriptos=150)],
            cuatris_visibles={"1C"},
        )
        second = session.exec(select(InscripcionHistoricaDB)).one()
        assert second.inscriptos == 150
        # Refresca timestamp (>= porque puede coincidir el microsegundo
        # en tests rápidos).
        assert second.updated_at is not None
        assert second.updated_at >= first_ts

    def test_origen_override_via_parametro(self, session, catalogo):
        guardar_registros_materia(
            session, "MAT101",
            [RegistroInscripcion(anio=2024, cuatrimestre="1C", inscriptos=100)],
            cuatris_visibles={"1C"},
            origen="override",
        )
        row = session.exec(select(InscripcionHistoricaDB)).one()
        assert row.origen == "override"


# =============================================================================
# Auditoría en el import masivo (canal importado)
# =============================================================================


class TestAuditoriaImportMasivo:
    def test_commit_import_pobla_origen_importado(self, session, catalogo):
        df = pd.DataFrame([
            {"codigo_materia": "MAT101", "anio": 2024,
             "cuatrimestre": "1C", "inscriptos": 100},
        ])
        pv = preview_import(session, _fake_excel(df))
        commit_import(session, pv)

        row = session.exec(select(InscripcionHistoricaDB)).one()
        assert row.origen == "importado"
        assert row.updated_at is not None

    def test_commit_import_pisa_valor_previo_manual(self, session, catalogo):
        """Un dato cargado manualmente puede quedar sobrescrito por el
        importer; el `origen` cambia a 'importado' para dejar trazabilidad
        de que ya no viene del canal manual.
        """
        guardar_registros_materia(
            session, "MAT101",
            [RegistroInscripcion(anio=2024, cuatrimestre="1C", inscriptos=100)],
            cuatris_visibles={"1C"},
        )
        assert session.exec(select(InscripcionHistoricaDB)).one().origen == "manual"

        df = pd.DataFrame([
            {"codigo_materia": "MAT101", "anio": 2024,
             "cuatrimestre": "1C", "inscriptos": 200},
        ])
        pv = preview_import(session, _fake_excel(df))
        commit_import(session, pv)

        row = session.exec(select(InscripcionHistoricaDB)).one()
        assert row.inscriptos == 200
        assert row.origen == "importado"


# =============================================================================
# CodigoAliasDB
# =============================================================================


class TestCodigoAlias:
    def test_registrar_alias_inserta(self, session, catalogo):
        alias = registrar_alias(session, "MAT101_OLD", "MAT101")
        assert alias.codigo_externo == "MAT101_OLD"
        assert alias.materia_codigo == "MAT101"
        assert alias.origen == "manual"
        assert alias.updated_at is not None

    def test_registrar_alias_upsert(self, session, catalogo):
        registrar_alias(session, "MAT_OLD", "MAT101", nota="typo antiguo")
        # Reasignar → upsert, no duplica.
        registrar_alias(session, "MAT_OLD", "FIS101", nota="me equivoqué antes")
        rows = list(session.exec(select(CodigoAliasDB)).all())
        assert len(rows) == 1
        assert rows[0].materia_codigo == "FIS101"
        assert rows[0].nota == "me equivoqué antes"

    def test_resolver_via_alias(self, session, catalogo):
        assert resolver_via_alias(session, "FANTASMA") is None
        registrar_alias(session, "FANTASMA", "MAT101")
        assert resolver_via_alias(session, "FANTASMA") == "MAT101"

    def test_list_y_delete(self, session, catalogo):
        registrar_alias(session, "A1", "MAT101")
        registrar_alias(session, "B2", "FIS101")
        aliases = list_aliases(session)
        assert [a.codigo_externo for a in aliases] == ["A1", "B2"]

        delete_alias(session, "A1")
        aliases = list_aliases(session)
        assert [a.codigo_externo for a in aliases] == ["B2"]


# =============================================================================
# Preview usa alias para resolver códigos "sin matchear"
# =============================================================================


class TestImportResuelveViaAlias:
    def test_codigo_externo_sin_alias_va_a_error(self, session, catalogo):
        df = pd.DataFrame([
            {"codigo_materia": "MAT_OLD", "anio": 2024,
             "cuatrimestre": "1C", "inscriptos": 100},
        ])
        pv = preview_import(session, _fake_excel(df))
        assert pv.filas_ok == []
        assert len(pv.filas_error) == 1

    def test_alias_persistido_resuelve_codigo_externo(
        self, session, catalogo,
    ):
        """Después de guardar `MAT_OLD → MAT101` como alias, el importer
        resuelve automáticamente sin marcar error.
        """
        registrar_alias(session, "MAT_OLD", "MAT101")

        df = pd.DataFrame([
            {"codigo_materia": "MAT_OLD", "anio": 2024,
             "cuatrimestre": "1C", "inscriptos": 100},
        ])
        pv = preview_import(session, _fake_excel(df))
        assert pv.filas_error == []
        assert len(pv.filas_ok) == 1
        assert pv.filas_ok[0].materia_codigo == "MAT101"
        assert pv.filas_ok[0].resolucion_type == "alias"
        # Warning que informa la resolución vía alias
        assert any("alias" in w.lower() for w in pv.warnings)

    def test_commit_via_alias_persiste_bajo_codigo_canonico(
        self, session, catalogo,
    ):
        registrar_alias(session, "MAT_OLD", "MAT101")
        df = pd.DataFrame([
            {"codigo_materia": "MAT_OLD", "anio": 2024,
             "cuatrimestre": "1C", "inscriptos": 100},
        ])
        pv = preview_import(session, _fake_excel(df))
        commit_import(session, pv)

        row = session.exec(select(InscripcionHistoricaDB)).one()
        assert row.materia_codigo == "MAT101"  # no "MAT_OLD"
        assert row.origen == "importado"

    def test_alias_apuntando_a_materia_inexistente_falla_gracefully(
        self, session, catalogo,
    ):
        """Si el alias apunta a un código que ya no está en el catálogo
        (materia archivada / renombrada), no debería crashear el
        preview — cae a error de "no está en el catálogo".
        """
        # Guardar el alias antes de que exista la materia destino
        # (rompe la FK, así que directamente insertamos la fila).
        session.add(CodigoAliasDB(
            codigo_externo="HUERFANO",
            materia_codigo="MAT101",  # cumple FK pero simularemos borrado
        ))
        session.commit()
        # Simular que MAT101 desapareció del catálogo activo — como no
        # podemos borrarla (violaría la FK del alias), sólo verificamos
        # el caso "por_codigo no la tiene" con un mock: cambiamos el
        # alias target a un código huérfano — SQLite no enforza la FK
        # por default en tests.
        alias = session.exec(select(CodigoAliasDB)).one()
        alias.materia_codigo = "CODIGO_FANTASMA"
        session.add(alias)
        session.commit()

        df = pd.DataFrame([
            {"codigo_materia": "HUERFANO", "anio": 2024,
             "cuatrimestre": "1C", "inscriptos": 100},
        ])
        pv = preview_import(session, _fake_excel(df))
        # No crashea; el alias no resuelve porque el target no está
        # en `por_codigo`. Cae al camino de guarani, y si tampoco
        # matchea, va a error.
        assert pv.filas_ok == []
        assert len(pv.filas_error) == 1
        # Bugfix task #348 (2026-09-22): el mensaje ahora es específico
        # y no dice "ni por alias" (que era confuso porque sí había
        # alias). Desde 2026-09-24 guía a re-asociar desde la propia
        # vista previa (la sección legacy "Sin matchear" se removió).
        _fila_num, _msg = pv.filas_error[0]
        assert "CODIGO_FANTASMA" in _msg
        assert "vista previa" in _msg
        assert "HUERFANO" in pv.codigos_no_resueltos
