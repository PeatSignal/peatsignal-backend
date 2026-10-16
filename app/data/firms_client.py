import asyncio
import csv
import io
import logging
import re
from dataclasses import dataclass
from datetime import date

import httpx

from app.data.hotspots import REQUIRED_COLUMNS, BoundingBox, HotspotDataError, HotspotRecord
from app.data.viirs_rows import normalize_viirs_row
from app.schemas.firms import SyncRequest

AREAS = {
    "batanghari": BoundingBox(102.9, -2.2, 104.0, -1.3),
    "kubu-raya": BoundingBox(108.9, -1.2, 110.0, 0.3),
}
SYNC_AREAS = {**AREAS, "indonesia": BoundingBox(94.0, -11.5, 141.5, 6.5)}
MAX_RESPONSE_BYTES = 20 * 1024 * 1024


class RedactFirmsKey(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        record.msg = re.sub(
            r"(/api/area/csv/)[^/\s]+", r"\1[REDACTED]", record.getMessage()
        )
        record.args = ()
        return True


for logger_name in ("httpx", "httpcore"):
    logging.getLogger(logger_name).addFilter(RedactFirmsKey())


class FirmsError(Exception):
    def __init__(self, code: str, status_code: int, detail: str, retry_after: int | None = None):
        super().__init__(detail)
        self.code = code
        self.status_code = status_code
        self.detail = detail
        self.retry_after = retry_after


@dataclass(frozen=True)
class FirmsResponse:
    raw: bytes
    records: list[HotspotRecord]


def parse_response(raw: bytes, request: SyncRequest, date_from: date, date_to: date):
    try:
        reader = csv.DictReader(io.StringIO(raw.decode("utf-8-sig")))
        if not REQUIRED_COLUMNS.issubset(set(reader.fieldnames or [])):
            raise ValueError("CSV header")
        records = []
        bbox = SYNC_AREAS[request.area_id]
        expected_satellites = {"N", "SNPP", "Suomi-NPP"} if "SNPP" in request.source_product else {
            "N20", "NOAA-20", "1", "JPSS-1"
        }
        for row_number, row in enumerate(reader, 2):
            if None in row or any(value is None for value in row.values()):
                raise ValueError("CSV row shape")
            record = normalize_viirs_row(row, row_number, request.source_product)
            if (
                not date_from <= record.acquired_at.date() <= date_to
                or not bbox.contains(record.latitude, record.longitude)
                or record.satellite not in expected_satellites
            ):
                raise ValueError("CSV scope")
            records.append(record)
        return records
    except (UnicodeDecodeError, ValueError, csv.Error, HotspotDataError) as exc:
        raise FirmsError("INVALID_RESPONSE", 502, "Respons CSV NASA FIRMS tidak valid.") from exc


class FirmsClient:
    def __init__(self, key: str | None, transport: httpx.AsyncBaseTransport | None = None):
        self.key = key
        self.transport = transport

    async def fetch(
        self, request: SyncRequest, date_from: date, date_to: date
    ) -> FirmsResponse:
        if not self.key:
            raise FirmsError("KEY_NOT_CONFIGURED", 503, "Key NASA FIRMS belum dikonfigurasi.")
        box = SYNC_AREAS[request.area_id]
        bbox = ",".join(str(v) for v in (box.west, box.south, box.east, box.north))
        # Explicit start date fixes the UTC window even when the request crosses midnight.
        url = (
            "https://firms.modaps.eosdis.nasa.gov/api/area/csv/"
            f"{self.key}/{request.source_product}/{bbox}/{request.day_range}/{date_from}"
        )
        try:
            async with asyncio.timeout(30), httpx.AsyncClient(
                transport=self.transport, timeout=httpx.Timeout(30, connect=5),
                follow_redirects=False,
            ) as client:
                async with client.stream("GET", url) as response:
                    if response.status_code != 200:
                        raise FirmsError("UPSTREAM_HTTP", 502, "NASA FIRMS gagal merespons.")
                    length = response.headers.get("content-length", "")
                    if length.isdigit() and int(length) > MAX_RESPONSE_BYTES:
                        raise FirmsError("RESPONSE_TOO_LARGE", 502, "Respons NASA terlalu besar.")
                    raw = bytearray()
                    async for chunk in response.aiter_bytes():
                        raw.extend(chunk)
                        if len(raw) > MAX_RESPONSE_BYTES:
                            raise FirmsError(
                                "RESPONSE_TOO_LARGE", 502, "Respons NASA terlalu besar."
                            )
            payload = bytes(raw)
            return FirmsResponse(payload, parse_response(payload, request, date_from, date_to))
        except (TimeoutError, httpx.TimeoutException) as exc:
            raise FirmsError("UPSTREAM_TIMEOUT", 504, "NASA FIRMS melewati batas waktu.") from exc
        except httpx.HTTPError as exc:
            raise FirmsError("UPSTREAM_NETWORK", 502, "Koneksi NASA FIRMS gagal.") from exc
