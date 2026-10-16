import asyncio
from datetime import UTC, date, datetime, timedelta

import httpx
import pytest
from geoalchemy2.elements import WKTElement
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.orm import Session
from test_postgis_integration import database  # noqa: F401

from app.data.priority_rules import evaluate
from app.db.session import get_async_db
from app.main import app
from app.models.entities import (
    DataSource,
    FieldReport,
    GroundwaterObservation,
    Hotspot,
    InspectionTask,
    PriorityAssessment,
    Station,
    TaskStatusHistory,
    User,
)
from app.repositories.priorities import PriorityRepository


@pytest.mark.parametrize("query", [
    "mode=HISTORICAL_REPLAY&as_of=2019-01-07T23:59:59",
    "mode=CURRENT_MONITORING&as_of=2099-01-07T23:59:59Z",
    "mode=UNKNOWN&as_of=2019-01-07T23:59:59Z",
    "mode=HISTORICAL_REPLAY&as_of=2019-01-07T23:59:59Z&area_id=unknown",
])
def test_endpoint_rejects_invalid_cutoffs(client, query):
    assert client.get("/api/v1/priorities?" + query).status_code == 422


def snapshot(hotspots=(), trends=(), reports=()):
    return {"hotspots": list(hotspots), "gwt_trends": list(trends),
            "supporting_reports": list(reports)}


@pytest.mark.parametrize(("inputs", "decision", "priority"), [
    (snapshot(), "INSUFFICIENT_DATA", "INSUFFICIENT_DATA"),
    (snapshot(trends=[{"delta_m": -0.1}]), "MONITOR", "MEDIUM"),
    (snapshot(trends=[{"delta_m": 0.1}]), "MONITOR", "LOW"),
    (snapshot(hotspots=[{"acquired_at": "2019-01-01", "reviewed": False}]), "REVIEW", "MEDIUM"),
    (snapshot(hotspots=[{"acquired_at": f"2019-01-0{day}", "reviewed": False}
                        for day in (1, 2, 3)]), "REVIEW", "HIGH"),
    (snapshot(hotspots=[{"acquired_at": f"2019-01-0{day}", "reviewed": True}
                        for day in (1, 2, 3)], reports=[{"id": "report"}]), "ESCALATE", "HIGH"),
])
def test_rules_deterministic(inputs, decision, priority):
    first = evaluate(inputs)
    assert first == evaluate(inputs)
    assert (first["decision"], first["priority"]) == (decision, priority)
    assert "CHIRPS_RAINFALL" in first["missing_inputs"]


