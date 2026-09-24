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
        "nombre_materia",
        "NO se completa: aparece solo al elegir el código en la "
        "columna de al lado, para que verifiques que es la materia "
        "correcta. La columna está protegida.",
        34,
    ),
    (
        "codigo_materia",
        "Código de la materia (lista de la hoja 'Materias'). Es el "
        "único dato de materia que se carga: al elegirlo, el nombre "
        "aparece solo en la primera columna.",
        16,
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

    # Materia: el CÓDIGO (columna B, desplegable contra la hoja
    # VISIBLE `Materias`) es el único punto de entrada (2026-09-24 —
    # simplificación pedida por el usuario: quien carga debe conocer
    # el código correcto). El nombre (columna A, primera a pedido
    # del usuario) se autocompleta por fórmula y queda bloqueado por
    # la protección de la hoja: es una verificación visual, no un
    # dato a cargar. Así no puede haber un código y un nombre que no
    # se correspondan. En la hoja `Materias` el nombre también va
    # primero: los nombres viven en Materias!$A y los códigos en
    # Materias!$B.
    if n_mat:
        dv_mat_cod = DataValidation(
            type="list",
            formula1=f"=Materias!$B$2:$B${n_mat + 1}",
            allow_blank=True,
            errorTitle="Código no válido",
            error=(
                "Elegí un código de la lista (hoja 'Materias'). Sólo "
                "se aceptan materias con dictado activo en este ciclo."
            ),
            showErrorMessage=True,
        )
        dv_mat_cod.add(f"B2:B{max_row}")
        ws.add_data_validation(dv_mat_cod)

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
    dv_cod_com.add(f"C2:C{max_row}")
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
    dv_dia.add(f"E2:E{max_row}")
    ws.add_data_validation(dv_dia)

    # Hora inicio / hora fin — lista desplegable de horas discretas
    # según granularidad + rango operativo.
    ref_horas = _escribir_hoja_lista(wb, "_horas", slots_horarios)
    if ref_horas:
        for col_letra, err_msg in (
            ("F", "Elegí la hora de inicio de la lista. Sólo se aceptan valores múltiplos de la granularidad configurada. Debe ser anterior a hora_fin."),  # noqa: E501
            ("G", "Elegí la hora de fin de la lista. Sólo se aceptan valores múltiplos de la granularidad configurada. Debe ser posterior a hora_inicio."),  # noqa: E501
        ):
            dv_hora = DataValidation(
                type="list", formula1=ref_horas, allow_blank=False,
                errorTitle="Hora no válida",
                error=err_msg,
                showErrorMessage=True,
            )
            dv_hora.add(f"{col_letra}2:{col_letra}{max_row}")
            ws.add_data_validation(dv_hora)

    # Tipo de clase y virtual: desplegables DEPENDIENTES entre sí
    # (2026-09-24) para que Excel no deje combinar laboratorio +
    # virtual. La fuente de cada lista es una fórmula IF por fila
    # (truco estándar de listas dependientes: la validación de tipo
    # `list` acepta una fórmula que devuelve un rango). No hay
    # circularidad: cada fórmula LEE la otra celda, no la escribe.
    # Si el valor se tipea a mano, la validación lo rechaza igual
    # contra la lista restringida. Pegar valores saltea cualquier
    # DataValidation — para eso queda la guardia del importador.
    _escribir_hoja_lista(wb, "_tipos", TIPOS_CLASE)
    _escribir_hoja_lista(wb, "_virtual", VIRTUAL_OPCIONES)

    # Con virtual = VERDADERO, el tipo sólo puede ser teorica
    # (_tipos!A1); sino, la lista completa (_tipos!A1:A2).
    dv_tipo = DataValidation(
        type="list",
        formula1=(
            "=IF($I2=TRUE,"
            "_tipos!$A$1:$A$1,"
            f"_tipos!$A$1:$A${len(TIPOS_CLASE)})"
        ),
        allow_blank=True,
        errorTitle="Tipo de clase no válido",
        error=(
            "Dejalo vacío (lo determina la asignación automática) o "
            "elegí 'teorica' / 'laboratorio'. Ojo: una clase marcada "
            "virtual no puede ser laboratorio — el laboratorio "
            "requiere aula física."
        ),
        showErrorMessage=True,
    )
    dv_tipo.add(f"H2:H{max_row}")
    ws.add_data_validation(dv_tipo)

    # Con tipo = laboratorio, virtual sólo puede ser FALSO
    # (_virtual!A2); sino, VERDADERO/FALSO (_virtual!A1:A2).
    dv_virt = DataValidation(
        type="list",
        formula1=(
            '=IF($H2="laboratorio",'
            "_virtual!$A$2:$A$2,"
            "_virtual!$A$1:$A$2)"
        ),
        allow_blank=True,
        errorTitle="Valor no válido",
        error=(
            "Elegí VERDADERO o FALSO (vacío equivale a FALSO). "
            "Recordá: un laboratorio no puede ser virtual."
        ),
        showErrorMessage=True,
    )
    dv_virt.add(f"I2:I{max_row}")
    ws.add_data_validation(dv_virt)

    # Fórmula precargada en la columna A (notación canónica inglesa —
    # Excel la localiza solo): el nombre de la materia a partir del
    # código elegido en B. Junto con la protección de la hoja (ver
    # el generador), A queda como verificación visual de sólo
    # lectura: el usuario no puede pisarla ni tipear un nombre que
    # no se corresponda con el código.
    #
    # Además se DESBLOQUEAN las celdas de las columnas de carga
    # (todas menos A) — openpyxl deja `locked=True` por default y la
    # protección de hoja bloquearía todo.
    _cols_entrada = list(range(2, len(HORARIO_COLUMNS) + 1))
    _rango_nom = f"Materias!$A$2:$A${n_mat + 1}" if n_mat else ""
    _rango_cod = f"Materias!$B$2:$B${n_mat + 1}" if n_mat else ""
    from openpyxl.styles import Protection as _Protection
    _desbloqueada = _Protection(locked=False)
    for _r in range(2, max_row + 1):
        if n_mat:
            ws.cell(row=_r, column=1).value = (
                f'=IFERROR(INDEX({_rango_nom},'
                f'MATCH($B{_r},{_rango_cod},0)),"")'
            )
        for _c in _cols_entrada:
            ws.cell(row=_r, column=_c).protection = _desbloqueada


# Columnas de la hoja `Materias` (2026-09-24): nombre y código
# primero (los referencian la lista desplegable y la fórmula de la
# hoja Horarios: nombres en $A, códigos en $B) y después el contexto
# completo pedido por el usuario — atributos del catálogo, ubicación
# en los planes de carrera y configuración del dictado del ciclo.
MATERIAS_CONTEXT_COLUMNS: list[tuple[str, int]] = [
    ("Nombre", 42),
    ("Código", 11),
    ("Código Guaraní", 14),
    ("Período", 13),
    ("Hs/sem", 9),
    ("Hs teoría", 10),
    ("Hs laboratorio", 13),
    ("Cupo", 8),
    ("Optativa", 10),
    ("Virtual (catálogo)", 16),
    ("Regla de recursado", 22),
    ("Planes de carrera (año y cuatrimestre)", 44),
    ("Dictado del ciclo", 20),
    ("Modalidad del dictado", 30),
    ("Dictado de recursado", 18),
]


def _si_no(valor: bool) -> str:
    return "sí" if valor else "no"


def obtener_contexto_materias_del_ciclo(
    session: Session, ciclo_id: str,
) -> list[dict]:
    """Contexto completo de cada materia con dictado activo en el
    ciclo, para la hoja `Materias` de la plantilla (2026-09-24).

    Por materia (orden por código, el mismo que usan los rangos de
    la hoja Horarios): atributos del catálogo, en qué planes de
    carrera del ciclo aparece y en qué momento (año/cuatrimestre,
    optativa), y cómo quedó configurado el dictado para el ciclo
    (código de dictado, modalidad resuelta con la jerarquía
    dictado > catálogo, y si es un dictado de recursado — es decir,
    si todas sus apariciones en los planes del ciclo son del
    cuatrimestre opuesto).
    """
    from src.database.models import (
        CicloPlanVersionDB,
        DictadoCicloDB,
        DictadoDB,
        PlanEstudioDB,
    )
    from src.services.dictado_service import _is_opposite_cuatrimestre

    ciclo = session.get(CicloDB, ciclo_id)
    if ciclo is None:
        return []
    pares = obtener_referencia_materias_del_ciclo(session, ciclo_id)
    if not pares:
        return []
    codigos = [c for c, _ in pares]
    materias = {
        m.codigo: m for m in session.exec(
            select(MateriaDB).where(
                MateriaDB.codigo.in_(codigos)  # type: ignore[attr-defined]
            )
        ).all()
    }
    plan_version_ids = list(session.exec(
        select(CicloPlanVersionDB.plan_version_id).where(
            CicloPlanVersionDB.ciclo_id == ciclo_id
        )
    ).all())
    planes_por_materia: dict[str, list] = {}
    if plan_version_ids:
        for pe in session.exec(
            select(PlanEstudioDB)
            .where(PlanEstudioDB.materia_codigo.in_(codigos))  # type: ignore[attr-defined]
            .where(PlanEstudioDB.plan_version_id.in_(plan_version_ids))  # type: ignore[attr-defined]
        ).all():
            planes_por_materia.setdefault(pe.materia_codigo, []).append(pe)
    dictados = {
        d.materia_codigo: d for d in session.exec(
            select(DictadoDB)
            .join(DictadoCicloDB, DictadoDB.id == DictadoCicloDB.dictado_id)
            .where(DictadoCicloDB.ciclo_id == ciclo_id)
        ).all()
    }

    filas: list[dict] = []
    for cod, nom in pares:
        mat = materias.get(cod)
        if mat is None:
            continue

        _planes = sorted(
            planes_por_materia.get(cod, []),
            key=lambda e: (e.carrera_codigo, e.anio_plan or 0),
        )
        _planes_str = "; ".join(
            f"{e.carrera_codigo} — "
            f"{f'{e.anio_plan}° año' if e.anio_plan else 'año s/d'}, "
            f"{e.cuatrimestre_plan or 's/cuatrimestre'}"
            + (" (optativa)" if e.optativa else "")
            for e in _planes
        )

        d = dictados.get(cod)
        if d is None:
            _dictado_str = "-"
            _modalidad = "-"
        else:
            _dictado_str = d.dictado_codigo or d.id
            if d.virtual is True:
                _modalidad = "virtual (definida en el dictado)"
            elif d.virtual is False and mat.virtual:
                _modalidad = "presencial (definida en el dictado)"
            elif mat.virtual:
                _modalidad = "virtual (heredada del catálogo)"
            else:
                _modalidad = "presencial"

        _recursado = "no"
        if (
            mat.periodo == "cuatrimestral"
            and plan_version_ids
            and _is_opposite_cuatrimestre(
                session, mat, ciclo, plan_version_ids,
            )
        ):
            _recursado = "sí"

        if mat.dicta_recursado is None:
            _regla_rec = "según carrera"
        else:
            _regla_rec = _si_no(mat.dicta_recursado)

        filas.append({
            "Nombre": nom,
            "Código": cod,
            "Código Guaraní": mat.codigo_guarani or "",
            "Período": mat.periodo,
            "Hs/sem": mat.horas_semanales,
            "Hs teoría": mat.horas_teoria,
            "Hs laboratorio": mat.horas_laboratorio,
            "Cupo": mat.cupo,
            "Optativa": _si_no(mat.optativa),
            "Virtual (catálogo)": _si_no(mat.virtual),
            "Regla de recursado": _regla_rec,
            "Planes de carrera (año y cuatrimestre)": _planes_str,
            "Dictado del ciclo": _dictado_str,
            "Modalidad del dictado": _modalidad,
            "Dictado de recursado": _recursado,
        })
    return filas


def _escribir_hoja_materias(wb: Workbook, contexto: list[dict]) -> None:
    """Hoja VISIBLE `Materias`: referencia nombre + código y el
    contexto completo de cada materia (2026-09-24).

    Alimenta la lista desplegable de códigos y la fórmula del nombre
    de la hoja `Horarios` (por eso el orden de filas — por código —
    tiene que coincidir con el de los rangos referenciados). Queda
    **protegida sin contraseña**: es material de consulta, la cátedra
    no debe poder editar códigos ni nombres. No es una hoja de datos
    a importar: el selector de hoja de la app la excluye.
    """
    ws = wb.create_sheet(title="Materias")
    for col_idx, (titulo, ancho) in enumerate(
        MATERIAS_CONTEXT_COLUMNS, start=1,
    ):
        cell = ws.cell(row=1, column=col_idx, value=titulo)
        cell.font = HEADER_FONT
        cell.fill = HEADER_FILL
        cell.alignment = HEADER_ALIGN
        ws.column_dimensions[get_column_letter(col_idx)].width = ancho
    for i, fila in enumerate(contexto, start=2):
        for col_idx, (titulo, _ancho) in enumerate(
            MATERIAS_CONTEXT_COLUMNS, start=1,
        ):
            ws.cell(row=i, column=col_idx, value=fila.get(titulo))
    # Nombre y código siempre visibles al scrollear el contexto.
    ws.freeze_panes = "C2"
    # Sólo lectura: todas las celdas quedan bloqueadas (default de
    # openpyxl); se permite ordenar/filtrar y ajustar anchos.
    ws.protection.sheet = True
    ws.protection.selectLockedCells = False
    ws.protection.selectUnlockedCells = False
    ws.protection.sort = False
    ws.protection.autoFilter = False
    ws.protection.formatColumns = False
    ws.protection.formatRows = False


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
       "2) La materia se ingresa por CÓDIGO (lista desplegable en la "
       "columna 'codigo_materia'). Al elegirlo, el nombre aparece "
       "solo en la primera columna, para que verifiques que es la "
       "materia correcta — esa columna está protegida y no se "
       "completa a mano. La hoja 'Materias' tiene la referencia "
       "completa para buscar el código que necesitás: nombre, "
       "código, atributos de la materia, en qué planes de carrera "
       "aparece (año y cuatrimestre) y cómo está configurado el "
       "dictado para este ciclo (modalidad, recursado).")
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
       "ciclo, elegibles por código en la columna 'codigo_materia'. "
       "Sólo se aceptan códigos de la lista; el nombre se completa "
       "solo.")
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
       "laboratorio requiere un aula física). Los desplegables ya lo "
       "impiden: con tipo 'laboratorio' la columna virtual sólo "
       "ofrece FALSO, y con virtual VERDADERO el tipo sólo ofrece "
       "'teorica'.")
    row += 1
    _t(row,
       "• Las hojas 'Horarios' y 'Materias' están protegidas (sin "
       "contraseña) para cuidar las fórmulas, la columna del nombre "
       "y la referencia de materias. Si necesitás algo fuera de lo "
       "previsto, podés desprotegerlas desde Revisar → Desproteger "
       "hoja.")
    row += 1
    _t(row,
       "• El código de comisión es obligatorio y debe ser un entero "
       "mayor o igual a 1. Dos comisiones distintas de la misma "
       "materia no pueden compartir código ni nombre.")
    row += 1
    _t(row,
       "• Si le ponés nombre a una comisión, la correspondencia "
       "código-nombre tiene que ser uno a uno dentro de la materia: "
       "un mismo código siempre con el mismo nombre, y un mismo "
       "nombre siempre con el mismo código.")
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
       "• La hoja Horarios es una tabla de Excel con capacidad para "
       "1000 filas, con filtros por columna para revisar lo cargado.")
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
    - Hoja VISIBLE "Materias" (protegida, sólo consulta) con el
      contexto completo de cada materia con dictado activo: nombre y
      código primero, atributos del catálogo, en qué planes de
      carrera aparece y en qué momento, y la configuración del
      dictado del ciclo (modalidad resuelta, recursado). La materia
      se ingresa SOLO por código (desplegable, 2026-09-24): el
      nombre — primera columna de Horarios — se autocompleta por
      fórmula como verificación visual y queda de sólo lectura
      (hoja protegida sin contraseña, con las columnas de carga
      desbloqueadas). Quien carga debe conocer el código correcto;
      no puede haber código y nombre que no se correspondan.
    - El área de datos es una TABLA de Excel (``TablaHorarios``):
      filtros por columna y bandeado de filas.
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
    # Hoja VISIBLE `Materias` (2026-09-24): referencia nombre+código
    # más el contexto completo de cada materia (catálogo, planes,
    # dictado del ciclo), protegida contra edición. Alimenta el
    # desplegable de códigos y la fórmula del nombre. Se crea ANTES
    # de las validaciones porque las fórmulas la referencian, y el
    # orden de filas (por código) tiene que coincidir con el de los
    # rangos.
    _contexto_materias = obtener_contexto_materias_del_ciclo(
        session, ciclo_id,
    )
    _escribir_hoja_materias(wb, _contexto_materias)
    # Bugfix (2026-09-22, task #341): no se escribe fila de ejemplo en
    # la hoja Horarios porque el parser no distingue ejemplo de dato
    # real; el ejemplo textual queda en la hoja Instrucciones.
    _agregar_data_validations_horarios(
        ws_main, wb, [f["Código"] for f in _contexto_materias],
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

    # Proteger la hoja SIN contraseña (2026-09-24): la columna del
    # nombre de materia queda de sólo lectura (celdas bloqueadas con
    # la fórmula de autocompletado); las columnas de carga están
    # desbloqueadas celda a celda en
    # `_agregar_data_validations_horarios`. Se permiten expresamente
    # ordenar, filtrar, insertar/eliminar filas y ajustar
    # anchos/altos — en openpyxl estos flags en True significan
    # acción BLOQUEADA, por eso van en False. Sin contraseña, quien
    # necesite algo fuera de lo previsto desprotege la hoja en un
    # clic (Revisar → Desproteger hoja).
    ws_main.protection.sheet = True
    ws_main.protection.selectLockedCells = False
    ws_main.protection.selectUnlockedCells = False
    ws_main.protection.sort = False
    ws_main.protection.autoFilter = False
    ws_main.protection.insertRows = False
    ws_main.protection.deleteRows = False
    ws_main.protection.formatColumns = False
    ws_main.protection.formatRows = False

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
