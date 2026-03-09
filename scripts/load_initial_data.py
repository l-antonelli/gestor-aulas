"""
Load initial data from Excel files into the database.

Reads from data/input/:
- aulas/aulas.xlsx              -> Aula records
- Carreras/Maestro materias.xlsx -> Materia records
- Carreras/Maestro planes.xlsx   -> Carrera + PlanEstudio records
- cronogramas/horarios_2C_2025.xlsx -> Horario + Comision records (derived)

Usage:
    python -m scripts.load_initial_data [--reset]

    --reset: Drop and recreate all tables before loading (WARNING: deletes all data)
"""

import argparse
import math
import sys
import uuid
from datetime import time
from pathlib import Path

import pandas as pd
from sqlmodel import Session, select

# Add project root to path
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

from src.database.connection import get_session, init_db
from src.database.models import (
    AulaDB, CarreraDB, ComisionDB, HorarioDB, MateriaDB, PlanEstudioDB,
    PlanCarreraVersionDB,
)
from src.database.crud import aula_crud, materia_crud, carrera_crud, horario_crud, comision_crud
from src.services.horario_loading_service import (
    _resolve_materia_code, derive_comision_count,
)

DATA_DIR = project_root / "data" / "input"
AULAS_FILE = DATA_DIR / "aulas" / "aulas.xlsx"
MAESTRO_MATERIAS = DATA_DIR / "Carreras" / "Maestro materias.xlsx"
MAESTRO_PLANES = DATA_DIR / "Carreras" / "Maestro planes.xlsx"
HORARIOS_2C_2025 = DATA_DIR / "cronogramas" / "horarios_2C_2025.xlsx"


# =============================================================================
# Step 1: Load Aulas
# =============================================================================

def load_aulas(session: Session) -> dict:
    """Load aulas from aulas.xlsx."""
    df = pd.read_excel(AULAS_FILE)
    stats = {"created": 0, "skipped": 0, "warnings": []}

    for _, row in df.iterrows():
        nombre = str(row["Aula"]).strip()
        capacidad_raw = row["Capacidad (Alumnos)"]

        try:
            capacidad = int(capacidad_raw)
        except (ValueError, TypeError):
            stats["warnings"].append(f"{nombre}: capacidad invalida '{capacidad_raw}'")
            continue

        # Derive ID from name: "AULA 01" -> "AULA-01"
        aula_id = nombre.replace(" ", "-")

        existing = aula_crud.get(session, aula_id)
        if existing:
            stats["skipped"] += 1
            continue

        aula = AulaDB(
            id=aula_id,
            sede="Principal",
            nombre=nombre,
            capacidad=capacidad,
            tipo="teorica",
        )
        session.add(aula)
        stats["created"] += 1

    session.commit()
    return stats


# =============================================================================
# Step 2: Load Materias
# =============================================================================

def load_materias(session: Session) -> dict:
    """Load materias from Maestro materias.xlsx."""
    df = pd.read_excel(MAESTRO_MATERIAS)
    stats = {"created": 0, "skipped": 0, "warnings": []}

    for _, row in df.iterrows():
        codigo = str(row["codigo_plan"]).strip()
        nombre = str(row["nombre"]).strip()

        # Parse horas
        horas_raw = row["horas"]
        horas = None
        if pd.notna(horas_raw) and str(horas_raw).strip() != "-":
            try:
                horas = int(float(horas_raw))
            except (ValueError, TypeError):
                stats["warnings"].append(f"{codigo}: horas invalidas '{horas_raw}'")

        # Parse codigo_guarani
        guarani_raw = str(row["codigo_guarani"]).strip()
        codigo_guarani = None if guarani_raw in ("-", "", "nan") else guarani_raw

        # Parse periodo
        periodo = str(row["periodo"]).strip().lower()
        if periodo not in ("anual", "cuatrimestral"):
            stats["warnings"].append(f"{codigo}: periodo invalido '{periodo}', usando 'cuatrimestral'")
            periodo = "cuatrimestral"

        # Skip if already exists
        existing = materia_crud.get(session, codigo)
        if existing:
            stats["skipped"] += 1
            continue

        materia = MateriaDB(
            codigo=codigo,
            nombre=nombre,
            codigo_guarani=codigo_guarani,
            cupo=None,
            horas_semanales=horas,
            periodo=periodo,
        )
        session.add(materia)
        stats["created"] += 1

    session.commit()
    return stats


