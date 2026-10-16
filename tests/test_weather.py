import asyncio
from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock

import httpx
import pytest
from test_prevention import payload

from app.api.routes.rainfall import automatic_rainfall
from app.data.weather import WeatherClient
from app.ml.artifacts import MlArtifactStore
from app.ml.field_service import FieldForecastService
from app.schemas.prevention import PreventionRequest


def weather_payload():
    end = datetime.now(UTC).date()
    return {
        "latitude": -1.75, "longitude": 103.45, "utc_offset_seconds": 0,
        "daily_units": {"precipitation_sum": "mm"},
        "daily": {
            "time": [(end-timedelta(days=6-i)).isoformat() for i in range(7)],
            "precipitation_sum": [5.9, 1, 2.2, 4.4, 0, 0, 12],
        },
    }


def fetch(data):
    client = WeatherClient(httpx.MockTransport(lambda _: httpx.Response(200, json=data)))
    return asyncio.run(client.fetch("batanghari", datetime.now(UTC).date()))


def test_current_weather_keeps_forecast_separate_from_completed_days(tmp_path):
    result = fetch(weather_payload())
    assert result.status == "AVAILABLE"
    assert result.provider == "OPEN_METEO"
    assert result.scope == "REGIONAL_REFERENCE_POINT"
    assert result.days[-1].rainfall_mm == 12
    assert result.days[-1].kind == "FORECAST"
    assert not result.days[-1].eligible_for_assessment
    assert all(day.eligible_for_assessment for day in result.days[:-1])
    body = payload(rain=999)
    body["rainfall_mode"] = "AUTO"
    assessment = FieldForecastService(MlArtifactStore(tmp_path)).assess(
        PreventionRequest.model_validate(body), rainfall=result,
    )
    assert assessment.readings[0].rainfall_mm == 5.9
    assert assessment.readings[-1].rainfall_mm is None
    assert assessment.prevention.rainfall_days == 6
    assert assessment.prevention.rainfall_7d_mm is None
    assert assessment.prevention.dry_spell_days is None


@pytest.mark.parametrize("invalid", ["dates", "unit", "location", "bool", "negative"])
def test_bad_weather_response_cannot_become_dry_weather(invalid):
    data = weather_payload()
    if invalid == "dates":
        data["daily"]["time"].reverse()
    elif invalid == "unit":
        data["daily_units"]["precipitation_sum"] = "inch"
    elif invalid == "location":
        data["latitude"] = 20
    else:
        data["daily"]["precipitation_sum"][-1] = True if invalid == "bool" else -1
    result = fetch(data)
    assert result.status == "ERROR"
    assert all(day.rainfall_mm is None for day in result.days)


def test_missing_values_and_real_zeros_remain_distinct():
    data = weather_payload()
    data["daily"]["precipitation_sum"][0] = None
    result = fetch(data)
    assert result.status == "PARTIAL"
    assert result.days[0].rainfall_mm is None
    assert result.days[4].rainfall_mm == 0


def test_weather_cache_avoids_repeated_upstream_requests():
    calls = []

    def handler(request):
        calls.append(request)
        return httpx.Response(200, json=weather_payload())

    client = WeatherClient(httpx.MockTransport(handler))

    async def run():
        first = await client.fetch("batanghari", datetime.now(UTC).date())
        first.days[0].rainfall_mm = 999
        second = await client.fetch("batanghari", datetime.now(UTC).date())
        return second

    # Caller mutations must not alter cached data.
    result = asyncio.run(run())
    assert len(calls) == 1
    assert result.days[0].rainfall_mm == 5.9


def test_automatic_source_routes_recent_and_historical_without_mixing():
    chirps, weather = AsyncMock(), AsyncMock()
    today = datetime.now(UTC).date()

    async def run():
        await automatic_rainfall("batanghari", today, chirps, weather)
        await automatic_rainfall("batanghari", today-timedelta(days=15), chirps, weather)

    asyncio.run(run())
    weather.fetch.assert_awaited_once_with("batanghari", today)
    chirps.fetch.assert_awaited_once_with("batanghari", today-timedelta(days=15))
