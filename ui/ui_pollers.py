import threading
import time
import requests


def model_server_status(model_server_url: str) -> tuple[bool, bool]:
    """
    Returns (online, ready).
    - online: HTTP reachable
    - ready: best-effort "can accept completions" (may be True for older builds where we can't detect)
    """
    base = (model_server_url or "").rstrip("/")
    online = False
    ready = None

    for path in ("/health", "/v1/models"):
        try:
            resp = requests.get(f"{base}{path}", timeout=2)
        except Exception:
            continue
        online = True
        if resp.status_code == 200:
            ready = True
            break
        if resp.status_code == 503:
            ready = False
            break

    if not online:
        try:
            resp = requests.get(f"{base}/completion", timeout=2)
            online = resp is not None
        except Exception:
            online = False

    if ready is None:
        ready = bool(online)

    return bool(online), bool(ready)


def is_model_server_online(model_server_url: str) -> bool:
    return model_server_status(model_server_url)[0]


def is_model_server_ready(model_server_url: str) -> bool:
    return model_server_status(model_server_url)[1]


def poll_health_loop(
    *,
    page,
    ui_call,
    state: dict,
    model_server_url: str,
    search_api_url: str,
    model_status_dot,
    model_switch_spinner,
    search_status_dot,
    web_search_backoff_label,
    update_send_state,
    show_snack,
    healthcheck_interval_ms: int,
    success_color: str,
    warning_color: str,
    danger_color: str,
) -> None:
    api_base = (search_api_url or "").rstrip("/")

    while True:
        try:
            model_online, model_ready = model_server_status(model_server_url)
        except Exception:
            model_online, model_ready = (False, False)
        try:
            search_resp = requests.get(f"{api_base}/health", timeout=3)
            api_ok = search_resp.ok
            health = search_resp.json() if api_ok else {}
            search_enabled = bool(health.get("search_enabled", True)) if api_ok else False
            search_backend = (health.get("search_backend") if isinstance(health, dict) else None) if api_ok else None
            search_error = (health.get("search_error") if isinstance(health, dict) else None) if api_ok else None
            web_search_ok = bool(api_ok and search_enabled)
        except Exception:
            api_ok = False
            web_search_ok = False
            search_enabled = False
            search_backend = None
            search_error = None

        def apply_status():
            if state.get("switching_model"):
                state["model_online"] = False
                state["model_ready"] = False
            else:
                state["model_online"] = bool(model_online)
                if state.get("model_loading"):
                    state["model_ready"] = False
                    if model_ready:
                        state["model_loading"] = False
                        state["model_loading_since"] = None
                        state["model_loading_error_shown"] = False
                        state["model_ready"] = True
                else:
                    state["model_ready"] = bool(model_ready)

            state["api_online"] = api_ok
            state["search_online"] = web_search_ok
            state["search_enabled"] = bool(search_enabled)
            state["search_backend"] = search_backend
            state["search_error"] = search_error

            loading = bool(state.get("switching_model") or state.get("model_loading"))
            if loading:
                model_status_dot.bgcolor = warning_color
                model_switch_spinner.visible = True
            else:
                if state.get("model_online") and (not state.get("model_ready")):
                    model_status_dot.bgcolor = warning_color
                else:
                    model_status_dot.bgcolor = success_color if state.get("model_online") else danger_color
                model_switch_spinner.visible = False

            if state.get("model_loading"):
                since = state.get("model_loading_since")
                if isinstance(since, (int, float)) and since > 0:
                    elapsed = time.time() - float(since)
                    if (not state.get("model_online")) and elapsed > 120 and (not state.get("model_loading_error_shown")):
                        state["model_loading_error_shown"] = True
                        state["model_loading"] = False
                        model_status_dot.bgcolor = danger_color
                        show_snack("Model restart failed (possible OOM). Check llama.log and try a smaller ctx-size.", danger_color)

            now = time.time()
            backoff_until = float(state.get("search_rate_limited_until") or 0.0)
            if backoff_until and now < backoff_until:
                search_status_dot.bgcolor = warning_color
                try:
                    remaining = int(max(1, backoff_until - now))
                    web_search_backoff_label.value = f"Web search backoff: {remaining}s"
                    web_search_backoff_label.visible = True
                except Exception:
                    web_search_backoff_label.visible = False
            else:
                if not api_ok:
                    search_status_dot.bgcolor = danger_color
                else:
                    search_status_dot.bgcolor = success_color if web_search_ok else warning_color
                web_search_backoff_label.visible = False

            update_send_state()
            page.update()

        ui_call(page, apply_status)
        time.sleep(max(0.25, float(healthcheck_interval_ms) / 1000.0))


