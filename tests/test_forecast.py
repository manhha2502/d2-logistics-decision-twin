"""Unit tests for Forecast models, metrics, and runtime forecast service."""
import pytest
import numpy as np
import pandas as pd
from datetime import datetime, timedelta
from pathlib import Path
import tempfile

from src.common.schemas import ForecastPoint, QuantileValue
from src.forecast.baseline import NaiveForecast, SeasonalNaiveForecast, ExponentialSmoothingForecast, BaselineSuite
from src.forecast.metrics import mean_absolute_error, wape, pinball_loss, quantile_coverage, evaluate_forecast
from src.forecast.quantile_model import (
    train_target_models,
    train_all_quantile_models,
    predict_step_quantiles,
    save_models,
    load_models,
)
from src.forecast.service import forecast_future_drivers, _sanitize_quantiles
from src.data.features import FEATURE_COLUMNS, TARGET_COLUMNS


@pytest.fixture
def synthetic_series():
    np.random.seed(42)
    return pd.Series(5.0 + np.sin(np.linspace(0, 10, 100)) + np.random.normal(0, 0.2, 100))


@pytest.fixture
def dummy_train_data():
    np.random.seed(42)
    N = 60
    X = pd.DataFrame(np.random.rand(N, len(FEATURE_COLUMNS)), columns=FEATURE_COLUMNS)
    y = pd.DataFrame({
        "r1_demand_totes": 6.0 + np.random.rand(N) * 2,
        "travel_loaded_min": 5.0 + np.random.rand(N),
        "travel_empty_min": 4.0 + np.random.rand(N),
        "picking_min": 3.0 + np.random.rand(N),
        "loading_min": 1.0 + np.random.rand(N),
        "unloading_min": 0.8 + np.random.rand(N),
    })
    return X, y


# 1. Baseline Models Tests
def test_baseline_naive_fit_predict(synthetic_series):
    model = NaiveForecast()
    model.fit(synthetic_series)
    preds = model.predict(horizon=4)
    assert len(preds["p50"]) == 4
    assert np.all(preds["p10"] <= preds["p50"])
    assert np.all(preds["p50"] <= preds["p90"])
    assert np.all(preds["p10"] >= 0.0)


def test_baseline_seasonal_naive(synthetic_series):
    model = SeasonalNaiveForecast(season_length=16)
    model.fit(synthetic_series)
    preds = model.predict(horizon=4)
    assert len(preds["p50"]) == 4
    assert np.all(preds["p10"] <= preds["p90"])


def test_baseline_exponential_smoothing(synthetic_series):
    model = ExponentialSmoothingForecast()
    model.fit(synthetic_series)
    preds = model.predict(horizon=4)
    assert len(preds["p50"]) == 4
    assert np.all(preds["p10"] <= preds["p90"])


# 2. Metrics Tests
def test_forecast_metrics():
    y_true = np.array([10.0, 20.0, 30.0])
    y_pred = np.array([11.0, 19.0, 32.0])

    mae = mean_absolute_error(y_true, y_pred)
    assert pytest.approx(mae, 0.01) == (1.0 + 1.0 + 2.0) / 3.0

    w = wape(y_true, y_pred)
    assert pytest.approx(w, 0.01) == 4.0 / 60.0

    p_loss = pinball_loss(y_true, y_pred, alpha=0.5)
    assert p_loss > 0

    cov = quantile_coverage(y_true, np.array([9.0, 18.0, 25.0]), np.array([12.0, 22.0, 35.0]))
    assert cov == 1.0


# 3. Quantile Regression & Non-crossing Tests
def test_quantile_model_training_and_non_crossing(dummy_train_data):
    X, y = dummy_train_data
    bundle = train_all_quantile_models(X, y, targets=TARGET_COLUMNS, seed=42)
    assert len(bundle) == 6

    step_X = X.iloc[[0]]
    for target in TARGET_COLUMNS:
        q_pred = predict_step_quantiles(bundle, target, step_X)
        assert 0.0 <= q_pred["p10"] <= q_pred["p50"] <= q_pred["p90"]


def test_model_save_and_load(dummy_train_data, tmp_path):
    X, y = dummy_train_data
    bundle = train_all_quantile_models(X, y, targets=TARGET_COLUMNS[:2], seed=42)
    save_file = tmp_path / "test_model.joblib"
    save_models(bundle, save_file)
    assert save_file.is_file()

    loaded = load_models(save_file)
    assert set(loaded.keys()) == set(bundle.keys())


# 4. Service Runtime Tests
def test_service_returns_exact_4_timestamps():
    now_dt = datetime(2026, 10, 8, 14, 0, 0)
    points = forecast_future_drivers(now=now_dt, horizon_min=60, interval_min=15)
    assert len(points) == 4

    expected_times = [
        now_dt + timedelta(minutes=15),
        now_dt + timedelta(minutes=30),
        now_dt + timedelta(minutes=45),
        now_dt + timedelta(minutes=60),
    ]
    assert [p.timestamp for p in points] == expected_times

    # Verify all quantiles are ordered and non-negative
    for pt in points:
        for driver_name in ("demand", "travel_loaded", "travel_empty", "picking_time", "loading_time", "unloading_time"):
            qv = getattr(pt, driver_name)
            assert isinstance(qv, QuantileValue)
            assert 0.0 <= qv.p10 <= qv.p50 <= qv.p90 < float("inf")


def test_service_graceful_fallback(monkeypatch, tmp_path):
    """When ML model file is missing or corrupted, service must fallback to baseline without crashing."""
    # Point model path to non-existent file
    fake_path = tmp_path / "does_not_exist.joblib"
    monkeypatch.setattr("src.forecast.service.MODEL_PATH", fake_path)

    points = forecast_future_drivers(now="2026-10-08 14:00:00")
    assert len(points) == 4
    for pt in points:
        assert pt.demand.p10 <= pt.demand.p50 <= pt.demand.p90
        assert pt.demand.p10 >= 0.0
