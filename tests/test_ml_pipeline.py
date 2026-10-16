from datetime import date, timedelta
from pathlib import Path

import pytest

from app.data.groundwater import GroundwaterRecord, audit_groundwater
from app.ml.pipeline import (
    FEATURE_NAMES,
    MlDataError,
    build_feature_rows,
    chronological_split,
    train_station_experiment,
)
from app.schemas.common import QualityFlag


def _record(day: date, value: float | None, quality: QualityFlag = QualityFlag.VALID):
    return GroundwaterRecord(
        observed_date=day,
        gwt_m=value,
        station_code="BRG6",
        region="Demo",
        quality_flag=quality,
        source_row_number=1,
    )


def test_features_use_preceding_days_and_shifted_rolling_values():
    start = date(2019, 1, 1)
    records = tuple(_record(start + timedelta(days=offset), float(offset)) for offset in range(8))

    rows = build_feature_rows(records, "brg6")

    assert len(rows) == 1
    assert rows[0].target_date == date(2019, 1, 8)
    assert rows[0].actual_gwt_m == 7
    assert rows[0].baseline_gwt_m == 6
    assert rows[0].features == (6, 4, 0, 5, 3, 1, 2, 6)
    assert len(rows[0].features) == len(FEATURE_NAMES)


def test_missing_value_breaks_sequence_instead_of_becoming_zero():
    start = date(2019, 1, 1)
    records = tuple(
        _record(
            start + timedelta(days=offset),
            None if offset == 4 else float(offset),
            QualityFlag.MISSING if offset == 4 else QualityFlag.VALID,
        )
        for offset in range(12)
    )

    assert build_feature_rows(records, "BRG6") == ()


def test_chronological_split_rejects_small_or_unsorted_dataset():
    start = date(2019, 1, 1)
    records = tuple(_record(start + timedelta(days=offset), float(offset)) for offset in range(220))
    rows = build_feature_rows(records, "BRG6")
    split = chronological_split(rows)

    assert split.train[-1].target_date < split.validation[0].target_date
    assert split.validation[-1].target_date < split.test[0].target_date
    with pytest.raises(MlDataError, match="ordered chronologically"):
        chronological_split(tuple(reversed(rows)))
    with pytest.raises(MlDataError, match="30 complete rows"):
        chronological_split(rows[:100])


def test_real_candidates_train_reproducibly_and_compare_identical_test_dates():
    pytest.importorskip("sklearn")
    dataset_path = Path(__file__).parents[1] / "dataset" / "mmc1.xlsx"
    audit = audit_groundwater(dataset_path)

    for station in ("BRG6", "BRG3"):
        _, first = train_station_experiment(
            audit.records, station, audit.report["source"]["sha256"]
        )
        _, second = train_station_experiment(
            audit.records, station, audit.report["source"]["sha256"]
        )

        assert first["model_version"] == second["model_version"]
        assert first["mae_cm"] == pytest.approx(second["mae_cm"])
        assert first["predictions"] == second["predictions"]
        assert len(first["predictions"]) == first["test_size"]
        assert all(point["date"] >= first["test_from"] for point in first["predictions"])
        assert all(point["date"] <= first["test_to"] for point in first["predictions"])
        assert first["label"] == "HASIL EKSPERIMEN HISTORIS"
        assert first["release_gate"] in {
            "EXPERIMENT_ONLY",
            "ELIGIBLE_FOR_HISTORICAL_FORECAST",
        }
