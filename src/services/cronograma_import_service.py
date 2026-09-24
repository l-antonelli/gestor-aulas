"""Servicio de importación de horarios a un cronograma existente.

Fase C2 del rediseño 2026-09-15. Reemplaza al flujo antiguo
``create_schedule_standalone`` (que sólo servía para crear cronogramas
nuevos y confiaba parcialmente en el input) por un pipeline explícito
de dos pasos:

1. **Preview** (``preview_import``): parsea el archivo, resuelve
   códigos de materia contra el catálogo, detecta materias que ya
   tienen datos en el cronograma destino, arma comisiones sintéticas
   por (materia, nombre_comision), y devuelve un ``ImportPreview``
   que la UI puede mostrar antes de commitear nada.

2. **Commit** (``commit_import``): recibe el preview + las decisiones
   por materia (``agregar`` / ``reemplazar`` / ``ignorar``) que
   resolvió el usuario en la UI, y aplica los cambios sobre
   ``ScheduleEntryDB`` + ``ComisionDB`` en una sola transacción.

El importer NO ejecuta las validaciones estructurales completas del
cronograma (cobertura, conflictos horarios, camino de cursada, etc.)
— esas quedan a cargo de ``validar_cronograma`` una vez que el
usuario aprieta "Prevalidar". El preview sólo hace las validaciones
"tipográficas" que evitan un import roto:

- Códigos de materia existentes en el catálogo (con resolución
  ``codigo_guarani``).
- Nombres de comisión únicos para las que se agregan (dentro de la
  misma materia y del mismo cronograma).
- Detección de materias con horarios previos → decisión requerida.

Comisiones "nombradas" arbitrariamente (no numéricas): el usuario
puede llamar a una comisión ``1``, ``A``, ``Mañana`` o
``Comisión 3 turno tarde``. La unicidad se resuelve sobre el string
canonicalizado (trim + normalización case-insensitive). El campo
``ComisionDB.numero`` sigue siendo un entero autoderivado (usado por
``comision_key`` y ordenamiento), pero el usuario no lo ve.
"""

from __future__ import annotations

import uuid
from collections import Counter
from dataclasses import dataclass, field
from typing import Literal, Optional

from sqlmodel import Session, select

from src.database.models import (
    ComisionDB,
    ScheduleDB,
    ScheduleEntryDB,
)
from src.services.comision_service import (
    create_comision_for_schedule,
    list_comisiones_for_schedule_materia,
)
from src.services.horario_file_parser import parse_horarios_file
from src.services.horario_loading_service import (
    HorarioInput,
    _resolve_materia_code,
)


# =============================================================================
# Dataclasses
# =============================================================================

MergePolicy = Literal["agregar", "reemplazar", "ignorar"]


@dataclass
class ComisionEnPreview:
    """Comisión sintética derivada del archivo importado.

    Agrupa los horarios que comparten (materia_codigo, comisión) en el
    archivo. Se usa para (a) decidir si el nombre choca con una
    comisión ya existente y (b) volcar los entries al DB al commitear.

    ``codigo`` (2026-09-23): código numérico declarado en la plantilla
    nueva (columna ``codigo_comision``) — se persiste como
    ``ComisionDB.numero``. ``None`` = esquema histórico (texto libre),
    donde el número se autoderiva al crear.
    """
    materia_codigo: str
    nombre_comision: str
    codigo: Optional[int] = None
    horarios: list[HorarioInput] = field(default_factory=list)

    @property
    def nombre_canonico(self) -> str:
        """Clave normalizada para deduplicación (trim + lowercase).

        La UI muestra el nombre como lo escribió el usuario, pero el
        chequeo de unicidad usa esta forma canónica para evitar
        problemas obvios (``"1 "`` vs ``"1"``, ``"A"`` vs ``"a"``).
        """
        return self.nombre_comision.strip().lower()


@dataclass
class MateriaEnPreview:
    """Estado de una materia dentro del preview.

    Contiene tanto las comisiones que trae el archivo como las que ya
    existen en el cronograma (si las hay), para que la UI pueda pedir
    la decisión de merge apropiada.
    """
    materia_codigo: str
    materia_nombre: str
    resolution_type: str  # "direct" | "guarani" | "unresolved"
    original_code: Optional[str] = None  # sólo si resolution_type == "guarani"
    comisiones_nuevas: list[ComisionEnPreview] = field(default_factory=list)
    comisiones_existentes: list[str] = field(default_factory=list)  # nombres
    n_entries_existentes: int = 0

    @property
    def tiene_datos_previos(self) -> bool:
        return self.n_entries_existentes > 0

    @property
    def n_horarios_nuevos(self) -> int:
        return sum(len(c.horarios) for c in self.comisiones_nuevas)


@dataclass
class ImportPreview:
    """Resultado del preview de importación sobre un cronograma.

    - ``schedule_id``: cronograma destino (siempre existe: el preview
      requiere un cronograma ya creado).
    - ``materias``: lista de ``MateriaEnPreview`` con las materias que
      trae el archivo. Cada una es una unidad de decisión de merge.
    - ``materias_no_resueltas``: códigos que no matchean el catálogo,
      con la fila donde aparecieron.
    - ``parse_errors``: errores estructurales del archivo (columnas
      faltantes, filas mal formadas). Bloquean el commit.
    - ``warnings``: mensajes no bloqueantes (por ejemplo, resolución
      via ``codigo_guarani``).
    """
    schedule_id: str
    materias: list[MateriaEnPreview] = field(default_factory=list)
    materias_no_resueltas: list[tuple[str, int]] = field(default_factory=list)
    parse_errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)

    @property
    def tiene_errores_bloqueantes(self) -> bool:
        return bool(self.parse_errors)

    @property
    def total_horarios(self) -> int:
        return sum(m.n_horarios_nuevos for m in self.materias)

    @property
    def materias_con_conflicto(self) -> list[MateriaEnPreview]:
        """Materias que ya tienen datos previos — requieren decisión."""
        return [m for m in self.materias if m.tiene_datos_previos]


