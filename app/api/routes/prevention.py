from typing import Annotated

from fastapi import APIRouter, Depends
from starlette.concurrency import run_in_threadpool

from app.api.routes.rainfall import automatic_rainfall, get_chirps_client, get_weather_client
from app.core.config import get_settings
from app.data.chirps import STATION_RAINFALL_AREAS, ChirpsClient
from app.data.weather import WeatherClient
from app.ml.artifacts import MlArtifactStore
from app.ml.field_service import FieldForecastService
from app.schemas.prevention import PreventionRequest, PreventionResponse

router = APIRouter(prefix="/api/v1", tags=["prevention"])


def get_field_service() -> FieldForecastService:
    return FieldForecastService(MlArtifactStore(get_settings().ml_artifact_dir))


@router.post("/prevention/assess", response_model=PreventionResponse)
async def assess_field_measurements(
    payload: PreventionRequest,
    service: Annotated[FieldForecastService, Depends(get_field_service)],
    chirps: Annotated[ChirpsClient, Depends(get_chirps_client)],
    weather: Annotated[WeatherClient, Depends(get_weather_client)],
) -> PreventionResponse:
    rainfall = None
    if payload.rainfall_mode == "CHIRPS":
        rainfall = await chirps.fetch(
            STATION_RAINFALL_AREAS[payload.station_code], payload.readings[-1].date
        )
    elif payload.rainfall_mode == "AUTO":
        rainfall = await automatic_rainfall(
            STATION_RAINFALL_AREAS[payload.station_code], payload.readings[-1].date,
            chirps, weather,
        )
    return await run_in_threadpool(service.assess, payload, rainfall)
