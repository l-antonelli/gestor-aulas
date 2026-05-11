"""
Carga datos historicos de inscriptos desde data/input/inscriptos/final_df.xlsx.

Estrategia de matcheo en 3 capas:
  1. Match directo por codigo (328 materias)
  2. Normalizacion por formato de codigo — reglas por carrera:
     - TUIA:           IAxy   -> IA x.y
     - Prof. Fisica:   PFxy   -> PFx.y
     - Lic. Fisica:    F18dd  -> LF{dd}
     - Lic. Matematica: L18dd -> LM{dd}
     - Prof. Matematica: P18dd -> PM{dd}
  3. Match por nombre dentro de la misma carrera (LCC T10xx -> R-xxx,
     curso ingreso CI24xx -> CE) + tabla hardcodeada para typos.

NO se matchea por nombre entre carreras distintas (ej: "Fisica II" existe
en Lic. Fisica, Prof. Fisica e Ingenierias como materias diferentes).

Usage:
    python -m scripts.load_inscriptos [--reset]

    --reset: Borra todos los registros de inscripciones_historicas antes de cargar.
"""

import argparse
import re
import sys
from pathlib import Path

import pandas as pd
from sqlmodel import select

project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

from src.database.connection import get_session, init_db
from src.database.models import InscripcionHistoricaDB, MateriaDB

INSCRIPTOS_FILE = project_root / "data" / "input" / "inscriptos" / "final_df.xlsx"

# Mapeo manual para codigos con typos o diferencias menores de nombre
_HARDCODED_MAP = {
    "T1001": "R-111",   # Algebra vs Álgebra
    "T1004": "R-121",   # Algebra y Geometría Analitica vs Analítica
    "T1007": "R-211",   # Algebra vs Álgebra
    "T1008": "R-212",   # Algoritmo vs Algoritmos
    "T1016": "R-322",   # Lenguaje de Progamación vs Lenguajes de Programación
    "T1020": "R-324",   # Bases de Datos vs Base de Datos
    "T1021": "R-411",   # del Software vs de Software
    "T1024": "R-421",   # del Software vs de Software
    "T1026": "R-423",   # Complemento vs Complementos
    "T1031": "PF3.6",   # Examen de Suficiencia de Inglés (compartida)
}


def _normalize_code(code: str) -> str | None:
    """Intenta normalizar un codigo de inscriptos al formato de la DB."""
    if code in _HARDCODED_MAP:
        return _HARDCODED_MAP[code]

    # TUIA: IA11 -> IA 1.1
    m = re.match(r'^IA(\d)(\d)$', code)
    if m:
        return f"IA {m.group(1)}.{m.group(2)}"

    # Prof Fisica: PF14 -> PF1.4
    m = re.match(r'^PF(\d)(\d)$', code)
    if m:
        return f"PF{m.group(1)}.{m.group(2)}"

    # Lic Fisica: F1801 -> LF1
    m = re.match(r'^F18(\d{2})$', code)
    if m:
        return f"LF{int(m.group(1))}"

    # Lic Matematica: L1801 -> LM1
    m = re.match(r'^L18(\d{2})$', code)
    if m:
        return f"LM{int(m.group(1))}"

    # Prof Matematica: P1801 -> PM1
    m = re.match(r'^P18(\d{2})$', code)
    if m:
        return f"PM{int(m.group(1))}"

    return None


def _build_name_map(mat_codes_names: list[tuple[str, str]], prefixes: list[str]) -> dict[str, str]:
    """Arma un mapa nombre_lower -> codigo para materias con prefijos dados."""
    result = {}
    for cod, nom in mat_codes_names:
        if any(cod.startswith(p) for p in prefixes):
            result[nom.strip().lower()] = cod
    return result