@dataclass
class ImportResult:
    """Resultado del commit de una importación.

    - ``entries_creados``: cantidad de ``ScheduleEntryDB`` insertados.
    - ``comisiones_creadas``: cantidad de ``ComisionDB`` nuevas.
    - ``entries_borrados``: cantidad borrada por decisión ``reemplazar``.
    - ``materias_ignoradas``: códigos que el usuario decidió omitir.
    - ``errors``: errores encontrados al commitear (por ejemplo,
      colisión de nombre de comisión no detectada en el preview).
    """
    entries_creados: int = 0
    comisiones_creadas: int = 0
    entries_borrados: int = 0
    comisiones_borradas: int = 0
    materias_ignoradas: list[str] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)


# =============================================================================
# Preview
# =============================================================================


def preview_import(
    session: Session,
    schedule_id: str,
    file,
    sheet_name: str | None = None,
) -> ImportPreview:
    """Arma un preview de la importación sin commitear nada.

    Args:
        session: sesión activa.
        schedule_id: cronograma destino.
        file: file-like con ``.name`` (Streamlit UploadedFile o similar).
        sheet_name: nombre de la hoja del Excel a importar cuando el
            archivo tiene múltiples hojas visibles. ``None`` mantiene
            el fallback tradicional (``Horarios`` si existe, sino
            primera hoja no-sistema). No aplica a CSV.

    Returns:
        ``ImportPreview`` con las materias detectadas y los conflictos
        de merge que la UI tiene que resolver antes de commitear.
    """
    preview = ImportPreview(schedule_id=schedule_id)

    # Validar que el cronograma existe.
    if session.get(ScheduleDB, schedule_id) is None:
        preview.parse_errors.append(
            f"Cronograma '{schedule_id}' no existe."
        )
        return preview

    # Parsear el archivo.
    entries, parse_errors = parse_horarios_file(file, sheet_name=sheet_name)
    preview.parse_errors.extend(parse_errors)
    if not entries:
        if not parse_errors:
            preview.parse_errors.append(
                "El archivo no tiene horarios válidos."
            )
        return preview

    # Agrupar por materia (código original antes de resolver) y por comisión.
    # Se preserva la fila para reportar errores útiles si algo no resuelve.
    por_materia_original: dict[str, dict[str, list[tuple[int, HorarioInput]]]] = {}
    for idx, entry in enumerate(entries, start=1):
        por_materia = por_materia_original.setdefault(entry.codigo_materia, {})
        # Clave de agrupación (2026-09-23): si la fila declara
        # `codigo_comision`, agrupa por código (identificador estable
        # que el usuario controla). Sin código, deduplicación canónica
        # del nombre (esquema histórico de texto libre).
        if entry.comision_codigo is not None:
            clave = f"#{entry.comision_codigo}"
        else:
            clave = entry.comision_nombre.strip().lower()
        por_materia.setdefault(clave, []).append((idx, entry))

    # Resolver códigos y armar el preview.
    for codigo_original, por_comision in por_materia_original.items():
        resolution = _resolve_materia_code(session, codigo_original)

        if resolution.resolution_type == "unresolved":
            # Reportar la primera fila donde apareció el código.
            primera_fila = min(
                idx for horarios in por_comision.values() for idx, _ in horarios
            )
            preview.materias_no_resueltas.append(
                (codigo_original, primera_fila)
            )
            continue

        if resolution.resolution_type == "guarani":
            preview.warnings.append(
                f"Código '{resolution.original_code}' resuelto vía "
                f"código Guaraní → '{resolution.resolved_code}'."
            )

        codigo_resuelto = resolution.resolved_code
        assert codigo_resuelto is not None  # unresolved ya salió arriba
        materia = resolution.materia
        materia_nombre = materia.nombre if materia else codigo_resuelto

        # Comisiones nuevas del archivo.
        comisiones_nuevas: list[ComisionEnPreview] = []
        for _, horarios in por_comision.items():
            # Tomar el primer nombre como el "canónico" para display.
            nombre_display = horarios[0][1].comision_nombre.strip()
            com = ComisionEnPreview(
                materia_codigo=codigo_resuelto,
                nombre_comision=nombre_display,
                codigo=horarios[0][1].comision_codigo,
                horarios=[hor for _, hor in horarios],
            )
            comisiones_nuevas.append(com)

        # Existentes en el cronograma.
        coms_db = list_comisiones_for_schedule_materia(
            session, schedule_id, codigo_resuelto,
        )
        nombres_existentes = [c.nombre for c in coms_db]
        n_entries_prev = session.exec(
            select(ScheduleEntryDB.id)
            .where(ScheduleEntryDB.schedule_id == schedule_id)
            .where(ScheduleEntryDB.codigo_materia == codigo_resuelto)
        ).all()

        mp = MateriaEnPreview(
            materia_codigo=codigo_resuelto,
            materia_nombre=materia_nombre,
            resolution_type=resolution.resolution_type,
            original_code=(
                resolution.original_code
                if resolution.resolution_type == "guarani" else None
            ),
            comisiones_nuevas=comisiones_nuevas,
            comisiones_existentes=nombres_existentes,
            n_entries_existentes=len(n_entries_prev),
        )
        preview.materias.append(mp)

    # Orden estable para la UI: primero las que requieren decisión.
    preview.materias.sort(
        key=lambda m: (not m.tiene_datos_previos, m.materia_codigo),
    )

    return preview


