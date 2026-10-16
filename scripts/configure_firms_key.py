"""Copy an existing local key into ignored .env without printing it.

Run from the backend repository root. Preserves existing environment entries
and writes with private permissions.
"""
import os
import re
import tempfile
from pathlib import Path

from app.core.config import get_settings


def main() -> None:
    if get_settings().firms_map_key:
        print("FIRMS key already configured; existing value retained.")
        return
    source = Path("api_key_firms.md")
    match = re.search(r"^\s*FIRMS_MAP_KEY\s*=\s*([A-Za-z0-9_-]+)\s*$",
                      source.read_text(), re.MULTILINE)
    if not match:
        raise SystemExit("Local key file has no valid FIRMS_MAP_KEY entry.")
    env_file = Path(".env")
    original = env_file.read_text() if env_file.exists() else Path(".env.example").read_text()
    key_line = f"FIRMS_MAP_KEY={match.group(1)}"
    old_line = next((line for line in original.splitlines()
                     if line.startswith("FIRMS_MAP_KEY=")), None)
    if old_line is not None:
        updated = "\n".join(
            key_line if line.startswith("FIRMS_MAP_KEY=") else line
            for line in original.splitlines()
        ) + "\n"
    else:
        updated = original.rstrip("\n") + "\n" + key_line + "\n"
    temporary_path = None
    try:
        with tempfile.NamedTemporaryFile(mode="w", dir=env_file.parent, delete=False) as temporary:
            temporary_path = Path(temporary.name)
            temporary.write(updated)
        os.replace(temporary_path, env_file)
    finally:
        if temporary_path is not None and temporary_path.exists():
            temporary_path.unlink()
    print("FIRMS key configured in ignored .env; secret not displayed.")


if __name__ == "__main__":
    main()
