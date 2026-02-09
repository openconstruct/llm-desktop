import time


def estimate_tokens(text: str, chars_per_token: int = 4) -> int:
    if not text:
        return 0
    try:
        cpt = int(chars_per_token)
        if cpt <= 0:
            cpt = 4
        return max(0, int(len(text) / cpt))
    except Exception:
        return 0


def build_context_block(
    *,
    loaded_documents: list[dict],
    pending_search_contexts: list[str],
    user_text: str,
    max_text_file_embed_size: int,
    consume_search: bool = True,
) -> tuple[str, list[str]]:
    context: list[str] = []

    if loaded_documents:
        context.append("Loaded Documents:")
        for doc in loaded_documents:
            name = doc.get("name") or "Unknown file"
            if doc.get("error"):
                context.append(f"[File: {name} - ERROR: {doc.get('error')}]")
                continue
            context.append(f"[File: {name} ({doc.get('type') or 'unknown'})]")
            content = doc.get("content")
            if content and len(content) < int(max_text_file_embed_size or 0):
                context.append("Content:\n---\n" + content + "\n---")
            elif content:
                context.append("(File content too large to embed)")
            else:
                context.append("(Binary file not embedded)")
        context.append("")

    out_pending = list(pending_search_contexts or [])
    if out_pending:
        context.append("Web Search Results:")
        for idx, ctx in enumerate(out_pending, start=1):
            context.append(f"Search {idx}:\n{ctx}")
        context.append("")
        if consume_search:
            out_pending = []

    prefix = ("\n".join(context) + "\n") if context else ""
    return prefix + (user_text or "(no text)"), out_pending


