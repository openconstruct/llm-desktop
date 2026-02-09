import json


def format_bytes(value) -> str:
    try:
        value = float(value)
    except (TypeError, ValueError):
        return "--"
    units = ["B", "KB", "MB", "GB", "TB"]
    idx = 0
    while value >= 1024 and idx < len(units) - 1:
        value /= 1024
        idx += 1
    return f"{value:.0f} {units[idx]}" if idx == 0 else f"{value:.1f} {units[idx]}"


def strip_emoji(text: str | None) -> str | None:
    if not text:
        return text
    stripped: list[str] = []
    for ch in text:
        code = ord(ch)
        if ch in ("\u200d", "\ufe0f", "\u20e3"):
            continue
        if (
            0x1F300 <= code <= 0x1FAFF
            or 0x1F1E6 <= code <= 0x1F1FF
            or 0x2600 <= code <= 0x26FF
            or 0x2700 <= code <= 0x27BF
            or 0x1F000 <= code <= 0x1F02F
        ):
            continue
        stripped.append(ch)
    return "".join(stripped)


def _strip_code_fences(text: str) -> str:
    raw = (text or "").strip()
    if raw.startswith("```") and raw.endswith("```"):

        lines = raw.splitlines()
        if len(lines) >= 3:
            inner = "\n".join(lines[1:-1]).strip()
            return inner
    return raw


def _extract_first_json_object(text: str) -> str | None:
    """
    Extract the first balanced JSON object substring from `text`.
    Supports raw JSON or fenced ```json blocks embedded in other text.
    """
    if not text:
        return None

    raw = text

    fence_idx = raw.find("```json")
    if fence_idx == -1:
        fence_idx = raw.find("```")
    if fence_idx != -1:
        tail = raw[fence_idx:]
        end = tail.find("```", 3)
        if end != -1:
            block = tail[: end + 3]
            inner = _strip_code_fences(block)
            if inner.startswith("{") and inner.endswith("}"):
                return inner


    s = raw
    start = s.find("{")
    if start == -1:
        return None
    in_str = False
    esc = False
    depth = 0
    for i in range(start, len(s)):
        ch = s[i]
        if in_str:
            if esc:
                esc = False
            elif ch == "\\":
                esc = True
            elif ch == "\"":
                in_str = False
            continue
        else:
            if ch == "\"":
                in_str = True
                continue
            if ch == "{":
                depth += 1
            elif ch == "}":
                depth -= 1
                if depth == 0:
                    return s[start : i + 1]
    return None


def _escape_raw_newlines_in_json_strings(raw: str) -> str:
    """
    Best-effort repair for a common model failure mode:
    emitting literal newlines inside JSON string values (invalid JSON).

    We only escape CR/LF characters that occur *inside* a quoted JSON string.
    """
    if not raw:
        return raw
    out: list[str] = []
    in_str = False
    esc = False
    for ch in raw:
        if in_str:
            if esc:
                esc = False
                out.append(ch)
                continue
            if ch == "\\":
                esc = True
                out.append(ch)
                continue
            if ch == "\"":
                in_str = False
                out.append(ch)
                continue
            if ch == "\r" or ch == "\n":
                out.append("\\n")
                continue
            out.append(ch)
            continue


        if ch == "\"":
            in_str = True
            out.append(ch)
            continue
        out.append(ch)

    return "".join(out)


def parse_tool_call(text: str):
    """
    Tool calls must be a single JSON object:
      {"tool":"web_search","args":{"query":"...","count":5}}
      {"tool":"fs_list","args":{"path":".","recursive":false,"limit":200}}
      {"tool":"fs_read","args":{"path":"notes/todo.txt","max_bytes":200000}}
      {"tool":"fs_write","args":{"path":"notes/todo.txt","content":"...","overwrite":true}}
      {"tool":"fs_search","args":{"query":"needle","path":".","limit":50,"regex":false,"case_sensitive":false}}
    """
    raw = _extract_first_json_object((text or "").strip())
    if not raw:
        return None
    try:
        obj = json.loads(raw)
    except Exception:


        fixed = _escape_raw_newlines_in_json_strings(raw)
        if fixed == raw:
            return None
        try:
            obj = json.loads(fixed)
        except Exception:
            return None
    if not isinstance(obj, dict):
        return None
    tool = obj.get("tool")
    args = obj.get("args")
    if not isinstance(args, dict):
        return None

    if tool == "web_search":
        query = args.get("query")
        if not isinstance(query, str) or not query.strip():
            return None
        count = args.get("count", 5)
        try:
            count = int(count)
        except Exception:
            count = 5
        count = max(1, min(10, count))
        return {"tool": "web_search", "args": {"query": query.strip(), "count": count}}

    if tool == "fs_list":
        path = args.get("path", ".")
        if not isinstance(path, str) or not path.strip():
            path = "."
        recursive = bool(args.get("recursive", False))
        limit = args.get("limit", 200)
        try:
            limit = int(limit)
        except Exception:
            limit = 200
        limit = max(1, min(1000, limit))
        return {"tool": "fs_list", "args": {"path": path.strip(), "recursive": recursive, "limit": limit}}

    if tool == "fs_read":
        path = args.get("path")
        if not isinstance(path, str) or not path.strip():
            return None
        max_bytes = args.get("max_bytes", 200000)
        try:
            max_bytes = int(max_bytes)
        except Exception:
            max_bytes = 200000
        max_bytes = max(1, min(5_000_000, max_bytes))
        return {"tool": "fs_read", "args": {"path": path.strip(), "max_bytes": max_bytes}}

    if tool == "fs_write":
        path = args.get("path")
        content = args.get("content")
        content_lines = args.get("content_lines")
        if not isinstance(path, str) or not path.strip():
            return None
        if isinstance(content, list) and all(isinstance(x, str) for x in content):
            content = "\n".join(content)
        elif (content is None) and isinstance(content_lines, list) and all(isinstance(x, str) for x in content_lines):
            content = "\n".join(content_lines)
        if not isinstance(content, str):
            return None
        overwrite = bool(args.get("overwrite", True))
        return {"tool": "fs_write", "args": {"path": path.strip(), "content": content, "overwrite": overwrite}}

    if tool == "fs_search":
        query = args.get("query")
        if not isinstance(query, str) or not query.strip():
            return None
        path = args.get("path", ".")
        if not isinstance(path, str) or not path.strip():
            path = "."
        limit = args.get("limit", 50)
        try:
            limit = int(limit)
        except Exception:
            limit = 50
        limit = max(1, min(500, limit))
        regex = bool(args.get("regex", False))
        case_sensitive = bool(args.get("case_sensitive", False))
        return {
            "tool": "fs_search",
            "args": {
                "query": query.strip(),
                "path": path.strip(),
                "limit": limit,
                "regex": regex,
                "case_sensitive": case_sensitive,
            },
        }

    return None
