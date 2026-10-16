from dataclasses import dataclass

from app.schemas.common import TaskStatus, UserRole

TRANSITIONS: dict[TaskStatus, frozenset[TaskStatus]] = {
    TaskStatus.OPEN: frozenset({TaskStatus.ASSIGNED}),
    TaskStatus.ASSIGNED: frozenset({TaskStatus.IN_PROGRESS}),
    TaskStatus.IN_PROGRESS: frozenset({TaskStatus.SUBMITTED}),
    TaskStatus.SUBMITTED: frozenset(
        {TaskStatus.VERIFIED, TaskStatus.DISMISSED, TaskStatus.NEEDS_FOLLOWUP}
    ),
    TaskStatus.NEEDS_FOLLOWUP: frozenset({TaskStatus.ASSIGNED}),
    TaskStatus.VERIFIED: frozenset(),
    TaskStatus.DISMISSED: frozenset(),
}

TRANSITION_ROLE: dict[TaskStatus, UserRole] = {
    TaskStatus.ASSIGNED: UserRole.COORDINATOR,
    TaskStatus.IN_PROGRESS: UserRole.FIELD_OFFICER,
    TaskStatus.SUBMITTED: UserRole.FIELD_OFFICER,
    TaskStatus.VERIFIED: UserRole.COORDINATOR,
    TaskStatus.DISMISSED: UserRole.COORDINATOR,
    TaskStatus.NEEDS_FOLLOWUP: UserRole.COORDINATOR,
}


@dataclass(frozen=True, slots=True)
class WorkflowViolation(Exception):
    status_code: int
    detail: str


def validate_transition(
    *,
    current: TaskStatus,
    target: TaskStatus,
    actor_role: UserRole,
    actor_is_assignee: bool,
    effective_assignee: bool,
    via_report: bool = False,
) -> None:
    if target not in TRANSITIONS[current]:
        raise WorkflowViolation(409, f"Transisi {current.value} → {target.value} tidak diizinkan")
    required_role = TRANSITION_ROLE[target]
    if actor_role != required_role:
        raise WorkflowViolation(403, "Peran pengguna tidak diizinkan melakukan transisi ini")
    if target == TaskStatus.SUBMITTED and not via_report:
        raise WorkflowViolation(409, "Status SUBMITTED hanya dapat dicapai melalui laporan")
    if target is TaskStatus.ASSIGNED and not effective_assignee:
        raise WorkflowViolation(409, "Pilih petugas lapangan sebelum menugaskan")
    if target in {TaskStatus.IN_PROGRESS, TaskStatus.SUBMITTED} and not actor_is_assignee:
        raise WorkflowViolation(403, "Hanya petugas yang ditugaskan dapat memperbarui tugas")
