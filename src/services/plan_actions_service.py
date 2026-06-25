"""Acciones operativas sobre un plan de cursada.

Agrupa funciones que toman un plan y aplican modificaciones derivadas
(no editoriales) sobre sus entidades. Estas acciones se exponen desde
el panel "🔧 Acciones del plan" en la página de Planes.

Acciones disponibles:

- ``preview_auto_completar_tipos``: dado un plan, lista los horarios
  cuyo ``tipo_clase`` está en ``None`` y que pueden auto-determinarse a
  partir de las horas declaradas en su materia (regla: si la materia
  tiene ``horas_laboratorio == 0`` y ``horas_teoria > 0`` → tipo
  ``teorica``; al revés → ``laboratorio``).
- ``aplicar_auto_completar_tipos``: aplica el cambio sobre los
  ``HorarioDB`` afectados y devuelve el detalle de qué cambió.

La regla NO toca horarios cuya materia tiene ``hteo > 0`` y ``hlab > 0``
simultáneamente (esos los decide el LP), ni horarios que ya tienen
tipo distinto de ``None`` (los respeta el operador).
"""

from __future__ import annotations

from dataclasses import dataclass, field

from sqlmodel import Session, select

from src.database.models import (
    ComisionDB,
    HorarioDB,
    MateriaDB,
)


@dataclass
class HorarioAutoTipo:
    """Detalle de un horario que el auto-completador puede tipificar."""

    horario_id: str
    materia_codigo: str
    materia_nombre: str
    comision_nombre: str
    dia: str
    hora_inicio: str  # "HH:MM"
    hora_fin: str
    tipo_propuesto: str  # "teorica" | "laboratorio"
    razon: str  # "hlab=0" | "hteo=0"


@dataclass
class AutoCompletarPreview:
    """Resultado del preview ANTES de aplicar."""

    a_teorica: list[HorarioAutoTipo] = field(default_factory=list)
    a_laboratorio: list[HorarioAutoTipo] = field(default_factory=list)
    # Materias del plan sin horas declaradas (ambas en None / 0); el
    # auto-completador no puede inferir nada acá.
    materias_sin_horas: list[str] = field(default_factory=list)
    # Materias del plan con ambas > 0 (decisión del LP, no se toca).
    materias_mixtas: list[str] = field(default_factory=list)

    @property
    def total(self) -> int:
        return len(self.a_teorica) + len(self.a_laboratorio)


def _materias_del_plan(
    session: Session, plan_id: str,
) -> dict[str, MateriaDB]:
    """Devuelve {materia_codigo: MateriaDB} de las materias presentes
    en las comisiones del plan."""
    com_rows = list(session.exec(
        select(ComisionDB.materia_codigo).where(
            ComisionDB.plan_cursada_id == plan_id,
        ).distinct()
    ).all())
    if not com_rows:
        return {}
    materias = list(session.exec(
        select(MateriaDB).where(
            MateriaDB.codigo.in_(com_rows)  # type: ignore[attr-defined]
        )
    ).all())
    return {m.codigo: m for m in materias}


def _horarios_del_plan(
    session: Session, plan_id: str,
) -> list[HorarioDB]:
    """Horarios de todas las comisiones del plan."""
    com_ids = list(session.exec(
        select(ComisionDB.id).where(
            ComisionDB.plan_cursada_id == plan_id,
        )
    ).all())
    if not com_ids:
        return []
    return list(session.exec(
        select(HorarioDB).where(
            HorarioDB.comision_id.in_(com_ids)  # type: ignore[attr-defined]
        )
    ).all())


def _comisiones_del_plan(
    session: Session, plan_id: str,
) -> dict[str, ComisionDB]:
    coms = list(session.exec(
        select(ComisionDB).where(
            ComisionDB.plan_cursada_id == plan_id,
        )
    ).all())
    return {c.id: c for c in coms}


