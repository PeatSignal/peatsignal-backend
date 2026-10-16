from datetime import date, datetime
from typing import Literal

from pydantic import BaseModel, Field


class ErrorMetrics(BaseModel):
    mae_cm: float = Field(ge=0)
    rmse_cm: float = Field(ge=0)


class MlPredictionPoint(BaseModel):
    date: date
    actual_m: float
    predicted_m: float
    baseline_m: float


class DatePeriod(BaseModel):
    from_: date = Field(alias="from")
    to: date


class MlExperiment(BaseModel):
    model_version: str
    model_type: Literal["RandomForestRegressor"]
    station_id: str
    station_code: str
    target: Literal["GWT_T_PLUS_1_DAY"]
    features: list[str]
    training_period: DatePeriod
    test_period: DatePeriod
    test_size: int = Field(gt=0)
    model_metrics: ErrorMetrics
    baseline_metrics: ErrorMetrics
    beats_baseline: bool
    predictions: list[MlPredictionPoint]
    trained_at: datetime
    is_simulation: Literal[False] = False
    release_gate: Literal["EXPERIMENT_ONLY", "ELIGIBLE_FOR_HISTORICAL_FORECAST"]
    limitations: list[str]


class MlMetricsAvailable(BaseModel):
    status: Literal["AVAILABLE"] = "AVAILABLE"
    experiments: list[MlExperiment]


class MlMetricsNotAvailable(BaseModel):
    status: Literal["NOT_AVAILABLE"] = "NOT_AVAILABLE"
    reason: str


MlMetricsResponse = MlMetricsAvailable | MlMetricsNotAvailable


class MlForecastRequest(BaseModel):
    station_id: str
    date: date


class MlForecastOk(BaseModel):
    status: Literal["OK"] = "OK"
    station_id: str
    input_date: date
    forecast_date: date
    predicted_gwt_m: float
    baseline_gwt_m: float
    model_version: str
    release_gate: Literal["EXPERIMENT_ONLY", "ELIGIBLE_FOR_HISTORICAL_FORECAST"]


class MlForecastRejected(BaseModel):
    status: Literal["REJECTED"] = "REJECTED"
    reason: str


MlForecastResponse = MlForecastOk | MlForecastRejected

