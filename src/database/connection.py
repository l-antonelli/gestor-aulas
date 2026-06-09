"""Database connection and session management."""

import json
import os
import logging
import re
import uuid as uuid_mod
from typing import Generator

from sqlmodel import SQLModel, Session, create_engine

logger = logging.getLogger(__name__)

# Default to local SQLite file in data directory
DATABASE_URL = os.getenv("DATABASE_URL", "sqlite:///data/database.db")

# Create engine with SQLite-specific settings
engine = create_engine(
    DATABASE_URL,
    echo=False,  # Set to True for SQL debugging
    connect_args={"check_same_thread": False}  # Needed for SQLite + Streamlit
)


def get_engine():
    """Get the database engine instance."""
    return engine


def _run_migrations(eng):
    """Run ALTER TABLE migrations for columns added after initial schema creation.

    SQLModel.metadata.create_all() only creates new tables; it does NOT add
    columns to existing tables.  This function handles that gap for SQLite.
    Each migration is idempotent — it silently skips if the column already exists.
    """
    migrations = [
        "ALTER TABLE carreras ADD COLUMN dicta_recursado BOOLEAN DEFAULT 1",
        "ALTER TABLE materias ADD COLUMN virtual BOOLEAN DEFAULT 0",
        "ALTER TABLE dictados ADD COLUMN virtual BOOLEAN DEFAULT 0",
        "ALTER TABLE schedule_entries ADD COLUMN tipo_clase VARCHAR DEFAULT NULL",
        "ALTER TABLE horarios ADD COLUMN tipo_clase VARCHAR DEFAULT NULL",
        "ALTER TABLE clases ADD COLUMN tipo_clase VARCHAR DEFAULT NULL",
        "ALTER TABLE materias ADD COLUMN horas_teoria REAL DEFAULT NULL",
        "ALTER TABLE materias ADD COLUMN horas_laboratorio REAL DEFAULT NULL",
        "ALTER TABLE schedule_validations ADD COLUMN dictado_count_at_validation INTEGER NOT NULL DEFAULT 0",
        "ALTER TABLE schedule_validations ADD COLUMN n_conflictos_horarios INTEGER NOT NULL DEFAULT 0",
        "ALTER TABLE schedule_validations ADD COLUMN excluir_virtuales_optativas BOOLEAN NOT NULL DEFAULT 0",
        # B.2.1: el toggle paso a ser solo optativas (las virtuales si cuentan
        # para cobertura/conflictos). La columna nueva convive con la vieja
        # para no perder snapshots historicos; la lectura usa la nueva.
        "ALTER TABLE schedule_validations ADD COLUMN excluir_optativas BOOLEAN NOT NULL DEFAULT 0",
        "ALTER TABLE plan_validations ADD COLUMN excluir_optativas BOOLEAN NOT NULL DEFAULT 0",
        "ALTER TABLE materias ADD COLUMN dicta_recursado BOOLEAN DEFAULT NULL",
        "ALTER TABLE comisiones ADD COLUMN coef_asignacion REAL NOT NULL DEFAULT 1.0",
        "ALTER TABLE planificaciones_cursada ADD COLUMN forecast_metodo_default VARCHAR NOT NULL DEFAULT 'media_movil'",
        "DROP TABLE IF EXISTS inscripcion_forecasts",
        # Override manual del valor de forecast por (plan, materia, cuatri).
        # Si esta seteado, fuerza el valor de inscriptos esperados,
        # sobreescribiendo cualquier resultado del forecast historico.
        "ALTER TABLE materia_forecast_config ADD COLUMN valor_override REAL DEFAULT NULL",
        # LP asignacion de aulas: flag para distinguir asignaciones
        # manuales (las del usuario) de las del LP. El re-run respeta las
        # manuales por default.
        "ALTER TABLE clases ADD COLUMN aula_asignada_manualmente BOOLEAN NOT NULL DEFAULT 0",
        # Override manual de `activo` en dictados: None = usar regla,
        # True/False = forzar manualmente. Lo respeta `recompute_activo_for_ciclo`
        # por default. Permite desactivar materias "comodín" sin que la
        # próxima recalculación las vuelva a activar.
        "ALTER TABLE dictados ADD COLUMN activo_override_manual BOOLEAN DEFAULT NULL",
        # Sede como entidad propia + IDs de aulas a UUID. Las columnas se
        # agregan acá; el remap de datos lo hace `_migrate_aulas_sede_y_uuid`.
        # Nota: aulas.sede (string legacy) se conserva pero el modelo no la
        # mapea más; se limpiará en una recreación posterior de la tabla.
        "ALTER TABLE aulas ADD COLUMN sede_id VARCHAR DEFAULT NULL",
        "ALTER TABLE aulas ADD COLUMN codigo_aula VARCHAR DEFAULT NULL",
    ]
    with eng.connect() as conn:
        for sql in migrations:
            try:
                conn.exec_driver_sql(sql)
                conn.commit()
            except Exception:
                # Column already exists — safe to ignore
                conn.rollback()

    # Data migration: populate horas_teoria/horas_laboratorio from horas_semanales
    with eng.connect() as conn:
        conn.exec_driver_sql(
            "UPDATE materias SET horas_teoria = horas_semanales, horas_laboratorio = 0 "
            "WHERE horas_teoria IS NULL AND horas_semanales IS NOT NULL"
        )
        conn.commit()

    # Data migration: limpiar tipo_clase='teorica' heredado del DEFAULT de la
    # migracion ALTER TABLE. Ninguno fue seteado manualmente; el default correcto
    # ahora es NULL (sin determinar, el LP decide).
    with eng.connect() as conn:
        conn.exec_driver_sql(
            "UPDATE schedule_entries SET tipo_clase = NULL WHERE tipo_clase = 'teorica'"
        )
        conn.exec_driver_sql(
            "UPDATE horarios SET tipo_clase = NULL WHERE tipo_clase = 'teorica'"
        )
        conn.exec_driver_sql(
            "UPDATE clases SET tipo_clase = NULL WHERE tipo_clase = 'teorica'"
        )
        conn.commit()

    # Migration: make schedules.ciclo_id nullable (SQLite requires table recreation)
    _migrate_schedules_nullable_ciclo(eng)

    # Migration: make materia_forecast_config.metodo nullable (para
    # poder tener filas con solo valor_override sin metodo override).
    _migrate_forecast_config_metodo_nullable(eng)

    # Migration: extraer Sede como entidad propia y migrar IDs de Aulas a UUID.
    # Idempotente: detecta filas ya migradas (id con shape de UUID y sede_id no NULL).
    _migrate_aulas_sede_y_uuid(eng)

    # Recrear `aulas` para eliminar la columna legacy `sede` (string) y
    # aplicar UNIQUE en codigo_aula. Solo actúa si `aulas` aún tiene esa
    # columna (DBs legacy); en DBs nuevas no hace nada.
    _migrate_aulas_drop_legacy_sede(eng)


