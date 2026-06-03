"""Service de forecasting de inscriptos por (materia, cuatrimestre).

Implementa tres metodos simples adecuados a series cortas (3-4 puntos):
- `media_movil`: promedio de los ultimos N puntos (default = todos)
- `drift`: extrapolacion lineal entre primer y ultimo punto
- `ses`: suavizado exponencial simple, alpha auto-calibrado por SSE in-sample

Resolucion del metodo a usar (desde un Plan):
1. Si existe `MateriaForecastConfigDB` para (plan, materia, cuatri) → usa override.
2. Sino → usa `PlanificacionCursadaDB.forecast_metodo_default`.

El **valor del forecast NO se persiste**. Se recomputa al vuelo cada vez que se
necesita (servicio puro, sin cache). Si la serie historica cambia, el valor
queda actualizado automaticamente.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional

from sqlmodel import Session, select

from src.database.models import (
    InscripcionHistoricaDB,
    MateriaForecastConfigDB,
    PlanificacionCursadaDB,
)


# Metodos disponibles, exportados como constantes para que la UI los use.
METODOS_DISPONIBLES: list[str] = ["media_movil", "drift", "ses"]
METODO_LABELS: dict[str, str] = {
    "media_movil": "Media móvil",
    "drift": "Drift (lineal)",
    "ses": "SES (α auto)",
    "manual": "Manual (override)",
}


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

    _, forecast_value = _ses_predict(valores, best_alpha)
    sse = _sse_for_alpha(best_alpha)

    return ForecastResult(
        metodo="ses",
        valor=float(forecast_value),
        parametros={"alpha": float(best_alpha)},
        in_sample_sse=sse,
        historico=list(serie),
    )


# =============================================================================
# Despachador por nombre de metodo
# =============================================================================

def compute_forecast(
    serie: list[tuple[int, int]], metodo: str,
) -> ForecastResult:
    """Computa el forecast aplicando el metodo indicado. Si la serie tiene
    <2 puntos, drift y SES degeneran a media_movil para evitar resultados
    sin sentido.
    """
    if metodo not in METODOS_DISPONIBLES:
        raise ValueError(
            f"Metodo desconocido '{metodo}'. Disponibles: {METODOS_DISPONIBLES}"
        )
    if len(serie) < 2 and metodo != "media_movil":
        # Degenerar a media_movil para series cortas
        return forecast_media_movil(serie)
    if metodo == "media_movil":
        return forecast_media_movil(serie)
    if metodo == "drift":
        return forecast_drift(serie)
    return forecast_ses(serie)


# =============================================================================
# Acceso a datos
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


def get_all_forecasts(
    serie: list[tuple[int, int]],
) -> dict[str, ForecastResult]:
    """Devuelve {metodo: ForecastResult} para todos los metodos disponibles.

    Si la serie tiene <2 puntos, devuelve solo `media_movil` (drift y SES
    degeneran sin tendencia).
    """
    if not serie:
        return {}
    results: dict[str, ForecastResult] = {
        "media_movil": forecast_media_movil(serie),
    }
    if len(serie) >= 2:
        results["drift"] = forecast_drift(serie)
        results["ses"] = forecast_ses(serie)
    return results


# =============================================================================
# Resolucion del metodo a usar (override por materia > default de plan)
# =============================================================================

def get_metodo_override(
    session: Session,
    plan_cursada_id: str,
    materia_codigo: str,
    cuatrimestre: str,
) -> Optional[str]:
    """Devuelve el metodo overrideado para (plan, materia, cuatri) o None."""
    rec = session.get(
        MateriaForecastConfigDB,
        (plan_cursada_id, materia_codigo, cuatrimestre),
    )
    return rec.metodo if rec is not None else None


def resolve_metodo(
    session: Session,
    plan_cursada_id: str,
    materia_codigo: str,
    cuatrimestre: str,
) -> str:
    """Devuelve el metodo a usar: override si existe, sino default del plan."""
    override = get_metodo_override(
        session, plan_cursada_id, materia_codigo, cuatrimestre,
    )
    if override is not None:
        return override
    plan = session.get(PlanificacionCursadaDB, plan_cursada_id)
    if plan is None:
        return "media_movil"
    return plan.forecast_metodo_default


def set_metodo_override(
    session: Session,
    plan_cursada_id: str,
    materia_codigo: str,
    cuatrimestre: str,
    metodo: Optional[str],
) -> None:
    """Setea o elimina el override del metodo de forecast.

    Si `metodo` es None y no hay valor_override, elimina la fila
    completa (vuelve al default). Si hay valor_override, solo limpia
    el metodo y preserva el valor_override.
    """
    rec = session.get(
        MateriaForecastConfigDB,
        (plan_cursada_id, materia_codigo, cuatrimestre),
    )
    if metodo is None:
        if rec is None:
            return
        if rec.valor_override is None:
            session.delete(rec)
        else:
            rec.metodo = None
            session.add(rec)
        session.commit()
        return
    if metodo not in METODOS_DISPONIBLES:
        raise ValueError(f"Metodo desconocido '{metodo}'")
    if rec is None:
        rec = MateriaForecastConfigDB(
            plan_cursada_id=plan_cursada_id,
            materia_codigo=materia_codigo,
            cuatrimestre=cuatrimestre,
            metodo=metodo,
        )
    else:
        rec.metodo = metodo
    session.add(rec)
    session.commit()


def get_valor_override(
    session: Session,
    plan_cursada_id: str,
    materia_codigo: str,
    cuatrimestre: str,
) -> Optional[float]:
    """Devuelve el valor manual seteado o None si no hay."""
    rec = session.get(
        MateriaForecastConfigDB,
        (plan_cursada_id, materia_codigo, cuatrimestre),
    )
    return rec.valor_override if rec is not None else None


def set_valor_override(
    session: Session,
    plan_cursada_id: str,
    materia_codigo: str,
    cuatrimestre: str,
    valor: Optional[float],
) -> None:
    """Setea o elimina el override del valor de forecast.

    Si `valor` es None y no hay metodo override, elimina la fila
    completa. Si hay metodo override, solo limpia el valor.
    """
    rec = session.get(
        MateriaForecastConfigDB,
        (plan_cursada_id, materia_codigo, cuatrimestre),
    )
    if valor is None:
        if rec is None:
            return
        if rec.metodo is None:
            session.delete(rec)
        else:
            rec.valor_override = None
            session.add(rec)
        session.commit()
        return
    if valor < 0:
        raise ValueError("valor_override debe ser >= 0")
    if rec is None:
        rec = MateriaForecastConfigDB(
            plan_cursada_id=plan_cursada_id,
            materia_codigo=materia_codigo,
            cuatrimestre=cuatrimestre,
            valor_override=valor,
        )
    else:
        rec.valor_override = valor
    session.add(rec)
    session.commit()


def get_forecast_for_materia(
    session: Session,
    plan_cursada_id: str,
    materia_codigo: str,
    cuatrimestre: str,
) -> Optional[ForecastResult]:
    """Devuelve el forecast a usar para (plan, materia, cuatri).

    Resolución:
    1. Si hay `valor_override` → devuelve un ForecastResult sintético
       con valor=override, metodo="manual".
    2. Sino, computa desde la serie histórica con el método resuelto
       (override del método > default del plan).
    3. Si no hay serie → None.
    """
    override = get_valor_override(
        session, plan_cursada_id, materia_codigo, cuatrimestre,
    )
    if override is not None:
        return ForecastResult(valor=override, metodo="manual")
    serie = get_serie(session, materia_codigo, cuatrimestre)
    if not serie:
        return None
    metodo = resolve_metodo(
        session, plan_cursada_id, materia_codigo, cuatrimestre,
    )
    return compute_forecast(serie, metodo)
