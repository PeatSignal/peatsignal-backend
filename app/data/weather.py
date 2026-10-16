"""Recent weather model estimates, explicitly distinct from CHIRPS and field gauges."""

import asyncio
import json
import math
from collections import OrderedDict
from datetime import UTC, date, datetime, timedelta
from time import monotonic

import httpx

from app.data.chirps import AREA_LABELS
from app.data.firms_client import AREAS
from app.schemas.rainfall import ChirpsRainfall, RainfallDay

WEATHER_URL = "https://api.open-meteo.com/v1/forecast"


class WeatherClient:
    def __init__(self, transport: httpx.AsyncBaseTransport | None = None):
        self.transport = transport
        self.cache: OrderedDict[tuple, tuple[float, ChirpsRainfall]] = OrderedDict()

    async def fetch(self, area_id: str, end: date) -> ChirpsRainfall:
        key = (area_id, end)
        if key in self.cache and self.cache[key][0] > monotonic():
            return self.cache[key][1].model_copy(deep=True)
        box, today = AREAS[area_id], datetime.now(UTC).date()
        latitude, longitude = (box.south + box.north) / 2, (box.west + box.east) / 2
        start = end - timedelta(days=6)
        params = {
            "latitude": latitude, "longitude": longitude, "daily": "precipitation_sum",
            "start_date": start.isoformat(), "end_date": end.isoformat(), "timezone": "UTC",
        }
        url = str(httpx.URL(WEATHER_URL, params=params))
        days = [RainfallDay(
            date=start+timedelta(days=i), rainfall_mm=None, source_url=url,
            kind="FORECAST" if start+timedelta(days=i) >= today else "MODEL_ESTIMATE",
            eligible_for_assessment=start+timedelta(days=i) < today,
        ) for i in range(7)]
        status = "ERROR"
        try:
            async with asyncio.timeout(15), httpx.AsyncClient(
                transport=self.transport, timeout=httpx.Timeout(12, connect=5),
                follow_redirects=False,
            ) as client, client.stream("GET", WEATHER_URL, params=params) as response:
                response.raise_for_status()
                raw = bytearray()
                async for chunk in response.aiter_bytes():
                    raw.extend(chunk)
                    if len(raw) > 128 * 1024:
                        raise ValueError("Weather response too large")
            payload = json.loads(raw)
            if (payload["daily_units"]["precipitation_sum"] != "mm"
                    or payload.get("utc_offset_seconds") != 0
                    or abs(payload["latitude"] - latitude) > 0.5
                    or abs(payload["longitude"] - longitude) > 0.5
                    or payload["daily"]["time"] != [row.date.isoformat() for row in days]
                    or len(payload["daily"]["precipitation_sum"]) != 7):
                raise ValueError("Unexpected weather scope or units")
            for row, value in zip(days, payload["daily"]["precipitation_sum"], strict=True):
                if value is not None:
                    if (isinstance(value, bool) or not isinstance(value, (int, float))
                            or not math.isfinite(value) or not 0 <= value <= 1500):
                        raise ValueError("Invalid precipitation")
                    row.rainfall_mm = float(value)
            count = sum(row.rainfall_mm is not None for row in days)
            status = "AVAILABLE" if count == 7 else "PARTIAL" if count else "NOT_AVAILABLE"
        except (httpx.HTTPError, TimeoutError, ValueError, KeyError, TypeError):
            # An invalid response must not leave partially accepted values behind.
            for row in days:
                row.rainfall_mm = None
        note = (
            "Open-Meteo: estimasi model cuaca pada titik acuan wilayah DEMO, bukan CHIRPS "
            "atau pengukuran penakar hujan stasiun. Hari ini masih prakiraan; nilainya "
            "ditampilkan tetapi dikecualikan dari agregasi hujan untuk rekomendasi."
        )
        if status == "ERROR":
            note += " Pengambilan cuaca gagal; data tetap kosong."
        result = ChirpsRainfall(
            status=status, dataset_id="OPEN_METEO_PRECIPITATION", provider="OPEN_METEO",
            scope="REGIONAL_REFERENCE_POINT", area_id=area_id, area_label=AREA_LABELS[area_id],
            bbox=[box.west, box.south, box.east, box.north], reference_point=[longitude, latitude],
            resolution_degrees=None, statistic="MODEL_GRID_POINT", date_from=start, date_to=end,
            retrieved_at=datetime.now(UTC), days=days, note=note,
        )
        self.cache[key] = (
            monotonic() + (60 if status == "ERROR" else 1800), result.model_copy(deep=True),
        )
        self.cache.move_to_end(key)
        while len(self.cache) > 64:
            self.cache.popitem(last=False)
        return result
