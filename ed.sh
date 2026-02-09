#!/usr/bin/env bash

set -euo pipefail

BASE_DIR="$(cd "$(dirname "$0")" && pwd)"
CHAT_DIR="$BASE_DIR/chat"
SEARCH_DIR="$BASE_DIR/search"
SEARCH_SCRIPT="$SEARCH_DIR/search.py"
UI_SCRIPT="$BASE_DIR/ui/app.py"
SEARCH_PID_FILE="$BASE_DIR/search.pid"
UI_PID_FILE="$BASE_DIR/ui.pid"
LAUNCHER_PID_FILE="$BASE_DIR/ed.pid"
USER_SEARCH_ENV=""
UI_PID=""
SEARCH_PID=""
LLAMA_PID=""
CLEANED_UP=0
echo $$ > "$LAUNCHER_PID_FILE"

CMD="${1:-start}"

ED_HAS_RG=0
if command -v rg >/dev/null 2>&1; then
  ED_HAS_RG=1
fi

ED_LOG_MAX_BYTES="${ED_LOG_MAX_BYTES:-104857600}"
ED_LOG_ROTATE_COUNT="${ED_LOG_ROTATE_COUNT:-3}"

rotate_log_file() {
  local path="$1"
  local max_bytes="$ED_LOG_MAX_BYTES"
  local keep="$ED_LOG_ROTATE_COUNT"

  [ -f "$path" ] || return 0
  [[ "$max_bytes" =~ ^[0-9]+$ ]] || return 0
  [[ "$keep" =~ ^[0-9]+$ ]] || keep=0
  if [ "$max_bytes" -le 0 ]; then
    return 0
  fi

  local sz=""
  sz="$(stat -c%s "$path" 2>/dev/null || true)"
  if [ -z "${sz:-}" ]; then
    sz="$(wc -c < "$path" 2>/dev/null || echo 0)"
  fi
  [[ "$sz" =~ ^[0-9]+$ ]] || sz=0

  if [ "$sz" -lt "$max_bytes" ]; then
    return 0
  fi

  if [ "$keep" -le 0 ]; then
    rm -f "$path" || true
    return 0
  fi

  rm -f "$path.$keep" 2>/dev/null || true
  local i=$((keep - 1))
  while [ "$i" -ge 1 ]; do
    if [ -f "$path.$i" ]; then
      mv -f "$path.$i" "$path.$((i + 1))" 2>/dev/null || true
    fi
    i=$((i - 1))
  done
  mv -f "$path" "$path.1" 2>/dev/null || true
}

ed_filter_fixed() {
  local needle="$1"
  if [ "$ED_HAS_RG" = "1" ]; then
    rg -F -- "$needle"
  else
    grep -F -- "$needle"
  fi
}

ed_filter_regex() {
  local needle="$1"
  if [ "$ED_HAS_RG" = "1" ]; then
    rg -- "$needle"
  else
    grep -E -- "$needle"
  fi
}

ed_extract_regex() {
  local needle="$1"
  if [ "$ED_HAS_RG" = "1" ]; then
    rg -o -- "$needle"
  else
    grep -oE -- "$needle"
  fi
}

USER_SEARCH_ENV=""

ED_VENV_DIR="${ED_VENV_DIR:-$BASE_DIR/.venv}"
ED_USE_SYSTEM_PY="${ED_USE_SYSTEM_PY:-0}"
ED_PIP_UPGRADE="${ED_PIP_UPGRADE:-1}"
ED_FORCE_PIP="${ED_FORCE_PIP:-0}"