# =============================================================================
# Commit
# =============================================================================


def commit_import(
    session: Session,
    preview: ImportPreview,
    decisiones: dict[str, MergePolicy],
) -> ImportResult:
    """Aplica el preview con las decisiones de merge por materia.

    Args:
        session: sesión activa.
        preview: preview generado por ``preview_import``. Debe pertenecer
            al mismo cronograma que se está editando.
        decisiones: mapa ``{materia_codigo -> MergePolicy}``. Para
            materias sin datos previos la decisión se ignora (siempre
            se agrega). Para materias con datos previos, la decisión
            debe estar presente (default implícito: ``agregar``).

    Returns:
        ``ImportResult`` con estadísticas del commit.

    Raises:
        ValueError si el preview trae errores bloqueantes.
    """
    if preview.tiene_errores_bloqueantes:
        raise ValueError(
            "El preview tiene errores bloqueantes; corregir el archivo "
            "antes de commitear."
        )

    result = ImportResult()
    schedule_id = preview.schedule_id

    # Auditoría H9 (2026-09-23): si el archivo trae el mismo dictado
    # bajo dos códigos distintos que resuelven a la misma materia
    # (código de plan + código Guaraní), el preview genera dos
    # `MateriaEnPreview` con el mismo `materia_codigo`. Con
    # "reemplazar", la segunda iteración borraba lo que acababa de
    # crear la primera. Se trackean las materias ya reemplazadas para
    # borrar una sola vez; el segundo grupo se comporta como "agregar"
    # y el chequeo de colisión de nombres (abajo) reporta duplicados.
    _ya_reemplazadas: set[str] = set()

    for mp in preview.materias:
        decision: MergePolicy = decisiones.get(mp.materia_codigo, "agregar")

        # "ignorar" se respeta SIEMPRE, tenga o no datos previos
        # (2026-09-23): el usuario puede excluir del import una materia
        # nueva cuyo archivo vino mal, sin comprometerse a subirla.
        # Antes el forzado a "agregar" de abajo pisaba el "ignorar".
        if decision == "ignorar":
            result.materias_ignoradas.append(mp.materia_codigo)
            continue

        if not mp.tiene_datos_previos:
            # Nada previo — "reemplazar" no tiene sentido; se agrega.
            decision = "agregar"

        attrs_previos: dict[str, dict] = {}
        if decision == "reemplazar":
            if mp.materia_codigo not in _ya_reemplazadas:
                attrs_previos = _borrar_entries_y_comisiones_de_materia(
                    session, schedule_id, mp.materia_codigo, result,
                )
                _ya_reemplazadas.add(mp.materia_codigo)
            # Después de borrar, el escenario es equivalente a "sin datos
            # previos": todas las comisiones nuevas se pueden crear sin
            # colisión de nombre.

        _agregar_comisiones_nuevas(
            session, schedule_id, mp, result,
            attrs_previos=attrs_previos,
        )

    session.commit()
    return result


def _borrar_entries_y_comisiones_de_materia(
    session: Session, schedule_id: str, materia_codigo: str,
    result: ImportResult,
) -> dict[str, dict]:
    """Borra todas las entries y comisiones de una materia en un cronograma.

    Devuelve una instantánea ``{nombre_canónico: atributos}`` de las
    comisiones borradas (``cupo``, ``descripcion``, ``coef_asignacion``,
    ``carrera_asignada``, ``numero``) para que el caller pueda
    restituirlos en las comisiones homónimas que cree después.

    Fix auditoría H1 (2026-09-23): antes el modo "reemplazar" borraba
    la ``ComisionDB`` y la recreaba desde cero con los defaults del
    catálogo, destruyendo la configuración manual del usuario (en
    particular ``carrera_asignada``, el override de sede del LP,
    RF-LP-15) — y el toast lo reportaba como "sin cambio" porque el
    fingerprint de entries no mira atributos de comisión.
    """
    entries = list(session.exec(
        select(ScheduleEntryDB)
        .where(ScheduleEntryDB.schedule_id == schedule_id)
        .where(ScheduleEntryDB.codigo_materia == materia_codigo)
    ).all())
    for e in entries:
        session.delete(e)
    result.entries_borrados += len(entries)

    coms = list_comisiones_for_schedule_materia(
        session, schedule_id, materia_codigo,
    )
    attrs_previos: dict[str, dict] = {}
    for c in coms:
        attrs_previos[(c.nombre or "").strip().lower()] = {
            "cupo": c.cupo,
            "descripcion": c.descripcion,
            "coef_asignacion": c.coef_asignacion,
            "carrera_asignada": c.carrera_asignada,
            "numero": c.numero,
        }
        session.delete(c)
    result.comisiones_borradas += len(coms)
    session.flush()
    return attrs_previos


