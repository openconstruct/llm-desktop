#!/usr/bin/env python3
import os
import threading
import time
from pathlib import Path

import flet as ft
import requests

import ui_config as cfg
import chat_controller
import ui_backend_tools
import ui_documents as docs
import ui_filepicker as filepicker_utils
import ui_flet
import ui_markdown
import ui_prefs_io
import ui_prompt
import ui_sessions_io
import ui_pollers
import ui_shell
import ui_sessions as sessions
import ui_style as style
import ui_text as text
import view_keyboard
import view_chat
import view_models
import view_sessions
import view_settings
import view_tools


APP_TITLE = cfg.APP_TITLE

LLM_HOST = cfg.LLM_HOST
LLM_PORT = cfg.LLM_PORT
API_HOST = cfg.API_HOST
API_PORT = cfg.API_PORT
MODEL_SERVER_URL = cfg.MODEL_SERVER_URL
SEARCH_API_URL = cfg.SEARCH_API_URL

HEALTHCHECK_INTERVAL_MS = cfg.HEALTHCHECK_INTERVAL_MS
POWER_POLL_INTERVAL_MS = cfg.POWER_POLL_INTERVAL_MS
STREAM_CONNECT_TIMEOUT_S = cfg.STREAM_CONNECT_TIMEOUT_S
STREAM_READ_TIMEOUT_S = cfg.STREAM_READ_TIMEOUT_S

MAX_TEXT_FILE_EMBED_SIZE = cfg.MAX_TEXT_FILE_EMBED_SIZE
CHARS_PER_TOKEN = cfg.CHARS_PER_TOKEN
CHAT_MAX_WIDTH = cfg.CHAT_MAX_WIDTH
CHAT_MIN_WIDTH = cfg.CHAT_MIN_WIDTH
CHAT_SIDE_MARGIN = cfg.CHAT_SIDE_MARGIN
SIDEBAR_WIDTH = cfg.SIDEBAR_WIDTH

BG = style.BG
SIDEBAR_BG = style.SIDEBAR_BG
SURFACE = style.SURFACE
SURFACE_ALT = style.SURFACE_ALT
SURFACE_ELEV = style.SURFACE_ELEV
BORDER = style.BORDER
TEXT_PRIMARY = style.TEXT_PRIMARY
TEXT_MUTED = style.TEXT_MUTED
ACCENT = style.ACCENT
ACCENT_SOFT = style.ACCENT_SOFT
SUCCESS = style.SUCCESS
WARNING = style.WARNING
DANGER = style.DANGER
STATUS_LABEL_COLOR = style.STATUS_LABEL_COLOR

_status_color = style.status_color
_status_text_color = style.status_text_color


THEME_PRESETS = {
    "Obsidian": {
        "BG": style.BG,
        "SIDEBAR_BG": style.SIDEBAR_BG,
        "SURFACE": style.SURFACE,
        "SURFACE_ALT": style.SURFACE_ALT,
        "SURFACE_ELEV": style.SURFACE_ELEV,
        "BORDER": style.BORDER,
        "TEXT_PRIMARY": style.TEXT_PRIMARY,
        "TEXT_MUTED": style.TEXT_MUTED,
    },
    "Graphite": {
        "BG": "#0f1216",
        "SIDEBAR_BG": "#0c1015",
        "SURFACE": "#141a22",
        "SURFACE_ALT": "#101722",
        "SURFACE_ELEV": "#18202a",
        "BORDER": "#243041",
        "TEXT_PRIMARY": style.TEXT_PRIMARY,
        "TEXT_MUTED": style.TEXT_MUTED,
    },
    "Midnight": {
        "BG": "#0b1020",
        "SIDEBAR_BG": "#090d18",
        "SURFACE": "#0f1730",
        "SURFACE_ALT": "#0d1429",
        "SURFACE_ELEV": "#121c3a",
        "BORDER": "#22325a",
        "TEXT_PRIMARY": style.TEXT_PRIMARY,
        "TEXT_MUTED": style.TEXT_MUTED,
    },
}

DENSITY_PRESETS = {
    "Comfortable": {"chat_spacing": 14, "chat_padding": 12, "bubble_padding": 14, "meta_gap": 4, "outer_pad_v": 6},
    "Compact": {"chat_spacing": 10, "chat_padding": 8, "bubble_padding": 10, "meta_gap": 2, "outer_pad_v": 4},
}

DATA_DIR = sessions.DATA_DIR
SESSIONS_DIR = sessions.SESSIONS_DIR
SESSION_INDEX_FILE = sessions.SESSION_INDEX_FILE
_load_session_index = sessions.load_session_index
_save_session_index = sessions.save_session_index

_ui_call = ui_flet.ui_call

_format_bytes = text.format_bytes
_strip_emoji = text.strip_emoji
_parse_tool_call = text.parse_tool_call

_read_text_file = docs.read_text_file
_read_pdf_file = docs.read_pdf_file
_read_docx_file = docs.read_docx_file
_read_csv_file = docs.read_csv_file


