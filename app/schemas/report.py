from datetime import datetime
from typing import Annotated, Literal

from pydantic import AnyHttpUrl, AwareDatetime, BaseModel, ConfigDict, StringConstraints

FieldReportResult = Literal[
    "ACTIVE_FIRE_FOUND",
    "BURN_SCAR_FOUND",
    "NO_FIRE_FOUND",
    "LOCATION_INACCESSIBLE",
]


class FieldReport(BaseModel):
    id: str
    task_id: str
    observed_at: datetime
    result: FieldReportResult
    note: str
    evidence_url: str | None = None
    submitted_by: str
    submitted_at: datetime
    is_simulation: bool


class FieldReportCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    observed_at: AwareDatetime
    result: FieldReportResult
    note: Annotated[
        str, StringConstraints(strip_whitespace=True, min_length=3, max_length=1000)
    ]
    evidence_url: AnyHttpUrl | None = None
    is_simulation: bool
