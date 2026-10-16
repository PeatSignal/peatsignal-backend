from datetime import UTC, datetime
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, HTTPException
from pydantic import AwareDatetime
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.session import get_async_db
from app.repositories.priorities import PriorityRepository
from app.schemas.common import MonitoringMode
from app.schemas.priority import PriorityAssessment

router = APIRouter(prefix="/api/v1", tags=["priorities"])


@router.get("/priorities", response_model=list[PriorityAssessment])
async def list_priorities(
    mode: MonitoringMode,
    as_of: AwareDatetime,
    session: Annotated[AsyncSession, Depends(get_async_db)],
    area_id: Literal["batanghari", "kubu-raya"] | None = None,
) -> list[PriorityAssessment]:
    cutoff = as_of.astimezone(UTC)
    if cutoff > datetime.now(UTC):
        raise HTTPException(422, "as_of tidak boleh berada di masa depan")
    repository = PriorityRepository(session)
    results = [await repository.assess(mode, cutoff, area)
               for area in ([area_id] if area_id else ["batanghari", "kubu-raya"])]
    await session.commit()
    return results
