"""Parser de tablas de horarios de la web de FCEIA (UNR).

Descarga una pagina de horarios publicados por Asuntos Estudiantiles,
parsea las tablas HTML y extrae los bloques de horario con materia,
dia, hora inicio y hora fin.

Uso standalone (para debug/verificacion):
    python -m scripts.parse_fceia_schedule --url URL [--dump-json]

Uso como modulo:
    from scripts.parse_fceia_schedule import fetch_and_parse
    tables = fetch_and_parse("https://www.fceia.unr.edu.ar/estudiantil/?page_id=17396")
    for table in tables:
        print(table["title"], len(table["entries"]))

Limitaciones conocidas:
    - Algunas tablas nocturnas tienen etiquetas de tiempo (<th>) faltantes
      en la columna 0 (ej: omiten 20:00 y 22:00). Esto causa que el calculo
      de end_time por avance de slots sobreestime la hora de fin.
    - Al cargar multiples paginas, se generan entries duplicadas porque las
      mismas comisiones aparecen en distintas paginas. Deduplicar despues
      de cargar usando la clave (materia, dia, hora_inicio, hora_fin).
    - Los nombres de materias incluyen sufijos variables (Virtual, Division,
      Laboratorio, Teoria, Com. NNN, nombres de profesores) que hay que
      limpiar antes de matchear contra la DB.
"""

import re
import subprocess
import json
import sys
from dataclasses import dataclass, field, asdict
from html.parser import HTMLParser
from datetime import time
from typing import Optional


# =============================================================================
# Dataclass para el resultado
# =============================================================================

@dataclass
class ScheduleEntry:
    """Un bloque de horario parseado desde la web."""
    subject: str        # Nombre de la materia tal como aparece en la web
    day: str            # Lunes, Martes, Miercoles, Jueves, Viernes
    start: time         # Hora inicio
    end: time           # Hora fin
    rowspan: int        # Rowspan original (para debug)
    aula: str = ""      # Info de aula si se encontro


@dataclass
class ParsedTable:
    """Una tabla parseada (= una comision)."""
    index: int                          # Indice de tabla en la pagina (0-based)
    title: str                          # Titulo de la comision si se encuentra
    entries: list[ScheduleEntry] = field(default_factory=list)


# =============================================================================
# HTML Table Parser
# =============================================================================

class _TableParser(HTMLParser):
    """Parser de HTML que extrae celdas con tipo, rowspan, colspan y texto."""

    def __init__(self):
        super().__init__()
        self.rows: list[list[dict]] = []
        self._current_row: Optional[list] = None
        self._current_cell: Optional[dict] = None
        self._in_cell = False

    def handle_starttag(self, tag, attrs):
        a = dict(attrs)
        if tag == "tr":
            self._current_row = []
        elif tag in ("td", "th"):
            self._in_cell = True
            self._current_cell = {
                "type": tag,
                "rowspan": int(a.get("rowspan", "1")),
                "colspan": int(a.get("colspan", "1")),
                "class": a.get("class", ""),
                "text": "",
            }
        elif tag == "br" and self._in_cell:
            self._current_cell["text"] += "\n"

    def handle_endtag(self, tag):
        if tag == "tr" and self._current_row is not None:
            self.rows.append(self._current_row)
            self._current_row = None
        elif tag in ("td", "th") and self._in_cell:
            self._current_cell["text"] = self._current_cell["text"].strip()
            if self._current_row is not None:
                self._current_row.append(self._current_cell)
            self._in_cell = False
            self._current_cell = None

    def handle_data(self, data):
        if self._in_cell and self._current_cell:
            self._current_cell["text"] += data

    def handle_entityref(self, name):
        # Manejar entidades HTML comunes
        if self._in_cell and self._current_cell:
            entities = {"rsquo": "\u2019", "lsquo": "\u2018", "ndash": "\u2013",
                        "mdash": "\u2014", "amp": "&", "lt": "<", "gt": ">",
                        "nbsp": " "}
            self._current_cell["text"] += entities.get(name, "")

    def handle_charref(self, name):
        if self._in_cell and self._current_cell:
            try:
                self._current_cell["text"] += chr(int(name))
            except (ValueError, OverflowError):
                pass


def _parse_table_html(table_inner_html: str) -> list[list[dict]]:
    """Parsea el HTML interno de un <table> y retorna lista de filas."""
    parser = _TableParser()
    parser.feed("<table>" + table_inner_html + "</table>")
    return parser.rows


