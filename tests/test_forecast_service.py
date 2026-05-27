"""Tests para forecast_service."""

import pytest
from sqlalchemy.pool import StaticPool
from sqlmodel import Session, SQLModel, create_engine

from src.database.models import (
    InscripcionForecastDB,
    InscripcionHistoricaDB,
    MateriaDB,
)
from src.services.forecast_service import (
    forecast_drift,
    forecast_media_movil,
    forecast_ses,
    get_or_compute_forecasts,
    get_persisted_forecast,
    get_serie,
    persist_forecast,
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
        # slope = (120 - 100) / 2 = 10; valor = 120 + 10 = 130
        assert r.valor == 130.0
        assert r.parametros["slope"] == 10.0

    def test_serie_unitaria_no_extrapola(self):
        r = forecast_drift([(2024, 50)])
        assert r.valor == 50.0

    def test_serie_decreciente(self):
        r = forecast_drift([(2022, 200), (2023, 150), (2024, 100)])
        # slope = -50; valor = 50
        assert r.valor == 50.0


class TestSES:
    def test_alpha_auto_minimiza_sse(self):
        serie = [(2022, 100), (2023, 110), (2024, 120), (2025, 130)]
        r = forecast_ses(serie)
        chosen_alpha = r.parametros["alpha"]
        # Verificar que ningun otro alpha en la grilla tenga SSE menor
        for a in [round(0.1 * i, 2) for i in range(1, 10)]:
            r_alt = forecast_ses(serie, alpha=a)
            assert r.in_sample_sse <= r_alt.in_sample_sse + 1e-9
        assert 0.1 <= chosen_alpha <= 0.9

    def test_alpha_fijo_se_respeta(self):
        serie = [(2022, 100), (2023, 110), (2024, 120)]
        r = forecast_ses(serie, alpha=0.5)
        assert r.parametros["alpha"] == 0.5

    def test_serie_unitaria_devuelve_valor(self):
        r = forecast_ses([(2024, 50)])
        assert r.valor == 50.0

    def test_serie_constante_predice_constante(self):
        r = forecast_ses([(2022, 100), (2023, 100), (2024, 100)], alpha=0.5)
        assert r.valor == 100.0


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


class TestGetOrComputeForecasts:
    def test_serie_completa_devuelve_3_metodos(self, session, materia, serie_3_anios):
        results = get_or_compute_forecasts(session, "MAT101", "1C", 2025)
        assert set(results.keys()) == {"media_movil", "drift", "ses"}

    def test_serie_corta_solo_media_movil(self, session, materia):
        session.add(InscripcionHistoricaDB(
            materia_codigo="MAT101", anio=2024,
            cuatrimestre="1C", inscriptos=100,
        ))
        session.commit()
        results = get_or_compute_forecasts(session, "MAT101", "1C", 2025)
        assert set(results.keys()) == {"media_movil"}

    def test_sin_serie_devuelve_dict_vacio(self, session, materia):
        results = get_or_compute_forecasts(session, "MAT101", "1C", 2025)
        assert results == {}


class TestPersistencia:
    def test_persist_y_recuperar(self, session, materia, serie_3_anios):
        results = get_or_compute_forecasts(session, "MAT101", "1C", 2025)
        ses_result = results["ses"]
        record = persist_forecast(
            session, "MAT101", "1C", 2025, "ses", ses_result,
        )
        assert isinstance(record, InscripcionForecastDB)

        retrieved = get_persisted_forecast(session, "MAT101", "1C", 2025)
        assert retrieved is not None
        assert retrieved.metodo == "ses"
        assert retrieved.valor == ses_result.valor

    def test_persist_sobrescribe_existente(self, session, materia, serie_3_anios):
        results = get_or_compute_forecasts(session, "MAT101", "1C", 2025)
        persist_forecast(session, "MAT101", "1C", 2025, "media_movil", results["media_movil"])
        persist_forecast(session, "MAT101", "1C", 2025, "drift", results["drift"])

        retrieved = get_persisted_forecast(session, "MAT101", "1C", 2025)
        assert retrieved is not None
        assert retrieved.metodo == "drift"
        assert retrieved.valor == results["drift"].valor

    def test_get_persisted_inexistente(self, session, materia):
        assert get_persisted_forecast(session, "MAT101", "1C", 2025) is None