def _migrate_schedules_nullable_ciclo(eng):
    """Recreate schedules table so ciclo_id allows NULL.

    SQLite no soporta ALTER COLUMN.  Verificamos con PRAGMA table_info si
    ciclo_id ya es nullable (notnull == 0).  Si ya lo es, no hacemos nada.
    """
    with eng.connect() as conn:
        rows = conn.exec_driver_sql("PRAGMA table_info(schedules)").fetchall()
        if not rows:
            # Table doesn't exist yet — create_all will handle it
            return

        # PRAGMA table_info columns: (cid, name, type, notnull, dflt_value, pk)
        for row in rows:
            if row[1] == "ciclo_id":
                if row[3] == 0:
                    # Already nullable — nothing to do
                    return
                break
        else:
            # ciclo_id column not found — schema mismatch, skip
            return

        # Recreate table with nullable ciclo_id
        logger.info("Migrating schedules table: making ciclo_id nullable")
        conn.exec_driver_sql("""
            CREATE TABLE schedules_tmp (
                id VARCHAR NOT NULL PRIMARY KEY,
                ciclo_id VARCHAR,
                nombre VARCHAR NOT NULL,
                fecha_upload DATE NOT NULL,
                source_filename VARCHAR NOT NULL DEFAULT '',
                FOREIGN KEY (ciclo_id) REFERENCES ciclos (id)
            )
        """)
        conn.exec_driver_sql("""
            INSERT INTO schedules_tmp (id, ciclo_id, nombre, fecha_upload, source_filename)
            SELECT id, ciclo_id, nombre, fecha_upload, source_filename FROM schedules
        """)
        conn.exec_driver_sql("DROP TABLE schedules")
        conn.exec_driver_sql("ALTER TABLE schedules_tmp RENAME TO schedules")
        conn.exec_driver_sql("CREATE INDEX IF NOT EXISTS ix_schedules_ciclo_id ON schedules (ciclo_id)")
        conn.commit()
        logger.info("Migration complete: schedules.ciclo_id is now nullable")


