from functools import lru_cache
from pathlib import Path
from typing import Literal

from pydantic import model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

Environment = Literal["development", "test", "production"]


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        extra="ignore",
    )

    app_name: str = "PeatSignal API"
    app_version: str = "0.1.0"
    app_env: Environment = "development"
    database_url: str = (
        "postgresql+psycopg://gambutops:gambutops@127.0.0.1:5433/gambutops"
    )
    cors_allowed_origins: str = "http://localhost:3000"
    coordinator_token: str | None = None
    field_officer_token: str | None = None
    firms_map_key: str | None = None
    ml_artifact_dir: Path = Path("var/ml")

    @model_validator(mode="after")
    def require_production_secrets(self) -> "Settings":
        if self.app_env == "production":
            if not self.coordinator_token or not self.field_officer_token:
                raise ValueError("Both demo role tokens must be configured in production")
            if self.coordinator_token == self.field_officer_token:
                raise ValueError("Demo role tokens must be distinct")
            if len(self.coordinator_token) < 32 or len(self.field_officer_token) < 32:
                raise ValueError("Production demo role tokens must contain at least 32 characters")
        return self

    @property
    def allowed_origins(self) -> list[str]:
        return [origin.strip() for origin in self.cors_allowed_origins.split(",") if origin.strip()]

    @property
    def async_database_url(self) -> str:
        if self.database_url.startswith("postgresql+psycopg://"):
            return self.database_url.replace(
                "postgresql+psycopg://", "postgresql+psycopg_async://", 1
            )
        return self.database_url

    @property
    def resolved_coordinator_token(self) -> str:
        return self.coordinator_token or "demo-coordinator-token"

    @property
    def resolved_field_officer_token(self) -> str:
        return self.field_officer_token or "demo-field-officer-token"


@lru_cache
def get_settings() -> Settings:
    return Settings()

