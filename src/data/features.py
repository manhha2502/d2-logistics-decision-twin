"""Feature engineering pipeline for demand and logistics time series forecasting."""
import pandas as pd
import numpy as np
from typing import Tuple, List, Optional

SHIFT_MAPPING = {
    "SHIFT_A": 0,
    "SHIFT_B": 1,
    "SHIFT_C": 2,
}

FEATURE_COLUMNS = [
    "hour",
    "day_of_week",
    "is_weekend",
    "shift_code",
    "planned_output_units",
    "demand_lag_1",
    "demand_lag_2",
    "demand_lag_4",
    "travel_loaded_lag_1",
    "travel_loaded_lag_2",
    "travel_loaded_lag_4",
    "picking_lag_1",
    "picking_lag_4",
    "queue_lag_1",
    "demand_rolling_mean_4",
    "demand_rolling_mean_8",
    "travel_rolling_mean_4",
    "buffer_mat_a",
    "buffer_mat_b",
    "r1_amr_available",
]

TARGET_COLUMNS = [
    "r1_demand_totes",
    "travel_loaded_min",
    "travel_empty_min",
    "picking_min",
    "loading_min",
    "unloading_min",
]


def encode_shift(shift_series: pd.Series) -> pd.Series:
    """Encode categorical shift string to integer code."""
    return shift_series.map(SHIFT_MAPPING).fillna(0).astype(int)


def extract_features(df: pd.DataFrame) -> pd.DataFrame:
    """Extract strictly historical lag, rolling, and calendar features.

    CRITICAL: All lags and rolling windows apply .shift(1) to avoid future data leakage.
    Features at timestamp t only depend on data at or prior to t-1, with planned_output_units
    and calendar attributes known ahead of time.
    """
    feat = pd.DataFrame(index=df.index)
    ts = pd.to_datetime(df["timestamp"])

    # Calendar features
    feat["hour"] = ts.dt.hour
    feat["day_of_week"] = ts.dt.dayofweek
    feat["is_weekend"] = df["is_weekend"].astype(int)
    feat["shift_code"] = encode_shift(df["shift"]) if "shift" in df.columns else 0

    # Exogenous production plan (known driver)
    feat["planned_output_units"] = df["planned_output_units"].astype(float)

    # Lags for Target 1: r1_demand_totes
    demand = df["r1_demand_totes"]
    feat["demand_lag_1"] = demand.shift(1)
    feat["demand_lag_2"] = demand.shift(2)
    feat["demand_lag_4"] = demand.shift(4)

    # Lags for Target 2: travel_loaded_min
    travel = df["travel_loaded_min"]
    feat["travel_loaded_lag_1"] = travel.shift(1)
    feat["travel_loaded_lag_2"] = travel.shift(2)
    feat["travel_loaded_lag_4"] = travel.shift(4)

    # Lags for Target 3: picking_min
    picking = df["picking_min"]
    feat["picking_lag_1"] = picking.shift(1)
    feat["picking_lag_4"] = picking.shift(4)

    # Lags for queue state
    if "r1_queue_start_totes" in df.columns:
        feat["queue_lag_1"] = df["r1_queue_start_totes"].shift(1)
    else:
        feat["queue_lag_1"] = 0.0

    # Rolling statistics (strictly lagged by 1 to prevent leakage)
    feat["demand_rolling_mean_4"] = demand.shift(1).rolling(window=4, min_periods=1).mean()
    feat["demand_rolling_mean_8"] = demand.shift(1).rolling(window=8, min_periods=1).mean()
    feat["travel_rolling_mean_4"] = travel.shift(1).rolling(window=4, min_periods=1).mean()

    # System state features (lagged)
    if "buffer_mat_a_end_totes" in df.columns:
        feat["buffer_mat_a"] = df["buffer_mat_a_end_totes"].shift(1)
    else:
        feat["buffer_mat_a"] = 15.0

    if "buffer_mat_b_end_totes" in df.columns:
        feat["buffer_mat_b"] = df["buffer_mat_b_end_totes"].shift(1)
    else:
        feat["buffer_mat_b"] = 15.0

    if "r1_amr_available" in df.columns:
        feat["r1_amr_available"] = df["r1_amr_available"].shift(1)
    else:
        feat["r1_amr_available"] = 3

    # Backfill earliest initial rows where shift created NaNs
    feat = feat.bfill().ffill()

    return feat[FEATURE_COLUMNS]


