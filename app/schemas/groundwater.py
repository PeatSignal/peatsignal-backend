from datetime import date, datetime

from pydantic import BaseModel, ConfigDict

from app.schemas.common import MonitoringMode, QualityFlag


class GroundwaterObservation(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    station_id: str
    observed_date: date
    observed_at: datetime
    gwt_m: float | None
    quality_flag: QualityFlag
    source: str
    source_id: str
    source_sha256: str
    mode: MonitoringMode

