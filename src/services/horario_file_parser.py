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


# Hoja que el parser prefiere cuando no se le indica una explícita.
# La UI del selector de hoja usa esta misma constante para elegir el
# default del selectbox (fix auditoría H2, 2026-09-23: antes el
# selectbox arrancaba en la primera hoja visible del workbook, pisando
# esta preferencia y rompiendo archivos que el fallback importaba bien).
HOJA_PREFERIDA = "Horarios"


def listar_hojas_visibles(file) -> list[str]:
    """Lista las hojas **visibles** de un archivo Excel, excluyendo las
    de sistema (``Instrucciones`` y las de prefijo ``_`` que la
    plantilla generada esconde).

    Compartida por los importers de cronograma e inscriptos (los
    wrappers ``list_horarios_sheets`` / ``list_inscriptos_sheets``
    delegan acá).

    Implementación (fix auditoría 2026-09-23): usa
    ``openpyxl.load_workbook(read_only=True)`` en vez de
    ``pd.read_excel(sheet_name=None)`` por dos razones medidas:

    - **Hojas ocultas**: pandas ignora ``sheet_state``, así que una
      hoja marcada oculta sin prefijo ``_`` (típico en archivos
      institucionales: "Datos viejos", "Backup") aparecía como opción
      válida del selector. openpyxl expone el estado y se filtra.
    - **Rendimiento**: pandas materializa todos los DataFrames del
      workbook para después descartarlos (~1,2 s en un libro de 10
      hojas grandes); leer sólo los nombres cuesta ~0,02 s.

    Para ``.xls`` (formato viejo, que openpyxl no lee) se cae a
    ``pd.ExcelFile`` sin información de visibilidad.

    Returns:
        Nombres de hoja en el orden del workbook. Para CSV, ``[]``.
        No propaga excepciones — si el archivo no se puede leer,
        devuelve ``[]`` y el caller reporta el error al parsear.
    """
    fname = str(getattr(file, "name", "") or "")
    low = fname.lower()
    if not low.endswith((".xlsx", ".xlsm", ".xls")):
        return []
    try:
        # `file` puede ser un Streamlit UploadedFile — necesita rewind.
        try:
            file.seek(0)
        except Exception:  # noqa: BLE001
            pass
        if low.endswith(".xls"):
            nombres = [str(n) for n in pd.ExcelFile(file).sheet_names]
        else:
            import openpyxl
            wb = openpyxl.load_workbook(file, read_only=True)
            try:
                nombres = [
                    ws.title for ws in wb.worksheets
                    if ws.sheet_state == "visible"
                ]
            finally:
                wb.close()
    except Exception:  # noqa: BLE001
        return []
    finally:
        try:
            file.seek(0)
        except Exception:  # noqa: BLE001
            pass
    return [
        name for name in nombres
        if not str(name).startswith("_") and str(name) != "Instrucciones"
    ]


def hoja_default(sheets: list[str], preferida: str = HOJA_PREFERIDA) -> int:
    """Índice de la hoja que el selector de la UI debe pre-seleccionar.

    Replica la preferencia del parser: si la hoja preferida está en la
    lista, ésa; sino la primera. Mantener esta lógica acá evita que la
    UI y el fallback del parser vuelvan a divergir (auditoría H2).
    """
    return sheets.index(preferida) if preferida in sheets else 0


def list_horarios_sheets(file) -> list[str]:
    """Hojas candidatas a importar horarios. Ver ``listar_hojas_visibles``."""
    return listar_hojas_visibles(file)


def parse_horarios_file(
    file, sheet_name: str | None = None,
) -> tuple[List[HorarioInput], list[str]]:
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
        sheet_name: nombre de la hoja a leer cuando el archivo es
            Excel con múltiples hojas. Si es ``None`` se aplica el
            fallback tradicional: hoja ``Horarios`` si existe, sino la
            primera visible que no sea ``Instrucciones`` o de sistema
            (prefijo ``_``). No aplica a CSV.

    Returns:
        Tuple of (list of HorarioInput, list of parse errors)
    """
    errors: list[str] = []
    inputs: list[HorarioInput] = []

    _low = str(file.name).lower()
    try:
        if _low.endswith(".csv"):
            df = pd.read_csv(file)
        elif _low.endswith((".xlsx", ".xlsm", ".xls")):
            # Si el archivo tiene múltiples hojas (por ejemplo la
            # plantilla generada por el sistema, que trae
            # 'Instrucciones' + 'Horarios' + hojas ocultas), preferir
            # la hoja llamada 'Horarios'. Sino, fallback a la primera.
            # Cover: sin esto, pandas leería 'Instrucciones' porque
            # es la primera hoja del workbook.
            #
            # Rendimiento (fix auditoría 2026-09-23): se lee SOLO la
            # hoja elegida via `pd.ExcelFile` — antes se materializaban
            # todos los DataFrames del workbook para descartar todos
            # menos uno.
            _xls = pd.ExcelFile(file)
            _nombres = [str(n) for n in _xls.sheet_names]
            if sheet_name is not None and sheet_name in _nombres:
                _elegida = sheet_name
            elif HOJA_PREFERIDA in _nombres:
                _elegida = HOJA_PREFERIDA
            else:
                # Primera hoja no oculta (nombre sin prefijo '_').
                _visibles = [
                    n for n in _nombres
                    if not n.startswith("_") and n != "Instrucciones"
                ]
                _elegida = _visibles[0] if _visibles else _nombres[0]
            df = _xls.parse(_elegida)
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
