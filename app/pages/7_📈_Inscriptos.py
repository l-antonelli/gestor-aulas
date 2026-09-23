"""Visualizacion y edicion de datos historicos de inscriptos por materia.

El forecast se muestra como referencia (3 metodos superpuestos al grafico).
NO se persiste valor ni metodo desde aca: la eleccion del metodo vive en el
PlanificacionCursadaDB (default) y opcionalmente como override por materia
desde Planes -> Detalle.
"""

import streamlit as st
import pandas as pd
from pathlib import Path
from sqlmodel import select, col
from src.database.connection import get_session, init_db
from src.database.models import (
    InscripcionHistoricaDB, MateriaDB, PlanEstudioDB, CarreraDB,
)
from src.services.forecast_service import (
    METODO_LABELS,
    METODOS_DISPONIBLES,
    get_all_forecasts,
)
from src.services.inscripcion_service import (
    RegistroInscripcion,
    guardar_registros_materia,
)
from scripts.load_inscriptos import _normalize_code, _build_name_map

init_db()

st.set_page_config(page_title="Inscriptos", page_icon="📈", layout="wide")

# Toast diferido de la última acción de import (creado antes del
# rerun por el bloque de commit_import más abajo).
if "_insc_import_toast" in st.session_state:
    st.toast(
        st.session_state.pop("_insc_import_toast"),
        icon="✅",
    )

st.title("📈 Inscriptos históricos")
st.caption(
    "Cargá y visualizá la cantidad de inscriptos por materia y "
    "cuatrimestre a lo largo del tiempo. Sobre estos datos se "
    "calcula la proyección de inscriptos para el ciclo siguiente."
)


# =============================================================================
# Data loading
# =============================================================================
with next(get_session()) as _session:
    _all_inscripciones = _session.exec(
        select(InscripcionHistoricaDB)
        .order_by(
            col(InscripcionHistoricaDB.materia_codigo),
            col(InscripcionHistoricaDB.anio),
            col(InscripcionHistoricaDB.cuatrimestre),
        )
    ).all()
    _all_materias_full = list(_session.exec(select(MateriaDB)).all())
    _all_carreras = list(_session.exec(
        select(CarreraDB).order_by(col(CarreraDB.codigo))
    ).all())
    _all_pe = list(_session.exec(select(PlanEstudioDB)).all())

_mat_by_code = {m.codigo: m for m in _all_materias_full}
_mat_nombres = {m.codigo: m.nombre for m in _all_materias_full}
_mat_codes = set(_mat_nombres.keys())
_mat_options = [f"{m.codigo} - {m.nombre}" for m in _all_materias_full]

# Carrera y año por materia (puede haber multiples carreras por materia)
_carreras_por_materia: dict[str, set[str]] = {}
_anios_por_materia: dict[str, set[int]] = {}
_optativa_por_materia: dict[str, bool] = {}
for _pe in _all_pe:
    _carreras_por_materia.setdefault(_pe.materia_codigo, set()).add(
        _pe.carrera_codigo
    )
    if _pe.anio_plan is not None:
        _anios_por_materia.setdefault(_pe.materia_codigo, set()).add(
            _pe.anio_plan
        )
    if _pe.optativa:
        _optativa_por_materia[_pe.materia_codigo] = True
# Inicializar a False las que no aparecen marcadas optativa
for _mc in _mat_codes:
    _optativa_por_materia.setdefault(_mc, False)

_insc_by_mat: dict[str, list] = {}
for _i in _all_inscripciones:
    _insc_by_mat.setdefault(_i.materia_codigo, []).append(_i)

_mat_codes_with_data = set(_insc_by_mat.keys())
_mat_codes_without_data = sorted(_mat_codes - _mat_codes_with_data)

# Compute unmatched codes from Excel
_inscriptos_file = Path("data/input/inscriptos/final_df.xlsx")
_unmatched_codes: list[str] = []
_unmatched_agg: dict[str, pd.DataFrame] = {}
_nombre_insc: dict[str, str] = {}

