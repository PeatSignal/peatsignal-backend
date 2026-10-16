from datetime import date, datetime
from typing import Literal

from pydantic import BaseModel


class RainfallDay(BaseModel):
    date: date
    rainfall_mm: float | None
    valid_cells: int | None = None
    source_url: str
    kind: Literal["HISTORICAL_ESTIMATE", "MODEL_ESTIMATE", "FORECAST"] = "HISTORICAL_ESTIMATE"
    eligible_for_assessment: bool = True


class ChirpsRainfall(BaseModel):
    status: Literal["AVAILABLE", "PARTIAL", "NOT_AVAILABLE", "PENDING", "ERROR"]
    dataset_id: Literal["UCSB-CHG/CHIRPS/DAILY", "OPEN_METEO_PRECIPITATION"] = (
        "UCSB-CHG/CHIRPS/DAILY"
    )
    provider: Literal["CLIMATESERV", "OPEN_METEO"] = "CLIMATESERV"
    scope: Literal["REGIONAL_DEMO_BBOX", "REGIONAL_REFERENCE_POINT"] = "REGIONAL_DEMO_BBOX"
    area_id: Literal["batanghari", "kubu-raya"]
    area_label: str
    bbox: list[float]
    resolution_degrees: float | None = 0.05
    statistic: Literal["MEAN_VALID_CELLS", "MODEL_GRID_POINT"] = "MEAN_VALID_CELLS"
    date_from: date
    date_to: date
    retrieved_at: datetime
    days: list[RainfallDay]
    note: str
    job_id: str | None = None
    reference_point: list[float] | None = None
