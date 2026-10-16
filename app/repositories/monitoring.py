from datetime import UTC, date, datetime, time, timedelta
from uuid import UUID

from sqlalchemy import Select, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.data.hotspots import BoundingBox
from app.models.entities import DataSource, GroundwaterObservation, Hotspot, Station
from app.schemas.common import MonitoringMode
from app.schemas.groundwater import GroundwaterObservation as GroundwaterObservationSchema
from app.schemas.hotspot import Hotspot as HotspotSchema
from app.schemas.hotspot import HotspotMap, HotspotMapPoint, HotspotPage
from app.schemas.station import Station as StationSchema


def hotspot_filters(*, date_from, date_to, bbox, satellite, source_product, mode):
    filters = [Hotspot.mode == mode.value]
    if date_from is not None:
        filters.append(Hotspot.acquired_at >= datetime.combine(date_from, time.min, tzinfo=UTC))
    if date_to is not None:
        filters.append(
            Hotspot.acquired_at
            < datetime.combine(date_to + timedelta(days=1), time.min, tzinfo=UTC)
        )
    if bbox is not None:
        envelope = func.ST_MakeEnvelope(
            bbox.west, bbox.south, bbox.east, bbox.north, 4326
        )
        filters.append(func.ST_Intersects(Hotspot.geom, envelope))
    if satellite is not None:
        filters.append(Hotspot.satellite == satellite)
    if source_product is not None:
        filters.append(Hotspot.source_product == source_product)
    return filters


class MonitoringRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def list_stations(self) -> list[StationSchema]:
        metadata = (
            select(
                GroundwaterObservation.station_id,
                func.min(GroundwaterObservation.observed_date).label("period_start"),
                func.max(GroundwaterObservation.observed_date).label("period_end"),
                func.array_agg(func.distinct(DataSource.name)).label("sources"),
            )
            .join(DataSource, DataSource.id == GroundwaterObservation.source_id)
            .group_by(GroundwaterObservation.station_id)
            .subquery()
        )
        rows = (await self.session.execute(
            select(Station, metadata.c.period_start, metadata.c.period_end, metadata.c.sources)
            .outerjoin(metadata, metadata.c.station_id == Station.id)
            .order_by(Station.code)
        )).all()
        return [
            StationSchema(
                id=str(station.id),
                code=station.code,
                region=station.region,
                latitude=station.latitude,
                longitude=station.longitude,
                coordinate_source=station.coordinate_source,
                period_start=period_start,
                period_end=period_end,
                source=", ".join(sorted(sources)) if sources else None,
            )
            for station, period_start, period_end, sources in rows
        ]

    async def station_exists(self, station_id: UUID) -> bool:
        station = await self.session.scalar(select(Station.id).where(Station.id == station_id))
        return station is not None

    async def list_groundwater(
        self,
        station_id: UUID,
        *,
        date_from: date | None,
        date_to: date | None,
        mode: MonitoringMode,
    ) -> list[GroundwaterObservationSchema]:
        statement = (
            select(GroundwaterObservation, DataSource)
            .join(DataSource, DataSource.id == GroundwaterObservation.source_id)
            .where(
                GroundwaterObservation.station_id == station_id,
                GroundwaterObservation.mode == mode.value,
            )
            .order_by(GroundwaterObservation.observed_date)
        )
        if date_from is not None:
            statement = statement.where(GroundwaterObservation.observed_date >= date_from)
        if date_to is not None:
            statement = statement.where(GroundwaterObservation.observed_date <= date_to)
        rows = (await self.session.execute(statement)).all()
        return [
            GroundwaterObservationSchema(
                id=str(observation.id),
                station_id=str(observation.station_id),
                observed_date=observation.observed_date,
                observed_at=datetime.combine(observation.observed_date, time.min, tzinfo=UTC),
                gwt_m=observation.gwt_m,
                quality_flag=observation.quality_flag,
                source=source.name,
                source_id=str(source.id),
                source_sha256=source.sha256,
                mode=observation.mode,
            )
            for observation, source in rows
        ]

    async def list_hotspots(
        self,
        *,
        date_from: date | None,
        date_to: date | None,
        bbox: BoundingBox | None,
        satellite: str | None,
        source_product: str | None,
        mode: MonitoringMode,
        limit: int,
        offset: int,
    ) -> HotspotPage:
        filters = hotspot_filters(
            date_from=date_from, date_to=date_to, bbox=bbox, satellite=satellite,
            source_product=source_product, mode=mode,
        )

        total = await self.session.scalar(select(func.count(Hotspot.id)).where(*filters))
        statement: Select[tuple[Hotspot, DataSource, float, float]] = (
            select(
                Hotspot,
                DataSource,
                func.ST_Y(Hotspot.geom).label("latitude"),
                func.ST_X(Hotspot.geom).label("longitude"),
            )
            .join(DataSource, DataSource.id == Hotspot.source_id)
            .where(*filters)
            .order_by(Hotspot.acquired_at.desc(), Hotspot.id)
            .limit(limit)
            .offset(offset)
        )
        rows = (await self.session.execute(statement)).all()
        items = [
            HotspotSchema(
                id=str(hotspot.id),
                external_key=hotspot.external_key,
                latitude=latitude,
                longitude=longitude,
                acquired_at=hotspot.acquired_at,
                source_product=hotspot.source_product,
                sensor=hotspot.sensor,
                satellite=hotspot.satellite,
                frp=hotspot.frp,
                confidence_raw=hotspot.confidence_raw,
                verification_status=hotspot.verification_status,
                source=source.name,
                quality_flag=hotspot.quality_flag,
                mode=hotspot.mode,
                last_synced_at=hotspot.last_synced_at,
            )
            for hotspot, source, latitude, longitude in rows
        ]
        return HotspotPage(items=items, total=total or 0, limit=limit, offset=offset)

    async def hotspot_map(self, **query) -> HotspotMap:
        # Map coverage is independent of list pagination; load only marker fields.
        rows = (await self.session.execute(
            select(
                Hotspot.id, Hotspot.acquired_at, Hotspot.frp, Hotspot.verification_status,
                func.ST_Y(Hotspot.geom).label("latitude"),
                func.ST_X(Hotspot.geom).label("longitude"),
            ).where(*hotspot_filters(**query))
            .order_by(Hotspot.acquired_at.desc(), Hotspot.id)
        )).all()
        return HotspotMap(mode=query["mode"], items=[
            HotspotMapPoint(
                id=str(row.id), latitude=row.latitude, longitude=row.longitude,
                observed_at=row.acquired_at, frp_mw=row.frp,
                verification_status=row.verification_status, list_offset=index,
            )
            for index, row in enumerate(rows)
        ])