def _migrate_forecast_config_metodo_nullable(eng):
    """Recreate materia_forecast_config para que `metodo` permita NULL.

    El modelo ahora soporta filas con solo `valor_override` (sin metodo
    override). Para eso `metodo` debe ser nullable. SQLite no soporta
    ALTER COLUMN, asi que recreamos la tabla preservando los datos.
    """
    with eng.connect() as conn:
        rows = conn.exec_driver_sql(
            "PRAGMA table_info(materia_forecast_config)"
        ).fetchall()
        if not rows:
            return  # Tabla no existe aun; create_all la hara con el modelo nuevo

        # PRAGMA table_info: (cid, name, type, notnull, dflt_value, pk)
        for row in rows:
            if row[1] == "metodo":
                if row[3] == 0:
                    return  # ya nullable
                break
        else:
            return  # columna metodo no existe (raro)

        logger.info(
            "Migrating materia_forecast_config: making metodo nullable"
        )
        conn.exec_driver_sql("""
            CREATE TABLE materia_forecast_config_tmp (
                plan_cursada_id VARCHAR NOT NULL,
                materia_codigo VARCHAR NOT NULL,
                cuatrimestre VARCHAR NOT NULL,
                metodo VARCHAR,
                valor_override REAL,
                PRIMARY KEY (plan_cursada_id, materia_codigo, cuatrimestre),
                FOREIGN KEY (plan_cursada_id) REFERENCES planificaciones_cursada (id),
                FOREIGN KEY (materia_codigo) REFERENCES materias (codigo)
            )
        """)
        conn.exec_driver_sql("""
            INSERT INTO materia_forecast_config_tmp (
                plan_cursada_id, materia_codigo, cuatrimestre,
                metodo, valor_override
            )
            SELECT plan_cursada_id, materia_codigo, cuatrimestre,
                   metodo, valor_override
            FROM materia_forecast_config
        """)
        conn.exec_driver_sql("DROP TABLE materia_forecast_config")
        conn.exec_driver_sql(
            "ALTER TABLE materia_forecast_config_tmp "
            "RENAME TO materia_forecast_config"
        )
        conn.commit()


_UUID_RE = re.compile(
    r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$",
    re.IGNORECASE,
)


