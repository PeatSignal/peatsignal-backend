from datetime import date
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.entities import GroundwaterObservation, Station
from app.schemas.common import MonitoringMode, QualityFlag


class MlRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def station_ids_by_codes(self, codes: list[str]) -> dict[str, str]:
        rows = (
            await self.session.execute(
                select(Station.code, Station.id).where(Station.code.in_(codes))
            )
        ).all()
        return {code: str(station_id) for code, station_id in rows}

    async def station_code(self, station_id: UUID) -> str | None:
        return await self.session.scalar(select(Station.code).where(Station.id == station_id))

    async def valid_history(
        self, station_id: UUID, date_from: date, date_to: date
    ) -> dict[date, float]:
        rows = (
            await self.session.execute(
                select(
                    GroundwaterObservation.observed_date,
                    GroundwaterObservation.gwt_m,
                ).where(
                    GroundwaterObservation.station_id == station_id,
                    GroundwaterObservation.observed_date >= date_from,
                    GroundwaterObservation.observed_date <= date_to,
                    GroundwaterObservation.mode == MonitoringMode.HISTORICAL_REPLAY.value,
                    GroundwaterObservation.quality_flag == QualityFlag.VALID.value,
                    GroundwaterObservation.gwt_m.is_not(None),
                )
            )
        ).all()
        return {observed_date: float(value) for observed_date, value in rows}
