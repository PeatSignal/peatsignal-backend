import csv
import hashlib
import math
from collections import Counter
from collections.abc import Iterator
from dataclasses import dataclass
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Any

from sqlalchemy import select, text
from sqlalchemy.orm import Session

from app.data.common import sha256_file
from app.models.entities import DataImportRun, DataSource

AUDIT_VERSION = "viirs-audit-v1"
REQUIRED_COLUMNS = {
    "latitude",
    "longitude",
    "acq_date",
    "acq_time",
    "satellite",
    "instrument",
    "confidence",
    "frp",
}


class HotspotDataError(ValueError):
    pass


@dataclass(frozen=True)
class BoundingBox:
    west: float
    south: float
    east: float
    north: float

    def __post_init__(self) -> None:
        if not all(math.isfinite(v) for v in (self.west, self.south, self.east, self.north)):
            raise HotspotDataError("bbox coordinates must be finite")
        if not (-180 <= self.west < self.east <= 180):
            raise HotspotDataError("bbox longitude must satisfy -180 <= west < east <= 180")
        if not (-90 <= self.south < self.north <= 90):
            raise HotspotDataError("bbox latitude must satisfy -90 <= south < north <= 90")

    def contains(self, latitude: float, longitude: float) -> bool:
        return self.west <= longitude <= self.east and self.south <= latitude <= self.north


@dataclass(frozen=True)
class HotspotRecord:
    external_key: str
    source_product: str
    acquired_at: datetime
    latitude: float
    longitude: float
    satellite: str
    instrument: str
    confidence_raw: str | None
    frp: float | None
    source_row_number: int


def parse_bbox(value: str) -> BoundingBox:
    try:
        values = [float(part.strip()) for part in value.split(",")]
    except ValueError as exc:
        raise HotspotDataError("bbox must contain four comma-separated numbers") from exc
    if len(values) != 4:
        raise HotspotDataError("bbox must use west,south,east,north")
    return BoundingBox(*values)


def infer_source_product(path: Path) -> str:
    name = path.name.lower()
    if "jpss1" in name:
        return "VIIRS_NOAA20_HISTORICAL"
    if "snpp" in name:
        return "VIIRS_SNPP_HISTORICAL"
    raise HotspotDataError(f"Cannot infer VIIRS product from filename: {path.name}")


def stable_external_key(
    source_product: str,
    acquired_at: datetime,
    latitude: float,
    longitude: float,
    satellite: str,
) -> str:
    canonical = "|".join(
        (
            source_product,
            acquired_at.astimezone(UTC).isoformat(),
            f"{latitude:.5f}",
            f"{longitude:.5f}",
            satellite,
        )
    )
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def _parse_acquired_at(raw_date: str, raw_time: str, row_number: int) -> datetime:
    time_value = raw_time.strip().zfill(4)
    try:
        return datetime.strptime(
            f"{raw_date.strip()} {time_value}", "%Y-%m-%d %H%M"
        ).replace(tzinfo=UTC)
    except ValueError as exc:
        raise HotspotDataError(f"Invalid acquisition time at CSV row {row_number}") from exc


def iter_hotspots(
    path: str | Path,
    *,
    date_from: date | None = None,
    date_to: date | None = None,
    bbox: BoundingBox | None = None,
) -> Iterator[HotspotRecord]:
    source_path = Path(path).resolve()
    if date_from and date_to and date_from > date_to:
        raise HotspotDataError("date_from must be on or before date_to")
    source_product = infer_source_product(source_path)
    with source_path.open(newline="", encoding="utf-8-sig") as source:
        reader = csv.DictReader(source)
        columns = set(reader.fieldnames or ())
        missing_columns = REQUIRED_COLUMNS - columns
        if missing_columns:
            raise HotspotDataError(f"Missing required CSV columns: {sorted(missing_columns)}")

        for row_number, row in enumerate(reader, start=2):
            from app.data.viirs_rows import normalize_viirs_row

            record = normalize_viirs_row(row, row_number, source_product)
            if date_from and record.acquired_at.date() < date_from:
                continue
            if date_to and record.acquired_at.date() > date_to:
                continue
            if bbox and not bbox.contains(record.latitude, record.longitude):
                continue
            yield record


