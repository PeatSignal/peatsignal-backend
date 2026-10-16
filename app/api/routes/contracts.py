from typing import Annotated

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.db.session import get_async_db
from app.ml.artifacts import MlArtifactStore
from app.ml.service import MlService
from app.repositories.ml import MlRepository
from app.schemas.ml import MlForecastRequest, MlForecastResponse, MlMetricsResponse

router = APIRouter(prefix="/api/v1")


def get_ml_service(
    session: Annotated[AsyncSession, Depends(get_async_db)],
) -> MlService:
    return MlService(MlRepository(session), MlArtifactStore(get_settings().ml_artifact_dir))


@router.get("/ml/metrics", response_model=MlMetricsResponse, tags=["ml"])
async def list_ml_metrics(
    service: Annotated[MlService, Depends(get_ml_service)],
) -> MlMetricsResponse:
    return await service.metrics()


@router.post("/ml/forecast", response_model=MlForecastResponse, tags=["ml"])
async def forecast(
    payload: MlForecastRequest,
    service: Annotated[MlService, Depends(get_ml_service)],
) -> MlForecastResponse:
    return await service.forecast(payload)

