from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest
from fastapi import HTTPException
from pydantic import ValidationError

from app.api.routes.tasks import parse_statuses
from app.data.task_state import WorkflowViolation, validate_transition
from app.schemas.common import TaskStatus, UserRole
from app.schemas.report import FieldReportCreate
from app.schemas.task import InspectionTaskCreate, TaskStatusChange


def test_state_machine_accepts_only_the_documented_path() -> None:
    validate_transition(
        current=TaskStatus.OPEN,
        target=TaskStatus.ASSIGNED,
        actor_role=UserRole.COORDINATOR,
        actor_is_assignee=False,
        effective_assignee=True,
    )
    validate_transition(
        current=TaskStatus.ASSIGNED,
        target=TaskStatus.IN_PROGRESS,
        actor_role=UserRole.FIELD_OFFICER,
        actor_is_assignee=True,
        effective_assignee=True,
    )
    validate_transition(
        current=TaskStatus.IN_PROGRESS,
        target=TaskStatus.SUBMITTED,
        actor_role=UserRole.FIELD_OFFICER,
        actor_is_assignee=True,
        effective_assignee=True,
        via_report=True,
    )
    for outcome in (
        TaskStatus.VERIFIED,
        TaskStatus.DISMISSED,
        TaskStatus.NEEDS_FOLLOWUP,
    ):
        validate_transition(
            current=TaskStatus.SUBMITTED,
            target=outcome,
            actor_role=UserRole.COORDINATOR,
            actor_is_assignee=False,
            effective_assignee=True,
        )


@pytest.mark.parametrize(
    ("current", "target", "role", "is_assignee", "via_report", "status_code"),
    [
        (TaskStatus.OPEN, TaskStatus.IN_PROGRESS, UserRole.COORDINATOR, False, False, 409),
        (TaskStatus.OPEN, TaskStatus.ASSIGNED, UserRole.FIELD_OFFICER, True, False, 403),
        (TaskStatus.ASSIGNED, TaskStatus.IN_PROGRESS, UserRole.FIELD_OFFICER, False, False, 403),
        (TaskStatus.IN_PROGRESS, TaskStatus.SUBMITTED, UserRole.FIELD_OFFICER, True, False, 409),
        (TaskStatus.SUBMITTED, TaskStatus.VERIFIED, UserRole.FIELD_OFFICER, True, False, 403),
        (TaskStatus.VERIFIED, TaskStatus.ASSIGNED, UserRole.COORDINATOR, False, False, 409),
    ],
)
def test_state_machine_rejects_invalid_transition_or_actor(
    current: TaskStatus,
    target: TaskStatus,
    role: UserRole,
    is_assignee: bool,
    via_report: bool,
    status_code: int,
) -> None:
    with pytest.raises(WorkflowViolation) as raised:
        validate_transition(
            current=current,
            target=target,
            actor_role=role,
            actor_is_assignee=is_assignee,
            effective_assignee=True,
            via_report=via_report,
        )
    assert raised.value.status_code == status_code


def test_task_and_report_contract_validation_and_aliases() -> None:
    task = InspectionTaskCreate.model_validate(
        {
            "mode": "CURRENT_MONITORING",
            "title": "  Periksa anomali termal  ",
            "priority": "HIGH",
            "hotspot_id": str(uuid4()),
        }
    )
    assert task.title == "Periksa anomali termal"

    with pytest.raises(ValidationError):
        InspectionTaskCreate.model_validate(
            {
                "mode": "CURRENT_MONITORING",
                "title": "Tanpa referensi",
                "priority": "HIGH",
            }
        )
    with pytest.raises(ValidationError):
        FieldReportCreate.model_validate(
            {
                "observed_at": (datetime.now(UTC) - timedelta(minutes=1)).isoformat(),
                "result": "KEBAKARAN",
                "note": "temuan",
                "is_simulation": True,
            }
        )

    change = TaskStatusChange(
        from_status="OPEN",
        to_status="ASSIGNED",
        actor_id=str(uuid4()),
        actor_role="coordinator",
        changed_at=datetime.now(UTC),
    )
    rendered = change.model_dump(mode="json", by_alias=True)
    assert rendered["from"] == "OPEN"
    assert rendered["to"] == "ASSIGNED"
    assert "at" in rendered


def test_status_filter_accepts_csv_and_rejects_unknown_value() -> None:
    assert parse_statuses("ASSIGNED, IN_PROGRESS") == (
        TaskStatus.ASSIGNED,
        TaskStatus.IN_PROGRESS,
    )
    assert parse_statuses(None) == ()
    with pytest.raises(HTTPException) as raised:
        parse_statuses("UNKNOWN")
    assert raised.value.status_code == 422