def preview_auto_completar_tipos(
    session: Session, plan_id: str,
) -> AutoCompletarPreview:
    """Para cada horario del plan con ``tipo_clase=None``, decide si
    puede auto-completarse a partir de las horas declaradas de su materia.

    Reglas:

    - Si ``hlab == 0`` y ``hteo > 0`` → ``teorica``.
    - Si ``hteo == 0`` y ``hlab > 0`` → ``laboratorio``.
    - Si ambas son ``> 0`` → no se toca (lo decide el LP). Se reporta
      la materia en ``materias_mixtas``.
    - Si ambas son ``None`` o ``0`` → no se toca. Se reporta en
      ``materias_sin_horas``.

    NO modifica la base; sólo reporta el alcance del cambio.
    """
    preview = AutoCompletarPreview()
    materias = _materias_del_plan(session, plan_id)
    horarios = _horarios_del_plan(session, plan_id)
    comisiones = _comisiones_del_plan(session, plan_id)
    if not horarios:
        return preview

    # Clasifico materias por tipo de regla aplicable.
    tipo_predecible: dict[str, tuple[str, str]] = {}  # codigo → (tipo, razon)
    for codigo, m in materias.items():
        hteo = m.horas_teoria or 0.0
        hlab = m.horas_laboratorio or 0.0
        if hteo > 0 and hlab > 0:
            preview.materias_mixtas.append(codigo)
            continue
        if hteo == 0 and hlab == 0:
            preview.materias_sin_horas.append(codigo)
            continue
        if hlab == 0 and hteo > 0:
            tipo_predecible[codigo] = ("teorica", "hlab=0")
        elif hteo == 0 and hlab > 0:
            tipo_predecible[codigo] = ("laboratorio", "hteo=0")

    # Filtrar horarios None y emparejar con la regla.
    for h in horarios:
        if h.tipo_clase is not None:
            continue
        regla = tipo_predecible.get(h.codigo_materia)
        if regla is None:
            continue
        tipo, razon = regla
        materia = materias.get(h.codigo_materia)
        com = comisiones.get(h.comision_id)
        item = HorarioAutoTipo(
            horario_id=h.id,
            materia_codigo=h.codigo_materia,
            materia_nombre=materia.nombre if materia else h.codigo_materia,
            comision_nombre=com.nombre if com else "?",
            dia=h.dia,
            hora_inicio=h.hora_inicio.strftime("%H:%M"),
            hora_fin=h.hora_fin.strftime("%H:%M"),
            tipo_propuesto=tipo,
            razon=razon,
        )
        if tipo == "teorica":
            preview.a_teorica.append(item)
        else:
            preview.a_laboratorio.append(item)

    # Ordenar para que la lista sea estable y legible.
    def _sort_key(it: HorarioAutoTipo) -> tuple:
        return (it.materia_codigo, it.dia, it.hora_inicio)
    preview.a_teorica.sort(key=_sort_key)
    preview.a_laboratorio.sort(key=_sort_key)
    preview.materias_mixtas.sort()
    preview.materias_sin_horas.sort()
    return preview


def aplicar_auto_completar_tipos(
    session: Session, plan_id: str,
) -> AutoCompletarPreview:
    """Aplica el auto-completador y persiste los cambios en
    ``HorarioDB.tipo_clase``.

    Devuelve el mismo ``AutoCompletarPreview`` con el detalle de lo
    que se cambió (idéntico al ``preview_auto_completar_tipos`` previo).
    Es seguro re-ejecutar: si nada cambió, ``preview.total == 0``.
    """
    preview = preview_auto_completar_tipos(session, plan_id)
    if preview.total == 0:
        return preview

    ids_to_tipo: dict[str, str] = {}
    for it in preview.a_teorica:
        ids_to_tipo[it.horario_id] = "teorica"
    for it in preview.a_laboratorio:
        ids_to_tipo[it.horario_id] = "laboratorio"

    horarios = list(session.exec(
        select(HorarioDB).where(
            HorarioDB.id.in_(ids_to_tipo.keys())  # type: ignore[attr-defined]
        )
    ).all())
    for h in horarios:
        h.tipo_clase = ids_to_tipo[h.id]
        session.add(h)
    session.commit()

    # Invalidar pool por si hay sesiones cacheadas.
    from src.database.connection import engine as _engine
    _engine.dispose()
    return preview


# =============================================================================
# Edición de horario con preview de validaciones
# =============================================================================

from datetime import time as _time


