"""Test de migración para la PK compuesta de grupo_materia_sede.

Contexto: la primera versión del schema tenía PK (grupo_id, sede_id).
En 2026-09-09 la PK cambió a (grupo_id, sede_id, tipo) para permitir
que una sede aparezca en el mismo grupo con tipo DURO y tipo BLANDO
simultáneamente. En bases creadas antes del cambio, un `ALTER TABLE
ADD COLUMN tipo` no altera la PK (SQLite no lo permite), así que la
constraint UNIQUE quedó sobre (grupo_id, sede_id) y al insertar la
misma sede con dos tipos distintos falla.

Este test:

1. Crea manualmente la tabla con la PK vieja (simulando una DB legacy).
2. Verifica que insertar la misma sede con DURO + BLANDO rompa.
3. Corre la migración `_migrate_grupo_materia_sede_pk`.
4. Verifica que ahora sí acepta la doble entrada (DURO y BLANDO).
"""

from __future__ import annotations

import pytest
from sqlalchemy.pool import StaticPool
from sqlmodel import Session, create_engine


@pytest.fixture(name="engine_legacy")
def engine_legacy_fixture():
    """Engine con la tabla creada con la PK vieja (sin `tipo`)."""
    eng = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    with eng.connect() as conn:
        # Reproducimos la tabla como quedaba antes de la migración.
        conn.exec_driver_sql("""
            CREATE TABLE grupo_materia (
                id VARCHAR NOT NULL PRIMARY KEY,
                nombre VARCHAR NOT NULL UNIQUE,
                es_sin_clasificar BOOLEAN NOT NULL DEFAULT 0
            )
        """)
        conn.exec_driver_sql("""
            CREATE TABLE sedes (
                id VARCHAR NOT NULL PRIMARY KEY,
                nombre VARCHAR NOT NULL UNIQUE,
                es_default_comunes BOOLEAN NOT NULL DEFAULT 0
            )
        """)
        # Tabla con la PK vieja: (grupo_id, sede_id) — sin `tipo`.
        conn.exec_driver_sql("""
            CREATE TABLE grupo_materia_sede (
                grupo_id VARCHAR NOT NULL,
                sede_id VARCHAR NOT NULL,
                orden INTEGER NOT NULL DEFAULT 0,
                PRIMARY KEY (grupo_id, sede_id),
                FOREIGN KEY (grupo_id) REFERENCES grupo_materia (id),
                FOREIGN KEY (sede_id) REFERENCES sedes (id)
            )
        """)
        # Simular el ALTER TABLE que agrega `tipo` sin cambiar la PK.
        conn.exec_driver_sql(
            "ALTER TABLE grupo_materia_sede "
            "ADD COLUMN tipo VARCHAR DEFAULT 'DURO'"
        )
        # Seed: un grupo + una sede.
        conn.exec_driver_sql(
            "INSERT INTO grupo_materia (id, nombre, es_sin_clasificar) "
            "VALUES ('g1', 'Grupo 1', 0)"
        )
        conn.exec_driver_sql(
            "INSERT INTO sedes (id, nombre) VALUES ('s1', 'Sede 1')"
        )
        # Insertamos una fila DURO para simular una config previa.
        conn.exec_driver_sql(
            "INSERT INTO grupo_materia_sede "
            "(grupo_id, sede_id, tipo, orden) "
            "VALUES ('g1', 's1', 'DURO', 0)"
        )
        conn.commit()
    return eng


class TestBugPKLegacy:
    """Verifica primero que la PK vieja realmente rompe al insertar
    (grupo, sede, tipo) duplicado, y después que la migración lo
    arregla."""

    def test_pk_vieja_rompe_al_insertar_misma_sede_con_ambos_tipos(
        self, engine_legacy,
    ):
        """Reproduce el error reportado: insertar la misma sede con
        DURO y BLANDO en el mismo grupo choca con la PK vieja."""
        with engine_legacy.connect() as conn:
            with pytest.raises(Exception) as excinfo:
                conn.exec_driver_sql(
                    "INSERT INTO grupo_materia_sede "
                    "(grupo_id, sede_id, tipo, orden) "
                    "VALUES ('g1', 's1', 'BLANDO', 0)"
                )
                conn.commit()
            assert "UNIQUE constraint failed" in str(excinfo.value)

    def test_migracion_recrea_tabla_con_pk_correcta(self, engine_legacy):
        """Después de correr la migración, la misma sede puede aparecer
        con DURO y con BLANDO en el mismo grupo."""
        from src.database.connection import (
            _migrate_grupo_materia_sede_pk,
        )
        _migrate_grupo_materia_sede_pk(engine_legacy)

        with engine_legacy.connect() as conn:
            # La fila DURO original tiene que seguir ahí.
            row = conn.exec_driver_sql(
                "SELECT tipo, orden FROM grupo_materia_sede "
                "WHERE grupo_id = 'g1' AND sede_id = 's1'"
            ).fetchone()
            assert row is not None
            assert row[0] == "DURO"
            # Ahora podemos insertar la misma sede con BLANDO.
            conn.exec_driver_sql(
                "INSERT INTO grupo_materia_sede "
                "(grupo_id, sede_id, tipo, orden) "
                "VALUES ('g1', 's1', 'BLANDO', 0)"
            )
            conn.commit()
            # Chequeo: hay 2 filas para (g1, s1) con tipos distintos.
            rows = list(conn.exec_driver_sql(
                "SELECT tipo FROM grupo_materia_sede "
                "WHERE grupo_id = 'g1' AND sede_id = 's1' "
                "ORDER BY tipo"
            ).fetchall())
            tipos = [r[0] for r in rows]
            assert tipos == ["BLANDO", "DURO"]

    def test_migracion_idempotente(self, engine_legacy):
        """Correr la migración dos veces no rompe ni duplica filas."""
        from src.database.connection import (
            _migrate_grupo_materia_sede_pk,
        )
        _migrate_grupo_materia_sede_pk(engine_legacy)
        _migrate_grupo_materia_sede_pk(engine_legacy)

        with engine_legacy.connect() as conn:
            rows = list(conn.exec_driver_sql(
                "SELECT COUNT(*) FROM grupo_materia_sede"
            ).fetchone())
            assert rows[0] == 1  # sólo la fila DURO seed
