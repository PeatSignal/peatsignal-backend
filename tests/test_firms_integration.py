import asyncio
from datetime import UTC, datetime, timedelta

import httpx
import pytest
from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import create_async_engine
from sqlalchemy.orm import Session
from test_firms import HEADER, REQUEST, ROW
from test_postgis_integration import database  # noqa: F401

from app.core.security import DEMO_COORDINATOR_ID
from app.data.firms_client import FirmsClient, FirmsError
from app.data.firms_sync import FirmsSyncService
from app.models.entities import FirmsSyncRun, Hotspot


def test_persistent_sync_upsert_cooldown_failure_and_lock(database, monkeypatch):  # noqa: F811
    url = database.url.render_as_string(hide_password=False).replace(
        "postgresql+psycopg://", "postgresql+psycopg_async://"
    )

    async def check():
        engine = create_async_engine(url)
        now = datetime(2026, 10, 15, 8, tzinfo=UTC)
        gate = asyncio.Event()
        started = asyncio.Event()
        fail = False
        block = False

        async def handler(request):
            started.set()
            if block:
                await gate.wait()
            return httpx.Response(200, content=b"bad" if fail else (HEADER + ROW + ROW).encode())

        service = FirmsSyncService(engine, FirmsClient("test-secret", httpx.MockTransport(handler)),
                                   clock=lambda: now)
        try:
            initial = await service.statuses(None, None)
            assert len(initial) == 2 and all(s.status == "NOT_SYNCED" for s in initial)
            first = await service.sync(REQUEST, DEMO_COORDINATOR_ID)
            assert (first.rows_received, first.rows_inserted, first.rows_conflicts) == (2, 1, 1)
            with pytest.raises(FirmsError) as caught:
                await service.sync(REQUEST, DEMO_COORDINATOR_ID)
            assert caught.value.code == "COOLDOWN" and caught.value.retry_after == 600
            with Session(database) as session, session.begin():
                session.execute(update(Hotspot).values(verification_status="VERIFIED"))
            now += timedelta(minutes=11)
            second = await service.sync(REQUEST, DEMO_COORDINATOR_ID)
            assert second.rows_inserted == 0 and second.rows_conflicts == 2
            with Session(database) as session:
                hotspot = session.scalar(select(Hotspot))
                assert hotspot.mode == "CURRENT_MONITORING"
                assert hotspot.verification_status == "VERIFIED"
                assert session.scalar(select(func.count(Hotspot.id))) == 1
            now += timedelta(minutes=11)
            fail = True
            with pytest.raises(FirmsError):
                await service.sync(REQUEST, DEMO_COORDINATOR_ID)
            state = (await service.statuses("batanghari", "VIIRS_SNPP_NRT"))[0]
            assert state.status == "FAILED"
            assert state.last_successful_at == second.completed_at
            with Session(database) as session:
                assert session.scalar(select(func.count(Hotspot.id))) == 1
                assert session.scalar(select(func.count(FirmsSyncRun.id))) == 3
            now += timedelta(minutes=11)
            fail = False
            block = True
            started.clear()
            pending = asyncio.create_task(service.sync(REQUEST, DEMO_COORDINATOR_ID))
            await asyncio.wait_for(started.wait(), timeout=5)
            try:
                with pytest.raises(FirmsError) as busy:
                    await service.sync(REQUEST, DEMO_COORDINATOR_ID)
                assert busy.value.code == "SYNC_RUNNING"
                active = (await service.statuses("batanghari", "VIIRS_SNPP_NRT"))[0]
                assert active.status == "RUNNING"
            finally:
                gate.set()
                await pending
            now += timedelta(minutes=11)
            block = False
            from app.data import firms_sync

            original_import = firms_sync.import_response

            async def fail_after_insert(*args, **kwargs):
                await original_import(*args, **kwargs)
                raise ValueError("simulate failure after database writes")

            with monkeypatch.context() as patch:
                patch.setattr(firms_sync, "import_response", fail_after_insert)
                with pytest.raises(FirmsError) as failed_import:
                    await service.sync(REQUEST, DEMO_COORDINATOR_ID)
                assert failed_import.value.code == "IMPORT_FAILED"
            state = (await service.statuses("batanghari", "VIIRS_SNPP_NRT"))[0]
            assert state.status == "FAILED" and state.last_successful_at is not None
            with Session(database) as session:
                assert session.scalar(select(func.count(Hotspot.id))) == 1
        finally:
            await engine.dispose()

    asyncio.run(check())
