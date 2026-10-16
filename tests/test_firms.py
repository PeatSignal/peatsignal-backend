import asyncio
import logging
from datetime import UTC, date, datetime

import httpx
import pytest

from app.api.routes.firms import get_firms_service
from app.data.firms_client import FirmsClient, FirmsError, RedactFirmsKey, parse_response
from app.data.viirs_rows import normalize_viirs_row
from app.main import app
from app.schemas.firms import SyncRequest

HEADER = "latitude,longitude,acq_date,acq_time,satellite,instrument,confidence,frp\n"
ROW = "-1.5,103.5,2026-10-15,0055,N,VIIRS,n,12.5\n"
REQUEST = SyncRequest(area_id="batanghari", source_product="VIIRS_SNPP_NRT")


def test_csv_utc_empty_and_same_key_for_file_http_row() -> None:
    rows = parse_response((HEADER + ROW).encode(), REQUEST, date(2026, 10, 13), date(2026, 10, 15))
    assert rows[0].acquired_at == datetime(2026, 10, 15, 0, 55, tzinfo=UTC)
    normalized = normalize_viirs_row({
        "latitude": "-1.5", "longitude": "103.5", "acq_date": "2026-10-15",
        "acq_time": "55", "satellite": "N", "instrument": "VIIRS",
        "confidence": "n", "frp": "12.5",
    }, 2, REQUEST.source_product)
    assert rows[0].external_key == normalized.external_key
    assert parse_response(HEADER.encode(), REQUEST, date(2026, 10, 13), date(2026, 10, 15)) == []


@pytest.mark.parametrize("body", [
    b"<html>Invalid MAP_KEY</html>", b"Error: Invalid key", b"latitude,longitude\n1,2",
    (HEADER + ROW.replace("12.5", "nan")).encode(),
    (HEADER + ROW.replace("-1.5", "-20")).encode(),
    (HEADER + ROW.replace("2026-10-15", "2019-01-01")).encode(),
    (HEADER + ROW.replace(",N,", ",N20,")).encode(),
    (HEADER + ROW.replace("0055", "9999")).encode(),
])
def test_bad_payloads_fail_without_exposing_body(body: bytes) -> None:
    with pytest.raises(FirmsError) as caught:
        parse_response(body, REQUEST, date(2026, 10, 13), date(2026, 10, 15))
    assert caught.value.code == "INVALID_RESPONSE"
    assert "MAP_KEY" not in str(caught.value)


@pytest.mark.parametrize("failure", ["http", "timeout", "network", "large"])
def test_client_bounded_failures(failure: str) -> None:
    def handler(request):
        if failure == "timeout":
            raise httpx.ReadTimeout("sensitive URL", request=request)
        if failure == "network":
            raise httpx.ConnectError("sensitive URL", request=request)
        if failure == "large":
            return httpx.Response(200, headers={"Content-Length": str(21 * 1024 * 1024)})
        return httpx.Response(500, text="upstream error with sensitive information")

    async def check():
        client = FirmsClient("test-secret", httpx.MockTransport(handler))
        with pytest.raises(FirmsError) as caught:
            await client.fetch(REQUEST, date(2026, 10, 13), date(2026, 10, 15))
        assert caught.value.status_code == (504 if failure == "timeout" else 502)
        assert "test-secret" not in str(caught.value)

    asyncio.run(check())


def test_redacts_httpx_log_url() -> None:
    record = logging.LogRecord(
        "httpx", logging.INFO, "", 0,
        "GET https://firms.test/api/area/csv/secret/VIIRS_SNPP_NRT", (), None,
    )
    RedactFirmsKey().filter(record)
    assert "secret" not in record.getMessage()
    assert "[REDACTED]" in record.getMessage()


def test_stream_limit_without_numeric_content_length(monkeypatch) -> None:
    from app.data import firms_client

    monkeypatch.setattr(firms_client, "MAX_RESPONSE_BYTES", 10)
    transport = httpx.MockTransport(lambda request: httpx.Response(
        200, content=(HEADER + ROW).encode(), headers={"content-length": "unknown"}
    ))

    async def check():
        with pytest.raises(FirmsError) as caught:
            await FirmsClient("test-secret", transport).fetch(
                REQUEST, date(2026, 10, 13), date(2026, 10, 15)
            )
        assert caught.value.code == "RESPONSE_TOO_LARGE"

    asyncio.run(check())


def test_sync_auth_input_and_safe_unconfigured_response(client) -> None:
    payload = REQUEST.model_dump()
    assert client.post("/api/v1/admin/hotspots/sync", json=payload).status_code == 401
    officer = {"Authorization": "Bearer demo-field-officer-token"}
    coordinator = {"Authorization": "Bearer demo-coordinator-token"}
    denied = client.post("/api/v1/admin/hotspots/sync", json=payload, headers=officer)
    assert denied.status_code == 403
    for changed in ({"day_range": 6}, {"area_id": "world"}, {"source_product": "MODIS_NRT"}):
        assert client.post("/api/v1/admin/hotspots/sync", json={**payload, **changed},
                           headers=coordinator).status_code == 422

    class FakeService:
        async def sync(self, request, actor_id):
            raise FirmsError("KEY_NOT_CONFIGURED", 503, "Key NASA FIRMS belum dikonfigurasi.")

    async def dependency():
        return FakeService()

    app.dependency_overrides[get_firms_service] = dependency
    try:
        response = client.post("/api/v1/admin/hotspots/sync", json=payload, headers=coordinator)
        assert response.status_code == 503
        assert "Key NASA" in response.json()["detail"]
    finally:
        app.dependency_overrides.clear()


def test_cooldown_api_returns_retry_after(client) -> None:
    class Service:
        async def sync(self, request, actor_id):
            raise FirmsError("COOLDOWN", 429, "Tunggu sebelum sync berikutnya.", 590)

    async def dependency():
        return Service()

    app.dependency_overrides[get_firms_service] = dependency
    try:
        response = client.post(
            "/api/v1/admin/hotspots/sync", json=REQUEST.model_dump(),
            headers={"Authorization": "Bearer demo-coordinator-token"},
        )
        assert response.status_code == 429 and response.headers["Retry-After"] == "590"
    finally:
        app.dependency_overrides.clear()


def test_nationwide_sync_accepts_hotspots_outside_original_areas() -> None:
    request = SyncRequest(area_id="indonesia", source_product="VIIRS_SNPP_NRT")
    body = (HEADER + "5.5,95.3,2026-10-15,0055,N,VIIRS,n,12.5\n"
            + "-8.5,140.5,2026-10-15,0055,N,VIIRS,n,8\n")
    rows = parse_response(body.encode(), request, date(2026, 10, 13), date(2026, 10, 15))
    assert len(rows) == 2

    def handler(upstream):
        assert "/94.0,-11.5,141.5,6.5/3/2026-10-13" in str(upstream.url)
        return httpx.Response(200, content=body.encode())

    result = asyncio.run(FirmsClient("test-secret", httpx.MockTransport(handler)).fetch(
        request, date(2026, 10, 13), date(2026, 10, 15)
    ))
    assert len(result.records) == 2
    with pytest.raises(FirmsError):
        parse_response((HEADER + ROW.replace("103.5", "150")).encode(), request,
                       date(2026, 10, 13), date(2026, 10, 15))
