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
    return preview
