"""Shared VIIRS CSV row normalizer for local files and NASA HTTP responses."""
import math

from app.data.hotspots import (
    HotspotDataError,
    HotspotRecord,
    _parse_acquired_at,
    stable_external_key,
)


def normalize_viirs_row(row: dict, row_number: int, source_product: str) -> HotspotRecord:
    try:
        latitude, longitude = float(row["latitude"]), float(row["longitude"])
        if not (-90 <= latitude <= 90 and -180 <= longitude <= 180):
            raise ValueError("coordinates")
        acquired_at = _parse_acquired_at(row["acq_date"], row["acq_time"], row_number)
        satellite, instrument = row["satellite"].strip(), row["instrument"].strip()
        if not satellite or instrument != "VIIRS":
            raise ValueError("satellite/instrument")
        raw_frp = row["frp"].strip()
        frp = float(raw_frp) if raw_frp else None
        if frp is not None and (not math.isfinite(frp) or frp < 0):
            raise ValueError("frp")
        confidence = row["confidence"].strip() or None
    except (ValueError, TypeError, AttributeError, KeyError) as exc:
        raise HotspotDataError(f"Invalid VIIRS row {row_number}") from exc
    return HotspotRecord(
        external_key=stable_external_key(
            source_product, acquired_at, latitude, longitude, satellite
        ),
        source_product=source_product, acquired_at=acquired_at,
        latitude=latitude, longitude=longitude, satellite=satellite, instrument=instrument,
        confidence_raw=confidence, frp=frp, source_row_number=row_number,
    )
