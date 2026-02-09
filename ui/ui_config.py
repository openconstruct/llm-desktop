import os


APP_TITLE = "LLM-Desktop"


LLM_HOST = os.getenv("LLM_HOST", "127.0.0.1")
LLM_PORT = os.getenv("LLM_PORT", "8080")
API_HOST = os.getenv("API_HOST", "127.0.0.1")
API_PORT = os.getenv("API_PORT", "8000")

MODEL_SERVER_URL = os.getenv("MODEL_SERVER_URL", f"http://{LLM_HOST}:{LLM_PORT}").rstrip("/")
SEARCH_API_URL = os.getenv("SEARCH_API_URL", f"http://{API_HOST}:{API_PORT}").rstrip("/")


HEALTHCHECK_INTERVAL_MS = int(os.getenv("WEB_POLL_TIMER_MS", "8000"))
POWER_POLL_INTERVAL_MS = int(os.getenv("WEB_TELEMETRY_MS", "10000"))
STREAM_CONNECT_TIMEOUT_S = float(os.getenv("LLM_STREAM_CONNECT_TIMEOUT_S", "10"))
_stream_read_timeout_raw = os.getenv("LLM_STREAM_READ_TIMEOUT_S", "300").strip().lower()
STREAM_READ_TIMEOUT_S = None if _stream_read_timeout_raw in ("", "none", "null") else float(_stream_read_timeout_raw)


CHAT_MAX_WIDTH = 760
CHAT_MIN_WIDTH = 320
CHAT_SIDE_MARGIN = 220
SIDEBAR_WIDTH = 290


MAX_TEXT_FILE_EMBED_SIZE = 200 * 1024
CHARS_PER_TOKEN = 4

