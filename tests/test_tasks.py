import asyncio
from datetime import UTC, datetime
from uuid import UUID

import httpx
from geoalchemy2.elements import WKTElement
from sqlalchemy import func, select, text
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.orm import Session
from test_postgis_integration import database  # noqa: F401

from app.db.session import get_async_db
from app.main import app
from app.models.entities import (
    DataSource,
    FieldReport,
    Hotspot,
    TaskStatusHistory,
)

COORDINATOR = {"Authorization": "Bearer demo-coordinator-token"}
OFFICER = {"Authorization": "Bearer demo-field-officer-token"}
OFFICER_ID = "00000000-0000-4000-8000-000000000002"


def test_task_report_workflow_persists_and_updates_hotspot(database) -> None:  # noqa: F811
    now = datetime.now(UTC)
    with Session(database) as session, session.begin():
        source = DataSource(name="Task workflow fixture", sha256="c" * 64)
        session.add(source)
        session.flush()
        hotspot = Hotspot(
            external_key="task-workflow-hotspot",
            source_product="VIIRS_SNPP_NRT",
            sensor="VIIRS",
            satellite="Suomi NPP",
            acquired_at=now,
            geom=WKTElement("POINT(109.2 -0.3)", srid=4326),
            frp=7.5,
            confidence_raw="nominal",
            quality_flag="VALID",
            mode="CURRENT_MONITORING",
            verification_status="UNVERIFIED",
            source_id=source.id,
            last_synced_at=now,
        )
        session.add(hotspot)
        session.flush()
        hotspot_id = str(hotspot.id)

    async def run_workflow() -> None:
        async_url = database.url.render_as_string(hide_password=False).replace(
            "postgresql+psycopg://", "postgresql+psycopg_async://"
        )
        engine = create_async_engine(async_url)
        try:
            session_factory = async_sessionmaker(engine, expire_on_commit=False)

            async def dependency():
                async with session_factory() as session:
                    yield session

            app.dependency_overrides[get_async_db] = dependency
            try:
                async with httpx.AsyncClient(
                    transport=httpx.ASGITransport(app=app), base_url="http://test"
                ) as client:
                    users = await client.get(
                        "/api/v1/users", params={"role": "field_officer"}
                    )
                    assert users.status_code == 200
                    assert [item["id"] for item in users.json()] == [OFFICER_ID]

                    created = await client.post(
                        "/api/v1/tasks",
                        headers=COORDINATOR,
                        json={
                            "mode": "CURRENT_MONITORING",
                            "title": "Periksa anomali panas DEMO",
                            "priority": "HIGH",
                            "hotspot_id": hotspot_id,
                            "area_id": "kubu-raya",
                            "assignee_id": OFFICER_ID,
                            "note": "Prioritas pemeriksaan simulasi",
                        },
                    )
                    assert created.status_code == 201, created.text
                    task = created.json()
                    task_id = task["id"]
                    assert task["status"] == "ASSIGNED"
                    assert task["is_simulation"] is True
                    assert [item["to"] for item in task["history"]] == [
                        "OPEN",
                        "ASSIGNED",
                    ]

                    invalid = await client.patch(
                        f"/api/v1/tasks/{task_id}",
                        headers=OFFICER,
                        json={"status": "SUBMITTED"},
                    )
                    assert invalid.status_code == 409

                    started = await client.patch(
                        f"/api/v1/tasks/{task_id}",
                        headers=OFFICER,
                        json={"status": "IN_PROGRESS"},
                    )
                    assert started.status_code == 200
                    assert started.json()["status"] == "IN_PROGRESS"

                    report_payload = {
                        "observed_at": datetime.now(UTC).isoformat(),
                        "result": "NO_FIRE_FOUND",
                        "note": "Tidak ada api teramati pada lokasi DEMO.",
                        "evidence_url": "https://example.test/evidence/demo-1.jpg",
                        "is_simulation": False,
                    }
                    rejected_report = await client.post(
                        f"/api/v1/tasks/{task_id}/reports",
                        headers=OFFICER,
                        json=report_payload,
                    )
                    assert rejected_report.status_code == 422

                    report_payload["is_simulation"] = True
                    submitted = await client.post(
                        f"/api/v1/tasks/{task_id}/reports",
                        headers=OFFICER,
                        json=report_payload,
                    )
                    assert submitted.status_code == 201, submitted.text
                    assert submitted.json()["is_simulation"] is True

                    followup = await client.patch(
                        f"/api/v1/tasks/{task_id}",
                        headers=COORDINATOR,
                        json={
                            "status": "NEEDS_FOLLOWUP",
                            "note": "Ulangi pemeriksaan SIMULASI",
                        },
                    )
                    assert followup.status_code == 200

                    reassigned = await client.patch(
                        f"/api/v1/tasks/{task_id}",
                        headers=COORDINATOR,
                        json={"status": "ASSIGNED", "assignee_id": OFFICER_ID},
                    )
                    assert reassigned.status_code == 200
                    assert reassigned.json()["status"] == "ASSIGNED"

                    await client.patch(
                        f"/api/v1/tasks/{task_id}",
                        headers=OFFICER,
                        json={"status": "IN_PROGRESS"},
                    )
                    report_payload.update(
                        observed_at=datetime.now(UTC).isoformat(),
                        result="ACTIVE_FIRE_FOUND",
                        note="Indikasi api aktif pada skenario SIMULASI.",
                        evidence_url=None,
                    )
                    second_report = await client.post(
                        f"/api/v1/tasks/{task_id}/reports",
                        headers=OFFICER,
                        json=report_payload,
                    )
                    assert second_report.status_code == 201

                    verified = await client.patch(
                        f"/api/v1/tasks/{task_id}",
                        headers=COORDINATOR,
                        json={"status": "VERIFIED", "note": "Ditinjau koordinator DEMO"},
                    )
                    assert verified.status_code == 200
                    assert verified.json()["status"] == "VERIFIED"

                    detail = await client.get(f"/api/v1/tasks/{task_id}")
                    assert detail.status_code == 200
                    assert len(detail.json()["reports"]) == 2
                    assert detail.json()["history"][-1]["to"] == "VERIFIED"

                    filtered = await client.get(
                        "/api/v1/tasks",
                        params={
                            "mode": "CURRENT_MONITORING",
                            "status": "VERIFIED,DISMISSED",
                        },
                    )
                    assert [item["id"] for item in filtered.json()] == [task_id]
            finally:
                app.dependency_overrides.pop(get_async_db, None)

            async with session_factory() as session:
                assert await session.scalar(select(func.count(FieldReport.id))) == 2
                histories = (
                    await session.scalars(
                        select(TaskStatusHistory).order_by(TaskStatusHistory.changed_at)
                    )
                ).all()
                assert all(
                    item.actor_role in {"coordinator", "field_officer"}
                    for item in histories
                )
                persisted_hotspot = await session.get(Hotspot, UUID(hotspot_id))
                assert persisted_hotspot.verification_status == "VERIFIED"
                rls_enabled = await session.scalar(
                    text(
                        "SELECT relrowsecurity FROM pg_class "
                        "WHERE oid = 'public.inspection_tasks'::regclass"
                    )
                )
                assert rls_enabled is True
        finally:
            await engine.dispose()

    asyncio.run(run_workflow())
