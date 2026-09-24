"""Generación de plantillas Excel para carga masiva de datos.

Módulo transversal del rediseño Cronogramas + Inscriptos (fases C1 y E1
del rediseño 2026-09-15). El objetivo es que el usuario final —una
persona que recibe datos de horarios o de inscriptos de las cátedras
por email— pueda descargar una plantilla con **listas predeterminadas
de códigos válidos** integradas via ``openpyxl.DataValidation``, y
sepa exactamente qué se puede escribir en cada columna sin necesidad
de consultar el catálogo por afuera.

La plantilla no valida contra reglas de negocio (unicidad de
comisión, gap horario, etc.): esas se ejecutan en el `import_service`
al momento del preview. Acá sólo se hacen los ``DataValidation``
tipográficos (valor en lista, formato de hora, número no negativo).

Convenciones:
- Las hojas de listas se prefijan con ``_`` y se marcan ``sheet_state
  = "hidden"``. Excel las respeta y no las muestra en las pestañas
  inferiores.
- La hoja principal se llama con nombre descriptivo (``"Horarios"``,
  ``"Inscriptos"``).
- Una hoja **``Instrucciones``** en castellano abre el archivo como
  primera pestaña activa — el usuario ve la guía antes que la
  tabla vacía.
"""

from __future__ import annotations

import io
from typing import Iterable

from openpyxl import Workbook
from openpyxl.styles import Alignment, Font, PatternFill
from openpyxl.utils import get_column_letter
from openpyxl.worksheet.datavalidation import DataValidation
from sqlmodel import Session, select

from src.database.models import CicloDB, MateriaDB
from src.services.dictado_service import get_materias_esperadas_from_dictados


# =============================================================================
# Constantes de estilo
# =============================================================================

HEADER_FONT = Font(bold=True, color="FFFFFF")
HEADER_FILL = PatternFill("solid", fgColor="366092")
HEADER_ALIGN = Alignment(horizontal="center", vertical="center", wrap_text=True)

EJEMPLO_FILL = PatternFill("solid", fgColor="FFF2CC")  # amarillo claro
EJEMPLO_FONT = Font(italic=True, color="7F6000")

INSTRUCCIONES_TITLE_FONT = Font(bold=True, size=14, color="366092")
INSTRUCCIONES_HEADER_FONT = Font(bold=True, size=11)


# =============================================================================
# Cronograma
# =============================================================================

# Columnas del template de horarios (canónicas). Orden importa — así se
# escriben en la hoja. Los alias reconocidos por el parser están en
# `horario_file_parser.COLUMN_ALIASES`; acá se usan los canónicos.
#
# 2026-09-23: la comisión se declara con CÓDIGO numérico obligatorio
# (`codigo_comision` → `ComisionDB.numero`, lo que se ve en los
# cronogramas) + `nombre_comision` opcional. Además `nombre_materia`
# permite elegir la materia por nombre: al elegirlo, la columna
# `codigo_materia` se autocompleta con una fórmula que busca en la
# hoja `Materias`.
HORARIO_COLUMNS: list[tuple[str, str, int]] = [
    # (nombre_columna, ayuda, ancho_columna)
    (
        "codigo_materia",
        "Código de la materia (lista de la hoja 'Materias'). Se "
        "autocompleta al elegir el nombre en la columna de al lado; "
        "si lo elegís directo, el nombre aparece en la columna "
        "'verificacion'.",
        16,
    ),
    (
        "nombre_materia",
        "Nombre de la materia (lista de la hoja 'Materias'). Al "
        "elegirlo se autocompleta el código.",
        34,
    ),
    (
        "verificacion",
        "NO completar: se llena sola. Muestra el nombre de la materia "
        "al elegir un código, y avisa si el código y el nombre no se "
        "corresponden.",
        34,
    ),
    (
        "codigo_comision",
        "Código numérico de la comisión (entero >= 1, obligatorio). "
        "Es lo que se ve en los cronogramas (C1, C2, ...).",
        14,
    ),
    (
        "nombre_comision",
        "Nombre descriptivo de la comisión (opcional; ej: 'Mañana', "
        "'A', 'Nocturno').",
        16,
    ),
    (
        "dia",
        "Día de la semana (Lunes, Martes, ...).",
        11,
    ),
    (
        "hora_inicio",
        "Hora de inicio en formato HH:MM (ej: 08:00). Debe ser "
        "anterior a hora_fin.",
        11,
    ),
    (
        "hora_fin",
        "Hora de fin en formato HH:MM (ej: 11:00).",
        11,
    ),
    (
        "tipo_clase",
        "Opcional: dejalo vacío y el tipo lo determina la asignación "
        "automática (LP). 'teorica' o 'laboratorio' si la cátedra lo "
        "predetermina.",
        14,
    ),
    (
        "virtual",
        "VERDADERO = clase virtual (sin aula). Vacío o FALSO = "
        "presencial. Un laboratorio no puede ser virtual.",
        11,
    ),
]