LLM_HOST="${LLM_HOST:-127.0.0.1}"
LLM_MODEL_DIR="${LLM_MODEL_DIR:-./models}"
LLM_MODEL_PATH="${LLM_MODEL_PATH:-}"
LLM_PORT="${LLM_PORT:-8080}"
LLAMA_ARGS="${LLAMA_ARGS:---threads 7 --ctx-size 8192 --batch-size 4 --mlock}"
API_HOST="${API_HOST:-127.0.0.1}"
API_MODEL="${API_MODEL:-duckduckgo-web}"
API_PORT="${API_PORT:-8000}"
WEB_POLL_TIMER_MS="${WEB_POLL_TIMER_MS:-8000}"
WEB_TELEMETRY_MS="${WEB_TELEMETRY_MS:-10000}"

if ! [[ "$LLM_PORT" =~ ^[0-9]+$ ]]; then
  echo "[!] LLM_PORT is invalid ($LLM_PORT). Using 8080." >&2
  LLM_PORT=8080
fi
if ! [[ "$API_PORT" =~ ^[0-9]+$ ]]; then
  echo "[!] API_PORT is invalid ($API_PORT). Using 8000." >&2
  API_PORT=8000
fi

MODEL_SERVER_URL="http://${LLM_HOST}:${LLM_PORT}"
SEARCH_API_URL="http://${API_HOST}:${API_PORT}"

if ! [[ "$WEB_POLL_TIMER_MS" =~ ^[0-9]+$ ]]; then
  echo "[!] WEB_POLL_TIMER_MS is invalid ($WEB_POLL_TIMER_MS). Using 8000ms." >&2
  WEB_POLL_TIMER_MS=8000
fi
if ! [[ "$WEB_TELEMETRY_MS" =~ ^[0-9]+$ ]]; then
  echo "[!] WEB_TELEMETRY_MS is invalid ($WEB_TELEMETRY_MS). Using 10000ms." >&2
  WEB_TELEMETRY_MS=10000
fi

export API_MODEL
export API_PORT
export API_HOST
export CHAT_DIR
export LLM_HOST
export LLM_PORT
export LLAMA_ARGS
export LLAMA_PID_FILE="$BASE_DIR/llama.pid"
export LLAMA_LOG_FILE="$BASE_DIR/llama.log"
export MODEL_SERVER_URL
export SEARCH_API_URL
export LLM_DESKTOP_DATA_DIR="$BASE_DIR/config"