def audit_hotspots(
    path: str | Path,
    *,
    date_from: date | None = None,
    date_to: date | None = None,
    bbox: BoundingBox | None = None,
) -> dict[str, Any]:
    source_path = Path(path).resolve()
    source_hash = sha256_file(source_path)
    counts: Counter[str] = Counter()
    first_acquired_at: datetime | None = None
    last_acquired_at: datetime | None = None
    seen: set[str] = set()
    duplicates = 0
    for record in iter_hotspots(
        source_path,
        date_from=date_from,
        date_to=date_to,
        bbox=bbox,
    ):
        counts["rows"] += 1
        counts[f"satellite:{record.satellite}"] += 1
        counts[f"instrument:{record.instrument}"] += 1
        counts[f"confidence:{record.confidence_raw or 'null'}"] += 1
        counts["frp_null"] += record.frp is None
        if record.external_key in seen:
            duplicates += 1
        else:
            seen.add(record.external_key)
        first_acquired_at = min(first_acquired_at or record.acquired_at, record.acquired_at)
        last_acquired_at = max(last_acquired_at or record.acquired_at, record.acquired_at)

    if sha256_file(source_path) != source_hash:
        raise HotspotDataError("Source file changed during audit")
    return {
        "audit_version": AUDIT_VERSION,
        "source": {
            "name": source_path.name,
            "sha256": source_hash,
            "source_product": infer_source_product(source_path),
        },
        "filters": {
            "from": date_from.isoformat() if date_from else None,
            "to": date_to.isoformat() if date_to else None,
            "bbox": (
                [bbox.west, bbox.south, bbox.east, bbox.north] if bbox is not None else None
            ),
        },
        "rows": counts["rows"],
        "unique_external_keys": len(seen),
        "duplicate_external_keys": duplicates,
        "first_acquired_at": first_acquired_at.isoformat() if first_acquired_at else None,
        "last_acquired_at": last_acquired_at.isoformat() if last_acquired_at else None,
        "frp_null": counts["frp_null"],
        "satellites": {
            key.removeprefix("satellite:"): value
            for key, value in sorted(counts.items())
            if key.startswith("satellite:")
        },
        "instruments": {
            key.removeprefix("instrument:"): value
            for key, value in sorted(counts.items())
            if key.startswith("instrument:")
        },
        "confidence_raw": {
            key.removeprefix("confidence:"): value
            for key, value in sorted(counts.items())
            if key.startswith("confidence:")
        },
    }


def import_hotspots(
    session: Session,
    path: str | Path,
    *,
    date_from: date | None = None,
    date_to: date | None = None,
    bbox: BoundingBox | None = None,
) -> dict[str, Any]:
    source_path = Path(path).resolve()
    audit = audit_hotspots(source_path, date_from=date_from, date_to=date_to, bbox=bbox)
    source_hash = audit["source"]["sha256"]
    source = session.scalar(select(DataSource).where(DataSource.sha256 == source_hash))
    if source is None:
        source = DataSource(
            name=source_path.name,
            url=source_path.as_posix(),
            sha256=source_hash,
        )
        session.add(source)
        session.flush()

    import_run = DataImportRun(
        source_id=source.id,
        dataset_kind="HOTSPOT",
        status="STARTED",
        rows_seen=audit["rows"],
        rows_inserted=0,
        rows_skipped=0,
        audit_json=audit,
    )
    session.add(import_run)
    session.flush()

    connection = session.connection()
    driver_connection = connection.connection.driver_connection
    imported_at = datetime.now(UTC)
    with driver_connection.cursor() as cursor:
        cursor.execute(
            """
            CREATE TEMP TABLE hotspot_import_stage (
                external_key text NOT NULL,
                source_product text NOT NULL,
                acquired_at timestamptz NOT NULL,
                latitude double precision NOT NULL,
                longitude double precision NOT NULL,
                satellite text NOT NULL,
                instrument text NOT NULL,
                confidence_raw text,
                frp double precision,
                source_row_number integer NOT NULL
            ) ON COMMIT DROP
            """
        )
        with cursor.copy(
            """
            COPY hotspot_import_stage (
                external_key, source_product, acquired_at, latitude, longitude,
                satellite, instrument, confidence_raw, frp, source_row_number
            ) FROM STDIN
            """
        ) as copy:
            for record in iter_hotspots(
                source_path,
                date_from=date_from,
                date_to=date_to,
                bbox=bbox,
            ):
                copy.write_row(
                    (
                        record.external_key,
                        record.source_product,
                        record.acquired_at,
                        record.latitude,
                        record.longitude,
                        record.satellite,
                        record.instrument,
                        record.confidence_raw,
                        record.frp,
                        record.source_row_number,
                    )
                )

    result = session.execute(
        text(
            """
            WITH inserted AS (INSERT INTO hotspots (
                external_key, source_product, sensor, satellite, acquired_at, geom,
                frp, confidence_raw, quality_flag, mode, source_row_number,
                verification_status, source_id, last_synced_at
            )
            SELECT
                external_key, source_product, instrument, satellite, acquired_at,
                ST_SetSRID(ST_MakePoint(longitude, latitude), 4326), frp,
                confidence_raw, 'VALID', 'HISTORICAL_REPLAY', source_row_number,
                'UNVERIFIED', :source_id, :imported_at
            FROM hotspot_import_stage
            ON CONFLICT (external_key) DO NOTHING
            RETURNING id)
            SELECT count(*) FROM inserted
            """
        ),
        {"source_id": source.id, "imported_at": imported_at},
    )
    inserted = result.scalar_one()
    if sha256_file(source_path) != source_hash:
        raise HotspotDataError("Source file changed during import; transaction must roll back")
    session.execute(text("DROP TABLE hotspot_import_stage"))
    import_run.status = "COMPLETED"
    import_run.rows_inserted = inserted
    import_run.rows_skipped = audit["rows"] - inserted
    import_run.completed_at = datetime.now(UTC)
    session.flush()
    return {
        "source_sha256": source_hash,
        "rows_seen": audit["rows"],
        "rows_inserted": inserted,
        "rows_skipped": audit["rows"] - inserted,
    }
