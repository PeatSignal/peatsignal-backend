import asyncio
from datetime import UTC, date, datetime, timedelta

import httpx
import pytest
from test_prevention import payload

from app.api.routes.prevention import get_field_service
from app.api.routes.rainfall import get_chirps_client
from app.data.chirps import ChirpsClient, parse_days
from app.main import app
from app.ml.artifacts import MlArtifactStore
from app.ml.field_service import FieldForecastService

JOB = "d8cb44c3-712a-4c72-964c-93ba84304c89"
END = date(2019, 9, 15)
START = END - timedelta(days=6)


def response_data(end=END, values=(0, 0, 0, 0, 0, 0.961839, 3.424721)):
    return {"uid": JOB, "datatype": 0, "operationtype": 5, "intervaltype": 0, "data": [
        {"date": (end-timedelta(days=6-i)).strftime("%m/%d/%Y"), "value": {"avg": value}}
        for i, value in enumerate(values)
    ]}


def transport_for(data, calls):
    def handler(request):
        method = request.url.path.strip("/").split("/")[-1]
        calls.append(method)
        if method == "submitDataRequest":
            assert request.url.params["datatype"] == "0"
            assert request.url.params["operationtype"] == "5"
            return httpx.Response(200, json=[JOB])
        if method == "getDataRequestProgress":
            return httpx.Response(200, json=[100.0])
        return httpx.Response(200, json=data)
    return httpx.MockTransport(handler)


def test_parser_preserves_real_zero_and_masks_missing_not_as_zero():
    result = parse_days(response_data(values=(0, -9999, None, "nan", 2, 3, 4)), START, END,
                        "https://climateserv.servirglobal.net/api/getDataFromRequest/")
    assert [row.rainfall_mm for row in result] == [0, None, None, None, 2, 3, 4]
    assert [row.date for row in result] == [START + timedelta(days=i) for i in range(7)]


@pytest.mark.parametrize("bad", ["duplicate", "future_row", "wrong_dataset", "monthly", "bool"])
def test_parser_rejects_unmatched_data(bad):
    data = response_data()
    if bad == "duplicate":
        data["data"][0]["date"] = data["data"][1]["date"]
    elif bad == "future_row":
        data["data"][0]["date"] = "09/16/2019"
    elif bad == "wrong_dataset":
        data["datatype"] = 31
    elif bad == "monthly":
        data["intervaltype"] = 1
    else:
        data["data"][0]["value"]["avg"] = True
    with pytest.raises(ValueError):
        parse_days(data, START, END, "https://example.org/result")


def test_client_reuses_cached_job_and_reports_regional_scope():
    calls = []
    service = ChirpsClient(transport_for(response_data(), calls))

    async def run():
        first = await service.fetch("batanghari", END)
        again = await service.fetch("batanghari", END)
        return first, again
    first, again = asyncio.run(run())
    assert first.status == again.status == "AVAILABLE"
    assert first.scope == "REGIONAL_DEMO_BBOX"
    assert first.provider == "CLIMATESERV"
    assert first.days[-1].rainfall_mm == pytest.approx(3.424721)
    assert calls == ["submitDataRequest", "getDataRequestProgress", "getDataFromRequest"]


def test_upstream_error_is_not_a_dry_week():
    service = ChirpsClient(httpx.MockTransport(lambda _: httpx.Response(503)))
    result = asyncio.run(service.fetch("batanghari", END))
    assert result.status == "ERROR"
    assert all(row.rainfall_mm is None for row in result.days)


def test_pending_request_resumes_same_job(monkeypatch):
    async def no_delay(_):
        return None
    monkeypatch.setattr("app.data.chirps.asyncio.sleep", no_delay)
    ready = False
    calls = []

    def handler(request):
        method = request.url.path.strip("/").split("/")[-1]
        calls.append(method)
        if method == "submitDataRequest":
            return httpx.Response(200, json=[JOB])
        if method == "getDataRequestProgress":
            return httpx.Response(200, json=[100 if ready else 0])
        return httpx.Response(200, json=response_data())

    service = ChirpsClient(httpx.MockTransport(handler))

    async def run():
        nonlocal ready
        pending = await service.fetch("batanghari", END)
        assert pending.status == "PENDING"
        assert all(row.rainfall_mm is None for row in pending.days)
        ready = True
        return await service.fetch("batanghari", END)
    result = asyncio.run(run())
    assert result.status == "AVAILABLE"
    assert calls.count("submitDataRequest") == 1


def test_partial_dates_are_not_shifted_to_the_missing_dates():
    data = response_data()
    data["data"].pop(2)
    service = ChirpsClient(transport_for(data, []))
    result = asyncio.run(service.fetch("batanghari", END))
    assert result.status == "PARTIAL"
    assert result.days[2].rainfall_mm is None
    assert result.days[-1].date == END


def test_prevention_refetches_source_and_discards_client_chirps_values(client, tmp_path):
    end = datetime.now(UTC).date()
    chirps = ChirpsClient(transport_for(response_data(end, values=(-9999,)*7), []))
    app.dependency_overrides[get_chirps_client] = lambda: chirps
    app.dependency_overrides[get_field_service] = lambda: FieldForecastService(
        MlArtifactStore(tmp_path)
    )
    try:
        body = payload(rain=0)
        body["rainfall_mode"] = "CHIRPS"
        response = client.post("/api/v1/prevention/assess", json=body)
        assert response.status_code == 200
        result = response.json()
        assert result["rainfall"]["status"] == "NOT_AVAILABLE"
        assert result["prevention"]["rainfall_7d_mm"] is None
        assert result["prevention"]["dry_spell_days"] is None
        assert all(row["rainfall_mm"] is None for row in result["readings"])
        assert result["rainfall"]["area_id"] == "batanghari"
        assert client.get(
            "/api/v1/rainfall/chirps?area_id=batanghari&date_to=2099-01-01"
        ).status_code == 422
    finally:
        app.dependency_overrides.pop(get_chirps_client)
        app.dependency_overrides.pop(get_field_service)
