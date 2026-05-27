"""Tests para forecast_service."""

import pytest
import uuid
from datetime import date
from sqlalchemy.pool import StaticPool
from sqlmodel import Session, SQLModel, create_engine

from src.database.models import (
    CicloDB,
    InscripcionHistoricaDB,
    MateriaDB,
    MateriaForecastConfigDB,
    PlanificacionCursadaDB,
)
from src.services.forecast_service import (
    compute_forecast,
    forecast_drift,
    forecast_media_movil,
    forecast_ses,
    get_all_forecasts,
    get_forecast_for_materia,
    get_metodo_override,
    get_serie,
    resolve_metodo,
    set_metodo_override,
)


# =============================================================================
# Fixtures
# =============================================================================

@pytest.fixture(name="engine")
def engine_fixture():
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    SQLModel.metadata.create_all(engine)
    return engine


@pytest.fixture(name="session")
def session_fixture(engine):
    with Session(engine) as session:
        yield session


@pytest.fixture
def materia(session):
    m = MateriaDB(codigo="MAT101", nombre="Calculo I", periodo="cuatrimestral")
    session.add(m)
    session.commit()
    return m


@pytest.fixture
def serie_3_anios(session, materia):
    for anio, valor in [(2022, 100), (2023, 110), (2024, 120)]:
        session.add(InscripcionHistoricaDB(
            materia_codigo="MAT101", anio=anio,
            cuatrimestre="1C", inscriptos=valor,
        ))
    session.commit()


@pytest.fixture
def plan(session, materia):
    ciclo = CicloDB(
        id="2025-1C", anio=2025, numero=1,
        fecha_inicio=date(2025, 3, 10), fecha_fin=date(2025, 7, 5),
    )
    session.add(ciclo)
    session.flush()
    p = PlanificacionCursadaDB(
        id=str(uuid.uuid4()), nombre="P1", ciclo_id="2025-1C",
        forecast_metodo_default="media_movil",
    )
    session.add(p)
    session.commit()
    return p


# =============================================================================
# Tests metodos puros
# =============================================================================

class TestMediaMovil:
    def test_default_window_usa_toda_la_serie(self):
        serie = [(2022, 100), (2023, 110), (2024, 120)]
        r = forecast_media_movil(serie)
        assert r.metodo == "media_movil"
        assert r.valor == 110.0
        assert r.parametros["window"] == 3

    def test_custom_window_limita_a_ultimos_n(self):
        serie = [(2020, 50), (2021, 60), (2022, 100), (2023, 110), (2024, 120)]
        r = forecast_media_movil(serie, window=2)
        assert r.valor == 115.0  # mean(110, 120)
        assert r.parametros["window"] == 2

    def test_serie_unitaria(self):
        r = forecast_media_movil([(2024, 50)])
        assert r.valor == 50.0

    def test_serie_vacia(self):
        r = forecast_media_movil([])
        assert r.valor == 0.0


class TestDrift:
    def test_calcula_pendiente(self):
        serie = [(2022, 100), (2023, 110), (2024, 120)]
        r = forecast_drift(serie)
        assert r.valor == 130.0
        assert r.parametros["slope"] == 10.0

    def test_serie_unitaria_no_extrapola(self):
        r = forecast_drift([(2024, 50)])
        assert r.valor == 50.0

    def test_serie_decreciente(self):
        r = forecast_drift([(2022, 200), (2023, 150), (2024, 100)])
        assert r.valor == 50.0


class TestSES:
    def test_alpha_auto_minimiza_sse(self):
        serie = [(2022, 100), (2023, 110), (2024, 120), (2025, 130)]
        r = forecast_ses(serie)
        for a in [round(0.1 * i, 2) for i in range(1, 10)]:
            r_alt = forecast_ses(serie, alpha=a)
            assert r.in_sample_sse <= r_alt.in_sample_sse + 1e-9

    def test_alpha_fijo_se_respeta(self):
        r = forecast_ses([(2022, 100), (2023, 110), (2024, 120)], alpha=0.5)
        assert r.parametros["alpha"] == 0.5

    def test_serie_unitaria_devuelve_valor(self):
        r = forecast_ses([(2024, 50)])
        assert r.valor == 50.0


class TestComputeForecastDispatcher:
    def test_dispatch_correcto(self):
        serie = [(2022, 100), (2023, 110), (2024, 120)]
        assert compute_forecast(serie, "media_movil").metodo == "media_movil"
        assert compute_forecast(serie, "drift").metodo == "drift"
        assert compute_forecast(serie, "ses").metodo == "ses"

    def test_serie_corta_degenera_a_media_movil(self):
        serie = [(2024, 50)]
        # Cualquier metodo con serie de 1 punto cae a media_movil
        for m in ("media_movil", "drift", "ses"):
            r = compute_forecast(serie, m)
            assert r.metodo == "media_movil"

    def test_metodo_invalido_lanza(self):
        with pytest.raises(ValueError):
            compute_forecast([(2024, 50), (2025, 60)], "kalman")