MODEL_DIR_FOR_EXPORT="$LLM_MODEL_DIR"
if [[ "$MODEL_DIR_FOR_EXPORT" != /* ]]; then
  MODEL_DIR_FOR_EXPORT="$BASE_DIR/$MODEL_DIR_FOR_EXPORT"
fi
export LLM_MODEL_DIR="$MODEL_DIR_FOR_EXPORT"

sha256_file() {
  local path="$1"
  python3 - "$path" <<'PY'
import hashlib
import sys

p = sys.argv[1]
h = hashlib.sha256()
with open(p, "rb") as f:
    for chunk in iter(lambda: f.read(1024 * 1024), b""):
        h.update(chunk)
print(h.hexdigest())
PY
}

ensure_venv() {
  if [ "$ED_USE_SYSTEM_PY" = "1" ]; then
    SEARCH_PYTHON="python3"
    return 0
  fi

  local venv="$ED_VENV_DIR"
  local vpy="$venv/bin/python"
  local req_file="$SEARCH_DIR/requirements.txt"
  local marker="$venv/.llm_desktop_requirements.sha256"

  if [ ! -x "$vpy" ]; then
    echo "[*] Creating Python virtual environment at $venv"
    if ! command -v python3 >/dev/null 2>&1; then
      echo "[!] python3 not found. Install Python 3 and retry." >&2
      exit 1
    fi
    if ! python3 -m venv "$venv" >/dev/null 2>&1; then
      echo "[!] Failed to create venv at $venv." >&2
      echo "    On Debian/Ubuntu, install: sudo apt-get install -y python3-venv" >&2
      echo "    On Fedora, install: sudo dnf install -y python3-virtualenv python3-pip" >&2
      exit 1
    fi
  fi

  if [ ! -f "$req_file" ]; then
    echo "[!] Requirements file missing: $req_file" >&2
    exit 1
  fi

  local req_hash=""
  req_hash="$(sha256_file "$req_file")"
  local old_hash=""
  old_hash="$(cat "$marker" 2>/dev/null || true)"
  if [ "$ED_FORCE_PIP" = "1" ]; then
    old_hash=""
  fi

  if [ "$ED_PIP_UPGRADE" = "1" ] && [ "$old_hash" != "$req_hash" ]; then
    echo "[*] Updating pip tooling..."
    if ! "$vpy" -m pip --version >/dev/null 2>&1; then
      "$vpy" -m ensurepip --upgrade >/dev/null 2>&1 || true
    fi
    "$vpy" -m pip install -U pip setuptools wheel
  fi

  if [ "$old_hash" != "$req_hash" ]; then
    echo "[*] Installing Python requirements (this may take a minute)..."
    if ! "$vpy" -m pip --version >/dev/null 2>&1; then
      "$vpy" -m ensurepip --upgrade >/dev/null 2>&1 || true
    fi
    "$vpy" -m pip install -r "$req_file"
    echo "$req_hash" > "$marker"
  fi

  SEARCH_PYTHON="$vpy"
}

pid_is_running() {
  local pid="$1"
  [ -n "$pid" ] || return 1
  [[ "$pid" =~ ^[0-9]+$ ]] || return 1
  kill -0 "$pid" 2>/dev/null
}

pid_cmd_contains() {
  local pid="$1"
  local needle="$2"
  pid_is_running "$pid" || return 1
  ps -p "$pid" -o args= 2>/dev/null | ed_filter_fixed "$needle" >/dev/null 2>&1
}

kill_pid() {
  local pid="$1"
  local label="$2"
  if ! pid_is_running "$pid"; then
    return 0
  fi
  echo "[*] Stopping $label (PID $pid)..."
  kill "$pid" 2>/dev/null || true
  for _ in $(seq 1 20); do
    if ! pid_is_running "$pid"; then
      return 0
    fi
    sleep 0.1
  done
  echo "[!] $label did not stop gracefully; sending SIGKILL." >&2
  kill -9 "$pid" 2>/dev/null || true
}

stop_from_pidfiles() {
  local all="${1:-}"
  local ui_pid=""
  local search_pid=""
  local llama_pid=""

  if [ -f "$UI_PID_FILE" ]; then
    ui_pid="$(head -n 1 "$UI_PID_FILE" 2>/dev/null || true)"
    if pid_cmd_contains "$ui_pid" "$UI_SCRIPT"; then
      kill_pid "$ui_pid" "Flet UI"
    else
      echo "[!] $UI_PID_FILE exists but PID $ui_pid does not look like this UI; skipping." >&2
    fi
    rm -f "$UI_PID_FILE"
  fi

  if [ -f "$SEARCH_PID_FILE" ]; then
    search_pid="$(head -n 1 "$SEARCH_PID_FILE" 2>/dev/null || true)"
    if pid_cmd_contains "$search_pid" "$SEARCH_SCRIPT"; then
      kill_pid "$search_pid" "search server"
    else
      echo "[!] $SEARCH_PID_FILE exists but PID $search_pid does not look like this search server; skipping." >&2
    fi
    rm -f "$SEARCH_PID_FILE"
  fi

  if [ -f "$LLAMA_PID_FILE" ]; then
    llama_pid="$(head -n 1 "$LLAMA_PID_FILE" 2>/dev/null || true)"
    if pid_is_running "$llama_pid"; then
      kill_pid "$llama_pid" "llama-server"
    fi
    rm -f "$LLAMA_PID_FILE"
  fi

  if [ "$all" = "--all" ]; then
    pkill -f "$UI_SCRIPT" 2>/dev/null || true
    pkill -f "$SEARCH_SCRIPT" 2>/dev/null || true
    pkill -f "$CHAT_DIR/llama-server" 2>/dev/null || true
    pkill -f "llama-server -m $BASE_DIR/" 2>/dev/null || true

    if command -v ss >/dev/null 2>&1; then
      for p in 8000 8080 8001 8081; do
        pids="$(ss -lptn 2>/dev/null | ed_filter_regex ":${p}([^0-9]|$)" | ed_extract_regex "pid=[0-9]+" | cut -d= -f2 | sort -u || true)"
        if [ -n "${pids:-}" ]; then
          while read -r pid; do
            [ -n "$pid" ] || continue
            kill_pid "$pid" "port $p listener"
          done <<< "$pids"
        fi
      done
    fi
  fi
}

show_status() {
  echo "Processes:"
  if [ "$ED_HAS_RG" = "1" ]; then
    ps -ef | rg -F "$UI_SCRIPT" | rg -v rg || true
    ps -ef | rg -F "$SEARCH_SCRIPT" | rg -v rg || true
    ps -ef | rg -F "$CHAT_DIR/llama-server" | rg -v rg || true
  else
    ps -ef | grep -F -- "$UI_SCRIPT" | grep -v grep || true
    ps -ef | grep -F -- "$SEARCH_SCRIPT" | grep -v grep || true
    ps -ef | grep -F -- "$CHAT_DIR/llama-server" | grep -v grep || true
  fi
  echo
  echo "Ports:"
  (command -v ss >/dev/null 2>&1 && ss -lptn 2>/dev/null || true) | ed_filter_regex ":(${API_PORT}|${LLM_PORT})([^0-9]|$)" || true
}

if [ "$CMD" = "stop" ]; then
  stop_from_pidfiles "${2:-}"
  rm -f "$LAUNCHER_PID_FILE"
  exit 0
fi
if [ "$CMD" = "status" ]; then
  show_status
  exit 0
fi
if [ "$CMD" = "bootstrap" ]; then
  ensure_venv
  echo "[*] Bootstrap complete."
  echo "[*] Python: $SEARCH_PYTHON"
  "$SEARCH_PYTHON" - <<'PY' 2>/dev/null || true
import importlib.metadata as m
for name in ("flet", "fastapi", "uvicorn", "pydantic", "requests"):
    try:
        print(f"{name}=={m.version(name)}")
    except Exception:
        pass
PY
  rm -f "$LAUNCHER_PID_FILE"
  exit 0
fi

stop_services() {
  if [ "${CLEANED_UP:-0}" -eq 1 ]; then
    return 0
  fi
  CLEANED_UP=1
  echo
  echo 'Stopping services...'
  stop_from_pidfiles

  kill_pid "${UI_PID:-}" "Flet UI" || true
  kill_pid "${SEARCH_PID:-}" "search server" || true
  kill_pid "${LLAMA_PID:-}" "llama-server" || true

  rm -f "$UI_PID_FILE" "$SEARCH_PID_FILE" "$LLAMA_PID_FILE"
  rm -f "$LAUNCHER_PID_FILE"
}

trap 'stop_services; exit 0' INT TERM
trap 'stop_services' EXIT

port_is_free() {
  local host="$1"
  local port="$2"
  python3 - "$host" "$port" <<'PY'
import socket
import sys

host = sys.argv[1]
port = int(sys.argv[2])

s = socket.socket()
try:
    s.bind((host, port))
except OSError:
    sys.exit(1)
else:
    sys.exit(0)
finally:
    try:
        s.close()
    except Exception:
        pass
PY
}

choose_free_port() {
  local host="$1"
  local preferred="$2"
  local max_tries="${3:-20}"
  local p="$preferred"
  local i=0
  while [ "$i" -lt "$max_tries" ]; do
    if port_is_free "$host" "$p"; then
      echo "$p"
      return 0
    fi
    p=$((p + 1))
    i=$((i + 1))
  done
  return 1
}

if ! port_is_free "$API_HOST" "$API_PORT"; then
  new_api_port="$(choose_free_port "$API_HOST" "$API_PORT" 50 || true)"
  if [ -n "${new_api_port:-}" ]; then
    echo "[!] API_PORT $API_PORT is already in use on $API_HOST; using $new_api_port instead." >&2
    API_PORT="$new_api_port"
    export API_PORT
    SEARCH_API_URL="http://${API_HOST}:${API_PORT}"
    export SEARCH_API_URL
  else
    echo "[!] API_PORT $API_PORT is already in use and no free port was found nearby." >&2
    exit 1
  fi
fi

if ! port_is_free "$LLM_HOST" "$LLM_PORT"; then
  new_llm_port="$(choose_free_port "$LLM_HOST" "$LLM_PORT" 50 || true)"
  if [ -n "${new_llm_port:-}" ]; then
    echo "[!] LLM_PORT $LLM_PORT is already in use on $LLM_HOST; using $new_llm_port instead." >&2
    LLM_PORT="$new_llm_port"
    export LLM_PORT
    MODEL_SERVER_URL="http://${LLM_HOST}:${LLM_PORT}"
    export MODEL_SERVER_URL
  else
    echo "[!] LLM_PORT $LLM_PORT is already in use and no free port was found nearby." >&2
    exit 1
  fi
fi

echo "[*] Skipping llama-server startup (managed by the app / search server)."
LLAMA_PID=""

select_search_python() {
  ensure_venv
  echo "[*] Using Python: $SEARCH_PYTHON"
}

check_flet_version() {
  local required="0.24.1"
  local found=""
  found="$("$SEARCH_PYTHON" - <<'PY' 2>/dev/null || true
import importlib.metadata as m
try:
    print(m.version("flet"))
except Exception:
    print("")
PY
)"
  if [ -z "${found:-}" ]; then
    echo "[!] Could not detect Flet version in $SEARCH_PYTHON environment." >&2
    return 0
  fi
  if [ "$found" != "$required" ]; then
    echo "[!] Flet version is $found but $required is recommended (FilePicker compatibility)." >&2
    echo "    Fix: $SEARCH_PYTHON -m pip install -U \"flet==$required\"" >&2
    if [ "${STRICT_FLET_VERSION:-0}" = "1" ]; then
      echo "[!] STRICT_FLET_VERSION=1 is set; refusing to start." >&2
      exit 1
    fi
  fi
}

echo "[*] Starting search server..."
cd "$SEARCH_DIR"
select_search_python
check_flet_version
rotate_log_file "$BASE_DIR/search.log"
"$SEARCH_PYTHON" "$SEARCH_SCRIPT" > "$BASE_DIR/search.log" 2>&1 &
SEARCH_PID=$!
echo "$SEARCH_PID" > "$SEARCH_PID_FILE"
cd "$BASE_DIR"

sleep 0.2
if ! pid_is_running "$SEARCH_PID"; then
  echo "[!] Search server exited early. See $BASE_DIR/search.log" >&2
  tail -n 120 "$BASE_DIR/search.log" >&2 || true
  exit 1
fi

echo "[*] Starting Flet UI..."
rotate_log_file "$BASE_DIR/flet.log"
env FLET_LOG_LEVEL=debug "$SEARCH_PYTHON" "$UI_SCRIPT" > "$BASE_DIR/flet.log" 2>&1 &
UI_PID=$!
echo "$UI_PID" > "$UI_PID_FILE"

if [ -n "$LLAMA_PID" ]; then
  echo "llama-server PID: $LLAMA_PID"
else
  echo "llama-server: Not started (no model loaded)"
fi
echo "search server PID: $SEARCH_PID"
echo "Flet UI PID: $UI_PID"
echo "Logs: $BASE_DIR/llama.log, $BASE_DIR/search.log"
echo "Press Ctrl+C to stop everything."

while true; do sleep 1; done