def _agregar_comisiones_nuevas(
    session: Session,
    schedule_id: str,
    mp: "MateriaEnPreview",
    result: ImportResult,
    attrs_previos: dict[str, dict] | None = None,
) -> None:
    """Crea las comisiones + entries nuevas de una materia.

    - Si la materia ya tiene una comisión con el mismo nombre canónico,
      la comisión del archivo se rechaza (unicidad) y el error se
      acumula en ``result.errors``. Con "reemplazar" recién aplicado no
      hay colisiones posibles porque se acaba de borrar todo.
    - ``attrs_previos`` (fix H1, 2026-09-23): instantánea de atributos
      de las comisiones que el modo "reemplazar" acaba de borrar. Si el
      nombre canónico coincide, se restituyen ``cupo``, ``descripcion``,
      ``coef_asignacion``, ``carrera_asignada`` y ``numero`` — el
      archivo de horarios no trae esos campos y no puede reponerlos.
    """
    attrs_previos = attrs_previos or {}
    # Nombres canónicos ya usados (comisiones que sobrevivieron).
    coms_actuales = list_comisiones_for_schedule_materia(
        session, schedule_id, mp.materia_codigo,
    )
    nombres_actuales_canon: set[str] = {
        (c.nombre or "").strip().lower() for c in coms_actuales
    }

    # Códigos (numeros) ya usados por las comisiones que sobreviven —
    # para detectar colisiones de código cuando la plantilla nueva
    # declara `codigo_comision` explícito (2026-09-23).
    numeros_actuales: dict[int, str] = {
        c.numero: (c.nombre or "") for c in coms_actuales
    }

    for com_new in mp.comisiones_nuevas:
        canon = com_new.nombre_canonico
        if canon in nombres_actuales_canon:
            result.errors.append(
                f"{mp.materia_codigo}: la comisión "
                f"'{com_new.nombre_comision}' ya existe en el "
                "cronograma. Elegí otro nombre o cambiá la decisión "
                "a 'reemplazar' para esta materia."
            )
            continue
        if (
            com_new.codigo is not None
            and com_new.codigo in numeros_actuales
        ):
            result.errors.append(
                f"{mp.materia_codigo}: el código de comisión "
                f"C{com_new.codigo} ya está usado por la comisión "
                f"'{numeros_actuales[com_new.codigo]}'. Elegí otro "
                "código o cambiá la decisión a 'reemplazar'."
            )
            continue

        _prev = attrs_previos.get(canon)
        # Número: el código declarado en el archivo manda; sino el
        # número previo restituido por "reemplazar"; sino autoderivar.
        _numero = com_new.codigo
        if _numero is None and _prev:
            _numero = _prev["numero"]
        com_db = create_comision_for_schedule(
            session, schedule_id, mp.materia_codigo,
            nombre=com_new.nombre_comision,
            numero=_numero,
            cupo=_prev["cupo"] if _prev else None,
            carrera_asignada=_prev["carrera_asignada"] if _prev else None,
            descripcion=_prev["descripcion"] if _prev else "",
            # Fix H10 (2026-09-23): sin commit interno — todo el import
            # queda en una única transacción que cierra `commit_import`.
            commit=False,
        )
        if _prev is not None:
            com_db.coef_asignacion = _prev["coef_asignacion"]
            session.add(com_db)
        result.comisiones_creadas += 1
        nombres_actuales_canon.add(canon)
        numeros_actuales[com_db.numero] = com_db.nombre or ""

        for hor in com_new.horarios:
            entry = ScheduleEntryDB(
                id=str(uuid.uuid4()),
                schedule_id=schedule_id,
                codigo_materia=mp.materia_codigo,
                dia=hor.dia,
                hora_inicio=hor.hora_inicio,
                hora_fin=hor.hora_fin,
                comision_id=com_db.id,
                tipo_clase=hor.tipo_clase,
                virtual=hor.virtual,
            )
            session.add(entry)
            result.entries_creados += 1


# =============================================================================
# Shadow schedule (Fase G del rediseño 2026-09-15)
# =============================================================================
#
# En vez de que el usuario vea el preview como una tabla estática y
# después confirme para persistir, se crea un "cronograma sombra" que
# contiene las entries del destino + las nuevas del archivo aplicadas
# según las decisiones de merge. Ese shadow es un ScheduleDB normal
# con `es_shadow_import=True`, lo cual permite:
#
# - Renderizarlo con el calendario editable normal (mismos widgets).
# - Ejecutar `validar_cronograma` sobre él (validaciones sobre el
#   estado hipotético).
# - Editarlo con `add_schedule_entry`/`update_schedule_entry`/etc.
#
# Al confirmar, se aplican las diferencias entre el shadow y el
# destino (create/update/delete de entries y comisiones), y se
# elimina el shadow. Al cancelar se borra el shadow directamente.


