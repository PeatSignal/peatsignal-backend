"""Smoke the FastAPI read and task workflow against Supabase without persisting test rows."""

import asyncio
import json
from datetime import UTC, date, datetime, timedelta
from math import isclose
from typing import Any

import httpx
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine

from app.core.config import get_settings
from app.db.session import get_async_db
from app.main import app

OFFICER_ID = "00000000-0000-4000-8000-000000000002"


def require(response: httpx.Response, expected: int = 200) -> Any:
    if response.status_code != expected:
        raise RuntimeError(
            f"{response.request.method} {response.request.url.path} returned "
            f"{response.status_code}: {response.text[:500]}"
        )
    return response.json()


async def run() -> None:
    settings = get_settings()
    coordinator = {"Authorization": f"Bearer {settings.resolved_coordinator_token}"}
    officer = {"Authorization": f"Bearer {settings.resolved_field_officer_token}"}
    engine = create_async_engine(
        settings.async_database_url,
        pool_pre_ping=True,
        connect_args={"connect_timeout": 15},
    )
    summary: dict[str, Any] = {}
    try:
        async with engine.connect() as connection:
            outer_transaction = await connection.begin()

            async def smoke_session():
                async with AsyncSession(
                    bind=connection,
                    expire_on_commit=False,
                    join_transaction_mode="create_savepoint",
                ) as session:
                    yield session

            app.dependency_overrides[get_async_db] = smoke_session
            try:
                transport = httpx.ASGITransport(app=app, raise_app_exceptions=False)
                async with httpx.AsyncClient(
                    transport=transport,
                    base_url="http://supabase-smoke",
                    timeout=30,
                ) as client:
                    summary["health"] = require(await client.get("/health"))["status"]
                    require(await client.get("/openapi.json"))

                    users = require(
                        await client.get(
                            "/api/v1/users", params={"role": "field_officer"}
                        )
                    )
                    if not any(user["id"] == OFFICER_ID for user in users):
                        raise RuntimeError("Demo field officer is missing")
                    summary["field_officers"] = len(users)

                    stations = require(await client.get("/api/v1/stations"))
                    brg6 = next(
                        (station for station in stations if station["code"] == "BRG6"),
                        None,
                    )
                    if brg6 is None:
                        raise RuntimeError("BRG6 is missing")
                    summary["stations"] = len(stations)

                    groundwater = require(
                        await client.get(
                            f"/api/v1/stations/{brg6['id']}/groundwater",
                            params={
                                "mode": "HISTORICAL_REPLAY",
                                "from": "2019-09-01",
                                "to": "2019-09-15",
                            },
                        )
                    )
                    if not groundwater:
                        raise RuntimeError("Groundwater query returned no observations")
                    summary["groundwater_sample"] = len(groundwater)

                    ml_metrics = require(await client.get("/api/v1/ml/metrics"))
                    if ml_metrics["status"] != "AVAILABLE":
                        raise RuntimeError("ML artifacts are not available")
                    if {item["station_code"] for item in ml_metrics["experiments"]} != {
                        "BRG6", "BRG3"
                    }:
                        raise RuntimeError("ML metrics must contain BRG6 and BRG3")
                    forecasts = []
                    for experiment in ml_metrics["experiments"]:
                        prediction = experiment["predictions"][0]
                        first_target = date.fromisoformat(prediction["date"])
                        ml_forecast = require(
                            await client.post(
                                "/api/v1/ml/forecast",
                                json={
                                    "station_id": experiment["station_id"],
                                    "date": (first_target - timedelta(days=1)).isoformat(),
                                },
                            )
                        )
                        if ml_forecast["status"] != "OK":
                            raise RuntimeError(f"Historical ML forecast rejected: {ml_forecast}")
                        if (
                            ml_forecast["forecast_date"] != prediction["date"]
                            or ml_forecast["model_version"] != experiment["model_version"]
                            or ml_forecast["release_gate"] != experiment["release_gate"]
                            or not isclose(
                                ml_forecast["predicted_gwt_m"], prediction["predicted_m"],
                                rel_tol=1e-9, abs_tol=1e-9,
                            )
                            or not isclose(
                                ml_forecast["baseline_gwt_m"], prediction["baseline_m"],
                                rel_tol=1e-9, abs_tol=1e-9,
                            )
                        ):
                            raise RuntimeError("ML forecast does not match the test artifact")
                        forecasts.append({
                            "station": experiment["station_code"],
                            "release_gate": ml_forecast["release_gate"],
                            "forecast_date": ml_forecast["forecast_date"],
                            "matches_artifact": True,
                        })
                    rejected = require(
                        await client.post(
                            "/api/v1/ml/forecast",
                            json={"station_id": brg6["id"], "date": "2026-10-15"},
                        )
                    )
                    if rejected["status"] != "REJECTED":
                        raise RuntimeError("ML accepted a forecast without recent GWT data")
                    summary["ml"] = {
                        "experiments": len(forecasts),
                        "forecasts": forecasts,
                        "missing_history": "REJECTED",
                    }

                    hotspot_page = require(
                        await client.get(
                            "/api/v1/hotspots",
                            params={
                                "mode": "HISTORICAL_REPLAY",
                                "from": "2019-08-17",
                                "to": "2019-09-15",
                                "bbox": "102.9,-2.2,104,-1.3",
                                "limit": 5,
                            },
                        )
                    )
                    if hotspot_page["total"] != 3439 or not hotspot_page["items"]:
                        raise RuntimeError("Batanghari hotspot total does not match the seed")
                    hotspot_id = hotspot_page["items"][0]["id"]
                    summary["batanghari_hotspots"] = hotspot_page["total"]

                    priorities = require(
                        await client.get(
                            "/api/v1/priorities",
                            params={
                                "mode": "HISTORICAL_REPLAY",
                                "as_of": "2019-09-15T23:59:59Z",
                            },
                        )
                    )
                    if {item["area_id"] for item in priorities} != {
                        "batanghari",
                        "kubu-raya",
                    }:
                        raise RuntimeError("Priority response does not contain both demo areas")
                    summary["priorities"] = len(priorities)

                    created = require(
                        await client.post(
                            "/api/v1/tasks",
                            headers=coordinator,
                            json={
                                "mode": "HISTORICAL_REPLAY",
                                "title": "Smoke pemeriksaan Supabase SIMULASI",
                                "priority": "HIGH",
                                "hotspot_id": hotspot_id,
                                "area_id": "batanghari",
                                "assignee_id": OFFICER_ID,
                                "note": "Dihapus otomatis setelah smoke selesai",
                            },
                        ),
                        201,
                    )
                    task_id = created["id"]
                    if created["status"] != "ASSIGNED":
                        raise RuntimeError("Created task is not ASSIGNED")

                    started = require(
                        await client.patch(
                            f"/api/v1/tasks/{task_id}",
                            headers=officer,
                            json={"status": "IN_PROGRESS"},
                        )
                    )
                    if started["status"] != "IN_PROGRESS":
                        raise RuntimeError("Task did not enter IN_PROGRESS")

                    report = require(
                        await client.post(
                            f"/api/v1/tasks/{task_id}/reports",
                            headers=officer,
                            json={
                                "observed_at": datetime.now(UTC).isoformat(),
                                "result": "NO_FIRE_FOUND",
                                "note": "Laporan smoke SIMULASI, tidak dipersistenkan.",
                                "evidence_url": None,
                                "is_simulation": True,
                            },
                        ),
                        201,
                    )
                    if not report["is_simulation"]:
                        raise RuntimeError("Smoke report lost its simulation label")

                    verified = require(
                        await client.patch(
                            f"/api/v1/tasks/{task_id}",
                            headers=coordinator,
                            json={"status": "VERIFIED", "note": "Smoke review"},
                        )
                    )
                    detail = require(await client.get(f"/api/v1/tasks/{task_id}"))
                    if verified["status"] != "VERIFIED" or len(detail["reports"]) != 1:
                        raise RuntimeError("Task verification workflow is incomplete")
                    summary["workflow"] = "ASSIGNED→IN_PROGRESS→SUBMITTED→VERIFIED"
                    summary["history_entries"] = len(detail["history"])
            finally:
                app.dependency_overrides.pop(get_async_db, None)
                await outer_transaction.rollback()
    finally:
        await engine.dispose()

    summary["database_changes"] = "ROLLED_BACK"
    print(json.dumps(summary, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    asyncio.run(asyncio.wait_for(run(), timeout=120))
