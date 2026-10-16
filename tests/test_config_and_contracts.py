from pathlib import Path

import pytest
from pydantic import ValidationError

from app.core.config import Settings
from app.schemas.common import MonitoringMode, QualityFlag
from app.schemas.groundwater import GroundwaterObservation


@pytest.mark.parametrize("source", ["environment", "dotenv"])
def test_settings_load_unprefixed_keys(
    source: str, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    values = {
        "APP_NAME": "Deployment Test API",
        "APP_VERSION": "0.2.0",
        "APP_ENV": "production",
        "DATABASE_URL": "postgresql+psycopg://user:password@localhost:5433/config_test",
        "CORS_ALLOWED_ORIGINS": "https://demo.example.com,http://localhost:3000",
        "COORDINATOR_TOKEN": "coordinator-token-with-at-least-32-characters",
        "FIELD_OFFICER_TOKEN": "field-officer-token-with-at-least-32-characters",
        "FIRMS_MAP_KEY": "test-firms-key",
        "ML_ARTIFACT_DIR": "deployment/ml",
    }
    for key in values:
        monkeypatch.delenv(key, raising=False)
    env_file = tmp_path / ".env"
    if source == "environment":
        for key, value in values.items():
            monkeypatch.setenv(key, value)
    else:
        env_file.write_text("\n".join(f"{key}={value}" for key, value in values.items()))

    settings = Settings(_env_file=env_file)

    assert settings.app_name == values["APP_NAME"]
    assert settings.app_version == values["APP_VERSION"]
    assert settings.app_env == "production"
    assert settings.database_url == values["DATABASE_URL"]
    assert settings.allowed_origins == ["https://demo.example.com", "http://localhost:3000"]
    assert settings.resolved_coordinator_token == values["COORDINATOR_TOKEN"]
    assert settings.resolved_field_officer_token == values["FIELD_OFFICER_TOKEN"]
    assert settings.firms_map_key == values["FIRMS_MAP_KEY"]
    assert settings.ml_artifact_dir == Path("deployment/ml")


def test_production_requires_distinct_role_tokens() -> None:
    with pytest.raises(ValidationError):
        Settings(app_env="production", coordinator_token=None, field_officer_token=None)

    with pytest.raises(ValidationError):
        Settings(
            app_env="production",
            coordinator_token="same-token",
            field_officer_token="same-token",
        )

    with pytest.raises(ValidationError):
        Settings(
            app_env="production",
            coordinator_token="short-coordinator",
            field_officer_token="short-officer",
        )

    settings = Settings(
        app_env="production",
        coordinator_token="coordinator-token-with-at-least-32-characters",
        field_officer_token="field-officer-token-with-at-least-32-characters",
    )
    assert settings.app_env == "production"


def test_groundwater_null_is_preserved_and_historical_mode_is_explicit() -> None:
    observation = GroundwaterObservation.model_validate(
        {
            "id": "obs-1",
            "station_id": "BRG6",
            "observed_date": "2019-01-02",
            "observed_at": "2019-01-02T00:00:00Z",
            "gwt_m": None,
            "quality_flag": "MISSING",
            "source": "mmc1.xlsx",
            "source_id": "source-1",
            "source_sha256": "a" * 64,
            "mode": "HISTORICAL_REPLAY",
        }
    )

    assert observation.gwt_m is None
    assert observation.quality_flag is QualityFlag.MISSING
    assert observation.mode is MonitoringMode.HISTORICAL_REPLAY

