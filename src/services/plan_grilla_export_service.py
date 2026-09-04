"""Export a Excel del cronograma de la Grilla Horaria del plan.

Genera un ``.xlsx`` con 3 hojas:

1. **Metadata** — plan, ciclo, filtros aplicados, timestamp.
2. **Cronograma** — matriz día × franja al estilo calendario visual.
3. **Detalle** — tabla plana con una fila por horario (materia,
   comisión, día, hora, aula, modalidad, alcance).

Diseñado para consumo por parte de la administración académica al
publicar cronogramas por carrera / año / cuatri o listados de
comunes.
"""

from __future__ import annotations

from datetime import datetime
from io import BytesIO

from openpyxl import Workbook
from openpyxl.styles import (
    Alignment, Border, Font, PatternFill, Side,
)
from openpyxl.utils import get_column_letter

from src.services.schedule_service import ScheduleBlock


DIAS_ORDER = [
    "Lunes", "Martes", "Miércoles", "Jueves", "Viernes", "Sábado",
]


def _fill_header(cell) -> None:
    cell.font = Font(bold=True, color="FFFFFF")
    cell.fill = PatternFill(
        "solid", fgColor="1E88E5",
    )
    cell.alignment = Alignment(horizontal="center", vertical="center")


def _fmt_time(t) -> str:
    return t.strftime("%H:%M") if t else ""


def _write_metadata_sheet(
    ws,
    plan_nombre: str,
    ciclo_label: str,
    filtros: dict,
) -> None:
    """Escribe la hoja Metadata con contexto del export."""
    ws.title = "Metadata"
    ws.column_dimensions["A"].width = 26
    ws.column_dimensions["B"].width = 60

    ws["A1"] = "Cronograma del plan"
    ws["A1"].font = Font(bold=True, size=14)
    ws.merge_cells("A1:B1")

    ahora = datetime.now().strftime("%Y-%m-%d %H:%M")
    filas = [
        ("Plan", plan_nombre),
        ("Ciclo", ciclo_label),
        ("Exportado", ahora),
        ("", ""),
        ("Filtros aplicados", ""),
    ]
    row = 3
    for k, v in filas:
        ws.cell(row=row, column=1, value=k).font = Font(bold=True)
        ws.cell(row=row, column=2, value=v)
        row += 1

    for label, valor in filtros.items():
        if not valor:
            valor = "(sin filtro)"
        ws.cell(row=row, column=1, value=label)
        ws.cell(row=row, column=2, value=valor)
        row += 1


_MATERIA_PALETTE = [
    ("1E88E5", "FFFFFF"),  # azul
    ("43A047", "FFFFFF"),  # verde
    ("F4511E", "FFFFFF"),  # naranja
    ("8E24AA", "FFFFFF"),  # violeta
    ("00897B", "FFFFFF"),  # turquesa
    ("FFB300", "212121"),  # amarillo (texto oscuro)
    ("3949AB", "FFFFFF"),  # indigo
    ("D81B60", "FFFFFF"),  # magenta
    ("039BE5", "FFFFFF"),  # celeste
    ("7CB342", "FFFFFF"),  # verde lima
    ("6D4C41", "FFFFFF"),  # marrón
    ("546E7A", "FFFFFF"),  # gris azulado
]
_EMPTY_FILL = "F5F5F5"      # fondo suave del cronograma vacío
_EMPTY_BORDER = "E0E0E0"


def _color_para_materia(codigo: str) -> tuple[str, str]:
    """Asigna un color determinístico por código de materia."""
    idx = sum(ord(c) for c in codigo) % len(_MATERIA_PALETTE)
    return _MATERIA_PALETTE[idx]


def _minutos_bloque(blk: ScheduleBlock) -> tuple[int, int]:
    return (
        blk.hora_inicio.hour * 60 + blk.hora_inicio.minute,
        blk.hora_fin.hour * 60 + blk.hora_fin.minute,
    )


