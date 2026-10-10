"""Forecast service providing public runtime API for logistics drivers."""
from datetime import datetime, timedelta
from pathlib import Path
from typing import List, Optional, Union
import numpy as np
import pandas as pd

from src.common.schemas import ForecastPoint, QuantileValue
from src.common.config import load_config
from src.data.loader import load_recent_history, load_future_production_plan
from src.data.features import (
    build_step_inference_features,
    TARGET_COLUMNS,
)
from src.forecast.quantile_model import load_models, predict_step_quantiles
from src.forecast.baseline import BaselineSuite, NaiveForecast

MODEL_PATH = Path("artifacts/models/forecast_models.joblib")


def _sanitize_quantiles(p10: float, p50: float, p90: float, min_floor: float = 0.0) -> QuantileValue:
    """Ensure non-negativity and strictly non-crossing ordering: 0 <= p10 <= p50 <= p90."""
    p10_c = max(min_floor, float(p10))
    p50_c = max(p10_c, float(p50))
    p90_c = max(p50_c, float(p90))
    return QuantileValue(p10=round(p10_c, 4), p50=round(p50_c, 4), p90=round(p90_c, 4))


def _predict_with_fallback(
    recent_history: pd.DataFrame,
    horizon_steps: int = 4,
) -> dict[str, dict[str, np.ndarray]]:
    """Predict using BaselineSuite when LightGBM models are not available."""
    suite = BaselineSuite(model_class=NaiveForecast)
    suite.fit(recent_history, TARGET_COLUMNS)
    return suite.predict(horizon=horizon_steps)