if _inscriptos_file.exists():
    _df_raw = pd.read_excel(_inscriptos_file)
    _all_materias_tuples = [(m.codigo, m.nombre) for m in _all_materias_full]
    _r_by_name = _build_name_map(_all_materias_tuples, ["R-"])
    _ce_by_name = _build_name_map(_all_materias_tuples, ["CE"])
    _nombre_insc_series = _df_raw.drop_duplicates("codigo").set_index("codigo")["actividad"]
    _nombre_insc = _nombre_insc_series.to_dict()

    _all_insc_codes = set(_df_raw["codigo"].unique())
    _matched_insc: set[str] = set()
    for _c in _all_insc_codes:
        if _c in _mat_codes:
            _matched_insc.add(_c)
            continue
        _norm = _normalize_code(_c)
        if _norm and _norm in _mat_codes:
            _matched_insc.add(_c)
            continue
        _nom = str(_nombre_insc.get(_c, "")).strip().lower()
        if _c.startswith("T10") and _nom in _r_by_name:
            _matched_insc.add(_c)
        elif _c.startswith("CI24") and _nom in _ce_by_name:
            _matched_insc.add(_c)

    _unmatched_codes = sorted(_all_insc_codes - _matched_insc)

    _unmatched_df = _df_raw[_df_raw["codigo"].isin(_unmatched_codes)]
    for _uc in _unmatched_codes:
        _uc_df = (
            _unmatched_df[_unmatched_df["codigo"] == _uc]
            .groupby(["year", "period"])["cant._inscriptos"]
            .sum()
            .reset_index()
            .sort_values(["year", "period"])
        )
        _uc_df.columns = ["Año", "Cuatrimestre", "Inscriptos"]
        _unmatched_agg[_uc] = _uc_df


# =============================================================================
# Shared render function
# =============================================================================
def _render_materia_expander(
    code: str,
    nombre: str,
    records: list,
    cuatri_filter: str,
    key_prefix: str,
    anio_target: int,
    editable: bool = True,
):
    """Renderiza un expander con tabla editable + grafico de hist+forecast."""
    filtered_records = records
    if cuatri_filter != "Todos":
        filtered_records = [r for r in records if r.cuatrimestre == cuatri_filter]

    if not filtered_records:
        return

    total = sum(r.inscriptos for r in records)
    with st.expander(f"{code} — {nombre} ({total} inscriptos totales)"):
        rows = [
            {"Año": r.anio, "Cuatrimestre": r.cuatrimestre, "Inscriptos": r.inscriptos}
            for r in filtered_records
        ]
        df = pd.DataFrame(rows)

        c1, c2 = st.columns([1, 2])
        with c1:
            if editable:
                edited = st.data_editor(
                    df,
                    num_rows="dynamic",
                    use_container_width=True,
                    hide_index=True,
                    column_config={
                        "Año": st.column_config.NumberColumn(
                            "Año", min_value=2020, max_value=2035, step=1, format="%d",
                        ),
                        "Cuatrimestre": st.column_config.SelectboxColumn(
                            "Cuatrimestre", options=["1C", "2C", "Anual"], required=True,
                        ),
                        "Inscriptos": st.column_config.NumberColumn(
                            "Inscriptos", min_value=0, step=1,
                        ),
                    },
                    key=f"{key_prefix}_de_{code}",
                )

                _orig = df[["Año", "Cuatrimestre", "Inscriptos"]].reset_index(drop=True)
                _edit = edited[["Año", "Cuatrimestre", "Inscriptos"]].reset_index(drop=True)
                _changed = len(_orig) != len(_edit) or not _orig.equals(_edit)

                if _changed and st.button(
                    "Guardar", type="primary",
                    key=f"{key_prefix}_save_{code}",
                ):
                    _valid = edited.dropna(subset=["Año", "Cuatrimestre", "Inscriptos"])
                    _cuatris_visibles = (
                        {"1C", "2C", "Anual"} if cuatri_filter == "Todos"
                        else {cuatri_filter}
                    )
                    _registros = [
                        RegistroInscripcion(
                            anio=int(r["Año"]),
                            cuatrimestre=str(r["Cuatrimestre"]),
                            inscriptos=int(r["Inscriptos"]),
                        )
                        for _, r in _valid.iterrows()
                    ]
                    try:
                        with next(get_session()) as sess:
                            n_persistidas = guardar_registros_materia(
                                sess, code, _registros,
                                cuatris_visibles=_cuatris_visibles,
                            )
                    except ValueError as e:
                        st.error(f"No se pudo guardar: {e}")
                    else:
                        st.toast(
                            f"{code}: {n_persistidas} registro(s) guardado(s). "
                            f"Los cuatrimestres fuera del filtro quedaron intactos."
                        )
                        st.rerun()
            else:
                st.dataframe(df, hide_index=True, use_container_width=True)

        with c2:
            # =====================================================
            # Grafico: historico + forecast superpuesto
            # =====================================================
            _cuatris_para_grafico = (
                [cuatri_filter] if cuatri_filter != "Todos"
                else sorted({r.cuatrimestre for r in records})
            )

            # Build the merged DataFrame: una columna por (cuatri x serie)
            # Series:
            # - "{cuatri} histórico": valor historico
            # - "{cuatri} {metodo_label}": valor del forecast en anio_target
            chart_data: dict[int, dict[str, float]] = {}
            for _r in records:
                if _r.cuatrimestre not in _cuatris_para_grafico:
                    continue
                col_name = f"{_r.cuatrimestre} histórico"
                chart_data.setdefault(_r.anio, {})[col_name] = float(_r.inscriptos)

            # Forecasts for each cuatri
            for _cuatri in _cuatris_para_grafico:
                _serie = sorted(
                    [(r.anio, r.inscriptos) for r in records if r.cuatrimestre == _cuatri]
                )
                if len(_serie) < 1:
                    continue
                _all_fcs = get_all_forecasts(_serie)
                _last_anio = _serie[-1][0]
                _last_val = float(_serie[-1][1])
                # Para que la linea del forecast arranque en el ultimo punto historico
                # y termine en anio_target, agregamos puntos en ambos.
                for _m, _r in _all_fcs.items():
                    _label = f"{_cuatri} {METODO_LABELS.get(_m, _m)}"
                    chart_data.setdefault(_last_anio, {})[_label] = _last_val
                    chart_data.setdefault(int(anio_target), {})[_label] = _r.valor

            if not chart_data:
                st.caption("Sin datos para graficar.")
            else:
                _chart_df = pd.DataFrame.from_dict(chart_data, orient="index")
                _chart_df.index.name = "Año"
                _chart_df = _chart_df.sort_index()
                st.line_chart(_chart_df)

                # Métricas chiquitas debajo del gráfico con los valores forecast
                for _cuatri in _cuatris_para_grafico:
                    _serie = sorted(
                        [(r.anio, r.inscriptos) for r in records if r.cuatrimestre == _cuatri]
                    )
                    if not _serie:
                        continue
                    _all_fcs = get_all_forecasts(_serie)
                    if not _all_fcs:
                        continue
                    st.markdown(f"**{_cuatri}** → forecast {anio_target}:")
                    _mcols = st.columns(len(_all_fcs))
                    for _i, (_m, _r) in enumerate(_all_fcs.items()):
                        _params_str = ""
                        if "alpha" in _r.parametros and _r.parametros["alpha"] is not None:
                            _params_str = f" (α={_r.parametros['alpha']:.2f})"
                        elif "slope" in _r.parametros:
                            _params_str = f" (m={_r.parametros['slope']:.1f})"
                        elif "window" in _r.parametros:
                            _params_str = f" (w={_r.parametros['window']})"
                        _mcols[_i].metric(
                            f"{METODO_LABELS.get(_m, _m)}{_params_str}",
                            f"{_r.valor:.0f}",
                            help=f"Error cuadrático sobre datos históricos: {_r.in_sample_sse:.1f}",
                        )

        st.caption(
            "💡 El método de proyección que se aplica al armar la "
            "asignación se configura en **📊 Planes → Detalle → "
            "Método de forecast** (por defecto del plan y con "
            "excepciones por materia). Acá se muestran los 3 "
            "métodos superpuestos como referencia."
        )


