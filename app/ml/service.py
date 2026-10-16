from datetime import timedelta
from uuid import UUID

import numpy as np

from app.ml.artifacts import MlArtifactStore
from app.ml.pipeline import MlDataError, build_forecast_features
from app.repositories.ml import MlRepository
from app.schemas.ml import (
    ErrorMetrics,
    MlExperiment,
    MlForecastOk,
    MlForecastRejected,
    MlForecastRequest,
    MlForecastResponse,
    MlMetricsAvailable,
    MlMetricsNotAvailable,
    MlMetricsResponse,
    MlPredictionPoint,
)


class MlService:
    def __init__(self, repository: MlRepository, artifacts: MlArtifactStore) -> None:
        self.repository = repository
        self.artifacts = artifacts

    async def metrics(self) -> MlMetricsResponse:
        manifests = self.artifacts.list_manifests()
        if not manifests:
            return MlMetricsNotAvailable(
                reason="Model GWT belum dilatih atau artifact belum tersedia."
            )
        station_ids = await self.repository.station_ids_by_codes(
            [manifest["station_code"] for manifest in manifests]
        )
        experiments = [
            self._experiment(manifest, station_ids.get(manifest["station_code"]))
            for manifest in manifests
            if manifest["station_code"] in station_ids
        ]
        if not experiments:
            return MlMetricsNotAvailable(
                reason="Artifact tersedia tetapi stasiun sumber tidak ditemukan."
            )
        return MlMetricsAvailable(experiments=experiments)

    async def forecast(self, request: MlForecastRequest) -> MlForecastResponse:
        try:
            station_id = UUID(request.station_id)
        except ValueError:
            return MlForecastRejected(reason="ID stasiun tidak valid.")
        station_code = await self.repository.station_code(station_id)
        if station_code is None:
            return MlForecastRejected(reason="Stasiun tidak ditemukan.")
        manifest = self.artifacts.find_manifest(station_code)
        if manifest is None:
            return MlForecastRejected(reason="Model untuk stasiun ini belum tersedia.")

        forecast_date = request.date + timedelta(days=1)
        values = await self.repository.valid_history(
            station_id, request.date - timedelta(days=6), request.date
        )
        try:
            features = build_forecast_features(values, forecast_date)
        except MlDataError:
            return MlForecastRejected(
                reason=(
                    "Forecast historis memerlukan tujuh hari kalender berurutan "
                    "dengan observasi GWT valid."
                )
            )
        model = self.artifacts.load_model(manifest)
        baseline = features[0]
        predicted = baseline + float(
            model.predict(np.asarray([features], dtype=float))[0]
        )
        return MlForecastOk(
            station_id=request.station_id,
            input_date=request.date,
            forecast_date=forecast_date,
            predicted_gwt_m=predicted,
            baseline_gwt_m=baseline,
            model_version=manifest["model_version"],
            release_gate=manifest["release_gate"],
        )

    @staticmethod
    def _experiment(manifest: dict, station_id: str | None) -> MlExperiment:
        if station_id is None:
            raise ValueError("Station ID is required")
        return MlExperiment(
            model_version=manifest["model_version"],
            model_type="RandomForestRegressor",
            station_id=station_id,
            station_code=manifest["station_code"],
            target="GWT_T_PLUS_1_DAY",
            features=manifest["features"],
            training_period={
                "from": manifest["training_from"],
                "to": manifest["training_to"],
            },
            test_period={"from": manifest["test_from"], "to": manifest["test_to"]},
            test_size=manifest["test_size"],
            model_metrics=ErrorMetrics(
                mae_cm=manifest["mae_cm"], rmse_cm=manifest["rmse_cm"]
            ),
            baseline_metrics=ErrorMetrics(
                mae_cm=manifest["baseline_mae_cm"],
                rmse_cm=manifest["baseline_rmse_cm"],
            ),
            beats_baseline=manifest["beats_baseline"],
            predictions=[
                MlPredictionPoint(
                    date=point["date"],
                    actual_m=point["actual_gwt_m"],
                    predicted_m=point["predicted_gwt_m"],
                    baseline_m=point["baseline_gwt_m"],
                )
                for point in manifest["predictions"]
            ],
            trained_at=manifest["trained_at"],
            release_gate=manifest["release_gate"],
            limitations=manifest["limitations"],
        )
