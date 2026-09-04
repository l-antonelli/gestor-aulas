"""Página de historial de cambios (Fase 3b).

Vista consolidada de mutaciones capturadas por el change log en las
entidades trackeadas (Materia, Carrera, Dictado, DictadoCiclo, Sede).

Dos modos:
- **Feed global**: últimas N horas/días de cambios en todas las
  entidades. Filtros por tipo y origen.
- **Por entidad**: seleccionás una entidad puntual y ves su historial
  completo.
"""

import streamlit as st

from src.database.connection import get_session, init_db
from src.database.models import (
    CarreraDB, DictadoDB, MateriaDB, SedeDB,
)
from src.ui.historial_widget import (
    render_feed_global,
    render_historial_entidad,
)
from sqlmodel import select

init_db()

st.set_page_config(page_title="📜 Historial", layout="wide")
st.title("📜 Historial de cambios")

st.caption(
    "Registro automático de los cambios hechos sobre el catálogo "
    "y la configuración (Materias, Carreras, Dictados, Sedes). "
    "Quedan trazados los cambios editoriales, las promociones a "
    "regla, los borrados manuales y las aceptaciones de extras "
    "del cronograma, junto con su origen."
)

_tabs = st.tabs(["🌐 Feed global", "🔎 Por entidad"])

with _tabs[0]:
    with st.container(border=True):
        st.markdown("**🔎 Filtros del feed**")
        _c1, _c2, _c3 = st.columns([1, 1, 3])
        with _c1:
            _days = st.number_input(
                "Días hacia atrás",
                min_value=1, max_value=365, value=30, step=1,
                key="feed_days",
                help=(
                    "Ventana temporal a mostrar: sólo se listan "
                    "los cambios de los últimos N días."
                ),
            )
        with _c2:
            _limit = st.number_input(
                "Máximo de eventos a mostrar",
                min_value=10, max_value=500, value=100, step=10,
                key="feed_limit",
                help=(
                    "Tope de eventos que se traen en la consulta. "
                    "Subilo si esperás ver muchos cambios en el "
                    "período."
                ),
            )
    render_feed_global(limit=int(_limit), days=int(_days), key_ns="feed")

with _tabs[1]:
    st.caption(
        "Elegí el tipo de entidad y la entidad concreta para ver "
        "toda su historia de cambios."
    )
    _tipo_labels = {
        "MateriaDB": "Materia",
        "CarreraDB": "Carrera",
        "DictadoDB": "Dictado",
        "SedeDB": "Sede",
    }
    _tipo = st.selectbox(
        "Tipo de entidad",
        options=list(_tipo_labels.keys()),
        format_func=lambda t: _tipo_labels.get(t, t),
        key="hist_ent_tipo",
    )

    # Cargar entidades disponibles del tipo seleccionado.
    with next(get_session()) as _s:
        if _tipo == "MateriaDB":
            _items = list(_s.exec(select(MateriaDB)).all())
            _opts = {f"{m.codigo} — {m.nombre}": m.codigo for m in _items}
        elif _tipo == "CarreraDB":
            _items = list(_s.exec(select(CarreraDB)).all())
            _opts = {f"{c.codigo} — {c.nombre}": c.codigo for c in _items}
        elif _tipo == "DictadoDB":
            _items = list(_s.exec(select(DictadoDB)).all())
            _opts = {
                f"{d.dictado_codigo} ({d.materia_codigo})": d.id
                for d in _items
            }
        else:  # SedeDB
            _items = list(_s.exec(select(SedeDB)).all())
            _opts = {s.nombre: s.id for s in _items}

    if not _opts:
        st.info(f"No hay entidades del tipo {_tipo_labels.get(_tipo, _tipo)}.")
    else:
        _sel_label = st.selectbox(
            "Seleccioná una entidad",
            options=list(_opts.keys()),
            key="hist_ent_id",
        )
        _sel_id = _opts[_sel_label]
        st.divider()
        render_historial_entidad(_tipo, _sel_id)
