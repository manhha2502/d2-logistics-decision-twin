"""Baseline time series forecasting models used for benchmarking and runtime fallback."""
import numpy as np
import pandas as pd
from typing import Dict, Union, Optional

try:
    from statsmodels.tsa.holtwinters import SimpleExpSmoothing
    HAS_STATSMODELS = True
except ImportError:
    HAS_STATSMODELS = False


class NaiveForecast:
    """Naive model predicting last observed value, with residual-based quantiles."""

    def __init__(self, z_score: float = 1.28):
        self.z_score = z_score
        self.last_val = 0.0
        self.std_err = 0.5

    def fit(self, y: Union[pd.Series, np.ndarray]) -> "NaiveForecast":
        vals = np.asarray(y, dtype=float)
        if len(vals) == 0:
            raise ValueError("Cannot fit NaiveForecast on empty series")
        self.last_val = float(vals[-1])
        if len(vals) > 1:
            diffs = np.diff(vals)
            std = float(np.std(diffs))
            self.std_err = max(std, 0.05)
        else:
            self.std_err = 0.5
        return self

    def predict(self, horizon: int = 4) -> Dict[str, np.ndarray]:
        p50 = np.full(horizon, self.last_val, dtype=float)
        p10 = np.maximum(0.0, p50 - self.z_score * self.std_err)
        p90 = p50 + self.z_score * self.std_err
        return {"p10": p10, "p50": p50, "p90": p90}


class SeasonalNaiveForecast:
    """Seasonal Naive model repeating values from the last season (default: 32 steps = 8hr shift)."""

    def __init__(self, season_length: int = 32, z_score: float = 1.28):
        self.season_length = season_length
        self.z_score = z_score
        self.seasonal_cycle = np.array([])
        self.std_err = 0.5

    def fit(self, y: Union[pd.Series, np.ndarray]) -> "SeasonalNaiveForecast":
        vals = np.asarray(y, dtype=float)
        if len(vals) == 0:
            raise ValueError("Cannot fit SeasonalNaiveForecast on empty series")
        cycle_len = min(len(vals), self.season_length)
        self.seasonal_cycle = vals[-cycle_len:]
        if len(vals) > 1:
            diffs = np.diff(vals)
            self.std_err = max(float(np.std(diffs)), 0.05)
        else:
            self.std_err = 0.5
        return self

    def predict(self, horizon: int = 4) -> Dict[str, np.ndarray]:
        if len(self.seasonal_cycle) == 0:
            raise RuntimeError("Model must be fitted before predict")
        reps = int(np.ceil(horizon / len(self.seasonal_cycle)))
        repeated = np.tile(self.seasonal_cycle, reps)[:horizon]
        p50 = repeated.astype(float)
        p10 = np.maximum(0.0, p50 - self.z_score * self.std_err)
        p90 = p50 + self.z_score * self.std_err
        return {"p10": p10, "p50": p50, "p90": p90}


class ExponentialSmoothingForecast:
    """Exponential Smoothing with statistical quantiles."""

    def __init__(self, alpha: Optional[float] = None, z_score: float = 1.28):
        self.alpha = alpha
        self.z_score = z_score
        self.model_fitted = None
        self.last_val = 0.0
        self.std_err = 0.5

    def fit(self, y: Union[pd.Series, np.ndarray]) -> "ExponentialSmoothingForecast":
        vals = np.asarray(y, dtype=float)
        if len(vals) == 0:
            raise ValueError("Cannot fit ExponentialSmoothing on empty series")
        self.last_val = float(vals[-1])
        if len(vals) > 1:
            diffs = np.diff(vals)
            self.std_err = max(float(np.std(diffs)), 0.05)
        else:
            self.std_err = 0.5

        if HAS_STATSMODELS and len(vals) >= 10:
            try:
                ses = SimpleExpSmoothing(vals, initialization_method="estimated")
                self.model_fitted = ses.fit(smoothing_level=self.alpha, optimized=(self.alpha is None))
            except Exception:
                self.model_fitted = None
        return self

    def predict(self, horizon: int = 4) -> Dict[str, np.ndarray]:
        if self.model_fitted is not None:
            try:
                preds = self.model_fitted.forecast(horizon)
                p50 = np.asarray(preds, dtype=float)
            except Exception:
                p50 = np.full(horizon, self.last_val, dtype=float)
        else:
            p50 = np.full(horizon, self.last_val, dtype=float)

        p10 = np.maximum(0.0, p50 - self.z_score * self.std_err)
        p90 = p50 + self.z_score * self.std_err
        return {"p10": p10, "p50": p50, "p90": p90}


class BaselineSuite:
    """Manager holding baseline models across all target drivers for quick fallback."""

    def __init__(self, model_class=NaiveForecast):
        self.model_class = model_class
        self.models: Dict[str, any] = {}

    def fit(self, df: pd.DataFrame, target_columns: list[str]) -> "BaselineSuite":
        for col in target_columns:
            if col in df.columns:
                model = self.model_class()
                model.fit(df[col].dropna())
                self.models[col] = model
        return self

    def predict(self, horizon: int = 4) -> Dict[str, Dict[str, np.ndarray]]:
        results = {}
        for col, model in self.models.items():
            results[col] = model.predict(horizon=horizon)
        return results