# =============================================================================
# Import masivo desde Excel (Fase E1 del rediseño 2026-09-15)
# =============================================================================
with st.expander(
    "📥 Cargar masivo desde plantilla Excel", expanded=False,
):
    st.caption(
        "Descargá la plantilla, completala con los datos de "
        "inscriptos por (materia, año, cuatri), y subila para "
        "importar de una. La app muestra un preview antes de "
        "commitear, indicando qué filas son nuevas y cuáles pisan "
        "valores existentes."
    )

    _tpl_col, _upl_col = st.columns(2)

    with _tpl_col:
        st.markdown("**Paso 1 · Descargar plantilla**")
        from src.services.template_export_service import (
            generar_plantilla_inscriptos_excel,
            obtener_referencia_materias_activas,
        )
        _tpl_key = "insc_tpl_bytes"
        _tpl_err_key = "insc_tpl_err"
        if st.button(
            "🧮 Generar plantilla",
            key="insc_tpl_btn",
            help=(
                "Arma un Excel con los códigos del catálogo como "
                "dropdown y validaciones de cuatri, año e inscriptos."
            ),
        ):
            try:
                with next(get_session()) as _sess:
                    st.session_state[_tpl_key] = (
                        generar_plantilla_inscriptos_excel(_sess)
                    )
                st.session_state.pop(_tpl_err_key, None)
            except ValueError as _exc:
                st.session_state[_tpl_err_key] = str(_exc)
                st.session_state.pop(_tpl_key, None)

        if _tpl_err_key in st.session_state:
            st.error(st.session_state[_tpl_err_key])
        elif _tpl_key in st.session_state:
            st.download_button(
                "⬇️ Descargar plantilla_inscriptos.xlsx",
                data=st.session_state[_tpl_key],
                file_name="plantilla_inscriptos.xlsx",
                mime=(
                    "application/vnd.openxmlformats-officedocument"
                    ".spreadsheetml.sheet"
                ),
                key="insc_tpl_dl",
            )
            with next(get_session()) as _sess:
                _refs = obtener_referencia_materias_activas(_sess)
            st.caption(
                f"Plantilla lista con **{len(_refs)}** códigos "
                "válidos en el dropdown."
            )

    with _upl_col:
        st.markdown("**Paso 2 · Subir archivo completado**")
        from src.services.inscripcion_import_service import (
            commit_import as _insc_commit_import,
            preview_import as _insc_preview_import,
        )
        _upl_file = st.file_uploader(
            "Archivo CSV o Excel con inscriptos",
            type=["csv", "xlsx", "xls"],
            key="insc_upload",
        )

        # Selector de hoja para Excel con múltiples hojas visibles
        # (por ejemplo un archivo institucional con "1C" y "2C" como
        # hojas separadas). Aparece sólo si hay más de una hoja
        # candidata; con 1 hoja se fija automáticamente.
        _insc_sheet_choice: str | None = None
        if _upl_file is not None:
            from src.services.horario_file_parser import hoja_default
            from src.services.inscripcion_import_service import (
                HOJA_PREFERIDA as _INSC_HOJA_PREF,
                list_inscriptos_sheets,
            )
            # Cache por archivo (fix auditoría H2-perf, 2026-09-23).
            _insc_fid = (
                getattr(_upl_file, "file_id", None) or _upl_file.name
            )
            _insc_cache = st.session_state.get("_insc_sheets_cache")
            if not _insc_cache or _insc_cache[0] != _insc_fid:
                _insc_cache = (
                    _insc_fid, list_inscriptos_sheets(_upl_file),
                )
                st.session_state["_insc_sheets_cache"] = _insc_cache
            _insc_sheets = _insc_cache[1]
            if len(_insc_sheets) > 1:
                _insc_sheet_choice = st.selectbox(
                    "Hoja del Excel a importar",
                    options=_insc_sheets,
                    # Fix auditoría H2 (2026-09-23): arrancar en la
                    # hoja preferida del parser ("Inscriptos"), no en
                    # la primera del workbook.
                    index=hoja_default(_insc_sheets, _INSC_HOJA_PREF),
                    key="insc_upload_sheet",
                    help=(
                        "El archivo tiene varias hojas. Elegí cuál "
                        "querés previsualizar e importar."
                    ),
                )
            elif len(_insc_sheets) == 1:
                _insc_sheet_choice = _insc_sheets[0]

        _pv_key = "insc_import_preview"
        _c_prev, _c_reset = st.columns([3, 1])
        with _c_prev:
            if st.button(
                "🔍 Ver preview",
                disabled=not _upl_file,
                type="primary",
                width="stretch",
                key="insc_import_prev_btn",
            ):
                with next(get_session()) as _sess:
                    st.session_state[_pv_key] = _insc_preview_import(
                        _sess, _upl_file,
                        sheet_name=_insc_sheet_choice,
                    )
        with _c_reset:
            if _pv_key in st.session_state:
                if st.button(
                    "🗑",
                    help="Cancelar preview",
                    key="insc_import_reset_btn",
                    width="stretch",
                ):
                    st.session_state.pop(_pv_key, None)
                    st.rerun()

    # Render del preview (fuera de las columnas para tener todo el ancho).
    if _pv_key in st.session_state:
        _pv = st.session_state[_pv_key]
        st.divider()
        if _pv.tiene_errores_bloqueantes:
            st.error("❌ El archivo tiene errores bloqueantes.")
            for _err in _pv.parse_errors:
                st.error(_err)
        else:
            _m1, _m2, _m3, _m4 = st.columns(4)
            _m1.metric("Filas OK", len(_pv.filas_ok))
            _m2.metric(
                "Nuevas", _pv.n_nuevos,
                help="Filas que agregan un registro nuevo a la DB.",
            )
            _m3.metric(
                "Pisan valor", _pv.n_pisan,
                help=(
                    "Filas cuyo (materia, año, cuatri) ya existía "
                    "en la DB y el valor difiere — se sobrescribe."
                ),
            )
            _m4.metric(
                "Con errores", len(_pv.filas_error),
                delta=(
                    "⚠️ se ignoran" if _pv.filas_error else None
                ),
                delta_color="inverse",
            )
            if _pv.n_iguales:
                st.caption(
                    f"Además hay {_pv.n_iguales} filas con valor "
                    "idéntico al previo — no cambian nada."
                )

            if _pv.warnings:
                with st.expander(
                    f"⚠️ Avisos ({len(_pv.warnings)})", expanded=False,
                ):
                    for _w in _pv.warnings:
                        st.warning(_w)

            if _pv.filas_error:
                with st.expander(
                    f"🚫 Filas con errores ({len(_pv.filas_error)})",
                    expanded=True,
                ):
                    for _fila_num, _msg in _pv.filas_error:
                        st.warning(f"Fila {_fila_num}: {_msg}")

            # Tabla de filas OK para inspección.
            if _pv.filas_ok:
                _df_pv = pd.DataFrame([
                    {
                        "Fila": f.fila_num,
                        "Materia": f"{f.materia_codigo} — {f.materia_nombre}",
                        "Año": f.anio,
                        "Cuatri": f.cuatrimestre,
                        "Valor previo": (
                            "(nuevo)" if f.valor_previo is None
                            else str(f.valor_previo)
                        ),
                        "Valor nuevo": f.inscriptos,
                        "Cambio": (
                            "🆕 nuevo" if f.es_nuevo
                            else ("✏️ actualiza" if f.cambia_valor else "= igual")
                        ),
                    }
                    for f in _pv.filas_ok
                ])
                st.dataframe(
                    _df_pv, use_container_width=True, hide_index=True,
                )

            if st.button(
                "✅ Confirmar importación",
                type="primary",
                width="stretch",
                key="insc_import_confirm_btn",
            ):
                with next(get_session()) as _sess:
                    _res = _insc_commit_import(_sess, _pv)
                # Toast diferido — el rerun barre `st.success` porque
                # se renderea antes del reload. Uso la misma técnica
                # que el importer de cronograma (`_crono_import_toast`).
                st.session_state["_insc_import_toast"] = (
                    f"✅ Se insertaron {_res.filas_creadas} y se "
                    f"actualizaron {_res.filas_actualizadas} "
                    f"registro(s) de inscriptos. "
                    f"{_res.filas_sin_cambio} quedaron sin cambio."
                )
                st.session_state.pop(_pv_key, None)
                st.session_state.pop("insc_upload", None)
                st.rerun()


