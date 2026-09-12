"""Auditoría de `PlanEstudioDB` contra la fuente de verdad en Excel.

Fuente de verdad: ``data/input/Carreras/BD Study Plans and Subjects.xlsx``

Cada hoja del Excel representa el plan de una carrera (o un conjunto
de optativas). El script:

1. Parsea cada hoja según su layout (hay 3 formatos distintos).
2. Compara contra la versión **activa** de ``PlanCarreraVersionDB``
   de la carrera correspondiente en la base.
3. Genera un reporte a ``project/2. Desarrollo/AUDITORIA_PLANES_<fecha>.md``
   con 4 secciones por carrera:

   - **Faltantes en DB**: materias que están en el Excel y no en la DB.
   - **Sobrantes en DB**: materias que están en la DB y no en el Excel.
   - **Divergentes**: mismo código, distinto año/cuatri/optativa.
   - **Coincidentes**: total OK (solo cuenta, no lista).

**No aplica ningún cambio a la DB** — sólo reporta. Para sincronizar
después, se puede escribir un script aplicador separado que consuma
el reporte con confirmación del usuario.

Uso:
    python -m scripts.audit_planes_estudio
"""
from __future__ import annotations

import re
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path
from typing import Optional

import pandas as pd
from sqlmodel import Session, select

from src.database.connection import engine
from src.database.models import (
    CarreraDB,
    MateriaDB,
    PlanCarreraVersionDB,
    PlanEstudioDB,
)

EXCEL_PATH = Path(
    "data/input/Carreras/BD Study Plans and Subjects.xlsx"
)
REPORT_DIR = Path("project/2. Desarrollo")

# ============================================================================
# Mapeo hoja → carrera. Las hojas que son "listados de optativas por
# carrera" tienen su propia carrera en la columna 0.
# ============================================================================
HOJA_A_CARRERA = {
    "Agrimensura": "G",
    "Civil": "C",
    "Electrica": "E",
    "Electronica": "A",
    "Industrial": "I",
    "Mecanica": "M",
    "Lic. en física": "LF",
    "Lic. en matematica": "LM",
    "Prof. matematica": "PM",
    "Prof. fisica": "PF",
    "LCC": "R",
    "TUIA": "IA",
    # Optativas específicas por carrera:
    "EPF": "PF",
    "IAE": "IA",
    "ELA": "A",
    "ELC": "C",
    "ELE": "E",
    "ELG": "G",
    "ELI": "I",
    "ELM": "M",
    "ELR": "R",
    "ELLF": "LF",
    "ELLM": "LM",
}
# La hoja "Electivas" distribuye por columna 0 (código de carrera en Excel).
# Mapeo del código que aparece en Excel al codigo de la DB:
CARRERA_EXCEL_A_DB = {
    "A": "A", "C": "C", "E": "E", "G": "G", "I": "I", "M": "M",
    "LF": "LF", "LM": "LM", "PF": "PF", "PM": "PM",
    "R": "R", "IA": "IA",
    "LC": "R",  # variante en algunas hojas
}


@dataclass
class MateriaExcel:
    """Fila de plan tal como está en el Excel."""
    codigo: str
    nombre: str
    anio: int
    cuatri: str  # "1C" | "2C" | "anual"
    optativa: bool
    hoja: str
    carrera_codigo: str


@dataclass
class MateriaDBRow:
    """Entrada en PlanEstudioDB."""
    codigo: str
    nombre: str
    anio: Optional[int]
    cuatri: Optional[str]
    optativa: bool


@dataclass
class ReporteCarrera:
    carrera_codigo: str
    carrera_nombre: str
    faltantes: list[MateriaExcel] = field(default_factory=list)
    sobrantes: list[MateriaDBRow] = field(default_factory=list)
    divergentes: list[tuple[MateriaExcel, MateriaDBRow]] = field(
        default_factory=list,
    )
    coincidentes: int = 0

    @property
    def total_diffs(self) -> int:
        return (
            len(self.faltantes)
            + len(self.sobrantes)
            + len(self.divergentes)
        )


# ============================================================================
# Parsers por layout
# ============================================================================


def _normalizar_cuatri(raw) -> Optional[str]:
    """Devuelve '1C' | '2C' | 'anual' | None."""
    if raw is None or (isinstance(raw, float) and pd.isna(raw)):
        return None
    s = str(raw).strip().lower()
    if s in ("", "-", "nan"):
        return None
    if "anual" in s:
        return "anual"
    # "1C", "1º cuat.", "1er cuatri", "1º cuatrimestre"
    if re.search(r"\b1", s) or "1º" in s or s.startswith("1"):
        return "1C"
    if re.search(r"\b2", s) or "2º" in s or s.startswith("2"):
        return "2C"
    return None


