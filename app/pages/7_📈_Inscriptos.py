"""Visualizacion y edicion de datos historicos de inscriptos por materia."""

import streamlit as st
import pandas as pd
from pathlib import Path
from sqlmodel import select, col, delete
from src.database.connection import get_session, init_db
from src.database.models import InscripcionHistoricaDB, MateriaDB
from src.services.forecast_service import (
    get_or_compute_forecasts,
    get_persisted_forecast,
    persist_forecast,
    delete_persisted_forecast,
)
from scripts.load_inscriptos import _normalize_code, _build_name_map

init_db()

st.set_page_config(page_title="Inscriptos Historicos", page_icon="📈", layout="wide")
st.title("📈 Inscriptos Historicos")


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
    _all_materias = _session.exec(
        select(MateriaDB.codigo, MateriaDB.nombre)
        .order_by(col(MateriaDB.codigo))
    ).all()

_mat_nombres = {cod: nom for cod, nom in _all_materias}
_mat_codes = set(_mat_nombres.keys())
_mat_options = [f"{cod} - {nom}" for cod, nom in _all_materias]

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
    _r_by_name = _build_name_map(list(_all_materias), ["R-"])
    _ce_by_name = _build_name_map(list(_all_materias), ["CE"])
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
    editable: bool = True,
):
    """Renderiza un expander con tabla editable + grafico para una materia."""
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
                    with next(get_session()) as sess:
                        sess.exec(
                            delete(InscripcionHistoricaDB)
                            .where(InscripcionHistoricaDB.materia_codigo == code)
                        )
                        _valid = edited.dropna(subset=["Año", "Cuatrimestre", "Inscriptos"])
                        for _, r in _valid.iterrows():
                            sess.add(InscripcionHistoricaDB(
                                materia_codigo=code,
                                anio=int(r["Año"]),
                                cuatrimestre=str(r["Cuatrimestre"]),
                                inscriptos=int(r["Inscriptos"]),
                            ))
                        sess.commit()
                    st.toast(f"{code}: {len(_valid)} registros guardados.")
                    st.rerun()
            else:
                st.dataframe(df, hide_index=True, use_container_width=True)

        with c2:
            if len(df) < 2:
                st.caption("Se necesitan al menos 2 registros para graficar.")
            elif cuatri_filter != "Todos":
                st.line_chart(df.set_index("Año")[["Inscriptos"]])
            else:
                pivot = df.pivot_table(
                    index="Año", columns="Cuatrimestre",
                    values="Inscriptos", aggfunc="sum",
                )
                st.line_chart(pivot)

        # =============================================================
        # Forecast: por (materia, cuatri)
        # =============================================================
        st.divider()
        st.markdown("**🔮 Forecast de inscriptos**")
        st.caption(
            "Estimación del próximo punto de la serie. Se calcula por "
            "(materia, cuatri) para capturar la diferencia 1C/2C cuando "
            "aplique. El método elegido queda persistido y se usa como "
            "input del LP de asignación de aulas."
        )

        # Cuatris disponibles para esta materia (segun los registros)
        _cuatris_disponibles = sorted({r.cuatrimestre for r in records})
        if not _cuatris_disponibles:
            st.caption("Sin registros para forecast.")
            return

        _max_anio_hist = max(r.anio for r in records)
        _anio_target = st.number_input(
            "Año target",
            min_value=2020, max_value=2040,
            value=_max_anio_hist + 1, step=1,
            key=f"{key_prefix}_fc_anio_{code}",
            help="Año para el cual se proyecta el valor.",
        )

        for _cuatri in _cuatris_disponibles:
            with next(get_session()) as _fc_sess:
                _results = get_or_compute_forecasts(
                    _fc_sess, code, _cuatri, _anio_target,
                )
                _persisted = get_persisted_forecast(
                    _fc_sess, code, _cuatri, _anio_target,
                )

            if not _results:
                continue

            st.markdown(f"**{_cuatri}**")
            _cols = st.columns([2, 1, 1, 1])
            _labels_method = {
                "media_movil": "Media móvil",
                "drift": "Drift (lineal)",
                "ses": "SES (α auto)",
            }

            # Métricas: una columna por método disponible
            for _i, (_m, _r) in enumerate(_results.items()):
                _col = _cols[min(_i + 1, 3)] if _i + 1 < len(_cols) else _cols[-1]
                _params_str = ""
                if "alpha" in _r.parametros and _r.parametros["alpha"] is not None:
                    _params_str = f" α={_r.parametros['alpha']:.2f}"
                elif "slope" in _r.parametros:
                    _params_str = f" m={_r.parametros['slope']:.1f}"
                elif "window" in _r.parametros:
                    _params_str = f" w={_r.parametros['window']}"
                _col.metric(
                    f"{_labels_method.get(_m, _m)}{_params_str}",
                    f"{_r.valor:.0f}",
                    help=f"SSE in-sample: {_r.in_sample_sse:.1f}",
                )

            # Selector de metodo elegido + persistencia
            _method_options = list(_results.keys())
            _opts_labels = [_labels_method.get(m, m) for m in _method_options]
            _opts_labels = [None] + _opts_labels  # None = no elegido
            _method_keys = [None] + _method_options

            _curr_idx = 0
            if _persisted is not None:
                try:
                    _curr_idx = _method_keys.index(_persisted.metodo)
                except ValueError:
                    _curr_idx = 0

            _ml_c1, _ml_c2 = st.columns([2, 2])
            with _ml_c1:
                _chosen = st.selectbox(
                    f"Método elegido ({_cuatri})",
                    options=list(range(len(_method_keys))),
                    format_func=lambda i: _opts_labels[i] or "— ninguno —",
                    index=_curr_idx,
                    key=f"{key_prefix}_fc_method_{code}_{_cuatri}",
                    label_visibility="collapsed",
                )
            with _ml_c2:
                _chosen_method = _method_keys[_chosen]
                if _persisted is not None:
                    st.caption(
                        f"Persistido: **{_labels_method.get(_persisted.metodo, _persisted.metodo)}** "
                        f"= {_persisted.valor:.0f} "
                        f"({_persisted.fecha_calculo.strftime('%Y-%m-%d')})"
                    )
                else:
                    st.caption("Sin método persistido.")

            # Aplicar cambio de selección
            _persisted_method = _persisted.metodo if _persisted else None
            if _chosen_method != _persisted_method:
                _action_col = st.empty()
                with _action_col:
                    if _chosen_method is None:
                        if st.button(
                            "Eliminar persistido",
                            key=f"{key_prefix}_fc_del_{code}_{_cuatri}",
                        ):
                            with next(get_session()) as _save_s:
                                delete_persisted_forecast(
                                    _save_s, code, _cuatri, _anio_target,
                                )
                            st.toast(f"{code} {_cuatri}: forecast eliminado.")
                            st.rerun()
                    else:
                        if st.button(
                            f"Guardar {_labels_method.get(_chosen_method, _chosen_method)}",
                            type="primary",
                            key=f"{key_prefix}_fc_save_{code}_{_cuatri}",
                        ):
                            with next(get_session()) as _save_s:
                                persist_forecast(
                                    _save_s, code, _cuatri,
                                    int(_anio_target), _chosen_method,
                                    _results[_chosen_method],
                                )
                            st.toast(
                                f"{code} {_cuatri}: forecast persistido "
                                f"({_results[_chosen_method].valor:.0f})."
                            )
                            st.rerun()