# =============================================================================
# Filtros + visibility toggles
# =============================================================================
with st.container(border=True):
    st.markdown("**🔎 Filtros de la lista de materias**")
    st.caption(
        "Acotá la lista según lo que quieras revisar. Los filtros "
        "se combinan (AND); las materias tienen que cumplir todos."
    )
    fc1, fc2, fc3 = st.columns([3, 2, 2])
    with fc1:
        _search = st.text_input(
            "🔎 Buscar por código o nombre",
            key="insc_search",
            placeholder="Ej: algebra, F0301...",
        )
    with fc2:
        _cuatri_filter = st.selectbox(
            "Cuatrimestre a mostrar",
            ["Todos", "1C", "2C", "Anual"],
            key="insc_cuatri_filter",
            help=(
                "Filtra qué registros se muestran en las tablas. "
                "'Todos' incluye Anual. Con 'Anual' se muestran sólo "
                "los registros de materias que se cursan todo el año."
            ),
        )
    with fc3:
        _anio_target_global = st.number_input(
            "Año a proyectar",
            min_value=2020, max_value=2040, value=2026, step=1,
            key="insc_anio_target",
            help=(
                "Año hacia el que se extienden las líneas de "
                "forecast en los gráficos."
            ),
        )

    fc4, fc5, fc6, fc7 = st.columns(4)
    with fc4:
        _carrera_options = [c.codigo for c in _all_carreras]
        _carrera_sel = st.multiselect(
            "Carrera",
            options=_carrera_options,
            default=_carrera_options,
            format_func=lambda c: f"{c} — {next((cc.nombre for cc in _all_carreras if cc.codigo == c), c)}",
            key="insc_carrera",
        )
    with fc5:
        _all_anios_plan = sorted({
            a for s in _anios_por_materia.values() for a in s
        })
        _anio_plan_sel = st.multiselect(
            "Año dentro del plan",
            options=_all_anios_plan,
            default=_all_anios_plan,
            format_func=lambda a: f"{a}°",
            key="insc_anio_plan",
        )
    with fc6:
        _opt_filt = st.selectbox(
            "Optativas",
            options=["Incluir", "Solo", "Excluir"],
            index=0,
            key="insc_opt_filt",
            help=(
                "**Incluir**: no filtra por optativas.\n"
                "**Solo**: sólo optativas.\n"
                "**Excluir**: sólo obligatorias."
            ),
        )
    with fc7:
        _periodo_sel = st.multiselect(
            "Período de la materia",
            options=["cuatrimestral", "anual"],
            default=["cuatrimestral", "anual"],
            key="insc_periodo",
        )

    fc8, _ = st.columns([2, 6])
    with fc8:
        # Drift task #347 (2026-09-22): unificamos el label a "Virtual"
        # (consistente con la columna del export y con la plantilla).
        # Semánticamente sigue siendo un filtro binario Presencial/Virtual.
        _modal_sel = st.multiselect(
            "Virtual",
            options=["Presencial", "Virtual"],
            default=["Presencial", "Virtual"],
            key="insc_modal",
        )