def _normalizar_anio(raw) -> Optional[int]:
    if raw is None or (isinstance(raw, float) and pd.isna(raw)):
        return None
    s = str(raw).strip()
    if s in ("", "-", "nan"):
        return None
    try:
        return int(float(s))
    except (ValueError, TypeError):
        return None


def _norm_codigo(raw) -> Optional[str]:
    """Normaliza el código: strip + upper.

    Los códigos en la DB tienen espacios internos ('IA 1.1'), no se
    tocan — sino generamos falsos positivos por diferencia formal."""
    if raw is None or (isinstance(raw, float) and pd.isna(raw)):
        return None
    s = str(raw).strip().upper()
    return s or None


def _find_header_row(df: pd.DataFrame, cols_esperadas: list[str]) -> Optional[int]:
    """Busca la fila que contiene los headers esperados (case-insensitive)."""
    for i in range(min(10, len(df))):
        row_values = [
            str(v).strip().lower()
            for v in df.iloc[i].tolist()
            if not (isinstance(v, float) and pd.isna(v))
        ]
        matches = sum(
            1 for c in cols_esperadas
            if any(c.lower() in v for v in row_values)
        )
        if matches >= 2:
            return i
    return None


def parse_hoja_ingenieria(
    df: pd.DataFrame, hoja: str, carrera_codigo: str,
) -> list[MateriaExcel]:
    """Layout: Código | Año | Cuatrimestre | Correlativas | Actividad | Hs.Sem | Hs.Tot"""
    header_row = _find_header_row(df, ["código", "año", "cuatri"])
    if header_row is None:
        return []
    resultados: list[MateriaExcel] = []
    for i in range(header_row + 1, len(df)):
        row = df.iloc[i].tolist()
        codigo = _norm_codigo(row[0])
        anio = _normalizar_anio(row[1])
        cuatri = _normalizar_cuatri(row[2])
        nombre = str(row[4]).strip() if len(row) > 4 and not (
            isinstance(row[4], float) and pd.isna(row[4])
        ) else ""
        if not codigo or anio is None or cuatri is None:
            continue
        resultados.append(MateriaExcel(
            codigo=codigo, nombre=nombre, anio=anio, cuatri=cuatri,
            optativa=False, hoja=hoja, carrera_codigo=carrera_codigo,
        ))
    return resultados


def parse_hoja_lcc_tuia(
    df: pd.DataFrame, hoja: str, carrera_codigo: str,
) -> list[MateriaExcel]:
    """Layout: Código | Nombre | (Hs.Sem | Hs.Tot | Correlativas |) Cuatri | Año

    LCC y TUIA tienen distinto orden de columnas pero misma idea.
    Detectamos por posición del header 'año' y 'cuatrimestre'.
    """
    header_row = _find_header_row(df, ["código", "año", "cuatri"])
    if header_row is None:
        return []
    # Encontrar índices de las columnas.
    header = df.iloc[header_row].tolist()

    def _find_col(pat: str) -> Optional[int]:
        for j, h in enumerate(header):
            if isinstance(h, str) and pat in h.lower():
                return j
        return None

    idx_codigo = _find_col("código")
    idx_nombre = _find_col("actividad")
    if idx_nombre is None:
        idx_nombre = _find_col("nombre")
    idx_anio = _find_col("año")
    idx_cuatri = _find_col("cuatri")
    if None in (idx_codigo, idx_anio, idx_cuatri):
        return []

    resultados: list[MateriaExcel] = []
    for i in range(header_row + 1, len(df)):
        row = df.iloc[i].tolist()
        codigo = _norm_codigo(row[idx_codigo])
        anio = _normalizar_anio(row[idx_anio])
        cuatri = _normalizar_cuatri(row[idx_cuatri])
        nombre = ""
        if idx_nombre is not None and idx_nombre < len(row):
            val = row[idx_nombre]
            if not (isinstance(val, float) and pd.isna(val)):
                nombre = str(val).strip()
        if not codigo or anio is None or cuatri is None:
            continue
        resultados.append(MateriaExcel(
            codigo=codigo, nombre=nombre, anio=anio, cuatri=cuatri,
            optativa=False, hoja=hoja, carrera_codigo=carrera_codigo,
        ))
    return resultados


