from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict

from app.schemas.common import MonitoringMode, PriorityLevel


class PriorityAssessment(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    area_id: Literal["batanghari", "kubu-raya"]
    decision: Literal["REVIEW", "MONITOR", "ESCALATE", "INSUFFICIENT_DATA"]
    mode: MonitoringMode
    as_of: datetime
    priority: PriorityLevel
    explanation: str
    reason_codes: list[str]
    missing_inputs: list[str]
    input_snapshot: dict[str, Any]
    rule_version: str
    recommended_actions: list[str]
    scientific_status: Literal["heuristic_not_validated"] = "heuristic_not_validated"