def _copiar_entries_y_comisiones(
    session: Session,
    src_schedule_id: str,
    dst_schedule_id: str,
    materia_codigo: str | None = None,
) -> dict[str, str]:
    """Duplica las comisiones + entries del schedule origen al destino.

    Si ``materia_codigo`` viene distinto de ``None``, sólo se copian
    las comisiones + entries de esa materia (usado por
    ``regenerar_materia_en_shadow``).

    Devuelve un mapa `{com_id_origen: com_id_destino}` para que el
    caller pueda re-linkear referencias si hace falta.
    """
    _coms_stmt = select(ComisionDB).where(
        ComisionDB.schedule_id == src_schedule_id
    )
    if materia_codigo is not None:
        _coms_stmt = _coms_stmt.where(
            ComisionDB.materia_codigo == materia_codigo
        )
    coms_src = list(session.exec(_coms_stmt).all())
    com_id_map: dict[str, str] = {}
    for c in coms_src:
        new_id = str(uuid.uuid4())
        com_id_map[c.id] = new_id
        session.add(ComisionDB(
            id=new_id,
            materia_codigo=c.materia_codigo,
            dictado_id=c.dictado_id,
            plan_cursada_id=None,
            schedule_id=dst_schedule_id,
            comision_key=c.comision_key,
            nombre=c.nombre,
            numero=c.numero,
            cupo=c.cupo,
            descripcion=c.descripcion,
            coef_asignacion=c.coef_asignacion,
            carrera_asignada=c.carrera_asignada,
        ))
    session.flush()

    _entries_stmt = select(ScheduleEntryDB).where(
        ScheduleEntryDB.schedule_id == src_schedule_id,
    )
    if materia_codigo is not None:
        _entries_stmt = _entries_stmt.where(
            ScheduleEntryDB.codigo_materia == materia_codigo
        )
    entries_src = list(session.exec(_entries_stmt).all())
    for e in entries_src:
        new_com_id = com_id_map.get(e.comision_id) if e.comision_id else None
        session.add(ScheduleEntryDB(
            id=str(uuid.uuid4()),
            schedule_id=dst_schedule_id,
            codigo_materia=e.codigo_materia,
            dia=e.dia,
            hora_inicio=e.hora_inicio,
            hora_fin=e.hora_fin,
            comision_id=new_com_id,
            tipo_clase=e.tipo_clase,
            virtual=e.virtual,
        ))
    session.flush()
    return com_id_map


def crear_shadow_import(
    session: Session,
    destino_id: str,
    file,
    sheet_name: str | None = None,
) -> tuple[ScheduleDB, ImportPreview]:
    """Crea un shadow ScheduleDB con los datos del destino + import.

    El shadow es un cronograma temporal marcado con
    `es_shadow_import=True` y `shadow_target_schedule_id=destino_id`.
    Contiene una copia de las entries del destino + las del archivo
    aplicadas con la decisión de merge por default: **"reemplazar"**
    para las materias con datos previos, "agregar" para las nuevas.

    Uso previsto: el shadow alimenta las tarjetas per-materia del
    preview (calendarios Antes / Después, chequeos estructurales) y
    se puede correr `validar_cronograma` sobre él para ver el estado
    hipotético global. Los calendarios que ve el usuario son de sólo
    lectura, pero el shadow **sí** se muta: cambiar la decisión de
    merge de una materia llama a `regenerar_materia_en_shadow`, que
    recomputa esa materia dejando las demás intactas. Al final,
    `finalizar_shadow_import` aplica el shadow al destino y
    `descartar_shadow_import` lo tira.

    Devuelve `(shadow, preview)` para que el caller pueda mostrar
    tanto el calendario del shadow como el detalle del preview. Los
    errores no bloqueantes del commit inicial sobre el shadow (por
    ejemplo colisiones de nombre de comisión) se anexan a
    `preview.warnings`.
    """
    destino = session.get(ScheduleDB, destino_id)
    if destino is None:
        raise ValueError(f"Cronograma destino '{destino_id}' no existe.")

    # Preview inicial para tener el desglose de comisiones nuevas.
    preview = preview_import(session, destino_id, file, sheet_name=sheet_name)
    if preview.tiene_errores_bloqueantes:
        # Devolvemos un shadow "vacío" descartable — la UI mostrará
        # los parse_errors y no ofrecerá calendario.
        raise ValueError(
            "El archivo tiene errores estructurales — no se puede "
            "armar el preview. Detalles: "
            + "; ".join(preview.parse_errors)
        )

    # 1) Crear el shadow y copiar todo el estado actual del destino.
    from datetime import date as _date
    shadow = ScheduleDB(
        id=str(uuid.uuid4()),
        ciclo_id=destino.ciclo_id,
        nombre=f"[SHADOW] {destino.nombre}",
        fecha_upload=_date.today(),
        source_filename=f"shadow:{destino_id}",
        es_shadow_import=True,
        shadow_target_schedule_id=destino_id,
    )
    session.add(shadow)
    session.flush()
    _copiar_entries_y_comisiones(session, destino_id, shadow.id)
    session.flush()

    # 2) Aplicar el import sobre el shadow como si fuera un cronograma
    #    normal. Necesitamos recomputar el preview PARA EL SHADOW
    #    (el original apuntaba al destino). En el shadow, después de
    #    la copia, todas las materias del archivo que ya estaban en
    #    el destino aparecen como "con datos previos" → decisiones
    #    default: `agregar`. Si el nombre de comisión colisiona (por
    #    ejemplo "1" del destino y "1" del archivo), `commit_import`
    #    lo marca como error, que la UI muestra.
    #
    #    Rewind al inicio del archivo para volver a parsear:
    # Bugfix (2026-09-22, task #339): antes se hacía
    # `try: file.seek(0) except: pass`, silenciando un error real que
    # dejaba el shadow persistido sin datos del archivo. Ahora
    # levantamos ValueError y descartamos el shadow — la UI ya
    # convierte el error en toast.
    try:
        file.seek(0)
    except Exception as exc:  # noqa: BLE001
        _borrar_shadow_datos(session, shadow.id)
        session.delete(shadow)
        session.commit()
        raise ValueError(
            "No se pudo re-leer el archivo para armar el shadow "
            f"({exc}). Subí el archivo de nuevo."
        ) from exc
    preview_shadow = preview_import(
        session, shadow.id, file, sheet_name=sheet_name,
    )
    if preview_shadow.tiene_errores_bloqueantes:
        # Bugfix (2026-09-22, task #339): antes se commiteaba un
        # shadow vacío en este caso, lo que dejaba un preview inútil
        # (calendario con las entries del destino y sin la señal del
        # error). Ahora descartamos el shadow y avisamos al caller.
        _borrar_shadow_datos(session, shadow.id)
        session.delete(shadow)
        session.commit()
        raise ValueError(
            "El archivo generó errores al aplicarse sobre el shadow: "
            + "; ".join(preview_shadow.parse_errors)
        )
    # Decisiones por default: "reemplazar" para todo lo que tenga
    # datos previos (task #359, 2026-09-23). Antes era "agregar",
    # pero eso llevaba a acumulación silenciosa cuando el usuario
    # re-importaba con comisiones de nombre distinto — y era la
    # decisión menos frecuente en la práctica (el usuario típicamente
    # sube el archivo actualizado de la cátedra, no un delta).
    # La UI ahora expone el radio por materia; este default se puede
    # sobreescribir vía `regenerar_materia_en_shadow`.
    decisiones: dict[str, MergePolicy] = {
        m.materia_codigo: "reemplazar"
        for m in preview_shadow.materias
        if m.tiene_datos_previos
    }
    _commit_res = commit_import(session, preview_shadow, decisiones)
    # Fix auditoría H3 (2026-09-23): los errores no bloqueantes del
    # commit sobre el shadow (colisiones de nombre) se anexan a los
    # warnings del preview para que la UI los muestre en vez de
    # descartarlos en silencio.
    for _err in _commit_res.errors:
        preview.warnings.append(f"Al aplicar sobre el preview: {_err}")

    session.commit()
    session.refresh(shadow)
    # El preview que devolvemos es el "vs destino" (para que la UI
    # muestre las decisiones que se aplicaron al shadow).
    return shadow, preview


