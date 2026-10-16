from datetime import UTC, date, datetime, timedelta
from functools import lru_cache
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, HTTPException

from app.data.chirps import ChirpsClient
from app.data.weather import WeatherClient
from app.schemas.rainfall import ChirpsRainfall

router = APIRouter(prefix="/api/v1/rainfall", tags=["rainfall"])


@lru_cache
def get_chirps_client() -> ChirpsClient:
    return ChirpsClient()


@lru_cache
def get_weather_client() -> WeatherClient:
    return WeatherClient()


async def automatic_rainfall(
    area_id: str, end: date, chirps: ChirpsClient, weather: WeatherClient
) -> ChirpsRainfall:
    if end >= datetime.now(UTC).date() - timedelta(days=14):
        return await weather.fetch(area_id, end)
    return await chirps.fetch(area_id, end)


@router.get("/automatic", response_model=ChirpsRainfall)
async def get_automatic_rainfall(
    area_id: Literal["batanghari", "kubu-raya"], date_to: date,
    chirps: Annotated[ChirpsClient, Depends(get_chirps_client)],
    weather: Annotated[WeatherClient, Depends(get_weather_client)],
) -> ChirpsRainfall:
    if date_to > datetime.now(UTC).date() or date_to - timedelta(days=6) < date(1981, 1, 1):
        raise HTTPException(422, "Periode tidak valid.")
    return await automatic_rainfall(area_id, date_to, chirps, weather)


@router.get("/chirps", response_model=ChirpsRainfall)
async def get_chirps_rainfall(
    area_id: Literal["batanghari", "kubu-raya"], date_to: date,
    client: Annotated[ChirpsClient, Depends(get_chirps_client)],
) -> ChirpsRainfall:
    if date_to > datetime.now(UTC).date() or date_to - timedelta(days=6) < date(1981, 1, 1):
        raise HTTPException(422, "Periode harus sejak 1981 dan tidak melewati hari ini (UTC).")
    return await client.fetch(area_id, date_to)
