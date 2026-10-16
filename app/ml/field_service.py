from datetime import UTC, datetime, timedelta

import numpy as np

from app.data.prevention import assess_prevention
from app.ml.artifacts import MlArtifactStore
from app.ml.pipeline import build_forecast_features
from app.schemas.prevention import FieldForecast, PreventionRequest, PreventionResponse
from app.schemas.rainfall import ChirpsRainfall


class FieldForecastService:
    """Stateless inference: manual/demo input never becomes a measured database record."""

    def __init__(self, artifacts: MlArtifactStore):
        self.artifacts = artifacts

    def assess(
        self, request: PreventionRequest, rainfall: ChirpsRainfall | None = None
    ) -> PreventionResponse:
        if request.rainfall_mode != "MANUAL":
            # Client-supplied rain values cannot impersonate a CHIRPS observation.
            values = {} if rainfall is None else {
                row.date: row.rainfall_mm if row.eligible_for_assessment else None
                for row in rainfall.days
            }
            request = request.model_copy(update={"readings": [
                row.model_copy(update={"rainfall_mm": values.get(row.date)})
                for row in request.readings
            ]})
        last = request.readings[-1]
        fresh = (datetime.now(UTC).date() - last.date).days <= 2
        forecast = FieldForecast(
            status="NOT_AVAILABLE", forecast_date=last.date + timedelta(days=1),
            reason="Perbarui tujuh hari input; pengukuran terakhir lebih dari dua hari lalu.",
        )
        limitations = [
            "Input pengguna belum diverifikasi; contoh DEMO bukan pengukuran lapangan.",
            "Model dilatih pada 2018–2019; akurasi pada kondisi sekarang belum divalidasi.",
            "Rekomendasi memakai pengukuran GWT, bukan output model eksperimental.",
            "Acuan −0,40 m, penurunan 5 cm dan hujan <10 mm/7 hari adalah aturan prototipe.",
            "Hasil berlaku di stasiun input; bukan estimasi wilayah atau peluang kebakaran.",
            "Input ini tidak disimpan sebagai observasi atau mengubah dashboard pemantauan.",
        ]
        if fresh:
            forecast = self._predict(request)
        prevention = assess_prevention(request, fresh=fresh)
        if request.rainfall_mode != "MANUAL":
            limitations.append(
                "Hujan otomatis adalah estimasi wilayah; bukan hujan terukur di stasiun."
            )
            prevention.reasons.append(
                "Sumber hujan: " + (
                    "Open-Meteo, titik acuan DEMO Batanghari."
                    if rainfall is not None and rainfall.provider == "OPEN_METEO"
                    else "CHIRPS v2 Final, wilayah DEMO Batanghari."
                )
            )
            if rainfall is not None:
                limitations.append(rainfall.note)
        return PreventionResponse(
            station_code=request.station_code, source_kind=request.source_kind,
            source_note=request.source_note, is_simulation=request.source_kind == "DEMO",
            input_date=last.date, freshness="RECENT" if fresh else "STALE",
            observation_status=(
                "SIMULATED" if request.source_kind == "DEMO" else "USER_PROVIDED_UNVERIFIED"
            ),
            forecast=forecast, prevention=prevention,
            limitations=limitations, rainfall=rainfall, readings=request.readings,
        )

    def _predict(self, request: PreventionRequest) -> FieldForecast:
        last = request.readings[-1]
        forecast_date = last.date + timedelta(days=1)
        baseline = FieldForecast(
            status="BASELINE_ONLY", forecast_date=forecast_date,
            selected_method="PERSISTENCE", selected_gwt_m=last.gwt_m,
            baseline_gwt_m=last.gwt_m,
            reason="Artifact model belum tersedia; pembanding memakai GWT terakhir.",
        )
        try:
            manifest = self.artifacts.find_manifest(request.station_code)
        except (OSError, ValueError):
            baseline.reason = "Artifact model tidak tersedia; pembanding memakai GWT terakhir."
            return baseline
        if manifest is None:
            return baseline
        features = build_forecast_features(
            {row.date: row.gwt_m for row in request.readings}, forecast_date
        )
        try:
            model = self.artifacts.load_model(manifest)
            predicted = last.gwt_m + float(model.predict(np.asarray([features]))[0])
            if not np.isfinite(predicted):
                raise ValueError("Non-finite model output")
        except (OSError, ValueError, KeyError):
            baseline.reason = "Artifact model tidak dapat dibaca; pembanding memakai GWT terakhir."
            return baseline
        # Historical skill selects the comparison, never an operational release approval.
        prefer_model = (
            manifest["mae_cm"] < manifest["baseline_mae_cm"]
            and manifest["rmse_cm"] < manifest["baseline_rmse_cm"]
        )
        return FieldForecast(
            status="EXPERIMENTAL", forecast_date=forecast_date,
            selected_method="RANDOM_FOREST" if prefer_model else "PERSISTENCE",
            selected_gwt_m=predicted if prefer_model else last.gwt_m,
            model_gwt_m=predicted, baseline_gwt_m=last.gwt_m,
            model_version=manifest["model_version"], model_mae_cm=manifest["mae_cm"],
            baseline_mae_cm=manifest["baseline_mae_cm"],
            reason=(
                "Model lebih baik pada MAE dan RMSE historis; tetap bersifat eksperimental."
                if prefer_model else
                "Baseline dipilih: model belum lebih baik pada MAE dan RMSE historis."
            ),
        )
