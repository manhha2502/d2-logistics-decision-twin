"""Data loader for D2 Logistics Decision Twin training and inference history."""
from datetime import datetime
from pathlib import Path
from typing import Union
import pandas as pd

REQUIRED_TRAINING_COLUMNS = [
    "timestamp",
    "shift",
    "is_weekend",
    "planned_output_units",
    "r1_demand_totes",
    "travel_loaded_min",
    "travel_empty_min",
    "picking_min",
    "loading_min",
    "unloading_min",
    "r1_amr_available",
    "r1_queue_start_totes",
    "buffer_mat_a_end_totes",
    "buffer_mat_b_end_totes",
]


def load_training_data(file_path: Union[str, Path] = "data/model_ready/model_training_15min.csv") -> pd.DataFrame:
    """Load model-ready 15min training data, parse timestamp, sort chronologically, and validate columns."""
    path = Path(file_path)
    if not path.is_file():
        raise FileNotFoundError(f"Training data file not found: {path}")

    df = pd.read_csv(path)
    if "timestamp" not in df.columns:
        raise ValueError("Missing 'timestamp' column in data")

    df["timestamp"] = pd.to_datetime(df["timestamp"])
    df = df.sort_values("timestamp").reset_index(drop=True)

    missing_cols = [c for c in REQUIRED_TRAINING_COLUMNS if c not in df.columns]
    if missing_cols:
        raise ValueError(f"Missing required columns in training data: {missing_cols}")

    return df


def load_recent_history(
    now: Union[datetime, str, pd.Timestamp],
    window_steps: int = 32,
    file_path: Union[str, Path] = "data/model_ready/model_training_15min.csv",
) -> pd.DataFrame:
    """Load historical data up to `now` and return the latest `window_steps` rows for lag computation."""
    df = load_training_data(file_path)
    now_dt = pd.to_datetime(now)
    history_df = df[df["timestamp"] <= now_dt].copy()

    if history_df.empty:
        raise ValueError(f"No historical records found at or before {now_dt}")

    if len(history_df) > window_steps:
        history_df = history_df.iloc[-window_steps:].reset_index(drop=True)

    return history_df


def load_future_production_plan(
    file_path: Union[str, Path] = "data/known_future/future_production_plan_15min.csv",
) -> pd.DataFrame:
    """Load future production plan, parse timestamp, and sort chronologically."""
    path = Path(file_path)
    if not path.is_file():
        raise FileNotFoundError(f"Production plan file not found: {path}")

    df = pd.read_csv(path)
    if "timestamp" not in df.columns:
        raise ValueError("Missing 'timestamp' column in production plan")

    df["timestamp"] = pd.to_datetime(df["timestamp"])
    df = df.sort_values("timestamp").reset_index(drop=True)
    return df