@dataclass
class FinalizarShadowResult:
    """Métricas de la aplicación de un shadow al destino.

    Sirve para armar el toast de confirmación en la UI. Se computan
    comparando los conjuntos de entries antes/después por *fingerprint*
    lógico (materia, comisión-por-nombre, día, hora_inicio, hora_fin,
    tipo_clase, virtual) en vez de por ``entry.id`` (que cambia al
    copiar shadow → destino). De ahí salen los tres contadores
    disjuntos:

    - ``entries_agregadas``: fingerprints que están en el shadow pero
      no en el destino previo.
    - ``entries_eliminadas``: fingerprints que estaban en el destino
      pero ya no están en el shadow (se borran al confirmar).
    - ``entries_sin_cambio``: fingerprints que aparecen en ambos lados.

    Bugfix (2026-09-23): antes el conteo era
    ``reemplazadas = min(previas, finales)``, que hacía que re-importar
    los mismos datos reportara todas las entries como "reemplazadas"
    aunque no hubiera cambio real.
    """
    destino_id: str
    destino_nombre: str
    entries_previas: int
    entries_finales: int
    entries_agregadas: int
    entries_eliminadas: int
    entries_sin_cambio: int


def finalizar_shadow_import(
    session: Session, shadow_id: str,
) -> FinalizarShadowResult:
    """Aplica los cambios del shadow al schedule destino y borra el shadow.

    Estrategia: reemplaza completamente las entries + comisiones del
    destino con las del shadow. Es más simple y consistente que
    calcular diffs — el shadow ya representa el estado deseado.

    Devuelve un ``FinalizarShadowResult`` con métricas para la UI
    (destino, entries previas/finales, agregadas, reemplazadas).

    Nota (task #355, 2026-09-22): esta operación **no** tiene lock
    optimista sobre el destino. Si otro proceso edita el destino
    entre `crear_shadow_import` y `finalizar_shadow_import`, esos
    cambios se pierden silenciosamente (el shadow los pisa). El
    riesgo se acepta porque el sistema es single-user en la práctica
    (uso desktop de una persona por vez). Para escenarios multi-user
    habría que agregar una columna `version` a `ScheduleDB` y
    validar que `destino.version` no cambió respecto al snapshot al
    crear el shadow.
    """
    shadow = session.get(ScheduleDB, shadow_id)
    if shadow is None:
        raise ValueError(f"Shadow '{shadow_id}' no existe.")
    if not shadow.es_shadow_import:
        raise ValueError(
            f"El schedule '{shadow_id}' no es un shadow del importer."
        )
    destino_id = shadow.shadow_target_schedule_id
    if destino_id is None:
        raise ValueError(
            f"Shadow '{shadow_id}' no tiene destino asociado."
        )
    destino = session.get(ScheduleDB, destino_id)
    if destino is None:
        raise ValueError(
            f"Destino '{destino_id}' del shadow ya no existe."
        )

    # 1) Snapshot entries previas del destino + entries finales del
    # shadow. Se comparan por fingerprint lógico (nombre de comisión,
    # no id) para clasificarlas como agregadas/eliminadas/sin_cambio.
    entries_dst = list(session.exec(
        select(ScheduleEntryDB).where(
            ScheduleEntryDB.schedule_id == destino_id,
        )
    ).all())
    n_entries_previas = len(entries_dst)

    entries_shadow = list(session.exec(
        select(ScheduleEntryDB).where(
            ScheduleEntryDB.schedule_id == shadow_id,
        )
    ).all())
    n_entries_finales = len(entries_shadow)

    fp_previas = _fingerprint_entries(session, entries_dst)
    fp_finales = _fingerprint_entries(session, entries_shadow)

    # 2) Borrar entries + comisiones del destino.
    for e in entries_dst:
        session.delete(e)
    coms_dst = list(session.exec(
        select(ComisionDB).where(ComisionDB.schedule_id == destino_id)
    ).all())
    for c in coms_dst:
        session.delete(c)
    session.flush()

    # 3) Copiar shadow → destino.
    _copiar_entries_y_comisiones(session, shadow_id, destino_id)

    # 4) Borrar el shadow (entries + comisiones + fila del schedule).
    _borrar_shadow_datos(session, shadow_id)
    session.delete(shadow)
    session.commit()

    # Métricas honestas por diff de fingerprints (aritmética de
    # multiconjuntos — fix auditoría H7, 2026-09-23: con `set` las
    # entries duplicadas idénticas colapsaban y el toast subcontaba
    # agregadas o reportaba 0 eliminadas al deduplicar). Invariantes
    # que ahora se cumplen siempre:
    #   agregadas + sin_cambio == finales
    #   eliminadas + sin_cambio == previas
    entries_agregadas = sum((fp_finales - fp_previas).values())
    entries_eliminadas = sum((fp_previas - fp_finales).values())
    entries_sin_cambio = sum((fp_previas & fp_finales).values())

    return FinalizarShadowResult(
        destino_id=destino_id,
        destino_nombre=destino.nombre,
        entries_previas=n_entries_previas,
        entries_finales=n_entries_finales,
        entries_agregadas=entries_agregadas,
        entries_eliminadas=entries_eliminadas,
        entries_sin_cambio=entries_sin_cambio,
    )