DIAS_SEMANA = [
    "Lunes", "Martes", "Miércoles", "Jueves", "Viernes", "Sábado", "Domingo",
]

TIPOS_CLASE = ["teorica", "laboratorio"]

# 2026-09-23: virtual es un booleano — la lista ofrece los booleanos
# REALES de Excel (se muestran VERDADERO/FALSO en castellano). Elegir
# del desplegable deja un bool en la celda; con textos ("SI"/"NO" o
# "TRUE"/"FALSE") Excel coerciona lo tipeado a booleano y la
# validación de lista rechazaría el valor por diferencia de tipo.
VIRTUAL_OPCIONES = [True, False]


def _slots_horarios_validos(
    granularidad_min: int,
    inicio,
    fin,
) -> list[str]:
    """Devuelve la lista de horas HH:MM válidas según la config.

    Va desde `inicio` hasta `fin` inclusive, en pasos de
    `granularidad_min` minutos. Ambos extremos entran en la lista
    porque son valores válidos como inicio o fin de una clase.

    Ejemplo: granularidad=15, inicio=07:00, fin=23:00 → ["07:00",
    "07:15", ..., "23:00"] (65 elementos).
    """
    from datetime import datetime, timedelta

    if granularidad_min <= 0:
        granularidad_min = 15

    _base = datetime(2000, 1, 1, inicio.hour, inicio.minute)
    _fin_dt = datetime(2000, 1, 1, fin.hour, fin.minute)
    # Interpretar `fin=00:00` como medianoche (24:00).
    if fin.hour == 0 and fin.minute == 0:
        _fin_dt = datetime(2000, 1, 2, 0, 0)

    slots: list[str] = []
    cur = _base
    delta = timedelta(minutes=granularidad_min)
    while cur <= _fin_dt:
        slots.append(cur.strftime("%H:%M"))
        cur += delta
    return slots


def _escribir_hoja_lista(
    wb: Workbook, nombre_hoja: str, valores: Iterable[str | bool],
) -> str:
    """Crea una hoja oculta con la lista de valores y devuelve la
    fórmula que un ``DataValidation`` puede usar como ``formula1``.

    Formato Excel para referenciar una lista externa desde
    ``DataValidation``: ``=NombreHoja!$A$1:$A$N``. El signo dólar
    fija las referencias y ``NombreHoja`` va sin comillas (nombres
    con guion bajo no las necesitan).
    """
    ws = wb.create_sheet(title=nombre_hoja)
    ws.sheet_state = "hidden"
    valores_l = list(valores)
    for i, v in enumerate(valores_l, start=1):
        ws.cell(row=i, column=1, value=v)
    if not valores_l:
        # Hoja vacía: devolver referencia vacía deliberada. Sin datos
        # válidos el DataValidation no se agrega.
        return ""
    return f"={nombre_hoja}!$A$1:$A${len(valores_l)}"


def _escribir_headers_horarios(ws) -> None:
    for col_idx, (nombre, ayuda, ancho) in enumerate(HORARIO_COLUMNS, start=1):
        cell = ws.cell(row=1, column=col_idx, value=nombre)
        cell.font = HEADER_FONT
        cell.fill = HEADER_FILL
        cell.alignment = HEADER_ALIGN
        cell.comment = None
        # Ayuda como comment nativo de Excel (aparece al hover).
        from openpyxl.comments import Comment
        cell.comment = Comment(ayuda, "gestor-aulas")
        letra = get_column_letter(col_idx)
        ws.column_dimensions[letra].width = ancho
    ws.row_dimensions[1].height = 32
    ws.freeze_panes = "A2"


