import asyncio
import json
from datetime import date, timedelta
from uuid import UUID

import joblib
import numpy as np
from conftest import AsgiClient

from app.api.routes.contracts import get_ml_service
from app.main import app
from app.ml.artifacts import MlArtifactStore
from app.ml.service import MlService
from app.schemas.ml import MlForecastRequest

STATION_ID = UUID("11111111-1111-4111-8111-111111111111")


class ConstantDeltaModel:
    def predict(self, values):
        return np.full(len(values), 0.01)


class FakeMlRepository:
    def __init__(self, *, complete_history: bool = True) -> None:
        self.complete_history = complete_history

    async def station_ids_by_codes(self, codes: list[str]) -> dict[str, str]:
        return {code: str(STATION_ID) for code in codes}

    async def station_code(self, station_id: UUID) -> str | None:
        return "BRG6" if station_id == STATION_ID else None

    async def valid_history(
        self, station_id: UUID, date_from: date, date_to: date
    ) -> dict[date, float]:
        del station_id
        values = {
            date_from + timedelta(days=offset): -0.5 - offset / 100
            for offset in range((date_to - date_from).days + 1)
        }
        if not self.complete_history:
            values.pop(date_from + timedelta(days=2))
        return values


def _artifact_store(tmp_path) -> MlArtifactStore:
    artifact_file = "gwt-rf-brg6-test.joblib"
    joblib.dump(ConstantDeltaModel(), tmp_path / artifact_file)
    manifest = {
        "model_version": "gwt-rf-brg6-test",
        "station_code": "BRG6",
        "artifact_file": artifact_file,
        "trained_at": "2026-10-15T00:00:00Z",
        "features": ["lag_1_m"],
        "training_from": "2018-04-18",
        "training_to": "2019-07-18",
        "test_from": "2019-07-19",
        "test_to": "2019-10-07",
        "test_size": 81,
        "mae_cm": 2.8,
        "rmse_cm": 4.1,
        "baseline_mae_cm": 1.7,
        "baseline_rmse_cm": 3.1,
        "beats_baseline": False,
        "release_gate": "EXPERIMENT_ONLY",
        "limitations": ["Historis saja."],
        "predictions": [
            {
                "date": "2019-07-19",
                "actual_gwt_m": -0.77,
                "predicted_gwt_m": -0.76,
                "baseline_gwt_m": -0.75,
            }
        ],
    }
    (tmp_path / "brg6.metrics.json").write_text(json.dumps(manifest))
    return MlArtifactStore(tmp_path)


def test_ml_service_returns_metrics_and_historical_forecast(tmp_path):
    service = MlService(FakeMlRepository(), _artifact_store(tmp_path))

    async def run():
        metrics = await service.metrics()
        forecast = await service.forecast(
            MlForecastRequest(station_id=str(STATION_ID), date=date(2019, 7, 18))
        )
        return metrics, forecast

    metrics, forecast = asyncio.run(run())

    assert metrics.status == "AVAILABLE"
    assert metrics.experiments[0].station_id == str(STATION_ID)
    assert metrics.experiments[0].is_simulation is False
    assert forecast.status == "OK"
    assert forecast.forecast_date == date(2019, 7, 19)
    assert forecast.predicted_gwt_m == -0.55
    assert forecast.release_gate == "EXPERIMENT_ONLY"


def test_ml_service_rejects_incomplete_lag_history(tmp_path):
    service = MlService(
        FakeMlRepository(complete_history=False), _artifact_store(tmp_path)
    )

    result = asyncio.run(
        service.forecast(
            MlForecastRequest(station_id=str(STATION_ID), date=date(2019, 7, 18))
        )
    )

    assert result.status == "REJECTED"
    assert "tujuh hari" in result.reason


def test_ml_http_contract_matches_frontend_envelope(client: AsgiClient, tmp_path):
    service = MlService(FakeMlRepository(), _artifact_store(tmp_path))

    async def override_service():
        return service

    app.dependency_overrides[get_ml_service] = override_service
    try:
        metrics = client.get("/api/v1/ml/metrics")
        forecast = client.post(
            "/api/v1/ml/forecast",
            json={"station_id": str(STATION_ID), "date": "2019-07-18"},
        )
    finally:
        app.dependency_overrides.pop(get_ml_service, None)

    assert metrics.status_code == 200
    assert metrics.json()["status"] == "AVAILABLE"
    assert metrics.json()["experiments"][0]["target"] == "GWT_T_PLUS_1_DAY"
    assert forecast.status_code == 200
    assert forecast.json()["status"] == "OK"