def poll_telemetry_loop(
    *,
    page,
    ui_call,
    search_api_url: str,
    update_status_pill,
    power_pill,
    ram_pill,
    cpu_pill,
    temp_pill,
    vram_pill,
    format_bytes,
    telemetry_interval_ms: int,
) -> None:
    api_base = (search_api_url or "").rstrip("/")

    while True:
        try:
            resp = requests.get(f"{api_base}/telemetry/power", timeout=5)
            resp.raise_for_status()
            data = resp.json()
        except Exception:
            data = None

        def apply_telemetry():
            if not data:
                update_status_pill(power_pill, "n/a", "alert")
                update_status_pill(ram_pill, "n/a", "alert")
                update_status_pill(cpu_pill, "n/a", "alert")
                update_status_pill(temp_pill, "n/a", "alert")
                update_status_pill(vram_pill, "--", "idle")
                page.update()
                return

            watts = data.get("watts")
            util = data.get("power_utilization")
            severity = "ok"
            if util is not None:
                if util >= 0.85:
                    severity = "alert"
                elif util >= 0.6:
                    severity = "warn"
            update_status_pill(power_pill, f"{watts:.1f} W" if isinstance(watts, (int, float)) else "n/a", severity)

            ram_percent = data.get("ram_percent")
            ram_sev = "ok"
            if isinstance(ram_percent, (int, float)):
                if ram_percent >= 85:
                    ram_sev = "alert"
                elif ram_percent >= 70:
                    ram_sev = "warn"
                ram_text = f"{ram_percent:.1f}%"
            else:
                ram_text = "n/a"
                ram_sev = "alert"
            update_status_pill(ram_pill, ram_text, ram_sev)

            cpu_usage = data.get("cpu_usage_percent")
            cpu_sev = "ok"
            if isinstance(cpu_usage, (int, float)):
                if cpu_usage >= 85:
                    cpu_sev = "alert"
                elif cpu_usage >= 60:
                    cpu_sev = "warn"
                cpu_text = f"{cpu_usage:.1f}%"
            else:
                cpu_text = "n/a"
                cpu_sev = "alert"
            update_status_pill(cpu_pill, cpu_text, cpu_sev)

            temp = data.get("cpu_temp_c")
            temp_sev = "ok"
            if isinstance(temp, (int, float)):
                if temp >= 75:
                    temp_sev = "alert"
                elif temp >= 60:
                    temp_sev = "warn"
                temp_text = f"{temp:.1f} C"
            else:
                temp_text = "n/a"
                temp_sev = "alert"
            update_status_pill(temp_pill, temp_text, temp_sev)

            vram_used = data.get("vram_used_bytes")
            vram_total = data.get("vram_total_bytes")
            if isinstance(vram_used, (int, float)):
                if vram_total and vram_total > 0:
                    percent = (vram_used / vram_total) * 100
                    if percent < 0:
                        percent = 0
                    elif percent > 100:
                        percent = 100
                    vram_text = f"{percent:.1f}%"
                    vram_sev = "warn" if percent >= 70 else "ok"
                    if percent >= 90:
                        vram_sev = "alert"
                else:
                    vram_text = format_bytes(vram_used)
                    vram_sev = "ok"
            else:
                vram_text = "--"
                vram_sev = "idle"
            update_status_pill(vram_pill, vram_text, vram_sev)
            page.update()

        ui_call(page, apply_telemetry)
        time.sleep(max(0.5, float(telemetry_interval_ms) / 1000.0))


def start_pollers(*, health: dict, telemetry: dict) -> list[threading.Thread]:
    t1 = threading.Thread(target=poll_health_loop, kwargs=dict(health or {}), daemon=True)
    t2 = threading.Thread(target=poll_telemetry_loop, kwargs=dict(telemetry or {}), daemon=True)
    t1.start()
    t2.start()
    return [t1, t2]