def _agregar_data_validations_horarios(
    ws,
    wb: Workbook,
    materias_codigos: list[str],
    dias_operativos: list[str],
    slots_horarios: list[str],
) -> None:
    """Configura los ``DataValidation`` de la hoja Horarios.

    Fase H.2 del rediseño 2026-09-15: los días y las horas ahora
    salen de ``ConfiguracionHoraria`` en vez de estar hardcodeadas.

    - `dias_operativos`: lista ordenada de días válidos (ej: sin
      Domingo si la config lo excluye).
    - `slots_horarios`: lista de horas HH:MM discretizadas por
      granularidad de la config, en el rango operativo. Se usan
      tanto para ``hora_inicio`` como para ``hora_fin``.

    Cada validación se agrega a la hoja principal y referencia las
    hojas ocultas de listas. Se aplican a un rango generoso (filas
    2..1001) para cubrir importaciones grandes sin re-generar la
    plantilla.
    """
    max_row = 1001  # rango generoso para cargas típicas
    n_mat = len(materias_codigos)

    # Materia: desplegable en AMBAS columnas (pedido 2026-09-23) —
    # por código (A) y por nombre (B), las dos contra la hoja VISIBLE
    # `Materias`. Al elegir el nombre, la fórmula precargada en A
    # autocompleta el código; al elegir el código, la columna
    # `verificacion` (C) muestra el nombre — no se puede poner una
    # fórmula espejo en B porque A y B se referenciarían mutuamente
    # (referencia circular). La misma columna C avisa si el usuario
    # dejó un código y un nombre que no se corresponden, y el
    # importador rechaza esas filas de todos modos.
    if n_mat:
        dv_mat_cod = DataValidation(
            type="list",
            formula1=f"=Materias!$A$2:$A${n_mat + 1}",
            allow_blank=True,
            errorTitle="Código no válido",
            error=(
                "Elegí un código de la lista (hoja 'Materias'). Sólo "
                "se aceptan materias con dictado activo en este ciclo."
            ),
            showErrorMessage=True,
        )
        dv_mat_cod.add(f"A2:A{max_row}")
        ws.add_data_validation(dv_mat_cod)

        dv_mat_nom = DataValidation(
            type="list",
            formula1=f"=Materias!$B$2:$B${n_mat + 1}",
            allow_blank=True,
            errorTitle="Nombre no válido",
            error="Elegí un nombre de la lista (hoja 'Materias').",
            showErrorMessage=True,
        )
        dv_mat_nom.add(f"B2:B{max_row}")
        ws.add_data_validation(dv_mat_nom)

    # Código de comisión — entero >= 1, obligatorio.
    dv_cod_com = DataValidation(
        type="whole", operator="greaterThanOrEqual",
        formula1=1,
        allow_blank=False,
        errorTitle="Código de comisión no válido",
        error=(
            "El código de comisión debe ser un número entero mayor o "
            "igual a 1. Es obligatorio: identifica la comisión dentro "
            "de la materia (C1, C2, ...)."
        ),
        showErrorMessage=True,
    )
    dv_cod_com.add(f"D2:D{max_row}")
    ws.add_data_validation(dv_cod_com)

    # Día — lista cerrada según config.
    ref_dias = _escribir_hoja_lista(
        wb, "_dias", dias_operativos or DIAS_SEMANA,
    )
    dv_dia = DataValidation(
        type="list", formula1=ref_dias, allow_blank=False,
        errorTitle="Día no válido",
        error=(
            "Elegí un día de la lista. Sólo se aceptan los días "
            "operativos configurados en el sistema."
        ),
        showErrorMessage=True,
    )
    dv_dia.add(f"F2:F{max_row}")
    ws.add_data_validation(dv_dia)

    # Hora inicio / hora fin — lista desplegable de horas discretas
    # según granularidad + rango operativo.
    ref_horas = _escribir_hoja_lista(wb, "_horas", slots_horarios)
    if ref_horas:
        for col_letra, err_msg in (
            ("G", "Elegí la hora de inicio de la lista. Sólo se aceptan valores múltiplos de la granularidad configurada. Debe ser anterior a hora_fin."),  # noqa: E501
            ("H", "Elegí la hora de fin de la lista. Sólo se aceptan valores múltiplos de la granularidad configurada. Debe ser posterior a hora_inicio."),  # noqa: E501
        ):
            dv_hora = DataValidation(
                type="list", formula1=ref_horas, allow_blank=False,
                errorTitle="Hora no válida",
                error=err_msg,
                showErrorMessage=True,
            )
            dv_hora.add(f"{col_letra}2:{col_letra}{max_row}")
            ws.add_data_validation(dv_hora)

    # Tipo de clase — lista cerrada, permite blanco (= lo determina
    # la asignación automática).
    ref_tipos = _escribir_hoja_lista(wb, "_tipos", TIPOS_CLASE)
    dv_tipo = DataValidation(
        type="list", formula1=ref_tipos, allow_blank=True,
        errorTitle="Tipo de clase no válido",
        error=(
            "Dejalo vacío (lo determina la asignación automática) o "
            "elegí 'teorica' / 'laboratorio'."
        ),
        showErrorMessage=True,
    )
    dv_tipo.add(f"I2:I{max_row}")
    ws.add_data_validation(dv_tipo)

    # Virtual — booleano: lista de VERDADERO/FALSO reales; vacío =
    # FALSO (presencial).
    ref_virt = _escribir_hoja_lista(wb, "_virtual", VIRTUAL_OPCIONES)
    dv_virt = DataValidation(
        type="list", formula1=ref_virt, allow_blank=True,
        errorTitle="Valor no válido",
        error=(
            "Elegí VERDADERO o FALSO (vacío equivale a FALSO). "
            "Recordá: un laboratorio no puede ser virtual."
        ),
        showErrorMessage=True,
    )
    dv_virt.add(f"J2:J{max_row}")
    ws.add_data_validation(dv_virt)

    # Fórmulas precargadas (notación canónica inglesa — Excel las
    # localiza solo):
    #
    # - Columna A: auto-población del código a partir del nombre. Si
    #   el usuario elige/escribe el código, pisa la fórmula —
    #   comportamiento esperado.
    # - Columna C (`verificacion`): la dirección inversa. Muestra el
    #   nombre de la materia cuando la fila trae sólo el código, "OK"
    #   cuando código y nombre se corresponden, y una advertencia
    #   cuando no. No puede ir como fórmula en la celda B porque A y
    #   B se referenciarían mutuamente (referencia circular — Excel
    #   sólo lo tolera con cálculo iterativo, un ajuste de sesión
    #   frágil que depende de qué libro se abrió primero).
    if n_mat:
        _rango_cod = f"Materias!$A$2:$A${n_mat + 1}"
        _rango_nom = f"Materias!$B$2:$B${n_mat + 1}"
        for _r in range(2, max_row + 1):
            ws.cell(row=_r, column=1).value = (
                f'=IFERROR(INDEX({_rango_cod},'
                f'MATCH($B{_r},{_rango_nom},0)),"")'
            )
            _nom_de_a = (
                f'INDEX({_rango_nom},MATCH($A{_r},{_rango_cod},0))'
            )
            ws.cell(row=_r, column=3).value = (
                f'=IF($A{_r}="","",IFERROR('
                f'IF($B{_r}="",{_nom_de_a},'
                f'IF({_nom_de_a}=$B{_r},"OK",'
                f'"⚠ el código y el nombre no se corresponden")),'
                f'"⚠ código desconocido"))'
            )


