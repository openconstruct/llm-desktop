from __future__ import annotations

import json
import threading
import time
from dataclasses import dataclass

import flet as ft
import requests


@dataclass
class ChatContext:
    page: ft.Page
    state: dict


    input_field: ft.TextField
    max_tokens_field: ft.TextField
    temperature_field: ft.TextField
    top_p_field: ft.TextField
    top_k_field: ft.TextField
    stop_sequences_field: ft.TextField

    perf_row: ft.Row


    text_muted: str
    surface: str
    warning: str
    danger: str
    secondary_button_style: ft.ButtonStyle


    model_server_url: str
    stream_connect_timeout_s: float
    stream_read_timeout_s: float | None


    ui_call: callable
    show_snack: callable
    update_send_state: callable
    update_perf_stats: callable

    add_message: callable
    build_context_block: callable
    format_prompt: callable
    render_markdown: callable

    estimate_tokens: callable
    strip_prompt_echo: callable
    parse_tool_call: callable
    extract_first_json_object: callable | None
    strip_emoji: callable

    backend_tools: object
    chars_per_token: int

    active_stream: dict
    active_stream_lock: threading.Lock


def send_message(ctx: ChatContext, _=None) -> None:
    state = ctx.state
    page = ctx.page
    input_field = ctx.input_field

    if not input_field.value.strip() and not state["loaded_documents"]:
        ctx.show_snack("Message cannot be empty.", ctx.warning)
        return
    if state.get("switching_model"):
        ctx.show_snack("Switching model, please wait...", ctx.warning)
        return
    if not state.get("model_online"):
        ctx.show_snack("Model offline. Wait for it to come online (or switch models).", ctx.warning)
        return
    if not state.get("model_ready"):
        ctx.show_snack("Model not ready yet (still starting).", ctx.warning)
        return
    if state["streaming"]:
        ctx.show_snack("Wait for the current response to finish.", ctx.warning)
        return

    user_text = input_field.value.strip()
    user_display = user_text or ""
    context_text = ctx.build_context_block(user_text, consume_search=True)

    if state["loaded_documents"] and not user_text:
        user_display = "📎 Documents attached"
    elif state["loaded_documents"]:
        user_display = f"📎 Documents attached\n\n{user_text}"

    ctx.add_message("user", user_display, llm_content=context_text)
    input_field.value = ""
    ctx.update_send_state()

    model_msg = ctx.add_message("model", "")
    state["streaming"] = True
    state["cancel_event"].clear()
    ctx.update_send_state()

    def render_markdown_for(msg: dict) -> None:
        try:
            md = ctx.render_markdown(msg.get("display_content") or msg.get("content") or "")
            block = msg.get("content_block")
            if block is not None:
                block.content = md
                msg["control"] = md
                msg["render_mode"] = "markdown"
                block.update()
        except Exception:
            pass

    def stream_completion_into(model_msg_: dict) -> dict:
        cancel_event = state["cancel_event"]
        model_control = model_msg_["control"]
        start_time = time.perf_counter()
        first_token_time = None
        chars = 0
        was_cancelled = False
        pending_display = ""
        pending_raw = ""
        last_flush = 0.0
        saw_tool_call = {"value": False}
        tool_call_detected = {"value": False}

        def flush_pending() -> None:
            nonlocal pending_display, pending_raw
            if pending_display:
                to_add_display = pending_display
                pending_display = ""

                def flush_tail():
                    raw = (model_msg_.get("display_raw") or "") + to_add_display
                    model_msg_["display_raw"] = raw
                    sanitized = ctx.strip_prompt_echo(raw)
                    model_control.value = sanitized
                    model_msg_["display_content"] = sanitized
                    tok = model_msg_.get("token_label")
                    if isinstance(tok, ft.Text):
                        tok.value = f"~{ctx.estimate_tokens(sanitized)} tok"
                        try:
                            tok.update()
                        except Exception:
                            pass
                    model_control.update()

                ctx.ui_call(page, flush_tail)
            if pending_raw:
                model_msg_["content"] = (model_msg_.get("content") or "") + pending_raw
                pending_raw = ""

        max_retries = 2
        attempt = 0
        last_err = None
        loading_deadline = time.time() + 180.0
        loading_notified = False

        def tool_status_text_for(name: str) -> str:
            if name == "web_search":
                return "Searching the web..."
            if name == "fs_list":
                return "Listing files..."
            if name == "fs_search":
                return "Searching files..."
            if name == "fs_read":
                return "Reading file..."
            if name == "fs_write":
                return "Writing file..."
            return "Running tool..."

        while attempt <= max_retries:
            if cancel_event.is_set():
                was_cancelled = True
                break
            if attempt > 0:
                ctx.ui_call(page, lambda: ctx.show_snack(f"Stream interrupted; reconnecting (attempt {attempt}/{max_retries})...", ctx.warning))

            prompt = ctx.format_prompt()
            if attempt > 0 and prompt.endswith("\nASSISTANT:"):
                prompt = prompt[:-len("\nASSISTANT:")] + "\nSYSTEM: Previous stream disconnected. Continue from where you left off without repeating.\nASSISTANT:"
            max_pred = int(float(ctx.max_tokens_field.value or 1024))
            tokens_so_far = max(0, int(chars / int(ctx.chars_per_token or 4))) if chars else 0
            remaining = max(16, max_pred - tokens_so_far)
            payload = {
                "prompt": prompt,
                "stream": True,
                "temperature": float(ctx.temperature_field.value or 0.7),
                "top_p": float(ctx.top_p_field.value or 0.95),
                "top_k": int(float(ctx.top_k_field.value or 40)),
                "n_predict": remaining,
                "stop": [s.strip() for s in (ctx.stop_sequences_field.value or "").split(",") if s.strip()],
            }

            response = None
            try:
                response = requests.post(
                    f"{ctx.model_server_url}/completion",
                    json=payload,
                    stream=True,
                    timeout=(ctx.stream_connect_timeout_s, ctx.stream_read_timeout_s),
                )
                with ctx.active_stream_lock:
                    ctx.active_stream["response"] = response
                response.encoding = "utf-8"
                if not response.ok:
                    detail = (response.text or "").strip()
                    if response.status_code == 503 and ("loading model" in detail.lower() or "unavailable_error" in detail.lower()):
                        state["model_loading"] = True
                        state["model_ready"] = False
                        if state.get("model_loading_since") is None:
                            state["model_loading_since"] = time.time()
                            state["model_loading_error_shown"] = False
                        if not loading_notified:
                            loading_notified = True
                            ctx.ui_call(page, lambda: ctx.show_snack("Model is loading... waiting.", ctx.warning))
                        try:
                            response.close()
                        except Exception:
                            pass
                        if cancel_event.is_set():
                            was_cancelled = True
                            break
                        if time.time() > loading_deadline:
                            raise RuntimeError("Model is still loading (timeout).")
                        time.sleep(0.5)
                        continue
                    reason = response.reason or "Bad request"
                    raise RuntimeError(f"Completion error {response.status_code}: {detail or reason}")

                state["model_loading"] = False
                state["model_ready"] = True

                for raw_line in response.iter_lines(decode_unicode=False):
                    if cancel_event.is_set():
                        was_cancelled = True
                        break
                    if not raw_line:
                        continue
                    try:
                        line = raw_line.decode("utf-8", errors="replace").strip()
                    except Exception:
                        line = str(raw_line).strip()
                    if not line.startswith("data: "):
                        continue
                    chunk = json.loads(line[6:])
                    content = chunk.get("content", "")
                    if not content:
                        continue

                    if first_token_time is None:
                        first_token_time = time.perf_counter()

                    raw_content = content
                    display_chunk = ctx.strip_emoji(raw_content) if state.get("strip_emoji") else raw_content
                    chars += len(raw_content)
                    pending_display += display_chunk
                    pending_raw += raw_content

                    if not saw_tool_call["value"]:
                        combined = (model_msg_.get("content") or "") + pending_raw
                        tool_call = ctx.parse_tool_call((combined or "").strip())
                        if tool_call:
                            extractor = ctx.extract_first_json_object
                            tool_json = extractor((combined or "").strip()) if callable(extractor) else None
                            if tool_json:
                                tool_name = tool_call.get("tool") or "tool"
                                status = tool_status_text_for(tool_name)
                                saw_tool_call["value"] = True
                                model_msg_["tool_call_raw"] = tool_json

                                def mark_tool_call_early():
                                    model_msg_["role"] = "tool_call"
                                    model_msg_["content"] = status
                                    model_msg_["display_content"] = status
                                    model_msg_["display_raw"] = status
                                    ctl = model_msg_.get("control")
                                    if ctl is not None and hasattr(ctl, "value"):
                                        ctl.value = status
                                        try:
                                            ctl.update()
                                        except Exception:
                                            pass
                                    block = model_msg_.get("content_block")
                                    if block is not None:
                                        try:
                                            block.content = ft.Text(status, color=ctx.text_muted)
                                            block.update()
                                        except Exception:
                                            pass

                                ctx.ui_call(page, mark_tool_call_early)

                                tool_call_detected["value"] = True
                                pending_display = ""
                                pending_raw = ""
                                try:
                                    response.close()
                                except Exception:
                                    pass
                                break

                    now = time.perf_counter()
                    if (now - last_flush) >= 0.05:
                        last_flush = now
                        flush_pending()

                flush_pending()
                break

            except Exception as exc:
                flush_pending()
                if cancel_event.is_set():
                    was_cancelled = True
                    break
                last_err = exc
                transient = isinstance(exc, requests.exceptions.RequestException)
                if transient and attempt < max_retries:
                    attempt += 1
                    try:
                        if response is not None:
                            response.close()
                    except Exception:
                        pass
                    continue
                break
            finally:
                with ctx.active_stream_lock:
                    if ctx.active_stream.get("response") is response:
                        ctx.active_stream["response"] = None
                try:
                    if response is not None:
                        response.close()
                except Exception:
                    pass

        end_time = time.perf_counter()
        gen_ms = max(0.0, (end_time - (first_token_time or start_time)) * 1000)
        tokens = max(1, int(chars / int(ctx.chars_per_token or 4))) if chars else 0
        state["session_tokens"] += tokens
        state["session_gen_time_ms"] += gen_ms
        flush_pending()

        return {

            "was_cancelled": bool(was_cancelled),
            "error": str(last_err) if (last_err and not was_cancelled) else None,
            "ttft": f"{(first_token_time - start_time):.2f}s" if first_token_time else "-",
            "gen_seconds": end_time - start_time,
            "chars": chars,
            "tokens": tokens,
        }

    def agent_worker() -> None:
        tool_budget = 8
        try:
            current_model_msg = model_msg
            while True:
                stats = stream_completion_into(current_model_msg)
                if stats.get("error"):
                    ctx.ui_call(page, lambda: ctx.show_snack(f"Stream error: {stats['error']}", ctx.danger))
                    ctx.ui_call(page, lambda: render_markdown_for(current_model_msg))
                    break
                if stats.get("was_cancelled"):
                    ctx.ui_call(page, lambda: render_markdown_for(current_model_msg))
                    break

                raw_out = (current_model_msg.get("tool_call_raw") or current_model_msg.get("content") or "").strip()
                tool_call = ctx.parse_tool_call(raw_out)
                if tool_call and tool_budget <= 0:
                    def mark_budget_exceeded():
                        current_model_msg["role"] = "tool_call"
                        msg = "Tool budget exceeded for this message. Send a new message to continue."
                        ctl = current_model_msg.get("control")
                        if ctl is not None and hasattr(ctl, "value"):
                            ctl.value = msg
                            try:
                                ctl.update()
                            except Exception:
                                pass
                        block = current_model_msg.get("content_block")
                        if block is not None:
                            try:
                                block.content = ft.Text(msg, color=ctx.text_muted)
                                block.update()
                            except Exception:
                                pass

                    ctx.ui_call(page, mark_budget_exceeded)
                    break

                if tool_call and tool_budget > 0:
                    tool_budget -= 1
                    tool_name = tool_call.get("tool") or "tool"

                    def tool_status_text() -> str:
                        if tool_name == "web_search":
                            return "Searching the web..."
                        if tool_name == "fs_list":
                            return "Listing files..."
                        if tool_name == "fs_read":
                            return "Reading file..."
                        if tool_name == "fs_write":
                            return "Writing file..."
                        if tool_name == "fs_search":
                            return "Searching files..."
                        return "Running tool..."

                    def mark_tool_call():
                        status = tool_status_text()
                        current_model_msg["role"] = "tool_call"
                        current_model_msg["tool_call_raw"] = raw_out
                        current_model_msg["content"] = status
                        current_model_msg["display_content"] = status
                        current_model_msg["display_raw"] = status
                        ctl = current_model_msg.get("control")
                        if ctl is not None and hasattr(ctl, "value"):
                            ctl.value = status
                            try:
                                ctl.update()
                            except Exception:
                                pass
                        block = current_model_msg.get("content_block")
                        if block is not None:
                            try:
                                block.content = ft.Text(status, color=ctx.text_muted)
                                block.update()
                            except Exception:
                                pass

                    ctx.ui_call(page, mark_tool_call)

                    try:
                        if tool_name == "web_search":
                            if not state.get("tool_web_search_enabled", True):
                                raise RuntimeError("Tool disabled: web_search (enable it in the Tools tab).")
                            md, tool_ctx = ctx.backend_tools.web_search(state, tool_call["args"]["query"], tool_call["args"]["count"])
                        elif tool_name == "fs_list":
                            if not state.get("tool_fs_enabled", True):
                                raise RuntimeError("Tool disabled: file tools (enable them in the Tools tab).")
                            md, tool_ctx = ctx.backend_tools.fs_list(
                                tool_call["args"].get("path", "."),
                                tool_call["args"].get("recursive", False),
                                tool_call["args"].get("limit", 200),
                            )
                        elif tool_name == "fs_search":
                            if not state.get("tool_fs_enabled", True):
                                raise RuntimeError("Tool disabled: file tools (enable them in the Tools tab).")
                            md, tool_ctx = ctx.backend_tools.fs_search(
                                tool_call["args"].get("query", ""),
                                tool_call["args"].get("path", "."),
                                tool_call["args"].get("limit", 50),
                                tool_call["args"].get("regex", False),
                                tool_call["args"].get("case_sensitive", False),
                            )
                        elif tool_name == "fs_read":
                            if not state.get("tool_fs_enabled", True):
                                raise RuntimeError("Tool disabled: file tools (enable them in the Tools tab).")
                            try:
                                cap_bytes = int(state.get("tool_files_max_bytes") or 200000)
                            except Exception:
                                cap_bytes = 200000
                            cap_bytes = max(10_000, min(10_000_000, cap_bytes))
                            requested = tool_call["args"].get("max_bytes", cap_bytes)
                            try:
                                requested = int(requested)
                            except Exception:
                                requested = cap_bytes
                            requested = max(1000, min(cap_bytes, requested))
                            md, tool_ctx = ctx.backend_tools.fs_read(tool_call["args"]["path"], requested)
                        elif tool_name == "fs_write":
                            if not state.get("tool_fs_enabled", True):
                                raise RuntimeError("Tool disabled: file tools (enable them in the Tools tab).")
                            req_path = tool_call["args"]["path"]
                            req_content = tool_call["args"]["content"]
                            overwrite_requested = bool(tool_call["args"].get("overwrite", False))

                            def _prompt_write_conflict(rel_path: str) -> str:
                                note = "The model requested overwrite=true." if overwrite_requested else "The model requested overwrite=false."
                                decision = {"value": None}
                                evt = threading.Event()

                                def show_dialog():
                                    def choose(val: str):
                                        decision["value"] = val
                                        try:
                                            dlg.open = False
                                            page.update()
                                        except Exception:
                                            pass
                                        evt.set()

                                    dlg = ft.AlertDialog(
                                        modal=True,
                                        title=ft.Text("File already exists"),
                                        content=ft.Text(f"`{rel_path}` already exists.\n\n{note}\n\nWhat should I do?"),
                                        actions=[
                                            ft.TextButton("Cancel", on_click=lambda _: choose("cancel")),
                                            ft.OutlinedButton("Save .bak", on_click=lambda _: choose("bak"), style=ctx.secondary_button_style),
                                            ft.ElevatedButton(
                                                "Overwrite",
                                                on_click=lambda _: choose("overwrite"),
                                                style=ft.ButtonStyle(bgcolor=ctx.danger, color=ctx.surface),
                                            ),
                                        ],
                                        actions_alignment=ft.MainAxisAlignment.END,
                                    )
                                    page.dialog = dlg
                                    dlg.open = True
                                    page.update()

                                ctx.ui_call(page, show_dialog)
                                evt.wait(timeout=180)
                                return decision["value"] or "cancel"

                            def _write_unique_bak(rel_path: str, content: str):
                                for n in range(0, 50):
                                    suffix = ".bak" if n == 0 else f".bak.{n}"
                                    candidate = f"{rel_path}{suffix}"
                                    try:
                                        return ctx.backend_tools.fs_write(candidate, content, overwrite=False)
                                    except Exception as exc:
                                        msg = str(exc)
                                        if "overwrite=false" in msg or "File exists" in msg:
                                            continue
                                        raise
                                raise RuntimeError("Unable to find an available .bak filename after 50 attempts.")

                            try:
                                md, tool_ctx = ctx.backend_tools.fs_write(req_path, req_content, overwrite=False)
                            except Exception as exc:
                                msg = str(exc)
                                if "overwrite=false" not in msg and "File exists" not in msg:
                                    raise
                                choice = _prompt_write_conflict(req_path)
                                if choice == "overwrite":
                                    md, tool_ctx = ctx.backend_tools.fs_write(req_path, req_content, overwrite=True)
                                elif choice == "bak":
                                    md, tool_ctx = _write_unique_bak(req_path, req_content)
                                else:
                                    md = f"## Write cancelled\nDid not write `{req_path}`."
                                    tool_ctx = f"FILE WRITE CANCELLED: {req_path}"
                        else:
                            raise RuntimeError(f"Unsupported tool: {tool_name}")

                        ctx.ui_call(
                            page,
                            lambda: ctx.add_message(
                                "tool",
                                md,
                                llm_content=tool_ctx or md,
                                tool_name=tool_name,
                                show_in_chat=(tool_name not in ("fs_list",)),
                            ),
                        )
                    except Exception as exc:
                        ctx.ui_call(page, lambda: ctx.add_message("tool", f"## Tool error\n{exc}", tool_name=tool_name))

                    def new_assistant_msg():
                        return ctx.add_message("model", "")

                    current_model_msg_box = {"value": None}

                    def create():
                        current_model_msg_box["value"] = new_assistant_msg()

                    ctx.ui_call(page, create)
                    while current_model_msg_box["value"] is None:
                        time.sleep(0.01)
                    current_model_msg = current_model_msg_box["value"]
                    continue

                def finalize_render():
                    try:
                        md = ctx.render_markdown(current_model_msg.get("display_content") or current_model_msg.get("content") or "")
                        block = current_model_msg.get("content_block")
                        if block is not None:
                            block.content = md
                            current_model_msg["control"] = md
                            current_model_msg["render_mode"] = "markdown"
                            block.update()
                    except Exception:
                        pass

                    ctx.update_perf_stats(
                        stats.get("ttft") or "-",
                        float(stats.get("gen_seconds") or 0.0),
                        int(stats.get("chars") or 0),
                        int(stats.get("tokens") or 0),
                    )
                    ctx.update_send_state()
                    if stats.get("was_cancelled"):
                        ctx.show_snack("Generation stopped.", ctx.warning)
                    if ctx.perf_row.visible:
                        ctx.perf_row.update()

                ctx.ui_call(page, finalize_render)
                break
        except Exception as exc:
            def fail():
                state["streaming"] = False
                state["cancel_event"].clear()
                ctx.update_send_state()
                ctx.show_snack(f"Error: {exc}", ctx.danger)

            ctx.ui_call(page, fail)
        finally:
            def done():
                state["streaming"] = False
                state["cancel_event"].clear()
                ctx.update_send_state()

            ctx.ui_call(page, done)

    threading.Thread(target=agent_worker, daemon=True).start()
