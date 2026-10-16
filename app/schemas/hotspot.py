from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field

from app.schemas.common import MonitoringMode, QualityFlag, VerificationStatus


class Hotspot(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    external_key: str
    latitude: float = Field(ge=-90, le=90)
    longitude: float = Field(ge=-180, le=180)
    acquired_at: datetime
    source_product: str
    sensor: str
    satellite: str
    frp: float | None = None
    confidence_raw: str | None = None
    verification_status: VerificationStatus
    source: str
    quality_flag: QualityFlag
    mode: MonitoringMode
    last_synced_at: datetime


class HotspotPage(BaseModel):
    items: list[Hotspot]
    total: int = Field(ge=0)
    limit: int = Field(ge=1, le=1000)
    offset: int = Field(ge=0)



class HotspotMapPoint(BaseModel):
    id: str
    latitude: float = Field(ge=-90, le=90)
    longitude: float = Field(ge=-180, le=180)
    observed_at: datetime
    frp_mw: float | None
    verification_status: VerificationStatus
    list_offset: int = Field(ge=0)


class HotspotMap(BaseModel):
    mode: MonitoringMode
    items: list[HotspotMapPoint]
