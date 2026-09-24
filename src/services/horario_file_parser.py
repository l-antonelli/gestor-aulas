"""Parser for horario data from CSV/Excel files."""

from datetime import time
from typing import List

import pandas as pd

from src.services.horario_loading_service import HorarioInput

# Column name aliases: canonical_name -> list of accepted alternatives
#
# 2026-09-23: las comisiones se identifican por CÓDIGO numérico
# (`codigo_comision`, obligatorio en la plantilla nueva — mapea a
# `ComisionDB.numero`) con un `nombre_comision` opcional. La columna
# histórica `comision` (texto libre) se sigue aceptando por
# compatibilidad: se interpreta como nombre y el código se autoderiva.
# También se acepta `nombre_materia` para resolver la materia por
# nombre cuando el código viene vacío.
COLUMN_ALIASES = {
    "codigo_materia": ["codigo_plan", "materia", "cod_materia"],
    "nombre_materia": ["materia_nombre"],
    "codigo_comision": ["cod_comision"],
    "nombre_comision": ["comision_nombre"],
    "comision": [],
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


def _parse_virtual(value) -> bool:
    """Normaliza la columna virtual leída del archivo a un booleano.

    La plantilla nueva (2026-09-23) usa booleanos reales de Excel
    (VERDADERO/FALSO), que pandas entrega como ``bool``. Por
    compatibilidad se aceptan además variantes textuales:
    SI/NO, sí/no, true/false, verdadero/falso, 1/0.

    2026-09-23: virtual es un **booleano** — un valor vacío (o NaN) se
    interpreta como ``False`` (presencial). Antes vacío significaba
    "heredar del dictado/materia" (tri-estado), lo que resultaba
    opaco: el usuario no podía saber mirando el archivo si una clase
    iba a quedar virtual o no.
    """
    if value is None:
        return False
    if isinstance(value, bool):
        return value
    # Números 0/1 (2026-09-24, reporte de usuario): cuando la columna
    # mezcla booleanos con celdas vacías, pandas la convierte a
    # numérica y un VERDADERO llega acá como ``1.0`` (float) — el
    # caso más común al marcar virtual sólo algunas filas.
    if isinstance(value, (int, float)):
        if pd.isna(value):
            return False
        if float(value) == 1.0:
            return True
        if float(value) == 0.0:
            return False
        raise ValueError(
            f"virtual '{value}' no reconocido "
            "(esperado: VERDADERO/FALSO, SI/NO o vacío = FALSO)"
        )
    s = str(value).strip().lower()
    if s == "" or s == "nan":
        return False
    if s in ("si", "sí", "s", "true", "verdadero", "1", "1.0", "yes", "y"):
        return True
    if s in ("no", "n", "false", "falso", "0", "0.0"):
        return False
    raise ValueError(
        f"virtual '{value}' no reconocido "
        "(esperado: VERDADERO/FALSO, SI/NO o vacío = FALSO)"
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


# Hojas del archivo que NUNCA son datos a importar: la guía, la
# referencia visible de materias (2026-09-23) y las listas de sistema
# con prefijo `_`.
HOJAS_SISTEMA = {"Instrucciones", "Materias"}

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
        if not str(name).startswith("_")
        and str(name) not in HOJAS_SISTEMA
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
                    if not n.startswith("_") and n not in HOJAS_SISTEMA
                ]
                _elegida = _visibles[0] if _visibles else _nombres[0]
            df = _xls.parse(_elegida)
        else:
            return [], [f"Formato no soportado: {file.name}. Use CSV o Excel (.xlsx)"]
    except Exception as e:
        return [], [f"Error leyendo archivo: {e}"]

    df = _normalize_columns(df)

    # `codigo_materia` puede reemplazarse por `nombre_materia` (la
    # plantilla nueva permite elegir la materia por nombre; el
    # importador resuelve el nombre contra el catálogo).
    required = {"dia", "hora_inicio", "hora_fin"}
    missing = required - set(df.columns)
    if (
        "codigo_materia" not in df.columns
        and "nombre_materia" not in df.columns
    ):
        missing.add("codigo_materia")
    if missing:
        return [], [f"Columnas faltantes: {', '.join(sorted(missing))}"]

    def _celda(row, col) -> str:
        if col not in df.columns:
            return ""
        _v = row.get(col)
        if _v is None or (isinstance(_v, float) and pd.isna(_v)):
            return ""
        s = str(_v).strip()
        return "" if s.lower() == "nan" else s

    has_tipo = "tipo_clase" in df.columns
    has_virtual = "virtual" in df.columns

    # Correspondencia código ↔ nombre de comisión POR MATERIA
    # (2026-09-24): si se declara nombre, tiene que ser 1 a 1. Se
    # acumulan sólo los nombres DECLARADOS (las filas que dejan el
    # default C{código} no participan) y al final del archivo se
    # emiten los errores de consistencia.
    _nombres_por_codigo: dict[tuple[str, int], set[str]] = {}
    _codigos_por_nombre: dict[tuple[str, str], set[int]] = {}

    for idx, row in df.iterrows():
        row_num = idx + 2  # +2: 0-based idx + header row

        try:
            codigo_raw = _celda(row, "codigo_materia")
            nombre_mat = _celda(row, "nombre_materia")
            dia_raw = _celda(row, "dia")
            hi_raw = _celda(row, "hora_inicio")
            hf_raw = _celda(row, "hora_fin")

            # Fila totalmente vacía (típico: filas de la plantilla con
            # la fórmula de auto-población del código y nada más) —
            # se saltea en silencio, no es un error.
            if not any((codigo_raw, nombre_mat, dia_raw, hi_raw, hf_raw)):
                continue

            # Nombre declarado JUNTO al código: se propaga aparte
            # para que el importador verifique que se corresponden
            # (2026-09-23). Si el código viene vacío, el nombre pasa
            # a ser la clave de resolución y no hay nada que cruzar.
            nombre_declarado: str | None = None
            if not codigo_raw:
                if nombre_mat:
                    # Resolución por nombre: el importador la cruza
                    # contra el catálogo (código > guaraní > nombre).
                    codigo_raw = nombre_mat
                else:
                    errors.append(f"Fila {row_num}: codigo_materia vacio")
                    continue
            elif nombre_mat:
                nombre_declarado = nombre_mat

            hora_inicio = _parse_time(row["hora_inicio"])
            hora_fin = _parse_time(row["hora_fin"])
            # Validación (2026-09-23): el inicio debe ser anterior al
            # fin — antes una fila invertida entraba y recién rompía
            # en las validaciones del cronograma.
            if hora_inicio >= hora_fin:
                errors.append(
                    f"Fila {row_num}: hora_inicio "
                    f"({hora_inicio.strftime('%H:%M')}) debe ser "
                    f"anterior a hora_fin "
                    f"({hora_fin.strftime('%H:%M')})"
                )
                continue

            # Comisión: esquema nuevo (código numérico + nombre
            # opcional) con fallback al texto libre histórico.
            comision_codigo: int | None = None
            _cod_com_raw = _celda(row, "codigo_comision")
            _nom_com_raw = _celda(row, "nombre_comision")
            _legacy_com = _celda(row, "comision")
            if _cod_com_raw:
                try:
                    comision_codigo = int(float(_cod_com_raw))
                except (TypeError, ValueError):
                    errors.append(
                        f"Fila {row_num}: codigo_comision "
                        f"'{_cod_com_raw}' no es un número entero"
                    )
                    continue
                if comision_codigo < 1:
                    errors.append(
                        f"Fila {row_num}: codigo_comision debe ser "
                        f"un entero >= 1 (vino {comision_codigo})"
                    )
                    continue
                comision_nombre = _nom_com_raw or f"C{comision_codigo}"
                if _nom_com_raw:
                    _nombres_por_codigo.setdefault(
                        (codigo_raw, comision_codigo), set(),
                    ).add(_nom_com_raw)
                    _codigos_por_nombre.setdefault(
                        (codigo_raw, _nom_com_raw.strip().lower()), set(),
                    ).add(comision_codigo)
            elif _nom_com_raw:
                comision_nombre = _nom_com_raw
            elif _legacy_com:
                comision_nombre = _legacy_com
            else:
                comision_nombre = "Comision Unica"

            tipo_clase = None
            if has_tipo:
                tipo_clase = _parse_tipo_clase(row["tipo_clase"])

            virtual = False
            if has_virtual:
                virtual = _parse_virtual(row["virtual"])

            # Validación (2026-09-23): una clase de laboratorio no
            # puede ser virtual — el laboratorio requiere aula física.
            if tipo_clase == "laboratorio" and virtual:
                errors.append(
                    f"Fila {row_num}: una clase de laboratorio no "
                    "puede ser virtual — corregí el tipo o la "
                    "columna virtual"
                )
                continue

            entry = HorarioInput(
                codigo_materia=codigo_raw,
                nombre_materia=nombre_declarado,
                comision_nombre=comision_nombre,
                comision_codigo=comision_codigo,
                dia=dia_raw,
                hora_inicio=hora_inicio,
                hora_fin=hora_fin,
                tipo_clase=tipo_clase,
                virtual=virtual,
            )
            inputs.append(entry)
        except Exception as e:
            errors.append(f"Fila {row_num}: {e}")

    # Chequeo 1:1 código ↔ nombre de comisión (por materia).
    for (_mat, _cod), _noms in sorted(_nombres_por_codigo.items()):
        _canon = {n.strip().lower() for n in _noms}
        if len(_canon) > 1:
            _lst = ", ".join(f"'{n}'" for n in sorted(_noms))
            errors.append(
                f"Materia {_mat}: el código de comisión {_cod} "
                f"aparece con nombres distintos ({_lst}) — usá un "
                "único nombre por código."
            )
    for (_mat, _nom), _cods in sorted(_codigos_por_nombre.items()):
        if len(_cods) > 1:
            _lst = ", ".join(str(c) for c in sorted(_cods))
            errors.append(
                f"Materia {_mat}: el nombre de comisión '{_nom}' "
                f"aparece con códigos distintos ({_lst}) — un nombre "
                "identifica una única comisión."
            )

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
