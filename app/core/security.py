import secrets
from collections.abc import Callable
from typing import Annotated

from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from app.core.config import Settings, get_settings
from app.schemas.common import UserRole
from app.schemas.user import User

bearer_scheme = HTTPBearer(auto_error=False)
DEMO_COORDINATOR_ID = "00000000-0000-4000-8000-000000000001"
DEMO_FIELD_OFFICER_ID = "00000000-0000-4000-8000-000000000002"


async def get_current_user(
    credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(bearer_scheme)],
) -> User:
    settings: Settings = get_settings()
    if credentials is None or credentials.scheme.lower() != "bearer":
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Bearer token is required",
            headers={"WWW-Authenticate": "Bearer"},
        )

    token = credentials.credentials
    if secrets.compare_digest(token, settings.resolved_coordinator_token):
        return User(
            id=DEMO_COORDINATOR_ID,
            role=UserRole.COORDINATOR,
            display_name="Koordinator Demo",
        )
    if secrets.compare_digest(token, settings.resolved_field_officer_token):
        return User(
            id=DEMO_FIELD_OFFICER_ID,
            role=UserRole.FIELD_OFFICER,
            display_name="Petugas Lapangan Demo",
        )
    raise HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Invalid bearer token",
        headers={"WWW-Authenticate": "Bearer"},
    )


def require_roles(*roles: UserRole) -> Callable[[User], User]:
    allowed = set(roles)

    async def dependency(user: Annotated[User, Depends(get_current_user)]) -> User:
        if user.role not in allowed:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="This role is not allowed to perform the operation",
            )
        return user

    return dependency

