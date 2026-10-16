from pydantic import BaseModel, ConfigDict

from app.schemas.common import UserRole


class User(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    role: UserRole
    display_name: str

