from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException

from app.core.config import get_settings
from app.core.security import require_roles
from app.data.firms_client import FirmsClient, FirmsError
from app.data.firms_sync import FirmsSyncService
from app.db.session import async_engine
from app.schemas.common import UserRole
from app.schemas.firms import AreaId, FirmsProduct, SyncRequest, SyncResult, SyncStatus
from app.schemas.user import User

router = APIRouter(prefix="/api/v1", tags=["firms"])


async def get_firms_service() -> FirmsSyncService:
    return FirmsSyncService(async_engine, FirmsClient(get_settings().firms_map_key))


@router.post("/admin/hotspots/sync", response_model=SyncResult)
async def sync_hotspots(
    payload: SyncRequest,
    user: Annotated[User, Depends(require_roles(UserRole.COORDINATOR))],
    service: Annotated[FirmsSyncService, Depends(get_firms_service)],
) -> SyncResult:
    try:
        return await service.sync(payload, user.id)
    except FirmsError as exc:
        headers = {"Retry-After": str(exc.retry_after)} if exc.retry_after else None
        raise HTTPException(exc.status_code, detail=exc.detail, headers=headers) from None


@router.get("/hotspots/sync-status", response_model=list[SyncStatus])
async def sync_status(
    service: Annotated[FirmsSyncService, Depends(get_firms_service)],
    area_id: AreaId | None = None,
    source_product: FirmsProduct | None = None,
) -> list[SyncStatus]:
    return await service.statuses(area_id, source_product)