def _migrate_aulas_sede_y_uuid(eng):
    """Migrar Sede a entidad y reasignar IDs de Aulas a UUID.

    Pasos:
    1. Crear `SedeDB` por cada distinct `aulas.sede` (legacy string).
    2. Llenar `aulas.sede_id` desde el string legacy.
    3. Llenar `aulas.codigo_aula = aulas.id` (preserva display).
    4. Para cada aula con id no-UUID, generar UUID y remapear FKs:
       - `clases.aula_id`
       - `materia_laboratorio.aula_id`
       - `lp_runs.details_json` (JSON con lista de horarios; cada item
         puede tener `aula_id`).

    Idempotencia: si ya existe `sede_id` no NULL en todas las filas y
    todos los `aulas.id` son UUID, no hay nada que hacer.
    """
    with eng.connect() as conn:
        # ¿Existe la tabla aulas? (en DB nueva, create_all la habrá creado
        # con el schema nuevo; no hay nada legacy para migrar.)
        rows = conn.exec_driver_sql("PRAGMA table_info(aulas)").fetchall()
        if not rows:
            return

        col_names = {r[1] for r in rows}
        if "sede" not in col_names:
            # DB ya creada con el schema nuevo (sin columna legacy `sede`).
            # Solo verificamos que haya al menos una sede default si las
            # tablas están vacías.
            _seed_default_sede_if_empty(conn)
            return

        # Hay columna legacy `sede`. Verificar si la migración ya corrió.
        aulas = conn.exec_driver_sql(
            "SELECT id, sede, sede_id, codigo_aula FROM aulas"
        ).fetchall()

        # Caso 1: tabla vacía. Solo sembrar sede default si no existe.
        if not aulas:
            _seed_default_sede_if_empty(conn)
            return

        ya_migradas = all(
            (row[2] is not None and row[3] is not None and _UUID_RE.match(row[0]))
            for row in aulas
        )
        if ya_migradas:
            return

        logger.info("Migrating aulas: extracting Sede entity and converting IDs to UUID")

        # 1. Sedes únicas a partir del string legacy.
        sedes_unicas = sorted({(row[1] or "Sin sede") for row in aulas})
        sede_nombre_to_id: dict[str, str] = {}
        for nombre in sedes_unicas:
            existing = conn.exec_driver_sql(
                "SELECT id FROM sedes WHERE nombre = ?", (nombre,)
            ).fetchone()
            if existing:
                sede_nombre_to_id[nombre] = existing[0]
                continue
            sede_id = str(uuid_mod.uuid4())
            conn.exec_driver_sql(
                "INSERT INTO sedes (id, nombre) VALUES (?, ?)",
                (sede_id, nombre),
            )
            sede_nombre_to_id[nombre] = sede_id

        # 2 + 3. Setear sede_id y codigo_aula. 4. Remapear ids no-UUID.
        id_remap: dict[str, str] = {}
        for old_id, sede_legacy, sede_id_actual, codigo_actual in aulas:
            sede_nombre = sede_legacy or "Sin sede"
            sede_id = sede_id_actual or sede_nombre_to_id[sede_nombre]
            codigo_aula = codigo_actual or old_id

            new_id = old_id if _UUID_RE.match(old_id) else str(uuid_mod.uuid4())
            if new_id != old_id:
                id_remap[old_id] = new_id

            conn.exec_driver_sql(
                "UPDATE aulas SET id = ?, sede_id = ?, codigo_aula = ? WHERE id = ?",
                (new_id, sede_id, codigo_aula, old_id),
            )

        # Remap de FKs que apuntan a aulas.id.
        for old_id, new_id in id_remap.items():
            conn.exec_driver_sql(
                "UPDATE clases SET aula_id = ? WHERE aula_id = ?",
                (new_id, old_id),
            )
            # materia_laboratorio: PK compuesta (materia_codigo, aula_id).
            # Como remapeamos a un id distinto, no debería haber colisiones
            # (los UUIDs nuevos son únicos por aula).
            conn.exec_driver_sql(
                "UPDATE materia_laboratorio SET aula_id = ? WHERE aula_id = ?",
                (new_id, old_id),
            )

        # Remap dentro de lp_runs.details_json (snapshots históricos).
        if id_remap:
            lp_rows = conn.exec_driver_sql(
                "SELECT id, details_json FROM lp_runs"
            ).fetchall()
            for run_id, details_raw in lp_rows:
                if not details_raw:
                    continue
                try:
                    details = json.loads(details_raw)
                except (json.JSONDecodeError, TypeError):
                    logger.warning(
                        "lp_runs.id=%s: details_json no se pudo parsear, "
                        "se deja como está (snapshot histórico).",
                        run_id,
                    )
                    continue
                changed = False
                for h in details.get("horarios", []) or []:
                    aid = h.get("aula_id")
                    if aid and aid in id_remap:
                        h["aula_id"] = id_remap[aid]
                        changed = True
                if changed:
                    conn.exec_driver_sql(
                        "UPDATE lp_runs SET details_json = ? WHERE id = ?",
                        (json.dumps(details), run_id),
                    )

        conn.commit()
        logger.info(
            "Migration complete: %d sede(s), %d id(s) remapeados a UUID",
            len(sedes_unicas), len(id_remap),
        )


