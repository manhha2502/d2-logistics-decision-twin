"""Data validation rules for logistics and forecast training datasets."""
import pandas as pd
from typing import List

TARGET_COLUMNS = [
    "r1_demand_totes",
    "travel_loaded_min",
    "travel_empty_min",
    "picking_min",
    "loading_min",
    "unloading_min",
]

PROCESS_TIME_COLUMNS = [
    "travel_loaded_min",
    "travel_empty_min",
    "picking_min",
    "loading_min",
    "unloading_min",
]


class DataValidationError(ValueError):
    """Raised when dataset contains critical validation flaws."""
    pass


def validate_training_data(df: pd.DataFrame, strict: bool = True) -> List[str]:
    """Validate DataFrame for duplicates, missing targets, out-of-bound battery, and negative values.

    Returns a list of warning/error messages.
    If `strict=True`, raises DataValidationError if any error exists.
    """
    errors: List[str] = []

    # 1. Check duplicate timestamps
    if "timestamp" in df.columns:
        dup_count = df.duplicated("timestamp").sum()
        if dup_count > 0:
            errors.append(f"Found {dup_count} duplicate timestamps in dataset")

    # 2. Check missing values in target columns
    for target in TARGET_COLUMNS:
        if target in df.columns:
            null_count = df[target].isna().sum()
            if null_count > 0:
                errors.append(f"Target '{target}' has {null_count} null or missing values")
        else:
            errors.append(f"Required target column '{target}' is missing from DataFrame")

    # 3. Check non-negativity for demand
    if "r1_demand_totes" in df.columns:
        neg_demand = (df["r1_demand_totes"] < 0).sum()
        if neg_demand > 0:
            errors.append(f"Found {neg_demand} negative values in 'r1_demand_totes'")

    # 4. Check strictly positive process/travel times
    for col in PROCESS_TIME_COLUMNS:
        if col in df.columns:
            non_pos = (df[col] <= 0).sum()
            if non_pos > 0:
                errors.append(f"Found {non_pos} non-positive values (<= 0) in process time '{col}'")

    # 5. Check battery bounds [0, 100]
    if "r1_avg_battery_pct" in df.columns:
        out_of_bounds = ((df["r1_avg_battery_pct"] < 0) | (df["r1_avg_battery_pct"] > 100)).sum()
        if out_of_bounds > 0:
            errors.append(f"Found {out_of_bounds} values outside [0, 100] in 'r1_avg_battery_pct'")

    # 6. Check invalid counts/quantities (AMR, queue, buffer)
    for col in ["r1_amr_available", "r1_queue_start_totes", "buffer_mat_a_end_totes", "buffer_mat_b_end_totes"]:
        if col in df.columns:
            neg_count = (df[col] < 0).sum()
            if neg_count > 0:
                errors.append(f"Found {neg_count} negative values in count/state column '{col}'")

    if strict and errors:
        raise DataValidationError("; ".join(errors))

    return errors