with st.container(border=True):
    st.markdown("**👁 Secciones a mostrar**")
    st.caption(
        "Elegí qué grupos de materias querés ver debajo. Las "
        "**sin matchear** son códigos del Excel de inscriptos "
        "que no encontraron materia en la base."
    )
    tc1, tc2, tc3 = st.columns(3)
    with tc1:
        _show_with_data = st.checkbox(
            f"Con datos ({len(_mat_codes_with_data)})",
            value=True,
            key="insc_show_with",
        )
    with tc2:
        _show_without_data = st.checkbox(
            f"Sin datos ({len(_mat_codes_without_data)})",
            value=False,
            key="insc_show_without",
        )
    with tc3:
        _show_unmatched = st.checkbox(
            f"Sin matchear ({len(_unmatched_codes)})",
            value=False,
            key="insc_show_unmatched",
        )


def _materia_pasa_filtros(code: str) -> bool:
    """True si la materia pasa todos los filtros activos."""
    nombre = _mat_nombres.get(code, "")
    # Search
    if _search:
        s = _search.lower()
        if s not in code.lower() and s not in nombre.lower():
            return False
    # Carrera
    _carreras_mat = _carreras_por_materia.get(code, set())
    if _carrera_sel and not (_carreras_mat & set(_carrera_sel)):
        # Si la materia no está en ninguna carrera del plan, queda visible
        # solo si NO seleccionaste ninguna carrera (lo cual no pasa por default)
        if _carreras_mat:  # tiene carreras pero ninguna está seleccionada
            return False
        # sin carreras (huérfana en plan): solo se muestra si el filtro
        # incluye TODAS las carreras (es un proxy de "sin filtro").
        if len(_carrera_sel) < len(_carrera_options):
            return False
    # Año del plan
    _anios_mat = _anios_por_materia.get(code, set())
    if _anio_plan_sel:
        if _anios_mat and not (_anios_mat & set(_anio_plan_sel)):
            return False
        if not _anios_mat and len(_anio_plan_sel) < len(_all_anios_plan):
            return False
    # Optativa
    _es_opt = _optativa_por_materia.get(code, False)
    if _opt_filt == "Solo" and not _es_opt:
        return False
    if _opt_filt == "Excluir" and _es_opt:
        return False
    # Período
    _mat = _mat_by_code.get(code)
    if _mat is not None:
        if _mat.periodo not in _periodo_sel:
            return False
        # Modalidad
        _is_virt = _mat.virtual
        if _is_virt and "Virtual" not in _modal_sel:
            return False
        if not _is_virt and "Presencial" not in _modal_sel:
            return False
    return True


