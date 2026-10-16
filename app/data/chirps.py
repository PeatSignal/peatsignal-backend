"""CHIRPS v2 regional daily means via ClimateSERV, linked by the UCSB producer."""

import asyncio
import json
import math
from collections import OrderedDict
from datetime import UTC, date, datetime, timedelta
from time import monotonic
from uuid import UUID

import httpx

from app.data.firms_client import AREAS
from app.schemas.rainfall import ChirpsRainfall, RainfallDay

API = "https://climateserv.servirglobal.net/api"
AREA_LABELS = {"batanghari": "Batanghari", "kubu-raya": "Kubu Raya"}
# Both calibrated stations are in Batanghari (the source dataset supplies no coordinates).
STATION_RAINFALL_AREAS = {"BRG3": "batanghari", "BRG6": "batanghari"}
MAX_RESPONSE = 256 * 1024


def parse_days(payload: dict, start: date, end: date, source_url: str) -> list[RainfallDay]:
    if (not isinstance(payload, dict) or not isinstance(payload.get("data"), list)
            or payload.get("datatype", 0) != 0 or payload.get("operationtype", 5) != 5
            or payload.get("intervaltype", 0) != 0):
        raise ValueError("Unexpected CHIRPS result")
    values = {}
    for row in payload["data"]:
        # Use the dataset's date label, never reinterpret local-day epoch timestamps.
        day = datetime.strptime(row["date"], "%m/%d/%Y").date()
        if day < start or day > end or day in values:
            raise ValueError("CHIRPS result has duplicate or out-of-window dates")
        raw = row["value"].get("avg")
        if isinstance(raw, bool):
            raise ValueError("Invalid rainfall value")
        value = None if raw is None else float(raw)
        if value is not None and (not math.isfinite(value) or not 0 <= value <= 1500):
            value = None  # NoData (-9999), not a zero-rainfall observation.
        values[day] = value
    return [RainfallDay(
        date=start + timedelta(days=i), rainfall_mm=values.get(start + timedelta(days=i)),
        source_url=source_url,
    ) for i in range(7)]


class ChirpsClient:
    def __init__(self, transport: httpx.AsyncBaseTransport | None = None):
        self.transport = transport
        self.cache: OrderedDict[tuple, tuple[float, ChirpsRainfall]] = OrderedDict()
        self.jobs: OrderedDict[tuple, tuple[str, float]] = OrderedDict()
        self.lock = asyncio.Lock()

    async def _get(self, client: httpx.AsyncClient, method: str, params: dict):
        async with client.stream("GET", f"{API}/{method}/", params=params) as response:
            response.raise_for_status()
            raw = bytearray()
            async for chunk in response.aiter_bytes():
                raw.extend(chunk)
                if len(raw) > MAX_RESPONSE:
                    raise ValueError("CHIRPS API response is too large")
        return json.loads(raw)

    async def fetch(self, area_id: str, end: date) -> ChirpsRainfall:
        key = (area_id, end)
        cached = self.cache.get(key)
        if cached and cached[0] > monotonic():
            return cached[1].model_copy(deep=True)
        start, box = end - timedelta(days=6), AREAS[area_id]
        source_url = f"{API}/submitDataRequest/"
        days = [RainfallDay(date=start + timedelta(days=i), rainfall_mm=None,
                           source_url=source_url) for i in range(7)]
        status = "PENDING"
        job_id = None
        try:
            async with asyncio.timeout(25), self.lock, httpx.AsyncClient(
                transport=self.transport, timeout=httpx.Timeout(8, connect=5),
                follow_redirects=False,
            ) as client:
                # Recheck after waiting for another request to finish the same job.
                cached = self.cache.get(key)
                if cached and cached[0] > monotonic():
                    return cached[1].model_copy(deep=True)
                if key not in self.jobs:
                    polygon = {"type": "Polygon", "coordinates": [[
                        [box.west, box.south], [box.east, box.south],
                        [box.east, box.north], [box.west, box.north], [box.west, box.south],
                    ]]}
                    submitted = await self._get(client, "submitDataRequest", {
                        "datatype": 0, "begintime": start.strftime("%m/%d/%Y"),
                        "endtime": end.strftime("%m/%d/%Y"), "intervaltype": 0,
                        "operationtype": 5, "geometry": json.dumps(polygon),
                    })
                    if not isinstance(submitted, list) or len(submitted) != 1:
                        raise ValueError("Invalid CHIRPS job")
                    job_id = str(UUID(submitted[0]))
                    self.jobs[key] = (job_id, monotonic())
                    while len(self.jobs) > 64:
                        self.jobs.popitem(last=False)
                job_id, created = self.jobs[key]
                source_url = f"{API}/getDataFromRequest/?id={job_id}"
                if monotonic() - created > 120:
                    raise ValueError("CHIRPS job timed out")
                # Bound each request; a subsequent request resumes the same server job.
                for _ in range(8):
                    progress = await self._get(client, "getDataRequestProgress", {"id": job_id})
                    if not isinstance(progress, list) or len(progress) != 1:
                        raise ValueError("Invalid CHIRPS progress")
                    percent = float(progress[0])
                    if not math.isfinite(percent) or not 0 <= percent <= 100:
                        raise ValueError("Failed CHIRPS job")
                    if percent == 100:
                        payload = await self._get(client, "getDataFromRequest", {"id": job_id})
                        if payload.get("uid", job_id) != job_id:
                            raise ValueError("CHIRPS job identity mismatch")
                        days = parse_days(payload, start, end, source_url)
                        count = sum(row.rainfall_mm is not None for row in days)
                        status = "AVAILABLE" if count == 7 else (
                            "PARTIAL" if count else "NOT_AVAILABLE"
                        )
                        self.jobs.pop(key, None)
                        break
                    await asyncio.sleep(1)
        except TimeoutError:
            status = "PENDING" if key in self.jobs else "ERROR"
        except (httpx.HTTPError, ValueError, KeyError, TypeError, OverflowError):
            status = "ERROR"
            self.jobs.pop(key, None)
        note = (
            "CHIRPS v2 via ClimateSERV: estimasi hujan rata-rata piksel wilayah DEMO; "
            "bukan pengukuran di titik stasiun. "
        )
        note += {
            "AVAILABLE": "Ketujuh tanggal sesuai input tersedia.",
            "PARTIAL": "Sebagian tanggal belum tersedia; nilai kosong tidak dianggap nol.",
            "NOT_AVAILABLE": "Periode ini belum tersedia. CHIRPS Final memiliki jeda publikasi.",
            "PENDING": "Sumber masih memproses; pengecekan berikutnya memakai job yang sama.",
            "ERROR": "Sumber CHIRPS sedang terganggu. Nilai yang tidak didapat tetap kosong.",
        }[status]
        result = ChirpsRainfall(
            status=status, area_id=area_id, area_label=AREA_LABELS[area_id],
            bbox=[box.west, box.south, box.east, box.north], date_from=start, date_to=end,
            retrieved_at=datetime.now(UTC), days=days, note=note, job_id=job_id,
        )
        if status != "PENDING":
            ttl = 60 if status == "ERROR" else 900 if status != "AVAILABLE" else 21600
            self.cache[key] = (monotonic() + ttl, result)
            self.cache.move_to_end(key)
            while len(self.cache) > 64:
                self.cache.popitem(last=False)
        return result