def parse_hoja_optativas(
    df: pd.DataFrame, hoja: str, carrera_codigo: str,
) -> list[MateriaExcel]:
    """Hojas de optativas específicas (EPF, IAE, ELA, ELC, ...).

    Layout: <CarreraEnCol0> | Código | Nombre | Año | Período | ...
    Puede tener el año presente y período con formato "1º Cuatrimestre"
    o "-" (sin cuatrimestre asignado). Cuando cuatri es "-" o vacío,
    asumimos '1C' como default por convención — el usuario puede
    revisar en el reporte.
    """
    header_row = _find_header_row(df, ["código", "año"])
    if header_row is None:
        return []
    header = df.iloc[header_row].tolist()

    def _find_col(*pats: str) -> Optional[int]:
        for j, h in enumerate(header):
            if not isinstance(h, str):
                continue
            hl = h.lower()
            for p in pats:
                if p in hl:
                    return j
        return None

    idx_codigo = _find_col("código")
    idx_nombre = _find_col("nombre", "actividad")
    idx_anio = _find_col("año")
    idx_cuatri = _find_col("período", "cuatri")
    if idx_codigo is None or idx_anio is None:
        return []

    resultados: list[MateriaExcel] = []
    for i in range(header_row + 1, len(df)):
        row = df.iloc[i].tolist()
        codigo = _norm_codigo(row[idx_codigo])
        anio = _normalizar_anio(row[idx_anio])
        cuatri = None
        if idx_cuatri is not None and idx_cuatri < len(row):
            cuatri = _normalizar_cuatri(row[idx_cuatri])
        if cuatri is None:
            # Convención para optativas sin cuatri asignado: '1C'
            cuatri = "1C"
        nombre = ""
        if idx_nombre is not None and idx_nombre < len(row):
            val = row[idx_nombre]
            if not (isinstance(val, float) and pd.isna(val)):
                nombre = str(val).strip()
        if not codigo or anio is None:
            continue
        resultados.append(MateriaExcel(
            codigo=codigo, nombre=nombre, anio=anio, cuatri=cuatri,
            optativa=True, hoja=hoja, carrera_codigo=carrera_codigo,
        ))
    return resultados


def parse_hoja_electivas(df: pd.DataFrame, hoja: str) -> list[MateriaExcel]:
    """Hoja 'Electivas': columna 0 = carrera, código en col 1, año col 2, período col 3."""
    header_row = _find_header_row(df, ["código", "año"])
    if header_row is None:
        return []
    resultados: list[MateriaExcel] = []
    for i in range(header_row + 1, len(df)):
        row = df.iloc[i].tolist()
        carrera_excel = str(row[0]).strip().upper() if not (
            isinstance(row[0], float) and pd.isna(row[0])
        ) else ""
        carrera_db = CARRERA_EXCEL_A_DB.get(carrera_excel)
        if not carrera_db:
            continue
        codigo = _norm_codigo(row[1])
        anio = _normalizar_anio(row[2])
        cuatri = _normalizar_cuatri(row[3]) if len(row) > 3 else None
        if cuatri is None:
            cuatri = "1C"
        nombre = str(row[4]).strip() if len(row) > 4 and not (
            isinstance(row[4], float) and pd.isna(row[4])
        ) else ""
        if not codigo or anio is None:
            continue
        resultados.append(MateriaExcel(
            codigo=codigo, nombre=nombre, anio=anio, cuatri=cuatri,
            optativa=True, hoja=hoja, carrera_codigo=carrera_db,
        ))
    return resultados


# ============================================================================
# Dispatcher: elige el parser según la hoja.
# ============================================================================


HOJAS_INGENIERIAS = {
    "Agrimensura", "Civil", "Electrica", "Electronica",
    "Industrial", "Mecanica",
}
HOJAS_LICPROF = {
    "Lic. en física", "Lic. en matematica",
    "Prof. matematica", "Prof. fisica", "LCC", "TUIA",
}
HOJAS_OPTATIVAS_ESPECIFICAS = {
    "EPF", "IAE", "ELA", "ELC", "ELE", "ELG", "ELI",
    "ELM", "ELR", "ELLF", "ELLM",
}


def parse_excel(path: Path) -> dict[str, list[MateriaExcel]]:
    """Parsea todas las hojas y agrupa las materias por carrera_codigo."""
    xl = pd.ExcelFile(path)
    por_carrera: dict[str, list[MateriaExcel]] = defaultdict(list)
    for hoja in xl.sheet_names:
        df = pd.read_excel(path, sheet_name=hoja, header=None)
        if hoja in HOJAS_INGENIERIAS:
            carrera_db = HOJA_A_CARRERA[hoja]
            for m in parse_hoja_ingenieria(df, hoja, carrera_db):
                por_carrera[carrera_db].append(m)
        elif hoja in HOJAS_LICPROF:
            carrera_db = HOJA_A_CARRERA[hoja]
            for m in parse_hoja_lcc_tuia(df, hoja, carrera_db):
                por_carrera[carrera_db].append(m)
        elif hoja in HOJAS_OPTATIVAS_ESPECIFICAS:
            carrera_db = HOJA_A_CARRERA[hoja]
            for m in parse_hoja_optativas(df, hoja, carrera_db):
                por_carrera[carrera_db].append(m)
        elif hoja == "Electivas":
            for m in parse_hoja_electivas(df, hoja):
                por_carrera[m.carrera_codigo].append(m)
        else:
            print(f"[WARN] hoja sin parser: {hoja!r}")
    return dict(por_carrera)


