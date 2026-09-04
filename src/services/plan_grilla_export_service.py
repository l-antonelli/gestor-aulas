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
from openpyxl.styles import Alignment, Font, PatternFill
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


def _write_cronograma_sheet(
    ws,
    grid_data: dict[str, list[ScheduleBlock]],
) -> None:
    """Escribe la hoja Cronograma con una matriz día × franja al
    estilo calendario visual.

    Cada bloque ocupa una celda con el resumen: código de materia [Cx].
    Cuando varios bloques ocupan la misma celda (mismo día + franja
    de 15 min), se unen con salto de línea.
    """
    ws.title = "Cronograma"

    # Slots de 15 min entre 7:00 y 23:00 (rango operativo típico).
    # No dependemos de ConfiguracionHoraria acá para mantener el
    # export estable — la vista de UI usa la config, pero el Excel
    # necesita una grilla predecible.
    slots: list[tuple[int, int]] = []
    for h in range(7, 23):
        for m in (0, 15, 30, 45):
            slots.append((h * 60 + m, h * 60 + m + 15))

    def _fmt_slot(a: int, b: int) -> str:
        return (
            f"{a // 60:02d}:{a % 60:02d}–"
            f"{b // 60:02d}:{b % 60:02d}"
        )

    # Header.
    ws.cell(row=1, column=1, value="Franja")
    _fill_header(ws.cell(row=1, column=1))
    for j, dia in enumerate(DIAS_ORDER, start=2):
        c = ws.cell(row=1, column=j, value=dia)
        _fill_header(c)
    ws.column_dimensions["A"].width = 14
    for j in range(2, 2 + len(DIAS_ORDER)):
        ws.column_dimensions[get_column_letter(j)].width = 20

    # Filas por slot.
    for i, (a, b) in enumerate(slots, start=2):
        ws.cell(row=i, column=1, value=_fmt_slot(a, b))
        for j, dia in enumerate(DIAS_ORDER, start=2):
            blocks_dia = grid_data.get(dia, [])
            bloques_en_celda = []
            for blk in blocks_dia:
                h_s = (
                    blk.hora_inicio.hour * 60 + blk.hora_inicio.minute
                )
                h_e = blk.hora_fin.hour * 60 + blk.hora_fin.minute
                if h_s < b and h_e > a:
                    com_tag = (
                        f" [C{blk.comision_numero}]"
                        if blk.comision_numero else ""
                    )
                    resumen = f"{blk.materia_codigo}{com_tag}"
                    if blk.aula_label:
                        resumen += f" · {blk.aula_label}"
                    elif blk.virtual:
                        resumen += " · Virtual"
                    bloques_en_celda.append(resumen)
            if bloques_en_celda:
                cell = ws.cell(
                    row=i, column=j,
                    value="\n".join(bloques_en_celda),
                )
                cell.alignment = Alignment(
                    wrap_text=True, vertical="top",
                )

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
