import hashlib
import math
import uuid
from collections.abc import Callable
from datetime import UTC, datetime, timedelta

from geoalchemy2.elements import WKTElement
from sqlalchemy import func, select, text
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession

from app.data.firms_client import FirmsClient, FirmsError, FirmsResponse
from app.models.entities import DataImportRun, DataSource, FirmsSyncRun, Hotspot
from app.schemas.firms import SyncRequest, SyncResult, SyncStatus

COOLDOWN_SECONDS = 600


def run_result(run: FirmsSyncRun) -> SyncResult:
    return SyncResult(
        id=str(run.id), area_id=run.area_id, source_product=run.source_product, status=run.status,
        date_from=run.date_from, date_to=run.date_to, started_at=run.started_at,
        completed_at=run.completed_at, rows_received=run.rows_received,
        rows_inserted=run.rows_inserted, rows_conflicts=run.rows_conflicts,
        error_code=run.error_code,
    )


async def import_response(
    session: AsyncSession, response: FirmsResponse, run: FirmsSyncRun, now: datetime
) -> tuple[int, int]:
    digest = hashlib.sha256(response.raw).hexdigest()
    # A raw response can be shared across products (e.g. identical empty CSV headers).
    # Product/area provenance is therefore stored on the sync run and observations.
    source_id = await session.scalar(
        insert(DataSource).values(
            id=uuid.uuid4(), name="NASA FIRMS Area API",
            url="https://firms.modaps.eosdis.nasa.gov/api/area/", sha256=digest,
        ).on_conflict_do_nothing(index_elements=[DataSource.sha256]).returning(DataSource.id)
    )
    if source_id is None:
        source_id = await session.scalar(select(DataSource.id).where(DataSource.sha256 == digest))
    unique = {row.external_key: row for row in response.records}
    keys = list(unique)
    inserted = 0
    for start in range(0, len(keys), 500):
        batch = keys[start:start + 500]
        previous = set((await session.execute(
            select(Hotspot.external_key).where(Hotspot.external_key.in_(batch))
        )).scalars())
        rows = [
            {
                "id": uuid.uuid4(), "external_key": row.external_key,
                "source_product": row.source_product, "sensor": row.instrument,
                "satellite": row.satellite, "acquired_at": row.acquired_at,
                "geom": WKTElement(f"POINT({row.longitude} {row.latitude})", srid=4326),
                "frp": row.frp, "confidence_raw": row.confidence_raw, "quality_flag": "VALID",
                "mode": "CURRENT_MONITORING", "source_row_number": row.source_row_number,
                "verification_status": "UNVERIFIED", "source_id": source_id,
                "last_synced_at": now,
            }
            for key in batch for row in [unique[key]]
        ]
        statement = insert(Hotspot).values(rows)
        await session.execute(statement.on_conflict_do_update(
            index_elements=[Hotspot.external_key],
            set_={field: getattr(statement.excluded, field) for field in (
                "frp", "confidence_raw", "source_id", "last_synced_at", "source_row_number"
            )},
        ))
        inserted += len(batch) - len(previous)
    conflicts = len(response.records) - inserted
    run.source_sha256 = digest
    session.add(DataImportRun(
        source_id=source_id, dataset_kind="HOTSPOT", status="COMPLETED",
        rows_seen=len(response.records), rows_inserted=inserted, rows_skipped=conflicts,
        audit_json={"sync_id": str(run.id), "area_id": run.area_id,
                    "source_product": run.source_product, "mode": "CURRENT_MONITORING",
                    "source_sha256": digest},
        completed_at=now,
    ))
    await session.flush()
    return inserted, conflicts


