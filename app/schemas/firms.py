from datetime import date, datetime
from typing import Literal

from pydantic import BaseModel, Field

AreaId = Literal["batanghari", "kubu-raya", "indonesia"]
FirmsProduct = Literal["VIIRS_SNPP_NRT", "VIIRS_NOAA20_NRT"]


class SyncRequest(BaseModel):
    area_id: AreaId
    source_product: FirmsProduct
    day_range: int = Field(default=3, ge=1, le=5)


class SyncResult(BaseModel):
    id: str
    area_id: AreaId
    source_product: FirmsProduct
    status: Literal["RUNNING", "SUCCESS", "FAILED"]
    date_from: date
    date_to: date
    started_at: datetime
    completed_at: datetime | None
    rows_received: int
    rows_inserted: int
    rows_conflicts: int
    error_code: str | None


class SyncStatus(BaseModel):
    area_id: AreaId
    source_product: FirmsProduct
    status: Literal["NOT_SYNCED", "RUNNING", "SUCCESS", "FAILED"]
    last_attempt: SyncResult | None
    last_successful_at: datetime | None
