"""Evaluation metrics for point and quantile time series forecasts."""
import numpy as np
import pandas as pd
from typing import Dict, Union


def mean_absolute_error(y_true: np.ndarray, y_pred: np.ndarray) -> float:
    """Calculate Mean Absolute Error (MAE)."""
    yt = np.asarray(y_true, dtype=float)
    yp = np.asarray(y_pred, dtype=float)
    return float(np.mean(np.abs(yt - yp)))


def wape(y_true: np.ndarray, y_pred: np.ndarray, eps: float = 1e-8) -> float:
    """Calculate Weighted Absolute Percentage Error (WAPE)."""
    yt = np.asarray(y_true, dtype=float)
    yp = np.asarray(y_pred, dtype=float)
    total_actual = np.sum(np.abs(yt))
    if total_actual < eps:
        return 0.0
    return float(np.sum(np.abs(yt - yp)) / total_actual)


def pinball_loss(y_true: np.ndarray, y_pred: np.ndarray, alpha: float) -> float:
    """Calculate Pinball Loss (Quantile Loss) for a specific alpha quantile (e.g. 0.1, 0.5, 0.9)."""
    yt = np.asarray(y_true, dtype=float)
    yp = np.asarray(y_pred, dtype=float)
    diff = yt - yp
    loss = np.maximum(alpha * diff, (alpha - 1.0) * diff)
    return float(np.mean(loss))


def quantile_coverage(y_true: np.ndarray, y_p10: np.ndarray, y_p90: np.ndarray) -> float:
    """Calculate empirical coverage percentage between P10 and P90 intervals."""
    yt = np.asarray(y_true, dtype=float)
    p10 = np.asarray(y_p10, dtype=float)
    p90 = np.asarray(y_p90, dtype=float)
    inside = (yt >= p10) & (yt <= p90)
    return float(np.mean(inside))


def evaluate_forecast(
    y_true: Union[pd.Series, np.ndarray],
    preds: Dict[str, np.ndarray],
) -> Dict[str, float]:
    """Compute comprehensive performance summary for a target's quantile predictions."""
    yt = np.asarray(y_true, dtype=float)
    p10 = preds["p10"]
    p50 = preds["p50"]
    p90 = preds["p90"]

    return {
        "mae": mean_absolute_error(yt, p50),
        "wape": wape(yt, p50),
        "pinball_p10": pinball_loss(yt, p10, 0.1),
        "pinball_p50": pinball_loss(yt, p50, 0.5),
        "pinball_p90": pinball_loss(yt, p90, 0.9),
        "coverage": quantile_coverage(yt, p10, p90),
    }
