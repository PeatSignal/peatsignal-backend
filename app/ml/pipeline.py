from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from typing import TYPE_CHECKING, Any

from app.data.groundwater import GroundwaterRecord
from app.schemas.common import QualityFlag

if TYPE_CHECKING:
    from pathlib import Path

FEATURE_NAMES = (
    "lag_1_m",
    "lag_3_m",
    "lag_7_m",
    "rolling_mean_3_shifted_m",
    "rolling_mean_7_shifted_m",
    "delta_1_m",
    "delta_3_m",
    "delta_7_m",
)
RANDOM_STATE = 2026
PIPELINE_VERSION = "gwt-rf-v1"
TRAIN_FRACTION = 0.70
VALIDATION_FRACTION = 0.15
MIN_SPLIT_ROWS = 30
LEAF_CANDIDATES = (2, 5, 10, 20)


class MlDataError(ValueError):
    pass


class MlDependencyError(RuntimeError):
    pass


@dataclass(frozen=True)
class FeatureRow:
    target_date: date
    features: tuple[float, ...]
    actual_gwt_m: float
    baseline_gwt_m: float


@dataclass(frozen=True)
class ChronologicalSplit:
    train: tuple[FeatureRow, ...]
    validation: tuple[FeatureRow, ...]
    test: tuple[FeatureRow, ...]


def build_feature_rows(
    records: tuple[GroundwaterRecord, ...], station_code: str
) -> tuple[FeatureRow, ...]:
    """Build target-day rows using only the seven preceding calendar days.

    Missing, duplicate, or absent dates break the sequence. No interpolation is performed.
    """
    normalized_station = station_code.strip().upper()
    values = {
        record.observed_date: record.gwt_m
        for record in records
        if record.station_code == normalized_station
        and record.quality_flag is QualityFlag.VALID
        and record.gwt_m is not None
    }
    if not values:
        raise MlDataError(f"No valid observations for station {normalized_station}")

    rows: list[FeatureRow] = []
    for target_date, target in sorted(values.items()):
        try:
            features = build_forecast_features(values, target_date)
        except MlDataError:
            continue
        lag_1 = features[0]
        rows.append(
            FeatureRow(
                target_date=target_date,
                features=features,
                actual_gwt_m=float(target),
                baseline_gwt_m=lag_1,
            )
        )
    return tuple(rows)


def build_forecast_features(values: dict[date, float], target_date: date) -> tuple[float, ...]:
    prior = [values.get(target_date - timedelta(days=lag)) for lag in range(1, 8)]
    if any(value is None for value in prior):
        raise MlDataError("Seven consecutive valid calendar days are required")
    lag_values = tuple(float(value) for value in prior if value is not None)
    lag_1 = lag_values[0]
    return (
        lag_1,
        lag_values[2],
        lag_values[6],
        sum(lag_values[:3]) / 3,
        sum(lag_values) / 7,
        lag_1 - lag_values[1],
        lag_1 - lag_values[2],
        lag_1 - lag_values[6],
    )


def chronological_split(rows: tuple[FeatureRow, ...]) -> ChronologicalSplit:
    if tuple(sorted(rows, key=lambda row: row.target_date)) != rows:
        raise MlDataError("Feature rows must be ordered chronologically")
    train_end = int(len(rows) * TRAIN_FRACTION)
    validation_end = int(len(rows) * (TRAIN_FRACTION + VALIDATION_FRACTION))
    split = ChronologicalSplit(
        train=rows[:train_end],
        validation=rows[train_end:validation_end],
        test=rows[validation_end:],
    )
    if min(len(split.train), len(split.validation), len(split.test)) < MIN_SPLIT_ROWS:
        raise MlDataError(
            "At least 30 complete rows are required in each chronological split"
        )
    return split


def _require_ml_dependencies() -> tuple[Any, Any, Any, Any]:
    try:
        import numpy as np
        from sklearn.ensemble import RandomForestRegressor
        from sklearn.metrics import mean_absolute_error, root_mean_squared_error
    except ImportError as exc:
        raise MlDependencyError(
            "ML dependencies are unavailable; install the backend project dependencies"
        ) from exc
    return np, RandomForestRegressor, mean_absolute_error, root_mean_squared_error


def _arrays(np: Any, rows: tuple[FeatureRow, ...]) -> tuple[Any, Any, Any]:
    features = np.asarray([row.features for row in rows], dtype=float)
    actual = np.asarray([row.actual_gwt_m for row in rows], dtype=float)
    baseline = np.asarray([row.baseline_gwt_m for row in rows], dtype=float)
    return features, actual, baseline


def _metrics(
    actual: Any, predicted: Any, mean_absolute_error: Any, root_mean_squared_error: Any
) -> dict[str, float]:
    return {
        "mae_cm": float(mean_absolute_error(actual, predicted) * 100),
        "rmse_cm": float(root_mean_squared_error(actual, predicted) * 100),
    }