# =============================================================================
# Tests acceso a datos
# =============================================================================

class TestGetSerie:
    def test_serie_ordenada_por_anio(self, session, materia):
        for anio, v in [(2024, 120), (2022, 100), (2023, 110)]:
            session.add(InscripcionHistoricaDB(
                materia_codigo="MAT101", anio=anio,
                cuatrimestre="1C", inscriptos=v,
            ))
        session.commit()

        serie = get_serie(session, "MAT101", "1C")
        assert serie == [(2022, 100), (2023, 110), (2024, 120)]

    def test_filtra_por_cuatrimestre(self, session, materia):
        session.add(InscripcionHistoricaDB(
            materia_codigo="MAT101", anio=2024,
            cuatrimestre="1C", inscriptos=100,
        ))
        session.add(InscripcionHistoricaDB(
            materia_codigo="MAT101", anio=2024,
            cuatrimestre="2C", inscriptos=200,
        ))
        session.commit()
        assert get_serie(session, "MAT101", "1C") == [(2024, 100)]
        assert get_serie(session, "MAT101", "2C") == [(2024, 200)]

    def test_serie_inexistente(self, session, materia):
        assert get_serie(session, "NOPE", "1C") == []


class TestGetAllForecasts:
    def test_serie_completa_devuelve_3_metodos(self):
        serie = [(2022, 100), (2023, 110), (2024, 120)]
        results = get_all_forecasts(serie)
        assert set(results.keys()) == {"media_movil", "drift", "ses"}

    def test_serie_corta_solo_media_movil(self):
        results = get_all_forecasts([(2024, 100)])
        assert set(results.keys()) == {"media_movil"}

    def test_serie_vacia_devuelve_dict_vacio(self):
        assert get_all_forecasts([]) == {}


# =============================================================================
# Tests resolucion de metodo (override > default plan)
# =============================================================================

class TestResolveMetodo:
    def test_sin_override_usa_default_de_plan(self, session, plan):
        plan.forecast_metodo_default = "drift"
        session.add(plan)
        session.commit()
        assert resolve_metodo(session, plan.id, "MAT101", "1C") == "drift"

    def test_override_gana_sobre_default(self, session, plan):
        plan.forecast_metodo_default = "media_movil"
        session.add(plan)
        session.commit()
        set_metodo_override(session, plan.id, "MAT101", "1C", "ses")
        assert resolve_metodo(session, plan.id, "MAT101", "1C") == "ses"

    def test_override_solo_aplica_a_su_cuatri(self, session, plan):
        set_metodo_override(session, plan.id, "MAT101", "1C", "drift")
        # Para 2C, sigue usando el default
        assert resolve_metodo(session, plan.id, "MAT101", "2C") == "media_movil"

    def test_set_override_none_lo_elimina(self, session, plan):
        set_metodo_override(session, plan.id, "MAT101", "1C", "drift")
        assert get_metodo_override(session, plan.id, "MAT101", "1C") == "drift"
        set_metodo_override(session, plan.id, "MAT101", "1C", None)
        assert get_metodo_override(session, plan.id, "MAT101", "1C") is None

    def test_plan_inexistente_default_media_movil(self, session):
        assert resolve_metodo(session, "fake-plan", "MAT101", "1C") == "media_movil"


class TestGetForecastForMateria:
    def test_aplica_metodo_resuelto(self, session, plan, materia, serie_3_anios):
        plan.forecast_metodo_default = "drift"
        session.add(plan)
        session.commit()
        r = get_forecast_for_materia(session, plan.id, "MAT101", "1C")
        assert r is not None
        assert r.metodo == "drift"
        assert r.valor == 130.0

    def test_override_cambia_metodo(self, session, plan, materia, serie_3_anios):
        plan.forecast_metodo_default = "drift"
        session.add(plan)
        session.commit()
        set_metodo_override(session, plan.id, "MAT101", "1C", "media_movil")
        r = get_forecast_for_materia(session, plan.id, "MAT101", "1C")
        assert r is not None
        assert r.metodo == "media_movil"
        assert r.valor == 110.0

    def test_sin_serie_devuelve_none(self, session, plan, materia):
        assert get_forecast_for_materia(session, plan.id, "MAT101", "1C") is None
