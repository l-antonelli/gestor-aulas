"""Service de forecasting de inscriptos por (materia, cuatrimestre).

Implementa tres metodos simples adecuados a series cortas (3-4 puntos):
- `media_movil`: promedio de los ultimos N puntos (default = todos)
- `drift`: extrapolacion lineal entre primer y ultimo punto
- `ses`: suavizado exponencial simple, alpha auto-calibrado por SSE in-sample

El service expone:
- `forecast_*`: funciones puras que toman una serie y devuelven `ForecastResult`
- `get_serie`: arma la serie historica para una (materia, cuatri)
- `get_or_compute_forecasts`: arma todos los forecasts para una (materia, cuatri, anio)
- `persist_forecast`/`get_persisted_forecast`: persistencia del metodo elegido
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional

from sqlmodel import Session, select

from src.database.models import (
    InscripcionForecastDB,
    InscripcionHistoricaDB,
)


# =============================================================================
# Tipos
# =============================================================================

@dataclass
class ForecastResult:
    """Resultado de un metodo de forecast aplicado a una serie."""
    metodo: str
    valor: float
    parametros: dict = field(default_factory=dict)
    in_sample_sse: float = 0.0
    historico: list[tuple[int, int]] = field(default_factory=list)


# =============================================================================
# Metodos puros
# =============================================================================

def forecast_media_movil(
    serie: list[tuple[int, int]], window: Optional[int] = None,
) -> ForecastResult:
    """Forecast = promedio de los ultimos `window` puntos.

    Si `window` es None o > len(serie), usa todos los puntos.
    """
    if not serie:
        return ForecastResult(
            metodo="media_movil", valor=0.0,
            parametros={"window": 0}, in_sample_sse=0.0, historico=[],
        )

    n = len(serie)
    w = min(window, n) if window else n
    valores = [v for _, v in serie[-w:]]
    media = sum(valores) / w

    # SSE in-sample: aplicamos media movil a cada punto t (con su ventana hacia atras)
    sse = 0.0
    for t in range(1, n):
        ventana = [v for _, v in serie[max(0, t - w):t]]
        if not ventana:
            continue
        pred = sum(ventana) / len(ventana)
        sse += (serie[t][1] - pred) ** 2

    return ForecastResult(
        metodo="media_movil",
        valor=float(media),
        parametros={"window": w},
        in_sample_sse=sse,
        historico=list(serie),
    )


def forecast_drift(serie: list[tuple[int, int]]) -> ForecastResult:
    """Extrapolacion lineal: forecast = y_last + slope, donde
    slope = (y_last - y_first) / (n - 1).

    Con n=1 devuelve el unico valor sin slope.
    """
    if not serie:
        return ForecastResult(
            metodo="drift", valor=0.0,
            parametros={}, in_sample_sse=0.0, historico=[],
        )

    n = len(serie)
    if n == 1:
        return ForecastResult(
            metodo="drift",
            valor=float(serie[0][1]),
            parametros={"slope": 0.0},
            in_sample_sse=0.0,
            historico=list(serie),
        )

    y_first = serie[0][1]
    y_last = serie[-1][1]
    slope = (y_last - y_first) / (n - 1)
    valor = y_last + slope

    # SSE in-sample: para cada t en [1..n-1], aplicar drift sobre serie[:t]
    sse = 0.0
    for t in range(2, n):
        sub = serie[:t]
        sub_slope = (sub[-1][1] - sub[0][1]) / (len(sub) - 1)
        pred = sub[-1][1] + sub_slope
        sse += (serie[t][1] - pred) ** 2

    return ForecastResult(
        metodo="drift",
        valor=float(valor),
        parametros={"slope": float(slope)},
        in_sample_sse=sse,
        historico=list(serie),
    )


def _ses_predict(values: list[float], alpha: float) -> tuple[list[float], float]:
    """Aplica SES con alpha. Devuelve (niveles_in_sample, forecast_one_step_ahead)."""
    if not values:
        return [], 0.0
    s = [float(values[0])]
    for t in range(1, len(values)):
        s.append(alpha * values[t] + (1 - alpha) * s[-1])
    return s, s[-1]


def forecast_ses(
    serie: list[tuple[int, int]], alpha: Optional[float] = None,
) -> ForecastResult:
    """Suavizado exponencial simple. Si alpha=None, calibra por grilla."""
    if not serie:
        return ForecastResult(
            metodo="ses", valor=0.0,
            parametros={}, in_sample_sse=0.0, historico=[],
        )

    n = len(serie)
    if n == 1:
        return ForecastResult(
            metodo="ses",
            valor=float(serie[0][1]),
            parametros={"alpha": None},
            in_sample_sse=0.0,
            historico=list(serie),
        )

    valores = [float(v) for _, v in serie]

    def _sse_for_alpha(a: float) -> float:
        s, _ = _ses_predict(valores, a)
        # SSE in-sample: comparar y_t (t>=1) contra s_{t-1}
        return sum((valores[t] - s[t - 1]) ** 2 for t in range(1, n))

    if alpha is None:
        # Grid search
        grid = [round(0.1 * i, 2) for i in range(1, 10)]  # 0.1, 0.2, ..., 0.9
        best_alpha = min(grid, key=_sse_for_alpha)
    else:
        best_alpha = alpha

    levels, forecast_value = _ses_predict(valores, best_alpha)
    sse = _sse_for_alpha(best_alpha)

    return ForecastResult(
        metodo="ses",
        valor=float(forecast_value),
        parametros={"alpha": float(best_alpha)},
        in_sample_sse=sse,
        historico=list(serie),
    )


# =============================================================================
# Acceso a datos / orquestacion
# =============================================================================

def get_serie(
    session: Session, materia_codigo: str, cuatrimestre: str,
) -> list[tuple[int, int]]:
    """Retorna [(anio, inscriptos), ...] ordenado para esa (materia, cuatri)."""
    rows = list(session.exec(
        select(InscripcionHistoricaDB)
        .where(InscripcionHistoricaDB.materia_codigo == materia_codigo)
        .where(InscripcionHistoricaDB.cuatrimestre == cuatrimestre)
    ).all())
    rows.sort(key=lambda r: r.anio)
    return [(r.anio, r.inscriptos) for r in rows]


def get_or_compute_forecasts(
    session: Session,
    materia_codigo: str,
    cuatrimestre: str,
    anio_target: int,
    media_movil_window: Optional[int] = None,
) -> dict[str, ForecastResult]:
    """Devuelve {metodo: ForecastResult} para todos los metodos disponibles.

    Si la serie tiene <2 puntos, devuelve solo `media_movil` (drift y SES
    degeneran sin tendencia).
    """
    serie = get_serie(session, materia_codigo, cuatrimestre)
    if not serie:
        return {}

    results: dict[str, ForecastResult] = {
        "media_movil": forecast_media_movil(serie, window=media_movil_window),
    }
    if len(serie) >= 2:
        results["drift"] = forecast_drift(serie)
        results["ses"] = forecast_ses(serie)
    return results


def persist_forecast(
    session: Session,
    materia_codigo: str,
    cuatrimestre: str,
    anio_target: int,
    metodo: str,
    result: ForecastResult,
) -> InscripcionForecastDB:
    """Insert or update del forecast persistido para esa (materia, cuatri, anio)."""
    record = session.get(
        InscripcionForecastDB,
        (materia_codigo, cuatrimestre, anio_target),
    )
    if record is None:
        record = InscripcionForecastDB(
            materia_codigo=materia_codigo,
            cuatrimestre=cuatrimestre,
            anio_target=anio_target,
            metodo=metodo,
            valor=result.valor,
            parametros_json=json.dumps(result.parametros),
        )
    else:
        record.metodo = metodo
        record.valor = result.valor
        record.fecha_calculo = datetime.utcnow()
        record.parametros_json = json.dumps(result.parametros)
    session.add(record)
    session.commit()
    session.refresh(record)
    return record


def get_persisted_forecast(
    session: Session,
    materia_codigo: str,
    cuatrimestre: str,
    anio_target: int,
) -> Optional[InscripcionForecastDB]:
    """Devuelve el forecast persistido o None si no existe."""
    return session.get(
        InscripcionForecastDB,
        (materia_codigo, cuatrimestre, anio_target),
    )


def delete_persisted_forecast(
    session: Session,
    materia_codigo: str,
    cuatrimestre: str,
    anio_target: int,
) -> bool:
    """Elimina el forecast persistido. True si habia algo para borrar."""
    record = get_persisted_forecast(
        session, materia_codigo, cuatrimestre, anio_target,
    )
    if record is None:
        return False
    session.delete(record)
    session.commit()
    return True