@dataclass
class CambioHorarioPreview:
    """Resumen del impacto de un cambio propuesto a un HorarioDB.

    Se computa modificando el horario en una transacción que se hace
    rollback al final, así no toca la DB. La UI lo usa para mostrarle
    al usuario qué validaciones se romperían (o se resolverían) antes
    de pedir confirmación.
    """
    horario_id: str
    plan_id: str
    # Estado actual y propuesto.
    actual: dict  # {dia, hora_inicio, hora_fin}
    propuesto: dict
    # Conflictos pre-existentes (sin aplicar el cambio).
    conflictos_antes: list[dict] = field(default_factory=list)
    # Conflictos resultantes (con el cambio aplicado).
    conflictos_despues: list[dict] = field(default_factory=list)
    # Conflictos que el cambio AGREGA (están en después y no en antes).
    conflictos_agregados: list[dict] = field(default_factory=list)
    # Conflictos que el cambio QUITA (estaban en antes y no en después).
    conflictos_resueltos: list[dict] = field(default_factory=list)
    # Horarios de la misma comisión que ya existen en el día destino
    # (excluyendo al propio horario que se está editando). Indica que
    # la comisión ya tiene otra clase ese día. Cada item:
    # {"horario_id", "dia", "hora_inicio", "hora_fin"}.
    duplicados_mismo_dia: list[dict] = field(default_factory=list)
    error: str | None = None  # Si la validación cruda falla.

    @property
    def es_seguro(self) -> bool:
        """True si el cambio no agrega ningún conflicto nuevo NI
        coincide con otro horario de la misma comisión en el día destino."""
        return (
            self.error is None
            and not self.conflictos_agregados
            and not self.duplicados_mismo_dia
        )


def _conflicto_signature(c: dict) -> tuple:
    """Tupla canónica para comparar conflictos como sets.

    Normaliza el orden de los pares de materias para que (A,B) == (B,A).
    """
    a = c.get("materia_a", "")
    b = c.get("materia_b", "")
    mats = tuple(sorted([a, b]))
    return (
        c.get("carrera_codigo", ""),
        c.get("anio_plan", 0),
        c.get("cuatrimestre_plan", ""),
        c.get("dia", ""),
        mats[0], mats[1],
        c.get("hora_inicio_a", ""), c.get("hora_fin_a", ""),
        c.get("hora_inicio_b", ""), c.get("hora_fin_b", ""),
    )