def train_station_experiment(
    records: tuple[GroundwaterRecord, ...], station_code: str, source_sha256: str
) -> tuple[Any, dict[str, Any]]:
    """Tune on validation, refit on train+validation, and evaluate once on test.

    The forest predicts the next-day change from lag 1. The persisted GWT value remains the
    baseline. Both predictions are evaluated against the exact same target dates.
    """
    np, random_forest, mean_absolute_error, root_mean_squared_error = (
        _require_ml_dependencies()
    )
    normalized_station = station_code.strip().upper()
    rows = build_feature_rows(records, normalized_station)
    split = chronological_split(rows)
    train_x, train_y, train_baseline = _arrays(np, split.train)
    validation_x, validation_y, validation_baseline = _arrays(np, split.validation)

    candidates: list[dict[str, float | int]] = []
    for min_samples_leaf in LEAF_CANDIDATES:
        candidate = random_forest(
            n_estimators=300,
            min_samples_leaf=min_samples_leaf,
            max_features=0.8,
            random_state=RANDOM_STATE,
            n_jobs=1,
        )
        candidate.fit(train_x, train_y - train_baseline)
        predicted = validation_baseline + candidate.predict(validation_x)
        candidates.append(
            {
                "min_samples_leaf": min_samples_leaf,
                **_metrics(
                    validation_y, predicted, mean_absolute_error, root_mean_squared_error
                ),
            }
        )
    selected = min(candidates, key=lambda item: (item["mae_cm"], item["min_samples_leaf"]))

    fit_rows = split.train + split.validation
    fit_x, fit_y, fit_baseline = _arrays(np, fit_rows)
    model = random_forest(
        n_estimators=300,
        min_samples_leaf=int(selected["min_samples_leaf"]),
        max_features=0.8,
        random_state=RANDOM_STATE,
        n_jobs=1,
    )
    model.fit(fit_x, fit_y - fit_baseline)

    test_x, test_y, test_baseline = _arrays(np, split.test)
    test_prediction = test_baseline + model.predict(test_x)
    model_metrics = _metrics(
        test_y, test_prediction, mean_absolute_error, root_mean_squared_error
    )
    baseline_metrics = _metrics(
        test_y, test_baseline, mean_absolute_error, root_mean_squared_error
    )
    configuration = {
        "algorithm": "RandomForestRegressor",
        "pipeline_version": PIPELINE_VERSION,
        "target": "next_day_change_from_lag_1",
        "features": list(FEATURE_NAMES),
        "random_state": RANDOM_STATE,
        "n_estimators": 300,
        "max_features": 0.8,
        "min_samples_leaf": int(selected["min_samples_leaf"]),
        "source_sha256": source_sha256,
        "station_code": normalized_station,
    }
    version_hash = hashlib.sha256(
        json.dumps(configuration, sort_keys=True).encode("utf-8")
    ).hexdigest()[:12]
    result: dict[str, Any] = {
        "model_version": f"gwt-rf-{normalized_station.lower()}-{version_hash}",
        "station_code": normalized_station,
        "source_sha256": source_sha256,
        "label": "HASIL EKSPERIMEN HISTORIS",
        "training_from": fit_rows[0].target_date.isoformat(),
        "training_to": fit_rows[-1].target_date.isoformat(),
        "test_from": split.test[0].target_date.isoformat(),
        "test_to": split.test[-1].target_date.isoformat(),
        "train_size": len(split.train),
        "validation_size": len(split.validation),
        "test_size": len(split.test),
        **model_metrics,
        "baseline_mae_cm": baseline_metrics["mae_cm"],
        "baseline_rmse_cm": baseline_metrics["rmse_cm"],
        "beats_baseline": model_metrics["mae_cm"] < baseline_metrics["mae_cm"],
        "features": list(FEATURE_NAMES),
        "selected_parameters": {
            "n_estimators": 300,
            "max_features": 0.8,
            "min_samples_leaf": int(selected["min_samples_leaf"]),
            "random_state": RANDOM_STATE,
        },
        "validation_candidates": candidates,
        "predictions": [
            {
                "date": row.target_date.isoformat(),
                "actual_gwt_m": row.actual_gwt_m,
                "predicted_gwt_m": float(predicted),
                "baseline_gwt_m": row.baseline_gwt_m,
            }
            for row, predicted in zip(split.test, test_prediction, strict=True)
        ],
        "release_gate": (
            "EXPERIMENT_ONLY" if model_metrics["mae_cm"] >= baseline_metrics["mae_cm"]
            else "ELIGIBLE_FOR_HISTORICAL_FORECAST"
        ),
        "limitations": [
            "Data GWT hanya historis 2018-2019 dan bukan kondisi 2026.",
            "Baris dengan missing, duplikat, atau lag kalender tidak lengkap dikeluarkan.",
            "Model tidak digunakan oleh decision engine jika tidak mengalahkan baseline.",
        ],
    }
    return model, result


def write_experiment_result(result: dict[str, Any], output_path: Path) -> None:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(
        json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def write_model_artifact(model: Any, result: dict[str, Any], output_dir: Path) -> Path:
    try:
        import joblib
    except ImportError as exc:
        raise MlDependencyError(
            "ML dependencies are unavailable; install the backend project dependencies"
        ) from exc
    output_dir.mkdir(parents=True, exist_ok=True)
    artifact_path = output_dir / f"{result['model_version']}.joblib"
    joblib.dump(model, artifact_path)
    result["artifact_file"] = artifact_path.name
    result["trained_at"] = datetime.now(UTC).isoformat()
    return artifact_path
