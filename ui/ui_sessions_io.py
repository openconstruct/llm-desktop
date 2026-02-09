import json
import time
from pathlib import Path
import html


def build_session_payload(messages: list[dict]) -> dict:
    return {
        "messages": [
            {
                "role": msg.get("role"),
                "content": msg.get("content"),
                "llm_content": msg.get("llm_content"),
                "timestamp": msg.get("timestamp"),
            }
            for msg in (messages or [])
        ]
    }


def read_json(path: str | Path) -> dict:
    p = Path(path)
    data = json.loads(p.read_text(encoding="utf-8"))
    if isinstance(data, dict):
        return data
    return {"messages": []}


def write_json(path: str | Path, payload: dict) -> None:
    p = Path(path)
    p.write_text(json.dumps(payload, indent=2), encoding="utf-8")


def safe_filename(raw_name: str) -> str:
    raw = (raw_name or "").strip() or "session"
    return "".join(ch if ch.isalnum() or ch in ("-", "_") else "_" for ch in raw)


def export_session_text(payload: dict, raw_name: str, assistant_name: str, fmt: str) -> tuple[str, str]:
    fmt = (fmt or "json").strip().lower()
    if fmt not in ("json", "md", "txt", "html"):
        fmt = "json"

    def iter_msgs():
        for m in (payload.get("messages") or []):
            role = (m.get("role") or "").strip()
            content = m.get("content") or ""
            ts = (m.get("timestamp") or "").strip()
            if role == "tool_call":
                continue
            yield role, ts, content

    if fmt == "json":
        return "json", json.dumps(payload, indent=2)

    assistant_hdr = " ".join(str(assistant_name or "Assistant").split())[:80] or "Assistant"

    if fmt == "txt":
        lines = [raw_name, ""]
        for role, ts, content in iter_msgs():
            hdr = "USER" if role == "user" else ("ASSISTANT" if role == "model" else role.upper())
            if role == "model":
                hdr = f"{assistant_hdr.upper()}"
            if ts:
                hdr = f"{hdr} [{ts}]"
            lines.append(hdr)
            lines.append(str(content).rstrip())
            lines.append("")
        return "txt", "\n".join(lines).rstrip() + "\n"

    if fmt == "md":
        lines = [f"# {raw_name}", ""]
        for role, ts, content in iter_msgs():
            hdr = "User" if role == "user" else (assistant_hdr if role == "model" else role.title() or "Message")
            if ts:
                lines.append(f"## {hdr} ({ts})")
            else:
                lines.append(f"## {hdr}")
            lines.append("")
            lines.append(str(content).rstrip())
            lines.append("")
        return "md", "\n".join(lines).rstrip() + "\n"


    parts = [
        "<!doctype html>",
        "<html><head><meta charset=\"utf-8\"/>",
        f"<title>{html.escape(raw_name)}</title>",
        "<style>body{font-family:system-ui,Segoe UI,Roboto,Arial,sans-serif;max-width:900px;margin:24px auto;padding:0 16px;line-height:1.4}pre{white-space:pre-wrap;background:#0f172a;color:#e5e7eb;border:1px solid #334155;border-radius:10px;padding:12px}h1,h2{color:#0f172a}</style>",
        "</head><body>",
        f"<h1>{html.escape(raw_name)}</h1>",
    ]
    for role, ts, content in iter_msgs():
        hdr = "User" if role == "user" else ("Assistant" if role == "model" else role.title() or "Message")
        title = f"{hdr} ({ts})" if ts else hdr
        parts.append(f"<h2>{html.escape(title)}</h2>")
        parts.append(f"<pre>{html.escape(str(content).rstrip())}</pre>")
    parts.append("</body></html>")
    return "html", "\n".join(parts) + "\n"


def new_session_id() -> str:
    return str(int(time.time() * 1000))