def format_prompt(state: dict, messages: list[dict] | None = None) -> str:
    parts: list[str] = []

    raw_name = str(state.get("assistant_name") or "Assistant").strip()
    raw_tone = str(state.get("assistant_tone") or "helpful").strip()
    safe_name = " ".join(raw_name.split())[:80] or "Assistant"
    safe_tone = " ".join(raw_tone.split())[:120] or "helpful"

    parts.append(f"SYSTEM: You are {safe_name}, a helpful assistant with a {safe_tone} tone.")
    parts.append(f"SYSTEM: Current date/time is {time.strftime('%Y-%m-%d %H:%M')}.")
    parts.append("SYSTEM: Format your normal responses in Markdown when it helps readability (headings, lists, code blocks, tables).")
    parts.append("SYSTEM: Do not wrap the entire response in a single code fence.")

    files_root = (state.get("files_tool_dir") or "").strip()
    parts.append(f"SYSTEM: File tool root directory is: {files_root or '(not configured)'}")

    enabled: list[str] = []
    if state.get("tool_web_search_enabled"):
        enabled.append("web_search")
    if state.get("tool_fs_enabled"):
        enabled.append("fs_list/fs_read/fs_write/fs_search")
    enabled_txt = ", ".join(enabled) if enabled else "(none)"

    tool_lines: list[str] = []
    tool_lines.append("SYSTEM: You can use tools by emitting a JSON tool call. These JSON objects are commands for you (the assistant).")
    tool_lines.append("SYSTEM: The app will execute the tool call and then provide the result back to you as a TOOL[tool_name] message.")
    tool_lines.append("SYSTEM: If you need to use a tool, respond with EXACTLY one JSON object and nothing else.")
    tool_lines.append("SYSTEM: Do NOT include any prose like 'Sure, here is the JSON'. Do NOT wrap the JSON in Markdown code fences.")
    tool_lines.append("SYSTEM: The JSON must be valid JSON.")
    tool_lines.append(f"SYSTEM: Enabled tools (UI): {enabled_txt}")
    tool_lines.append("SYSTEM: Supported tools:")

    if state.get("tool_web_search_enabled"):
        tool_lines.append("SYSTEM: - web_search")
        tool_lines.append("SYSTEM:   Use this to look things up online (current events, facts, docs, troubleshooting).")
        tool_lines.append("SYSTEM:   Format: {\"tool\":\"web_search\",\"args\":{\"query\":\"...\",\"count\":5}}")

    if state.get("tool_fs_enabled"):
        try:
            file_tool_max_bytes = int(state.get("tool_files_max_bytes") or 200000)
        except Exception:
            file_tool_max_bytes = 200000
        file_tool_max_bytes = max(10_000, min(10_000_000, file_tool_max_bytes))

        tool_lines.append("SYSTEM: - fs_list")
        tool_lines.append("SYSTEM:   You can list files and folders under the file tool root directory using fs_list.")
        tool_lines.append("SYSTEM:   Format: {\"tool\":\"fs_list\",\"args\":{\"path\":\".\",\"recursive\":false,\"limit\":200}}")
        tool_lines.append("SYSTEM:   Tip: Keep limit small (e.g. 50-200) and avoid recursive=true unless you truly need it.")

        tool_lines.append("SYSTEM: - fs_read")
        tool_lines.append("SYSTEM:   You can read a file's contents under the file tool root directory using fs_read.")
        tool_lines.append(f"SYSTEM:   Format: {{\"tool\":\"fs_read\",\"args\":{{\"path\":\"relative/path.txt\",\"max_bytes\":{file_tool_max_bytes}}}}}")
        tool_lines.append("SYSTEM:   Tip: Use a small max_bytes when possible to keep context small and fast.")

        tool_lines.append("SYSTEM: - fs_write")
        tool_lines.append("SYSTEM:   You can write or update a file under the file tool root directory using fs_write (only when the user asks).")
        tool_lines.append("SYSTEM:   Format: {\"tool\":\"fs_write\",\"args\":{\"path\":\"relative/path.txt\",\"content\":\"...\",\"overwrite\":false}}")
        tool_lines.append("SYSTEM:   IMPORTANT: When the user asks you to create/modify a file, do not print the file contents in chat. Call fs_write.")
        tool_lines.append("SYSTEM:   For multi-line content, ensure valid JSON. Prefer using a single JSON string with \\n escapes, or provide content_lines:[\"line1\",\"line2\",...].")

        tool_lines.append("SYSTEM: - fs_search")
        tool_lines.append("SYSTEM:   You can search within files under the file tool root directory using fs_search.")
        tool_lines.append("SYSTEM:   Format: {\"tool\":\"fs_search\",\"args\":{\"query\":\"needle\",\"path\":\".\",\"limit\":50,\"regex\":false,\"case_sensitive\":false}}")

    tool_lines.append("SYSTEM: Rules:")
    tool_lines.append("SYSTEM: - Only call tools when necessary.")
    tool_lines.append("SYSTEM: - When calling a tool, output only the JSON object.")
    if state.get("tool_fs_enabled"):
        tool_lines.append("SYSTEM: - Paths for file tools must be RELATIVE to the configured file tool root directory.")
        tool_lines.append("SYSTEM: - Only use fs_write when the user explicitly asks you to create or modify files.")
        tool_lines.append("SYSTEM: - fs_write content must be a JSON string (escape newlines as \\n).")
        tool_lines.append("SYSTEM: - For fs_write, avoid surrounding the JSON with markdown fences or extra text.")
        tool_lines.append("SYSTEM: - fs_write will fail if the file already exists unless overwrite=true (you can also pick a new name like .bak).")
        tool_lines.append("SYSTEM: - Prefer fs_read before fs_write when editing an existing file.")
        tool_lines.append("SYSTEM: - If you are unsure about paths, call fs_list first.")
        tool_lines.append("SYSTEM: - Prefer fs_search before fs_read when locating where to edit.")
        tool_lines.append("SYSTEM: - Do not paste full fs_read contents into chat unless the user explicitly asks to see them.")
    tool_lines.append("SYSTEM: - Tool results will be provided in hidden context as TOOL[tool_name] messages. Do not repeat them verbatim; use them to answer normally.")
    tool_lines.append("SYSTEM: - Never output TOOL[...] yourself; that is an internal label.")

    parts.append("\n".join(tool_lines) + "\n")

    for msg in (messages if messages is not None else (state.get("messages") or [])):
        role = msg.get("role")
        if role == "user":
            text = msg.get("llm_content") if msg.get("llm_content") is not None else (msg.get("content") or "")
            ts = msg.get("timestamp", "--:--")
            parts.append(f"USER [{ts}]: {text}")
        elif role in ("search", "tool"):
            payload = msg.get("llm_content")
            if payload is None:
                payload = msg.get("content") or ""
            tool_name = msg.get("tool_name") or ("web_search" if role == "search" else "tool")
            parts.append(f"TOOL[{tool_name}]: {payload}")
        elif role == "tool_call":
            continue
        elif role == "model":
            ts = msg.get("timestamp", "--:--")
            text = msg.get("display_content")
            if text is None:
                text = msg.get("content") or ""
            parts.append(f"ASSISTANT [{ts}]: {text}")

    return "\n".join(parts) + "\nASSISTANT:"

