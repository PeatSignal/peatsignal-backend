import json
from datetime import UTC, datetime, timedelta

import pytest
from pydantic import ValidationError
from test_ml_api import _artifact_store

from app.api.routes.prevention import get_field_service
from app.main import app
from app.ml.field_service import FieldForecastService
from app.schemas.prevention import PreventionRequest


def payload(*, source="DEMO", rain=0, age=0, gwt=None):
    end = datetime.now(UTC).date() - timedelta(days=age)
    values = gwt or [-0.32, -0.35, -0.39, -0.42, -0.45, -0.48, -0.52]
    return {
        "station_code": "BRG6", "source_kind": source, "source_note": "Skenario tes",
        "readings": [
            {"date": (end - timedelta(days=6-i)).isoformat(),
             "gwt_m": value, "rainfall_mm": rain}
            for i, value in enumerate(values)
        ],
    }


def assess(tmp_path, body):
    service = FieldForecastService(_artifact_store(tmp_path))
    return service.assess(PreventionRequest.model_validate(body))


def test_current_manual_input_uses_actual_model_and_keeps_provenance(tmp_path):
    result = assess(tmp_path, payload(source="MANUAL"))
    assert result.observation_status == "USER_PROVIDED_UNVERIFIED"
    assert not result.is_simulation
    assert result.forecast.model_gwt_m == pytest.approx(-0.51)
    assert result.forecast.forecast_date == datetime.now(UTC).date() + timedelta(days=1)
    assert result.forecast.selected_method == "PERSISTENCE"
    assert result.forecast.selected_gwt_m == -0.52
    assert result.forecast.model_mae_cm == 2.8
    assert result.prevention.priority == "HIGH"
    assert not result.prevention.forecast_used
    assert result.prevention.rainfall_7d_mm == 0
    assert result.prevention.dry_spell_days == 7


def test_demo_flag_survives_inference_and_missing_rain_is_not_zero(tmp_path):
    result = assess(tmp_path, payload(rain=None))
    assert result.is_simulation and result.source_kind == "DEMO"
    assert result.prevention.rainfall_7d_mm is None
    assert result.prevention.dry_spell_days is None
    assert result.prevention.missing_inputs
    assert result.prevention.priority == "HIGH"  # GWT alone can justify inspection.


def test_rainfall_changes_advice_without_masking_low_groundwater(tmp_path):
    readings = [-0.45] * 7
    dry = assess(tmp_path, payload(gwt=readings, rain=0))
    wet = assess(tmp_path, payload(gwt=readings, rain=20))
    assert dry.prevention.priority == "HIGH"
    assert wet.prevention.priority == "MEDIUM"
    assert wet.prevention.latest_gwt_m == -0.45


def test_stale_data_cannot_produce_current_forecast(tmp_path):
    result = assess(tmp_path, payload(age=3))
    assert result.freshness == "STALE"
    assert result.forecast.status == "NOT_AVAILABLE"
    assert result.forecast.selected_gwt_m is None
    assert result.prevention.priority == "INSUFFICIENT_DATA"


def test_model_must_beat_both_historical_metrics_to_be_selected(tmp_path):
    store = _artifact_store(tmp_path)
    path = tmp_path / "brg6.metrics.json"
    manifest = json.loads(path.read_text())
    manifest["mae_cm"] = 1.0
    path.write_text(json.dumps(manifest))
    service = FieldForecastService(store)
    request = PreventionRequest.model_validate(payload())
    # A lower MAE alone cannot override the worse RMSE.
    assert service.assess(request).forecast.selected_method == "PERSISTENCE"
    manifest["rmse_cm"] = 2.0
    path.write_text(json.dumps(manifest))
    result = service.assess(request)
    assert result.forecast.selected_method == "RANDOM_FOREST"
    assert result.forecast.selected_gwt_m == pytest.approx(-0.51)
    assert not result.prevention.forecast_used


@pytest.mark.parametrize("mutation", [
    lambda body: body["readings"].pop(),
    lambda body: body["readings"][0].update(date=body["readings"][1]["date"]),
    lambda body: body["readings"][0].update(gwt_m=float("nan")),
    lambda body: body["readings"][0].update(rainfall_mm=-1),
    lambda body: body.update(source_note="   "),
    lambda body: body.update(source_kind="LIVE_SENSOR"),
])
def test_invalid_field_data_is_rejected(mutation):
    body = payload()
    mutation(body)
    with pytest.raises(ValidationError):
        PreventionRequest.model_validate(body)


def test_future_measurements_rejected():
    with pytest.raises(ValidationError):
        PreventionRequest.model_validate(payload(age=-1))


def test_endpoint_without_database_and_missing_model_keeps_recommendations(client, tmp_path):
    from app.ml.artifacts import MlArtifactStore

    app.dependency_overrides[get_field_service] = lambda: FieldForecastService(
        MlArtifactStore(tmp_path)
    )
    try:
        response = client.post("/api/v1/prevention/assess", json=payload())
        assert response.status_code == 200
        data = response.json()
        assert data["forecast"]["status"] == "BASELINE_ONLY"
        assert data["forecast"]["model_gwt_m"] is None
        assert data["prevention"]["priority"] == "HIGH"
    finally:
        app.dependency_overrides.pop(get_field_service)