def _paginator(total: int, key_prefix: str) -> tuple[int, int]:
    """Renderiza un paginador y devuelve (start, end) para slicing."""
    pc1, pc2, pc3, pc4, pc5 = st.columns([1.5, 1, 1, 1, 3])
    with pc1:
        page_size = st.selectbox(
            "Mostrar",
            options=[10, 25, 50, 100],
            index=1,
            key=f"{key_prefix}_page_size",
            label_visibility="collapsed",
        )
    n_pages = max(1, (total + page_size - 1) // page_size)
    page_key = f"{key_prefix}_page"
    if page_key not in st.session_state:
        st.session_state[page_key] = 1
    # Clamp page si cambió el filtro
    st.session_state[page_key] = max(1, min(st.session_state[page_key], n_pages))
    page = st.session_state[page_key]
    with pc2:
        if st.button("«", key=f"{key_prefix}_first", disabled=page == 1):
            st.session_state[page_key] = 1
            st.rerun()
    with pc3:
        if st.button("‹", key=f"{key_prefix}_prev", disabled=page == 1):
            st.session_state[page_key] = page - 1
            st.rerun()
    with pc4:
        if st.button("›", key=f"{key_prefix}_next", disabled=page >= n_pages):
            st.session_state[page_key] = page + 1
            st.rerun()
    with pc5:
        st.caption(
            f"Página **{page}** de {n_pages} — "
            f"{total} materia(s) total"
        )
    start = (page - 1) * page_size
    end = start + page_size
    return start, end


# =============================================================================
# Section 1: Materias con datos
# =============================================================================
if _show_with_data:
    _display_with = [
        c for c in sorted(_mat_codes_with_data)
        if _materia_pasa_filtros(c)
    ]

    st.divider()
    st.markdown(f"### 📊 Materias con datos ({len(_display_with)})")
    st.caption(
        "Materias que ya tienen registros de inscriptos históricos "
        "cargados. Podés editar la serie de valores en cualquier "
        "momento."
    )

    if not _display_with:
        st.caption("No hay materias que coincidan con los filtros.")
    else:
        _start, _end = _paginator(len(_display_with), "wd")
        for _code in _display_with[_start:_end]:
            _render_materia_expander(
                _code, _mat_nombres.get(_code, "?"),
                _insc_by_mat.get(_code, []),
                _cuatri_filter,
                key_prefix="wd",
                anio_target=int(_anio_target_global),
            )


# =============================================================================
# Section 2: Materias sin datos
# =============================================================================
if _show_without_data:
    _display_without = [
        c for c in _mat_codes_without_data
        if _materia_pasa_filtros(c)
    ]

    st.divider()
    st.markdown(f"### 📭 Materias sin datos de inscriptos ({len(_display_without)})")
    st.caption(
        "Materias registradas en el sistema que todavía no tienen "
        "ningún inscripto histórico cargado. Podés agregar los "
        "datos a mano acá."
    )

    if not _display_without:
        st.caption("No hay materias que coincidan con los filtros.")
    else:
        _start, _end = _paginator(len(_display_without), "wod")
        for _code in _display_without[_start:_end]:
            _nombre = _mat_nombres.get(_code, "?")
            with st.expander(f"📭 {_code} — {_nombre} (sin datos)"):
                _empty_df = pd.DataFrame(columns=["Año", "Cuatrimestre", "Inscriptos"])
                _empty_df = _empty_df.astype({"Año": int, "Inscriptos": int})

                edited = st.data_editor(
                    _empty_df,
                    num_rows="dynamic",
                    use_container_width=True,
                    hide_index=True,
                    column_config={
                        "Año": st.column_config.NumberColumn(
                            "Año", min_value=2020, max_value=2035, step=1, format="%d",
                        ),
                        "Cuatrimestre": st.column_config.SelectboxColumn(
                            "Cuatrimestre", options=["1C", "2C", "Anual"], required=True,
                        ),
                        "Inscriptos": st.column_config.NumberColumn(
                            "Inscriptos", min_value=0, step=1,
                        ),
                    },
                    key=f"wod_de_{_code}",
                )

                if len(edited) > 0 and st.button(
                    "Guardar", type="primary", key=f"wod_save_{_code}",
                ):
                    _valid = edited.dropna(subset=["Año", "Cuatrimestre", "Inscriptos"])
                    if not _valid.empty:
                        # Bugfix (2026-09-22, task #345): usar
                        # `guardar_registros_materia` en vez de
                        # `session.add` directo. Antes, si el usuario
                        # tipeaba dos filas con la misma PK
                        # (materia, año, cuatri) — o si por error
                        # apretaba Guardar dos veces —, saltaba
                        # `IntegrityError` sin captura y quedaba la
                        # sesión inutilizable. El helper deduplica
                        # (última fila gana) y respeta `cuatris_visibles`.
                        _cuatris_visibles = (
                            {"1C", "2C", "Anual"} if _cuatri_filter == "Todos"
                            else {_cuatri_filter}
                        )
                        _registros = [
                            RegistroInscripcion(
                                anio=int(r["Año"]),
                                cuatrimestre=str(r["Cuatrimestre"]),
                                inscriptos=int(r["Inscriptos"]),
                            )
                            for _, r in _valid.iterrows()
                        ]
                        try:
                            with next(get_session()) as sess:
                                n_persistidas = guardar_registros_materia(
                                    sess, _code, _registros,
                                    cuatris_visibles=_cuatris_visibles,
                                )
                        except ValueError as e:
                            st.error(f"No se pudo guardar: {e}")
                        else:
                            st.toast(
                                f"{_code}: {n_persistidas} registro(s) creado(s)."
                            )
                            st.rerun()


# =============================================================================
# Section 3: Sin matchear
# =============================================================================
if _show_unmatched:
    st.divider()
    st.markdown(f"### ⚠️ Sin matchear ({len(_unmatched_codes)})")
    st.caption(
        "Códigos que vienen en el Excel de inscriptos pero no "
        "pudieron matchearse con ninguna materia del sistema. "
        "Para asociarlos, elegí la materia destino y confirmá."
    )

    if not _unmatched_codes:
        st.success("Todos los códigos del Excel tienen match en el sistema.")
    else:
        # Aca el filtro busca por codigo o nombre del codigo unmatch
        _display_unmatched = [
            c for c in _unmatched_codes
            if not _search
            or _search.lower() in c.lower()
            or _search.lower() in str(_nombre_insc.get(c, "")).lower()
        ]
        _display_unmatched = sorted(
            _display_unmatched,
            key=lambda c: _unmatched_agg[c]["Inscriptos"].sum(),
            reverse=True,
        )

        if not _display_unmatched:
            st.caption("Sin coincidencias.")
        else:
            _start, _end = _paginator(len(_display_unmatched), "unm")
            for _uc in _display_unmatched[_start:_end]:
                _uc_nombre = str(_nombre_insc.get(_uc, "?"))
                _uc_data = _unmatched_agg[_uc]
                _uc_total = int(_uc_data["Inscriptos"].sum())

                with st.expander(f"⚠️ {_uc} — {_uc_nombre} ({_uc_total} inscriptos totales)"):
                    uc1, uc2 = st.columns([1, 2])
                    with uc1:
                        st.dataframe(_uc_data, hide_index=True, use_container_width=True)
                    with uc2:
                        if _cuatri_filter != "Todos":
                            _filt = _uc_data[_uc_data["Cuatrimestre"] == _cuatri_filter]
                            if not _filt.empty:
                                st.line_chart(_filt.set_index("Año")[["Inscriptos"]])
                        else:
                            _piv = _uc_data.pivot_table(
                                index="Año", columns="Cuatrimestre",
                                values="Inscriptos", aggfunc="sum",
                            )
                            st.line_chart(_piv)

                    st.markdown("---")
                    st.markdown("**Asociar a materia existente:**")
                    ac1, ac2 = st.columns([3, 1])
                    with ac1:
                        _dest = st.selectbox(
                            "Materia destino",
                            options=["(no asociar)"] + _mat_options,
                            key=f"unm_dest_{_uc}",
                        )
                    with ac2:
                        if _dest != "(no asociar)" and st.button(
                            "Asociar", type="primary", key=f"unm_assign_{_uc}",
                        ):
                            _dest_code = _dest.split(" - ")[0]
                            from datetime import datetime as _dt
                            from src.services.inscripcion_import_service import (
                                registrar_alias as _reg_alias,
                            )
                            _now = _dt.utcnow()
                            with next(get_session()) as sess:
                                # Bugfix (2026-09-22, task #343):
                                # antes se hacía `existing.inscriptos
                                # += _insc`, con lo cual un doble tap
                                # en "Asociar" duplicaba el valor.
                                # Ahora se sobrescribe (semántica
                                # consistente con el importer y con
                                # `guardar_registros_materia`).
                                # Registrar el alias PRIMERO además
                                # hace idempotente el segundo tap: al
                                # rerun el código ya no aparece en
                                # "Sin matchear".
                                _reg_alias(
                                    sess, _uc, _dest_code,
                                    origen="manual",
                                    nota=(
                                        f"Match manual desde UI el "
                                        f"{_now:%Y-%m-%d}"
                                    ),
                                )
                                for _, r in _uc_data.iterrows():
                                    _anio = int(r["Año"])
                                    _cuatri = str(r["Cuatrimestre"])
                                    _insc = int(r["Inscriptos"])
                                    existing = sess.get(
                                        InscripcionHistoricaDB,
                                        (_dest_code, _anio, _cuatri),
                                    )
                                    if existing:
                                        existing.inscriptos = _insc
                                        existing.updated_at = _now
                                        existing.origen = "override"
                                        sess.add(existing)
                                    else:
                                        sess.add(InscripcionHistoricaDB(
                                            materia_codigo=_dest_code,
                                            anio=_anio,
                                            cuatrimestre=_cuatri,
                                            inscriptos=_insc,
                                            updated_at=_now,
                                            origen="override",
                                        ))
                                sess.commit()
                            st.toast(
                                f"Asociado: {_uc} → {_dest_code}. "
                                "Alias guardado — no volverá a aparecer."
                            )
                            st.rerun()


if not _show_with_data and not _show_without_data and not _show_unmatched:
    st.info("Elegí al menos una sección para mostrar.")
