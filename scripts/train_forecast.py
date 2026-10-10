"""Offline training script for D2 Logistics Decision Twin forecast models.

Usage:
    python scripts/train_forecast.py
"""
import sys
from pathlib import Path

# Add project root to path
PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

import pandas as pd
import numpy as np

from src.data.loader import load_training_data
from src.data.validator import validate_training_data
from src.data.features import build_training_dataset, TARGET_COLUMNS
from src.forecast.quantile_model import train_all_quantile_models, save_models, predict_step_quantiles
from src.forecast.baseline import BaselineSuite, NaiveForecast
from src.forecast.metrics import evaluate_forecast
from src.forecast.service import forecast_future_drivers


def main():
    print("=" * 70)
    print("  D2 Logistics Decision Twin — Offline Forecast Training Pipeline")
    print("=" * 70)

    # 1. Load data
    data_path = PROJECT_ROOT / "data/model_ready/model_training_15min.csv"
    print(f"\n[1/6] Loading dataset from: {data_path}")
    df = load_training_data(data_path)
    print(f"      Loaded {len(df):,} records spanning from {df['timestamp'].min()} to {df['timestamp'].max()}.")

    # 2. Validate data
    print("\n[2/6] Validating dataset integrity...")
    validate_training_data(df, strict=True)
    print("      Validation passed: no missing targets, no duplicates, valid batteries and process times.")

    # 3. Build features
    print("\n[3/6] Generating feature matrix (lags, rolling stats, calendar, planned output)...")
    X, y = build_training_dataset(df)
    print(f"      Feature matrix shape: {X.shape}, Target matrix shape: {y.shape}")

    # 4. Chronological Train/Validation Split (85% train, 15% validation)
    split_idx = int(len(X) * 0.85)
    X_train, X_val = X.iloc[:split_idx], X.iloc[split_idx:]
    y_train, y_val = y.iloc[:split_idx], y.iloc[split_idx:]
    print(f"      Train set: {len(X_train):,} rows | Validation set: {len(X_val):,} rows")

    # 5. Train LightGBM Quantile models (6 targets x 3 quantiles = 18 models)
    print("\n[4/6] Training LightGBM Quantile Models (alpha = 0.1, 0.5, 0.9)...")
    models_bundle = train_all_quantile_models(X_train, y_train, targets=TARGET_COLUMNS, seed=42)
    print("      Successfully trained 18 quantile regression models.")

    # Fit baseline suite for fallback
    print("      Fitting Baseline Suite (fallback)...")
    baseline_suite = BaselineSuite(model_class=NaiveForecast)
    baseline_suite.fit(y_train, TARGET_COLUMNS)

    # 6. Evaluate on Validation Set
    print("\n[5/6] Evaluating on Validation Set:")
    print("-" * 75)
    print(f"{'Target Variable':<22} | {'MAE':<8} | {'WAPE (%)':<10} | {'Pinball P50':<12} | {'Coverage (80%)':<12}")
    print("-" * 75)

    for target in TARGET_COLUMNS:
        p10 = models_bundle[target][0.1].predict(X_val)
        p50 = models_bundle[target][0.5].predict(X_val)
        p90 = models_bundle[target][0.9].predict(X_val)

        # Enforce non-crossing for metrics
        p10 = np.maximum(0.0, p10)
        p50 = np.maximum(p10, p50)
        p90 = np.maximum(p50, p90)

        preds = {"p10": p10, "p50": p50, "p90": p90}
        metrics = evaluate_forecast(y_val[target], preds)

        print(
            f"{target:<22} | {metrics['mae']:<8.4f} | {metrics['wape'] * 100:<9.2f}% | "
            f"{metrics['pinball_p50']:<12.4f} | {metrics['coverage'] * 100:<11.2f}%"
        )
    print("-" * 75)

    # 7. Retrain on full dataset and save artifact
    print("\n[6/6] Retraining on full dataset and saving model artifacts...")
    full_models_bundle = train_all_quantile_models(X, y, targets=TARGET_COLUMNS, seed=42)

    model_dir = PROJECT_ROOT / "artifacts/models"
    model_dir.mkdir(parents=True, exist_ok=True)

    model_out = model_dir / "forecast_models.joblib"
    save_models(full_models_bundle, model_out)
    print(f"      Artifact saved: {model_out} ({model_out.stat().st_size / 1024:.1f} KB)")

    # 8. Smoke Test inference service
    print("\n[Smoke Test] Testing forecast_future_drivers() with real models...")
    points = forecast_future_drivers(now="2026-10-08 14:00:00")
    print(f"      Received {len(points)} ForecastPoints:")
    for pt in points:
        print(f"      * {pt.timestamp} | Demand P10/P50/P90: [{pt.demand.p10:.2f}, {pt.demand.p50:.2f}, {pt.demand.p90:.2f}] | Loaded Travel: [{pt.travel_loaded.p10:.2f}, {pt.travel_loaded.p50:.2f}, {pt.travel_loaded.p90:.2f}]")

    print("\n>>> TRAINING COMPLETED SUCCESSFULLY! <<<")


if __name__ == "__main__":
    main()
