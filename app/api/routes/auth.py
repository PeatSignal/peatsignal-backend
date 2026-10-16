from typing import Annotated

from fastapi import APIRouter, Depends

from app.core.security import get_current_user
from app.schemas.user import User

router = APIRouter(prefix="/api/v1/auth", tags=["auth"])


@router.get("/me", response_model=User, summary="Resolve the current demo identity")
async def current_identity(user: Annotated[User, Depends(get_current_user)]) -> User:
    return user

