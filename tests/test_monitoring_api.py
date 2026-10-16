from uuid import UUID

import pytest
from conftest import AsgiClient

from app.api.routes.monitoring import get_monitoring_repository
from app.main import app
from app.schemas.hotspot import HotspotMap, HotspotPage


class FakeRepository:
    calls: dict

    def __init__(self) -> None:
        self.calls = {}

    async def list_stations(self):
        return []

    async def station_exists(self, station_id: UUID) -> bool:
        return station_id.int == 1

    async def list_groundwater(self, station_id, **kwargs):
        self.calls = kwargs
        return []

    async def hotspot_map(self, **kwargs):
        self.calls = kwargs
        return HotspotMap(mode=kwargs["mode"], items=[])

    async def list_hotspots(self, **kwargs):
        self.calls = kwargs
        return HotspotPage(items=[], total=0, limit=kwargs["limit"], offset=kwargs["offset"])


@pytest.fixture
def repository():
    fake = FakeRepository()

    async def override():
        return fake

    app.dependency_overrides[get_monitoring_repository] = override
    yield fake
    app.dependency_overrides.clear()


def test_groundwater_uuid_range_and_current_mode(client: AsgiClient, repository) -> None:
    assert client.get("/api/v1/stations/not-a-uuid/groundwater").status_code == 422
    missing = "/api/v1/stations/00000000-0000-0000-0000-000000000002/groundwater"
    assert client.get(missing).status_code == 404
    path = "/api/v1/stations/00000000-0000-0000-0000-000000000001/groundwater"
    assert client.get(path + "?from=2019-02-01&to=2019-01-01").status_code == 422
    response = client.get(path + "?mode=CURRENT_MONITORING")
    assert response.status_code == 200
    assert response.json() == []
    assert repository.calls["mode"] == "CURRENT_MONITORING"


def test_hotspot_filters_and_pagination(client: AsgiClient, repository) -> None:
    response = client.get(
        "/api/v1/hotspots?from=2019-01-01&to=2019-01-02&bbox=100,-3,104,0"
        "&satellite=N&source_product=VIIRS_SNPP_HISTORICAL&limit=10&offset=20"
    )
    assert response.status_code == 200
    assert response.json() == {"items": [], "total": 0, "limit": 10, "offset": 20}
    assert repository.calls["satellite"] == "N"
    assert repository.calls["bbox"].west == 100
    for query in ("limit=1001", "offset=-1", "bbox=104,0,100,-3", "from=invalid"):
        assert client.get("/api/v1/hotspots?" + query).status_code == 422


def test_map_filters_are_validated_without_list_pagination(client, repository) -> None:
    response = client.get(
        "/api/v1/hotspots/map?mode=CURRENT_MONITORING&from=2026-10-13&to=2026-10-15"
        "&bbox=94,-11.5,141.5,6.5&satellite=N20"
    )
    assert response.status_code == 200
    assert response.json() == {"mode": "CURRENT_MONITORING", "items": []}
    assert repository.calls["satellite"] == "N20"
    assert repository.calls["bbox"].east == 141.5
    assert "limit" not in repository.calls and "offset" not in repository.calls
    for query in ("bbox=104,0,100,-3", "from=2026-10-15&to=2026-10-13", "mode=bad"):
        assert client.get("/api/v1/hotspots/map?" + query).status_code == 422


def test_map_includes_markers_beyond_the_first_list_page() -> None:
    import asyncio
    from datetime import UTC, datetime
    from types import SimpleNamespace

    from app.repositories.monitoring import MonitoringRepository
    from app.schemas.common import MonitoringMode

    class Session:
        async def execute(self, statement):
            assert statement._limit_clause is None
            assert statement._offset_clause is None
            rows = [SimpleNamespace(
                id=str(index), acquired_at=datetime(2026, 10, 15, tzinfo=UTC),
                frp=1.0, verification_status="UNVERIFIED",
                latitude=-2.0, longitude=114.0 if index == 150 else 102.0,
            ) for index in range(151)]
            return SimpleNamespace(all=lambda: rows)

    data = asyncio.run(MonitoringRepository(Session()).hotspot_map(
        mode=MonitoringMode.CURRENT_MONITORING, date_from=None, date_to=None,
        bbox=None, satellite=None, source_product=None,
    ))
    assert len(data.items) == 151
    assert data.items[-1].longitude == 114.0
    assert data.items[-1].list_offset == 150
