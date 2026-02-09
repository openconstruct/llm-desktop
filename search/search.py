#!/usr/bin/env python3
"""
FastAPI Search Server with DuckDuckGo integration
For IRIS/LLM-Desktop App
"""

from __future__ import annotations

import json
import os
import re
import shlex
import shutil
import signal
import struct
import subprocess
import sys
import tempfile
import threading
import time
from datetime import datetime
from pathlib import Path
from typing import Optional

import uvicorn
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware

import schemas as sch

DDGS = None
SEARCH_BACKEND = None
SEARCH_ERROR = None
try:
    from ddgs import DDGS as _DDGS
    DDGS = _DDGS
    SEARCH_BACKEND = "ddgs"
except ImportError:
    SEARCH_ERROR = "DuckDuckGo backend not installed; run `pip install ddgs`"

try:
    import psutil
except ImportError:
    psutil = None

app = FastAPI(title="IRIS Search API", version="1.0.0")


_search_cache_lock = threading.Lock()
_search_cache: dict[tuple[str, int], dict] = {}
_search_cache_ttl_s = float(os.getenv("LLM_SEARCH_CACHE_TTL_S", "60"))
_search_backoff_until = 0.0
_search_backoff_s = 0.0


_enable_cors = os.getenv("LLM_DESKTOP_ENABLE_CORS", "0").strip().lower() in ("1", "true", "yes", "on")
if _enable_cors:
    _cors_origin_regex = os.getenv(
        "LLM_DESKTOP_CORS_ORIGIN_REGEX",
        r"^https?://(localhost|127\.0\.0\.1)(:\d+)?$",
    )
    app.add_middleware(
        CORSMiddleware,
        allow_origin_regex=_cors_origin_regex,
        allow_credentials=False,
        allow_methods=["*"],
        allow_headers=["*"],
    )

if DDGS is None:
    print("⚠️  WARNING: DuckDuckGo search backend not installed; web search is disabled.")
    print("   Install with: pip install ddgs")

API_MODEL = os.getenv("API_MODEL", "duckduckgo-web")
API_HOST = os.getenv("API_HOST", "127.0.0.1")
POWER_IDLE_WATTS = float(os.getenv("POWER_IDLE_WATTS", "15"))
POWER_MAX_WATTS = float(os.getenv("POWER_MAX_WATTS", "65"))


TOOL_FILES_DIR = os.getenv("LLM_TOOL_FILES_DIR", "").strip()
MAX_FILE_TOOL_BYTES = int(os.getenv("LLM_TOOL_FILES_MAX_BYTES", "200000"))


CHAT_DIR = os.getenv("CHAT_DIR", "")
LLM_MODEL_DIR = os.getenv("LLM_MODEL_DIR", "")
LLM_HOST = os.getenv("LLM_HOST", "127.0.0.1")
LLM_PORT = os.getenv("LLM_PORT", "8080")
LLAMA_ARGS = os.getenv("LLAMA_ARGS", "--threads 7 --ctx-size 8192 --batch-size 4 --mlock")
LLAMA_PID_FILE = os.getenv("LLAMA_PID_FILE", "/tmp/ernie_llama.pid")
LLAMA_LOG_FILE = os.getenv("LLAMA_LOG_FILE", "")


try:
    _base = Path(__file__).resolve().parents[1]
except Exception:
    _base = None
PROJECT_ROOT = _base if _base is not None else Path.cwd()
try:
    PROJECT_ROOT = PROJECT_ROOT.resolve()
except Exception:
    PROJECT_ROOT = PROJECT_ROOT.absolute()
if not CHAT_DIR and _base is not None:
    cand = _base / "chat"
    if cand.exists():
        CHAT_DIR = str(cand)
if not LLM_MODEL_DIR and _base is not None:
    cand = _base / "models"
    if cand.exists():
        LLM_MODEL_DIR = str(cand)

DATA_DIR = Path(
    os.getenv("LLM_DESKTOP_DATA_DIR")
    or os.getenv("ERNIE_DATA_DIR")
    or ((_base / "config") if _base is not None else (Path.cwd() / "config"))
)
SETTINGS_FILE = DATA_DIR / "settings.json"
_settings_lock = threading.Lock()

def _resolve_project_path(raw: str) -> Optional[Path]:
    s = (raw or "").strip()
    if not s:
        return None
    p = Path(s).expanduser()
    if not p.is_absolute():
        p = PROJECT_ROOT / p
    try:
        return p.resolve()
    except OSError:
        return p.absolute()

def _to_project_relative(p: Path) -> str:
    try:
        rel = p.resolve().relative_to(PROJECT_ROOT)
    except Exception:
        try:
            rel = p.absolute().relative_to(PROJECT_ROOT)
        except Exception:
            return str(p)
    rel_s = str(rel)
    return rel_s if rel_s else "."

def _display_path(raw: str) -> str:
    p = _resolve_project_path(raw)
    if p is None:
        return (raw or "").strip()
    try:
        p.relative_to(PROJECT_ROOT)
    except Exception:
        return str(p)
    return _to_project_relative(p)

def _settings_defaults() -> dict:
    return {
        "model_dir": (LLM_MODEL_DIR or "").strip(),
        "current_model_path": None,
        "autostart_model": True,
        "tool_files_dir": (TOOL_FILES_DIR or "").strip(),
        "tool_files_max_bytes": int(MAX_FILE_TOOL_BYTES),
        "llama_args": (LLAMA_ARGS or "").strip(),
        "power_idle_watts": float(POWER_IDLE_WATTS),
        "power_max_watts": float(POWER_MAX_WATTS),
    }