def _asignar_lanes(blocks: list[ScheduleBlock]) -> tuple[
    list[tuple[ScheduleBlock, int]], int
]:
    """Asigna a cada bloque un "lane" (sub-columna) sin solapes.

    Es el algoritmo clásico de coloreo greedy para intervalos:
    ordenamos por hora de inicio y asignamos el lane libre más bajo.
    Dos bloques en el mismo lane nunca se solapan.

    Devuelve (lista de (block, lane_idx), cantidad total de lanes).
    """
    if not blocks:
        return [], 1
    ordenados = sorted(blocks, key=lambda b: _minutos_bloque(b))
    lanes_end: list[int] = []  # fin del último bloque en cada lane
    asignaciones: list[tuple[ScheduleBlock, int]] = []
    for blk in ordenados:
        h_s, h_e = _minutos_bloque(blk)
        lane_asignado = None
        for idx, end in enumerate(lanes_end):
            if end <= h_s:
                lane_asignado = idx
                lanes_end[idx] = h_e
                break
        if lane_asignado is None:
            lane_asignado = len(lanes_end)
            lanes_end.append(h_e)
        asignaciones.append((blk, lane_asignado))
    return asignaciones, max(1, len(lanes_end))


def _resumen_bloque(blk: ScheduleBlock) -> str:
    """Texto del contenido de un bloque en la hoja Cronograma."""
    com_tag = f" [C{blk.comision_numero}]" if blk.comision_numero else ""
    lineas = [f"{blk.materia_codigo}{com_tag}"]
    if blk.materia_nombre:
        lineas.append(blk.materia_nombre)
    if blk.virtual:
        lineas.append("💻 Virtual")
    elif blk.aula_label:
        emoji = "🧪" if blk.tipo_clase == "laboratorio" else "📖"
        lineas.append(f"{emoji} {blk.aula_label}")
    return "\n".join(lineas)


def _write_cronograma_sheet(
    ws,
    grid_data: dict[str, list[ScheduleBlock]],
) -> None:
    """Escribe la hoja Cronograma con una matriz día × franja tipo
    calendario visual, con:

    - **Sub-columnas por día** cuando hay clases paralelas: si un día
      tiene N bloques simultáneos como máximo, se dedica N columnas
      a ese día. Los días sin paralelismo ocupan 1 sola columna.
    - **Merge de celdas** verticalmente para cada bloque a lo largo
      de todas las franjas de 15 min que ocupa (por eso una clase
      de 2h se ve como un rectángulo unido, no como 8 celdas).
    - **Fondo suave** en toda la grilla (celdas vacías) y **color
      por materia** (determinístico por hash del código) en cada
      bloque, con texto blanco/oscuro según luminosidad del fondo.
    """
    ws.title = "Cronograma"

    # Slots de 15 min entre 7:00 y 23:00 (rango operativo típico).
    slots: list[tuple[int, int]] = []
    for h in range(7, 23):
        for m in (0, 15, 30, 45):
            slots.append((h * 60 + m, h * 60 + m + 15))
    n_slots = len(slots)

    def _fmt_slot(a: int, b: int) -> str:
        return (
            f"{a // 60:02d}:{a % 60:02d}–"
            f"{b // 60:02d}:{b % 60:02d}"
        )

    # Paso 1: lanes por día. Cada día tiene N lanes (sub-columnas)
    # según cuántos bloques paralelos tenga como máximo.
    lanes_por_dia: dict[str, list[tuple[ScheduleBlock, int]]] = {}
    ancho_dia: dict[str, int] = {}
    for dia in DIAS_ORDER:
        blocks = grid_data.get(dia, [])
        asign, n_lanes = _asignar_lanes(blocks)
        lanes_por_dia[dia] = asign
        ancho_dia[dia] = n_lanes

    # Paso 2: mapear día → rango de columnas.
    dia_col_start: dict[str, int] = {}
    col = 2  # A es franja
    for dia in DIAS_ORDER:
        dia_col_start[dia] = col
        col += ancho_dia[dia]
    total_cols = col - 1

    # Bordes finos para toda la grilla.
    thin = Side(style="thin", color=_EMPTY_BORDER)
    grid_border = Border(
        left=thin, right=thin, top=thin, bottom=thin,
    )

    # Paso 3: header (fila 1 = día, con merge sobre sus lanes).
    ws.cell(row=1, column=1, value="Franja")
    _fill_header(ws.cell(row=1, column=1))
    for dia in DIAS_ORDER:
        c0 = dia_col_start[dia]
        c1 = c0 + ancho_dia[dia] - 1
        cell = ws.cell(row=1, column=c0, value=dia)
        _fill_header(cell)
        if c1 > c0:
            ws.merge_cells(
                start_row=1, start_column=c0,
                end_row=1, end_column=c1,
            )

    # Paso 4: llenar toda la grilla con fondo suave + label de franja
    # en la columna A. Los bloques se pintan encima en el paso 5.
    empty_fill = PatternFill("solid", fgColor=_EMPTY_FILL)
    for i, (a, b) in enumerate(slots, start=2):
        franja_cell = ws.cell(row=i, column=1, value=_fmt_slot(a, b))
        franja_cell.font = Font(bold=True, size=9)
        franja_cell.alignment = Alignment(
            horizontal="right", vertical="center",
        )
        franja_cell.border = grid_border
        for j in range(2, total_cols + 1):
            c = ws.cell(row=i, column=j)
            c.fill = empty_fill
            c.border = grid_border

    # Paso 5: pintar cada bloque como un rectángulo unido en su(s)
    # columna(s) y rango de slots.
    slot_start = {s[0]: i for i, s in enumerate(slots)}
    for dia in DIAS_ORDER:
        for blk, lane in lanes_por_dia[dia]:
            h_s, h_e = _minutos_bloque(blk)
            # Índices de slot [start, end) que cubre el bloque.
            si_start = None
            si_end = None
            for si, (a, b) in enumerate(slots):
                if h_s < b and h_e > a:
                    if si_start is None:
                        si_start = si
                    si_end = si
            if si_start is None:
                continue

            r0 = si_start + 2
            r1 = si_end + 2
            c0 = dia_col_start[dia] + lane
            # (Los bloques siempre ocupan 1 sola columna, no
            # atraviesan lanes.)
            bg, fg = _color_para_materia(blk.materia_codigo)
            fill = PatternFill("solid", fgColor=bg)
            texto = _resumen_bloque(blk)
            cell = ws.cell(row=r0, column=c0, value=texto)
            cell.fill = fill
            cell.font = Font(bold=True, color=fg, size=9)
            cell.alignment = Alignment(
                horizontal="center",
                vertical="center",
                wrap_text=True,
            )
            cell.border = grid_border
            if r1 > r0:
                ws.merge_cells(
                    start_row=r0, start_column=c0,
                    end_row=r1, end_column=c0,
                )
                # Rellenar y bordear también las celdas mergeadas
                # para que el color/borde se aplique al rango entero.
                for r in range(r0 + 1, r1 + 1):
                    _c = ws.cell(row=r, column=c0)
                    _c.fill = fill
                    _c.border = grid_border

    # Anchos de columna: franja angosta, días anchos.
    ws.column_dimensions["A"].width = 12
    for j in range(2, total_cols + 1):
        # Anchura por lane: 22 si el día tiene 1 lane, 18 si tiene
        # más (para que quepan todos sin scroll horizontal).
        ws.column_dimensions[get_column_letter(j)].width = 20
    # Altura mínima de fila para que 3 líneas quepan bien.
    for i in range(2, n_slots + 2):
        ws.row_dimensions[i].height = 18

    ws.freeze_panes = "B2"


