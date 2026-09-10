"""Componente compartido de filtros de materias.

Extrae en un único lugar la lógica de:

- Búsqueda por código o nombre (tolerante a acentos).
- Ubicación curricular (carrera + año + cuatri) usando el plan
  **activo** de cada carrera, con **fallback al plan más reciente**
  si ninguna versión está marcada como activa. Esto evita que el
  filtro devuelva 0 materias cuando todavía nadie tocó el flag.
- Atributos de la materia (grupo, optativa, virtual, vigencia,
  período).

Callers actuales: pestaña **Lista de materias** (page Materias) y
sección **Reasignar materias** (page Materias → Grupos). Cualquier
pantalla nueva que necesite el mismo filtro debe consumir este
componente en lugar de reescribir el flujo.
"""

from __future__ import annotations

import unicodedata
from dataclasses import dataclass, field

import streamlit as st
from sqlmodel import Session, select

from src.database.models import (
    CarreraDB,
    GrupoMateriaDB,
    MateriaDB,
    PlanEstudioDB,
)
from src.services.grupo_materia_service import (
    get_plan_vigente,
    list_grupos,
)


# =============================================================================
# Modelo de estado
# =============================================================================


@dataclass
class MateriaFiltros:
    """Estado del filtro. Se construye desde `render_materia_filtros`
    y se aplica con `aplicar_materia_filtros`. Todos los campos con
    default vacío / 'Todos' significan "sin filtrar por este eje"."""
    busqueda: str = ""
    carreras: list[str] = field(default_factory=list)  # nombres
    anios: list[int] = field(default_factory=list)
    cuatris: list[str] = field(default_factory=list)
    grupo_nombre: str = "Todos"
    # "Todas" | "Sólo Sin clasificar" es un preset extra sólo para
    # pantallas de reasignación; por default no lo exponemos.
    grupo_scope: str = "Todos"  # "Todos" | "Sólo Sin clasificar"
    optativa: str = "Todas"     # "Todas" | "Sólo optativas" | "Sólo obligatorias"
    virtual: str = "Todas"      # "Todas" | "Sólo virtuales" | "Sólo presenciales"
    vigencia: str = "Todas"     # "Todas" | "Sólo activas" | "Sólo archivadas"
    lab: str = "Todas"          # "Todas" | "Con horas de lab" | "Sin horas de lab" | ...
    periodo: str = "Todos"      # "Todos" | "Cuatrimestral" | "Anual"


# =============================================================================
# Render + apply
# =============================================================================


def _normalizar(texto: str) -> str:
    """Lower + saca acentos para búsqueda tolerante."""
    nfkd = unicodedata.normalize("NFKD", texto)
    return "".join(c for c in nfkd if not unicodedata.combining(c)).lower()


