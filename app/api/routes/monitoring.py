from datetime import date
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Path, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.data.hotspots import BoundingBox, HotspotDataError, parse_bbox
from app.db.session import get_async_db
from app.repositories.monitoring import MonitoringRepository
from app.schemas.common import MonitoringMode
from app.schemas.groundwater import GroundwaterObservation
from app.schemas.hotspot import HotspotMap, HotspotPage
from app.schemas.station import Station

router = APIRouter(prefix="/api/v1")


async def get_monitoring_repository(
    session: Annotated[AsyncSession, Depends(get_async_db)],
) -> MonitoringRepository:
    return MonitoringRepository(session)


def validate_date_range(date_from: date | None, date_to: date | None) -> None:
    if date_from is not None and date_to is not None and date_from > date_to:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail="'from' must be on or before 'to'",
        )


def parse_optional_bbox(value: str | None) -> BoundingBox | None:
    if value is None:
        return None
    try:
        return parse_bbox(value)
    except HotspotDataError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail=str(exc),
        ) from exc


@router.get("/stations", response_model=list[Station], tags=["groundwater"])
async def list_stations(
    repository: Annotated[MonitoringRepository, Depends(get_monitoring_repository)],
) -> list[Station]:
    return await repository.list_stations()


@router.get(
    "/stations/{station_id}/groundwater",
    response_model=list[GroundwaterObservation],
    tags=["groundwater"],
)
async def list_groundwater(
    repository: Annotated[MonitoringRepository, Depends(get_monitoring_repository)],
    station_id: Annotated[UUID, Path()],
    date_from: Annotated[date | None, Query(alias="from")] = None,
    date_to: Annotated[date | None, Query(alias="to")] = None,
    mode: MonitoringMode = MonitoringMode.HISTORICAL_REPLAY,
) -> list[GroundwaterObservation]:
    validate_date_range(date_from, date_to)
    if not await repository.station_exists(station_id):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Station not found")
    return await repository.list_groundwater(
        station_id,
        date_from=date_from,
        date_to=date_to,
        mode=mode,
    )


@router.get("/hotspots", response_model=HotspotPage, tags=["hotspots"])
async def list_hotspots(
    repository: Annotated[MonitoringRepository, Depends(get_monitoring_repository)],
    date_from: Annotated[date | None, Query(alias="from")] = None,
    date_to: Annotated[date | None, Query(alias="to")] = None,
    bbox: str | None = None,
    satellite: str | None = None,
    source_product: str | None = None,
    mode: MonitoringMode = MonitoringMode.HISTORICAL_REPLAY,
    limit: Annotated[int, Query(ge=1, le=1000)] = 200,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> HotspotPage:
    validate_date_range(date_from, date_to)
    parsed_bbox = parse_optional_bbox(bbox)
    return await repository.list_hotspots(
        date_from=date_from,
        date_to=date_to,
        bbox=parsed_bbox,
        satellite=satellite,
        source_product=source_product,
        mode=mode,
        limit=limit,
        offset=offset,
    )


@router.get("/hotspots/map", response_model=HotspotMap, tags=["hotspots"])
async def hotspot_map(
    repository: Annotated[MonitoringRepository, Depends(get_monitoring_repository)],
    date_from: Annotated[date | None, Query(alias="from")] = None,
    date_to: Annotated[date | None, Query(alias="to")] = None,
    bbox: str | None = None,
    satellite: str | None = None,
    source_product: str | None = None,
    mode: MonitoringMode = MonitoringMode.HISTORICAL_REPLAY,
) -> HotspotMap:
    validate_date_range(date_from, date_to)
    return await repository.hotspot_map(
        date_from=date_from, date_to=date_to, bbox=parse_optional_bbox(bbox),
        satellite=satellite, source_product=source_product, mode=mode,
    )