# =============================================================================
# Filters + visibility toggles
# =============================================================================
fc1, fc2 = st.columns(2)
with fc1:
    _search = st.text_input("Buscar materia (codigo o nombre)", key="insc_search")
with fc2:
    _cuatri_filter = st.selectbox(
        "Cuatrimestre", ["Todos", "1C", "2C"], key="insc_cuatri_filter",
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


def _matches_search(code: str, nombre: str) -> bool:
    if not _search:
        return True
    s = _search.lower()
    return s in code.lower() or s in nombre.lower()


# =============================================================================
# Section 1: Materias con datos
# =============================================================================
if _show_with_data:
    _display_with = [
        c for c in sorted(_mat_codes_with_data)
        if _matches_search(c, _mat_nombres.get(c, ""))
    ]

    st.markdown(f"### Materias con datos ({len(_display_with)})")

    if not _display_with:
        st.info("No hay materias que coincidan con la busqueda.")
    else:
        for _code in _display_with[:50]:
            _render_materia_expander(
                _code, _mat_nombres.get(_code, "?"),
                _insc_by_mat.get(_code, []),
                _cuatri_filter, key_prefix="wd",
            )
        if len(_display_with) > 50:
            st.info(
                f"Mostrando primeras 50 de {len(_display_with)} materias. "
                "Usa el filtro para acotar."
            )

# =============================================================================
# Section 2: Materias sin datos
# =============================================================================
if _show_without_data:
    _display_without = [
        c for c in _mat_codes_without_data
        if _matches_search(c, _mat_nombres.get(c, ""))
    ]

    st.divider()
    st.markdown(f"### Materias sin datos de inscriptos ({len(_display_without)})")
    st.caption(
        "Materias en la DB que no tienen ningun registro de inscriptos. "
        "Podes agregar datos manualmente desde aca."
    )

    if not _display_without:
        st.info("No hay materias que coincidan con la busqueda.")
    else:
        for _code in _display_without[:50]:
            _nombre = _mat_nombres.get(_code, "?")
            # Create a dummy empty record list so the editor starts empty
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
                        with next(get_session()) as sess:
                            for _, r in _valid.iterrows():
                                sess.add(InscripcionHistoricaDB(
                                    materia_codigo=_code,
                                    anio=int(r["Año"]),
                                    cuatrimestre=str(r["Cuatrimestre"]),
                                    inscriptos=int(r["Inscriptos"]),
                                ))
                            sess.commit()
                        st.toast(f"{_code}: {len(_valid)} registros creados.")
                        st.rerun()

        if len(_display_without) > 50:
            st.info(
                f"Mostrando primeras 50 de {len(_display_without)}. "
                "Usa el filtro para acotar."
            )

# =============================================================================
# Section 3: Sin matchear
# =============================================================================
if _show_unmatched:
    st.divider()
    st.markdown(f"### Sin matchear ({len(_unmatched_codes)})")
    st.caption(
        "Codigos del Excel de inscriptos que no pudieron asociarse a ninguna materia "
        "de la DB. Para asociar, selecciona la materia destino y confirma."
    )

    if not _unmatched_codes:
        st.success("Todos los codigos del Excel tienen match en la DB.")
    else:
        _display_unmatched = [
            c for c in _unmatched_codes
            if _matches_search(c, _nombre_insc.get(c, ""))
        ]
        # Sort by total inscriptos desc
        _display_unmatched = sorted(
            _display_unmatched,
            key=lambda c: _unmatched_agg[c]["Inscriptos"].sum(),
            reverse=True,
        )

        st.markdown(f"**{len(_display_unmatched)} codigos** sin asociar.")

        for _uc in _display_unmatched[:50]:
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
                        with next(get_session()) as sess:
                            for _, r in _uc_data.iterrows():
                                _anio = int(r["Año"])
                                _cuatri = str(r["Cuatrimestre"])
                                _insc = int(r["Inscriptos"])
                                existing = sess.get(
                                    InscripcionHistoricaDB,
                                    (_dest_code, _anio, _cuatri),
                                )
                                if existing:
                                    existing.inscriptos += _insc
                                    sess.add(existing)
                                else:
                                    sess.add(InscripcionHistoricaDB(
                                        materia_codigo=_dest_code,
                                        anio=_anio,
                                        cuatrimestre=_cuatri,
                                        inscriptos=_insc,
                                    ))
                            sess.commit()
                        st.toast(
                            f"{_uc} ({_uc_nombre}) asociado a {_dest_code}. "
                            f"{len(_uc_data)} registros cargados."
                        )
                        st.rerun()

        if len(_display_unmatched) > 50:
            st.info(
                f"Mostrando primeros 50 de {len(_display_unmatched)}. "
                "Usa el filtro para acotar."
            )

if not _show_with_data and not _show_without_data and not _show_unmatched:
    st.info("Selecciona al menos una categoria para mostrar.")