# ============================================================================
# Auditoría contra la DB
# ============================================================================


def _cargar_db_por_carrera(
    session: Session,
) -> dict[str, tuple[CarreraDB, list[MateriaDBRow]]]:
    """Devuelve carrera_codigo → (CarreraDB, lista de entradas del plan activo)."""
    carreras = list(session.exec(select(CarreraDB)).all())
    materias = {
        m.codigo: m for m in session.exec(select(MateriaDB)).all()
    }

    result: dict[str, tuple[CarreraDB, list[MateriaDBRow]]] = {}
    for car in carreras:
        pv_activa = session.exec(
            select(PlanCarreraVersionDB).where(
                PlanCarreraVersionDB.carrera_codigo == car.codigo,
                PlanCarreraVersionDB.active == True,  # noqa: E712
            ).limit(1)
        ).first()
        if pv_activa is None:
            result[car.codigo] = (car, [])
            continue
        entries = list(session.exec(
            select(PlanEstudioDB).where(
                PlanEstudioDB.plan_version_id == pv_activa.id,
            )
        ).all())
        rows = []
        for e in entries:
            mat = materias.get(e.materia_codigo)
            rows.append(MateriaDBRow(
                codigo=e.materia_codigo,
                nombre=mat.nombre if mat else "?",
                anio=e.anio_plan,
                cuatri=e.cuatrimestre_plan,
                optativa=e.optativa,
            ))
        result[car.codigo] = (car, rows)
    return result


def _cuatri_equivalentes(a: Optional[str], b: Optional[str]) -> bool:
    """Iguala '1C'/'1c'/'anual' vs 'Anual', etc."""
    if a is None and b is None:
        return True
    if a is None or b is None:
        return False
    return a.strip().lower() == b.strip().lower()


def comparar(
    excel: list[MateriaExcel], db: list[MateriaDBRow], carrera: CarreraDB,
) -> ReporteCarrera:
    r = ReporteCarrera(
        carrera_codigo=carrera.codigo, carrera_nombre=carrera.nombre,
    )
    # Index por código, para diff bidireccional. Un código puede
    # aparecer más de una vez en Excel u en DB (ej: apareció duplicada)
    # pero típicamente cada carrera tiene una única aparición por
    # materia — chequeamos duplicados aparte.
    excel_by_code: dict[str, MateriaExcel] = {}
    excel_duplicados: list[MateriaExcel] = []
    for m in excel:
        if m.codigo in excel_by_code:
            excel_duplicados.append(m)
        else:
            excel_by_code[m.codigo] = m

    db_by_code: dict[str, MateriaDBRow] = {}
    for m in db:
        db_by_code.setdefault(m.codigo, m)

    excel_codes = set(excel_by_code.keys())
    db_codes = set(db_by_code.keys())

    for code in sorted(excel_codes - db_codes):
        r.faltantes.append(excel_by_code[code])
    for code in sorted(db_codes - excel_codes):
        r.sobrantes.append(db_by_code[code])

    for code in sorted(excel_codes & db_codes):
        ex = excel_by_code[code]
        d = db_by_code[code]
        misma = (
            ex.anio == d.anio
            and _cuatri_equivalentes(ex.cuatri, d.cuatri)
            and ex.optativa == d.optativa
        )
        if misma:
            r.coincidentes += 1
        else:
            r.divergentes.append((ex, d))
    return r


# ============================================================================
# Reporte markdown
# ============================================================================


def _fmt_ubicacion(anio, cuatri, optativa) -> str:
    tag = " (opt)" if optativa else ""
    return f"{anio}°{cuatri}{tag}"


