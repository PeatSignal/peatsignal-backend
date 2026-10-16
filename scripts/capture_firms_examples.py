"""Capture read-only FIRMS status and cached hotspot examples after a successful live sync."""
import asyncio
import json
from pathlib import Path

import httpx
from sqlalchemy import func, select

from app.db.session import AsyncSessionLocal, async_engine
from app.main import app
from app.models.entities import GroundwaterObservation, Hotspot


async def main() -> None:
    try:
        examples = {}
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://example.test"
        ) as client:
            path = "/api/v1/hotspots/sync-status?area_id=batanghari&source_product=VIIRS_SNPP_NRT"
            response = await client.get(path)
            assert response.status_code == 200
            state = response.json()[0]
            assert state["last_successful_at"] is not None
            examples["sync_status"] = {"method": "GET", "path": path, "body": response.json()}
            attempt = state["last_attempt"]
            path = (
                "/api/v1/hotspots?mode=CURRENT_MONITORING&limit=3"
                f"&from={attempt['date_from']}&to={attempt['date_to']}"
                "&bbox=102.9,-2.2,104,-1.3&source_product=VIIRS_SNPP_NRT"
            )
            response = await client.get(path)
            assert response.status_code == 200 and response.json()["total"] > 0
            assert all(row["mode"] == "CURRENT_MONITORING" for row in response.json()["items"])
            examples["cached_current_hotspots"] = {
                "method": "GET", "path": path, "body": response.json()
            }
        async with AsyncSessionLocal() as session:
            historical = await session.scalar(select(func.count(Hotspot.id)).where(
                Hotspot.mode == "HISTORICAL_REPLAY"
            ))
            gwt = await session.scalar(select(func.count(GroundwaterObservation.id)))
            assert historical == 6403 and gwt == 3928
        output = Path("docs/examples/firms-live.json")
        output.write_text(json.dumps({
            "description": "Successful local NASA live sync snapshot; times are UTC",
            "historical_hotspots_unchanged": historical, "groundwater_unchanged": gwt,
            "examples": examples,
        }, indent=2) + "\n", encoding="utf-8")
        print("Live sync status/current cache verified; historical data preserved.")
    finally:
        await async_engine.dispose()


if __name__ == "__main__":
    asyncio.run(main())
