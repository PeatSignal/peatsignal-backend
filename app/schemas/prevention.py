from datetime import UTC, date, datetime, timedelta
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.schemas.rainfall import ChirpsRainfall


class DailyFieldReading(BaseModel):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)

    date: date
    gwt_m: float = Field(ge=-10, le=2)
    rainfall_mm: float | None = Field(default=None, ge=0, le=1500)


class PreventionRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    station_code: Literal["BRG3", "BRG6"]
    source_kind: Literal["MANUAL", "DEMO"]
    source_note: str = Field(min_length=3, max_length=300)
    rainfall_mode: Literal["MANUAL", "CHIRPS", "AUTO"] = "MANUAL"
    readings: list[DailyFieldReading] = Field(min_length=7, max_length=7)

    @model_validator(mode="after")
    def validate_window(self):
        self.source_note = self.source_note.strip()
        if len(self.source_note) < 3:
            raise ValueError("Jelaskan sumber pengukuran (minimal 3 karakter).")
        self.readings.sort(key=lambda reading: reading.date)
        start = self.readings[0].date
        if any(row.date != start + timedelta(days=i) for i, row in enumerate(self.readings)):
            raise ValueError("Masukkan tujuh tanggal berurutan tanpa tanggal duplikat.")
        if self.readings[-1].date > datetime.now(UTC).date():
            raise ValueError("Pengukuran tidak boleh bertanggal masa depan (UTC).")
        if self.rainfall_mode != "MANUAL" and start < date(1981, 1, 1):
            raise ValueError("CHIRPS tersedia mulai 1981.")
        return self


class PreventionDecision(BaseModel):
    priority: Literal["LOW", "MEDIUM", "HIGH", "INSUFFICIENT_DATA"]
    explanation: str
    reasons: list[str]
    recommended_actions: list[str]
    missing_inputs: list[str]
    latest_gwt_m: float
    change_m: float
    rainfall_7d_mm: float | None
    rainfall_days: int
    dry_spell_days: int | None
    reference_gwt_m: float
    rule_version: str
    scientific_status: Literal["heuristic_not_validated"] = "heuristic_not_validated"
    forecast_used: Literal[False] = False


class FieldForecast(BaseModel):
    status: Literal["EXPERIMENTAL", "BASELINE_ONLY", "NOT_AVAILABLE"]
    reason: str
    forecast_date: date
    selected_method: Literal["PERSISTENCE", "RANDOM_FOREST"] | None = None
    selected_gwt_m: float | None = None
    model_gwt_m: float | None = None
    baseline_gwt_m: float | None = None
    model_version: str | None = None
    model_mae_cm: float | None = None
    baseline_mae_cm: float | None = None


class PreventionResponse(BaseModel):
    station_code: str
    source_kind: Literal["MANUAL", "DEMO"]
    source_note: str
    is_simulation: bool
    input_date: date
    freshness: Literal["RECENT", "STALE"]
    observation_status: Literal["USER_PROVIDED_UNVERIFIED", "SIMULATED"]
    forecast: FieldForecast
    prevention: PreventionDecision
    limitations: list[str]
    rainfall: ChirpsRainfall | None = None
    readings: list[DailyFieldReading] | None = None