def _fingerprint_entries(
    session: Session, entries: list[ScheduleEntryDB],
) -> "Counter[tuple]":
    """Fingerprint lógico de un conjunto de entries — resuelve el
    ``comision_id`` a ``nombre`` porque el id es distinto entre
    destino y shadow (se copian con nuevos UUIDs).

    Cada entry se representa como
    ``(codigo_materia, comision_nombre, dia, hi_str, hf_str, tipo, virtual)``.

    Devuelve un ``Counter`` (multiconjunto), no un ``set``: dos entries
    idénticas cuentan como dos, para que los contadores del toast no
    mientan cuando el archivo trae filas duplicadas (auditoría H7,
    2026-09-23).
    """
    if not entries:
        return Counter()

    com_ids = {e.comision_id for e in entries if e.comision_id}
    com_map: dict[str, str] = {}
    if com_ids:
        coms = list(session.exec(
            select(ComisionDB).where(
                ComisionDB.id.in_(com_ids)  # type: ignore[attr-defined]
            )
        ).all())
        com_map = {c.id: (c.nombre or "").strip() for c in coms}

    result: Counter[tuple] = Counter()
    for e in entries:
        com_nombre = (
            com_map.get(e.comision_id, "") if e.comision_id else ""
        )
        result[(
            e.codigo_materia,
            com_nombre,
            e.dia,
            e.hora_inicio.isoformat() if e.hora_inicio else "",
            e.hora_fin.isoformat() if e.hora_fin else "",
            e.tipo_clase or "",
            # 2026-09-23: virtual es booleano y un nulo equivale a
            # False — el fingerprint colapsa ambos para que
            # re-importar el mismo archivo sobre entries históricas
            # (virtual=None) no reporte cambios fantasma.
            "1" if e.virtual is True else "0",
        )] += 1
    return result


