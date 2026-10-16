import json
from pathlib import Path
from typing import Any

from app.ml.pipeline import MlDependencyError


class MlArtifactError(ValueError):
    pass


class MlArtifactStore:
    def __init__(self, directory: Path) -> None:
        self.directory = directory

    def list_manifests(self) -> list[dict[str, Any]]:
        if not self.directory.is_dir():
            return []
        manifests = []
        for path in sorted(self.directory.glob("*.metrics.json")):
            try:
                value = json.loads(path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError) as exc:
                raise MlArtifactError(f"Invalid ML metrics manifest: {path.name}") from exc
            required = {
                "model_version",
                "station_code",
                "artifact_file",
                "trained_at",
                "predictions",
            }
            if not isinstance(value, dict) or not required <= value.keys():
                raise MlArtifactError(f"Incomplete ML metrics manifest: {path.name}")
            artifact_file = value["artifact_file"]
            if not isinstance(artifact_file, str) or Path(artifact_file).name != artifact_file:
                raise MlArtifactError(f"Unsafe ML artifact path in {path.name}")
            if not (self.directory / artifact_file).is_file():
                raise MlArtifactError(f"Missing ML artifact for {path.name}")
            manifests.append(value)
        return manifests

    def find_manifest(self, station_code: str) -> dict[str, Any] | None:
        normalized = station_code.strip().upper()
        return next(
            (
                manifest
                for manifest in self.list_manifests()
                if manifest["station_code"] == normalized
            ),
            None,
        )

    def load_model(self, manifest: dict[str, Any]) -> Any:
        try:
            import joblib
        except ImportError as exc:
            raise MlDependencyError(
                "ML dependencies are unavailable; install the backend project dependencies"
            ) from exc
        return joblib.load(self.directory / manifest["artifact_file"])
