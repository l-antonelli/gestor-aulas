"""
Load initial data from Excel files into the database.

Reads from data/input/:
- aulas/aulas.xlsx              -> Aula records
- Carreras/Maestro materias.xlsx -> Materia records
- Carreras/Maestro planes.xlsx   -> Carrera + PlanEstudio records

Los cronogramas de horarios se cargan desde la pagina de Planes en la UI,
donde se asocian a un plan de cursada (evitando datos huerfanos).

Usage:
    python -m scripts.load_initial_data [--reset]

    --reset: Drop and recreate all tables before loading (WARNING: deletes all data)
"""

import argparse
import sys
import uuid
from pathlib import Path

import pandas as pd
from sqlmodel import Session, select

# Add project root to path
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

from src.database.connection import get_session, init_db
from src.database.models import (
    AulaDB, CarreraDB, MateriaDB, PlanEstudioDB,
    PlanCarreraVersionDB,
)
from src.database.crud import aula_crud, materia_crud, carrera_crud

DATA_DIR = project_root / "data" / "input"
AULAS_FILE = DATA_DIR / "aulas" / "aulas.xlsx"
MAESTRO_MATERIAS = DATA_DIR / "Carreras" / "Maestro materias.xlsx"
MAESTRO_PLANES = DATA_DIR / "Carreras" / "Maestro planes.xlsx"


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
# Main
# =============================================================================

def main():
    parser = argparse.ArgumentParser(description="Load initial data from Excel files")
    parser.add_argument("--reset", action="store_true",
                        help="Drop and recreate all tables before loading")
    args = parser.parse_args()

    # Verify input files exist
    for path in [AULAS_FILE, MAESTRO_MATERIAS, MAESTRO_PLANES]:
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

    # Summary
    print(f"\n{'=' * 60}")
    print("SUMMARY")
    print("=" * 60)
    print(f"  Aulas:      {a_stats['created']} created, {a_stats['skipped']} skipped")
    print(f"  Materias:   {m_stats['created']} created, {m_stats['skipped']} skipped")
    print(f"  Carreras:   {p_stats['carreras_created']} created")
    print(f"  Versions:   {p_stats['versions_created']} created")
    print(f"  Planes:     {p_stats['planes_created']} created")
    total_warnings = (len(a_stats["warnings"]) + len(m_stats["warnings"])
                      + len(p_stats["warnings"]))
    print(f"  Warnings:   {total_warnings}")
    print()
    print("NOTA: Los cronogramas de horarios se cargan desde la pagina de Planes en la UI.")


if __name__ == "__main__":
    main()
