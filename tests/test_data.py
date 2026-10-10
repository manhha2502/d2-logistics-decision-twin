"""Unit tests for Data Loader, Data Validator, and Feature Engineering."""
import pytest
import pandas as pd
import numpy as np
from pathlib import Path

from src.data.loader import load_training_data, load_recent_history
from src.data.validator import validate_training_data, DataValidationError
from src.data.features import (
    extract_features,
    build_training_dataset,
    build_step_inference_features,
    FEATURE_COLUMNS,
    TARGET_COLUMNS,
)


@pytest.fixture
def sample_raw_df():
    """Create a minimal valid DataFrame resembling training data."""
    dates = pd.date_range("2026-08-01 08:00:00", periods=20, freq="15min")
    df = pd.DataFrame({
        "timestamp": dates,
        "shift": ["SHIFT_A"] * 20,
        "is_weekend": [0] * 20,
        "planned_output_units": [37.5] * 20,
        "r1_demand_totes": [6.5 + i * 0.1 for i in range(20)],
        "travel_loaded_min": [5.2] * 20,
        "travel_empty_min": [4.3] * 20,
        "picking_min": [3.1] * 20,
        "loading_min": [1.2] * 20,
        "unloading_min": [0.9] * 20,
        "r1_amr_available": [3] * 20,
        "r1_avg_battery_pct": [75.0] * 20,
        "r1_queue_start_totes": [0.0] * 20,
        "buffer_mat_a_end_totes": [18.0] * 20,
        "buffer_mat_b_end_totes": [15.0] * 20,
    })
    return df


def test_loader_real_dataset():
    """Verify loading real model training dataset."""
    df = load_training_data("data/model_ready/model_training_15min.csv")
    assert not df.empty
    assert len(df) > 5000
    assert df["timestamp"].is_monotonic_increasing
    assert all(col in df.columns for col in TARGET_COLUMNS)


def test_loader_recent_history():
    """Verify loading slice up to snapshot time."""
    history = load_recent_history(now="2026-10-08 14:00:00", window_steps=16)
    assert len(history) == 16
    assert history["timestamp"].max() <= pd.to_datetime("2026-10-08 14:00:00")


def test_validator_detects_flaws(sample_raw_df):
    """Validator must detect duplicates, negatives, missing targets, and invalid battery."""
    # 1. Clean data passes
    assert validate_training_data(sample_raw_df, strict=False) == []

    # 2. Negative demand
    bad_df = sample_raw_df.copy()
    bad_df.loc[3, "r1_demand_totes"] = -1.5
    with pytest.raises(DataValidationError, match="negative values in 'r1_demand_totes'"):
        validate_training_data(bad_df, strict=True)

    # 3. Non-positive travel time
    bad_df = sample_raw_df.copy()
    bad_df.loc[5, "travel_loaded_min"] = 0.0
    with pytest.raises(DataValidationError, match="non-positive"):
        validate_training_data(bad_df, strict=True)

    # 4. Out of bounds battery
    bad_df = sample_raw_df.copy()
    bad_df.loc[2, "r1_avg_battery_pct"] = 120.0
    with pytest.raises(DataValidationError, match="outside \\[0, 100\\]"):
        validate_training_data(bad_df, strict=True)

    # 5. Duplicate timestamp
    bad_df = sample_raw_df.copy()
    bad_df.loc[1, "timestamp"] = bad_df.loc[0, "timestamp"]
    with pytest.raises(DataValidationError, match="duplicate timestamps"):
        validate_training_data(bad_df, strict=True)


def test_features_no_future_leakage(sample_raw_df):
    """Modifying future values must NOT alter past or present feature representations."""
    feats_original = extract_features(sample_raw_df)

    # Alter future targets in raw dataframe (rows 10 to 19)
    manipulated_df = sample_raw_df.copy()
    manipulated_df.loc[10:, "r1_demand_totes"] = 999.0
    manipulated_df.loc[10:, "travel_loaded_min"] = 888.0
    feats_manipulated = extract_features(manipulated_df)

    # Rows 0 through 9 must be completely identical
    pd.testing.assert_frame_equal(feats_original.iloc[:10], feats_manipulated.iloc[:10])


def test_features_dataset_generation(sample_raw_df):
    """Verify build_training_dataset returns matching X and y shapes."""
    X, y = build_training_dataset(sample_raw_df)
    assert len(X) == len(y)
    assert list(X.columns) == FEATURE_COLUMNS
    assert list(y.columns) == TARGET_COLUMNS
    assert not X.isna().any().any()
    assert not y.isna().any().any()


def test_build_step_inference_features(sample_raw_df):
    """Verify single step inference feature extraction."""
    inf_feat = build_step_inference_features(
        timestamp=pd.Timestamp("2026-10-08 14:15:00"),
        planned_output_units=50.85,
        recent_history=sample_raw_df.iloc[-10:],
        shift_str="SHIFT_B",
    )
    assert len(inf_feat) == 1
    assert list(inf_feat.columns) == FEATURE_COLUMNS
    assert inf_feat["planned_output_units"].iloc[0] == 50.85