def _migrate_aulas_drop_legacy_sede(eng):
    """Recrear `aulas` para eliminar columna legacy `sede` y aplicar
    UNIQUE en codigo_aula.

    SQLite no soporta DROP COLUMN ni ADD UNIQUE — hay que recrear. Solo
    actúa si la columna `sede` aún existe (DBs migradas desde versión
    vieja). En DBs nuevas, `create_all` ya creó la tabla con el schema
    correcto y esto es no-op.
    """
    with eng.connect() as conn:
        rows = conn.exec_driver_sql("PRAGMA table_info(aulas)").fetchall()
        if not rows:
            return
        col_names = {r[1] for r in rows}
        if "sede" not in col_names:
            return  # Ya migrada o tabla nueva.

        logger.info(
            "Recreating aulas: dropping legacy `sede` column, "
            "enforcing UNIQUE on codigo_aula"
        )
        conn.exec_driver_sql("""
            CREATE TABLE aulas_tmp (
                id VARCHAR NOT NULL PRIMARY KEY,
                sede_id VARCHAR NOT NULL,
                codigo_aula VARCHAR NOT NULL UNIQUE,
                nombre VARCHAR NOT NULL,
                capacidad INTEGER NOT NULL,
                tipo VARCHAR NOT NULL DEFAULT 'teorica',
                descripcion VARCHAR NOT NULL DEFAULT '',
                FOREIGN KEY (sede_id) REFERENCES sedes (id)
            )
        """)
        conn.exec_driver_sql("""
            INSERT INTO aulas_tmp
                (id, sede_id, codigo_aula, nombre, capacidad, tipo, descripcion)
            SELECT id, sede_id, codigo_aula, nombre, capacidad, tipo,
                   COALESCE(descripcion, '')
            FROM aulas
        """)
        conn.exec_driver_sql("DROP TABLE aulas")
        conn.exec_driver_sql("ALTER TABLE aulas_tmp RENAME TO aulas")
        conn.exec_driver_sql(
            "CREATE INDEX IF NOT EXISTS ix_aulas_sede_id ON aulas (sede_id)"
        )
        conn.exec_driver_sql(
            "CREATE INDEX IF NOT EXISTS ix_aulas_codigo_aula ON aulas (codigo_aula)"
        )
        conn.commit()


def _seed_default_sede_if_empty(conn):
    """Sembrar sede 'Pellegrini' si la tabla está vacía.

    Se invoca cuando creamos la DB desde cero (sin filas legacy en aulas).
    Garantiza que la UI de creación de aulas siempre tenga al menos una
    sede para elegir.
    """
    n = conn.exec_driver_sql("SELECT COUNT(*) FROM sedes").fetchone()[0]
    if n > 0:
        return
    conn.exec_driver_sql(
        "INSERT INTO sedes (id, nombre) VALUES (?, ?)",
        (str(uuid_mod.uuid4()), "Pellegrini"),
    )
    conn.commit()


def init_db():
    """Initialize database tables. Call once at app startup."""
    SQLModel.metadata.create_all(engine)
    _run_migrations(engine)


def get_session() -> Generator[Session, None, None]:
    """
    Get a database session.
    
    Usage:
        with get_session() as session:
            # do stuff with session
    
    Or as a generator for dependency injection:
        for session in get_session():
            # do stuff
    """
    with Session(engine) as session:
        yield session
