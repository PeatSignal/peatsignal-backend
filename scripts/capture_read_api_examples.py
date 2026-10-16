"""Capture bounded, real read API responses for the frontend handoff.

Run from backend/: .venv/bin/python scripts/capture_read_api_examples.py
This reads the configured application database and never imports or migrates data.
"""

import asyncio
import json
from pathlib import Path

import httpx
from sqlalchemy import func, select

from app.db.session import AsyncSessionLocal, async_engine
from app.main import app
from app.models.entities import GroundwaterObservation


async def capture() -> dict:
    examples = {}
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://example.test"
    ) as client:

        async def get(name: str, path: str, expected_status: int = 200):
            response = await client.get(path)
            assert response.status_code == expected_status, (name, response.text)
            examples[name] = {
                "method": "GET", "path": path, "status": response.status_code,
                "body": response.json(),
            }
            return response.json()

        stations = await get("stations", "/api/v1/stations")
        assert len(stations) == 8
        by_code = {station["code"]: station for station in stations}
        for station in stations:
            assert station["latitude"] is None and station["longitude"] is None
            assert station["source"] == "mmc1.xlsx"
            assert station["period_start"] and station["period_end"]
        assert by_code["BRG6"]["period_end"] == "2019-10-07"
        assert by_code["BRG3"]["period_end"] == "2019-08-27"

        for code in ("BRG6", "BRG3"):
            observations = await get(
                f"groundwater_{code.lower()}",
                f"/api/v1/stations/{by_code[code]['id']}/groundwater"
                "?from=2019-08-17&to=2019-08-19&mode=HISTORICAL_REPLAY",
            )
            assert len(observations) == 3
            assert all(row["source_sha256"] and row["mode"] == "HISTORICAL_REPLAY"
                       for row in observations)

        duplicate = await get(
            "groundwater_duplicate",
            f"/api/v1/stations/{by_code['BRG5']['id']}/groundwater"
            "?from=2019-03-21&to=2019-03-21&mode=HISTORICAL_REPLAY",
        )
        assert duplicate[0]["quality_flag"] == "DUPLICATE" and duplicate[0]["gwt_m"] is None
        async with AsyncSessionLocal() as session:
            missing_row = (await session.execute(
                select(GroundwaterObservation.station_id, GroundwaterObservation.observed_date)
                .where(GroundwaterObservation.quality_flag == "MISSING")
                .order_by(GroundwaterObservation.observed_date, GroundwaterObservation.station_id)
                .limit(1)
            )).one()
            count = await session.scalar(select(func.count(GroundwaterObservation.id)))
            assert count == 3928
        missing = await get(
            "groundwater_missing",
            f"/api/v1/stations/{missing_row.station_id}/groundwater"
            f"?from={missing_row.observed_date}&to={missing_row.observed_date}",
        )
        assert missing[0]["quality_flag"] == "MISSING" and missing[0]["gwt_m"] is None
        for name, query in (
            ("groundwater_current_empty", "from=2026-10-01&to=2026-10-14&mode=CURRENT_MONITORING"),
            ("groundwater_historical_empty", "from=2019-11-01&to=2019-11-03"),
        ):
            path = f"/api/v1/stations/{by_code['BRG6']['id']}/groundwater?{query}"
            assert await get(name, path) == []

        filters = (
            "from=2019-08-17&to=2019-09-15&mode=HISTORICAL_REPLAY"
            "&bbox=102.9,-2.2,104,-1.3&satellite=N&source_product=VIIRS_SNPP_HISTORICAL"
        )
        first = await get("hotspots_page_1", f"/api/v1/hotspots?{filters}&limit=2&offset=0")
        second = await get("hotspots_page_2", f"/api/v1/hotspots?{filters}&limit=2&offset=2")
        assert first["total"] == second["total"] == 3439
        assert len(first["items"]) == len(second["items"]) == 2
        assert not ({r["id"] for r in first["items"]} & {r["id"] for r in second["items"]})
        for row in first["items"] + second["items"]:
            assert 102.9 <= row["longitude"] <= 104 and -2.2 <= row["latitude"] <= -1.3
            assert row["mode"] == "HISTORICAL_REPLAY" and row["satellite"] == "N"
        current = await get("hotspots_current", "/api/v1/hotspots?mode=CURRENT_MONITORING&limit=2")
        assert all(row["mode"] == "CURRENT_MONITORING" for row in current["items"])
        empty = await get("hotspots_bbox_empty", "/api/v1/hotspots?bbox=0,0,1,1")
        assert empty["total"] == 0
        await get("invalid_bbox", "/api/v1/hotspots?bbox=104,0,100,-3", 422)
        await get("invalid_date_range", "/api/v1/hotspots?from=2019-09-15&to=2019-08-17", 422)
        await get("invalid_station_uuid", "/api/v1/stations/BRG6/groundwater", 422)
    return {
        "description": "Real application database responses; UUIDs and import times are snapshots",
        "examples": examples,
    }


async def main() -> None:
    try:
        payload = await capture()
        output = Path("docs/examples/read-api.json")
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(
            json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
        )
        print(f"Captured {len(payload['examples'])} verified responses in {output}")
    finally:
        await async_engine.dispose()


if __name__ == "__main__":
    asyncio.run(main())