class FirmsSyncService:
    def __init__(
        self, engine: AsyncEngine, client: FirmsClient,
        clock: Callable[[], datetime] = lambda: datetime.now(UTC),
    ):
        self.engine, self.client, self.clock = engine, client, clock

    async def sync(self, request: SyncRequest, actor_id: str) -> SyncResult:
        if not self.client.key:
            raise FirmsError("KEY_NOT_CONFIGURED", 503, "Key NASA FIRMS belum dikonfigurasi.")
        target = f"firms:{request.area_id}:{request.source_product}"
        lock_id = int.from_bytes(hashlib.sha256(target.encode()).digest()[:8], signed=True)
        # Keep a dedicated connection until unlock: session locks must not leak into the pool.
        async with self.engine.connect() as connection:
            acquired = await connection.scalar(
                text("SELECT pg_try_advisory_lock(:id)"), {"id": lock_id}
            )
            await connection.commit()
            if not acquired:
                raise FirmsError("SYNC_RUNNING", 409, "Sync wilayah/produk ini sedang berjalan.")
            try:
                async with AsyncSession(bind=connection, expire_on_commit=False) as session:
                    now = self.clock().astimezone(UTC)
                    async with session.begin():
                        last = await session.scalar(select(FirmsSyncRun).where(
                            FirmsSyncRun.area_id == request.area_id,
                            FirmsSyncRun.source_product == request.source_product,
                        ).order_by(FirmsSyncRun.started_at.desc(), FirmsSyncRun.id).limit(1))
                        if last is not None:
                            retry_after = math.ceil(
                                (last.started_at + timedelta(seconds=COOLDOWN_SECONDS) - now)
                                .total_seconds()
                            )
                            if retry_after > 0:
                                raise FirmsError(
                                    "COOLDOWN", 429, "Tunggu sebelum sync berikutnya.", retry_after
                                )
                            if last.status == "RUNNING":
                                last.status, last.error_code = "FAILED", "INTERRUPTED"
                                last.completed_at = now
                        date_to = now.date()
                        date_from = date_to - timedelta(days=request.day_range - 1)
                        run = FirmsSyncRun(
                            id=uuid.uuid4(), area_id=request.area_id,
                            source_product=request.source_product, day_range=request.day_range,
                            actor_id=uuid.UUID(actor_id), date_from=date_from, date_to=date_to,
                            status="RUNNING", started_at=now, rows_received=0,
                            rows_inserted=0, rows_conflicts=0,
                        )
                        session.add(run)
                    run_id = run.id
                    try:
                        response = await self.client.fetch(request, date_from, date_to)
                        async with session.begin():
                            inserted, conflicts = await import_response(
                                session, response, run, self.clock().astimezone(UTC)
                            )
                            run.rows_received = len(response.records)
                            run.rows_inserted, run.rows_conflicts = inserted, conflicts
                            run.status = "SUCCESS"
                            run.completed_at = self.clock().astimezone(UTC)
                    except Exception as exc:
                        error = exc if isinstance(exc, FirmsError) else FirmsError(
                            "IMPORT_FAILED", 502, "Sync gagal; cache sebelumnya dipertahankan."
                        )
                        await session.rollback()
                        async with session.begin():
                            failed = await session.get(FirmsSyncRun, run_id)
                            failed.status, failed.error_code = "FAILED", error.code
                            failed.completed_at = self.clock().astimezone(UTC)
                        raise error from None
                    return run_result(run)
            finally:
                try:
                    await connection.rollback()
                    await connection.execute(
                        text("SELECT pg_advisory_unlock(:id)"), {"id": lock_id}
                    )
                    await connection.commit()
                except BaseException:
                    await connection.invalidate()
                    raise

    async def statuses(self, area_id: str | None, source_product: str | None) -> list[SyncStatus]:
        result = []
        async with AsyncSession(self.engine) as session:
            for area in ([area_id] if area_id else ["indonesia"]):
                products = [source_product] if source_product else [
                    "VIIRS_SNPP_NRT", "VIIRS_NOAA20_NRT"
                ]
                for product in products:
                    filters = (FirmsSyncRun.area_id == area, FirmsSyncRun.source_product == product)
                    last = await session.scalar(select(FirmsSyncRun).where(*filters).order_by(
                        FirmsSyncRun.started_at.desc(), FirmsSyncRun.id
                    ).limit(1))
                    successful = await session.scalar(select(func.max(FirmsSyncRun.completed_at))
                        .where(*filters, FirmsSyncRun.status == "SUCCESS"))
                    snapshot = run_result(last) if last else None
                    if snapshot and snapshot.status == "RUNNING" and (
                        self.clock().astimezone(UTC) - snapshot.started_at
                    ).total_seconds() > 120:
                        snapshot = snapshot.model_copy(update={
                            "status": "FAILED", "error_code": "INTERRUPTED"
                        })
                    result.append(SyncStatus(
                        area_id=area, source_product=product,
                        status=snapshot.status if snapshot else "NOT_SYNCED",
                        last_attempt=snapshot, last_successful_at=successful,
                    ))
        return result