def _escribir_hoja_materias(
    wb: Workbook, materias: list[tuple[str, str]],
) -> None:
    """Hoja VISIBLE `Materias` con la referencia código + nombre.

    2026-09-23: el usuario pidió tener los datos de las materias a la
    vista dentro del archivo, y poder elegir por nombre. Esta hoja
    alimenta las dos listas desplegables de la hoja `Horarios` y la
    fórmula que autocompleta el código. No es una hoja de datos a
    importar: el selector de hoja de la app la excluye.
    """
    ws = wb.create_sheet(title="Materias")
    for col_idx, (titulo, ancho) in enumerate(
        (("codigo", 16), ("nombre", 50)), start=1,
    ):
        cell = ws.cell(row=1, column=col_idx, value=titulo)
        cell.font = HEADER_FONT
        cell.fill = HEADER_FILL
        cell.alignment = HEADER_ALIGN
        ws.column_dimensions[get_column_letter(col_idx)].width = ancho
    for i, (cod, nom) in enumerate(materias, start=2):
        ws.cell(row=i, column=1, value=cod)
        ws.cell(row=i, column=2, value=nom)
    ws.freeze_panes = "A2"


def _escribir_hoja_instrucciones_cronograma(
    wb: Workbook, ciclo: CicloDB, n_materias: int,
) -> None:
    """Hoja de guía en castellano, se posiciona como primera pestaña."""
    ws = wb.create_sheet(title="Instrucciones", index=0)
    ws.column_dimensions["A"].width = 100

    def _t(row: int, txt: str, font: Font | None = None) -> None:
        cell = ws.cell(row=row, column=1, value=txt)
        if font is not None:
            cell.font = font
        cell.alignment = Alignment(wrap_text=True, vertical="top")

    row = 1
    _t(row, f"Plantilla de horarios — Ciclo {ciclo.id}",
       INSTRUCCIONES_TITLE_FONT)
    row += 2
    _t(row, "Cómo usar esta plantilla", INSTRUCCIONES_HEADER_FONT)
    row += 1
    _t(row,
       "1) Abrir la hoja 'Horarios' e ir completando una fila por "
       "horario. Cada horario es una aparición semanal de una "
       "comisión (ej: 'MAT101, comisión C1, lunes 8 a 11').")
    row += 1
    _t(row,
       "2) La materia se puede elegir por CÓDIGO o por NOMBRE (las "
       "dos columnas tienen lista desplegable). Al elegir el nombre, "
       "el código se completa solo; al elegir el código, el nombre "
       "aparece en la columna 'verificacion'. Esa misma columna "
       "avisa si quedó un código y un nombre que no se corresponden "
       "— la aplicación rechaza esas filas al importar. La hoja "
       "'Materias' tiene la referencia completa de códigos y "
       "nombres.")
    row += 1
    _t(row,
       "3) Guardar el archivo y subirlo desde la aplicación en la "
       "pestaña 'Cargar' del módulo Cronogramas.")
    row += 2

    _t(row, "Columnas de la hoja Horarios", INSTRUCCIONES_HEADER_FONT)
    row += 1
    for nombre, ayuda, _ancho in HORARIO_COLUMNS:
        _t(row, f"• {nombre} — {ayuda}")
        row += 1
    row += 1

    _t(row, "Listas desplegables", INSTRUCCIONES_HEADER_FONT)
    row += 1
    _t(row,
       f"• Materias: {n_materias} materias con dictado activo en el "
       "ciclo, elegibles por código o por nombre. Sólo se aceptan "
       "valores de la lista.")
    row += 1
    _t(row,
       "• Días: los días operativos configurados en el sistema, tal "
       "cual figuran (con mayúscula inicial).")
    row += 1
    _t(row,
       "• Tipo de clase: opcional. Vacío significa que el tipo lo "
       "determina la asignación automática; 'teorica' o "
       "'laboratorio' sólo si la cátedra lo predetermina.")
    row += 1
    _t(row,
       "• Virtual: VERDADERO = la clase se dicta virtual (no "
       "requiere aula). Vacío o FALSO = presencial. Consejo: en "
       "Excel moderno (365) podés seleccionar la columna 'virtual' e "
       "insertar una 'Casilla de verificación' (pestaña Insertar) — "
       "la columna queda con casillas para tildar, que son "
       "exactamente estos mismos valores VERDADERO/FALSO.")
    row += 2

    _t(row, "Reglas que valida la aplicación al importar",
       INSTRUCCIONES_HEADER_FONT)
    row += 1
    _t(row,
       "• La hora de inicio debe ser anterior a la hora de fin.")
    row += 1
    _t(row,
       "• Una clase de laboratorio no puede ser virtual (el "
       "laboratorio requiere un aula física).")
    row += 1
    _t(row,
       "• Si completás código Y nombre de materia, tienen que "
       "corresponderse — la columna 'verificacion' te avisa en el "
       "momento si no.")
    row += 1
    _t(row,
       "• El código de comisión es obligatorio y debe ser un entero "
       "mayor o igual a 1. Dos comisiones distintas de la misma "
       "materia no pueden compartir código ni nombre.")
    row += 2

    _t(row, "Consejos", INSTRUCCIONES_HEADER_FONT)
    row += 1
    _t(row,
       "• El código de comisión (C1, C2, ...) es lo que se ve en los "
       "cronogramas de la aplicación; el nombre es un texto "
       "descriptivo opcional ('Mañana', 'A', 'Nocturno').")
    row += 1
    _t(row,
       "• Si una comisión tiene varios horarios (ej: lunes 8-11 + "
       "miércoles 8-11), poner una fila por cada horario con el "
       "mismo código de comisión.")
    row += 1
    _t(row,
       "• La hoja Horarios es una tabla de Excel: si necesitás más "
       "de 1000 filas, escribí debajo de la última y la tabla se "
       "extiende sola con sus listas y fórmulas.")
    row += 1
    _t(row,
       "• Antes de importar, la aplicación muestra una vista previa "
       "con validaciones por materia: podés cancelar y corregir el "
       "Excel si algo no cierra, o ajustar los horarios ahí mismo.")
    row += 1
    _t(row,
       "• Al importar, si una materia ya tiene horarios cargados, "
       "elegís caso por caso si reemplazás lo existente, agregás las "
       "comisiones nuevas, o ignorás la materia en esa importación.")