# =============================================================================
# Step 3: Load Carreras + Planes
# =============================================================================

def load_carreras_and_planes(session: Session) -> dict:
    """Load carreras, plan versions, and plan_estudio from Maestro planes.xlsx."""
    df = pd.read_excel(MAESTRO_PLANES)
    stats = {
        "carreras_created": 0, "versions_created": 0, "planes_created": 0,
        "skipped": 0, "warnings": [],
    }

    # Extract unique carreras and create "Plan Original" version for each
    carreras_seen = set()
    version_map: dict[str, str] = {}  # carrera_codigo -> plan_version_id

    for codigo_raw in df["codigo_carrera"].dropna().unique():
        codigo = str(codigo_raw).strip()
        if not codigo or codigo in carreras_seen:
            continue
        carreras_seen.add(codigo)

        existing = carrera_crud.get(session, codigo)
        if not existing:
            carrera = CarreraDB(
                codigo=codigo,
                nombre=codigo,  # Placeholder — to be filled in UI later
                titulo_otorgado="",
                duracion_anios=5,
                cantidad_materias=None,
            )
            session.add(carrera)
            stats["carreras_created"] += 1

    session.commit()

    # Create "Plan Original" version for each carrera
    from datetime import date as date_type
    for codigo in carreras_seen:
        # Check if version already exists
        existing_version = session.exec(
            select(PlanCarreraVersionDB)
            .where(PlanCarreraVersionDB.carrera_codigo == codigo)
            .where(PlanCarreraVersionDB.nombre == "Plan Original")
        ).first()

        if existing_version:
            version_map[codigo] = existing_version.id
        else:
            version_id = str(uuid.uuid4())
            version = PlanCarreraVersionDB(
                id=version_id,
                carrera_codigo=codigo,
                nombre="Plan Original",
                descripcion="Version inicial cargada desde Excel",
                fecha_creacion=date_type.today(),
            )
            session.add(version)
            version_map[codigo] = version_id
            stats["versions_created"] += 1

    session.commit()

    # Create PlanEstudio records
    for _, row in df.iterrows():
        carrera_raw = row["codigo_carrera"]
        if pd.isna(carrera_raw):
            stats["warnings"].append(
                f"Materia '{row['codigo_materia']}': sin carrera, omitido"
            )
            stats["skipped"] += 1
            continue

        carrera_codigo = str(carrera_raw).strip()
        materia_codigo = str(row["codigo_materia"]).strip()

        # Parse anio_plan
        anio_raw = row["anio_plan"]
        anio = None
        if pd.notna(anio_raw) and str(anio_raw).strip() != "-":
            try:
                anio = int(float(anio_raw))
            except (ValueError, TypeError):
                stats["warnings"].append(
                    f"{carrera_codigo}/{materia_codigo}: anio_plan invalido '{anio_raw}'"
                )

        # Parse cuatrimestre_plan
        cuat_raw = str(row["cuatrimestre_plan"]).strip()
        cuatrimestre = None if cuat_raw in ("-", "", "nan") else cuat_raw

        # Parse correlativas (raw text)
        corr_raw = str(row["correlativas"]).strip()
        correlativas = "" if corr_raw in ("-", "", "nan") else corr_raw

        # Check if materia exists
        materia = materia_crud.get(session, materia_codigo)
        if materia is None:
            stats["warnings"].append(
                f"{carrera_codigo}/{materia_codigo}: materia no existe, omitido"
            )
            stats["skipped"] += 1
            continue

        # Get plan version id for this carrera
        plan_version_id = version_map.get(carrera_codigo)
        if not plan_version_id:
            stats["warnings"].append(
                f"{carrera_codigo}/{materia_codigo}: sin version de plan, omitido"
            )
            stats["skipped"] += 1
            continue

        # Check if already exists (same materia + carrera + version)
        existing = session.exec(
            select(PlanEstudioDB)
            .where(PlanEstudioDB.materia_codigo == materia_codigo)
            .where(PlanEstudioDB.carrera_codigo == carrera_codigo)
            .where(PlanEstudioDB.plan_version_id == plan_version_id)
        ).first()
        if existing:
            stats["skipped"] += 1
            continue

        plan = PlanEstudioDB(
            plan_version_id=plan_version_id,
            materia_codigo=materia_codigo,
            carrera_codigo=carrera_codigo,
            anio_plan=anio,
            cuatrimestre_plan=cuatrimestre,
            correlativas=correlativas,
        )
        session.add(plan)
        stats["planes_created"] += 1

    session.commit()
    return stats


