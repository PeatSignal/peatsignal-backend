from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.security import get_current_user, require_roles
from app.db.session import get_async_db
from app.repositories.tasks import TaskRepository, TaskRepositoryError
from app.schemas.common import MonitoringMode, TaskStatus, UserRole
from app.schemas.report import FieldReport, FieldReportCreate
from app.schemas.task import (
    InspectionTask,
    InspectionTaskCreate,
    InspectionTaskDetail,
    InspectionTaskUpdate,
)
from app.schemas.user import User

router = APIRouter(prefix="/api/v1", tags=["tasks"])


def parse_statuses(raw_statuses: str | None) -> tuple[TaskStatus, ...]:
    if raw_statuses is None or not raw_statuses.strip():
        return ()
    try:
        return tuple(TaskStatus(value.strip()) for value in raw_statuses.split(","))
    except ValueError as exc:
        allowed = ", ".join(item.value for item in TaskStatus)
        raise HTTPException(422, f"Status tidak valid. Nilai yang didukung: {allowed}") from exc


def repository_error(exc: TaskRepositoryError) -> HTTPException:
    return HTTPException(status_code=exc.status_code, detail=exc.detail)


@router.get("/users", response_model=list[User])
async def list_users(
    session: Annotated[AsyncSession, Depends(get_async_db)],
    role: UserRole | None = None,
) -> list[User]:
    return await TaskRepository(session).list_users(role)


@router.get("/tasks", response_model=list[InspectionTask])
async def list_tasks(
    session: Annotated[AsyncSession, Depends(get_async_db)],
    mode: MonitoringMode | None = None,
    raw_statuses: Annotated[str | None, Query(alias="status")] = None,
    assignee_id: UUID | None = None,
) -> list[InspectionTask]:
    return await TaskRepository(session).list_tasks(
        mode=mode,
        statuses=parse_statuses(raw_statuses),
        assignee_id=assignee_id,
    )


@router.post(
    "/tasks", response_model=InspectionTask, status_code=status.HTTP_201_CREATED
)
async def create_task(
    payload: InspectionTaskCreate,
    user: Annotated[User, Depends(require_roles(UserRole.COORDINATOR))],
    session: Annotated[AsyncSession, Depends(get_async_db)],
) -> InspectionTask:
    try:
        result = await TaskRepository(session).create_task(payload, user)
        await session.commit()
        return result
    except TaskRepositoryError as exc:
        await session.rollback()
        raise repository_error(exc) from None


@router.get("/tasks/{task_id}", response_model=InspectionTaskDetail)
async def get_task(
    task_id: UUID,
    session: Annotated[AsyncSession, Depends(get_async_db)],
) -> InspectionTaskDetail:
    try:
        return await TaskRepository(session).get_task(task_id)
    except TaskRepositoryError as exc:
        raise repository_error(exc) from None


@router.patch("/tasks/{task_id}", response_model=InspectionTask)
async def update_task(
    task_id: UUID,
    payload: InspectionTaskUpdate,
    user: Annotated[User, Depends(get_current_user)],
    session: Annotated[AsyncSession, Depends(get_async_db)],
) -> InspectionTask:
    try:
        result = await TaskRepository(session).update_task(task_id, payload, user)
        await session.commit()
        return result
    except TaskRepositoryError as exc:
        await session.rollback()
        raise repository_error(exc) from None


@router.post(
    "/tasks/{task_id}/reports",
    response_model=FieldReport,
    status_code=status.HTTP_201_CREATED,
)
async def create_report(
    task_id: UUID,
    payload: FieldReportCreate,
    user: Annotated[User, Depends(require_roles(UserRole.FIELD_OFFICER))],
    session: Annotated[AsyncSession, Depends(get_async_db)],
) -> FieldReport:
    try:
        result = await TaskRepository(session).create_report(task_id, payload, user)
        await session.commit()
        return result
    except TaskRepositoryError as exc:
        await session.rollback()
        raise repository_error(exc) from None