def test_repository_cutoff_persistence_modes_and_reports(database):  # noqa: F811
    cutoff = datetime(2019, 1, 7, 23, 59, 59, tzinfo=UTC)
    with Session(database) as session, session.begin():
        source = DataSource(name="test", sha256="a" * 64)
        station = Station(code="TEST", region="Batanghari")
        user = User(role="coordinator", display_name="Test")
        session.add_all([source, station, user])
        session.flush()
        for day in range(1, 9):
            session.add(GroundwaterObservation(
                station_id=station.id, observed_date=date(2019, 1, day),
                gwt_m=-day / 10, quality_flag="VALID", source_id=source.id,
                mode="HISTORICAL_REPLAY",
            ))
        historical = []
        for day in (1, 2, 3, 8):
            hotspot = Hotspot(
                external_key=f"hist-{day}", source_product="VIIRS_SNPP_HISTORICAL",
                sensor="VIIRS", satellite="N", acquired_at=cutoff.replace(day=day, hour=1),
                geom=WKTElement("POINT(103 -2)", srid=4326), source_id=source.id,
                mode="HISTORICAL_REPLAY", last_synced_at=datetime.now(UTC),
                verification_status="VERIFIED",
            )
            historical.append(hotspot)
            session.add(hotspot)
        session.flush()
        task = InspectionTask(
            title="inspection", priority="HIGH", created_by_id=user.id,
            hotspot_id=historical[0].id, status="VERIFIED",
            mode="HISTORICAL_REPLAY", area_id="batanghari", is_simulation=True,
            created_at=cutoff - timedelta(days=3),
        )
        session.add(task)
        session.flush()
        report = FieldReport(
            task_id=task.id, observed_at=cutoff - timedelta(days=2),
            result="ACTIVE_FIRE_FOUND", note="simulation", is_simulation=True,
            submitted_by_id=user.id, created_at=cutoff - timedelta(days=1),
        )
        history = TaskStatusHistory(
            task_id=task.id, to_status="VERIFIED", actor_id=user.id,
            actor_role="coordinator",
            changed_at=cutoff + timedelta(days=1),
        )
        session.add_all([report, history])
        session.flush()
        history_id = history.id

    async def check():
        url = database.url.render_as_string(hide_password=False).replace(
            "postgresql+psycopg://", "postgresql+psycopg_async://"
        )
        engine = create_async_engine(url)
        try:
            async with async_sessionmaker(engine)() as session:
                repository = PriorityRepository(session)
                first = await repository.assess("HISTORICAL_REPLAY", cutoff, "batanghari")
                again = await repository.assess("HISTORICAL_REPLAY", cutoff, "batanghari")
                assert first == again
                assert first.decision == "REVIEW" and first.priority == "HIGH"
                assert len(first.input_snapshot["hotspots"]) == 3
                assert first.input_snapshot["gwt_trends"][0]["delta_m"] == -0.6
                assert first.input_snapshot["supporting_reports"] == []
                assert await session.scalar(select(func.count(PriorityAssessment.id))) == 1
                current = await repository.assess("CURRENT_MONITORING", cutoff, "batanghari")
                assert current.priority == "INSUFFICIENT_DATA"
                empty = await repository.assess("HISTORICAL_REPLAY", cutoff, "kubu-raya")
                assert empty.priority == "INSUFFICIENT_DATA"
                async def dependency():
                    yield session

                app.dependency_overrides[get_async_db] = dependency
                try:
                    async with httpx.AsyncClient(
                        transport=httpx.ASGITransport(app=app), base_url="http://test"
                    ) as client:
                        response = await client.get("/api/v1/priorities", params={
                            "mode": "HISTORICAL_REPLAY", "as_of": cutoff.isoformat(),
                        })
                        assert response.status_code == 200
                        assert [a["area_id"] for a in response.json()] == [
                            "batanghari", "kubu-raya"
                        ]
                        assert response.json()[0]["id"] == first.id
                finally:
                    app.dependency_overrides.pop(get_async_db, None)
                history = await session.get(TaskStatusHistory, history_id)
                history.changed_at = cutoff - timedelta(hours=1)
                await session.flush()
                supported = await repository.assess("HISTORICAL_REPLAY", cutoff, "batanghari")
                assert supported.decision == "ESCALATE"
                assert supported.id != first.id
                # A quality gap disqualifies a station's complete seven-day trend.
                observation = await session.scalar(select(GroundwaterObservation).where(
                    GroundwaterObservation.observed_date == date(2019, 1, 4)
                ))
                observation.quality_flag = "MISSING"
                observation.gwt_m = None
                await session.flush()
                gap = await repository.assess("HISTORICAL_REPLAY", cutoff, "batanghari")
                assert gap.input_snapshot["gwt_trends"] == []
                original = await session.scalar(select(Hotspot).where(
                    Hotspot.external_key == "hist-1"
                ))
                current_hotspots = []
                for day in (1, 2, 3, 4):
                    item = Hotspot(
                        external_key=f"current-{day}", source_product="VIIRS_SNPP_NRT",
                        sensor="VIIRS", satellite="N", mode="CURRENT_MONITORING",
                        acquired_at=cutoff.replace(day=day, hour=1),
                        geom=WKTElement("POINT(103 -2)", srid=4326),
                        source_id=original.source_id,
                        last_synced_at=cutoff + timedelta(hours=1 if day == 4 else -1),
                    )
                    current_hotspots.append(item)
                    session.add(item)
                await session.flush()
                task = await session.scalar(select(InspectionTask))
                task.hotspot_id = current_hotspots[0].id
                await session.flush()
                current = await repository.assess("CURRENT_MONITORING", cutoff, "batanghari")
                assert current.decision == "REVIEW"
                assert len(current.input_snapshot["hotspots"]) == 3
                assert current.input_snapshot["supporting_reports"] == []
                await session.commit()
            async with async_sessionmaker(engine)() as session:
                saved = await session.get(PriorityAssessment, first.id)
                assert saved.inputs_json == first.input_snapshot
        finally:
            await engine.dispose()
    asyncio.run(check())