# =============================================================================
# Step 4: Load Horarios + Derive Comisiones
# =============================================================================

def _parse_time_value(value) -> time:
    """Parse a time value from Excel (may be datetime.time or string)."""
    if isinstance(value, time):
        return value
    s = str(value).strip()
    parts = s.split(":")
    if len(parts) >= 2:
        return time(int(parts[0]), int(parts[1]))
    raise ValueError(f"Cannot parse time: '{value}'")


def load_horarios(session: Session) -> dict:
    """
    Load horarios from horarios_2C_2025.xlsx with comision derivation.

    Strategy:
    1. Parse all rows, resolving materia codes (codigo_plan -> codigo_guarani fallback)
    2. Group rows by materia
    3. For each materia, derive comision count:
       - n = ceil(total_weekly_hours / horas_semanales)
       - If rows can be evenly split among n comisiones, do so (sorted by dia+hora)
       - Otherwise, fall back to 1 comision with all rows
    4. Create Comision and Horario records
    """
    df = pd.read_excel(HORARIOS_2C_2025)
    stats = {
        "horarios_created": 0, "comisiones_created": 0,
        "rows_total": len(df),
        "rows_null_codigo": 0, "rows_unresolved": 0, "rows_guarani_remap": 0,
        "errors": [], "warnings": [], "comision_flags": [],
        "guarani_remaps": [],
    }

    # Parse rows, resolve codes, group by materia
    materia_rows: dict[str, list[dict]] = {}  # materia_codigo -> list of row dicts

    for idx, row in df.iterrows():
        row_num = idx + 2  # Excel row (header + 0-based)

        # Handle null codigo_plan
        codigo_raw = row["codigo_plan"]
        if pd.isna(codigo_raw):
            stats["rows_null_codigo"] += 1
            stats["warnings"].append(
                f"Fila {row_num}: codigo_plan es null "
                f"(dia={row['dia']}, {row['hora_ingreso']}-{row['hora_egreso']})"
            )
            continue

        codigo = str(codigo_raw).strip()

        # Resolve materia code
        resolution = _resolve_materia_code(session, codigo)

        if resolution.resolution_type == "unresolved":
            stats["rows_unresolved"] += 1
            stats["errors"].append(
                f"Fila {row_num}: '{codigo}' no encontrado como codigo_plan ni codigo_guarani"
            )
            continue

        if resolution.resolution_type == "guarani":
            stats["rows_guarani_remap"] += 1
            stats["guarani_remaps"].append(
                f"'{resolution.original_code}' -> '{resolution.resolved_code}' "
                f"({resolution.materia.nombre})"
            )

        materia_codigo = resolution.resolved_code

        # Parse times
        try:
            hora_inicio = _parse_time_value(row["hora_ingreso"])
            hora_fin = _parse_time_value(row["hora_egreso"])
        except ValueError as e:
            stats["errors"].append(f"Fila {row_num}: {e}")
            continue

        materia_rows.setdefault(materia_codigo, []).append({
            "dia": str(row["dia"]).strip(),
            "hora_inicio": hora_inicio,
            "hora_fin": hora_fin,
            "row_num": row_num,
        })

    # Deduplicate guarani_remaps
    stats["guarani_remaps"] = sorted(set(stats["guarani_remaps"]))

    # For each materia, derive comisiones and create records
    for materia_codigo, rows in materia_rows.items():
        materia = materia_crud.get(session, materia_codigo)
        if materia is None:
            stats["errors"].append(f"Materia '{materia_codigo}' desaparecio de la BD")
            continue

        # Calculate total weekly hours from schedule
        total_hours = sum(
            (r["hora_fin"].hour * 60 + r["hora_fin"].minute -
             r["hora_inicio"].hour * 60 - r["hora_inicio"].minute) / 60
            for r in rows
        )

        n_comisiones, flag = derive_comision_count(total_hours, materia.horas_semanales)

        # Check if rows can be evenly split
        n_rows = len(rows)
        if n_comisiones > 1 and n_rows % n_comisiones != 0:
            stats["comision_flags"].append(
                f"{materia_codigo}: ceil() dio {n_comisiones} comisiones pero "
                f"{n_rows} filas no se dividen equitativamente. Usando 1 comision."
            )
            n_comisiones = 1
            flag = "indivisible"

        if flag in ("ceil", "no_data"):
            stats["comision_flags"].append(
                f"{materia_codigo}: {n_comisiones} comision(es) "
                f"(total_h={total_hours:.1f}, h_sem={materia.horas_semanales}, flag={flag})"
            )

        # Sort rows by dia (weekday order) then hora_inicio
        dia_order = {"Lunes": 0, "Martes": 1, "Miércoles": 2,
                     "Jueves": 3, "Viernes": 4, "Sábado": 5, "Domingo": 6}
        rows_sorted = sorted(rows, key=lambda r: (dia_order.get(r["dia"], 9), r["hora_inicio"]))

        # Split rows into comisiones
        if n_comisiones == 1:
            groups = [rows_sorted]
        else:
            chunk_size = n_rows // n_comisiones
            groups = [
                rows_sorted[i * chunk_size:(i + 1) * chunk_size]
                for i in range(n_comisiones)
            ]

        # Create comisiones and horarios
        for com_idx, group in enumerate(groups):
            com_numero = com_idx + 1
            comision_id = f"{materia_codigo}-C{com_numero}"
            comision_nombre = f"Comision {com_numero}"

            # Check if comision already exists
            existing_com = session.exec(
                select(ComisionDB).where(ComisionDB.id == comision_id)
            ).first()

            if not existing_com:
                comision = ComisionDB(
                    id=comision_id,
                    materia_codigo=materia_codigo,
                    nombre=comision_nombre,
                    numero=com_numero,
                    cupo=materia.cupo or 0,
                )
                session.add(comision)
                session.flush()
                stats["comisiones_created"] += 1
            else:
                comision = existing_com

            for r in group:
                horario_id = f"HOR-{uuid.uuid4().hex[:8].upper()}"
                horario = HorarioDB(
                    id=horario_id,
                    comision_id=comision.id,
                    codigo_materia=materia_codigo,
                    dia=r["dia"],
                    hora_inicio=r["hora_inicio"],
                    hora_fin=r["hora_fin"],
                )
                session.add(horario)
                stats["horarios_created"] += 1

    session.commit()
    return stats