def generar_plantilla_cronograma_excel(
    session: Session, ciclo_id: str,
) -> bytes:
    """Genera una plantilla Excel para cargar horarios en un cronograma.

    La plantilla incluye:
    - Hoja "Instrucciones" con guía en castellano rioplatense.
    - Hoja "Horarios" con headers, ancho de columnas y freeze (sin
      fila de ejemplo — task #341).
    - Hoja VISIBLE "Materias" con la referencia código+nombre de las
      materias con dictado activo (2026-09-23): alimenta los
      desplegables por código y por nombre, la fórmula que
      autocompleta el código al elegir un nombre, y la columna
      ``verificacion`` que muestra el nombre al elegir un código y
      avisa si código y nombre no se corresponden (la fórmula espejo
      en la celda del nombre sería una referencia circular).
    - El área de datos es una TABLA de Excel (``TablaHorarios``):
      filas nuevas heredan fórmulas y validaciones, filtros por
      columna y bandeado de filas.
    - Hojas ocultas ``_dias``, ``_horas``, ``_tipos``, ``_virtual``
      que alimentan el resto de las listas desplegables.
    - Validaciones: código de comisión entero >= 1 (obligatorio),
      horas discretas según granularidad, tipo de clase opcional,
      virtual booleano VERDADERO/FALSO (vacío = FALSO; en Excel 365
      la columna puede convertirse en casillas de verificación
      nativas seleccionándola e insertando "Casilla").

    Args:
        session: sesión activa.
        ciclo_id: identificador del ``CicloDB`` para el que se genera
            la plantilla. Los códigos válidos salen de los dictados
            activos del ciclo (misma fuente que
            ``validar_cronograma``).

    Returns:
        Bytes del Excel listos para ``st.download_button``.

    Raises:
        ValueError si el ciclo no existe o no tiene dictados creados
        (sin dictados no hay lista de materias posibles).
    """
    ciclo = session.get(CicloDB, ciclo_id)
    if ciclo is None:
        raise ValueError(f"Ciclo '{ciclo_id}' no existe.")

    esperadas = get_materias_esperadas_from_dictados(session, ciclo_id)
    if not esperadas:
        raise ValueError(
            f"El ciclo '{ciclo_id}' no tiene dictados creados. Ir a "
            "Ciclos → Dictados y crear los dictados antes de generar "
            "la plantilla."
        )

    # Ordenar códigos alfabéticamente para que el dropdown sea navegable.
    codigos_ordenados = sorted(esperadas.keys())

    # Fase H.2 del rediseño 2026-09-15: leer ConfiguracionHoraria
    # para restringir los dropdowns de día y hora a valores válidos.
    from src.database.models import ConfiguracionHoraria
    _config = session.exec(select(ConfiguracionHoraria).limit(1)).first()
    if _config is not None:
        _dias_operativos = [
            d.strip() for d in (_config.dias_operativos or "").split(",")
            if d.strip()
        ]
        _slots = _slots_horarios_validos(
            _config.granularidad_minutos or 15,
            _config.hora_inicio_operativo,
            _config.hora_fin_operativo,
        )
    else:
        _dias_operativos = list(DIAS_SEMANA)
        # Sin config, fallback a granularidad 15 min 07:00-23:00.
        from datetime import time as _time
        _slots = _slots_horarios_validos(15, _time(7, 0), _time(23, 0))

    wb = Workbook()
    # openpyxl siempre crea una hoja "Sheet" al inicio — la usamos
    # como la hoja principal renombrada.
    ws_main = wb.active
    assert ws_main is not None
    ws_main.title = "Horarios"

    _escribir_headers_horarios(ws_main)
    # Hoja VISIBLE `Materias` (2026-09-23): referencia código+nombre
    # de todas las materias con dictado activo. Alimenta los dos
    # desplegables (por código y por nombre) y la fórmula que
    # autocompleta el código. Se crea ANTES de las validaciones porque
    # las fórmulas la referencian.
    _pares_materias = obtener_referencia_materias_del_ciclo(
        session, ciclo_id,
    )
    _escribir_hoja_materias(wb, _pares_materias)
    # Bugfix (2026-09-22, task #341): no se escribe fila de ejemplo en
    # la hoja Horarios porque el parser no distingue ejemplo de dato
    # real; el ejemplo textual queda en la hoja Instrucciones.
    # Los rangos de las listas referencian la hoja Materias, así que
    # la cantidad tiene que salir de los mismos pares.
    _agregar_data_validations_horarios(
        ws_main, wb, [c for c, _ in _pares_materias],
        dias_operativos=_dias_operativos,
        slots_horarios=_slots,
    )

    # Definir el área de datos como TABLA de Excel (2026-09-23). Qué
    # aporta: al escribir debajo de la última fila, la tabla se
    # extiende sola copiando fórmulas y validaciones (las filas más
    # allá de la 1001 no quedan "sueltas"), las columnas ganan
    # filtros y el bandeado de filas facilita la lectura. No afecta
    # al parser: pandas lee el rango de celdas igual.
    from openpyxl.worksheet.table import Table, TableStyleInfo
    _n_cols = len(HORARIO_COLUMNS)
    _tabla = Table(
        displayName="TablaHorarios",
        ref=f"A1:{get_column_letter(_n_cols)}1001",
    )
    _tabla.tableStyleInfo = TableStyleInfo(
        name="TableStyleMedium2",
        showRowStripes=True,
        showColumnStripes=False,
        showFirstColumn=False,
        showLastColumn=False,
    )
    ws_main.add_table(_tabla)

    _escribir_hoja_instrucciones_cronograma(wb, ciclo, len(codigos_ordenados))

    # Activar Instrucciones como primera pestaña visible al abrir.
    wb.active = 0

    buffer = io.BytesIO()
    wb.save(buffer)
    return buffer.getvalue()


