import json
import os
from pathlib import Path


DATA_DIR = Path(
    os.getenv("LLM_DESKTOP_DATA_DIR")
    or os.getenv("ERNIE_DATA_DIR")
    or (Path(__file__).resolve().parents[1] / "config")
)
SESSIONS_DIR = DATA_DIR / "sessions"
SESSION_INDEX_FILE = DATA_DIR / "session_index.json"


def ensure_data_dir() -> None:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    SESSIONS_DIR.mkdir(parents=True, exist_ok=True)


def load_session_index() -> list[dict]:
    if not SESSION_INDEX_FILE.exists():
        return []
    try:
        data = json.loads(SESSION_INDEX_FILE.read_text(encoding="utf-8"))
        return data if isinstance(data, list) else []
    except (json.JSONDecodeError, OSError):
        return []


def save_session_index(index: list[dict]) -> None:
    SESSION_INDEX_FILE.write_text(json.dumps(index, indent=2), encoding="utf-8")
