import csv
from datetime import UTC, datetime
from pathlib import Path

import pytest

from app.data.groundwater import audit_groundwater
from app.data.hotspots import HotspotDataError, audit_hotspots, iter_hotspots, parse_bbox

DATASET = Path(__file__).resolve().parents[1] / "dataset"


def test_real_workbook_audit_and_conflict_policy() -> None:
    audit = audit_groundwater(DATASET / "mmc1.xlsx")
    assert audit.report == audit_groundwater(DATASET / "mmc1.xlsx").report
    assert (audit.report["raw_rows"], audit.report["unique_observations"]) == (3929, 3928)
    assert audit.report["valid"] == 3534
    assert audit.report["missing"] == 393
    assert audit.report["duplicate_conflicts"] == 1
    assert audit.report["station_count"] == 8
    assert audit.report["archived_wrc_rows"] == 110
    conflict = audit.report["duplicates"][0]
    assert conflict["observed_date"] == "2019-03-21"
    assert [row["gwt_m"] for row in conflict["rows"]] == [-0.362, -0.316]
    record = next(r for r in audit.records if r.quality_flag == "DUPLICATE")
    assert record.gwt_m is None


@pytest.fixture
def viirs_file(tmp_path: Path) -> Path:
    path = tmp_path / "viirs-snpp_test.csv"
    with path.open("w", newline="", encoding="utf-8") as file:
        writer = csv.writer(file)
        writer.writerow([
            "latitude", "longitude", "acq_date", "acq_time", "satellite",
            "instrument", "confidence", "frp",
        ])
        writer.writerow([-1, 103, "2019-01-01", "0055", "N", "VIIRS", "n", 0])
        writer.writerow([-1, 103, "2019-01-01", "0055", "N", "VIIRS", "n", 0])
        writer.writerow([-2, 110, "2019-01-02", "0455", "N", "VIIRS", "l", ""])
    return path


def test_viirs_utc_dedup_null_zero_and_bbox(viirs_file: Path) -> None:
    records = list(iter_hotspots(viirs_file))
    assert records[0].acquired_at == datetime(2019, 1, 1, 0, 55, tzinfo=UTC)
    assert records[0].frp == 0
    assert records[2].frp is None
    assert records[0].external_key == records[1].external_key
    audit = audit_hotspots(viirs_file)
    assert (audit["rows"], audit["unique_external_keys"], audit["duplicate_external_keys"]) == (
        3, 2, 1
    )
    assert len(list(iter_hotspots(viirs_file, bbox=parse_bbox("102,-1.5,104,0")))) == 2


@pytest.mark.parametrize("value", ["a,b,c,d", "1,2,3", "4,0,3,1", "0,1,2,0", "nan,0,2,1"])
def test_invalid_bbox_is_rejected(value: str) -> None:
    with pytest.raises(HotspotDataError):
        parse_bbox(value)