# =============================================================================
# Referencia rápida sobre nombres de materia
# =============================================================================


def obtener_referencia_materias_del_ciclo(
    session: Session, ciclo_id: str,
) -> list[tuple[str, str]]:
    """Devuelve pares (codigo, nombre) de materias con dictado activo
    en el ciclo, ordenados por código. Útil para mostrar en la UI la
    lista de códigos que van a estar en el dropdown de la plantilla.

    No es parte del archivo Excel; se expone acá para el módulo UI.
    """
    esperadas = get_materias_esperadas_from_dictados(session, ciclo_id)
    if not esperadas:
        return []
    materias = list(session.exec(
        select(MateriaDB).where(
            MateriaDB.codigo.in_(list(esperadas.keys()))  # type: ignore[attr-defined]
        )
    ).all())
    return sorted(
        ((m.codigo, m.nombre) for m in materias),
        key=lambda t: t[0],
    )


# =============================================================================
# Inscriptos (Fase E1)
# =============================================================================

# Cuatrimestres válidos según `inscripcion_service.CUATRIS_VALIDOS`.
CUATRIS_INSCRIPTOS = ["1C", "2C", "Anual"]


INSCRIPTOS_COLUMNS: list[tuple[str, str, int]] = [
    (
        "codigo_materia",
        "Código de la materia. Debe estar en la lista de códigos válidos.",
        16,
    ),
    (
        "anio",
        "Año calendario del dato (ej: 2024). Rango sugerido: 2020-2035.",
        10,
    ),
    (
        "cuatrimestre",
        "Cuatrimestre del dato: 1C, 2C o Anual.",
        14,
    ),
    (
        "inscriptos",
        "Cantidad de inscriptos ese año/cuatri. Entero no negativo.",
        12,
    ),
]


