import flet as ft


def split_markdown_fences(md_text: str) -> list[tuple[str, str, str]]:
    """
    Split Markdown into segments of normal Markdown and fenced code blocks.
    Handles triple-backtick fences: ```lang ... ```
    Returns a list of (kind, lang, text) where kind is "md" or "code".
    """
    raw = md_text or ""
    lines = raw.splitlines()
    segments: list[tuple[str, str, str]] = []

    md_buf: list[str] = []
    code_buf: list[str] = []
    in_code = False
    code_lang = ""

    def flush_md():
        nonlocal md_buf
        if not md_buf:
            return
        text = "\n".join(md_buf)
        if text.strip():
            segments.append(("md", "", text))
        md_buf = []

    def flush_code():
        nonlocal code_buf, code_lang
        segments.append(("code", code_lang, "\n".join(code_buf)))
        code_buf = []
        code_lang = ""

    for ln in lines:
        s = ln.strip()
        if s.startswith("```"):
            if not in_code:
                flush_md()
                in_code = True
                code_lang = s[3:].strip()
            else:
                in_code = False
                flush_code()
            continue
        if in_code:
            code_buf.append(ln)
        else:
            md_buf.append(ln)

    if in_code:

        md_buf.append("```" + code_lang if code_lang else "```")
        md_buf.extend(code_buf)
    flush_md()
    return segments


def strip_prompt_echo(text: str) -> str:
    """
    Some models will mistakenly echo our internal prompt scaffolding (SYSTEM:/TOOL[...] blocks).
    Strip those blocks from the rendered assistant output to avoid dumping tool context into chat.
    """
    if not text:
        return ""
    markers = ("SYSTEM:", "TOOL[", "TOOL [", "USER [", "ASSISTANT [")
    if not any(m in text for m in markers):
        return text

    out: list[str] = []
    skipping = False
    for ln in (text or "").splitlines(keepends=True):
        s = ln.strip()
        if skipping:
            if s == "":
                skipping = False
            continue
        if s.startswith("SYSTEM:") or s.startswith("TOOL[") or s.startswith("TOOL [") or s.startswith("USER [") or s.startswith("ASSISTANT ["):
            skipping = True
            continue
        out.append(ln)
    return "".join(out)


def copy_to_clipboard(page: ft.Page, show_snack, text_to_copy: str, label: str, success_color: str, danger_color: str) -> None:
    try:
        page.set_clipboard(text_to_copy or "")
        show_snack(label, success_color)
    except Exception as exc:
        show_snack(f"Copy failed: {exc}", danger_color)


def make_code_block(
    *,
    page: ft.Page,
    show_snack,
    lang: str,
    code: str,
    colors: dict,
    success_color: str,
    danger_color: str,
) -> ft.Control:
    lang = (lang or "").strip()
    title = lang if lang else "code"
    raw = code or ""

    n_lines = raw.count("\n") + (1 if raw else 0)
    height_lines = max(3, min(18, n_lines))

    header = ft.Row(
        [
            ft.Text(title, size=11, color=str(colors.get("TEXT_MUTED")), weight=ft.FontWeight.W_600),
            ft.Container(expand=True),
            ft.IconButton(
                icon=ft.icons.CONTENT_COPY,
                tooltip="Copy",
                icon_color=str(colors.get("TEXT_MUTED")),
                on_click=lambda _e, t=raw: copy_to_clipboard(page, show_snack, t, "Code copied.", success_color, danger_color),
            ),
        ],
        spacing=6,
        vertical_alignment=ft.CrossAxisAlignment.CENTER,
    )

    body = ft.TextField(
        value=raw,
        multiline=True,
        read_only=True,
        min_lines=height_lines,
        max_lines=height_lines,
        text_style=ft.TextStyle(color=str(colors.get("TEXT_PRIMARY")), size=12, font_family="monospace"),
        bgcolor=str(colors.get("SURFACE")),
        border_color=str(colors.get("BORDER")),
        focused_border_color=str(colors.get("BORDER")),
    )

    return ft.Container(
        padding=12,
        bgcolor=str(colors.get("SURFACE_ALT")),
        border=ft.border.all(1, str(colors.get("BORDER"))),
        border_radius=14,
        content=ft.Column([header, body], spacing=8, tight=True),
    )


def render_markdown(
    *,
    page: ft.Page,
    md_text: str,
    open_link_handler,
    show_snack,
    colors: dict,
    success_color: str,
    danger_color: str,
) -> ft.Control:
    segs = split_markdown_fences(md_text or "")
    if not segs:
        return ft.Markdown(
            md_text or "",
            selectable=True,
            extension_set=ft.MarkdownExtensionSet.GITHUB_WEB,
            on_tap_link=open_link_handler,
        )
    if len(segs) == 1 and segs[0][0] == "md":
        return ft.Markdown(
            segs[0][2],
            selectable=True,
            extension_set=ft.MarkdownExtensionSet.GITHUB_WEB,
            on_tap_link=open_link_handler,
        )

    controls: list[ft.Control] = []
    for kind, lang, text in segs:
        if kind == "md":
            if (text or "").strip():
                controls.append(
                    ft.Markdown(
                        text,
                        selectable=True,
                        extension_set=ft.MarkdownExtensionSet.GITHUB_WEB,
                        on_tap_link=open_link_handler,
                    )
                )
        else:
            controls.append(
                make_code_block(
                    page=page,
                    show_snack=show_snack,
                    lang=lang,
                    code=text,
                    colors=colors,
                    success_color=success_color,
                    danger_color=danger_color,
                )
            )
    return ft.Column(controls, spacing=10, tight=True)

