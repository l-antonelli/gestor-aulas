"""El formulario del asignador sólo muestra parámetros que tienen efecto.

`lambda_intersede` (peso blando por cambiar de sede entre horarios
consecutivos) no está implementado en el modelo: el servicio lo acepta
pero no agrega ningún término al objetivo. Mostrarlo en la interfaz
confunde al usuario, así que el formulario no lo ofrece y la
configuración que arma siempre lo deja en 0.
"""

from __future__ import annotations

from streamlit.testing.v1 import AppTest


def _script(db_path: str) -> None:
    from datetime import date

    import streamlit as st
    from sqlmodel import Session, SQLModel, create_engine

    from src.database.models import CicloDB, PlanificacionCursadaDB
    from src.ui.asignacion_panel import _render_config_form

    engine = create_engine(f"sqlite:///{db_path}")
    SQLModel.metadata.create_all(engine)
    with Session(engine) as s:
        if s.get(CicloDB, "2026-1C") is None:
            s.add(CicloDB(id="2026-1C", anio=2026, numero=1,
                          fecha_inicio=date(2026, 3, 1), fecha_fin=date(2026, 7, 1)))
            s.add(PlanificacionCursadaDB(id="p1", nombre="Plan", ciclo_id="2026-1C"))
            s.commit()
        st.session_state["config"] = _render_config_form(s, "p1", "asig")


def test_el_formulario_no_ofrece_el_peso_de_intersede_no_implementado(tmp_path):
    at = AppTest.from_function(_script, args=(str(tmp_path / "db.sqlite"),), default_timeout=60)
    at.run()
    assert not at.exception
    etiquetas = [n.label for n in at.number_input]
    assert etiquetas, "el formulario debería tener parámetros numéricos"
    assert not any("intersede blando" in e.lower() for e in etiquetas)
