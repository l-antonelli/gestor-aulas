"""Servicio de importación masiva de inscriptos con preview.

Fase E1 del rediseño 2026-09-15. Complementa
``inscripcion_service.guardar_registros_materia`` (que sirve para el
data editor manual de la UI) con un pipeline de dos pasos:

1. **Preview** (``preview_import``): parsea el archivo, resuelve
   códigos contra el catálogo, y arma un ``InscripcionImportPreview``
   con qué registros son nuevos, cuáles pisan valores existentes y
   cuáles tienen errores.

2. **Commit** (``commit_import``): aplica el preview en una sola
   transacción. Semántica **overwrite** por default (última fila
   gana), consistente con el loader CLI histórico. La UI podría
   permitir des-seleccionar filas del preview antes de commitear —
   por ahora se comitea todo lo que llegue sin errores.

Comparado con el importer de cronograma:

- No hay decisión "merge / reemplazar / ignorar" por materia porque
  el modelo de inscriptos no tiene ese concepto (una fila (materia,
  año, cuatri) es un dato puntual: o se actualiza o no). En cambio
  se muestra explícitamente qué filas van a pisar valores previos.
- El "cronograma destino" no aplica: la serie histórica es global,
  no hay "buffer" que restringir.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime

import pandas as pd
from sqlmodel import Session, col, select

from src.database.models import (
    CodigoAliasDB,
    InscripcionHistoricaDB,
    MateriaDB,
)
from src.services.inscripcion_service import CUATRIS_VALIDOS


# =============================================================================
# Dataclasses
# =============================================================================


@dataclass
class InscripcionFilaPreview:
    """Una fila del archivo lista para commitear (o ya con error).

    Al preview le importa mostrar el "efecto" de cada fila: si es
    nueva (``valor_previo=None``) o si pisa un valor existente
    (``valor_previo!=None``, potencialmente distinto).
    """
    fila_num: int  # 1-based fila del archivo (encabezado = 1, primer dato = 2)
    codigo_original: str
    materia_codigo: str
    materia_nombre: str
    anio: int
    cuatrimestre: str
    inscriptos: int
    valor_previo: int | None = None
    resolucion_type: str = "direct"  # "direct" | "guarani"

    @property
    def es_nuevo(self) -> bool:
        return self.valor_previo is None

    @property
    def cambia_valor(self) -> bool:
        return (
            self.valor_previo is not None
            and self.valor_previo != self.inscriptos
        )


@dataclass
class InscripcionImportPreview:
    """Resultado del preview de importación de inscriptos.

    - ``filas_ok``: filas listas para commitear.
    - ``filas_error``: filas con problemas (código inválido, cuatri
      desconocido, valor negativo, año fuera de rango). No se
      comitean.
    - ``parse_errors``: errores estructurales (columnas faltantes,
      archivo ilegible). Bloquean el commit.
    - ``warnings``: avisos no bloqueantes (por ejemplo, resolución
      via ``codigo_guarani``, o filas duplicadas donde gana la última).
    """
    filas_ok: list[InscripcionFilaPreview] = field(default_factory=list)
    filas_error: list[tuple[int, str]] = field(default_factory=list)
    parse_errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)

    @property
    def tiene_errores_bloqueantes(self) -> bool:
        return bool(self.parse_errors)

    @property
    def total_filas(self) -> int:
        return len(self.filas_ok) + len(self.filas_error)

    @property
    def n_nuevos(self) -> int:
        return sum(1 for f in self.filas_ok if f.es_nuevo)

    @property
    def n_pisan(self) -> int:
        return sum(1 for f in self.filas_ok if f.cambia_valor)

    @property
    def n_iguales(self) -> int:
        """Filas con valor idéntico al previo — no cambian nada."""
        return sum(
            1 for f in self.filas_ok
            if f.valor_previo is not None and f.valor_previo == f.inscriptos
        )


@dataclass
class InscripcionImportResult:
    """Resultado del commit de una importación de inscriptos."""
    filas_creadas: int = 0
    filas_actualizadas: int = 0
    filas_sin_cambio: int = 0
    errors: list[str] = field(default_factory=list)


# =============================================================================
# Preview
# =============================================================================


COLUMNAS_REQUERIDAS = {"codigo_materia", "anio", "cuatrimestre", "inscriptos"}


COLUMN_ALIASES_INSC = {
    "codigo_materia": ["codigo", "codigo_plan", "materia", "cod_materia"],
    "anio": ["año", "year", "period_year"],
    "cuatrimestre": ["cuatri", "period"],
    "inscriptos": ["cant_inscriptos", "cant._inscriptos", "cantidad"],
}


def _normalize_columns(df: pd.DataFrame) -> pd.DataFrame:
    df.columns = [str(c).strip().lower().replace(" ", "_") for c in df.columns]
    rename_map = {}
    for canonical, aliases in COLUMN_ALIASES_INSC.items():
        if canonical not in df.columns:
            for alias in aliases:
                if alias in df.columns:
                    rename_map[alias] = canonical
                    break
    if rename_map:
        df = df.rename(columns=rename_map)
    return df


def list_inscriptos_sheets(file) -> list[str]:
    """Devuelve las hojas visibles del Excel candidatas a importar
    inscriptos, análogo a ``horario_file_parser.list_horarios_sheets``.

    Para CSV devuelve ``[]``. Excluye hojas ``Instrucciones`` y las
    hojas de sistema con prefijo ``_``. No propaga excepciones.
    """
    fname = getattr(file, "name", "")
    if not fname.endswith((".xlsx", ".xls")):
        return []
    try:
        try:
            file.seek(0)
        except Exception:  # noqa: BLE001
            pass
        _all_sheets = pd.read_excel(file, sheet_name=None)
    except Exception:  # noqa: BLE001
        return []
    finally:
        try:
            file.seek(0)
        except Exception:  # noqa: BLE001
            pass
    return [
        name for name in _all_sheets
        if not str(name).startswith("_") and str(name) != "Instrucciones"
    ]


def _read_dataframe(
    file, sheet_name: str | None = None,
) -> tuple[pd.DataFrame | None, str | None]:
    """Lee un file-like en pandas. Devuelve (df, error) — sólo uno no None.

    Cuando el archivo es un Excel con múltiples hojas (como la
    plantilla generada por ``template_export_service``), se elige
    preferentemente la hoja ``Inscriptos``; sino, la primera hoja
    visible no-``Instrucciones``. Sin esto pandas leería
    ``Instrucciones`` porque es la primera hoja del workbook.

    Si ``sheet_name`` viene explícito y existe en el workbook, gana
    sobre el fallback automático — es lo que usa el selector de hoja
    de la UI para archivos con varias hojas visibles.
    """
    fname = getattr(file, "name", "")
    try:
        if fname.endswith(".csv"):
            df = pd.read_csv(file)
        elif fname.endswith((".xlsx", ".xls")):
            _all_sheets = pd.read_excel(file, sheet_name=None)
            if sheet_name is not None and sheet_name in _all_sheets:
                df = _all_sheets[sheet_name]
            elif "Inscriptos" in _all_sheets:
                df = _all_sheets["Inscriptos"]
            else:
                _visibles = [
                    name for name in _all_sheets
                    if not name.startswith("_") and name != "Instrucciones"
                ]
                _preferida = _visibles[0] if _visibles else next(iter(_all_sheets))
                df = _all_sheets[_preferida]
        else:
            return None, (
                f"Formato no soportado: '{fname}'. "
                "Usar CSV o Excel (.xlsx)."
            )
    except Exception as exc:  # noqa: BLE001
        return None, f"Error leyendo el archivo: {exc}"
    return df, None


def preview_import(
    session: Session, file, sheet_name: str | None = None,
) -> InscripcionImportPreview:
    """Arma el preview de una importación masiva de inscriptos.

    Args:
        session: sesión activa.
        file: file-like con ``.name`` (Streamlit UploadedFile o
            similar). Puede ser CSV o Excel.
        sheet_name: nombre de la hoja del Excel a importar cuando el
            archivo tiene varias hojas visibles. ``None`` mantiene el
            fallback tradicional (hoja ``Inscriptos`` si existe, sino
            primera hoja no-sistema). No aplica a CSV.

    Returns:
        ``InscripcionImportPreview`` con filas OK / error / warnings.
    """
    preview = InscripcionImportPreview()

    df, err = _read_dataframe(file, sheet_name=sheet_name)
    if err is not None:
        preview.parse_errors.append(err)
        return preview
    assert df is not None

    df = _normalize_columns(df)
    faltantes = COLUMNAS_REQUERIDAS - set(df.columns)
    if faltantes:
        preview.parse_errors.append(
            f"Columnas faltantes: {', '.join(sorted(faltantes))}. "
            "Descargá la plantilla desde la aplicación para el "
            "formato correcto."
        )
        return preview

    # Cargar catálogo (codigo y codigo_guarani) para resolución.
    materias = list(session.exec(select(MateriaDB)).all())
    por_codigo = {m.codigo: m for m in materias}
    por_guarani: dict[str, list[MateriaDB]] = {}
    for m in materias:
        gc = getattr(m, "codigo_guarani", None)
        if gc:
            por_guarani.setdefault(gc, []).append(m)

    # Alias persistidos (Fase E2). Los matches manuales que el usuario
    # guardo antes se resuelven acá antes que la ambigüedad de guarani.
    aliases_map: dict[str, str] = {
        a.codigo_externo: a.materia_codigo
        for a in session.exec(select(CodigoAliasDB)).all()
    }

    # Pre-cargar existentes que van a ser referenciados (batch).
    codigos_en_archivo: set[str] = set()
    for _, r in df.iterrows():
        raw = r.get("codigo_materia")
        if pd.isna(raw):
            continue
        codigos_en_archivo.add(str(raw).strip())

    # Se resuelven después de saber cuál es el codigo canónico; por
    # ahora tomamos los directos.
    codigos_directos = codigos_en_archivo & set(por_codigo.keys())
    existentes_batch = list(session.exec(
        select(InscripcionHistoricaDB)
        .where(col(InscripcionHistoricaDB.materia_codigo).in_(list(codigos_directos)))
    ).all()) if codigos_directos else []
    existentes_map: dict[tuple[str, int, str], int] = {
        (r.materia_codigo, r.anio, r.cuatrimestre): r.inscriptos
        for r in existentes_batch
    }

    # Detectar duplicados dentro del archivo (misma PK; la última gana).
    pk_vistas: dict[tuple[str, int, str], int] = {}
    filas_ok_por_pk: dict[tuple[str, int, str], InscripcionFilaPreview] = {}

    for idx, row in df.iterrows():
        fila_num = int(idx) + 2  # +2: 0-based idx + fila de header

        raw_cod = row.get("codigo_materia")
        if pd.isna(raw_cod):
            preview.filas_error.append(
                (fila_num, "codigo_materia vacío"),
            )
            continue
        codigo_original = str(raw_cod).strip()

        # Resolución (Fase E2: alias tiene prioridad sobre guarani).
        materia = por_codigo.get(codigo_original)
        resolucion_type = "direct"
        # Bugfix (2026-09-22, task #348): tracker de "alias huérfano"
        # para diferenciar el caso "no hay alias" del caso "hay alias
        # pero apunta a un código que ya no existe en el catálogo".
        alias_huerfano_target: str | None = None
        if materia is None:
            alias_target = aliases_map.get(codigo_original)
            if alias_target is not None:
                materia = por_codigo.get(alias_target)
                if materia is not None:
                    resolucion_type = "alias"
                    preview.warnings.append(
                        f"Fila {fila_num}: código '{codigo_original}' "
                        f"resuelto vía alias persistido → "
                        f"'{materia.codigo}'."
                    )
                else:
                    alias_huerfano_target = alias_target
        if materia is None:
            matches = por_guarani.get(codigo_original, [])
            if len(matches) == 1:
                materia = matches[0]
                resolucion_type = "guarani"
                preview.warnings.append(
                    f"Fila {fila_num}: código '{codigo_original}' "
                    f"resuelto vía código Guaraní → "
                    f"'{materia.codigo}'."
                )
            elif alias_huerfano_target is not None:
                preview.filas_error.append((
                    fila_num,
                    f"código '{codigo_original}' tiene un alias "
                    f"persistido que apunta a '{alias_huerfano_target}', "
                    "pero esa materia ya no está en el catálogo. "
                    "Reasigná el código desde la sección 'Sin matchear' "
                    "(el alias viejo se sobrescribe con el nuevo match).",
                ))
                continue
            else:
                preview.filas_error.append((
                    fila_num,
                    f"código de materia '{codigo_original}' no está "
                    "en el catálogo (ni por codigo_plan ni por "
                    "codigo_guarani ni por alias)",
                ))
                continue

        # Año.
        try:
            anio_raw = row.get("anio")
            if pd.isna(anio_raw):
                raise ValueError("año vacío")
            anio = int(anio_raw)
            if anio < 2000 or anio > 2100:
                raise ValueError(
                    f"año {anio} fuera del rango razonable (2000-2100)"
                )
        except (ValueError, TypeError) as exc:
            preview.filas_error.append((fila_num, str(exc)))
            continue

        # Cuatrimestre.
        cuatri_raw = row.get("cuatrimestre")
        if pd.isna(cuatri_raw):
            preview.filas_error.append((fila_num, "cuatrimestre vacío"))
            continue
        cuatri = str(cuatri_raw).strip()
        # Normalización: 'anual' → 'Anual', '1c' → '1C'.
        if cuatri.lower() == "anual":
            cuatri = "Anual"
        elif cuatri.lower() in ("1c", "2c"):
            cuatri = cuatri.upper()
        if cuatri not in CUATRIS_VALIDOS:
            preview.filas_error.append((
                fila_num,
                f"cuatrimestre '{cuatri_raw}' no válido "
                f"(esperado: {sorted(CUATRIS_VALIDOS)})",
            ))
            continue

        # Inscriptos.
        try:
            insc_raw = row.get("inscriptos")
            if pd.isna(insc_raw):
                raise ValueError("inscriptos vacío")
            inscriptos = int(insc_raw)
            if inscriptos < 0:
                raise ValueError(
                    f"inscriptos negativo ({inscriptos})"
                )
        except (ValueError, TypeError) as exc:
            preview.filas_error.append((fila_num, str(exc)))
            continue

        pk = (materia.codigo, anio, cuatri)

        # Detección de duplicado dentro del archivo.
        if pk in pk_vistas:
            preview.warnings.append(
                f"Fila {fila_num}: duplica un valor previo del "
                f"archivo para ({materia.codigo}, {anio}, {cuatri}) "
                f"— gana la última fila."
            )

        pk_vistas[pk] = fila_num
        valor_previo = existentes_map.get(pk)
        fila = InscripcionFilaPreview(
            fila_num=fila_num,
            codigo_original=codigo_original,
            materia_codigo=materia.codigo,
            materia_nombre=materia.nombre,
            anio=anio,
            cuatrimestre=cuatri,
            inscriptos=inscriptos,
            valor_previo=valor_previo,
            resolucion_type=resolucion_type,
        )
        filas_ok_por_pk[pk] = fila  # la última fila gana

    preview.filas_ok = sorted(
        filas_ok_por_pk.values(),
        key=lambda f: (f.materia_codigo, f.anio, f.cuatrimestre),
    )
    return preview


# =============================================================================
# Commit
# =============================================================================


def commit_import(
    session: Session, preview: InscripcionImportPreview,
) -> InscripcionImportResult:
    """Aplica el preview: crea/actualiza filas en ``InscripcionHistoricaDB``.

    Semántica **overwrite** (última fila del archivo gana). Sólo se
    comitean las ``filas_ok``; las ``filas_error`` se ignoran (se
    reportan en el preview pero no bloquean el commit del resto).

    Args:
        session: sesión activa.
        preview: preview generado por ``preview_import``.

    Returns:
        ``InscripcionImportResult`` con contadores.

    Raises:
        ValueError si el preview tiene errores bloqueantes (columnas
        faltantes, archivo ilegible).
    """
    if preview.tiene_errores_bloqueantes:
        raise ValueError(
            "El preview tiene errores bloqueantes; corregir el "
            "archivo antes de commitear."
        )

    result = InscripcionImportResult()

    # Batch fetch de los existentes que se van a tocar.
    pks = [(f.materia_codigo, f.anio, f.cuatrimestre) for f in preview.filas_ok]
    if not pks:
        return result

    codigos = list({p[0] for p in pks})
    existentes = list(session.exec(
        select(InscripcionHistoricaDB)
        .where(col(InscripcionHistoricaDB.materia_codigo).in_(codigos))
    ).all())
    existentes_map: dict[tuple[str, int, str], InscripcionHistoricaDB] = {
        (r.materia_codigo, r.anio, r.cuatrimestre): r
        for r in existentes
    }

    now = datetime.utcnow()
    for fila in preview.filas_ok:
        pk = (fila.materia_codigo, fila.anio, fila.cuatrimestre)
        existente = existentes_map.get(pk)
        if existente is None:
            session.add(InscripcionHistoricaDB(
                materia_codigo=fila.materia_codigo,
                anio=fila.anio,
                cuatrimestre=fila.cuatrimestre,
                inscriptos=fila.inscriptos,
                updated_at=now,
                origen="importado",
            ))
            result.filas_creadas += 1
        elif existente.inscriptos != fila.inscriptos:
            existente.inscriptos = fila.inscriptos
            existente.updated_at = now
            existente.origen = "importado"
            session.add(existente)
            result.filas_actualizadas += 1
        else:
            # Bugfix (2026-09-22, task #344): la fila fue "tocada" por
            # el importer aunque el valor no cambió. Refrescamos
            # `updated_at` + `origen` para que la auditoría refleje
            # que el dato pasó por este import; el conteo específico
            # de filas sin cambio se preserva en `filas_sin_cambio`.
            existente.updated_at = now
            existente.origen = "importado"
            session.add(existente)
            result.filas_sin_cambio += 1

    session.commit()
    return result


# =============================================================================
# Alias de codigos
# =============================================================================


def resolver_via_alias(
    session: Session, codigo_externo: str,
) -> str | None:
    """Devuelve `materia_codigo` si hay un alias guardado, o None.

    Se consulta desde el flow "Sin matchear" de la UI antes de
    ofrecerle al usuario que asocie manualmente el código: si ya
    existe un alias, se resuelve automaticamente y no se le vuelve
    a preguntar en la proxima importacion.
    """
    row = session.get(CodigoAliasDB, codigo_externo)
    return row.materia_codigo if row is not None else None


def registrar_alias(
    session: Session, codigo_externo: str, materia_codigo: str,
    *,
    origen: str = "manual",
    nota: str = "",
) -> CodigoAliasDB:
    """Upsert de un alias externo → materia del catalogo.

    Si el alias ya existía, se actualiza (nueva materia destino,
    nuevo origen, nueva nota). Sirve para el flow "Sin matchear" y
    tambien para autopoblarlo desde el importer cuando se detecta
    una resolucion via ``codigo_guarani`` (para hacer la conversion
    persistente).
    """
    now = datetime.utcnow()
    existente = session.get(CodigoAliasDB, codigo_externo)
    if existente is None:
        alias = CodigoAliasDB(
            codigo_externo=codigo_externo,
            materia_codigo=materia_codigo,
            updated_at=now,
            origen=origen,
            nota=nota,
        )
        session.add(alias)
        session.commit()
        session.refresh(alias)
        return alias
    existente.materia_codigo = materia_codigo
    existente.updated_at = now
    existente.origen = origen
    if nota:
        existente.nota = nota
    session.add(existente)
    session.commit()
    session.refresh(existente)
    return existente


def list_aliases(session: Session) -> list[CodigoAliasDB]:
    """Todos los alias registrados, ordenados por codigo_externo."""
    return list(session.exec(
        select(CodigoAliasDB).order_by(col(CodigoAliasDB.codigo_externo))
    ).all())


def delete_alias(session: Session, codigo_externo: str) -> None:
    row = session.get(CodigoAliasDB, codigo_externo)
    if row is not None:
        session.delete(row)
        session.commit()