def _escribir_headers_inscriptos(ws) -> None:
    """Headers estilizados de la hoja Inscriptos + comments explicativos."""
    from openpyxl.comments import Comment

    for col_idx, (nombre, ayuda, ancho) in enumerate(INSCRIPTOS_COLUMNS, start=1):
        cell = ws.cell(row=1, column=col_idx, value=nombre)
        cell.font = HEADER_FONT
        cell.fill = HEADER_FILL
        cell.alignment = HEADER_ALIGN
        cell.comment = Comment(ayuda, "gestor-aulas")
        letra = get_column_letter(col_idx)
        ws.column_dimensions[letra].width = ancho
    ws.row_dimensions[1].height = 32
    ws.freeze_panes = "A2"


def _agregar_data_validations_inscriptos(
    ws, wb: Workbook, materias_codigos: list[str],
) -> None:
    """DataValidation en las 4 columnas del template de inscriptos."""
    max_row = 5001  # inscriptos es serie histórica, rango generoso

    # Materia — lista cerrada de códigos del catálogo.
    ref_materias = _escribir_hoja_lista(wb, "_materias", materias_codigos)
    if ref_materias:
        dv_mat = DataValidation(
            type="list", formula1=ref_materias, allow_blank=False,
            errorTitle="Código no válido",
            error=(
                "Elegí un código de la lista. Sólo se aceptan materias "
                "que están en el catálogo activo."
            ),
            showErrorMessage=True,
        )
        dv_mat.add(f"A2:A{max_row}")
        ws.add_data_validation(dv_mat)

    # Cuatrimestre — lista cerrada 1C / 2C / Anual.
    ref_cuatris = _escribir_hoja_lista(wb, "_cuatris", CUATRIS_INSCRIPTOS)
    dv_cuatri = DataValidation(
        type="list", formula1=ref_cuatris, allow_blank=False,
        errorTitle="Cuatrimestre no válido",
        error="Elegí 1C, 2C o Anual de la lista.",
        showErrorMessage=True,
    )
    dv_cuatri.add(f"C2:C{max_row}")
    ws.add_data_validation(dv_cuatri)

    # Año — entero en rango razonable.
    dv_anio = DataValidation(
        type="whole", operator="between",
        formula1=2000, formula2=2100,
        allow_blank=False,
        errorTitle="Año fuera de rango",
        error="El año debe ser un entero entre 2000 y 2100.",
        showErrorMessage=True,
    )
    dv_anio.add(f"B2:B{max_row}")
    ws.add_data_validation(dv_anio)

    # Inscriptos — entero no negativo.
    dv_insc = DataValidation(
        type="whole", operator="greaterThanOrEqual",
        formula1=0,
        allow_blank=False,
        errorTitle="Valor inválido",
        error="La cantidad de inscriptos debe ser un entero >= 0.",
        showErrorMessage=True,
    )
    dv_insc.add(f"D2:D{max_row}")
    ws.add_data_validation(dv_insc)


