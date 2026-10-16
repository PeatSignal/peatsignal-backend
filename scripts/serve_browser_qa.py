"""Serve real API/database for local browser QA; roll back domain writes on exit.

Run from backend/: .venv/bin/python scripts/serve_browser_qa.py
Only loopback is exposed. FIRMS uses its own connection/transactions, so sync writes
are blocked unless --allow-live-sync explicitly enables persistent satellite cache writes.
"""

import argparse
import asyncio
from contextlib import asynccontextmanager

import uvicorn
from fastapi.responses import JSONResponse
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine

from app.core.config import get_settings
from app.db.session import get_async_db
from app.main import create_app
from app.models.entities import FieldReport, InspectionTask, TaskStatusHistory

app = create_app()
app.state.allow_live_sync = False


@asynccontextmanager
async def lifespan(application):
    engine = create_async_engine(
        get_settings().async_database_url,
        connect_args={"connect_timeout": 15},
    )
    tables = [InspectionTask, FieldReport, TaskStatusHistory]
    try:
        async with engine.connect() as connection:
            transaction = await connection.begin()
            before = {
                table.__tablename__: await connection.scalar(
                    select(func.count()).select_from(table)
                )
                for table in tables
            }

            async def qa_session():
                async with AsyncSession(
                    bind=connection,
                    expire_on_commit=False,
                    join_transaction_mode="create_savepoint",
                ) as session:
                    yield session

            application.dependency_overrides[get_async_db] = qa_session
            print("Browser QA ready; domain writes remain in an outer transaction.", flush=True)
            try:
                yield
            finally:
                application.dependency_overrides.clear()
                await transaction.rollback()
                after = {
                    table.__tablename__: await connection.scalar(
                        select(func.count()).select_from(table)
                    )
                    for table in tables
                }
                print(
                    f"Browser QA rollback verified: {before == after}; counts={after}", flush=True
                )
                if before != after:
                    raise RuntimeError("Domain counts changed outside the QA transaction")
    finally:
        await engine.dispose()


app.router.lifespan_context = lifespan


class SerializedQARequests:
    def __init__(self, app):
        self.app = app
        self.lock = asyncio.Lock()

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            return await self.app(scope, receive, send)
        if (
            scope["method"] == "POST"
            and scope["path"] == "/api/v1/admin/hotspots/sync"
            and not app.state.allow_live_sync
        ):
            response = JSONResponse(
                status_code=409,
                content={"detail": "Live sync is disabled on the rollback-only browser QA server."},
            )
            return await response(scope, receive, send)
        # Include dependency cleanup, not just the response headers, in the lock.
        async with self.lock:
            await self.app(scope, receive, send)


app.add_middleware(SerializedQARequests)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--allow-live-sync", action="store_true",
        help="Allow NASA sync to persist its own cache and sync history outside QA rollback.",
    )
    app.state.allow_live_sync = parser.parse_args().allow_live_sync
    uvicorn.run(app, host="127.0.0.1", port=8001, access_log=False)