def render_reporte(reportes: list[ReporteCarrera]) -> str:
    lines: list[str] = []
    lines.append(
        f"# Auditoría de planes de estudio ({date.today().isoformat()})"
    )
    lines.append("")
    lines.append(
        f"**Fuente de verdad**: `{EXCEL_PATH}`"
    )
    lines.append("")
    lines.append("## Resumen por carrera")
    lines.append("")
    lines.append(
        "| Carrera | Coincidentes | Faltantes en DB | Sobrantes en DB "
        "| Divergentes |"
    )
    lines.append("|---|---|---|---|---|")
    for r in reportes:
        lines.append(
            f"| `{r.carrera_codigo}` — {r.carrera_nombre} "
            f"| {r.coincidentes} "
            f"| {len(r.faltantes)} "
            f"| {len(r.sobrantes)} "
            f"| {len(r.divergentes)} |"
        )
    lines.append("")

    for r in reportes:
        if r.total_diffs == 0:
            continue
        lines.append(f"## `{r.carrera_codigo}` — {r.carrera_nombre}")
        lines.append("")

        if r.faltantes:
            lines.append(
                f"### Faltantes en DB ({len(r.faltantes)})"
            )
            lines.append("")
            lines.append(
                "Materias que aparecen en el Excel pero no están en el "
                "plan activo."
            )
            lines.append("")
            lines.append("| Código | Nombre | Ubicación (Excel) | Hoja |")
            lines.append("|---|---|---|---|")
            for m in r.faltantes:
                lines.append(
                    f"| `{m.codigo}` | {m.nombre} "
                    f"| {_fmt_ubicacion(m.anio, m.cuatri, m.optativa)} "
                    f"| {m.hoja} |"
                )
            lines.append("")

        if r.sobrantes:
            lines.append(
                f"### Sobrantes en DB ({len(r.sobrantes)})"
            )
            lines.append("")
            lines.append(
                "Materias que están en el plan activo pero no aparecen "
                "en el Excel — candidatas a borrar."
            )
            lines.append("")
            lines.append("| Código | Nombre | Ubicación (DB) |")
            lines.append("|---|---|---|")
            for m in r.sobrantes:
                lines.append(
                    f"| `{m.codigo}` | {m.nombre} "
                    f"| {_fmt_ubicacion(m.anio, m.cuatri, m.optativa)} |"
                )
            lines.append("")

        if r.divergentes:
            lines.append(
                f"### Divergentes ({len(r.divergentes)})"
            )
            lines.append("")
            lines.append(
                "Mismo código, distinta ubicación (año/cuatri/optativa) "
                "entre Excel y DB. La DB tiene la ubicación incorrecta."
            )
            lines.append("")
            lines.append(
                "| Código | Nombre | Excel (verdad) | DB (actual) | Hoja |"
            )
            lines.append("|---|---|---|---|---|")
            for ex, d in r.divergentes:
                lines.append(
                    f"| `{ex.codigo}` | {ex.nombre or d.nombre} "
                    f"| **{_fmt_ubicacion(ex.anio, ex.cuatri, ex.optativa)}** "
                    f"| {_fmt_ubicacion(d.anio, d.cuatri, d.optativa)} "
                    f"| {ex.hoja} |"
                )
            lines.append("")

    return "\n".join(lines) + "\n"


def main() -> None:
    if not EXCEL_PATH.exists():
        raise SystemExit(f"No existe el Excel: {EXCEL_PATH}")

    print(f"Leyendo Excel: {EXCEL_PATH}")
    excel_data = parse_excel(EXCEL_PATH)
    total_excel = sum(len(v) for v in excel_data.values())
    print(
        f"Excel: {total_excel} filas en total, "
        f"{len(excel_data)} carreras con datos."
    )

    with Session(engine) as session:
        db_data = _cargar_db_por_carrera(session)
        print(f"DB: {len(db_data)} carreras con plan activo.")

        reportes: list[ReporteCarrera] = []
        for car_cod, (car, db_rows) in sorted(db_data.items()):
            excel_rows = excel_data.get(car_cod, [])
            r = comparar(excel_rows, db_rows, car)
            reportes.append(r)
            print(
                f"  {car_cod:<4}: coincidentes={r.coincidentes}, "
                f"faltantes={len(r.faltantes)}, "
                f"sobrantes={len(r.sobrantes)}, "
                f"divergentes={len(r.divergentes)}"
            )

        # Carreras en Excel pero no en DB
        for car_cod in sorted(set(excel_data) - set(db_data)):
            print(
                f"  [WARN] hay {len(excel_data[car_cod])} entradas en "
                f"Excel para carrera '{car_cod}' pero no existe en DB"
            )

    md = render_reporte(reportes)
    REPORT_DIR.mkdir(parents=True, exist_ok=True)
    out = REPORT_DIR / f"AUDITORIA_PLANES_{date.today().isoformat()}.md"
    out.write_text(md, encoding="utf-8")
    print(f"\nReporte escrito: {out}")


if __name__ == "__main__":
    main()