def _write_detalle_sheet(
    ws,
    grid_data: dict[str, list[ScheduleBlock]],
) -> None:
    """Tabla plana con una fila por horario, filtrable en Excel."""
    ws.title = "Detalle"
    headers = [
        "Materia (código)",
        "Materia (nombre)",
        "Comisión",
        "Alcance",
        "Día",
        "Hora inicio",
        "Hora fin",
        "Aula",
        "Modalidad",
    ]
    for j, h in enumerate(headers, start=1):
        c = ws.cell(row=1, column=j, value=h)
        _fill_header(c)

    # Widths.
    widths = [16, 40, 20, 30, 12, 12, 12, 30, 14]
    for j, w in enumerate(widths, start=1):
        ws.column_dimensions[get_column_letter(j)].width = w

    # Recolectar todos los bloques y ordenar por día → hora → materia.
    filas: list[ScheduleBlock] = []
    for dia in DIAS_ORDER:
        for b in grid_data.get(dia, []):
            filas.append(b)

    # (dia, hora_inicio) para ordenar respetando el orden de DIAS_ORDER.
    dia_idx = {d: i for i, d in enumerate(DIAS_ORDER)}
    filas.sort(
        key=lambda b: (
            dia_idx.get(_dia_de_block(b, grid_data), 99),
            b.hora_inicio,
            b.materia_codigo,
        )
    )

    for i, b in enumerate(filas, start=2):
        modalidad = (
            "Virtual" if b.virtual
            else ("Teórica" if b.tipo_clase == "teorica"
                  else ("Laboratorio" if b.tipo_clase == "laboratorio"
                        else "—"))
        )
        aula_txt = (
            "Virtual" if b.virtual
            else (b.aula_label or "Sin aula")
        )
        alcance = b.carreras_label or "—"
        com_txt = (
            b.comision_nombre or
            (f"C{b.comision_numero}" if b.comision_numero else "—")
        )
        ws.cell(row=i, column=1, value=b.materia_codigo)
        ws.cell(row=i, column=2, value=b.materia_nombre)
        ws.cell(row=i, column=3, value=com_txt)
        ws.cell(row=i, column=4, value=alcance)
        ws.cell(row=i, column=5, value=_dia_de_block(b, grid_data))
        ws.cell(row=i, column=6, value=_fmt_time(b.hora_inicio))
        ws.cell(row=i, column=7, value=_fmt_time(b.hora_fin))
        ws.cell(row=i, column=8, value=aula_txt)
        ws.cell(row=i, column=9, value=modalidad)

    # Autofilter en toda la tabla.
    if filas:
        ws.auto_filter.ref = (
            f"A1:{get_column_letter(len(headers))}{len(filas) + 1}"
        )
    ws.freeze_panes = "A2"