def preview_cambio_horario(
    session: Session,
    plan_id: str,
    horario_id: str,
    nuevo_dia: str,
    nuevo_hora_inicio: _time,
    nuevo_hora_fin: _time,
) -> CambioHorarioPreview:
    """Computa el impacto de cambiar día/hora de un horario, SIN
    persistir.

    Estrategia: lee los conflictos del plan ANTES, modifica el horario
    en memoria (sin commit), lee los conflictos DESPUÉS, hace
    ``rollback`` para descartar el cambio. Compara para mostrar al
    usuario qué conflictos agrega o resuelve.

    Args:
        session: sesión SQLAlchemy. La función NO commitea ni cierra.
        plan_id: id del plan.
        horario_id: id del horario a modificar.
        nuevo_dia, nuevo_hora_inicio, nuevo_hora_fin: valores propuestos.

    Returns:
        CambioHorarioPreview con la diferencia de conflictos antes/después.
    """
    from src.services.validations import (
        validar_conflictos_horarios_plan_estructurados,
    )

    horario = session.get(HorarioDB, horario_id)
    if horario is None:
        return CambioHorarioPreview(
            horario_id=horario_id,
            plan_id=plan_id,
            actual={},
            propuesto={
                "dia": nuevo_dia,
                "hora_inicio": nuevo_hora_inicio.strftime("%H:%M"),
                "hora_fin": nuevo_hora_fin.strftime("%H:%M"),
            },
            error=f"Horario '{horario_id}' no encontrado.",
        )

    # Snapshot del estado actual para el resultado.
    actual = {
        "dia": horario.dia,
        "hora_inicio": horario.hora_inicio.strftime("%H:%M"),
        "hora_fin": horario.hora_fin.strftime("%H:%M"),
    }
    propuesto = {
        "dia": nuevo_dia,
        "hora_inicio": nuevo_hora_inicio.strftime("%H:%M"),
        "hora_fin": nuevo_hora_fin.strftime("%H:%M"),
    }

    # Validación trivial.
    if nuevo_hora_fin <= nuevo_hora_inicio:
        return CambioHorarioPreview(
            horario_id=horario_id,
            plan_id=plan_id,
            actual=actual,
            propuesto=propuesto,
            error="La hora de fin debe ser posterior a la hora de inicio.",
        )

    # Duplicados: otros horarios de la MISMA COMISIÓN en el día
    # destino (excluyendo al propio horario que se está editando).
    # No es un "conflicto" formal del LP — pero suele indicar un
    # error operativo (no se espera que una comisión tenga dos
    # clases el mismo día). Lo reportamos como warning aparte.
    duplicados: list[dict] = []
    if nuevo_dia != horario.dia or True:  # siempre chequear contra el día destino
        otros_mismos_dia = list(session.exec(
            select(HorarioDB).where(
                HorarioDB.comision_id == horario.comision_id,
                HorarioDB.dia == nuevo_dia,
                HorarioDB.id != horario.id,
            )
        ).all())
        for oh in otros_mismos_dia:
            duplicados.append({
                "horario_id": oh.id,
                "dia": oh.dia,
                "hora_inicio": oh.hora_inicio.strftime("%H:%M"),
                "hora_fin": oh.hora_fin.strftime("%H:%M"),
            })

    # Conflictos antes del cambio.
    conflictos_antes_objs = validar_conflictos_horarios_plan_estructurados(
        session, plan_id,
    )
    conflictos_antes = [_conflicto_to_dict_local(c) for c in conflictos_antes_objs]

    # Aplicar el cambio EN MEMORIA (sin commit).
    horario.dia = nuevo_dia
    horario.hora_inicio = nuevo_hora_inicio
    horario.hora_fin = nuevo_hora_fin
    session.add(horario)
    session.flush()  # Hace visible el cambio para queries en la misma sesión.

    try:
        conflictos_despues_objs = (
            validar_conflictos_horarios_plan_estructurados(
                session, plan_id,
            )
        )
        conflictos_despues = [
            _conflicto_to_dict_local(c) for c in conflictos_despues_objs
        ]
    finally:
        # Descartar TODO lo no persistido en esta sesión.
        session.rollback()
        session.expire_all()

    # Calcular diferencias.
    sig_antes = {_conflicto_signature(c) for c in conflictos_antes}
    sig_despues = {_conflicto_signature(c) for c in conflictos_despues}
    agregados = [
        c for c in conflictos_despues
        if _conflicto_signature(c) not in sig_antes
    ]
    resueltos = [
        c for c in conflictos_antes
        if _conflicto_signature(c) not in sig_despues
    ]

    return CambioHorarioPreview(
        horario_id=horario_id,
        plan_id=plan_id,
        actual=actual,
        propuesto=propuesto,
        conflictos_antes=conflictos_antes,
        conflictos_despues=conflictos_despues,
        conflictos_agregados=agregados,
        conflictos_resueltos=resueltos,
        duplicados_mismo_dia=duplicados,
    )


def _conflicto_to_dict_local(c) -> dict:
    """Serializa ConflictoHorario a dict (igual que en
    plan_validation_service pero local para no introducir dependencia
    circular)."""
    return {
        "carrera_codigo": c.carrera_codigo,
        "anio_plan": c.anio_plan,
        "cuatrimestre_plan": c.cuatrimestre_plan,
        "materia_a": c.materia_a,
        "materia_b": c.materia_b,
        "dia": c.dia,
        "hora_inicio_a": c.hora_inicio_a,
        "hora_fin_a": c.hora_fin_a,
        "hora_inicio_b": c.hora_inicio_b,
        "hora_fin_b": c.hora_fin_b,
    }


def aplicar_cambio_horario(
    session: Session,
    horario_id: str,
    nuevo_dia: str,
    nuevo_hora_inicio: _time,
    nuevo_hora_fin: _time,
) -> bool:
    """Persiste el cambio de día/hora del horario.

    Asume que la UI ya corrió ``preview_cambio_horario`` y el usuario
    confirmó (incluso si había conflictos agregados, en cuyo caso el
    operador eligió forzar el cambio). NO valida acá.

    Returns:
        True si el cambio se aplicó, False si el horario no existe.
    """
    horario = session.get(HorarioDB, horario_id)
    if horario is None:
        return False
    horario.dia = nuevo_dia
    horario.hora_inicio = nuevo_hora_inicio
    horario.hora_fin = nuevo_hora_fin
    session.add(horario)
    session.commit()

    # Invalidar pool por si hay sesiones cacheadas.
    from src.database.connection import engine as _engine
    _engine.dispose()
    return True