def build_training_dataset(df: pd.DataFrame) -> Tuple[pd.DataFrame, pd.DataFrame]:
    """Generate X feature matrix and y target matrix for model training."""
    X = extract_features(df)
    y = df[TARGET_COLUMNS].copy()

    # Drop any initial rows if NaN persists
    valid_idx = X.dropna().index.intersection(y.dropna().index)
    return X.loc[valid_idx].reset_index(drop=True), y.loc[valid_idx].reset_index(drop=True)


def build_step_inference_features(
    timestamp: pd.Timestamp,
    planned_output_units: float,
    recent_history: pd.DataFrame,
    shift_str: str = "SHIFT_B",
    is_weekend: int = 0,
) -> pd.DataFrame:
    """Build feature row for a single future inference step using known plan and recent history."""
    row = {}
    ts = pd.to_datetime(timestamp)

    row["hour"] = ts.hour
    row["day_of_week"] = ts.dayofweek
    row["is_weekend"] = int(is_weekend)
    row["shift_code"] = SHIFT_MAPPING.get(shift_str, 0)
    row["planned_output_units"] = float(planned_output_units)

    # History values
    demand_series = recent_history["r1_demand_totes"]
    travel_series = recent_history["travel_loaded_min"]
    picking_series = recent_history["picking_min"]

    row["demand_lag_1"] = float(demand_series.iloc[-1])
    row["demand_lag_2"] = float(demand_series.iloc[-2]) if len(demand_series) >= 2 else float(demand_series.iloc[-1])
    row["demand_lag_4"] = float(demand_series.iloc[-4]) if len(demand_series) >= 4 else float(demand_series.iloc[-1])

    row["travel_loaded_lag_1"] = float(travel_series.iloc[-1])
    row["travel_loaded_lag_2"] = float(travel_series.iloc[-2]) if len(travel_series) >= 2 else float(travel_series.iloc[-1])
    row["travel_loaded_lag_4"] = float(travel_series.iloc[-4]) if len(travel_series) >= 4 else float(travel_series.iloc[-1])

    row["picking_lag_1"] = float(picking_series.iloc[-1])
    row["picking_lag_4"] = float(picking_series.iloc[-4]) if len(picking_series) >= 4 else float(picking_series.iloc[-1])

    if "r1_queue_start_totes" in recent_history.columns:
        row["queue_lag_1"] = float(recent_history["r1_queue_start_totes"].iloc[-1])
    else:
        row["queue_lag_1"] = 0.0

    row["demand_rolling_mean_4"] = float(demand_series.iloc[-4:].mean())
    row["demand_rolling_mean_8"] = float(demand_series.iloc[-8:].mean())
    row["travel_rolling_mean_4"] = float(travel_series.iloc[-4:].mean())

    if "buffer_mat_a_end_totes" in recent_history.columns:
        row["buffer_mat_a"] = float(recent_history["buffer_mat_a_end_totes"].iloc[-1])
    else:
        row["buffer_mat_a"] = 15.0

    if "buffer_mat_b_end_totes" in recent_history.columns:
        row["buffer_mat_b"] = float(recent_history["buffer_mat_b_end_totes"].iloc[-1])
    else:
        row["buffer_mat_b"] = 15.0

    if "r1_amr_available" in recent_history.columns:
        row["r1_amr_available"] = float(recent_history["r1_amr_available"].iloc[-1])
    else:
        row["r1_amr_available"] = 3.0

    return pd.DataFrame([row])[FEATURE_COLUMNS]