def _escribir_hoja_instrucciones_inscriptos(
    wb: Workbook, n_materias: int,
) -> None:
    """Hoja de guía en castellano para la plantilla de inscriptos."""
    ws = wb.create_sheet(title="Instrucciones", index=0)
    ws.column_dimensions["A"].width = 100

    def _t(row: int, txt: str, font: Font | None = None) -> None:
        cell = ws.cell(row=row, column=1, value=txt)
        if font is not None:
            cell.font = font
        cell.alignment = Alignment(wrap_text=True, vertical="top")

    row = 1
    _t(row, "Plantilla de inscriptos — Serie histórica",
       INSTRUCCIONES_TITLE_FONT)
    row += 2

    _t(row, "Cómo usar esta plantilla", INSTRUCCIONES_HEADER_FONT)
    row += 1
    _t(row,
       "1) Abrir la hoja 'Inscriptos'. Borrar la fila de ejemplo "
       "(fila 2, en amarillo) o pisarla con datos reales.")
    row += 1
    _t(row,
       "2) Cargar una fila por combinación (materia, año, cuatri). "
       "Cada fila representa cuántos alumnos se inscribieron en una "
       "materia en un cuatrimestre específico.")
    row += 1
    _t(row,
       "3) Guardar el archivo y subirlo desde el módulo Inscriptos "
       "de la aplicación.")
    row += 2

    _t(row, "Columnas de la hoja Inscriptos", INSTRUCCIONES_HEADER_FONT)
    row += 1
    for nombre, ayuda, _ancho in INSCRIPTOS_COLUMNS:
        _t(row, f"• {nombre} — {ayuda}")
        row += 1
    row += 1

    _t(row, "Listas predeterminadas", INSTRUCCIONES_HEADER_FONT)
    row += 1
    _t(row,
       f"• Códigos de materia: {n_materias} códigos válidos del "
       "catálogo. Escribir en la columna 'codigo_materia' abre el "
       "dropdown; sólo se aceptan valores de la lista.")
    row += 1
    _t(row,
       "• Cuatrimestre: 1C, 2C o Anual. 'Anual' se usa cuando la "
       "materia se cursa completa a lo largo del año (no dividida "
       "por cuatri).")
    row += 1
    _t(row,
       "• Año: entre 2000 y 2100. Datos históricos típicos: 2020 en "
       "adelante.")
    row += 1
    _t(row,
       "• Inscriptos: entero no negativo. Cero significa 'materia "
       "sin inscriptos ese cuatri'.")
    row += 2

    _t(row, "Consejos", INSTRUCCIONES_HEADER_FONT)
    row += 1
    _t(row,
       "• Al importar, la app muestra un preview con qué datos son "
       "nuevos y cuáles pisan valores existentes. Podés cancelar y "
       "corregir el Excel si algo no cierra.")
    row += 1
    _t(row,
       "• Los datos históricos alimentan el forecast (media móvil, "
       "drift, SES). Cargar más años mejora la calidad de la "
       "proyección.")
    row += 1
    _t(row,
       "• Si un mismo (materia, año, cuatri) aparece varias veces "
       "en el archivo, la última fila gana.")


def generar_plantilla_inscriptos_excel(session: Session) -> bytes:
    """Genera una plantilla Excel para carga masiva de inscriptos.

    A diferencia de la plantilla de cronograma, esta plantilla usa el
    **catálogo completo** de materias activas (no un ciclo). El
    dropdown de códigos incluye todas las materias del catálogo con
    ``MateriaDB.active=True``.

    Returns:
        Bytes del Excel listos para ``st.download_button``.

    Raises:
        ValueError si no hay materias activas en el catálogo.
    """
    materias = list(session.exec(
        select(MateriaDB).where(MateriaDB.active == True)  # noqa: E712
    ).all())
    if not materias:
        raise ValueError(
            "No hay materias activas en el catálogo. Cargar el "
            "catálogo antes de generar la plantilla de inscriptos."
        )

    codigos_ordenados = sorted(m.codigo for m in materias)

    wb = Workbook()
    ws_main = wb.active
    assert ws_main is not None
    ws_main.title = "Inscriptos"

    _escribir_headers_inscriptos(ws_main)
    # Bugfix (2026-09-22, task #341): mismo motivo que la plantilla de
    # cronograma — no se escribe fila de ejemplo porque el parser no la
    # distingue de dato real. El ejemplo queda en la hoja Instrucciones.
    _agregar_data_validations_inscriptos(ws_main, wb, codigos_ordenados)

    _escribir_hoja_instrucciones_inscriptos(wb, len(codigos_ordenados))

    wb.active = 0

    buffer = io.BytesIO()
    wb.save(buffer)
    return buffer.getvalue()


def obtener_referencia_materias_activas(
    session: Session,
) -> list[tuple[str, str]]:
    """Pares (codigo, nombre) de materias activas del catálogo,
    ordenados por código. Útil para mostrar cuántas materias entran
    al dropdown de la plantilla de inscriptos.
    """
    materias = list(session.exec(
        select(MateriaDB).where(MateriaDB.active == True)  # noqa: E712
    ).all())
    return sorted(
        ((m.codigo, m.nombre) for m in materias),
        key=lambda t: t[0],
    )