def _atomic_write_json(path: Path, obj: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_name = tempfile.mkstemp(prefix=".llm-desktop-tmp-", dir=str(path.parent))
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            fh.write(json.dumps(obj, indent=2))
        os.replace(tmp_name, str(path))
    finally:
        try:
            if os.path.exists(tmp_name):
                os.remove(tmp_name)
        except Exception:
            pass

def _settings_load() -> dict:
    defaults = _settings_defaults()
    if not SETTINGS_FILE.exists():
        return defaults
    try:
        raw = json.loads(SETTINGS_FILE.read_text(encoding="utf-8"))
        if not isinstance(raw, dict):
            return defaults
    except Exception:
        return defaults
    out = dict(defaults)
    out.update(raw)

    for k in (
        "web_read_max_bytes",
        "web_read_max_chars",
        "web_read_allow_private",
        "web_read_strict_ssrf",
    ):
        out.pop(k, None)
    return out

def _settings_save(settings: dict) -> None:

    out = dict(settings or {})
    for k in ("model_dir", "tool_files_dir", "current_model_path"):
        raw = (out.get(k) or "").strip()
        if not raw:
            continue
        p = _resolve_project_path(raw)
        if p is None:
            continue
        try:
            p.relative_to(PROJECT_ROOT)
        except Exception:

            out[k] = str(p)
            continue
        out[k] = _to_project_relative(p)
    _atomic_write_json(SETTINGS_FILE, out)

def _settings_apply(settings: dict) -> None:
    global LLM_MODEL_DIR, TOOL_FILES_DIR, LLAMA_ARGS
    global MAX_FILE_TOOL_BYTES
    global POWER_IDLE_WATTS, POWER_MAX_WATTS

    model_dir = (settings.get("model_dir") or "").strip()
    if model_dir:
        resolved = _resolve_project_path(model_dir)
        if resolved is not None:
            LLM_MODEL_DIR = str(resolved)
            os.environ["LLM_MODEL_DIR"] = str(resolved)

    files_dir = (settings.get("tool_files_dir") or "").strip()
    if files_dir:
        resolved = _resolve_project_path(files_dir)
        if resolved is not None:
            TOOL_FILES_DIR = str(resolved)
            os.environ["LLM_TOOL_FILES_DIR"] = str(resolved)

    try:
        MAX_FILE_TOOL_BYTES = int(settings.get("tool_files_max_bytes", MAX_FILE_TOOL_BYTES))
        if MAX_FILE_TOOL_BYTES < 10_000:
            MAX_FILE_TOOL_BYTES = 10_000
        if MAX_FILE_TOOL_BYTES > 10_000_000:
            MAX_FILE_TOOL_BYTES = 10_000_000
    except Exception:
        pass

    llama_args = (settings.get("llama_args") or "").strip()
    if llama_args:
        LLAMA_ARGS = llama_args
        os.environ["LLAMA_ARGS"] = llama_args

    try:
        POWER_IDLE_WATTS = float(settings.get("power_idle_watts", POWER_IDLE_WATTS))
    except Exception:
        pass
    try:
        POWER_MAX_WATTS = float(settings.get("power_max_watts", POWER_MAX_WATTS))
    except Exception:
        pass

def _settings_get() -> dict:
    with _settings_lock:
        s = _settings_load()
        _settings_apply(s)
        try:
            _settings_save(s)
        except Exception:
            pass
        return s

def _settings_set(key: str, value):
    with _settings_lock:
        s = _settings_load()
        s[key] = value
        _settings_apply(s)
        _settings_save(s)
        return s

def _get_port_value():
    raw = os.getenv("API_PORT", "8000")
    try:
        return int(raw)
    except ValueError:
        print(f"⚠️  WARNING: Invalid API_PORT '{raw}', falling back to 8000.")
        return 8000

API_PORT = _get_port_value()


try:
    _settings_get()
except Exception:
    pass

def _pid_is_running(pid: int) -> bool:
    try:
        os.kill(int(pid), 0)
        return True
    except Exception:
        return False

def _llama_pid_from_file() -> Optional[int]:
    try:
        if not os.path.exists(LLAMA_PID_FILE):
            return None
        with open(LLAMA_PID_FILE, "r", encoding="utf-8") as f:
            raw = (f.readline() or "").strip()
        return int(raw) if raw else None
    except Exception:
        return None

@app.on_event("startup")
async def _autostart_llama_server():
    """
    Best-effort autostart of the last-selected model.
    This keeps the "no env file" workflow smooth: users pick a model once and it comes back on next launch.
    """
    def worker():
        try:
            s = _settings_get()
        except Exception:
            s = {}
        if not s.get("autostart_model", True):
            return
        model_path = (s.get("current_model_path") or "").strip()

        if (not model_path) or (not os.path.exists(model_path)):
            try:
                pid_model = (_get_current_model() or "").strip()
            except Exception:
                pid_model = ""
            if pid_model and os.path.exists(pid_model):
                model_path = pid_model
                try:
                    _settings_set("current_model_path", model_path)
                except Exception:
                    pass
        if (not model_path) or (not os.path.exists(model_path)):
            return

        pid = _llama_pid_from_file()
        if pid and _pid_is_running(pid):
            return

        try:

            _stop_llama_server()
        except Exception:
            pass
        try:
            _start_llama_server(model_path)
        except Exception as exc:
            print(f"Autostart failed: {exc}")

    threading.Thread(target=worker, daemon=True).start()

def _format_size(bytes_size):
    """Format bytes to human readable size"""
    for unit in ['B', 'KB', 'MB', 'GB', 'TB']:
        if bytes_size < 1024.0:
            return f"{bytes_size:.2f} {unit}"
        bytes_size /= 1024.0
    return f"{bytes_size:.2f} PB"

def _get_current_model():
    """Get the currently loaded model from PID file"""
    if not os.path.exists(LLAMA_PID_FILE):

        try:
            s = _settings_get()
            raw = (s.get("current_model_path") or "").strip()
            if raw:
                p = _resolve_project_path(raw)
                if p is not None and p.exists():
                    return str(p)
        except Exception:
            pass
        return None
    try:
        with open(LLAMA_PID_FILE, 'r') as f:
            data = f.read().strip().split('\n')
            if len(data) >= 2:
                return data[1]
    except Exception:
        pass

    try:
        s = _settings_get()
        raw = (s.get("current_model_path") or "").strip()
        if raw:
            p = _resolve_project_path(raw)
            if p is not None and p.exists():
                return str(p)
    except Exception:
        pass
    return None

def _llama_parse_ctx_size(args_str: str) -> Optional[int]:
    if not args_str:
        return None
    try:
        toks = shlex.split(args_str)
    except Exception:
        toks = str(args_str).split()
    for i, t in enumerate(toks):
        if t.startswith("--ctx-size="):
            try:
                return int(t.split("=", 1)[1])
            except Exception:
                return None
        if t in ("--ctx-size", "-c") and i + 1 < len(toks):
            try:
                return int(toks[i + 1])
            except Exception:
                return None
    return None

def _llama_set_ctx_size(args_str: str, ctx_size: int) -> str:
    ctx_size = int(ctx_size)
    if ctx_size < 256:
        ctx_size = 256
    if ctx_size > 1_048_576:
        ctx_size = 1_048_576
    try:
        toks = shlex.split(args_str or "")
    except Exception:
        toks = (args_str or "").split()

    out = []
    i = 0
    replaced = False
    while i < len(toks):
        t = toks[i]
        if t.startswith("--ctx-size="):
            out.append(f"--ctx-size={ctx_size}")
            replaced = True
            i += 1
            continue
        if t in ("--ctx-size", "-c"):
            out.append(t)
            out.append(str(ctx_size))
            replaced = True
            i += 2
            continue
        out.append(t)
        i += 1

    if not replaced:
        out.extend(["--ctx-size", str(ctx_size)])

    try:
        return shlex.join(out)
    except Exception:
        return " ".join(out)

def _shell_join(argv: list[str]) -> str:
    try:
        return shlex.join(argv)
    except Exception:
        return " ".join(shlex.quote(str(a)) for a in (argv or []))

def _read_llama_pidfile() -> tuple[Optional[int], Optional[str]]:
    if not os.path.exists(LLAMA_PID_FILE):
        return None, None
    try:
        with open(LLAMA_PID_FILE, "r", encoding="utf-8") as f:
            lines = [ln.strip() for ln in f.read().splitlines() if ln.strip()]
        if not lines:
            return None, None
        pid = int(lines[0])
        model = lines[1] if len(lines) >= 2 else None
        return pid, model
    except Exception:
        return None, None

def _pid_is_running(pid: int) -> bool:
    try:
        os.kill(int(pid), 0)
        return True
    except Exception:
        return False

def _pid_cmdline(pid: int) -> Optional[list[str]]:
    if pid is None:
        return None
    if psutil is not None:
        try:
            return list(psutil.Process(int(pid)).cmdline())
        except Exception:
            pass
    proc_path = f"/proc/{int(pid)}/cmdline"
    try:
        with open(proc_path, "rb") as f:
            raw = f.read()
        parts = [p.decode("utf-8", errors="replace") for p in raw.split(b"\x00") if p]
        return parts or None
    except Exception:
        return None

def _extract_llama_extra_args(cmdline: Optional[list[str]]) -> Optional[list[str]]:
    if not cmdline:
        return None

    try:
        if "--port" in cmdline:
            i = cmdline.index("--port")
            if i + 2 <= len(cmdline):
                return cmdline[i + 2 :]
    except Exception:
        pass
    return None

_GGUF_MAGIC = b"GGUF"
_GGUF_MAX_STRLEN = 4 * 1024 * 1024
_GGUF_MAX_STRING_ARRAY = 500_000

def _gguf_u32(fh) -> int:
    raw = fh.read(4)
    if len(raw) != 4:
        raise OSError("Unexpected EOF")
    return struct.unpack("<I", raw)[0]

def _gguf_u64(fh) -> int:
    raw = fh.read(8)
    if len(raw) != 8:
        raise OSError("Unexpected EOF")
    return struct.unpack("<Q", raw)[0]

def _gguf_skip_bytes(fh, n: int) -> None:
    if n <= 0:
        return
    fh.seek(n, 1)

def _gguf_read_str(fh, *, decode: bool = True):
    n = _gguf_u64(fh)
    if n > _GGUF_MAX_STRLEN:
        raise OSError(f"GGUF string too large: {n} bytes")
    if not decode:
        _gguf_skip_bytes(fh, n)
        return None
    raw = fh.read(n)
    if len(raw) != n:
        raise OSError("Unexpected EOF")
    return raw.decode("utf-8", errors="replace")

def _gguf_skip_value(fh, vtype: int) -> None:


    if vtype in (0, 1, 7):
        _gguf_skip_bytes(fh, 1)
        return
    if vtype in (2, 3):
        _gguf_skip_bytes(fh, 2)
        return
    if vtype in (4, 5, 6):
        _gguf_skip_bytes(fh, 4)
        return
    if vtype in (10, 11, 12):
        _gguf_skip_bytes(fh, 8)
        return
    if vtype == 8:
        _gguf_read_str(fh, decode=False)
        return
    if vtype == 9:
        etype = _gguf_u32(fh)
        n = _gguf_u64(fh)
        if etype == 8:
            if n > _GGUF_MAX_STRING_ARRAY:
                raise OSError(f"GGUF string array too large: {n} entries")
            for _ in range(n):
                _gguf_read_str(fh, decode=False)
            return

        elem_size = {0: 1, 1: 1, 2: 2, 3: 2, 4: 4, 5: 4, 6: 4, 7: 1, 10: 8, 11: 8, 12: 8}.get(etype)
        if elem_size is not None:
            _gguf_skip_bytes(fh, int(n) * elem_size)
            return

        for _ in range(n):
            _gguf_skip_value(fh, etype)
        return
    raise OSError(f"Unknown GGUF value type: {vtype}")

_LLAMA_FTYPE_LABELS = {
    0: "F32",
    1: "F16",
    2: "Q4_0",
    3: "Q4_1",
    4: "Q4_1 (some F16)",
    5: "Q8_0",
    6: "Q5_0",
    7: "Q5_1",
    8: "Q2_K",
    9: "Q3_K_S",
    12: "Q3_K_M",
    13: "Q3_K_L",
    14: "Q4_K_S",
    15: "Q4_K_M",
    16: "Q5_K_S",
    17: "Q5_K_M",
    18: "Q6_K",
    32: "BF16",
}

def _llama_ftype_to_quant(ftype: Optional[int]) -> Optional[str]:
    if ftype is None:
        return None
    return _LLAMA_FTYPE_LABELS.get(int(ftype)) or f"ftype:{int(ftype)}"

def _read_gguf_metadata(path: str, *, need_file_type: bool = False) -> dict:
    """
    Best-effort GGUF metadata extraction.
    If need_file_type is True, we scan the whole KV table (skipping arrays) to find general.file_type.
    """
    meta = {"gguf_model_name": None, "gguf_architecture": None, "gguf_file_type": None}
    try:
        with open(path, "rb") as fh:
            if fh.read(4) != _GGUF_MAGIC:
                return meta
            _ = _gguf_u32(fh)
            _ = _gguf_u64(fh)
            kv_count = _gguf_u64(fh)

            for _i in range(int(kv_count)):
                key = _gguf_read_str(fh, decode=True)
                vtype = _gguf_u32(fh)
                if key == "general.name" and vtype == 8:
                    meta["gguf_model_name"] = _gguf_read_str(fh, decode=True)
                elif key == "general.architecture" and vtype == 8:
                    meta["gguf_architecture"] = _gguf_read_str(fh, decode=True)
                elif key == "general.file_type" and vtype == 4:
                    meta["gguf_file_type"] = _gguf_u32(fh)
                else:
                    _gguf_skip_value(fh, vtype)

                if not need_file_type and meta["gguf_model_name"] and meta["gguf_architecture"]:

                    break
                if need_file_type and meta["gguf_model_name"] and meta["gguf_architecture"] and meta["gguf_file_type"] is not None:
                    break
    except Exception:
        return meta
    return meta

def _list_gguf_models():
    """List all .gguf models in the model directory"""

    model_dir = LLM_MODEL_DIR if LLM_MODEL_DIR else CHAT_DIR

    if not model_dir or not os.path.isdir(model_dir):
        return []

    models = []
    current_model = _get_current_model()

    try:
        for file in os.listdir(model_dir):
            if file.endswith('.gguf'):
                full_path = os.path.join(model_dir, file)
                try:
                    size = os.path.getsize(full_path)
                    is_current = (full_path == current_model or file == current_model)
                    meta = _read_gguf_metadata(full_path, need_file_type=is_current)
                    ftype = meta.get("gguf_file_type")
                    models.append(sch.ModelInfo(
                        name=file,
                        path=full_path,
                        size_bytes=size,
                        size_human=_format_size(size),
                        is_current=is_current,
                        gguf_model_name=meta.get("gguf_model_name"),
                        gguf_architecture=meta.get("gguf_architecture"),
                        gguf_file_type=ftype,
                        quantization=_llama_ftype_to_quant(ftype) if is_current else None,
                    ))
                except OSError:
                    continue
    except OSError:
        pass

    return sorted(models, key=lambda m: m.name)

def _files_root() -> Path:
    global TOOL_FILES_DIR
    if not TOOL_FILES_DIR:
        raise HTTPException(status_code=503, detail="File tool directory not configured. Set LLM_TOOL_FILES_DIR or configure it in the UI.")
    root = Path(TOOL_FILES_DIR).expanduser()
    try:
        root_resolved = root.resolve()
    except OSError:
        root_resolved = root.absolute()
    if not root_resolved.exists():
        raise HTTPException(status_code=503, detail=f"File tool directory does not exist: {root_resolved}")
    if not root_resolved.is_dir():
        raise HTTPException(status_code=503, detail=f"File tool path is not a directory: {root_resolved}")
    return root_resolved

def _safe_join(root: Path, rel_path: str) -> Path:
    rel = (rel_path or "").strip()
    if rel in ("", "."):
        return root
    p = Path(rel)
    if p.is_absolute():
        raise HTTPException(status_code=400, detail="Path must be relative to the file tool root.")
    candidate = (root / p)
    try:
        resolved = candidate.resolve()
    except OSError:
        resolved = candidate.absolute()
    if resolved != root and root not in resolved.parents:
        raise HTTPException(status_code=403, detail="Path escapes the file tool root.")
    return resolved

def _is_writable_dir(path: Path) -> bool:
    try:
        return os.access(str(path), os.W_OK)
    except Exception:
        return False

def _atomic_write_text(path: Path, content: str) -> int:
    path.parent.mkdir(parents=True, exist_ok=True)

    fd, tmp_name = tempfile.mkstemp(prefix=".llm-desktop-tmp-", dir=str(path.parent))
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            fh.write(content)
        os.replace(tmp_name, str(path))
    finally:
        try:
            if os.path.exists(tmp_name):
                os.remove(tmp_name)
        except Exception:
            pass
    return len(content.encode("utf-8", errors="replace"))

def _stop_llama_server():
    """Stop the current llama-server process"""
    if not os.path.exists(LLAMA_PID_FILE):
        return True

    try:
        with open(LLAMA_PID_FILE, 'r') as f:
            pid = int(f.readline().strip())


        try:
            os.kill(pid, signal.SIGTERM)
        except OSError:

            pass


        for i in range(10):
            try:
                os.kill(pid, 0)
                time.sleep(0.5)
            except OSError:

                break


        try:
            os.kill(pid, signal.SIGKILL)
            time.sleep(0.5)
        except OSError:
            pass

        os.remove(LLAMA_PID_FILE)
        return True
    except Exception as e:
        print(f"Error stopping llama-server: {e}")
        return False

def _start_llama_server(model_path):
    """Start llama-server with the specified model"""
    if not CHAT_DIR:
        raise Exception("CHAT_DIR not configured")

    llama_binary = os.path.join(CHAT_DIR, "llama-server")
    if not os.path.exists(llama_binary):
        raise Exception(f"llama-server binary not found at {llama_binary}")


    cmd = [
        llama_binary,
        "-m", model_path,
        "--host", LLM_HOST,
        "--port", str(LLM_PORT)
    ]


    if LLAMA_ARGS:


        args_str = LLAMA_ARGS.strip()
        if (args_str.startswith('"') and args_str.endswith('"')) or (args_str.startswith("'") and args_str.endswith("'")):
            args_str = args_str[1:-1]
        cmd.extend(shlex.split(args_str))


    log_file = LLAMA_LOG_FILE if LLAMA_LOG_FILE else "/tmp/llama.log"
    with open(log_file, 'a') as log:
        log.write(f"\n=== Starting llama-server at {datetime.now().isoformat()} ===\n")
        log.write(f"Model: {model_path}\n")
        log.write(f"Command: {' '.join(cmd)}\n\n")
        log.flush()

        process = subprocess.Popen(
            cmd,
            cwd=CHAT_DIR,
            stdout=log,
            stderr=subprocess.STDOUT,
            start_new_session=True
        )


    time.sleep(0.5)
    rc = process.poll()
    if rc is not None:
        raise Exception(f"llama-server exited immediately (code {rc}). Check {log_file} for details.")
    try:
        os.kill(process.pid, 0)
    except OSError:
        raise Exception(f"llama-server process failed to start. Check {log_file} for details.")


    with open(LLAMA_PID_FILE, 'w') as f:
        f.write(f"{process.pid}\n{model_path}")

    print(f"Started llama-server with PID {process.pid}")
    return process.pid

@app.get("/")
async def root():
    return {
        "service": "IRIS Search API",
        "version": "1.0.0",
        "model": API_MODEL,
        "endpoints": {
            "search": "/search/web (POST)",
            "health": "/health (GET)",
        "telemetry": "/telemetry/power (GET)",
        "models": "/models (GET)",
        "switch_model": "/models/switch (POST)",
        "model_dir": "/models/dir (POST)"
    }
    }

@app.get("/health")
async def health_check():
    return {
        "status": "healthy",
        "search_enabled": DDGS is not None,
        "search_backend": SEARCH_BACKEND,
        "search_error": SEARCH_ERROR,
    }

@app.get("/settings", response_model=sch.SettingsResponse)
async def get_settings():
    s = _settings_get()
    return sch.SettingsResponse(settings=s, settings_file=_display_path(str(SETTINGS_FILE)))

@app.post("/settings", response_model=sch.SettingsResponse)
async def update_settings(request: sch.SettingsUpdateRequest):
    with _settings_lock:
        s = _settings_load()

        if request.autostart_model is not None:
            s["autostart_model"] = bool(request.autostart_model)

        if request.power_idle_watts is not None:
            try:
                s["power_idle_watts"] = float(request.power_idle_watts)
            except Exception:
                raise HTTPException(status_code=400, detail="power_idle_watts must be a number")
        if request.power_max_watts is not None:
            try:
                s["power_max_watts"] = float(request.power_max_watts)
            except Exception:
                raise HTTPException(status_code=400, detail="power_max_watts must be a number")

        if request.tool_files_max_bytes is not None:
            try:
                s["tool_files_max_bytes"] = int(request.tool_files_max_bytes)
            except Exception:
                raise HTTPException(status_code=400, detail="tool_files_max_bytes must be an integer")

        if request.llama_args is not None:
            if not isinstance(request.llama_args, str):
                raise HTTPException(status_code=400, detail="llama_args must be a string")
            val = request.llama_args.strip()
            if not val:
                raise HTTPException(status_code=400, detail="llama_args cannot be empty")
            if len(val) > 8192:
                raise HTTPException(status_code=400, detail="llama_args too long")
            s["llama_args"] = val

        _settings_apply(s)
        _settings_save(s)
        return sch.SettingsResponse(settings=s, settings_file=_display_path(str(SETTINGS_FILE)))

@app.get("/models", response_model=sch.ModelsResponse)
async def list_models():
    """List all available GGUF models in the model directory"""
    models = _list_gguf_models()
    current_model = _get_current_model()
    model_dir = LLM_MODEL_DIR if LLM_MODEL_DIR else CHAT_DIR

    return sch.ModelsResponse(
        models=models,
        current_model=current_model,
        model_dir=_display_path(model_dir or "")
    )

@app.post("/models/switch", response_model=sch.SwitchModelResponse)
async def switch_model(request: sch.SwitchModelRequest):
    """Switch to a different GGUF model"""
    if not CHAT_DIR:
        raise HTTPException(status_code=503, detail="Model switching not configured (CHAT_DIR not set)")

    raw = (request.model_path or "").strip()
    resolved = _resolve_project_path(raw)
    model_path = str(resolved) if resolved is not None else str(Path(raw).expanduser())


    if not os.path.exists(model_path):
        raise HTTPException(status_code=404, detail=f"Model not found: {model_path}")

    if not model_path.endswith('.gguf'):
        raise HTTPException(status_code=400, detail="Model must be a .gguf file")

    try:

        print(f"Stopping current llama-server...")
        _stop_llama_server()


        print(f"Starting llama-server with model: {model_path}")
        pid = _start_llama_server(model_path)

        model_name = os.path.basename(model_path)


        _settings_set("current_model_path", model_path)

        return sch.SwitchModelResponse(
            success=True,
            message=f"Successfully switched to {model_name} (PID: {pid})",
            new_model=model_path
        )
    except Exception as e:
        return sch.SwitchModelResponse(
            success=False,
            message=f"Failed to switch model: {str(e)}",
            new_model=None
        )

@app.post("/models/dir", response_model=sch.ModelDirResponse)
async def update_model_dir(request: sch.ModelDirRequest):
    """Update the model directory used to list GGUF models"""
    model_dir_raw = request.path.strip()
    if not model_dir_raw:
        raise HTTPException(status_code=400, detail="Model directory path is required")
    resolved = _resolve_project_path(model_dir_raw)
    model_dir_abs = str(resolved) if resolved is not None else str(Path(model_dir_raw).expanduser())
    if not os.path.isdir(model_dir_abs):
        raise HTTPException(status_code=400, detail=f"Not a directory: {model_dir_abs}")

    try:
        global LLM_MODEL_DIR
        LLM_MODEL_DIR = model_dir_abs
        os.environ["LLM_MODEL_DIR"] = model_dir_abs
        _settings_set("model_dir", model_dir_abs)
        return sch.ModelDirResponse(
            success=True,
            message="Model directory updated.",
            model_dir=_display_path(model_dir_abs)
        )
    except Exception as exc:
        return sch.ModelDirResponse(
            success=False,
            message=f"Failed to update model directory: {exc}",
            model_dir=None
        )

@app.get("/llama/ctx", response_model=sch.LlamaCtxResponse)
async def get_llama_ctx():
    """Return the configured llama-server ctx-size (from LLAMA_ARGS)."""
    ctx = _llama_parse_ctx_size(LLAMA_ARGS or "")
    return sch.LlamaCtxResponse(
        success=True,
        message="OK",
        ctx_size=ctx,
        llama_args=LLAMA_ARGS or "",
        restarted=False,
        pid=None,
        model=_get_current_model(),
    )

@app.get("/llama/status", response_model=sch.LlamaStatusResponse)
async def get_llama_status():

    try:
        _settings_get()
    except Exception:
        pass

    configured = (LLAMA_ARGS or "").strip()
    pid, model = _read_llama_pidfile()
    if not pid:
        return sch.LlamaStatusResponse(
            running=False,
            pid=None,
            model=model or _get_current_model(),
            cmdline=None,
            llama_args_running=None,
            llama_args_configured=configured,
            ctx_size_running=None,
            ctx_size_configured=_llama_parse_ctx_size(configured),
        )

    running = _pid_is_running(pid)
    cmd = _pid_cmdline(pid) if running else None
    extra = _extract_llama_extra_args(cmd) if cmd else None
    running_args = _shell_join(extra) if extra else None
    return sch.LlamaStatusResponse(
        running=bool(running),
        pid=int(pid),
        model=model or _get_current_model(),
        cmdline=_shell_join(cmd) if cmd else None,
        llama_args_running=running_args,
        llama_args_configured=configured,
        ctx_size_running=_llama_parse_ctx_size(running_args or "") if running_args else None,
        ctx_size_configured=_llama_parse_ctx_size(configured),
    )

@app.post("/llama/ctx", response_model=sch.LlamaCtxResponse)
async def set_llama_ctx(request: sch.LlamaCtxRequest):
    """
    Update the configured llama-server context size (LLAMA_ARGS --ctx-size) and optionally restart
    the running llama-server to apply it.
    """
    if not CHAT_DIR:
        raise HTTPException(status_code=503, detail="Model server management not configured (CHAT_DIR not set)")

    ctx_size = int(request.ctx_size)
    if ctx_size < 256 or ctx_size > 1_048_576:
        raise HTTPException(status_code=400, detail="ctx_size must be between 256 and 1048576")

    global LLAMA_ARGS
    new_args = _llama_set_ctx_size(LLAMA_ARGS or "", ctx_size)
    LLAMA_ARGS = new_args
    os.environ["LLAMA_ARGS"] = new_args
    _settings_set("llama_args", new_args)

    if not request.restart:
        return sch.LlamaCtxResponse(
            success=True,
            message="Updated LLAMA_ARGS (restart skipped).",
            ctx_size=_llama_parse_ctx_size(new_args),
            llama_args=new_args,
            restarted=False,
            pid=None,
            model=_get_current_model(),
        )

    model_path = _get_current_model()
    if not model_path:

        try:
            s = _settings_get()
            candidate = (s.get("current_model_path") or "").strip()
            if candidate and os.path.exists(candidate):
                model_path = candidate
        except Exception:
            pass

    if not model_path:
        return sch.LlamaCtxResponse(
            success=True,
            message="Updated LLAMA_ARGS, but no current model is running to restart (start/switch a model first).",
            ctx_size=_llama_parse_ctx_size(new_args),
            llama_args=new_args,
            restarted=False,
            pid=None,
            model=None,
        )

    try:
        _stop_llama_server()
        pid = _start_llama_server(model_path)

        deadline = time.time() + 5.0
        while time.time() < deadline:
            try:
                os.kill(pid, 0)
            except OSError:
                raise Exception(f"llama-server crashed during startup (possible OOM). Check {LLAMA_LOG_FILE or '/tmp/llama.log'}")
            time.sleep(0.25)
        return sch.LlamaCtxResponse(
            success=True,
            message=f"Restarted llama-server with ctx_size={ctx_size} (PID: {pid})",
            ctx_size=_llama_parse_ctx_size(new_args),
            llama_args=new_args,
            restarted=True,
            pid=pid,
            model=model_path,
        )
    except Exception as e:
        return sch.LlamaCtxResponse(
            success=False,
            message=f"Failed to restart llama-server: {str(e)}",
            ctx_size=_llama_parse_ctx_size(new_args),
            llama_args=new_args,
            restarted=False,
            pid=None,
            model=model_path,
        )

@app.get("/files/dir", response_model=sch.FilesDirResponse)
async def get_files_dir():
    global TOOL_FILES_DIR
    if not TOOL_FILES_DIR:
        return sch.FilesDirResponse(success=False, message="Not set.", files_dir=None, writable=None)
    path = str(Path(TOOL_FILES_DIR).expanduser())
    root = Path(path)
    exists = root.exists() and root.is_dir()
    writable = _is_writable_dir(root) if exists else None
    msg = "OK" if exists else "Directory does not exist."
    return sch.FilesDirResponse(success=exists, message=msg, files_dir=_display_path(path), writable=writable)

@app.post("/files/dir", response_model=sch.FilesDirResponse)
async def set_files_dir(request: sch.FilesDirRequest):
    global TOOL_FILES_DIR
    raw = (request.path or "").strip()
    if not raw:
        raise HTTPException(status_code=400, detail="Path is required")
    root = Path(raw).expanduser()
    if not root.is_absolute():
        root = PROJECT_ROOT / root
    if not root.exists():
        if request.create:
            try:
                root.mkdir(parents=True, exist_ok=True)
            except OSError as exc:
                raise HTTPException(status_code=400, detail=f"Unable to create directory: {exc}")
        else:
            raise HTTPException(status_code=400, detail=f"Directory does not exist: {root}")
    if not root.is_dir():
        raise HTTPException(status_code=400, detail=f"Not a directory: {root}")


    resolved = str(root.resolve())
    TOOL_FILES_DIR = resolved
    os.environ["LLM_TOOL_FILES_DIR"] = resolved
    _settings_set("tool_files_dir", resolved)
    writable = _is_writable_dir(Path(resolved))
    return sch.FilesDirResponse(success=True, message="File tool directory updated.", files_dir=_display_path(resolved), writable=writable)

@app.post("/files/list", response_model=sch.FilesListResponse)
async def files_list(request: sch.FilesListRequest):
    root = _files_root()
    limit = max(1, min(1000, int(request.limit or 200)))
    base = _safe_join(root, request.path)
    if not base.exists():
        raise HTTPException(status_code=404, detail="Path not found")
    if not base.is_dir():
        raise HTTPException(status_code=400, detail="Path is not a directory")

    entries: list[sch.FilesListEntry] = []
    truncated = False

    def add_entry(p: Path):
        nonlocal truncated
        try:
            st = p.stat()
        except OSError:
            st = None
        rel = str(p.relative_to(root))
        is_dir = p.is_dir()
        size = None if is_dir else (int(st.st_size) if st else None)
        mtime = float(st.st_mtime) if st else None
        entries.append(sch.FilesListEntry(path=rel, is_dir=is_dir, size_bytes=size, mtime_epoch=mtime))
        if len(entries) >= limit:
            truncated = True
            return False
        return True

    if request.recursive:
        for dirpath, dirnames, filenames in os.walk(base, followlinks=False):
            dirpath_p = Path(dirpath)

            for d in sorted(dirnames):
                p = dirpath_p / d
                rel = str(p.relative_to(root))
                entries.append(sch.FilesListEntry(path=rel, is_dir=True, size_bytes=None, mtime_epoch=None))
                if len(entries) >= limit:
                    return sch.FilesListResponse(root=_display_path(str(root)), base=str(base.relative_to(root)), entries=entries, truncated=True)
            for f in sorted(filenames):
                if not add_entry(dirpath_p / f):
                    return sch.FilesListResponse(root=_display_path(str(root)), base=str(base.relative_to(root)), entries=entries, truncated=True)
    else:
        try:
            with os.scandir(base) as it:
                items = sorted(it, key=lambda e: (not e.is_dir(follow_symlinks=False), e.name.lower()))
                for entry in items:
                    try:
                        is_dir = entry.is_dir(follow_symlinks=False)
                    except OSError:
                        is_dir = False
                    try:
                        st = entry.stat(follow_symlinks=False)
                    except OSError:
                        st = None

                    rel = str(Path(entry.path).relative_to(root))
                    size = None if is_dir else (int(st.st_size) if st else None)
                    mtime = float(st.st_mtime) if st else None
                    entries.append(sch.FilesListEntry(path=rel, is_dir=is_dir, size_bytes=size, mtime_epoch=mtime))
                    if len(entries) >= limit:
                        truncated = True
                        break
        except OSError as exc:
            raise HTTPException(status_code=500, detail=f"Unable to list directory: {exc}")

    return sch.FilesListResponse(root=_display_path(str(root)), base=str(base.relative_to(root)), entries=entries, truncated=truncated)

@app.post("/files/read", response_model=sch.FilesReadResponse)
async def files_read(request: sch.FilesReadRequest):
    root = _files_root()
    path = _safe_join(root, request.path)
    if not path.exists():
        raise HTTPException(status_code=404, detail="File not found")
    if path.is_dir():
        raise HTTPException(status_code=400, detail="Path is a directory")

    max_bytes = int(request.max_bytes or MAX_FILE_TOOL_BYTES)
    max_bytes = max(1, min(5_000_000, min(max_bytes, int(MAX_FILE_TOOL_BYTES))))
    try:

        with open(path, "rb") as fh:
            raw = fh.read(max_bytes + 1)
    except OSError as exc:
        raise HTTPException(status_code=500, detail=f"Unable to read file: {exc}")

    truncated = len(raw) > max_bytes
    if truncated:
        raw = raw[:max_bytes]
    content = raw.decode("utf-8", errors="replace")
    return sch.FilesReadResponse(
        root=_display_path(str(root)),
        path=str(path.relative_to(root)),
        content=content,
        truncated=truncated,
        bytes_read=len(raw),
    )

@app.post("/files/write", response_model=sch.FilesWriteResponse)
async def files_write(request: sch.FilesWriteRequest):
    root = _files_root()
    path = _safe_join(root, request.path)
    if path.exists() and path.is_dir():
        raise HTTPException(status_code=400, detail="Path is a directory")
    if path.exists() and not request.overwrite:
        raise HTTPException(status_code=409, detail="File exists and overwrite=false")

    backup_rel = None
    if path.exists() and request.overwrite:

        backup = path.with_name(path.name + ".bak")
        n = 1
        while backup.exists():
            backup = path.with_name(path.name + f".bak.{n}")
            n += 1
        try:
            shutil.copy2(path, backup)
            backup_rel = str(backup.relative_to(root))
        except OSError as exc:
            raise HTTPException(status_code=500, detail=f"Unable to create backup: {exc}")

    content = request.content or ""
    if len(content.encode("utf-8", errors="replace")) > 5_000_000:
        raise HTTPException(status_code=400, detail="Content too large")

    try:
        if request.mkdirs:
            bytes_written = _atomic_write_text(path, content)
        else:
            bytes_written = len(content.encode("utf-8", errors="replace"))
            with open(path, "w", encoding="utf-8") as fh:
                fh.write(content)
    except OSError as exc:
        raise HTTPException(status_code=500, detail=f"Unable to write file: {exc}")

    return sch.FilesWriteResponse(
        root=_display_path(str(root)),
        path=str(path.relative_to(root)),
        bytes_written=bytes_written,
        message="OK",
        backup_path=backup_rel,
    )

@app.post("/files/search", response_model=sch.FilesSearchResponse)
async def files_search(request: sch.FilesSearchRequest):
    root = _files_root()
    query = (request.query or "").strip()
    if not query:
        raise HTTPException(status_code=400, detail="Query cannot be empty")
    limit = max(1, min(500, int(request.limit or 50)))
    base = _safe_join(root, request.path or ".")
    if not base.exists():
        raise HTTPException(status_code=404, detail="Path not found")

    matches: list[sch.FilesSearchMatch] = []
    truncated = False

    rg = shutil.which("rg")
    if rg:
        cmd = [rg, "--no-heading", "--line-number", "--column", "--color", "never"]
        if not bool(request.case_sensitive):
            cmd.append("-i")
        if not bool(request.regex):
            cmd.append("-F")
        cmd.extend(["--", query, str(base)])
        try:
            proc = subprocess.run(cmd, capture_output=True, text=True, timeout=8)
        except subprocess.TimeoutExpired:
            raise HTTPException(status_code=408, detail="Search timed out (narrow your path or query).")
        if proc.returncode not in (0, 1):
            err = (proc.stderr or proc.stdout or "").strip() or "rg failed"
            raise HTTPException(status_code=500, detail=err)


        for ln in (proc.stdout or "").splitlines():
            m = re.match(r"^(.*?):(\\d+):(\\d+):(.*)$", ln)
            if not m:
                continue
            path_s, line_s, col_s, text = m.group(1), m.group(2), m.group(3), m.group(4)
            try:
                rel = str(Path(path_s).resolve().relative_to(root))
            except Exception:
                try:
                    rel = str(Path(path_s).relative_to(root))
                except Exception:
                    rel = str(path_s)
            try:
                line_i = int(line_s)
            except Exception:
                line_i = 0
            try:
                col_i = int(col_s)
            except Exception:
                col_i = None
            matches.append(sch.FilesSearchMatch(path=rel, line=line_i, column=col_i, text=text))
            if len(matches) >= limit:
                truncated = True
                break

        return sch.FilesSearchResponse(
            root=_display_path(str(root)),
            base=str(base.relative_to(root)) if base != root else ".",
            query=query,
            matches=matches,
            truncated=truncated,
        )


    needle = query if bool(request.case_sensitive) else query.lower()

    def iter_files(p: Path):
        if p.is_dir():
            for dirpath, _, filenames in os.walk(p, followlinks=False):
                for fn in sorted(filenames):
                    yield Path(dirpath) / fn
        else:
            yield p

    for fp in iter_files(base):
        if len(matches) >= limit:
            truncated = True
            break
        try:
            st = fp.stat()
        except OSError:
            continue

        if st.st_size > 2_000_000:
            continue
        try:
            with open(fp, "rb") as fh:
                raw = fh.read(200_000)
            if b"\x00" in raw:
                continue
            lines = raw.decode("utf-8", errors="replace").splitlines()
        except Exception:
            continue
        for idx, line in enumerate(lines, start=1):
            hay = line if bool(request.case_sensitive) else line.lower()
            if needle in hay:
                try:
                    rel = str(fp.relative_to(root))
                except Exception:
                    rel = str(fp)
                matches.append(sch.FilesSearchMatch(path=rel, line=idx, column=None, text=line))
                if len(matches) >= limit:
                    truncated = True
                    break

    return sch.FilesSearchResponse(
        root=_display_path(str(root)),
        base=str(base.relative_to(root)) if base != root else ".",
        query=query,
        matches=matches,
        truncated=truncated,
    )

@app.post("/search/web", response_model=sch.SearchResponse)
async def search_web(request: sch.SearchRequest):
    """
    Search using DuckDuckGo and return formatted results
    """
    if not request.query or len(request.query.strip()) == 0:
        raise HTTPException(status_code=400, detail="Query cannot be empty")

    if DDGS is None:
        raise HTTPException(
            status_code=503,
            detail="Search service not configured. Install ddgs."
        )

    try:
        q_norm = request.query.strip()
        c_norm = max(1, min(10, int(request.count or 5)))
        key = (q_norm.lower(), c_norm)
        now = time.time()
        global _search_backoff_until, _search_backoff_s

        with _search_cache_lock:
            if _search_backoff_until and now < _search_backoff_until:
                retry_after = int(max(1, _search_backoff_until - now))
                return sch.SearchResponse(
                    query=q_norm,
                    results=[],
                    model=API_MODEL,
                    error="DuckDuckGo rate-limited. Retry later.",
                    cached=False,
                    retry_after_s=retry_after,
                )
            cached = _search_cache.get(key)
            if cached:
                ts = float(cached.get("_ts") or 0.0)
                if ts and (now - ts) <= max(0.0, _search_cache_ttl_s):
                    return sch.SearchResponse(
                        query=q_norm,
                        results=cached.get("results") or [],
                        model=API_MODEL,
                        error=None,
                        cached=True,
                        retry_after_s=None,
                    )


        ddgs = DDGS()
        try:
            raw_results = ddgs.text(q_norm, max_results=c_norm)
            if raw_results is None:
                raw_results = []
            if not isinstance(raw_results, list):
                raw_results = list(raw_results)
        finally:
            close = getattr(ddgs, "close", None)
            if callable(close):
                try:
                    close()
                except Exception:
                    pass


        results = []
        for item in raw_results:
            results.append(sch.SearchResult(
                name=item.get("title") or item.get("heading") or "No title",
                url=item.get("href") or item.get("url") or "",
                snippet=item.get("body") or item.get("snippet") or item.get("content") or "No description available"
            ))

        if not results:
            return sch.SearchResponse(
                query=q_norm,
                results=[],
                model=API_MODEL,
                error="No results returned from DuckDuckGo. Check network access or try again.",
                cached=False,
            )

        with _search_cache_lock:
            _search_cache[key] = {"_ts": now, "results": results}
            _search_backoff_until = 0.0
            _search_backoff_s = 0.0

        return sch.SearchResponse(
            query=q_norm,
            results=results,
            model=API_MODEL,
            error=None,
            cached=False,
        )

    except Exception as e:
        msg = str(e)
        low = msg.lower()

        if ("429" in low) or ("rate" in low) or ("too many" in low) or ("ratelimit" in low):
            with _search_cache_lock:
                now = time.time()
                _search_backoff_s = float(_search_backoff_s or 10.0)
                _search_backoff_s = min(300.0, max(10.0, _search_backoff_s * 1.6))
                _search_backoff_until = now + _search_backoff_s
                retry_after = int(_search_backoff_s)
            return sch.SearchResponse(
                query=request.query.strip(),
                results=[],
                model=API_MODEL,
                error=f"DuckDuckGo rate-limited: {msg}",
                cached=False,
                retry_after_s=retry_after,
            )

        return sch.SearchResponse(
            query=request.query,
            results=[],
            model=API_MODEL,
            error=f"Search failed: {msg}",
            cached=False,
        )

def _read_power_supply_watts():
    if not sys.platform.startswith("linux"):
        return None
    try:
        from psutil import _pslinux
    except Exception:
        return None

    power_path = getattr(_pslinux, "POWER_SUPPLY_PATH", "/sys/class/power_supply")
    try:
        entries = [
            entry for entry in os.listdir(power_path)
            if entry.startswith("BAT") or "battery" in entry.lower()
        ]
    except FileNotFoundError:
        return None

    if not entries:
        return None

    root = os.path.join(power_path, sorted(entries)[0])

    def _read_number(*relative_paths):
        for rel in relative_paths:
            path = os.path.join(root, rel)
            try:
                with open(path, "r", encoding="utf-8") as fh:
                    raw = fh.read().strip()
            except FileNotFoundError:
                continue
            except OSError:
                continue
            try:
                return float(raw), rel
            except ValueError:
                continue
        return None, None

    power_value, source = _read_number("power_now", "current_now")
    if power_value is None:
        return None

    watts = None
    if source == "power_now":

        watts = power_value / 1_000_000.0
    elif source == "current_now":
        voltage_value, _ = _read_number("voltage_now")
        if voltage_value is not None:
            watts = (power_value * voltage_value) / 1_000_000_000_000.0

    if watts is None:
        return None

    if watts <= 0:
        return None
    return round(watts, 2)

def _read_hwmon_power_watts():
    base_path = "/sys/class/hwmon"
    if not os.path.isdir(base_path):
        return None
    try:
        hwmons = sorted(os.listdir(base_path))
    except OSError:
        return None

    for entry in hwmons:
        root = os.path.join(base_path, entry)
        try:
            files = os.listdir(root)
        except OSError:
            continue
        power_files = sorted(f for f in files if f.startswith("power") and f.endswith("_input"))
        for pf in power_files:
            path = os.path.join(root, pf)
            try:
                with open(path, "r", encoding="utf-8") as fh:
                    raw = fh.read().strip()
                    value = float(raw)
            except (OSError, ValueError):
                continue
            if value <= 0:
                continue

            watts = value / 1_000_000.0
            return round(watts, 2)
    return None

def _read_linux_power_watts():
    if not sys.platform.startswith("linux"):
        return None
    watts = _read_power_supply_watts()
    if watts is not None:
        return watts
    return _read_hwmon_power_watts()

def _estimate_power_draw():
    if psutil is None:
        return None
    try:
        load = psutil.cpu_percent(interval=0.05) / 100.0
        clamped = max(0.0, min(1.0, load))
        span = max(0.0, POWER_MAX_WATTS - POWER_IDLE_WATTS)
        watts = POWER_IDLE_WATTS + span * clamped
        return round(max(0.0, watts), 2)
    except Exception:
        return None

def get_power_metrics():
    payload = {
        "watts": None,
        "plugged": None,
        "percent": None,
        "status": "unavailable",
        "detail": None,
        "timestamp": datetime.utcnow().isoformat() + "Z",
        "ram_used_bytes": None,
        "ram_total_bytes": None,
        "ram_percent": None,
        "cpu_temp_c": None,
        "temp_source": None,
        "cpu_usage_percent": None,
        "power_idle_watts": POWER_IDLE_WATTS,
        "power_max_watts": POWER_MAX_WATTS,
        "power_utilization": None,
    }

    battery = None
    if psutil is None:
        payload["detail"] = "psutil is not installed"
    else:
        battery_reader = getattr(psutil, "sensors_battery", None)
        if battery_reader is None:
            payload["detail"] = "Battery sensors not supported on this platform"
        else:
            try:
                battery = battery_reader()
            except Exception as exc:
                payload["detail"] = f"Battery sensor error: {exc}"
                payload["status"] = "error"
            else:
                if battery is None:
                    payload["detail"] = "Battery information unavailable"
                else:
                    payload["plugged"] = getattr(battery, "power_plugged", None)
                    payload["percent"] = getattr(battery, "percent", None)

    watts = None
    if sys.platform.startswith("linux"):
        watts = _read_linux_power_watts()


    if watts is None and battery is not None:
        for attr in ("power_watts", "power_now", "current_watts"):
            raw = getattr(battery, attr, None)
            if raw is None:
                continue
            try:
                watts = float(raw)
                break
            except (TypeError, ValueError):
                continue

    if watts is None:
        estimated = _estimate_power_draw()
        if estimated is not None:
            watts = estimated
            payload["status"] = "estimated"
            payload["detail"] = "Estimated from CPU utilization"

    if watts is not None:
        payload["watts"] = round(watts, 2)
        if payload["status"] not in ("ok", "estimated"):
            payload["status"] = "ok"
        if payload["status"] == "ok":
            payload["detail"] = None
        span = max(0.0, POWER_MAX_WATTS - POWER_IDLE_WATTS)
        if span > 0:
            utilization = (watts - POWER_IDLE_WATTS) / span
            payload["power_utilization"] = max(0.0, min(1.0, utilization))
    else:
        if not payload["detail"]:
            payload["detail"] = "Power telemetry unavailable on this host."

    if psutil is not None:
        try:
            vm = psutil.virtual_memory()
            payload["ram_used_bytes"] = int(vm.used)
            payload["ram_total_bytes"] = int(vm.total)
            payload["ram_percent"] = round(float(vm.percent), 2)
        except Exception:
            payload["ram_percent"] = None
        try:
            usage = psutil.cpu_percent(interval=0.05)
            payload["cpu_usage_percent"] = round(float(usage), 1)
        except Exception:
            payload["cpu_usage_percent"] = None

    temp_value, temp_source = _read_cpu_temperature()
    if temp_value is not None:
        payload["cpu_temp_c"] = round(float(temp_value), 1)
        payload["temp_source"] = temp_source


    vram_used, vram_total, vram_source = _read_vram()
    if vram_used is not None:
        payload["vram_used_bytes"] = int(vram_used)
        payload["vram_total_bytes"] = int(vram_total) if vram_total is not None else None

        if vram_total and vram_total > 0:
            payload["vram_percent"] = round((vram_used / vram_total) * 100, 2)
        else:
            payload["vram_percent"] = None
        payload["vram_source"] = vram_source


    payload["gpu_driver"] = _detect_gpu_driver()
    payload["vulkan_available"] = _check_vulkan_available()

    return payload

def _read_cpu_temperature():
    if psutil is None:
        return None, None
    temp_reader = getattr(psutil, "sensors_temperatures", None)
    if temp_reader is None:
        return None, None
    try:
        temps = temp_reader()
    except Exception:
        return None, None
    if not temps:
        return None, None

    preferred = [
        "coretemp",
        "k10temp",
        "cpu-thermal",
        "soc-thermal",
        "thermal-fan-est",
        "acpitz",
    ]

    def pick_entry(entries):
        for entry in entries:
            current = getattr(entry, "current", None)
            if current is not None:
                return current
        return None

    for key in preferred:
        if key in temps:
            value = pick_entry(temps[key])
            if value is not None:
                return value, key

    for key, entries in temps.items():
        value = pick_entry(entries)
        if value is not None:
            return value, key
    return None, None

def _read_nvidia_vram():
    """
    Read VRAM from NVIDIA GPU using nvidia-smi command.
    Returns GPU with most VRAM if multiple GPUs present.
    """
    try:
        result = subprocess.run(
            ['nvidia-smi', '--query-gpu=memory.used,memory.total', '--format=csv,noheader,nounits'],
            capture_output=True,
            text=True,
            timeout=2
        )
        if result.returncode == 0 and result.stdout.strip():
            lines = result.stdout.strip().split('\n')
            best_gpu = None
            max_vram = 0


            for idx, line in enumerate(lines):
                parts = line.split(',')
                if len(parts) == 2:
                    try:
                        used_mb = float(parts[0].strip())
                        total_mb = float(parts[1].strip())

                        if total_mb > max_vram:
                            max_vram = total_mb
                            best_gpu = (used_mb, total_mb, idx)
                    except ValueError:
                        continue

            if best_gpu:
                used_mb, total_mb, gpu_idx = best_gpu
                source = f"nvidia-smi:gpu{gpu_idx}" if len(lines) > 1 else "nvidia-smi"
                return int(used_mb * 1024 * 1024), int(total_mb * 1024 * 1024), source
    except FileNotFoundError:

        pass
    except (subprocess.TimeoutExpired, ValueError, OSError):

        pass
    return None, None, None

def _read_amd_vram():
    """
    Read VRAM from AMD GPU using rocm-smi command or sysfs fallback.
    Returns GPU with most VRAM if multiple GPUs present.
    """

    try:
        result = subprocess.run(
            ['rocm-smi', '--showmeminfo', 'vram', '--json'],
            capture_output=True,
            text=True,
            timeout=2
        )
        if result.returncode == 0 and result.stdout.strip():
            try:
                import json
                data = json.loads(result.stdout)


                if isinstance(data, dict):
                    best_gpu = None
                    max_vram = 0

                    for gpu_id, gpu_data in data.items():
                        if isinstance(gpu_data, dict):
                            vram_info = gpu_data.get('VRAM Total Memory (B)', {})
                            if isinstance(vram_info, dict):
                                total = int(vram_info.get('value', 0))
                                used = int(gpu_data.get('VRAM Total Used Memory (B)', {}).get('value', 0))
                                if total > max_vram:
                                    max_vram = total
                                    best_gpu = (used, total, gpu_id)

                    if best_gpu:
                        used, total, gpu_id = best_gpu
                        source = f"rocm-smi:gpu{gpu_id}" if len(data) > 1 else "rocm-smi"
                        return used, total, source
            except (json.JSONDecodeError, KeyError, ValueError):
                pass
    except FileNotFoundError:

        pass
    except (subprocess.TimeoutExpired, OSError):

        pass


    try:
        result = subprocess.run(
            ['rocm-smi', '--showmeminfo', 'vram', '--csv'],
            capture_output=True,
            text=True,
            timeout=2
        )
        if result.returncode == 0 and result.stdout.strip():
            lines = result.stdout.strip().split('\n')
            best_gpu = None
            max_vram = 0

            for idx, line in enumerate(lines[1:], 0):
                parts = [p.strip() for p in line.split(',')]
                if len(parts) >= 3:
                    try:

                        used_mb = float(parts[1])
                        total_mb = float(parts[2])

                        if total_mb > max_vram:
                            max_vram = total_mb
                            best_gpu = (used_mb, total_mb, idx)
                    except ValueError:
                        continue

            if best_gpu:
                used_mb, total_mb, gpu_idx = best_gpu
                source = f"rocm-smi:gpu{gpu_idx}" if len(lines) > 2 else "rocm-smi"
                return int(used_mb * 1024 * 1024), int(total_mb * 1024 * 1024), source
    except (FileNotFoundError, subprocess.TimeoutExpired, ValueError, OSError):
        pass


    try:
        drm_path = '/sys/class/drm'
        if os.path.exists(drm_path):
            best_card = None
            max_vram = 0


            for entry in sorted(os.listdir(drm_path)):
                if not entry.startswith('card') or '-' in entry:
                    continue

                vram_used_path = os.path.join(drm_path, entry, 'device', 'mem_info_vram_used')
                vram_total_path = os.path.join(drm_path, entry, 'device', 'mem_info_vram_total')

                if os.path.exists(vram_used_path) and os.path.exists(vram_total_path):
                    try:
                        with open(vram_used_path, 'r') as f:
                            used = int(f.read().strip())
                        with open(vram_total_path, 'r') as f:
                            total = int(f.read().strip())


                        if total > max_vram:
                            max_vram = total
                            best_card = (used, total, entry)
                    except (ValueError, OSError):
                        continue


            if best_card:
                return best_card[0], best_card[1], f"amdgpu-sysfs:{best_card[2]}"
    except (FileNotFoundError, OSError):
        pass

    return None, None, None

def _read_intel_vram():
    """
    Read VRAM from Intel GPU using debugfs.
    Intel integrated GPUs share system RAM, so this is best-effort.
    """

    try:
        debugfs_path = '/sys/kernel/debug/dri'
        if os.path.exists(debugfs_path):

            for entry in sorted(os.listdir(debugfs_path)):
                gem_path = os.path.join(debugfs_path, entry, 'i915_gem_objects')
                if os.path.exists(gem_path):
                    try:
                        with open(gem_path, 'r') as f:
                            content = f.read()

                            for line in content.split('\n'):
                                if 'total' in line.lower() and 'bytes' in line.lower():

                                    parts = line.split()
                                    for i, part in enumerate(parts):
                                        if 'bytes' in part.lower() and i > 0:
                                            try:
                                                used = int(parts[i-1])


                                                return used, 0, f"intel-debugfs:{entry}"
                                            except ValueError:
                                                continue
                    except (PermissionError, OSError):

                        continue
    except (FileNotFoundError, OSError):
        pass

    return None, None, None

def _read_vram():
    """
    Read VRAM usage by checking for available tools in order of preference.
    Tries: nvidia-smi -> rocm-smi -> AMD sysfs -> Intel debugfs
    """

    used, total, source = _read_nvidia_vram()
    if used is not None:
        return used, total, source


    used, total, source = _read_amd_vram()
    if used is not None:
        return used, total, source


    used, total, source = _read_intel_vram()
    if used is not None:
        return used, total, source

    return None, None, None

def _detect_gpu_driver():
    """Detect which GPU driver is being used"""
    try:
        drm_path = '/sys/class/drm'
        if os.path.exists(drm_path):
            for entry in sorted(os.listdir(drm_path)):
                if not entry.startswith('card') or '-' in entry:
                    continue

                uevent_path = os.path.join(drm_path, entry, 'device', 'uevent')
                if os.path.exists(uevent_path):
                    with open(uevent_path, 'r') as f:
                        for line in f:
                            if line.startswith('DRIVER='):
                                driver = line.strip().split('=')[1]
                                return driver
    except (FileNotFoundError, OSError):
        pass
    return None

def _check_vulkan_available():
    """Check if Vulkan is available on the system"""

    vulkan_libs = [
        '/usr/lib64/libvulkan.so.1',
        '/usr/lib/x86_64-linux-gnu/libvulkan.so.1',
        '/usr/lib/libvulkan.so.1',
        '/usr/local/lib/libvulkan.so.1'
    ]

    for lib in vulkan_libs:
        if os.path.exists(lib):
            return True


    try:
        result = subprocess.run(['which', 'vulkaninfo'], capture_output=True, timeout=1)
        if result.returncode == 0:
            return True
    except (FileNotFoundError, subprocess.TimeoutExpired):
        pass

    return False

@app.get("/telemetry/power", response_model=sch.PowerTelemetry)
async def telemetry_power():
    return sch.PowerTelemetry(**get_power_metrics())

if __name__ == "__main__":
    print("=" * 60)
    print("IRIS Search API Server")
    print("=" * 60)
    print(f"Starting server on http://{API_HOST}:{API_PORT}")
    print("Endpoints:")
    print("  POST /search/web - Perform web search")
    print("  GET  /health - Health check")
    print("=" * 60)

    uvicorn.run(
        app,
        host=API_HOST,
        port=API_PORT,
        log_level="info"
    )
