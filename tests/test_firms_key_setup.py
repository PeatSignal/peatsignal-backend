import importlib.util
from pathlib import Path
from types import SimpleNamespace

spec = importlib.util.spec_from_file_location(
    "configure_firms_key", Path(__file__).resolve().parents[1] / "scripts/configure_firms_key.py"
)
configure_firms_key = importlib.util.module_from_spec(spec)
spec.loader.exec_module(configure_firms_key)


def test_local_key_setup_preserves_environment_and_private_permissions(tmp_path, monkeypatch):
    backend = tmp_path / "backend"
    backend.mkdir()
    key_file = backend / "api_key_firms.md"
    key_file.write_text("FIRMS_MAP_KEY=test-secret-value\n", encoding="utf-8")
    env = backend / ".env"
    env.write_text("DATABASE_URL=unchanged\nFIRMS_MAP_KEY=\n", encoding="utf-8")
    monkeypatch.chdir(backend)
    monkeypatch.setattr(
        configure_firms_key, "get_settings", lambda: SimpleNamespace(firms_map_key=None)
    )
    configure_firms_key.main()
    assert env.read_text() == (
        "DATABASE_URL=unchanged\nFIRMS_MAP_KEY=test-secret-value\n"
    )
    assert env.stat().st_mode & 0o077 == 0
    monkeypatch.setattr(
        configure_firms_key, "get_settings", lambda: SimpleNamespace(firms_map_key="set")
    )
    key_file.unlink()
    configure_firms_key.main()
    assert "DATABASE_URL=unchanged" in env.read_text()