# =============================================================================
# Main
# =============================================================================

def main():
    parser = argparse.ArgumentParser(description="Load initial data from Excel files")
    parser.add_argument("--reset", action="store_true",
                        help="Drop and recreate all tables before loading")
    args = parser.parse_args()

    # Verify input files exist
    for path in [AULAS_FILE, MAESTRO_MATERIAS, MAESTRO_PLANES, HORARIOS_2C_2025]:
        if not path.exists():
            print(f"ERROR: File not found: {path}")
            sys.exit(1)

    if args.reset:
        print("WARNING: --reset will delete ALL existing data.")
        confirm = input("Type 'yes' to confirm: ")
        if confirm != "yes":
            print("Aborted.")
            sys.exit(0)
        # Reset DB by removing the file and re-initializing
        db_path = project_root / "data" / "database.db"
        if db_path.exists():
            db_path.unlink()
            print(f"Deleted {db_path}")

    init_db()
    print("Database initialized.\n")

    with next(get_session()) as session:
        # Step 1: Aulas
        print("=" * 60)
        print("STEP 1: Loading Aulas")
        print("=" * 60)
        a_stats = load_aulas(session)
        print(f"  Created: {a_stats['created']}")
        print(f"  Skipped (existing): {a_stats['skipped']}")
        if a_stats["warnings"]:
            print(f"  Warnings ({len(a_stats['warnings'])}):")
            for w in a_stats["warnings"]:
                print(f"    - {w}")

        # Step 2: Materias
        print(f"\n{'=' * 60}")
        print("STEP 2: Loading Materias")
        print("=" * 60)
        m_stats = load_materias(session)
        print(f"  Created: {m_stats['created']}")
        print(f"  Skipped (existing): {m_stats['skipped']}")
        if m_stats["warnings"]:
            print(f"  Warnings ({len(m_stats['warnings'])}):")
            for w in m_stats["warnings"][:10]:
                print(f"    - {w}")
            if len(m_stats["warnings"]) > 10:
                print(f"    ... and {len(m_stats['warnings']) - 10} more")

        # Step 3: Carreras + Planes
        print(f"\n{'=' * 60}")
        print("STEP 3: Loading Carreras + Planes de Estudio")
        print("=" * 60)
        p_stats = load_carreras_and_planes(session)
        print(f"  Carreras created: {p_stats['carreras_created']}")
        print(f"  Plan versions created: {p_stats['versions_created']}")
        print(f"  Planes created: {p_stats['planes_created']}")
        print(f"  Skipped: {p_stats['skipped']}")
        if p_stats["warnings"]:
            print(f"  Warnings ({len(p_stats['warnings'])}):")
            for w in p_stats["warnings"][:10]:
                print(f"    - {w}")

        # Step 4: Horarios
        print(f"\n{'=' * 60}")
        print("STEP 4: Loading Horarios + Deriving Comisiones")
        print("=" * 60)
        h_stats = load_horarios(session)
        print(f"  Total rows in file: {h_stats['rows_total']}")
        print(f"  Rows with null codigo: {h_stats['rows_null_codigo']}")
        print(f"  Rows unresolved: {h_stats['rows_unresolved']}")
        print(f"  Rows remapped via guarani: {h_stats['rows_guarani_remap']}")
        print(f"  Comisiones created: {h_stats['comisiones_created']}")
        print(f"  Horarios created: {h_stats['horarios_created']}")

        if h_stats["guarani_remaps"]:
            print(f"\n  Guarani remaps ({len(h_stats['guarani_remaps'])}):")
            for r in h_stats["guarani_remaps"]:
                print(f"    - {r}")

        if h_stats["comision_flags"]:
            print(f"\n  Comision derivation flags ({len(h_stats['comision_flags'])}):")
            for f in h_stats["comision_flags"][:20]:
                print(f"    - {f}")
            if len(h_stats["comision_flags"]) > 20:
                print(f"    ... and {len(h_stats['comision_flags']) - 20} more")

        if h_stats["errors"]:
            print(f"\n  Errors ({len(h_stats['errors'])}):")
            for e in h_stats["errors"][:10]:
                print(f"    - {e}")
            if len(h_stats["errors"]) > 10:
                print(f"    ... and {len(h_stats['errors']) - 10} more")

    # Summary
    print(f"\n{'=' * 60}")
    print("SUMMARY")
    print("=" * 60)
    print(f"  Aulas:      {a_stats['created']} created, {a_stats['skipped']} skipped")
    print(f"  Materias:   {m_stats['created']} created, {m_stats['skipped']} skipped")
    print(f"  Carreras:   {p_stats['carreras_created']} created")
    print(f"  Versions:   {p_stats['versions_created']} created")
    print(f"  Planes:     {p_stats['planes_created']} created")
    print(f"  Comisiones: {h_stats['comisiones_created']} created")
    print(f"  Horarios:   {h_stats['horarios_created']} created")
    total_warnings = (len(a_stats["warnings"]) + len(m_stats["warnings"])
                      + len(p_stats["warnings"]) + len(h_stats.get("warnings", [])))
    total_errors = len(h_stats["errors"])
    print(f"  Warnings:   {total_warnings}")
    print(f"  Errors:     {total_errors}")


if __name__ == "__main__":
    main()