def render_materia_filtros(
    session: Session,
    *,
    key_ns: str,
    incluir_vigencia: bool = True,
    incluir_lab: bool = False,
    incluir_grupo_scope: bool = False,
    ubicacion_default_expanded: bool = False,
    atributos_default_expanded: bool = False,
) -> MateriaFiltros:
    """Renderiza la sección Filtros (dentro de un container bordeado)
    y devuelve el estado ``MateriaFiltros`` con las selecciones.

    Args:
        session: sesión SQLModel.
        key_ns: namespace para las keys de session_state (evita
            colisiones entre múltiples usos en la misma página).
        incluir_vigencia: si True, agrega el selector de vigencia
            (activas / archivadas). Útil en Lista, poco relevante en
            Reasignar.
        incluir_lab: si True, agrega el filtro de laboratorios.
        incluir_grupo_scope: si True, agrega un selector previo al
            selector de grupo con las opciones "Todos" / "Sólo Sin
            clasificar". Se usa en Reasignar como atajo al backlog.
        ubicacion_default_expanded: si True, el expander de ubicación
            arranca abierto.
        atributos_default_expanded: idem para atributos.
    """
    result = MateriaFiltros()

    with st.container(border=True):
        st.markdown("**🔎 Filtros**")

        # Ubicación curricular.
        with st.expander(
            "📍 Ubicación curricular",
            expanded=ubicacion_default_expanded,
        ):
            st.caption(
                "Filtra por dónde aparecen las materias en el plan "
                "de cada carrera. Usa la versión **activa** del plan; "
                "si la carrera no tiene versión activa marcada, cae "
                "al **plan más reciente**."
            )
            carreras_db = list(session.exec(
                select(CarreraDB).order_by(CarreraDB.nombre)  # type: ignore[arg-type]
            ).all())
            result.carreras = st.multiselect(
                "Carrera(s)",
                options=[c.nombre for c in carreras_db],
                key=f"{key_ns}_ubic_carrera",
            )
            _col_a, _col_c = st.columns(2)
            with _col_a:
                result.anios = st.multiselect(
                    "Año(s)",
                    options=list(range(1, 7)),
                    key=f"{key_ns}_ubic_anio",
                )
            with _col_c:
                result.cuatris = st.multiselect(
                    "Cuatri",
                    options=["1C", "2C", "Anual"],
                    key=f"{key_ns}_ubic_cuatri",
                )

        # Atributos.
        with st.expander(
            "🏷️ Atributos",
            expanded=atributos_default_expanded,
        ):
            grupos_lst = sorted(
                (g for g in list_grupos(session) if not g.es_sin_clasificar),
                key=lambda g: g.nombre.lower(),
            )
            if incluir_grupo_scope:
                scope_opts = ["Todos", "Sólo Sin clasificar"]
                result.grupo_scope = st.selectbox(
                    "Grupo actual (atajo)",
                    options=scope_opts,
                    key=f"{key_ns}_atr_grupo_scope",
                    help=(
                        "Atajo al backlog de materias sin grupo real. "
                        "Al elegir uno de estos presets, el selector "
                        "'Grupo' de abajo queda desactivado."
                    ),
                )
            grupo_disabled = (
                incluir_grupo_scope and result.grupo_scope != "Todos"
            )
            result.grupo_nombre = st.selectbox(
                "Grupo",
                options=["Todos"] + [g.nombre for g in grupos_lst],
                key=f"{key_ns}_atr_grupo",
                disabled=grupo_disabled,
                help=(
                    "Filtrá por el grupo de materias asignado a cada "
                    "materia. Excluye 'Sin clasificar' (usá el "
                    "selector de arriba si lo necesitás)."
                    if incluir_grupo_scope else
                    "Filtrá por el grupo de materias asignado a cada materia."
                ),
            )
            _ca1, _ca2 = st.columns(2)
            with _ca1:
                result.optativa = st.selectbox(
                    "Optativa",
                    options=[
                        "Todas", "Sólo optativas", "Sólo obligatorias",
                    ],
                    key=f"{key_ns}_atr_opt",
                )
                result.virtual = st.selectbox(
                    "Virtual",
                    options=[
                        "Todas", "Sólo virtuales", "Sólo presenciales",
                    ],
                    key=f"{key_ns}_atr_virt",
                )
            with _ca2:
                if incluir_vigencia:
                    result.vigencia = st.selectbox(
                        "Vigencia",
                        options=[
                            "Todas", "Sólo activas", "Sólo archivadas",
                        ],
                        key=f"{key_ns}_atr_vigencia",
                    )
                result.periodo = st.selectbox(
                    "Período",
                    options=["Todos", "Cuatrimestral", "Anual"],
                    key=f"{key_ns}_atr_periodo",
                )
            if incluir_lab:
                result.lab = st.selectbox(
                    "Laboratorio",
                    options=[
                        "Todas",
                        "Con horas de lab",
                        "Sin horas de lab",
                    ],
                    key=f"{key_ns}_atr_lab",
                )

        # Búsqueda por código o nombre.
        result.busqueda = st.text_input(
            "🔍 Buscar por código o nombre",
            key=f"{key_ns}_search",
            placeholder="Ej: F14, algebra, matemática…",
            help=(
                "La búsqueda ignora mayúsculas y acentos. "
                "Escribí 'fisica' y encuentra 'Física'."
            ),
        )

    return result