def _dia_de_block(
    block: ScheduleBlock,
    grid_data: dict[str, list[ScheduleBlock]],
) -> str:
    """Recupera el día del bloque desde la clave del grid_data.

    `ScheduleBlock` no guarda el día (viene implícito del key del
    dict de la grilla). Al aplanar para la hoja Detalle, necesitamos
    reasociar.
    """
    for dia, blocks in grid_data.items():
        if any(b.entry_id == block.entry_id for b in blocks):
            return dia
    return ""


def export_grilla_a_xlsx(
    grid_data: dict[str, list[ScheduleBlock]],
    plan_nombre: str,
    ciclo_label: str,
    filtros: dict,
) -> bytes:
    """Genera el Excel completo y devuelve los bytes listos para
    ofrecer al usuario via ``st.download_button``.

    Args:
        grid_data: día → lista de ScheduleBlock (lo que la UI ya
            filtró; el export exporta exactamente lo que hay en el
            grid, sin re-filtrar).
        plan_nombre: nombre visible del plan (para la hoja Metadata).
        ciclo_label: label del ciclo (ej. '2026-1C').
        filtros: dict ``{"Nombre filtro": "valor"}`` para la hoja
            Metadata. Ej.: ``{"Carrera": "A · Electrónica", ...}``.

    Returns:
        bytes del archivo .xlsx.
    """
    wb = Workbook()
    default = wb.active
    _write_metadata_sheet(default, plan_nombre, ciclo_label, filtros)
    cronograma_ws = wb.create_sheet("Cronograma")
    _write_cronograma_sheet(cronograma_ws, grid_data)
    detalle_ws = wb.create_sheet("Detalle")
    _write_detalle_sheet(detalle_ws, grid_data)

    buf = BytesIO()
    wb.save(buf)
    return buf.getvalue()


def build_export_filename(
    plan_nombre: str,
    ciclo_label: str,
    filtros: dict,
) -> str:
    """Nombre de archivo sugerido para el download.

    Formato: ``plan_ciclo_ubicacion_alcance_YYYYMMDD.xlsx``.
    Los filtros que estén en 'Todas'/vacío se omiten.
    """
    fecha = datetime.now().strftime("%Y%m%d")
    partes = [_slug(plan_nombre), _slug(ciclo_label)]
    car = filtros.get("Carrera")
    anio = filtros.get("Año")
    cuatri = filtros.get("Cuatrimestre")
    if car and car != "(sin filtro)":
        partes.append(_slug(str(car)))
    if anio and anio != "(sin filtro)":
        partes.append(_slug(str(anio)))
    if cuatri and cuatri != "(sin filtro)":
        partes.append(_slug(str(cuatri)))
    alcance = filtros.get("Alcance")
    if alcance and alcance not in ("Todas", "(sin filtro)"):
        partes.append(_slug(str(alcance)))
    partes.append(fecha)
    base = "_".join(p for p in partes if p)
    return f"{base}.xlsx"


def _slug(s: str) -> str:
    import re
    import unicodedata

    # Normalizar acentos y símbolos unicode a ASCII equivalente para
    # que el nombre del archivo sea seguro en cualquier filesystem.
    s = unicodedata.normalize("NFKD", s)
    s = "".join(c for c in s if not unicodedata.combining(c))
    s = s.strip().replace(" ", "-").replace("·", "").replace(",", "")
    s = re.sub(r"[^\w\-]", "", s)
    return re.sub(r"-+", "-", s).strip("-").lower()