def load_inscriptos(reset: bool = False):
    init_db()

    if not INSCRIPTOS_FILE.exists():
        print(f"ERROR: No se encontro {INSCRIPTOS_FILE}")
        sys.exit(1)

    df = pd.read_excel(INSCRIPTOS_FILE)
    print(f"Leidos {len(df)} registros de {INSCRIPTOS_FILE.name}")

    with next(get_session()) as session:
        mat_data = session.exec(select(MateriaDB.codigo, MateriaDB.nombre)).all()

    mat_codes = {cod for cod, _ in mat_data}
    print(f"Materias en DB: {len(mat_codes)}")

    # Build name-based maps for same-carrera matching
    r_by_name = _build_name_map(mat_data, ["R-"])
    ce_by_name = _build_name_map(mat_data, ["CE"])

    # Build full code mapping: insc_code -> db_code
    all_insc_codes = set(df["codigo"].unique())
    code_map: dict[str, str] = {}
    nombre_insc = df.drop_duplicates("codigo").set_index("codigo")["actividad"]

    for c in all_insc_codes:
        if c in mat_codes:
            # Layer 1: direct match
            code_map[c] = c
            continue

        norm = _normalize_code(c)
        if norm and norm in mat_codes:
            # Layer 2: format normalization
            code_map[c] = norm
            continue

        # Layer 3: name match within same carrera
        nom = nombre_insc.get(c, "").strip().lower()
        if c.startswith("T10") and nom in r_by_name:
            code_map[c] = r_by_name[nom]
        elif c.startswith("CI24") and nom in ce_by_name:
            code_map[c] = ce_by_name[nom]

    mapped_codes = {c for c in all_insc_codes if c in code_map}
    unmapped_codes = sorted(all_insc_codes - mapped_codes)
    n_direct = sum(1 for c in mapped_codes if code_map[c] == c)
    n_normalized = len(mapped_codes) - n_direct

    print(f"\nMatch directo: {n_direct} codigos")
    print(f"Normalizados: {n_normalized} codigos")
    print(f"Sin match: {len(unmapped_codes)} codigos")

    # Aggregate: sum inscriptos per (mapped) materia+year+period
    agg = (
        df.groupby(["codigo", "year", "period"])["cant._inscriptos"]
        .sum()
        .reset_index()
    )

    # Apply mapping
    agg["db_codigo"] = agg["codigo"].map(code_map)
    matched = agg[agg["db_codigo"].notna()].copy()
    unmatched = agg[agg["db_codigo"].isna()]

    # Re-aggregate in case multiple insc codes map to same db code
    matched = (
        matched.groupby(["db_codigo", "year", "period"])["cant._inscriptos"]
        .sum()
        .reset_index()
    )

    print(f"\nRegistros a cargar: {len(matched)} ({matched['db_codigo'].nunique()} materias)")

    with next(get_session()) as session:
        if reset:
            from sqlmodel import delete
            session.exec(delete(InscripcionHistoricaDB))
            session.commit()
            print("Tabla inscripciones_historicas vaciada.")

        created = 0
        updated = 0
        for _, row in matched.iterrows():
            db_code = row["db_codigo"]
            anio = int(row["year"])
            period = row["period"]
            inscriptos = int(row["cant._inscriptos"])

            existing = session.get(InscripcionHistoricaDB, (db_code, anio, period))
            if existing:
                existing.inscriptos = inscriptos
                session.add(existing)
                updated += 1
            else:
                session.add(InscripcionHistoricaDB(
                    materia_codigo=db_code,
                    anio=anio,
                    cuatrimestre=period,
                    inscriptos=inscriptos,
                ))
                created += 1

        session.commit()

    print(f"\nResultado: {created} creados, {updated} actualizados.")

    if unmapped_codes:
        print(f"\n{'='*60}")
        print(f"CODIGOS SIN MATCH ({len(unmapped_codes)}):")
        print(f"{'='*60}")
        unmatched_summary = (
            unmatched.groupby("codigo")["cant._inscriptos"]
            .sum()
            .reset_index()
            .sort_values("cant._inscriptos", ascending=False)
        )
        for _, row in unmatched_summary.iterrows():
            nombre = nombre_insc.get(row["codigo"], "?")
            print(f"  {row['codigo']:12s} {nombre:50s} (total: {int(row['cant._inscriptos'])})")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Carga inscriptos historicos")
    parser.add_argument("--reset", action="store_true", help="Borrar datos existentes")
    args = parser.parse_args()
    load_inscriptos(reset=args.reset)