def aplicar_materia_filtros(
    session: Session,
    materias: list[MateriaDB],
    filtros: MateriaFiltros,
) -> list[MateriaDB]:
    """Aplica el ``MateriaFiltros`` a la lista de materias y devuelve
    la sublista que cumple todos los criterios. La lista de entrada
    se puede pasar ya ordenada; el orden se preserva."""
    result = list(materias)

    # --- Búsqueda ---
    if filtros.busqueda.strip():
        term = _normalizar(filtros.busqueda.strip())
        result = [
            m for m in result
            if term in _normalizar(m.codigo)
            or term in _normalizar(m.nombre)
        ]

    # --- Ubicación curricular ---
    if filtros.carreras or filtros.anios or filtros.cuatris:
        carreras_db = list(session.exec(select(CarreraDB)).all())
        if filtros.carreras:
            cods_carr = [
                c.codigo for c in carreras_db
                if c.nombre in filtros.carreras
            ]
        else:
            cods_carr = [c.codigo for c in carreras_db]
        plan_ids: list[str] = []
        for cod in cods_carr:
            pv = get_plan_vigente(session, cod)
            if pv is not None:
                plan_ids.append(pv.id)
        if not plan_ids:
            return []
        pes = list(session.exec(
            select(PlanEstudioDB).where(
                PlanEstudioDB.plan_version_id.in_(plan_ids),  # type: ignore[attr-defined]
            )
        ).all())
        codigos_ok: set[str] = set()
        for pe in pes:
            if filtros.anios and pe.anio_plan not in filtros.anios:
                continue
            if filtros.cuatris and pe.cuatrimestre_plan not in filtros.cuatris:
                continue
            codigos_ok.add(pe.materia_codigo)
        result = [m for m in result if m.codigo in codigos_ok]

    # --- Grupo (scope o específico) ---
    if filtros.grupo_scope == "Sólo Sin clasificar":
        from src.services.grupo_materia_service import (
            get_grupo_sin_clasificar,
        )
        try:
            sc = get_grupo_sin_clasificar(session)
            result = [m for m in result if m.grupo_id == sc.id]
        except ValueError:
            result = []
    elif filtros.grupo_nombre != "Todos":
        target = session.exec(
            select(GrupoMateriaDB).where(
                GrupoMateriaDB.nombre == filtros.grupo_nombre,
            ).limit(1)
        ).first()
        if target is not None:
            result = [m for m in result if m.grupo_id == target.id]
        else:
            result = []

    # --- Optativa ---
    if filtros.optativa == "Sólo optativas":
        result = [m for m in result if m.optativa]
    elif filtros.optativa == "Sólo obligatorias":
        result = [m for m in result if not m.optativa]

    # --- Virtual ---
    if filtros.virtual == "Sólo virtuales":
        result = [m for m in result if m.virtual]
    elif filtros.virtual == "Sólo presenciales":
        result = [m for m in result if not m.virtual]

    # --- Vigencia ---
    if filtros.vigencia == "Sólo activas":
        result = [m for m in result if m.active]
    elif filtros.vigencia == "Sólo archivadas":
        result = [m for m in result if not m.active]

    # --- Período ---
    if filtros.periodo == "Cuatrimestral":
        result = [m for m in result if m.periodo == "cuatrimestral"]
    elif filtros.periodo == "Anual":
        result = [m for m in result if m.periodo == "anual"]

    # --- Laboratorio ---
    if filtros.lab == "Con horas de lab":
        result = [
            m for m in result if (m.horas_laboratorio or 0) > 0
        ]
    elif filtros.lab == "Sin horas de lab":
        result = [
            m for m in result if (m.horas_laboratorio or 0) == 0
        ]

    return result