# =============================================================================
# Grid builder (resuelve rowspan/colspan)
# =============================================================================

def _build_grid(rows: list[list[dict]]) -> tuple[list[list], list[list[bool]]]:
    """Construye grilla 2D resolviendo rowspan/colspan.

    Retorna:
        grid: grilla[row][col] = celda dict (o None)
        starts: starts[row][col] = True si la celda EMPIEZA ahi
    """
    max_cols = 6  # th-tiempo + 5 dias
    n_rows = len(rows)
    grid = [[None] * max_cols for _ in range(n_rows)]
    starts = [[False] * max_cols for _ in range(n_rows)]

    for r, row in enumerate(rows):
        ci = 0
        for cell in row:
            while ci < max_cols and grid[r][ci] is not None:
                ci += 1
            if ci >= max_cols:
                break
            starts[r][ci] = True
            for dr in range(cell["rowspan"]):
                for dc in range(cell["colspan"]):
                    rr, cc = r + dr, ci + dc
                    if rr < n_rows and cc < max_cols:
                        grid[rr][cc] = cell
            ci += cell["colspan"]

    return grid, starts


# =============================================================================
# Extraccion de horarios
# =============================================================================

_DAYS = ["", "Lunes", "Martes", "Miércoles", "Jueves", "Viernes"]

_TIME_RE = re.compile(r"(\d{1,2}):(\d{2})")


def _get_labeled_times(grid: list[list]) -> list[tuple[int, int]]:
    """Extrae (row_index, minutos) de las etiquetas <th> de tiempo."""
    labels = []
    for r in range(len(grid)):
        cell = grid[r][0]
        if cell and cell["type"] == "th":
            m = _TIME_RE.match(cell["text"].strip())
            if m:
                labels.append((r, int(m.group(1)) * 60 + int(m.group(2))))
    return labels


def _extract_subject_and_aula(text: str) -> tuple[str, str]:
    """Extrae nombre de materia y aula desde el texto de una celda.

    El texto tiene formato:
        Nombre de la materia
        [segunda linea del nombre]
        Aula: XX Edificio
        [Profesor1]
        [Profesor2]
    """
    lines = [l.strip() for l in text.split("\n") if l.strip()]
    subject_parts = []
    aula = ""
    for line in lines:
        if "Aula" in line or "aula" in line:
            aula = line
            break
        subject_parts.append(line)

    subject = " ".join(subject_parts).strip()
    return subject, aula


def _mins_to_time(mins: int) -> time:
    """Convierte minutos desde medianoche a datetime.time."""
    mins = max(0, min(mins, 23 * 60 + 59))
    h = mins // 60
    m = mins % 60
    return time(h, m)


