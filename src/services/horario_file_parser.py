"""Parser for horario data from CSV/Excel files."""

from datetime import time
from typing import List

import pandas as pd

from src.services.horario_loading_service import HorarioInput

# Column name aliases: canonical_name -> list of accepted alternatives
COLUMN_ALIASES = {
    "codigo_materia": ["codigo_plan", "materia", "cod_materia"],
    "comision": ["codigo_comision", "comision_nombre", "cod_comision"],
    "dia": ["dia_semana"],
    "hora_inicio": ["hora_ingreso", "inicio"],
    "hora_fin": ["hora_egreso", "fin"],
    "tipo_clase": ["tipo", "modalidad_clase"],
    "virtual": ["virtualidad", "es_virtual"],
}


def _parse_tipo_clase(value) -> str | None:
    """Normaliza el tipo de clase leído del archivo.

    Acepta 'teorica', 'laboratorio' (case-insensitive, con o sin
    tilde). Vacío o NaN se traduce a None (= por determinar).
    """
    if value is None:
        return None
    s = str(value).strip().lower()
    if s == "" or s == "nan":
        return None
    # Normalizar tildes básicas
    s_norm = s.replace("teórica", "teorica").replace("ó", "o")
    if s_norm in ("teorica", "t", "teoría", "teoria"):
        return "teorica"
    if s_norm in ("laboratorio", "lab", "l"):
        return "laboratorio"
    raise ValueError(
        f"tipo_clase '{value}' no reconocido "
        "(esperado: teorica, laboratorio o vacio)"
    )


def _parse_virtual(value) -> bool | None:
    """Normaliza el override de virtual leído del archivo.

    Acepta 'SI'/'NO' de la plantilla (case-insensitive), plus
    variantes booleanas (True/False, 1/0, si/no, sí/no). Vacío o
    NaN se traduce a None (= heredar).
    """
    if value is None:
        return None
    if isinstance(value, bool):
        return value
    s = str(value).strip().lower()
    if s == "" or s == "nan":
        return None
    if s in ("si", "sí", "s", "true", "1", "yes", "y"):
        return True
    if s in ("no", "n", "false", "0"):
        return False
    raise ValueError(
        f"virtual '{value}' no reconocido "
        "(esperado: SI, NO o vacio)"
    )


def _normalize_columns(df: pd.DataFrame) -> pd.DataFrame:
    """Normalize column names, applying aliases for known alternatives."""
    df.columns = [c.strip().lower().replace(" ", "_") for c in df.columns]

    rename_map = {}
    for canonical, aliases in COLUMN_ALIASES.items():
        if canonical not in df.columns:
            for alias in aliases:
                if alias in df.columns:
                    rename_map[alias] = canonical
                    break

    if rename_map:
        df = df.rename(columns=rename_map)

    return df


def parse_horarios_file(file) -> tuple[List[HorarioInput], list[str]]:
    """
    Parse a CSV or Excel file into HorarioInput objects.

    Accepted columns (with aliases):
    - codigo_materia (or: codigo_plan, materia, cod_materia)
    - comision (or: codigo_comision, comision_nombre, cod_comision)
    - dia (or: dia_semana)
    - hora_inicio (or: hora_ingreso, inicio)
    - hora_fin (or: hora_egreso, fin)

    Args:
        file: Streamlit UploadedFile (has .name attribute)

    Returns:
        Tuple of (list of HorarioInput, list of parse errors)
    """
    errors: list[str] = []
    inputs: list[HorarioInput] = []

    try:
        if file.name.endswith(".csv"):
            df = pd.read_csv(file)
        elif file.name.endswith((".xlsx", ".xls")):
            # Si el archivo tiene múltiples hojas (por ejemplo la
            # plantilla generada por el sistema, que trae
            # 'Instrucciones' + 'Horarios' + hojas ocultas), preferir
            # la hoja llamada 'Horarios'. Sino, fallback a la primera.
            # Cover: sin esto, pandas leería 'Instrucciones' porque
            # es la primera hoja del workbook.
            _all_sheets = pd.read_excel(file, sheet_name=None)
            if "Horarios" in _all_sheets:
                df = _all_sheets["Horarios"]
            else:
                # Primera hoja no oculta (nombre sin prefijo '_').
                _visibles = [
                    name for name in _all_sheets
                    if not name.startswith("_") and name != "Instrucciones"
                ]
                _preferida = _visibles[0] if _visibles else next(iter(_all_sheets))
                df = _all_sheets[_preferida]
        else:
            return [], [f"Formato no soportado: {file.name}. Use CSV o Excel (.xlsx)"]
    except Exception as e:
        return [], [f"Error leyendo archivo: {e}"]

    df = _normalize_columns(df)

    required = {"codigo_materia", "dia", "hora_inicio", "hora_fin"}
    missing = required - set(df.columns)
    if missing:
        return [], [f"Columnas faltantes: {', '.join(sorted(missing))}"]

    has_comision = "comision" in df.columns
    has_tipo = "tipo_clase" in df.columns
    has_virtual = "virtual" in df.columns

    for idx, row in df.iterrows():
        row_num = idx + 2  # +2: 0-based idx + header row

        try:
            codigo_raw = str(row["codigo_materia"]).strip()
            if not codigo_raw or codigo_raw.lower() == "nan":
                errors.append(f"Fila {row_num}: codigo_materia vacio")
                continue

            hora_inicio = _parse_time(row["hora_inicio"])
            hora_fin = _parse_time(row["hora_fin"])

            comision_nombre = "Comision Unica"
            if has_comision:
                comision_raw = str(row["comision"]).strip()
                if comision_raw and comision_raw.lower() != "nan":
                    comision_nombre = comision_raw

            tipo_clase = None
            if has_tipo:
                tipo_clase = _parse_tipo_clase(row["tipo_clase"])

            virtual = None
            if has_virtual:
                virtual = _parse_virtual(row["virtual"])

            entry = HorarioInput(
                codigo_materia=codigo_raw,
                comision_nombre=comision_nombre,
                dia=str(row["dia"]).strip(),
                hora_inicio=hora_inicio,
                hora_fin=hora_fin,
                tipo_clase=tipo_clase,
                virtual=virtual,
            )
            inputs.append(entry)
        except Exception as e:
            errors.append(f"Fila {row_num}: {e}")

    return inputs, errors


def _parse_time(value) -> time:
    """Parse a value into a time object."""
    if isinstance(value, time):
        return value
    s = str(value).strip()
    parts = s.split(":")
    if len(parts) >= 2:
        return time(int(parts[0]), int(parts[1]))
    raise ValueError(f"No se pudo interpretar '{value}' como hora (formato esperado: HH:MM)")