def main(page: ft.Page):
    sessions.ensure_data_dir()

    UI_PREFS_FILE = DATA_DIR / "ui_prefs.json"
    ui_prefs = ui_prefs_io.load_ui_prefs(UI_PREFS_FILE)


    def _apply_theme_globals(preset_name: str):
        global BG, SIDEBAR_BG, SURFACE, SURFACE_ALT, SURFACE_ELEV, BORDER, TEXT_PRIMARY, TEXT_MUTED
        pal = THEME_PRESETS.get(preset_name) or THEME_PRESETS["Obsidian"]
        BG = pal["BG"]
        SIDEBAR_BG = pal["SIDEBAR_BG"]
        SURFACE = pal["SURFACE"]
        SURFACE_ALT = pal["SURFACE_ALT"]
        SURFACE_ELEV = pal["SURFACE_ELEV"]
        BORDER = pal["BORDER"]
        TEXT_PRIMARY = pal["TEXT_PRIMARY"]
        TEXT_MUTED = pal["TEXT_MUTED"]

    def _get_density(name: str) -> dict:
        return dict(DENSITY_PRESETS.get(name) or DENSITY_PRESETS["Comfortable"])

    _theme_name = str(ui_prefs.get("theme_preset") or "Obsidian")
    _density_name = str(ui_prefs.get("density_preset") or "Comfortable")
    _assistant_name = str(ui_prefs.get("assistant_name") or "Assistant")
    _assistant_tone = str(ui_prefs.get("assistant_tone") or "helpful")
    _apply_theme_globals(_theme_name)
    density_cfg = _get_density(_density_name)

    page.title = cfg.APP_TITLE
    page.window_min_width = 1100
    page.window_min_height = 720

    try:
        page.window_maximized = True
    except Exception:
        try:
            win = getattr(page, "window", None)
            if win is not None:
                setattr(win, "maximized", True)
        except Exception:
            pass
    page.theme_mode = ft.ThemeMode.DARK
    page.bgcolor = style.BG
    page.padding = 0


    page.theme = ft.Theme(font_family="Noto Sans")

    state = {
        "messages": [],
        "pending_search_contexts": [],
        "loaded_documents": [],


        "model_online": False,
        "model_ready": False,
        "model_loading": False,
        "model_loading_since": None,
        "model_loading_error_shown": False,
        "api_online": False,
        "search_online": False,

        "search_rate_limited_until": 0.0,
        "files_tool_dir": "",
        "tool_files_max_bytes": 200000,
        "theme_preset": _theme_name,
        "density_preset": _density_name,
        "density_cfg": density_cfg,
        "assistant_name": _assistant_name,
        "assistant_tone": _assistant_tone,

        "tool_web_search_enabled": bool(ui_prefs.get("tool_web_search_enabled", True)),
        "tool_fs_enabled": bool(ui_prefs.get("tool_fs_enabled", True)),
        "session_tokens": 0,
        "session_gen_time_ms": 0,
        "streaming": False,
        "cancel_event": threading.Event(),

        "strip_emoji": False,

        "chat_scroll_index": 0,

        "model_dropdown_updating": False,
        "switching_model": False,
    }

    active_stream = {"response": None}
    active_stream_lock = threading.Lock()
    composer_outer_ref = {"value": None}
    backend_tools = ui_backend_tools.BackendTools(SEARCH_API_URL, _format_bytes)
    shell_colors = {
        "BG": BG,
        "SIDEBAR_BG": SIDEBAR_BG,
        "SURFACE": SURFACE,
        "SURFACE_ALT": SURFACE_ALT,
        "BORDER": BORDER,
        "TEXT_PRIMARY": TEXT_PRIMARY,
        "TEXT_MUTED": TEXT_MUTED,
    }


    def show_snack(message, color=style.ACCENT):

        page.snack_bar = ft.SnackBar(ft.Text(message, color=style.TEXT_PRIMARY), bgcolor=color)
        page.snack_bar.open = True
        page.update()

    def open_markdown_link(e):
        url = getattr(e, "data", None) or ""
        if not url:
            return
        try:
            page.launch_url(url)
        except Exception as exc:
            show_snack(f"Unable to open link: {exc}", DANGER)

    def _render_markdown(md_text: str):
        return ui_markdown.render_markdown(
            page=page,
            md_text=md_text or "",
            open_link_handler=open_markdown_link,
            show_snack=show_snack,
            colors=shell_colors,
            success_color=SUCCESS,
            danger_color=DANGER,
        )

    strip_prompt_echo = ui_markdown.strip_prompt_echo


    model_status_dot = ft.Container(width=12, height=12, bgcolor=style.SURFACE_ALT, border_radius=6)
    search_status_dot = ft.Container(width=12, height=12, bgcolor=style.SURFACE_ALT, border_radius=6)

    def make_telemetry_pill(label: str):

        label_text = ft.Text(label, size=11, color=style.status_text_color("idle"), weight=ft.FontWeight.W_600)
        value_text = ft.Text("--", size=12, color=style.status_text_color("idle"), weight=ft.FontWeight.W_700)
        pill = ft.Container(
            padding=ft.padding.symmetric(horizontal=10, vertical=6),
            bgcolor=style.status_color("idle"),
            border_radius=999,
            content=ft.Row([label_text, value_text], spacing=6, tight=True),
        )
        pill.data = {"label_text": label_text, "value_text": value_text}
        return pill

    power_pill = make_telemetry_pill("PWR")
    ram_pill = make_telemetry_pill("RAM")
    cpu_pill = make_telemetry_pill("CPU")
    temp_pill = make_telemetry_pill("TEMP")
    vram_pill = make_telemetry_pill("VRAM")


    chat_list = ft.ListView(
        expand=True,
        spacing=int(density_cfg.get("chat_spacing", 14) or 14),
        padding=int(density_cfg.get("chat_padding", 12) or 12),
        auto_scroll=True,
    )
    empty_state = ft.Container(
        expand=True,
        alignment=ft.alignment.center,
        content=ft.Text("What can I help with?", size=34, weight=ft.FontWeight.W_700, color=style.TEXT_PRIMARY),
        visible=True,
    )

    def update_empty_state():
        empty_state.visible = not bool(state["messages"])

    input_field = ft.TextField(
        hint_text="Message",
        multiline=True,
        min_lines=1,
        max_lines=8,
        expand=True,
        filled=True,
        bgcolor=style.SURFACE,
        border_color=style.BORDER,
        focused_border_color=style.BORDER,
        text_style=ft.TextStyle(color=style.TEXT_PRIMARY),
        hint_style=ft.TextStyle(color=style.TEXT_MUTED),
        content_padding=ft.padding.symmetric(horizontal=14, vertical=10),
        border_radius=16,
    )
    primary_button_style = ft.ButtonStyle(
        bgcolor=style.ACCENT,
        color=style.SURFACE,
        padding=ft.padding.symmetric(horizontal=16, vertical=12),
        shape=ft.RoundedRectangleBorder(radius=12),
    )
    secondary_button_style = ft.ButtonStyle(
        color=style.TEXT_PRIMARY,
        bgcolor=style.SURFACE,
        padding=ft.padding.symmetric(horizontal=16, vertical=12),
        shape=ft.RoundedRectangleBorder(radius=12),
        side=ft.BorderSide(1, style.BORDER),
    )

    attach_button = ft.IconButton(
        icon=ft.icons.ATTACH_FILE,
        tooltip="Add files",
        icon_color=style.TEXT_PRIMARY,
    )
    stop_button = ft.IconButton(
        icon=ft.icons.STOP_CIRCLE_OUTLINED,
        tooltip="Stop",
        disabled=True,
        icon_color=style.TEXT_PRIMARY,
    )
    send_button = ft.IconButton(
        icon=ft.icons.SEND,
        tooltip="Send",
        disabled=True,
        icon_color=style.SURFACE,
        bgcolor=style.ACCENT,
    )
    generating_label = ft.Text("Generating...", size=12, color=style.TEXT_MUTED)
    generating_spinner = ft.ProgressRing(width=16, height=16, stroke_width=2, color=style.ACCENT)
    generating_row = ft.Row([generating_spinner, generating_label], spacing=8, visible=False)

    perf_label = ft.Text("TTFT: - | Gen: - | chars: - | tokens: -", size=12, color=style.TEXT_MUTED)
    tps_label = ft.Text("Session TPS: --", size=12, color=style.TEXT_MUTED)
    context_label = ft.Text("Context: --", size=11, color=TEXT_MUTED)
    context_bar = ft.ProgressBar(value=0.0, height=6, expand=True, color=ACCENT, bgcolor=SURFACE_ALT)

    docs_list = ft.Row(spacing=8, wrap=True)
    docs_status_label = ft.Text("No files attached", size=11, color=style.TEXT_MUTED)
    clear_docs_button = ft.OutlinedButton("Clear docs", disabled=True, style=secondary_button_style)
    docs_row = ft.Row([docs_list, clear_docs_button], spacing=8, wrap=True, visible=False)
    perf_row = ft.Row([perf_label, tps_label], spacing=12, visible=True)
    context_row = ft.Row([context_label, context_bar], spacing=10, visible=True)


    assistant_name_field = ft.TextField(
        label="Assistant name",
        value=str(state.get("assistant_name") or "Assistant"),
        width=260,
    )
    assistant_tone_field = ft.TextField(
        label="Assistant tone",
        value=str(state.get("assistant_tone") or "helpful"),
        width=420,
    )
    temperature_field = ft.TextField(label="Temperature", value=str(ui_prefs.get("temperature", "0.7")), width=140)
    max_tokens_field = ft.TextField(label="Max Tokens", value=str(ui_prefs.get("max_tokens", "1024")), width=140)
    top_p_field = ft.TextField(label="Top P", value=str(ui_prefs.get("top_p", "0.95")), width=140)
    top_k_field = ft.TextField(label="Top K", value=str(ui_prefs.get("top_k", "40")), width=140)


    stop_sequences_field = ft.TextField(
        label="Stop Sequences (comma separated)",
        value=str(ui_prefs.get("stop_sequences", "USER:, \\nUSER:, <|user|>")),
        multiline=True,
        min_lines=1,
        max_lines=3,
        width=720,
    )
    state["strip_emoji"] = False
    theme_dropdown = ft.Dropdown(
        label="Theme preset",
        width=220,
        options=[ft.dropdown.Option(k, k) for k in THEME_PRESETS.keys()],
        value=str(state.get("theme_preset") or "Obsidian"),
    )
    density_dropdown = ft.Dropdown(
        label="Density",
        width=220,
        options=[ft.dropdown.Option(k, k) for k in DENSITY_PRESETS.keys()],
        value=str(state.get("density_preset") or "Comfortable"),
    )
    appearance_apply_button = ft.IconButton(
        icon=ft.icons.CHECK_CIRCLE_OUTLINED,
        tooltip="Apply appearance",
        icon_color=ACCENT,
    )
    model_dir_label = ft.Text("Model directory: --", size=12, color=style.TEXT_MUTED)
    files_dir_label = ft.Text("File tool directory: --", size=12, color=style.TEXT_MUTED)
    backend_settings_note_models = ft.Text("", size=11, color=style.TEXT_MUTED)
    backend_settings_note_settings = ft.Text("", size=11, color=style.TEXT_MUTED)


    tool_web_search_switch = ft.Switch(label="Enable web search (web_search)", value=bool(state["tool_web_search_enabled"]))
    tool_fs_switch = ft.Switch(label="Enable file tools (fs_list/fs_read/fs_write/fs_search)", value=bool(state["tool_fs_enabled"]))
    web_search_backoff_label = ft.Text("", size=11, color=WARNING, visible=False)

    tool_files_max_bytes_field = ft.TextField(label="File tool max bytes", value="", width=200)
    tool_files_max_bytes_apply_button = ft.IconButton(
        icon=ft.icons.CHECK_CIRCLE_OUTLINED,
        tooltip="Apply file tool limit",
        icon_color=ACCENT,
    )


    llama_args_field = ft.TextField(
        label="llama-server args (LLAMA_ARGS)",
        value="",
        multiline=True,
        min_lines=2,
        max_lines=4,
        width=720,
    )
    llama_args_apply_button = ft.IconButton(
        icon=ft.icons.CHECK_CIRCLE_OUTLINED,
        tooltip="Save llama args",
        icon_color=ACCENT,
    )
    llama_args_restart_switch = ft.Switch(label="Restart model server after saving", value=True)
    llama_args_note = ft.Text(
        "Tip: include --ctx-size N to change context length. Server restart required to apply.",
        size=11,
        color=TEXT_MUTED,
    )
    llama_status_label = ft.Text("Server: --", size=11, color=TEXT_MUTED, selectable=True)
    llama_running_args_label = ft.Text("Running LLAMA_ARGS: --", size=11, color=TEXT_MUTED, selectable=True)
    llama_cmdline_label = ft.Text("Cmdline: --", size=11, color=TEXT_MUTED, selectable=True)
    llama_restart_needed_label = ft.Text("", size=11, color=WARNING, visible=False)


    autostart_model_switch = ft.Switch(label="Autostart last model on launch", value=True)


    power_idle_field = ft.TextField(label="Power idle (W)", value="", width=160)
    power_max_field = ft.TextField(label="Power max (W)", value="", width=160)
    power_apply_button = ft.IconButton(
        icon=ft.icons.CHECK_CIRCLE_OUTLINED,
        tooltip="Apply telemetry calibration",
        icon_color=ACCENT,
    )

    _prefs_timer = {"timer": None}

    def save_ui_prefs_now():


        export_fmt = "json"
        try:
            dd = globals().get("export_format_dropdown")
            export_fmt = str(getattr(dd, "value", None) or ui_prefs.get("export_format") or "json")
        except Exception:
            export_fmt = str(ui_prefs.get("export_format") or "json")
        prefs = {
            "assistant_name": str(assistant_name_field.value or "").strip(),
            "assistant_tone": str(assistant_tone_field.value or "").strip(),
            "temperature": temperature_field.value,
            "max_tokens": max_tokens_field.value,
            "top_p": top_p_field.value,
            "top_k": top_k_field.value,
            "stop_sequences": stop_sequences_field.value,
            "theme_preset": str(state.get("theme_preset") or "Obsidian"),
            "density_preset": str(state.get("density_preset") or "Comfortable"),
            "tool_web_search_enabled": bool(state.get("tool_web_search_enabled", True)),
            "tool_fs_enabled": bool(state.get("tool_fs_enabled", True)),
            "export_format": export_fmt,
        }
        try:
            ui_prefs_io.save_ui_prefs(UI_PREFS_FILE, prefs)
        except Exception:
            pass

    def refresh_assistant_name_labels():
        raw_name = str(state.get("assistant_name") or "Assistant").strip()
        safe_name = " ".join(raw_name.split())[:80] or "Assistant"
        changed = False
        for msg in state.get("messages") or []:
            if msg.get("role") != "model":
                continue
            lbl = msg.get("name_label")
            if isinstance(lbl, ft.Text):
                if lbl.value != safe_name:
                    lbl.value = safe_name
                    changed = True
                    try:
                        lbl.update()
                    except Exception:
                        pass
        if changed:
            try:
                page.update()
            except Exception:
                pass

    def schedule_save_ui_prefs():
        t = _prefs_timer.get("timer")
        if t is not None:
            try:
                t.cancel()
            except Exception:
                pass

        def run():
            save_ui_prefs_now()

        _prefs_timer["timer"] = threading.Timer(0.2, run)
        _prefs_timer["timer"].daemon = True
        _prefs_timer["timer"].start()


    model_dropdown = ft.Dropdown(label="Model", options=[], width=280)
    refresh_models_button = ft.IconButton(icon=ft.icons.REFRESH, tooltip="Refresh models", icon_color=style.TEXT_PRIMARY)
    switch_model_button = ft.IconButton(icon=ft.icons.CHECK_CIRCLE_OUTLINED, tooltip="Switch model", icon_color=style.ACCENT)
    palette_button = ft.IconButton(icon=ft.icons.SEARCH, tooltip="Command palette (Ctrl+K)", icon_color=style.TEXT_PRIMARY)
    model_status_text = ft.Text("", color=style.TEXT_MUTED)
    current_model_info = ft.Text("File: --\nName: --\nArch: --\nQuant: --\nSize: --", size=12, color=TEXT_PRIMARY, selectable=True)
    llama_ctx_label = ft.Text("Server context: --", size=12, color=style.TEXT_MUTED)
    ctx_size_field = ft.TextField(label="Context length (n_ctx)", value="8192", width=200)
    ctx_apply_button = ft.OutlinedButton("Apply + restart", style=secondary_button_style)

    def on_model_dropdown_change(_=None):
        if state.get("model_dropdown_updating"):
            return
        switch_model()
    model_dropdown.on_change = on_model_dropdown_change
    model_switch_spinner = ft.ProgressRing(width=12, height=12, stroke_width=2, color=WARNING, visible=False)


    sessions_list = ft.ListView(expand=True, spacing=6, padding=10)
    sidebar_sessions_list = ft.ListView(expand=True, spacing=2, padding=6)
    session_filter_field = ft.TextField(
        hint_text="Search chats",
        filled=True,
        bgcolor=SURFACE,
        border_color=BORDER,
        focused_border_color=BORDER,
        text_style=ft.TextStyle(color=TEXT_PRIMARY, size=12),
        hint_style=ft.TextStyle(color=TEXT_MUTED, size=12),
    )
    save_session_button = ft.ElevatedButton("Save session", style=primary_button_style)
    load_session_button = ft.OutlinedButton("Load selected", disabled=True, style=secondary_button_style)
    delete_session_button = ft.OutlinedButton("Delete selected", disabled=True, style=secondary_button_style)
    export_session_button = ft.OutlinedButton("Export session", style=secondary_button_style)
    import_session_button = ft.OutlinedButton("Import session", style=secondary_button_style)
    export_format_dropdown = ft.Dropdown(
        label="Export format",
        width=200,
        options=[
            ft.dropdown.Option("json", "JSON"),
            ft.dropdown.Option("md", "Markdown"),
            ft.dropdown.Option("txt", "Text"),
            ft.dropdown.Option("html", "HTML"),
        ],
        value=str(ui_prefs.get("export_format") or "json"),
    )
    session_name_input = ft.TextField(label="Selected session", read_only=True, expand=True)
    export_dir_label = ft.Text("Export folder: (not set)", size=12, color=style.TEXT_MUTED)
    import_dir_label = ft.Text("Import folder: (not set)", size=12, color=style.TEXT_MUTED)
    import_file_dropdown = ft.Dropdown(label="Session file", options=[], expand=True)


    keyboard_last_event_label = ft.Text("Last key: --", size=12, color=TEXT_MUTED, selectable=True)


    file_picker = None
    dir_picker = None
    try:
        file_picker = ft.FilePicker()
        page.overlay.append(file_picker)
    except Exception:
        file_picker = None
    try:
        dir_picker = ft.FilePicker()
        page.overlay.append(dir_picker)
    except Exception:
        dir_picker = None
    selected_session_id = {"value": None}
    export_dir = {"value": ""}
    import_dir = {"value": ""}
    model_dir = {"value": ""}
    dir_picker_target = {"value": None}

    def update_send_state():
        can_send = bool(input_field.value.strip() or state["loaded_documents"])
        is_streaming = state["streaming"]
        is_cancelling = state["cancel_event"].is_set()
        model_ok = bool(state.get("model_ready"))
        send_button.disabled = (not can_send) or is_streaming or (not model_ok)
        stop_button.disabled = (not is_streaming) or is_cancelling

        send_button.bgcolor = BORDER if send_button.disabled else ACCENT
        send_button.icon_color = TEXT_MUTED if send_button.disabled else SURFACE
        stop_button.icon_color = TEXT_MUTED if stop_button.disabled else TEXT_PRIMARY
        if send_button.disabled and (not model_ok):
            send_button.tooltip = "Model not ready"
        else:
            send_button.tooltip = "Send"
        generating_row.visible = is_streaming
        generating_label.value = "Stopping..." if is_cancelling else "Generating..."


        for ctl in (send_button, stop_button, generating_row):
            try:
                ctl.update()
            except AssertionError:
                pass
            except Exception:
                pass

    def update_details_visibility():


        docs_row.visible = bool(state["loaded_documents"])
        perf_row.visible = True

        docs_status_label.visible = True
        docs_row.update()
        perf_row.update()
        docs_status_label.update()

    def update_doc_list():
        docs_list.controls.clear()
        for doc in state["loaded_documents"]:
            label = f"{doc['name']} ({_format_bytes(doc['size'])})"
            if doc.get("error"):
                label = f"{doc['name']} (error)"
            chip = ft.Container(
                padding=ft.padding.symmetric(horizontal=10, vertical=6),
                bgcolor=SURFACE_ALT,
                border_radius=999,
                border=ft.border.all(1, BORDER),
                content=ft.Text(label, size=11, color=TEXT_PRIMARY),
            )
            docs_list.controls.append(chip)
        clear_docs_button.disabled = not state["loaded_documents"]
        if state["loaded_documents"]:
            docs_status_label.value = f"{len(state['loaded_documents'])} file(s) attached"
        else:
            docs_status_label.value = "No files attached"
        update_details_visibility()
        update_send_state()
        try:
            schedule_context_stats_update()
        except Exception:
            pass

    def _estimate_tokens(s: str) -> int:
        return ui_prompt.estimate_tokens(s or "", CHARS_PER_TOKEN)

    def add_message(role, content, llm_content=None, search_results=None, timestamp=None, tool_name=None, show_in_chat: bool = True):
        ts = timestamp or time.strftime("%H:%M")
        display_content = None
        display_raw = None
        name_label = None

        def _window_width():
            w = getattr(getattr(page, "window", None), "width", None)
            if isinstance(w, (int, float)) and w > 0:
                return int(w)
            return int(getattr(page, "window_width", 1100) or 1100)

        def content_width():

            width = _window_width()
            sidebar_w = SIDEBAR_WIDTH
            try:
                if not sidebar_container.visible:
                    sidebar_w = 0
            except Exception:
                pass
            available = width - sidebar_w - 90
            if available < CHAT_MIN_WIDTH:
                available = width - 40
            return min(CHAT_MAX_WIDTH, max(CHAT_MIN_WIDTH, int(available)))

        def avatar(label, bgcolor, fg):
            return ft.Container(
                width=28,
                height=28,
                bgcolor=bgcolor,
                border_radius=14,
                alignment=ft.alignment.center,
                content=ft.Text(label, size=10, weight=ft.FontWeight.W_700, color=fg),
                border=ft.border.all(1, BORDER),
            )

        dens = state.get("density_cfg") or {}
        bubble_pad = int(dens.get("bubble_padding", 14) or 14)
        meta_gap = int(dens.get("meta_gap", 4) or 4)
        outer_pad_v = int(dens.get("outer_pad_v", 6) or 6)

        max_w = content_width()
        outer = ft.Container(width=max_w, padding=ft.padding.symmetric(horizontal=12, vertical=outer_pad_v))
        token_label = None
        bubble_ref = None

        def user_bubble_width(max_width: int) -> int:


            try:
                w = int(max_width)
            except Exception:
                w = 760
            return max(240, min(w, int(w * 0.82)))

        if role == "user":
            bubble = ft.Container(
                bgcolor=SURFACE,
                border_radius=18,
                padding=bubble_pad,
                border=ft.border.all(1, BORDER),
                width=user_bubble_width(max_w),
                content=ft.Text(content, color=TEXT_PRIMARY, selectable=True, no_wrap=False),
            )
            bubble_ref = bubble
            tokens = _estimate_tokens(str(content or ""))
            token_label = ft.Text(f"~{tokens} tok", size=10, color=TEXT_MUTED)
            wrapper = ft.Column(
                [bubble, token_label],
                spacing=meta_gap,
                horizontal_alignment=ft.CrossAxisAlignment.END,
            )
            outer.content = ft.Row([wrapper], alignment=ft.MainAxisAlignment.END)
            text_control = None
        elif role in ("search", "tool"):
            header = "Web search" if (role == "search" or tool_name == "web_search") else "Tool"
            if tool_name and tool_name.startswith("fs_"):
                header = "File system"
            expanded_by_default = bool(role == "search" or tool_name in ("web_search",))
            expanded = {"value": expanded_by_default}
            toggle_btn = ft.IconButton(
                icon=ft.icons.EXPAND_LESS if expanded_by_default else ft.icons.EXPAND_MORE,
                tooltip="Collapse" if expanded_by_default else "Expand",
                icon_color=TEXT_MUTED,
            )
            bubble = ft.Container(
                bgcolor=SURFACE_ALT,
                border_radius=14,
                padding=12,
                border=ft.border.all(1, BORDER),
                content=ft.Column(
                    [
                        ft.Row(
                            [
                                ft.Text(header, size=11, weight=ft.FontWeight.W_600, color=TEXT_MUTED),
                                ft.Container(expand=True),
                                toggle_btn,
                            ],
                            spacing=6,
                            vertical_alignment=ft.CrossAxisAlignment.CENTER,
                        ),
                        ft.Container(
                            content=_render_markdown(content or ""),
                            visible=expanded_by_default,
                        ),
                    ],
                    spacing=6,
                ),
            )
            body_container = bubble.content.controls[1]
            def toggle_tool_body(_=None):
                expanded["value"] = not expanded["value"]
                body_container.visible = bool(expanded["value"])
                toggle_btn.icon = ft.icons.EXPAND_LESS if expanded["value"] else ft.icons.EXPAND_MORE
                toggle_btn.tooltip = "Collapse" if expanded["value"] else "Expand"
                bubble.update()
            toggle_btn.on_click = toggle_tool_body
            bubble_ref = bubble
            outer.content = ft.Row([bubble], alignment=ft.MainAxisAlignment.START)
            text_control = None
        else:
            raw_content = content or ""
            content = raw_content
            cleaned = strip_prompt_echo(raw_content)
            display_raw = _strip_emoji(raw_content) if state["strip_emoji"] else raw_content
            display_content = _strip_emoji(cleaned) if state["strip_emoji"] else cleaned

            text_control = ft.Text(display_content or "", color=TEXT_PRIMARY, selectable=True)
            content_block = ft.Container(
                padding=ft.padding.only(top=2, bottom=2),
                content=text_control,
            )
            token_label = ft.Text(f"~{_estimate_tokens(display_content or '')} tok", size=10, color=TEXT_MUTED)
            raw_name = str(state.get("assistant_name") or "Assistant").strip()
            safe_name = " ".join(raw_name.split())[:80] or "Assistant"
            name_label = ft.Text(safe_name, size=11, weight=ft.FontWeight.W_600, color=TEXT_MUTED)
            outer.content = ft.Row(
                [
                    avatar("AI", ACCENT_SOFT, ACCENT),
                    ft.Column(
                        [
                            ft.Row(
                                [
                                    name_label,
                                    ft.Container(expand=True),
                                    token_label,
                                ],
                                spacing=6,
                                vertical_alignment=ft.CrossAxisAlignment.CENTER,
                            ),
                            content_block,
                        ],
                        spacing=6,
                        expand=True,
                    ),
                ],
                spacing=12,
                alignment=ft.MainAxisAlignment.START,
                vertical_alignment=ft.CrossAxisAlignment.START,
            )

        row = ft.Row([outer], alignment=ft.MainAxisAlignment.CENTER)
        msg = {
            "role": role,
            "content": content,
            "display_content": display_content if role == "model" else None,
            "display_raw": display_raw if role == "model" else None,


            "tool_call_raw": None,
            "llm_content": llm_content,
            "control": text_control,
            "content_block": content_block if role == "model" else None,
            "render_mode": "text" if role == "model" else None,
            "outer": outer,
            "bubble": bubble_ref,
            "name_label": name_label,
            "token_label": token_label,
            "search_results": search_results,
            "timestamp": ts,
            "tool_name": tool_name,
        }
        state["messages"].append(msg)
        if show_in_chat:
            update_empty_state()
            chat_list.controls.append(row)
            page.update()
        try:
            schedule_context_stats_update()
        except Exception:
            pass
        return msg

    def format_prompt(messages=None):
        return ui_prompt.format_prompt(state, messages)

    def update_perf_stats(ttft, gen_seconds, chars, tokens):
        perf_label.value = f"TTFT: {ttft} | Gen: {gen_seconds:.2f}s | chars: {chars} | tokens: {tokens}"
        if state["session_gen_time_ms"] > 0 and state["session_tokens"] > 0:
            tps = state["session_tokens"] / (state["session_gen_time_ms"] / 1000)
            tps_label.value = f"Session TPS: {tps:.2f} ({state['session_tokens']} tok)"
        else:
            tps_label.value = "Session TPS: --"

    def reset_perf_stats():
        perf_label.value = "TTFT: - | Gen: - | chars: - | tokens: -"
        tps_label.value = "Session TPS: --"

    def build_context_block(user_text, consume_search: bool = True):
        block, out_pending = ui_prompt.build_context_block(
            loaded_documents=state.get("loaded_documents") or [],
            pending_search_contexts=state.get("pending_search_contexts") or [],
            user_text=(user_text or ""),
            max_text_file_embed_size=MAX_TEXT_FILE_EMBED_SIZE,
            consume_search=consume_search,
        )
        if consume_search:
            state["pending_search_contexts"] = out_pending
        return block

    _ctx_stats_timer = {"timer": None}

    def update_context_stats(_=None):

        user_text = (input_field.value or "").strip()
        has_user_block = bool(user_text or state.get("loaded_documents") or state.get("pending_search_contexts"))
        ts = time.strftime("%H:%M")
        preview_msgs = list(state["messages"])
        if has_user_block:
            ctx_text = build_context_block(user_text, consume_search=False)
            preview_msgs = preview_msgs + [{"role": "user", "content": user_text, "llm_content": ctx_text, "timestamp": ts}]
        prompt = format_prompt(preview_msgs)
        approx_tokens = _estimate_tokens(prompt)

        ctx_size = state.get("ctx_size")
        if not isinstance(ctx_size, int) or ctx_size <= 0:
            raw = (ctx_size_field.value or "").strip()
            try:
                ctx_size = int(raw)
            except Exception:
                ctx_size = None

        if isinstance(ctx_size, int) and ctx_size > 0:
            frac = max(0.0, min(1.0, approx_tokens / float(ctx_size)))
            context_bar.value = frac
            if frac >= 0.90:
                context_bar.color = DANGER
            elif frac >= 0.75:
                context_bar.color = WARNING
            else:
                context_bar.color = ACCENT
            context_label.value = f"Context: ~{approx_tokens} tok / {ctx_size} ({int(frac * 100)}%)"
        else:
            context_bar.value = 0.0
            context_bar.color = ACCENT
            context_label.value = f"Context: ~{approx_tokens} tok / --"
        try:
            context_row.update()
        except Exception:
            page.update()

    def schedule_context_stats_update():
        t = _ctx_stats_timer.get("timer")
        if t is not None:
            try:
                t.cancel()
            except Exception:
                pass

        def run():
            _ui_call(page, update_context_stats)

        _ctx_stats_timer["timer"] = threading.Timer(0.25, run)
        _ctx_stats_timer["timer"].daemon = True
        _ctx_stats_timer["timer"].start()

    def send_message(_=None):
        chat_controller.send_message(
            chat_controller.ChatContext(
                page=page,
                state=state,
                input_field=input_field,
                max_tokens_field=max_tokens_field,
                temperature_field=temperature_field,
                top_p_field=top_p_field,
                top_k_field=top_k_field,
                stop_sequences_field=stop_sequences_field,
                perf_row=perf_row,
                text_muted=TEXT_MUTED,
                surface=SURFACE,
                warning=WARNING,
                danger=DANGER,
                secondary_button_style=secondary_button_style,
                model_server_url=MODEL_SERVER_URL,
                stream_connect_timeout_s=STREAM_CONNECT_TIMEOUT_S,
                stream_read_timeout_s=STREAM_READ_TIMEOUT_S,
                ui_call=_ui_call,
                show_snack=show_snack,
                update_send_state=update_send_state,
                update_perf_stats=update_perf_stats,
                add_message=add_message,
                build_context_block=build_context_block,
                format_prompt=format_prompt,
                render_markdown=_render_markdown,
                estimate_tokens=_estimate_tokens,
                strip_prompt_echo=strip_prompt_echo,
                parse_tool_call=_parse_tool_call,
                extract_first_json_object=getattr(text, '_extract_first_json_object', None),
                strip_emoji=_strip_emoji,
                backend_tools=backend_tools,
                chars_per_token=CHARS_PER_TOKEN,
                active_stream=active_stream,
                active_stream_lock=active_stream_lock,
            )
        )

    def stop_stream(_=None):
        if not state["streaming"]:
            return
        if state["cancel_event"].is_set():
            return
        state["cancel_event"].set()

        with active_stream_lock:
            resp = active_stream.get("response")
        if resp is not None:
            try:
                resp.close()
            except Exception:
                pass

        try:
            requests.post(f"{MODEL_SERVER_URL}/cancel", timeout=0.2)
        except Exception:
            pass
        update_send_state()

    def add_document_from_path(path):
        if not path:
            return
        if not os.path.exists(path):
            show_snack(f"File not found: {path}", DANGER)
            return
        file_path = Path(path)
        doc = {
            "name": file_path.name,
            "path": str(file_path),
            "size": file_path.stat().st_size,
            "type": file_path.suffix.lower(),
            "content": "",
            "error": None,
        }
        suffix = doc["type"]
        try:
            if suffix == ".pdf":
                doc["content"] = _read_pdf_file(file_path)
            elif suffix == ".docx":
                doc["content"] = _read_docx_file(file_path)
            elif suffix == ".csv":
                doc["content"] = _read_csv_file(file_path)
            elif suffix in (".txt", ".md", ".py", ".js", ".ts", ".html", ".css", ".json", ".xml", ".log", ".cpp", ".c", ".hpp", ".h", ".java", ".go", ".rs"):
                doc["content"] = _read_text_file(file_path)
            else:
                doc["content"] = ""
        except Exception as exc:
            doc["error"] = str(exc)
        state["loaded_documents"].append(doc)

    def handle_files(result):
        paths, error_docs = filepicker_utils.normalize_file_picker_result(result)
        if error_docs:


            state["loaded_documents"].extend(error_docs)
            try:
                print(f"[filepicker] {len(error_docs)} item(s) missing readable path")
            except Exception:
                pass

        for path in paths:
            add_document_from_path(path)
        update_doc_list()
        page.update()

    if file_picker:
        file_picker.on_result = handle_files

    def update_import_files():
        path = import_dir["value"]
        options = []
        import_file_dropdown.value = None
        if path and os.path.isdir(path):
            for item in sorted(Path(path).glob("*.json")):
                options.append(ft.dropdown.Option(str(item), item.name))
        import_file_dropdown.options = options

    def handle_dir_pick(result):
        path = getattr(result, "path", None)
        if not path:
            return
        target = dir_picker_target["value"]
        if target == "export":
            export_dir["value"] = path
            export_dir_label.value = f"Export folder: {path}"
        elif target == "import":
            import_dir["value"] = path
            import_dir_label.value = f"Import folder: {path}"
            update_import_files()
        elif target == "model_dir":
            try:
                resp = requests.post(
                    f"{SEARCH_API_URL}/models/dir",
                    json={"path": path},
                    timeout=10,
                )
                resp.raise_for_status()
                data = resp.json()
                if not data.get("success", True):
                    show_snack(data.get("message", "Failed to update model directory."), DANGER)
                else:
                    model_dir["value"] = data.get("model_dir", path)
                    model_dir_label.value = f"Model directory: {model_dir['value']}"
                    refresh_models()
                    show_snack("Model directory updated.", SUCCESS)
            except Exception as exc:
                show_snack(f"Failed to update model directory: {exc}", DANGER)
        elif target == "files_dir":
            try:
                resp = requests.post(
                    f"{SEARCH_API_URL}/files/dir",
                    json={"path": path, "create": True},
                    timeout=10,
                )
                resp.raise_for_status()
                data = resp.json()
                if not data.get("success", True):
                    show_snack(data.get("message", "Failed to update file tool directory."), DANGER)
                else:
                    state["files_tool_dir"] = data.get("files_dir", path) or path
                    writable = data.get("writable")
                    suffix = ""
                    if writable is True:
                        suffix = " (writable)"
                    elif writable is False:
                        suffix = " (read-only)"
                    files_dir_label.value = f"File tool directory: {state['files_tool_dir']}{suffix}"
                    show_snack("File tool directory updated.", SUCCESS)
            except Exception as exc:
                show_snack(f"Failed to update file tool directory: {exc}", DANGER)
        page.update()

    if dir_picker:
        dir_picker.on_result = handle_dir_pick

    def clear_docs(_=None):
        state["loaded_documents"] = []
        update_doc_list()
        page.update()

    def refresh_models(_=None):
        try:
            resp = requests.get(f"{SEARCH_API_URL}/models", timeout=10)
            resp.raise_for_status()
            data = resp.json()
            options = []
            current = data.get("current_model")
            state["model_dropdown_updating"] = True
            try:
                for model in data.get("models", []):
                    label = model["name"]
                    if model.get("is_current"):
                        label = f"★ {label}"
                    options.append(ft.dropdown.Option(model["path"], label))
                    if model.get("is_current"):
                        model_dropdown.value = model["path"]
                model_dropdown.options = options
                model_dropdown.update()
            finally:
                state["model_dropdown_updating"] = False
            cur = None
            for m in data.get("models", []) or []:
                if m.get("is_current"):
                    cur = m
                    break
            if cur is None and current:
                for m in data.get("models", []) or []:
                    if m.get("path") == current or m.get("name") == current:
                        cur = m
                        break
            if cur:
                file_name = cur.get("name") or "--"
                gguf_name = cur.get("gguf_model_name") or "--"
                arch = cur.get("gguf_architecture") or "--"
                quant = cur.get("quantization") or "--"
                size_txt = cur.get("size_human") or "--"
                current_model_info.value = f"File: {file_name}\nName: {gguf_name}\nArch: {arch}\nQuant: {quant}\nSize: {size_txt}"
            else:
                current_model_info.value = "File: --\nName: --\nArch: --\nQuant: --\nSize: --"
            model_dir_value = data.get("model_dir", "")
            model_dir["value"] = model_dir_value
            model_status_text.value = f"Model dir: {model_dir_value}"
            model_dir_label.value = f"Model directory: {model_dir_value}" if model_dir_value else "Model directory: --"

            try:
                r2 = requests.get(f"{SEARCH_API_URL}/llama/ctx", timeout=5)
                if r2.ok:
                    d2 = r2.json() or {}
                    ctx = d2.get("ctx_size")
                    if isinstance(ctx, (int, float)) and ctx:
                        ctx_i = int(ctx)
                        state["ctx_size"] = int(ctx_i)
                        llama_ctx_label.value = f"Server context: {ctx_i}"
                        cur = (ctx_size_field.value or "").strip()
                        if cur in ("", "8192", str(ctx_i)):
                            ctx_size_field.value = str(ctx_i)
                    else:
                        llama_ctx_label.value = "Server context: --"
            except Exception:
                pass
        except Exception as exc:
            model_status_text.value = f"Error loading models: {exc}"
        page.update()
        try:
            schedule_context_stats_update()
        except Exception:
            pass

    def refresh_files_dir(_=None):
        try:
            resp = requests.get(f"{SEARCH_API_URL}/files/dir", timeout=10)
            resp.raise_for_status()
            data = resp.json()
            files_dir = data.get("files_dir") or ""
            state["files_tool_dir"] = files_dir
            writable = data.get("writable")
            if files_dir:
                suffix = ""
                if writable is True:
                    suffix = " (writable)"
                elif writable is False:
                    suffix = " (read-only)"
                files_dir_label.value = f"File tool directory: {files_dir}{suffix}"
            else:
                files_dir_label.value = "File tool directory: --"
        except Exception as exc:
            files_dir_label.value = f"File tool directory: (error: {exc})"
        page.update()

    backend_refresh_guard = {"value": False}

    def refresh_backend_settings(_=None):
        try:
            resp = requests.get(f"{SEARCH_API_URL}/settings", timeout=10)
            resp.raise_for_status()
            payload = resp.json() or {}
            s = payload.get("settings") or {}
            backend_refresh_guard["value"] = True
            try:

                autostart_model_switch.value = bool(s.get("autostart_model", True))


                if "llama_args" in s:
                    llama_args_field.value = str(s.get("llama_args") or "")


                if "power_idle_watts" in s:
                    power_idle_field.value = str(s.get("power_idle_watts"))
                if "power_max_watts" in s:
                    power_max_field.value = str(s.get("power_max_watts"))


                try:
                    state["tool_files_max_bytes"] = int(s.get("tool_files_max_bytes") or state.get("tool_files_max_bytes") or 200000)
                except Exception:
                    state["tool_files_max_bytes"] = int(state.get("tool_files_max_bytes") or 200000)
                tool_files_max_bytes_field.value = str(state["tool_files_max_bytes"])

                settings_file = payload.get("settings_file") or ""
                note_txt = f"Backend settings: {settings_file}" if settings_file else "Backend settings: --"
                backend_settings_note_models.value = note_txt
                backend_settings_note_settings.value = note_txt


                try:
                    r3 = requests.get(f"{SEARCH_API_URL}/llama/status", timeout=5)
                    if r3.ok:
                        d3 = r3.json() or {}
                        running = bool(d3.get("running", False))
                        pid = d3.get("pid")
                        model = d3.get("model") or "--"
                        running_args = (d3.get("llama_args_running") or "").strip()
                        configured_args = (d3.get("llama_args_configured") or (s.get("llama_args") or "")).strip()
                        cmdline = (d3.get("cmdline") or "").strip()
                        ctx_run = d3.get("ctx_size_running")
                        ctx_cfg = d3.get("ctx_size_configured")
                        llama_status_label.value = f"Server: {'running' if running else 'stopped'} | PID: {pid or '--'} | ctx: {ctx_run or '--'} (cfg {ctx_cfg or '--'})"
                        llama_running_args_label.value = f"Running LLAMA_ARGS: {running_args or '--'}"
                        cmd_short = (cmdline[:300] + "...") if (cmdline and len(cmdline) > 300) else (cmdline or "--")
                        llama_cmdline_label.value = f"Cmdline: {cmd_short}"
                        if running and configured_args and running_args and (running_args.strip() != configured_args.strip()):
                            llama_restart_needed_label.value = "Restart required: running args differ from configured args."
                            llama_restart_needed_label.visible = True
                        else:
                            llama_restart_needed_label.visible = False
                    else:
                        llama_status_label.value = "Server: (status unavailable)"
                        llama_running_args_label.value = "Running LLAMA_ARGS: --"
                        llama_cmdline_label.value = "Cmdline: --"
                        llama_restart_needed_label.visible = False
                except Exception:
                    llama_status_label.value = "Server: (status unavailable)"
                    llama_running_args_label.value = "Running LLAMA_ARGS: --"
                    llama_cmdline_label.value = "Cmdline: --"
                    llama_restart_needed_label.visible = False
            finally:
                backend_refresh_guard["value"] = False
        except Exception as exc:
            backend_refresh_guard["value"] = False
            backend_settings_note_models.value = f"Backend settings: (error: {exc})"
            backend_settings_note_settings.value = f"Backend settings: (error: {exc})"
        page.update()

    def switch_model(_=None):
        if not model_dropdown.value:
            show_snack("Select a model first.", WARNING)
            return
        target = model_dropdown.value

        def mark_switching():
            state["switching_model"] = True
            state["model_online"] = False
            state["model_ready"] = False
            state["model_loading"] = False
            state["model_loading_since"] = time.time()
            state["model_loading_error_shown"] = False
            model_switch_spinner.visible = True
            update_send_state()
            page.update()
        mark_switching()

        def worker():
            try:
                resp = requests.post(
                    f"{SEARCH_API_URL}/models/switch",
                    json={"model_path": target},
                    timeout=20,
                )
                data = resp.json()
                if not data.get("success"):
                    raise RuntimeError(data.get("message", "Switch failed"))
            except Exception as exc:
                def fail():
                    state["switching_model"] = False
                    model_switch_spinner.visible = False
                    update_send_state()
                    show_snack(f"Switch error: {exc}", DANGER)
                    page.update()
                _ui_call(page, fail)
                return

            _ui_call(page, lambda: show_snack("Switching model, please wait...", ACCENT))


            deadline = time.time() + 120.0
            ok = False
            while time.time() < deadline:
                try:
                    ok = ui_pollers.is_model_server_ready(MODEL_SERVER_URL)
                except Exception:
                    ok = False
                if ok:
                    break
                time.sleep(0.5)

            def done():
                state["switching_model"] = False
                model_switch_spinner.visible = False
                state["model_online"] = bool(ok)
                state["model_ready"] = bool(ok)
                state["model_loading"] = False
                state["model_loading_since"] = None
                state["model_loading_error_shown"] = False
                model_status_dot.bgcolor = SUCCESS if ok else DANGER
                update_send_state()
                if ok:
                    show_snack("Model online.", SUCCESS)
                    refresh_models()
                else:
                    show_snack("Model switch timed out (server still offline).", DANGER)
                page.update()
            _ui_call(page, done)

        threading.Thread(target=worker, daemon=True).start()

    def apply_ctx_size(_=None):
        if state.get("streaming"):
            show_snack("Stop generation before restarting the model server.", WARNING)
            return
        raw = (ctx_size_field.value or "").strip()
        try:
            ctx = int(raw)
        except Exception:
            show_snack("Context length must be a number.", WARNING)
            return
        if ctx < 256 or ctx > 1_048_576:
            show_snack("Context length must be between 256 and 1048576.", WARNING)
            return

        def mark_switching():
            state["switching_model"] = True
            state["model_online"] = False
            state["model_ready"] = False
            state["model_loading"] = False
            model_switch_spinner.visible = True
            update_send_state()
            page.update()
        mark_switching()

        def done():
            state["switching_model"] = False
            model_switch_spinner.visible = False


            state["model_online"] = False
            state["model_ready"] = False
            state["model_loading"] = True
            state["model_loading_since"] = time.time()
            state["model_loading_error_shown"] = False
            model_status_dot.bgcolor = WARNING
            update_send_state()
            refresh_models()
            show_snack(f"Context length set to {ctx}. Restarting server (may take a while)...", ACCENT)
            page.update()

        def worker():
            try:
                resp = requests.post(
                    f"{SEARCH_API_URL}/llama/ctx",
                    json={"ctx_size": ctx, "restart": True},
                    timeout=30,
                )
                data = resp.json() if resp is not None else {}
                if not resp.ok or not data.get("success", False):
                    msg = data.get("message") or data.get("detail") or (resp.text if resp is not None else "")
                    raise RuntimeError(str(msg).strip() or "Failed to update ctx-size")
            except Exception as exc:
                def fail():
                    state["switching_model"] = False
                    model_switch_spinner.visible = False
                    update_send_state()
                    show_snack(f"Ctx-size update failed: {exc}", DANGER)
                    page.update()
                _ui_call(page, fail)
                return
            _ui_call(page, done)

        threading.Thread(target=worker, daemon=True).start()

    def load_sessions():
        sessions_list.controls.clear()
        sidebar_sessions_list.controls.clear()
        needle = (session_filter_field.value or "").strip().lower()
        for session in _load_session_index():
            if needle and needle not in (session.get("name", "").lower()):
                continue
            tile = ft.ListTile(
                title=ft.Text(session["name"], color=TEXT_PRIMARY),
                subtitle=ft.Text(session["id"], color=TEXT_MUTED),
                on_click=lambda e, sid=session["id"], name=session["name"]: select_session(sid, name),
            )
            sessions_list.controls.append(tile)
            delete_btn = ft.IconButton(
                icon=ft.icons.DELETE_OUTLINE,
                tooltip="Delete session",
                icon_color=TEXT_MUTED,
                on_click=lambda e, sid=session["id"], name=session["name"]: confirm_delete_session(sid, name),
            )
            sidebar_tile = ft.ListTile(
                title=ft.Text(session["name"], size=12, color=TEXT_PRIMARY),
                on_click=lambda e, sid=session["id"], name=session["name"]: confirm_load_session(sid, name),
                trailing=delete_btn,
            )
            sidebar_sessions_list.controls.append(sidebar_tile)
        page.update()

    def select_session(session_id, name):
        selected_session_id["value"] = session_id
        session_name_input.value = name
        delete_session_button.disabled = False
        load_session_button.disabled = False
        page.update()

    def delete_session_by_id(session_id: str, announce: bool = True):
        if not session_id:
            return
        session_file = SESSIONS_DIR / f"{session_id}.json"
        try:
            if session_file.exists():
                session_file.unlink()
        except Exception as exc:
            show_snack(f"Delete failed: {exc}", DANGER)
            return
        try:
            index = [s for s in _load_session_index() if s.get("id") != session_id]
            _save_session_index(index)
        except Exception as exc:
            show_snack(f"Delete failed: {exc}", DANGER)
            return

        if selected_session_id.get("value") == session_id:
            selected_session_id["value"] = None
            session_name_input.value = ""
            delete_session_button.disabled = True
            load_session_button.disabled = True

        load_sessions()
        if announce:
            show_snack("Session deleted.", ACCENT)

    def confirm_delete_session(session_id, name):
        def close_dialog(_=None):
            try:
                dlg.open = False
                page.update()
            except Exception:
                pass

        def do_delete(_=None):
            close_dialog()
            delete_session_by_id(session_id)

        dlg = ft.AlertDialog(
            modal=True,
            title=ft.Text("Delete session"),
            content=ft.Text(f'Delete "{name}"?\n\nThis cannot be undone.'),
            actions=[
                ft.TextButton("Cancel", on_click=close_dialog),
                ft.ElevatedButton(
                    "Delete",
                    on_click=do_delete,
                    style=ft.ButtonStyle(bgcolor=DANGER, color=SURFACE),
                ),
            ],
            actions_alignment=ft.MainAxisAlignment.END,
        )
        page.dialog = dlg
        dlg.open = True
        page.update()

    def confirm_load_session(session_id, name):

        select_session(session_id, name)

        def close_dialog(_=None):
            try:
                dlg.open = False
                page.update()
            except Exception:
                pass

        def do_load(_=None):
            close_dialog()
            load_session_by_id(session_id)
            try:
                set_view(0)
            except Exception:
                pass
            show_snack("Session loaded.", SUCCESS)

        body_lines = []
        body_lines.append(f'Load "{name}"?')
        if state.get("messages"):
            body_lines.append("")
            body_lines.append("This will replace the current chat in the window.")

        dlg = ft.AlertDialog(
            modal=True,
            title=ft.Text("Load session"),
            content=ft.Text("\n".join(body_lines)),
            actions=[
                ft.TextButton("Cancel", on_click=close_dialog),
                ft.ElevatedButton("Load", on_click=do_load, style=primary_button_style),
            ],
            actions_alignment=ft.MainAxisAlignment.END,
        )
        page.dialog = dlg
        dlg.open = True
        page.update()

    def new_chat(_=None):
        state["messages"] = []
        state["pending_search_contexts"] = []
        state["loaded_documents"] = []
        chat_list.controls.clear()
        reset_perf_stats()
        input_field.value = ""
        selected_session_id["value"] = None
        session_name_input.value = ""
        delete_session_button.disabled = True
        load_session_button.disabled = True
        update_empty_state()
        update_doc_list()
        update_send_state()
        try:
            update_context_stats()
        except Exception:
            pass
        page.update()

    def save_session(_=None):
        name = f"Chat {time.strftime('%Y-%m-%d %H:%M:%S')}"
        session_id = ui_sessions_io.new_session_id()
        session_file = SESSIONS_DIR / f"{session_id}.json"
        session_payload = ui_sessions_io.build_session_payload(state.get("messages") or [])
        ui_sessions_io.write_json(session_file, session_payload)
        index = _load_session_index()
        index.append({"id": session_id, "name": name})
        _save_session_index(index)
        load_sessions()
        show_snack(f'Session saved as "{name}".', SUCCESS)

    def load_session_by_id(session_id):
        session_file = SESSIONS_DIR / f"{session_id}.json"
        if not session_file.exists():
            show_snack("Session file not found.", DANGER)
            return
        data = ui_sessions_io.read_json(session_file)
        state["messages"] = []
        state["pending_search_contexts"] = []
        state["loaded_documents"] = []
        chat_list.controls.clear()
        reset_perf_stats()
        input_field.value = ""
        for msg in data.get("messages", []):
            add_message(
                msg["role"],
                msg["content"],
                llm_content=msg.get("llm_content"),
                timestamp=msg.get("timestamp"),
            )
        update_doc_list()
        update_send_state()
        update_empty_state()
        try:
            update_context_stats()
        except Exception:
            pass
        page.update()

    def delete_session(_=None):
        session_id = selected_session_id["value"]
        if not session_id:
            return
        delete_session_by_id(session_id)

    def load_session(_=None):
        session_id = selected_session_id["value"]
        if not session_id:
            show_snack("Select a session to load.", WARNING)
            return
        load_session_by_id(session_id)
        show_snack("Session loaded.", SUCCESS)

    def export_session(_=None):
        session_id = selected_session_id["value"]
        if not session_id:
            show_snack("Select a session to export.", WARNING)
            return
        export_root = export_dir["value"]
        if not export_root:
            show_snack("Pick an export folder.", WARNING)
            return
        session_file = SESSIONS_DIR / f"{session_id}.json"
        if not session_file.exists():
            show_snack("Session file missing.", DANGER)
            return
        raw_name = session_name_input.value.strip() or f"session_{session_id}"
        safe_name = ui_sessions_io.safe_filename(raw_name)
        fmt = (export_format_dropdown.value or "json").strip().lower()
        try:
            payload = ui_sessions_io.read_json(session_file)
        except Exception as exc:
            show_snack(f"Export failed: {exc}", DANGER)
            return
        ext, out = ui_sessions_io.export_session_text(
            payload,
            raw_name,
            str(state.get("assistant_name") or "Assistant"),
            fmt,
        )
        export_path = Path(export_root) / f"{safe_name}.{ext}"
        export_path.write_text(out, encoding="utf-8")
        show_snack(f"Session exported as .{ext}.", SUCCESS)

    def import_session(_=None):
        import_path = (import_file_dropdown.value or "").strip()
        if not import_path:
            show_snack("Select a session file to import.", WARNING)
            return
        try:
            data = ui_sessions_io.read_json(import_path)
        except Exception as exc:
            show_snack(f"Import failed: {exc}", DANGER)
            return
        session_id = ui_sessions_io.new_session_id()
        session_file = SESSIONS_DIR / f"{session_id}.json"
        ui_sessions_io.write_json(session_file, data)
        index = _load_session_index()
        index.append({"id": session_id, "name": f"Imported {time.strftime('%Y-%m-%d %H:%M:%S')}"})
        _save_session_index(index)
        load_sessions()
        show_snack("Session imported.", SUCCESS)

    def _last_message_by_role(role: str):
        for msg in reversed(state.get("messages") or []):
            if msg.get("role") == role:
                return msg
        return None

    def copy_last_assistant_message():
        msg = _last_message_by_role("model")
        if not msg:
            show_snack("No assistant message to copy.", WARNING)
            return
        text_to_copy = (msg.get("display_content") or msg.get("content") or "").strip()
        if not text_to_copy:
            show_snack("Assistant message is empty.", WARNING)
            return
        try:
            page.set_clipboard(text_to_copy)
            show_snack("Copied assistant message to clipboard.", SUCCESS)
        except Exception as exc:
            show_snack(f"Copy failed: {exc}", DANGER)

    def edit_last_user_message():
        msg = _last_message_by_role("user")
        if not msg:
            show_snack("No user message to edit.", WARNING)
            return
        raw = str(msg.get("content") or "")

        if raw.startswith("📎 Documents attached"):
            raw = raw.split("\n\n", 1)[1] if "\n\n" in raw else ""
        input_field.value = raw.strip()
        try:
            input_field.focus()
        except Exception:
            pass
        update_send_state()
        page.update()

    def regenerate_last_response():
        msg = _last_message_by_role("user")
        if not msg:
            show_snack("No user message to regenerate from.", WARNING)
            return
        raw = str(msg.get("content") or "")
        if raw.startswith("📎 Documents attached"):
            raw = raw.split("\n\n", 1)[1] if "\n\n" in raw else ""
        input_field.value = raw.strip()
        page.update()
        send_message()

    def continue_last_response():
        input_field.value = "Continue."
        page.update()
        send_message()

    def copy_system_prompt_only():
        try:

            prompt = format_prompt(messages=[])
            if prompt.endswith("\nASSISTANT:"):
                prompt = prompt[:-len("\nASSISTANT:")].rstrip() + "\n"
            page.set_clipboard(prompt)
            show_snack("Copied system prompt to clipboard.", SUCCESS)
        except Exception as exc:
            show_snack(f"Copy failed: {exc}", DANGER)

    def open_command_palette(_=None):
        commands = [
            ("New chat", "Ctrl+N", lambda: new_chat()),
            ("Save session", "Ctrl+S", lambda: save_session()),
            ("Open Sessions tab", "Ctrl+O", lambda: set_view(2)),
            ("Open Models tab", "", lambda: set_view(1)),
            ("Open Tools tab", "", lambda: set_view(3)),
            ("Open Settings tab", "", lambda: set_view(4)),
            ("Open Keyboard shortcuts", "", lambda: set_view(5)),
            ("Attach file(s)", "Ctrl+A", lambda: (file_picker.pick_files(allow_multiple=True) if file_picker and hasattr(file_picker, "pick_files") else show_snack("File picker unavailable.", WARNING))),
            ("Refresh models", "Ctrl+R", lambda: refresh_models()),
            ("Stop generation", "Esc", lambda: stop_stream()),
            ("Regenerate last response", "", lambda: regenerate_last_response()),
            ("Continue last response", "", lambda: continue_last_response()),
            ("Edit last user message", "", lambda: edit_last_user_message()),
            ("Copy last assistant message", "", lambda: copy_last_assistant_message()),
            ("Copy system prompt", "", lambda: copy_system_prompt_only()),
            ("Toggle sidebar", "", lambda: toggle_sidebar()),
        ]

        query = ft.TextField(
            hint_text="Type a command...",
            autofocus=True,
            filled=True,
            bgcolor=SURFACE,
            border_color=BORDER,
            focused_border_color=BORDER,
            text_style=ft.TextStyle(color=TEXT_PRIMARY, size=12),
            hint_style=ft.TextStyle(color=TEXT_MUTED, size=12),
        )
        results = ft.ListView(spacing=2, height=320, auto_scroll=False)
        dlg_ref = {"dlg": None}

        def close_dialog(_=None):
            try:
                dlg.open = False
                page.update()
            except Exception:
                pass

        def run_cmd(fn):
            close_dialog()
            try:
                fn()
            except Exception as exc:
                show_snack(f"Command failed: {exc}", DANGER)

        def refresh_list(_=None):
            needle = (query.value or "").strip().lower()
            results.controls.clear()
            shown = 0
            for name, keys, fn in commands:
                if needle and needle not in name.lower():
                    continue
                subtitle = keys or ""
                tile = ft.ListTile(
                    title=ft.Text(name, color=TEXT_PRIMARY),
                    subtitle=ft.Text(subtitle, color=TEXT_MUTED) if subtitle else None,
                    on_click=lambda e, fn=fn: run_cmd(fn),
                )
                results.controls.append(tile)
                shown += 1
                if shown >= 25:
                    break

            try:
                if getattr(results, "page", None) is not None or (page.dialog is dlg_ref.get("dlg")):
                    results.update()
                else:
                    page.update()
            except Exception:
                try:
                    page.update()
                except Exception:
                    pass

        def submit(_=None):
            needle = (query.value or "").strip().lower()
            for name, _, fn in commands:
                if not needle or needle in name.lower():
                    run_cmd(fn)
                    return

        query.on_change = refresh_list
        query.on_submit = submit

        dlg = ft.AlertDialog(
            modal=True,
            title=ft.Text("Command palette"),
            content=ft.Column([query, results], tight=True, spacing=10, width=680),
            actions=[ft.TextButton("Close", on_click=close_dialog)],
            actions_alignment=ft.MainAxisAlignment.END,
        )
        dlg_ref["dlg"] = dlg
        page.dialog = dlg
        dlg.open = True
        page.update()
        refresh_list()

    _last_key_dedupe = {"sig": None, "t": 0.0}

    def handle_key_event(e: ft.KeyboardEvent):


        raw_key = ""
        try:
            raw_key = str(getattr(e, "key", "") or "")
        except Exception:
            raw_key = ""


        key_upper = raw_key.upper().strip()
        ctrl = bool(getattr(e, "ctrl", False))
        meta = bool(getattr(e, "meta", False))
        shift = bool(getattr(e, "shift", False))
        alt = bool(getattr(e, "alt", False))

        parts = [p.strip() for p in key_upper.replace("CONTROL", "CTRL").split("+") if p.strip()]
        mod_set = set()
        base = ""
        for p in parts:
            if p in ("CTRL", "CMD", "META", "SHIFT", "ALT", "OPTION"):
                mod_set.add(p)
                continue
            base = p
        if not base and parts:
            base = parts[-1]

        if "CTRL" in mod_set:
            ctrl = True
        if "CMD" in mod_set or "META" in mod_set:
            meta = True
        if "SHIFT" in mod_set:
            shift = True
        if "ALT" in mod_set or "OPTION" in mod_set:
            alt = True

        is_ctrl = bool(ctrl or meta)

        sig = (base, is_ctrl, bool(shift), bool(alt), key_upper)
        now = time.time()
        if _last_key_dedupe["sig"] == sig and (now - float(_last_key_dedupe["t"] or 0.0)) < 0.05:
            return
        _last_key_dedupe["sig"] = sig
        _last_key_dedupe["t"] = now


        try:
            keyboard_last_event_label.value = f"Last key: base={base} ctrl={is_ctrl} shift={shift} alt={alt} raw={key_upper}"
            keyboard_last_event_label.update()
        except Exception:
            pass

        if base in ("ENTER", "NUMPAD ENTER") and is_ctrl:
            if getattr(input_field, "focused", True):
                send_message()
            return

        if base == "ESCAPE":
            stop_stream()
            return

        def _try_open_palette():
            try:
                open_command_palette()
            except Exception as exc:
                show_snack(f"Command palette failed: {exc}", DANGER)

        if base == "F1":
            _try_open_palette()
            return

        if is_ctrl and base == "A":

            if file_picker and hasattr(file_picker, "pick_files") and not attach_button.disabled:
                file_picker.pick_files(allow_multiple=True)
            else:
                show_snack("File picker unavailable.", WARNING)
            return

        if is_ctrl and base == "S":
            save_session()
            return

        if is_ctrl and base == "N":
            new_chat()
            return


        if is_ctrl and base in ("K", "P"):
            _try_open_palette()
            return

        if is_ctrl and base == "R":
            refresh_models()
            return

        if is_ctrl and base == "M":

            try:
                model_dropdown.focus()
            except Exception:
                pass
            return

        if is_ctrl and base == "O":

            try:
                set_view(2)
            except Exception:
                pass
            sid = selected_session_id.get("value")
            if sid:

                name = (session_name_input.value or "").strip() or sid
                confirm_load_session(sid, name)
            else:
                show_snack("Select a session to open.", WARNING)
            try:
                session_filter_field.focus()
            except Exception:
                pass
            return

        if is_ctrl and base in ("ARROW UP", "ARROW_UP", "UP"):

            try:
                n = len(chat_list.controls)
                if n <= 0:
                    return
                idx = int(state.get("chat_scroll_index", n - 1))
                idx = max(0, min(n - 1, idx - 6))
                state["chat_scroll_index"] = idx
                if hasattr(chat_list, "scroll_to"):
                    try:
                        chat_list.scroll_to(index=idx)
                    except TypeError:
                        chat_list.scroll_to(idx)
                chat_list.update()
            except Exception:
                pass
            return

        if is_ctrl and base in ("ARROW DOWN", "ARROW_DOWN", "DOWN"):
            try:
                n = len(chat_list.controls)
                if n <= 0:
                    return
                idx = int(state.get("chat_scroll_index", n - 1))
                idx = max(0, min(n - 1, idx + 6))
                state["chat_scroll_index"] = idx
                if hasattr(chat_list, "scroll_to"):
                    try:
                        chat_list.scroll_to(index=idx)
                    except TypeError:
                        chat_list.scroll_to(idx)
                chat_list.update()
            except Exception:
                pass
            return

    def update_bubble_widths(_=None):
        w = getattr(getattr(page, "window", None), "width", None)
        if not isinstance(w, (int, float)) or w <= 0:
            w = getattr(page, "window_width", 1100) or 1100
        sidebar_w = 0
        try:
            if sidebar_container.visible:
                sidebar_w = SIDEBAR_WIDTH
        except Exception:
            sidebar_w = SIDEBAR_WIDTH
        width = min(CHAT_MAX_WIDTH, max(CHAT_MIN_WIDTH, int(w - sidebar_w - 90)))
        if width < CHAT_MIN_WIDTH:
            width = min(CHAT_MAX_WIDTH, max(CHAT_MIN_WIDTH, int(w - 40)))
        for msg in state["messages"]:
            outer = msg.get("outer")
            if outer is not None and hasattr(outer, "width"):
                outer.width = width
            if msg.get("role") == "user":
                bubble = msg.get("bubble")
                if bubble is not None and hasattr(bubble, "width"):
                    try:
                        bubble.width = max(240, min(int(width), int(int(width) * 0.82)))
                    except Exception:
                        bubble.width = max(240, min(int(width), int(width * 0.82)))
        composer_outer = composer_outer_ref.get("value")
        if composer_outer is not None and hasattr(composer_outer, "width"):
            composer_outer.width = width
        page.update()

    def apply_strip_setting():
        for msg in state["messages"]:
            if msg.get("role") != "model":
                continue
            control = msg.get("control")
            if not control:
                continue
            raw = msg.get("content") or ""
            msg["display_raw"] = _strip_emoji(raw) if state["strip_emoji"] else raw
            cleaned = strip_prompt_echo(raw)
            display = _strip_emoji(cleaned) if state["strip_emoji"] else cleaned
            msg["display_content"] = display
            if msg.get("render_mode") == "markdown":
                block = msg.get("content_block")
                if block is not None:
                    block.content = _render_markdown(display)
                    try:
                        block.update()
                    except Exception:
                        pass
            elif hasattr(control, "value"):
                control.value = display
        page.update()

    send_button.on_click = send_message
    stop_button.on_click = stop_stream
    if file_picker:
        attach_button.on_click = lambda _: file_picker.pick_files(allow_multiple=True)
    else:
        attach_button.disabled = True
    clear_docs_button.on_click = clear_docs

    refresh_models_button.on_click = refresh_models
    switch_model_button.on_click = switch_model
    palette_button.on_click = open_command_palette
    ctx_apply_button.on_click = apply_ctx_size

    save_session_button.on_click = save_session
    load_session_button.on_click = load_session
    delete_session_button.on_click = delete_session
    export_session_button.on_click = export_session
    import_session_button.on_click = import_session


    _send_state_timer = {"timer": None}
    def schedule_send_state_update():
        t = _send_state_timer.get("timer")
        if t is not None:
            try:
                t.cancel()
            except Exception:
                pass
        def run():
            _ui_call(page, update_send_state)
        _send_state_timer["timer"] = threading.Timer(0.08, run)
        _send_state_timer["timer"].daemon = True
        _send_state_timer["timer"].start()

    input_field.on_change = lambda _: (schedule_send_state_update(), schedule_context_stats_update())
    input_field.on_keyboard_event = handle_key_event
    page.on_keyboard_event = handle_key_event
    page.on_resize = update_bubble_widths
    temperature_field.on_change = lambda _: schedule_save_ui_prefs()
    max_tokens_field.on_change = lambda _: schedule_save_ui_prefs()
    top_p_field.on_change = lambda _: schedule_save_ui_prefs()
    top_k_field.on_change = lambda _: schedule_save_ui_prefs()
    stop_sequences_field.on_change = lambda _: schedule_save_ui_prefs()
    assistant_name_field.on_change = lambda _: (state.update({"assistant_name": str(assistant_name_field.value or "").strip()}), refresh_assistant_name_labels(), schedule_save_ui_prefs())
    assistant_tone_field.on_change = lambda _: (state.update({"assistant_tone": str(assistant_tone_field.value or "").strip()}), schedule_save_ui_prefs())
    export_format_dropdown.on_change = lambda _: schedule_save_ui_prefs()

    composer_buttons = ft.Row(
        [attach_button],
        spacing=2,
        vertical_alignment=ft.CrossAxisAlignment.CENTER,
    )
    composer_actions = ft.Row(
        [stop_button, generating_row, send_button],
        spacing=6,
        vertical_alignment=ft.CrossAxisAlignment.CENTER,
    )

    input_panel = ft.Column(
            [
                ft.Row(
                    [composer_buttons, input_field, composer_actions],
                    spacing=10,
                    vertical_alignment=ft.CrossAxisAlignment.CENTER,
                ),
                docs_status_label,
                docs_row,
                perf_row,
                context_row,
            ],
            spacing=6,
        )
    composer_outer = ft.Container(
        content=input_panel,
        padding=10,
        bgcolor=SURFACE,
        border=ft.border.all(1, BORDER),
        border_radius=22,
        shadow=ft.BoxShadow(blur_radius=18, spread_radius=-6, color="#00000066", offset=ft.Offset(0, 8)),
        width=CHAT_MAX_WIDTH,
    )
    composer_outer_ref["value"] = composer_outer

    chat_scroller = ft.Container(
        content=chat_list,
        expand=True,
        bgcolor=BG,
        padding=ft.padding.only(top=18),
    )
    chat_tab = view_chat.build_chat_tab(chat_scroller=chat_scroller, empty_state=empty_state, composer_outer=composer_outer)


    model_dir_button = ft.OutlinedButton("Choose model folder", style=secondary_button_style)
    files_dir_button = ft.OutlinedButton("Choose files folder", style=secondary_button_style)
    files_dir_home_button = ft.OutlinedButton("Home", style=secondary_button_style)
    files_dir_desktop_button = ft.OutlinedButton("Desktop", style=secondary_button_style)
    files_dir_project_button = ft.OutlinedButton("Project", style=secondary_button_style)

    if dir_picker and hasattr(dir_picker, "get_directory_path"):
        model_dir_button.on_click = lambda _: (dir_picker_target.update({"value": "model_dir"}), dir_picker.get_directory_path())
        files_dir_button.on_click = lambda _: (dir_picker_target.update({"value": "files_dir"}), dir_picker.get_directory_path())
    else:
        model_dir_button.disabled = True
        files_dir_button.disabled = True

    def _set_files_dir(path: str):
        try:
            resp = requests.post(
                f"{SEARCH_API_URL}/files/dir",
                json={"path": path, "create": True},
                timeout=10,
            )
            resp.raise_for_status()
            data = resp.json() or {}
            if not data.get("success", True):
                show_snack(data.get("message", "Failed to update file tool directory."), DANGER)
                return
            state["files_tool_dir"] = data.get("files_dir", path) or path
            writable = data.get("writable")
            suffix = ""
            if writable is True:
                suffix = " (writable)"
            elif writable is False:
                suffix = " (read-only)"
            files_dir_label.value = f"File tool directory: {state['files_tool_dir']}{suffix}"
            show_snack("File tool directory updated.", SUCCESS)
            page.update()
        except Exception as exc:
            show_snack(f"Failed to update file tool directory: {exc}", DANGER)

    files_dir_home_button.on_click = lambda _: _set_files_dir(str(Path.home()))
    files_dir_desktop_button.on_click = lambda _: _set_files_dir(str((Path.home() / "Desktop")))
    files_dir_project_button.on_click = lambda _: _set_files_dir(str(Path(__file__).resolve().parents[1]))

    models_tab = view_models.build_models_tab(
        current_model_info=current_model_info,
        model_dir_button=model_dir_button,
        model_dir_label=model_dir_label,
        llama_ctx_label=llama_ctx_label,
        ctx_size_field=ctx_size_field,
        ctx_apply_button=ctx_apply_button,
        autostart_model_switch=autostart_model_switch,
        backend_settings_note_models=backend_settings_note_models,
        model_status_text=model_status_text,
        surface=SURFACE,
        border=BORDER,
        text_muted=TEXT_MUTED,
    )

    export_dir_button = ft.OutlinedButton("Choose export folder", style=secondary_button_style)
    import_dir_button = ft.OutlinedButton("Choose import folder", style=secondary_button_style)

    if dir_picker and hasattr(dir_picker, "get_directory_path"):
        export_dir_button.on_click = lambda _: (dir_picker_target.update({"value": "export"}), dir_picker.get_directory_path())
        import_dir_button.on_click = lambda _: (dir_picker_target.update({"value": "import"}), dir_picker.get_directory_path())
    else:
        export_dir_button.disabled = True
        import_dir_button.disabled = True

    sessions_tab = view_sessions.build_sessions_tab(
        save_session_button=save_session_button,
        load_session_button=load_session_button,
        delete_session_button=delete_session_button,
        export_session_button=export_session_button,
        import_session_button=import_session_button,
        session_name_input=session_name_input,
        export_format_dropdown=export_format_dropdown,
        export_dir_button=export_dir_button,
        export_dir_label=export_dir_label,
        import_dir_button=import_dir_button,
        import_dir_label=import_dir_label,
        import_file_dropdown=import_file_dropdown,
        sessions_list=sessions_list,
    )

    def apply_tool_toggles(_=None):
        state["tool_web_search_enabled"] = bool(tool_web_search_switch.value)
        state["tool_fs_enabled"] = bool(tool_fs_switch.value)
        page.update()
        schedule_save_ui_prefs()

    def _parse_int_field(raw: str, default: int, lo: int, hi: int) -> int:
        try:
            n = int((raw or "").strip())
        except Exception:
            n = int(default)
        n = max(int(lo), min(int(hi), int(n)))
        return n

    def _parse_float_field(raw: str, default: float, lo: float, hi: float) -> float:
        try:
            v = float((raw or "").strip())
        except Exception:
            v = float(default)
        if v < lo:
            v = lo
        if v > hi:
            v = hi
        return float(v)

    def apply_file_tool_limit(_=None):
        if backend_refresh_guard["value"]:
            return
        max_bytes = _parse_int_field(tool_files_max_bytes_field.value, 200_000, 10_000, 10_000_000)
        try:
            resp = requests.post(
                f"{SEARCH_API_URL}/settings",
                json={"tool_files_max_bytes": int(max_bytes)},
                timeout=10,
            )
            resp.raise_for_status()
            show_snack("File tool limit updated.", SUCCESS)
            refresh_backend_settings()
        except Exception as exc:
            show_snack(f"Failed to update file tool limit: {exc}", DANGER)

    def apply_autostart_model(_=None):
        if backend_refresh_guard["value"]:
            return
        try:
            resp = requests.post(
                f"{SEARCH_API_URL}/settings",
                json={"autostart_model": bool(autostart_model_switch.value)},
                timeout=10,
            )
            resp.raise_for_status()
        except Exception as exc:
            show_snack(f"Failed to update autostart setting: {exc}", DANGER)

    def apply_power_calibration(_=None):
        if backend_refresh_guard["value"]:
            return
        idle = _parse_float_field(power_idle_field.value, 15.0, 0.0, 10_000.0)
        mx = _parse_float_field(power_max_field.value, 65.0, 0.0, 10_000.0)
        if mx <= idle:
            show_snack("Power max must be greater than power idle.", WARNING)
            return
        try:
            resp = requests.post(
                f"{SEARCH_API_URL}/settings",
                json={"power_idle_watts": float(idle), "power_max_watts": float(mx)},
                timeout=10,
            )
            resp.raise_for_status()
            show_snack("Telemetry calibration updated.", SUCCESS)
            refresh_backend_settings()
        except Exception as exc:
            show_snack(f"Failed to update telemetry calibration: {exc}", DANGER)

    def apply_llama_args(_=None):
        if backend_refresh_guard["value"]:
            return
        args = (llama_args_field.value or "").strip()
        if not args:
            show_snack("llama args cannot be empty.", WARNING)
            return

        try:
            resp = requests.post(
                f"{SEARCH_API_URL}/settings",
                json={"llama_args": args},
                timeout=10,
            )
            resp.raise_for_status()
            refresh_backend_settings()
        except Exception as exc:
            show_snack(f"Failed to save llama args: {exc}", DANGER)
            return

        if not bool(llama_args_restart_switch.value):
            show_snack("Saved llama args. Restart the model server to apply.", SUCCESS)
            return


        try:
            resp = requests.get(f"{SEARCH_API_URL}/models", timeout=10)
            resp.raise_for_status()
            data = resp.json() or {}
            current = (data.get("current_model") or "").strip()
        except Exception as exc:
            show_snack(f"Saved llama args, but failed to find current model for restart: {exc}", WARNING)
            return

        if not current:
            show_snack("Saved llama args. No model is currently loaded to restart.", SUCCESS)
            return

        def mark_loading():
            state["switching_model"] = True
            state["model_online"] = False
            state["model_ready"] = False
            state["model_loading"] = True
            state["model_loading_since"] = time.time()
            state["model_loading_error_shown"] = False
            model_switch_spinner.visible = True
            update_send_state()
            page.update()

        def worker():
            try:
                r2 = requests.post(
                    f"{SEARCH_API_URL}/models/switch",
                    json={"model_path": current},
                    timeout=20,
                )
                d2 = r2.json() if r2 is not None else {}
                if (not r2.ok) or (not d2.get("success", False)):
                    msg = d2.get("message") or d2.get("detail") or (r2.text if r2 is not None else "")
                    raise RuntimeError(str(msg).strip() or "Restart failed")
            except Exception as exc:
                def fail():
                    state["switching_model"] = False
                    state["model_loading"] = False
                    model_switch_spinner.visible = False
                    update_send_state()
                    show_snack(f"Restart failed: {exc}", DANGER)
                    page.update()
                _ui_call(page, fail)
                return

            def done():
                state["switching_model"] = False
                model_switch_spinner.visible = False

                state["model_online"] = False
                state["model_ready"] = False
                state["model_loading"] = True
                state["model_loading_since"] = time.time()
                state["model_loading_error_shown"] = False
                model_status_dot.bgcolor = WARNING
                update_send_state()
                show_snack("Saved llama args. Restarting model server...", ACCENT)
                try:
                    refresh_models()
                except Exception:
                    pass
                page.update()
            _ui_call(page, done)

        mark_loading()
        threading.Thread(target=worker, daemon=True).start()

    def apply_appearance(_=None):
        theme_name = str(theme_dropdown.value or "Obsidian")
        dens_name = str(density_dropdown.value or "Comfortable")
        if theme_name not in THEME_PRESETS:
            theme_name = "Obsidian"
        if dens_name not in DENSITY_PRESETS:
            dens_name = "Comfortable"

        state["theme_preset"] = theme_name
        state["density_preset"] = dens_name
        state["density_cfg"] = _get_density(dens_name)

        _apply_theme_globals(theme_name)

        shell_colors["BG"] = BG
        shell_colors["SIDEBAR_BG"] = SIDEBAR_BG
        shell_colors["SURFACE"] = SURFACE
        shell_colors["SURFACE_ALT"] = SURFACE_ALT
        shell_colors["BORDER"] = BORDER
        shell_colors["TEXT_PRIMARY"] = TEXT_PRIMARY
        shell_colors["TEXT_MUTED"] = TEXT_MUTED


        page.bgcolor = BG
        try:
            sidebar_container.bgcolor = SIDEBAR_BG
            sidebar_container.border = ft.border.only(right=ft.BorderSide(1, BORDER))
        except Exception:
            pass
        try:
            main_container.bgcolor = BG
        except Exception:
            pass
        try:
            content_holder.bgcolor = BG
        except Exception:
            pass
        try:
            chat_scroller.bgcolor = BG
        except Exception:
            pass
        try:
            top_bar.bgcolor = SURFACE_ALT
            top_bar.border = ft.border.only(bottom=ft.BorderSide(1, BORDER))
        except Exception:
            pass


        try:
            input_field.bgcolor = SURFACE
            input_field.border_color = BORDER
            input_field.focused_border_color = BORDER
        except Exception:
            pass
        try:
            composer_outer.bgcolor = SURFACE
            composer_outer.border = ft.border.all(1, BORDER)
        except Exception:
            pass
        try:
            session_filter_field.bgcolor = SURFACE
            session_filter_field.border_color = BORDER
            session_filter_field.focused_border_color = BORDER
        except Exception:
            pass
        try:
            context_bar.bgcolor = SURFACE_ALT
        except Exception:
            pass


        dens = state.get("density_cfg") or {}
        try:
            chat_list.spacing = int(dens.get("chat_spacing", 14) or 14)
            chat_list.padding = int(dens.get("chat_padding", 12) or 12)
        except Exception:
            pass

        bubble_pad = int(dens.get("bubble_padding", 14) or 14)
        outer_pad_v = int(dens.get("outer_pad_v", 6) or 6)
        for msg in state.get("messages") or []:
            outer = msg.get("outer")
            if isinstance(outer, ft.Container):
                try:
                    outer.padding = ft.padding.symmetric(horizontal=12, vertical=outer_pad_v)
                except Exception:
                    pass
            bubble = msg.get("bubble")
            if isinstance(bubble, ft.Container):
                try:
                    if msg.get("role") == "user":
                        bubble.bgcolor = SURFACE
                        bubble.padding = bubble_pad
                        bubble.border = ft.border.all(1, BORDER)
                    elif msg.get("role") in ("search", "tool"):
                        bubble.bgcolor = SURFACE_ALT
                        bubble.border = ft.border.all(1, BORDER)
                except Exception:
                    pass


        try:
            for chip in docs_list.controls:
                if isinstance(chip, ft.Container):
                    chip.bgcolor = SURFACE_ALT
                    chip.border = ft.border.all(1, BORDER)
        except Exception:
            pass

        update_nav_styles()
        update_bubble_widths()
        schedule_save_ui_prefs()
        page.update()

    tool_web_search_switch.on_change = apply_tool_toggles
    tool_fs_switch.on_change = apply_tool_toggles
    tool_files_max_bytes_apply_button.on_click = apply_file_tool_limit
    autostart_model_switch.on_change = apply_autostart_model
    power_apply_button.on_click = apply_power_calibration
    llama_args_apply_button.on_click = apply_llama_args
    appearance_apply_button.on_click = apply_appearance
    apply_tool_toggles()

    tools_tab = view_tools.build_tools_tab(
        tool_web_search_switch=tool_web_search_switch,
        web_search_backoff_label=web_search_backoff_label,
        tool_fs_switch=tool_fs_switch,
        files_dir_button=files_dir_button,
        files_dir_home_button=files_dir_home_button,
        files_dir_desktop_button=files_dir_desktop_button,
        files_dir_project_button=files_dir_project_button,
        files_dir_label=files_dir_label,
        tool_files_max_bytes_field=tool_files_max_bytes_field,
        tool_files_max_bytes_apply_button=tool_files_max_bytes_apply_button,
        text_primary=TEXT_PRIMARY,
        text_muted=TEXT_MUTED,
    )

    settings_tab = view_settings.build_settings_tab(
        theme_dropdown=theme_dropdown,
        density_dropdown=density_dropdown,
        appearance_apply_button=appearance_apply_button,
        assistant_name_field=assistant_name_field,
        assistant_tone_field=assistant_tone_field,
        temperature_field=temperature_field,
        max_tokens_field=max_tokens_field,
        top_p_field=top_p_field,
        top_k_field=top_k_field,
        stop_sequences_field=stop_sequences_field,
        llama_args_field=llama_args_field,
        llama_args_apply_button=llama_args_apply_button,
        llama_args_restart_switch=llama_args_restart_switch,
        llama_args_note=llama_args_note,
        llama_restart_needed_label=llama_restart_needed_label,
        llama_status_label=llama_status_label,
        llama_running_args_label=llama_running_args_label,
        llama_cmdline_label=llama_cmdline_label,
        backend_settings_note_settings=backend_settings_note_settings,
        power_idle_field=power_idle_field,
        power_max_field=power_max_field,
        power_apply_button=power_apply_button,
        surface=SURFACE,
        border=BORDER,
        text_muted=TEXT_MUTED,
    )

    keyboard_tab = view_keyboard.build_keyboard_tab(
        keyboard_last_event_label=keyboard_last_event_label,
        surface=SURFACE,
        border=BORDER,
        text_primary=TEXT_PRIMARY,
        text_muted=TEXT_MUTED,
    )

    shell = ui_shell.build_shell(
        page=page,
        app_title=APP_TITLE,
        colors=shell_colors,
        sidebar_width=SIDEBAR_WIDTH,
        chat_tab=chat_tab,
        models_tab=models_tab,
        sessions_tab=sessions_tab,
        tools_tab=tools_tab,
        settings_tab=settings_tab,
        keyboard_tab=keyboard_tab,
        model_dropdown=model_dropdown,
        refresh_models_button=refresh_models_button,
        switch_model_button=switch_model_button,
        palette_button=palette_button,
        model_status_dot=model_status_dot,
        model_switch_spinner=model_switch_spinner,
        search_status_dot=search_status_dot,
        power_pill=power_pill,
        ram_pill=ram_pill,
        cpu_pill=cpu_pill,
        temp_pill=temp_pill,
        vram_pill=vram_pill,
        session_filter_field=session_filter_field,
        sidebar_sessions_list=sidebar_sessions_list,
        on_new_chat=new_chat,
        primary_button_style=primary_button_style,
        update_bubble_widths=update_bubble_widths,
        handle_key_event=handle_key_event,
    )
    content_holder = shell["content_holder"]
    sidebar_container = shell["sidebar_container"]
    main_container = shell["main_container"]
    top_bar = shell["top_bar"]
    hamburger_button = shell["hamburger_button"]
    sidebar_visible = shell["sidebar_visible"]
    nav_refs = shell["nav_refs"]
    set_view = shell["set_view"]
    toggle_sidebar = shell["toggle_sidebar"]
    update_nav_styles = shell["update_nav_styles"]
    apply_responsive_layout = shell["apply_responsive_layout"]
    on_resize = shell["on_resize"]
    root_control = shell["root_control"]

    page.on_resize = on_resize
    session_filter_field.on_change = lambda _: load_sessions()

    page.add(root_control)
    apply_responsive_layout()
    set_view(0)

    def update_status_pill(pill, text, severity):
        pill.bgcolor = _status_color(severity)
        txt_color = _status_text_color(severity)
        if isinstance(getattr(pill, "data", None), dict):
            label_text = pill.data.get("label_text")
            value_text = pill.data.get("value_text")
            if isinstance(label_text, ft.Text):
                label_text.color = txt_color
            if isinstance(value_text, ft.Text):
                value_text.value = text
                value_text.color = txt_color
                return
        if isinstance(pill.content, ft.Text):
            pill.content.value = text
            pill.content.color = txt_color

    load_sessions()
    refresh_models()
    refresh_files_dir()
    refresh_backend_settings()
    update_doc_list()
    update_details_visibility()
    update_send_state()
    try:
        update_context_stats()
    except Exception:
        pass

    ui_pollers.start_pollers(
        health=dict(
            page=page,
            ui_call=_ui_call,
            state=state,
            model_server_url=MODEL_SERVER_URL,
            search_api_url=SEARCH_API_URL,
            model_status_dot=model_status_dot,
            model_switch_spinner=model_switch_spinner,
            search_status_dot=search_status_dot,
            web_search_backoff_label=web_search_backoff_label,
            update_send_state=update_send_state,
            show_snack=show_snack,
            healthcheck_interval_ms=HEALTHCHECK_INTERVAL_MS,
            success_color=SUCCESS,
            warning_color=WARNING,
            danger_color=DANGER,
        ),
        telemetry=dict(
            page=page,
            ui_call=_ui_call,
            search_api_url=SEARCH_API_URL,
            update_status_pill=update_status_pill,
            power_pill=power_pill,
            ram_pill=ram_pill,
            cpu_pill=cpu_pill,
            temp_pill=temp_pill,
            vram_pill=vram_pill,
            format_bytes=_format_bytes,
            telemetry_interval_ms=POWER_POLL_INTERVAL_MS,
        ),
    )


if __name__ == "__main__":
    ft.app(target=main)