def extract_entries_from_table(table_inner_html: str) -> list[ScheduleEntry]:
    """Extrae entradas de horario desde el HTML interno de un <table>.

    Algoritmo:
    1. Parsea HTML -> filas de celdas
    2. Construye grilla 2D resolviendo rowspan/colspan
    3. Extrae etiquetas de tiempo (columna 0)
    4. Para cada celda con contenido:
       - start_time = etiqueta de tiempo del slot donde empieza
       - duracion = rowspan / 3 horas (verificado: todos los rowspan de contenido son multiplo de 3)
       - end_time = avanzar duracion slots desde start_time
    """
    rows = _parse_table_html(table_inner_html)
    if not rows:
        return []

    grid, starts = _build_grid(rows)
    labels = _get_labeled_times(grid)

    if not labels:
        return []

    slot_rows = [r for r, _ in labels]
    slot_times = [t for _, t in labels]

    # Leer nombres de dias desde el header real de la tabla
    # (algunas tablas tienen columnas duplicadas o faltantes)
    col_days = list(_DAYS)  # fallback
    if grid and grid[0]:
        for c in range(min(6, len(grid[0]))):
            cell = grid[0][c]
            if cell and cell["type"] == "th" and cell["text"].strip():
                text = cell["text"].strip()
                if text in ("Lunes", "Martes", "Miércoles", "Jueves", "Viernes", "Sábado"):
                    while len(col_days) <= c:
                        col_days.append(f"col{c}")
                    col_days[c] = text

    entries = []

    for r in range(1, len(grid)):
        for c in range(1, min(6, len(grid[r]))):
            if not starts[r][c]:
                continue
            cell = grid[r][c]
            if not cell or cell["type"] != "td":
                continue
            text = cell["text"].strip()
            if not text:
                continue

            rs = cell["rowspan"]

            # Encontrar slot de inicio: el slot con row mas alto que sea <= r
            start_slot_idx = 0
            for i, sr in enumerate(slot_rows):
                if sr <= r:
                    start_slot_idx = i

            start_mins = slot_times[start_slot_idx]

            # End time: buscar el label con row mas alto que sea <= end_row.
            # Esto es mas robusto que el enfoque anterior (avanzar n_slots
            # por indice de label) porque no depende de que la tabla tenga
            # todas las etiquetas de tiempo. Cuando faltan labels intermedios,
            # el indice de inicio se desplaza y el offset n_slots produce
            # end_times incorrectos. Usando la posicion fisica de la fila
            # (end_row = r + rowspan) y buscando el label correspondiente,
            # se obtienen resultados consistentes entre tablas con distinta
            # cantidad de labels.
            # NOTA: Tablas nocturnas con labels faltantes (ej: omiten 20:00
            # y 22:00) aun pueden producir end_times imprecisos porque el
            # label mas cercano a end_row no es el correcto. Requiere
            # revision manual. Ver .claude/commands/cargar-horarios-fceia.md.
            end_row = r + rs
            end_mins = slot_times[0]
            for sr, st in zip(slot_rows, slot_times):
                if sr <= end_row:
                    end_mins = st

            subject, aula = _extract_subject_and_aula(text)
            day = col_days[c] if c < len(col_days) else f"col{c}"

            entries.append(ScheduleEntry(
                subject=subject,
                day=day,
                start=_mins_to_time(start_mins),
                end=_mins_to_time(end_mins),
                rowspan=rs,
                aula=aula,
            ))

    return entries


# =============================================================================
# Fetch + parse completo
# =============================================================================

def fetch_html(url: str) -> str:
    """Descarga HTML de una URL usando curl."""
    result = subprocess.run(
        ["curl", "-s", url],
        capture_output=True, text=True, timeout=30,
    )
    if result.returncode != 0:
        raise RuntimeError(f"curl fallo con codigo {result.returncode}: {result.stderr}")
    return result.stdout


def extract_tables_html(html: str) -> list[str]:
    """Extrae el HTML interno de todas las <table> en la pagina."""
    return re.findall(r"<table[^>]*>(.*?)</table>", html, re.DOTALL)


def fetch_and_parse(url: str) -> list[ParsedTable]:
    """Descarga una pagina y parsea todas las tablas de horario.

    Retorna una lista de ParsedTable, una por comision/tabla encontrada.
    """
    html = fetch_html(url)
    tables_html = extract_tables_html(html)

    results = []
    for idx, table_html in enumerate(tables_html):
        entries = extract_entries_from_table(table_html)
        if entries:
            results.append(ParsedTable(
                index=idx,
                title=f"Tabla {idx}",
                entries=entries,
            ))

    return results


# =============================================================================
# CLI
# =============================================================================

def main():
    import argparse
    parser = argparse.ArgumentParser(
        description="Parsear horarios de FCEIA desde la web"
    )
    parser.add_argument("--url", required=True, help="URL de la pagina de horarios")
    parser.add_argument("--dump-json", action="store_true", help="Salida en JSON")
    args = parser.parse_args()

    tables = fetch_and_parse(args.url)

    if args.dump_json:
        data = []
        for t in tables:
            data.append({
                "index": t.index,
                "title": t.title,
                "entries": [
                    {
                        "subject": e.subject,
                        "day": e.day,
                        "start": e.start.strftime("%H:%M"),
                        "end": e.end.strftime("%H:%M"),
                        "aula": e.aula,
                    }
                    for e in t.entries
                ],
            })
        print(json.dumps(data, indent=2, ensure_ascii=False))
    else:
        for t in tables:
            print(f"\n=== {t.title} ({len(t.entries)} entries) ===")
            for e in t.entries:
                print(
                    f"  {e.day:12s} {e.start.strftime('%H:%M')}-{e.end.strftime('%H:%M')}  "
                    f"{e.subject}"
                )

    print(f"\nTotal: {len(tables)} tablas, "
          f"{sum(len(t.entries) for t in tables)} entries", file=sys.stderr)


if __name__ == "__main__":
    main()
