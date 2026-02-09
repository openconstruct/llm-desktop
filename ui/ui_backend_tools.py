import time
import requests


class BackendTools:
    def __init__(self, search_api_url: str, format_bytes_fn):
        self.search_api_url = (search_api_url or "").rstrip("/")
        self._format_bytes = format_bytes_fn

    def web_search(self, state: dict, query: str, count: int = 5) -> tuple[str, str]:
        if not query or not query.strip():
            raise RuntimeError("Search query cannot be empty.")
        if not state.get("api_online"):
            raise RuntimeError("Search API offline (red API dot). Start the app backend (`./ed.sh start`) and try again.")
        if not state.get("search_online"):
            if not state.get("search_enabled", True):
                backend = state.get("search_backend") or "unknown"
                err = (state.get("search_error") or "").strip()
                msg = f"Web search disabled on backend ({backend})."
                if err:
                    msg += f" {err}"
                msg += " Install `ddgs` in the search environment to enable web search."
                raise RuntimeError(msg)
            raise RuntimeError("Web search unavailable.")

        resp = requests.post(
            f"{self.search_api_url}/search/web",
            json={"query": query.strip(), "count": int(count or 5)},
            timeout=20,
        )
        if not resp.ok:
            try:
                detail = resp.json().get("detail")
            except Exception:
                detail = resp.text
            detail = (detail or "").strip() or "Unknown error"
            raise RuntimeError(detail)
        data = resp.json()
        cached = bool(data.get("cached", False))
        if data.get("error"):
            detail = str(data["error"])
            retry_after = data.get("retry_after_s")
            if isinstance(retry_after, (int, float)) and retry_after:
                state["search_rate_limited_until"] = time.time() + float(retry_after)
                detail = f"{detail}\n\nRetry after: {int(retry_after)}s"
            low = detail.lower()
            if "rate" in low or "429" in low or "too many" in low:
                detail = f"{detail}\n\nTip: DuckDuckGo is rate-limiting requests. Wait a bit and retry, or reduce frequency."
            raise RuntimeError(detail)

        results = data.get("results", []) or []
        q = query.strip()
        lines = [f"## Web search: {q}"]
        if cached:
            lines.append("")
            lines.append("*Cached:* yes")
        context_lines = []
        for idx, item in enumerate(results, start=1):
            title = item.get("name") or item.get("title") or item.get("url") or f"Result {idx}"
            url = item.get("url") or ""
            snippet = item.get("snippet") or item.get("content") or ""
            if url:
                lines.append(f"{idx}. [{title}](<{url}>)")
            else:
                lines.append(f"{idx}. {title}")
            if snippet:
                lines.append(snippet)
            lines.append("")
            context_lines.append(f"[{idx}] {title}\nURL: {url}\n{snippet}")
        return "\n".join(lines), "\n\n".join(context_lines).strip()

    def fs_list(self, path: str = ".", recursive: bool = False, limit: int = 200) -> tuple[str, str]:
        t0 = time.perf_counter()
        resp = requests.post(
            f"{self.search_api_url}/files/list",
            json={"path": path or ".", "recursive": bool(recursive), "limit": int(limit or 200)},
            timeout=20,
        )
        elapsed_ms = int((time.perf_counter() - t0) * 1000)
        if not resp.ok:
            try:
                detail = resp.json().get("detail")
            except Exception:
                detail = resp.text
            raise RuntimeError((detail or "File listing failed").strip())
        data = resp.json()
        base = data.get("base", ".") or "."
        entries = data.get("entries", []) or []
        truncated = bool(data.get("truncated", False))

        lines = [f"## Files: `{base}`", "", f"*Elapsed:* {elapsed_ms} ms", ""]
        ctx_lines = [f"FILES under {base}:"]
        for item in entries:
            rel = item.get("path") or ""
            is_dir = bool(item.get("is_dir"))
            size = item.get("size_bytes")
            suffix = "/" if is_dir else ""
            if is_dir:
                lines.append(f"- `{rel}{suffix}`")
                ctx_lines.append(f"- DIR  {rel}{suffix}")
            else:
                size_txt = self._format_bytes(size) if size is not None else "--"
                lines.append(f"- `{rel}{suffix}` ({size_txt})")
                ctx_lines.append(f"- FILE {rel} ({size_txt})")
        if truncated:
            lines.append("")
            lines.append(f"*Note: list truncated to {len(entries)} entries*")
            ctx_lines.append(f"(truncated to {len(entries)} entries)")
        return "\n".join(lines).strip(), "\n".join(ctx_lines).strip()

    def fs_read(self, path: str, max_bytes: int = 200000) -> tuple[str, str]:
        t0 = time.perf_counter()
        resp = requests.post(
            f"{self.search_api_url}/files/read",
            json={"path": path, "max_bytes": int(max_bytes or 200000)},
            timeout=20,
        )
        elapsed_ms = int((time.perf_counter() - t0) * 1000)
        if not resp.ok:
            try:
                detail = resp.json().get("detail")
            except Exception:
                detail = resp.text
            raise RuntimeError((detail or "File read failed").strip())
        data = resp.json()
        rel = data.get("path") or path
        content = data.get("content") or ""
        truncated = bool(data.get("truncated", False))
        bytes_read = int(data.get("bytes_read") or 0)

        lines = [
            f"## Read: `{rel}`",
            "",
            f"*Bytes read:* {bytes_read}{' (truncated)' if truncated else ''}",
            f"*Elapsed:* {elapsed_ms} ms",
            "",
            "_Loaded into context (not shown in chat)._",
        ]

        ctx = f"FILE READ: {rel}\n---\n{content}\n---"
        if truncated:
            ctx += "\n(TRUNCATED)"
        return "\n".join(lines), ctx

    def fs_write(self, path: str, content: str, overwrite: bool = False) -> tuple[str, str]:
        t0 = time.perf_counter()
        resp = requests.post(
            f"{self.search_api_url}/files/write",
            json={"path": path, "content": content or "", "overwrite": bool(overwrite), "mkdirs": True},
            timeout=20,
        )
        elapsed_ms = int((time.perf_counter() - t0) * 1000)
        if not resp.ok:
            try:
                detail = resp.json().get("detail")
            except Exception:
                detail = resp.text
            raise RuntimeError((detail or "File write failed").strip())
        data = resp.json()
        rel = data.get("path") or path
        bytes_written = int(data.get("bytes_written") or 0)
        backup_path = data.get("backup_path")
        message = (data.get("message") or "").strip()
        lines = [f"## Wrote: `{rel}`", "", f"*Bytes written:* {bytes_written}", f"*Elapsed:* {elapsed_ms} ms"]
        if backup_path:
            lines.append(f"*Backup:* `{backup_path}`")
        if message and message != "OK":
            lines.append(f"*Message:* {message}")

        ctx = f"FILE WROTE: {rel} ({bytes_written} bytes)"
        if backup_path:
            ctx += f"\nBACKUP: {backup_path}"
        return "\n".join(lines), ctx

    def fs_search(
        self,
        query: str,
        path: str = ".",
        limit: int = 50,
        regex: bool = False,
        case_sensitive: bool = False,
    ) -> tuple[str, str]:
        t0 = time.perf_counter()
        resp = requests.post(
            f"{self.search_api_url}/files/search",
            json={
                "query": query or "",
                "path": path or ".",
                "limit": int(limit or 50),
                "regex": bool(regex),
                "case_sensitive": bool(case_sensitive),
            },
            timeout=20,
        )
        elapsed_ms = int((time.perf_counter() - t0) * 1000)
        if not resp.ok:
            try:
                detail = resp.json().get("detail")
            except Exception:
                detail = resp.text
            raise RuntimeError((detail or "File search failed").strip())
        data = resp.json() or {}
        base = data.get("base") or "."
        matches = data.get("matches", []) or []
        truncated = bool(data.get("truncated", False))

        lines = [f"## File search: `{query}`", "", f"*Base:* `{base}`", f"*Elapsed:* {elapsed_ms} ms", ""]
        ctx_lines = [f"FILE SEARCH: query={query} base={base}"]
        if not matches:
            lines.append("_No matches._")
            ctx_lines.append("(no matches)")
            return "\n".join(lines).strip(), "\n".join(ctx_lines).strip()

        shown = 0
        for m in matches:
            rel = m.get("path") or ""
            ln = int(m.get("line") or 0)
            col = m.get("column")
            text_line = (m.get("text") or "").rstrip()
            loc = f"{rel}:{ln}" + (f":{int(col)}" if isinstance(col, (int, float)) else "")
            lines.append(f"- `{loc}`: {text_line}")
            ctx_lines.append(f"- {loc}: {text_line}")
            shown += 1
            if shown >= 100:
                break
        if truncated or len(matches) > shown:
            lines.append("")
            lines.append(f"*Note: results truncated to {shown} match(es).*")
            ctx_lines.append(f"(truncated to {shown} matches)")
        return "\n".join(lines).strip(), "\n".join(ctx_lines).strip()

