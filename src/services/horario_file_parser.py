"""Parser for horario data from CSV/Excel files."""

from datetime import time
from typing import List

import pandas as pd

from src.services.horario_loading_service import HorarioInput


def parse_horarios_file(file) -> tuple[List[HorarioInput], list[str]]:
    """
    Parse a CSV or Excel file into HorarioInput objects.

    Expected columns: codigo_materia, comision, dia, hora_inicio, hora_fin

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
            df = pd.read_excel(file)
        else:
            return [], [f"Formato no soportado: {file.name}. Use CSV o Excel (.xlsx)"]
    except Exception as e:
        return [], [f"Error leyendo archivo: {e}"]

    # Normalize column names
    df.columns = [c.strip().lower().replace(" ", "_") for c in df.columns]

    required = {"codigo_materia", "comision", "dia", "hora_inicio", "hora_fin"}
    missing = required - set(df.columns)
    if missing:
        return [], [f"Columnas faltantes: {', '.join(sorted(missing))}"]

    for idx, row in df.iterrows():
        row_num = idx + 2  # +2: 0-based idx + header row

        try:
            hora_inicio = _parse_time(row["hora_inicio"])
            hora_fin = _parse_time(row["hora_fin"])

            comision_nombre = str(row["comision"]).strip()
            if not comision_nombre or comision_nombre.lower() == "nan":
                comision_nombre = "Comision Unica"

            entry = HorarioInput(
                codigo_materia=str(row["codigo_materia"]).strip(),
                comision_nombre=comision_nombre,
                dia=str(row["dia"]).strip(),
                hora_inicio=hora_inicio,
                hora_fin=hora_fin,
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
