from collections import defaultdict
from datetime import UTC, datetime
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.data.task_state import WorkflowViolation, validate_transition
from app.models.entities import (
    FieldReport as FieldReportModel,
)
from app.models.entities import (
    Hotspot,
    PriorityAssessment,
    TaskStatusHistory,
)
from app.models.entities import (
    InspectionTask as InspectionTaskModel,
)
from app.models.entities import (
    User as UserModel,
)
from app.schemas.common import MonitoringMode, TaskStatus, UserRole
from app.schemas.report import FieldReport, FieldReportCreate
from app.schemas.task import (
    InspectionTask,
    InspectionTaskCreate,
    InspectionTaskDetail,
    InspectionTaskUpdate,
    TaskStatusChange,
)
from app.schemas.user import User


class TaskRepositoryError(Exception):
    def __init__(self, status_code: int, detail: str):
        self.status_code = status_code
        self.detail = detail
        super().__init__(detail)


class TaskRepository:
    def __init__(self, session: AsyncSession):
        self.session = session

    async def list_users(self, role: UserRole | None = None) -> list[User]:
        query = select(UserModel).where(UserModel.is_active.is_(True))
        if role is not None:
            query = query.where(UserModel.role == role.value)
        users = (
            await self.session.scalars(query.order_by(UserModel.role, UserModel.display_name))
        ).all()
        return [
            User(id=str(user.id), role=user.role, display_name=user.display_name) for user in users
        ]

    async def list_tasks(
        self,
        *,
        mode: MonitoringMode | None = None,
        statuses: tuple[TaskStatus, ...] = (),
        assignee_id: UUID | None = None,
    ) -> list[InspectionTask]:
        query = select(InspectionTaskModel)
        if mode is not None:
            query = query.where(InspectionTaskModel.mode == mode.value)
        if statuses:
            query = query.where(InspectionTaskModel.status.in_([item.value for item in statuses]))
        if assignee_id is not None:
            query = query.where(InspectionTaskModel.assignee_id == assignee_id)
        tasks = (
            await self.session.scalars(
                query.order_by(InspectionTaskModel.updated_at.desc(), InspectionTaskModel.id)
            )
        ).all()
        histories = await self._load_histories([task.id for task in tasks])
        return [self._task_response(task, histories[task.id]) for task in tasks]

    async def get_task(self, task_id: UUID) -> InspectionTaskDetail:
        task = await self._load_task(task_id)
        histories = await self._load_histories([task.id])
        reports = await self._load_reports(task.id)
        return InspectionTaskDetail(
            **self._task_response(task, histories[task.id]).model_dump(),
            reports=reports,
        )

    async def create_task(self, payload: InspectionTaskCreate, actor: User) -> InspectionTask:
        if actor.role != UserRole.COORDINATOR:
            raise TaskRepositoryError(403, "Hanya koordinator yang dapat membuat tugas")

        assessment = None
        if payload.assessment_id is not None:
            assessment = await self.session.get(PriorityAssessment, payload.assessment_id)
            if assessment is None:
                raise TaskRepositoryError(422, "Assessment tidak ditemukan")
            if assessment.mode != payload.mode.value:
                raise TaskRepositoryError(422, "Mode assessment tidak sesuai dengan mode tugas")

        hotspot = None
        if payload.hotspot_id is not None:
            hotspot = await self.session.get(Hotspot, payload.hotspot_id)
            if hotspot is None:
                raise TaskRepositoryError(422, "Hotspot tidak ditemukan")
            if hotspot.mode != payload.mode.value:
                raise TaskRepositoryError(422, "Mode hotspot tidak sesuai dengan mode tugas")

        derived_area = None if assessment is None else assessment.inputs_json.get("area_id")
        if derived_area is not None and payload.area_id not in {None, derived_area}:
            raise TaskRepositoryError(422, "Area tugas tidak sesuai dengan assessment")
        area_id = derived_area or payload.area_id

        if assessment is not None and hotspot is not None:
            assessment_hotspots = {
                item.get("id") for item in assessment.inputs_json.get("hotspots", [])
            }
            if str(hotspot.id) not in assessment_hotspots:
                raise TaskRepositoryError(422, "Hotspot bukan bagian dari snapshot assessment")

        assignee = await self._field_officer(payload.assignee_id)
        now = datetime.now(UTC)
        initial_status = TaskStatus.ASSIGNED if assignee is not None else TaskStatus.OPEN
        task = InspectionTaskModel(
            mode=payload.mode.value,
            title=payload.title,
            priority=payload.priority.value,
            assessment_id=payload.assessment_id,
            hotspot_id=payload.hotspot_id,
            area_id=area_id,
            assignee_id=None if assignee is None else assignee.id,
            created_by_id=UUID(actor.id),
            status=initial_status.value,
            note=payload.note,
            is_simulation=True,
            created_at=now,
            updated_at=now,
        )
        self.session.add(task)
        await self.session.flush()
        history = [self._history(task, None, TaskStatus.OPEN, actor, now, None)]
        if initial_status == TaskStatus.ASSIGNED:
            history.append(
                self._history(
                    task,
                    TaskStatus.OPEN,
                    TaskStatus.ASSIGNED,
                    actor,
                    now,
                    "Petugas ditugaskan saat tugas dibuat",
                )
            )
        self.session.add_all(history)
        await self.session.flush()
        return self._task_response(task, [self._history_response(item) for item in history])

    async def update_task(
        self, task_id: UUID, payload: InspectionTaskUpdate, actor: User
    ) -> InspectionTask:
        task = await self._load_task(task_id, for_update=True)
        current = TaskStatus(task.status)
        target = payload.status or current
        assignee_changed = "assignee_id" in payload.model_fields_set
        note_changed = "note" in payload.model_fields_set

        if (assignee_changed or note_changed) and actor.role != UserRole.COORDINATOR:
            raise TaskRepositoryError(403, "Hanya koordinator yang dapat mengubah penugasan")

        effective_assignee = task.assignee_id
        if assignee_changed:
            assignee = await self._field_officer(payload.assignee_id)
            effective_assignee = None if assignee is None else assignee.id
            if current == TaskStatus.OPEN and target != TaskStatus.ASSIGNED:
                raise TaskRepositoryError(409, "Penugasan awal harus mengubah status ke ASSIGNED")
            if current == TaskStatus.NEEDS_FOLLOWUP and target != TaskStatus.ASSIGNED:
                raise TaskRepositoryError(409, "Tindak lanjut harus ditugaskan kembali")
            if current not in {
                TaskStatus.OPEN,
                TaskStatus.ASSIGNED,
                TaskStatus.NEEDS_FOLLOWUP,
            }:
                raise TaskRepositoryError(
                    409, "Petugas tidak dapat diganti setelah pekerjaan dimulai"
                )

        history = None
        if target != current:
            self._validate_transition(
                current=current,
                target=target,
                actor=actor,
                assignee_id=task.assignee_id,
                effective_assignee=effective_assignee,
            )
            history = self._history(
                task, current, target, actor, datetime.now(UTC), payload.note
            )
            task.status = target.value
        elif assignee_changed and effective_assignee != task.assignee_id:
            if current != TaskStatus.ASSIGNED:
                raise TaskRepositoryError(409, "Perubahan petugas memerlukan transisi ASSIGNED")
            history = self._history(
                task,
                current,
                current,
                actor,
                datetime.now(UTC),
                payload.note or "Petugas diperbarui",
            )

        if target == TaskStatus.ASSIGNED and effective_assignee is None:
            raise TaskRepositoryError(409, "Status ASSIGNED memerlukan petugas lapangan")

        task.assignee_id = effective_assignee
        if note_changed:
            task.note = payload.note
        task.updated_at = datetime.now(UTC)
        if history is not None:
            self.session.add(history)

        if target in {TaskStatus.VERIFIED, TaskStatus.DISMISSED} and task.hotspot_id:
            hotspot = await self.session.get(Hotspot, task.hotspot_id)
            if hotspot is not None:
                hotspot.verification_status = target.value

        await self.session.flush()
        histories = await self._load_histories([task.id])
        return self._task_response(task, histories[task.id])

    async def create_report(
        self, task_id: UUID, payload: FieldReportCreate, actor: User
    ) -> FieldReport:
        if actor.role != UserRole.FIELD_OFFICER:
            raise TaskRepositoryError(403, "Hanya petugas lapangan yang dapat mengirim laporan")
        if not payload.is_simulation:
            raise TaskRepositoryError(422, "Akun demo hanya dapat mengirim laporan SIMULASI")
        observed_at = payload.observed_at.astimezone(UTC)
        if observed_at > datetime.now(UTC):
            raise TaskRepositoryError(422, "Waktu observasi tidak boleh berada di masa depan")

        task = await self._load_task(task_id, for_update=True)
        if observed_at < task.created_at:
            raise TaskRepositoryError(422, "Waktu observasi tidak boleh mendahului tugas")
        current = TaskStatus(task.status)
        self._validate_transition(
            current=current,
            target=TaskStatus.SUBMITTED,
            actor=actor,
            assignee_id=task.assignee_id,
            effective_assignee=task.assignee_id,
            via_report=True,
        )
        now = datetime.now(UTC)
        report = FieldReportModel(
            task_id=task.id,
            observed_at=observed_at,
            result=payload.result,
            note=payload.note,
            is_simulation=True,
            evidence_url=None if payload.evidence_url is None else str(payload.evidence_url),
            submitted_by_id=UUID(actor.id),
            created_at=now,
        )
        task.status = TaskStatus.SUBMITTED.value
        task.updated_at = now
        history = self._history(
            task,
            current,
            TaskStatus.SUBMITTED,
            actor,
            now,
            "Laporan SIMULASI dikirim",
        )
        self.session.add_all([report, history])
        await self.session.flush()
        return self._report_response(report)

    async def _load_task(
        self, task_id: UUID, *, for_update: bool = False
    ) -> InspectionTaskModel:
        query = select(InspectionTaskModel).where(InspectionTaskModel.id == task_id)
        if for_update:
            query = query.with_for_update()
        task = await self.session.scalar(query)
        if task is None:
            raise TaskRepositoryError(404, "Tugas tidak ditemukan")
        return task

    async def _field_officer(self, user_id: UUID | None) -> UserModel | None:
        if user_id is None:
            return None
        user = await self.session.get(UserModel, user_id)
        if user is None or not user.is_active or user.role != UserRole.FIELD_OFFICER.value:
            raise TaskRepositoryError(422, "Petugas lapangan tidak ditemukan atau tidak aktif")
        return user

    async def _load_histories(
        self, task_ids: list[UUID]
    ) -> defaultdict[UUID, list[TaskStatusChange]]:
        grouped: defaultdict[UUID, list[TaskStatusChange]] = defaultdict(list)
        if not task_ids:
            return grouped
        query = (
            select(TaskStatusHistory)
            .where(TaskStatusHistory.task_id.in_(task_ids))
            .order_by(TaskStatusHistory.changed_at, TaskStatusHistory.id)
        )
        for history in (await self.session.scalars(query)).all():
            grouped[history.task_id].append(self._history_response(history))
        return grouped

    async def _load_reports(self, task_id: UUID) -> list[FieldReport]:
        query = (
            select(FieldReportModel)
            .where(FieldReportModel.task_id == task_id)
            .order_by(FieldReportModel.created_at.desc(), FieldReportModel.id)
        )
        reports = (await self.session.scalars(query)).all()
        return [self._report_response(report) for report in reports]

    @staticmethod
    def _task_response(
        task: InspectionTaskModel, history: list[TaskStatusChange]
    ) -> InspectionTask:
        return InspectionTask(
            id=str(task.id),
            mode=task.mode,
            title=task.title,
            status=task.status,
            priority=task.priority,
            assessment_id=None if task.assessment_id is None else str(task.assessment_id),
            hotspot_id=None if task.hotspot_id is None else str(task.hotspot_id),
            area_id=task.area_id,
            assignee_id=None if task.assignee_id is None else str(task.assignee_id),
            created_by=str(task.created_by_id),
            created_at=task.created_at,
            updated_at=task.updated_at,
            note=task.note,
            history=history,
            is_simulation=task.is_simulation,
        )

    @staticmethod
    def _report_response(report: FieldReportModel) -> FieldReport:
        return FieldReport(
            id=str(report.id),
            task_id=str(report.task_id),
            observed_at=report.observed_at,
            result=report.result,
            note=report.note,
            evidence_url=report.evidence_url,
            submitted_by=str(report.submitted_by_id),
            submitted_at=report.created_at,
            is_simulation=report.is_simulation,
        )

    @staticmethod
    def _history(
        task: InspectionTaskModel,
        from_status: TaskStatus | None,
        to_status: TaskStatus,
        actor: User,
        changed_at: datetime,
        note: str | None,
    ) -> TaskStatusHistory:
        return TaskStatusHistory(
            task_id=task.id,
            from_status=None if from_status is None else from_status.value,
            to_status=to_status.value,
            actor_id=UUID(actor.id),
            actor_role=actor.role.value,
            changed_at=changed_at,
            note=note,
        )

    @staticmethod
    def _history_response(history: TaskStatusHistory) -> TaskStatusChange:
        return TaskStatusChange(
            from_status=history.from_status,
            to_status=history.to_status,
            actor_id=str(history.actor_id),
            actor_role=history.actor_role,
            changed_at=history.changed_at,
            note=history.note,
        )

    @staticmethod
    def _validate_transition(
        *,
        current: TaskStatus,
        target: TaskStatus,
        actor: User,
        assignee_id: UUID | None,
        effective_assignee: UUID | None,
        via_report: bool = False,
    ) -> None:
        try:
            validate_transition(
                current=current,
                target=target,
                actor_role=actor.role,
                actor_is_assignee=(
                    assignee_id is not None and str(assignee_id) == actor.id
                ),
                effective_assignee=effective_assignee is not None,
                via_report=via_report,
            )
        except WorkflowViolation as exc:
            raise TaskRepositoryError(exc.status_code, exc.detail) from exc
