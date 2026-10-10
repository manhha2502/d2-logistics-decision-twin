"""LightGBM Quantile Regressors for multi-driver logistics forecasting."""
from pathlib import Path
from typing import Dict, List, Union
import numpy as np
import pandas as pd
import joblib

try:
    import lightgbm as lgb
    HAS_LIGHTGBM = True
except ImportError:
    HAS_LIGHTGBM = False

from sklearn.ensemble import GradientBoostingRegressor

from src.data.features import TARGET_COLUMNS, FEATURE_COLUMNS

ALPHAS = [0.1, 0.5, 0.9]


def create_quantile_regressor(alpha: float, seed: int = 42):
    """Instantiate a quantile regressor using LightGBM (preferred) or Sklearn fallback."""
    if HAS_LIGHTGBM:
        return lgb.LGBMRegressor(
            objective="quantile",
            alpha=alpha,
            n_estimators=80,
            learning_rate=0.05,
            max_depth=5,
            num_leaves=25,
            min_child_samples=10,
            random_state=seed,
            verbosity=-1,
            n_jobs=-1,
        )
    else:
        return GradientBoostingRegressor(
            loss="quantile",
            alpha=alpha,
            n_estimators=50,
            max_depth=4,
            random_state=seed,
        )


def train_target_models(
    X: pd.DataFrame,
    y_series: pd.Series,
    alphas: List[float] = ALPHAS,
    seed: int = 42,
) -> Dict[float, any]:
    """Train 3 quantile models (alpha=0.1, 0.5, 0.9) for a single target series."""
    models = {}
    for alpha in alphas:
        model = create_quantile_regressor(alpha=alpha, seed=seed)
        model.fit(X, y_series)
        models[alpha] = model
    return models


def train_all_quantile_models(
    X: pd.DataFrame,
    y: pd.DataFrame,
    targets: List[str] = TARGET_COLUMNS,
    alphas: List[float] = ALPHAS,
    seed: int = 42,
) -> Dict[str, Dict[float, any]]:
    """Train all 18 quantile models across the 6 logistics drivers."""
    bundle: Dict[str, Dict[float, any]] = {}
    for target in targets:
        if target not in y.columns:
            raise ValueError(f"Target column '{target}' not present in y")
        bundle[target] = train_target_models(X, y[target], alphas=alphas, seed=seed)
    return bundle


def predict_step_quantiles(
    bundle: Dict[str, Dict[float, any]],
    target: str,
    X_step: pd.DataFrame,
) -> Dict[str, float]:
    """Predict and enforce non-crossing quantiles for a target given a single-step feature vector.

    Guarantees: 0 <= p10 <= p50 <= p90.
    """
    models = bundle[target]
    p10_raw = float(models[0.1].predict(X_step)[0])
    p50_raw = float(models[0.5].predict(X_step)[0])
    p90_raw = float(models[0.9].predict(X_step)[0])

    # Enforce non-negativity and strictly non-crossing ordering
    p10 = max(0.0, p10_raw)
    p50 = max(p10, p50_raw)
    p90 = max(p50, p90_raw)

    # For process/travel times, ensure minimal physical floor (e.g. 0.05 min)
    if "min" in target:
        p10 = max(0.05, p10)
        p50 = max(p10, p50)
        p90 = max(p50, p90)

    return {"p10": p10, "p50": p50, "p90": p90}


def save_models(models_bundle: Dict[str, any], file_path: Union[str, Path]) -> None:
    """Save models dictionary to disk using joblib."""
    path = Path(file_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    joblib.dump(models_bundle, path)


def load_models(file_path: Union[str, Path]) -> Dict[str, any]:
    """Load models bundle from disk."""
    path = Path(file_path)
    if not path.is_file():
        raise FileNotFoundError(f"Model file not found: {path}")
    return joblib.load(path)