def forecast_future_drivers(
    now: Optional[Union[datetime, str, pd.Timestamp]] = None,
    horizon_min: int = 60,
    interval_min: int = 15,
) -> List[ForecastPoint]:
    """Forecast future drivers for route R1 across the specified horizon and interval.

    Returns exactly +15, +30, +45, +60 min ForecastPoint instances with P10/P50/P90.
    Falls back gracefully to baseline time-series models if trained ML models are unavailable.
    """
    if horizon_min != 60 or interval_min != 15:
        raise ValueError("MVP requires horizon_min=60 and interval_min=15")

    # 1. Resolve 'now' timestamp
    if now is None:
        try:
            cfg = load_config()
            now_str = cfg["system"]["snapshot_time"]
            now_dt = pd.to_datetime(now_str).to_pydatetime()
        except Exception:
            now_dt = datetime(2026, 10, 8, 14, 0, 0)
    else:
        now_dt = pd.to_datetime(now).to_pydatetime()

    if now_dt.tzinfo is not None:
        now_dt = now_dt.replace(tzinfo=None)

    # 2. Determine target timestamps (+15, +30, +45, +60)
    step_minutes = list(range(interval_min, horizon_min + 1, interval_min))
    target_times = [now_dt + timedelta(minutes=m) for m in step_minutes]

    # 3. Load historical context and future production plan
    try:
        cfg = load_config()
        hist_path = cfg["root"] / "data/model_ready/model_training_15min.csv"
        plan_path = cfg["paths"]["production_plan"]
        model_artifact_path = cfg["paths"]["artifacts_dir"] / "models/forecast_models.joblib"
    except Exception:
        hist_path = Path("data/model_ready/model_training_15min.csv")
        plan_path = Path("data/known_future/future_production_plan_15min.csv")
        model_artifact_path = MODEL_PATH

    history_df = load_recent_history(now=now_dt, window_steps=32, file_path=hist_path)

    try:
        plan_df = load_future_production_plan(file_path=plan_path)
    except Exception:
        plan_df = pd.DataFrame()

    # 4. Attempt to load LightGBM Quantile models; fallback to Baseline if missing/failed
    ml_models = None
    if model_artifact_path.is_file():
        try:
            ml_models = load_models(model_artifact_path)
        except Exception:
            ml_models = None

    forecast_points: List[ForecastPoint] = []
    curr_history = history_df.copy()

    if ml_models is not None:
        # Autoregressive Rollout using LightGBM Quantile Models
        for t_step in target_times:
            # Query known production plan for planned output
            plan_match = plan_df[plan_df["timestamp"] == t_step] if not plan_df.empty else pd.DataFrame()
            if not plan_match.empty:
                planned_output = float(plan_match["planned_output_units"].iloc[0])
                shift_val = str(plan_match["shift"].iloc[0])
            else:
                planned_output = 37.5
                shift_val = "SHIFT_B"

            # Build single-step inference feature vector
            X_step = build_step_inference_features(
                timestamp=t_step,
                planned_output_units=planned_output,
                recent_history=curr_history,
                shift_str=shift_val,
            )

            # Predict 6 drivers
            q_demand = predict_step_quantiles(ml_models, "r1_demand_totes", X_step)
            q_loaded = predict_step_quantiles(ml_models, "travel_loaded_min", X_step)
            q_empty = predict_step_quantiles(ml_models, "travel_empty_min", X_step)
            q_picking = predict_step_quantiles(ml_models, "picking_min", X_step)
            q_loading = predict_step_quantiles(ml_models, "loading_min", X_step)
            q_unloading = predict_step_quantiles(ml_models, "unloading_min", X_step)

            fp = ForecastPoint(
                timestamp=t_step,
                demand=_sanitize_quantiles(q_demand["p10"], q_demand["p50"], q_demand["p90"], min_floor=0.0),
                travel_loaded=_sanitize_quantiles(q_loaded["p10"], q_loaded["p50"], q_loaded["p90"], min_floor=0.1),
                travel_empty=_sanitize_quantiles(q_empty["p10"], q_empty["p50"], q_empty["p90"], min_floor=0.1),
                picking_time=_sanitize_quantiles(q_picking["p10"], q_picking["p50"], q_picking["p90"], min_floor=0.1),
                loading_time=_sanitize_quantiles(q_loading["p10"], q_loading["p50"], q_loading["p90"], min_floor=0.1),
                unloading_time=_sanitize_quantiles(q_unloading["p10"], q_unloading["p50"], q_unloading["p90"], min_floor=0.1),
            )
            forecast_points.append(fp)

            # Roll forward history with P50 predictions for autoregressive continuity
            new_row = {
                "timestamp": t_step,
                "r1_demand_totes": q_demand["p50"],
                "travel_loaded_min": q_loaded["p50"],
                "travel_empty_min": q_empty["p50"],
                "picking_min": q_picking["p50"],
                "loading_min": q_loading["p50"],
                "unloading_min": q_unloading["p50"],
                "r1_amr_available": curr_history["r1_amr_available"].iloc[-1],
                "r1_queue_start_totes": 0.0,
                "buffer_mat_a_end_totes": curr_history["buffer_mat_a_end_totes"].iloc[-1] if "buffer_mat_a_end_totes" in curr_history.columns else 15.0,
                "buffer_mat_b_end_totes": curr_history["buffer_mat_b_end_totes"].iloc[-1] if "buffer_mat_b_end_totes" in curr_history.columns else 15.0,
            }
            curr_history = pd.concat([curr_history, pd.DataFrame([new_row])], ignore_index=True)
    else:
        # Fallback Mode: Baseline Naive / Seasonal Naive
        baseline_preds = _predict_with_fallback(curr_history, horizon_steps=len(target_times))
        for idx, t_step in enumerate(target_times):
            fp = ForecastPoint(
                timestamp=t_step,
                demand=_sanitize_quantiles(
                    baseline_preds["r1_demand_totes"]["p10"][idx],
                    baseline_preds["r1_demand_totes"]["p50"][idx],
                    baseline_preds["r1_demand_totes"]["p90"][idx],
                    min_floor=0.0,
                ),
                travel_loaded=_sanitize_quantiles(
                    baseline_preds["travel_loaded_min"]["p10"][idx],
                    baseline_preds["travel_loaded_min"]["p50"][idx],
                    baseline_preds["travel_loaded_min"]["p90"][idx],
                    min_floor=0.1,
                ),
                travel_empty=_sanitize_quantiles(
                    baseline_preds["travel_empty_min"]["p10"][idx],
                    baseline_preds["travel_empty_min"]["p50"][idx],
                    baseline_preds["travel_empty_min"]["p90"][idx],
                    min_floor=0.1,
                ),
                picking_time=_sanitize_quantiles(
                    baseline_preds["picking_min"]["p10"][idx],
                    baseline_preds["picking_min"]["p50"][idx],
                    baseline_preds["picking_min"]["p90"][idx],
                    min_floor=0.1,
                ),
                loading_time=_sanitize_quantiles(
                    baseline_preds["loading_min"]["p10"][idx],
                    baseline_preds["loading_min"]["p50"][idx],
                    baseline_preds["loading_min"]["p90"][idx],
                    min_floor=0.1,
                ),
                unloading_time=_sanitize_quantiles(
                    baseline_preds["unloading_min"]["p10"][idx],
                    baseline_preds["unloading_min"]["p50"][idx],
                    baseline_preds["unloading_min"]["p90"][idx],
                    min_floor=0.1,
                ),
            )
            forecast_points.append(fp)

    return forecast_points
