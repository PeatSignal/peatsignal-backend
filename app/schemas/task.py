from datetime import datetime
from typing import Annotated, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, StringConstraints, model_validator

from app.schemas.common import MonitoringMode, PriorityLevel, TaskStatus, UserRole

AreaId = Literal["batanghari", "kubu-raya"]


class TaskStatusChange(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    from_status: TaskStatus | None = Field(serialization_alias="from")
    to_status: TaskStatus = Field(serialization_alias="to")
    actor_id: str
    actor_role: UserRole
    changed_at: datetime = Field(serialization_alias="at")
    note: str | None = None


class InspectionTask(BaseModel):
    id: str
    mode: MonitoringMode
    title: str
    status: TaskStatus
    priority: PriorityLevel
    assessment_id: str | None = None
    hotspot_id: str | None = None
    area_id: AreaId | None = None
    assignee_id: str | None = None
    created_by: str
    created_at: datetime
    updated_at: datetime
    note: str | None = None
    history: list[TaskStatusChange]
    is_simulation: bool


class InspectionTaskDetail(InspectionTask):
    reports: list["FieldReport"]


class InspectionTaskCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    mode: MonitoringMode
    title: Annotated[
        str, StringConstraints(strip_whitespace=True, min_length=5, max_length=120)
    ]
    priority: PriorityLevel
    assessment_id: UUID | None = None
    hotspot_id: UUID | None = None
    area_id: AreaId | None = None
    assignee_id: UUID | None = None
    note: Annotated[str, StringConstraints(max_length=500)] | None = None

    @model_validator(mode="after")
    def require_reference(self) -> "InspectionTaskCreate":
        if self.assessment_id is None and self.hotspot_id is None:
            raise ValueError("Tugas harus merujuk assessment atau hotspot")
        return self


class InspectionTaskUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    status: TaskStatus | None = None
    assignee_id: UUID | None = None
    note: Annotated[str, StringConstraints(max_length=500)] | None = None

    @model_validator(mode="after")
    def require_change(self) -> "InspectionTaskUpdate":
        if not self.model_fields_set:
            raise ValueError("Tidak ada perubahan")
        return self


from app.schemas.report import FieldReport  # noqa: E402

InspectionTaskDetail.model_rebuild()