def regenerar_materia_en_shadow(
    session: Session,
    shadow_id: str,
    materia_codigo: str,
    decision: MergePolicy,
    file,
    sheet_name: str | None = None,
) -> ImportResult:
    """Regenera las entries + comisiones de UNA materia en el shadow,
    aplicando la decisión (``reemplazar`` / ``agregar`` / ``ignorar``)
    con el contenido del archivo.

    Uso: la UI del importer expone por materia un radio "Decisión"; al
    cambiarlo se llama esta función para recomputar el estado
    hipotético de esa materia sin tocar las demás. Cualquier edición
    manual previa que el usuario haya hecho **en esta materia** se
    pierde (semántica documentada en la UI, task #360, 2026-09-23).

    Args:
        session: sesión activa.
        shadow_id: shadow del importer (debe existir).
        materia_codigo: materia a regenerar.
        decision: ``"reemplazar"`` (borra todo lo previo del destino
            en esta materia y aplica solo lo del archivo);
            ``"agregar"`` (mantiene lo previo del destino y suma las
            comisiones nuevas del archivo, exigiendo que no colisionen
            nombres); ``"ignorar"`` (deja solo lo previo del destino,
            sin nada del archivo).
        file: archivo original que se pasó a ``crear_shadow_import``.
        sheet_name: hoja del Excel a usar (mismo criterio que
            ``crear_shadow_import``).

    Returns:
        El ``ImportResult`` del commit sobre el shadow. Fix auditoría
        H3 (2026-09-23): antes se descartaba, así que si la decisión
        ``"agregar"`` colisionaba en nombres de comisión (el caso
        típico: archivo actualizado de la misma cátedra con la misma
        comisión "1"), los horarios del archivo se rechazaban en
        silencio y la UI no mostraba nada. El caller **debe** revisar
        ``result.errors`` y mostrarlos.

    Raises:
        ValueError: si el shadow no existe, no es un shadow válido, si
            el re-parseo del archivo levanta errores bloqueantes, o si
            la materia no aparece en la hoja importada (con decisión
            distinta de ``"ignorar"``).
    """
    shadow = session.get(ScheduleDB, shadow_id)
    if shadow is None:
        raise ValueError(f"Shadow '{shadow_id}' no existe.")
    if not shadow.es_shadow_import:
        raise ValueError(
            f"El schedule '{shadow_id}' no es un shadow del importer."
        )
    destino_id = shadow.shadow_target_schedule_id
    if destino_id is None:
        raise ValueError(
            f"Shadow '{shadow_id}' no tiene destino asociado."
        )

    # 1) Vaciar el estado actual de la materia en el shadow.
    _borrar_materia_en_shadow(session, shadow_id, materia_codigo)

    # 2) Copiar la materia desde el destino al shadow (baseline previo).
    _copiar_entries_y_comisiones(
        session, destino_id, shadow_id, materia_codigo=materia_codigo,
    )

    # 3) Re-parsear el archivo y aplicar la decisión sólo a esta
    # materia. `commit_import` acepta un preview del shadow completo,
    # así que armamos uno restringido.
    try:
        file.seek(0)
    except Exception as exc:  # noqa: BLE001
        raise ValueError(
            f"No se pudo re-leer el archivo ({exc}). Subilo de nuevo."
        ) from exc
    preview_shadow = preview_import(
        session, shadow_id, file, sheet_name=sheet_name,
    )
    if preview_shadow.tiene_errores_bloqueantes:
        raise ValueError(
            "El archivo tiene errores estructurales al re-parsear: "
            + "; ".join(preview_shadow.parse_errors)
        )

    # Filtrar el preview a solo la materia que estamos regenerando.
    # No borro la lista original — `commit_import` itera sobre
    # `preview.materias`, así que le paso un preview con esa lista
    # acotada.
    _materias_original = list(preview_shadow.materias)
    _materias_target = [
        m for m in _materias_original
        if m.materia_codigo == materia_codigo
    ]
    if not _materias_target and decision != "ignorar":
        # Guard (auditoría H5/H6-back, 2026-09-23): sin este raise, la
        # regeneración de una materia ausente del archivo era un no-op
        # silencioso equivalente a "ignorar" — el caller creía haber
        # aplicado la decisión.
        raise ValueError(
            f"La materia '{materia_codigo}' no aparece en la hoja "
            "del archivo que se está importando — no hay nada que "
            f"aplicar con la decisión '{decision}'."
        )
    preview_shadow.materias = _materias_target
    try:
        return commit_import(
            session, preview_shadow,
            {materia_codigo: decision},
        )
    finally:
        preview_shadow.materias = _materias_original


def _borrar_materia_en_shadow(
    session: Session, shadow_id: str, materia_codigo: str,
) -> None:
    """Borra entries + comisiones de una materia dentro del shadow."""
    entries = list(session.exec(
        select(ScheduleEntryDB)
        .where(ScheduleEntryDB.schedule_id == shadow_id)
        .where(ScheduleEntryDB.codigo_materia == materia_codigo)
    ).all())
    for e in entries:
        session.delete(e)
    coms = list(session.exec(
        select(ComisionDB)
        .where(ComisionDB.schedule_id == shadow_id)
        .where(ComisionDB.materia_codigo == materia_codigo)
    ).all())
    for c in coms:
        session.delete(c)
    session.flush()


def descartar_shadow_import(session: Session, shadow_id: str) -> None:
    """Elimina un shadow y todos sus datos temporales."""
    shadow = session.get(ScheduleDB, shadow_id)
    if shadow is None:
        return
    if not shadow.es_shadow_import:
        raise ValueError(
            f"El schedule '{shadow_id}' no es un shadow — no borro."
        )
    _borrar_shadow_datos(session, shadow_id)
    session.delete(shadow)
    session.commit()


def _borrar_shadow_datos(session: Session, shadow_id: str) -> None:
    """Borra entries + comisiones de un shadow (sin borrar la fila del schedule)."""
    entries = list(session.exec(
        select(ScheduleEntryDB).where(
            ScheduleEntryDB.schedule_id == shadow_id,
        )
    ).all())
    for e in entries:
        session.delete(e)
    coms = list(session.exec(
        select(ComisionDB).where(ComisionDB.schedule_id == shadow_id)
    ).all())
    for c in coms:
        session.delete(c)
    session.flush()


def list_shadows_huerfanos(session: Session) -> list[ScheduleDB]:
    """Devuelve los shadow schedules que quedaron en la DB.

    Si el usuario cierra el navegador con un preview abierto, el
    shadow queda persistido. Este helper lo lista para que la UI
    pueda ofrecerlo al usuario y limpiarlo.
    """
    stmt = select(ScheduleDB).where(
        ScheduleDB.es_shadow_import == True,  # noqa: E712
    ).order_by(ScheduleDB.fecha_upload.desc())  # type: ignore[attr-defined]
    return list(session.exec(stmt).all())
