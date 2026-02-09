import flet as ft


def build_shell(
    *,
    page: ft.Page,
    app_title: str,
    colors: dict,
    sidebar_width: int,
    chat_tab: ft.Control,
    models_tab: ft.Control,
    sessions_tab: ft.Control,
    tools_tab: ft.Control,
    settings_tab: ft.Control,
    keyboard_tab: ft.Control,

    model_dropdown: ft.Control,
    refresh_models_button: ft.Control,
    switch_model_button: ft.Control,
    palette_button: ft.Control,
    model_status_dot: ft.Control,
    model_switch_spinner: ft.Control,
    search_status_dot: ft.Control,
    power_pill: ft.Control,
    ram_pill: ft.Control,
    cpu_pill: ft.Control,
    temp_pill: ft.Control,
    vram_pill: ft.Control,

    session_filter_field: ft.Control,
    sidebar_sessions_list: ft.Control,

    on_new_chat,
    primary_button_style: ft.ButtonStyle,
    update_bubble_widths,
    handle_key_event,
) -> dict:
    def _c(k: str, default: str = "") -> str:
        try:
            v = colors.get(k)
            return str(v) if v is not None else default
        except Exception:
            return default

    content_holder = ft.Container(expand=True, bgcolor=_c("BG"))
    active_view = {"value": 0}
    nav_refs: list[dict] = []

    def update_nav_styles():
        for item in nav_refs:
            is_active = item["index"] == active_view["value"]
            item["box"].bgcolor = _c("SURFACE") if is_active else None
            item["box"].border = ft.border.all(1, _c("BORDER")) if is_active else None
            item["icon"].color = _c("TEXT_PRIMARY") if is_active else _c("TEXT_MUTED")
            item["text"].color = _c("TEXT_PRIMARY") if is_active else _c("TEXT_MUTED")
        page.update()

    def set_view(index: int):
        active_view["value"] = int(index)
        if index == 0:
            content_holder.content = chat_tab
        elif index == 1:
            content_holder.content = ft.Container(padding=20, content=models_tab, bgcolor=_c("BG"))
        elif index == 2:
            content_holder.content = ft.Container(padding=20, content=sessions_tab, bgcolor=_c("BG"))
        elif index == 3:
            content_holder.content = ft.Container(padding=20, content=tools_tab, bgcolor=_c("BG"))
        elif index == 4:
            content_holder.content = ft.Container(padding=20, content=settings_tab, bgcolor=_c("BG"))
        else:
            content_holder.content = ft.Container(padding=20, content=keyboard_tab, bgcolor=_c("BG"))
        update_nav_styles()
        try:
            update_bubble_widths()
        except Exception:
            pass

    def make_nav_item(label: str, icon, index: int) -> ft.Control:
        ico = ft.Icon(icon, size=18, color=_c("TEXT_MUTED"))
        txt = ft.Text(label, size=13, weight=ft.FontWeight.W_600, color=_c("TEXT_MUTED"))
        box = ft.Container(
            content=ft.Row([ico, txt], spacing=10),
            padding=ft.padding.symmetric(horizontal=10, vertical=8),
            border_radius=12,
            on_click=lambda _: set_view(index),
        )
        nav_refs.append({"box": box, "icon": ico, "text": txt, "index": index})
        return box

    sidebar_visible = {"value": True, "initialized": False}

    def apply_responsive_layout():
        w = getattr(getattr(page, "window", None), "width", None)
        if not isinstance(w, (int, float)) or w <= 0:
            w = getattr(page, "window_width", 1100) or 1100
        compact = bool(w < 980)
        if compact and not sidebar_visible["initialized"]:
            sidebar_visible["value"] = False
            sidebar_visible["initialized"] = True
        elif not sidebar_visible["initialized"]:
            sidebar_visible["initialized"] = True

        sidebar_container.visible = bool(sidebar_visible["value"])
        hamburger_button.visible = compact or (not sidebar_container.visible)

    def toggle_sidebar(_=None):
        sidebar_visible["value"] = not sidebar_visible["value"]
        try:
            apply_responsive_layout()
        except Exception:
            sidebar_container.visible = sidebar_visible["value"]
        try:
            update_bubble_widths()
        except Exception:
            pass
        page.update()

    hamburger_button = ft.IconButton(
        icon=ft.icons.MENU,
        tooltip="Menu",
        on_click=toggle_sidebar,
        icon_color=_c("TEXT_PRIMARY"),
    )

    new_chat_button = ft.ElevatedButton(
        "New chat",
        icon=ft.icons.ADD,
        on_click=on_new_chat,
        style=primary_button_style,
    )

    sidebar_nav = ft.Column(
        [
            make_nav_item("Chat", ft.icons.CHAT_BUBBLE_OUTLINE, 0),
            make_nav_item("Models", ft.icons.TUNE, 1),
            make_nav_item("Sessions", ft.icons.HISTORY, 2),
            make_nav_item("Tools", ft.icons.BUILD_OUTLINED, 3),
            make_nav_item("Settings", ft.icons.SETTINGS_OUTLINED, 4),
            make_nav_item("Keyboard", ft.icons.KEYBOARD, 5),
        ],
        spacing=4,
    )

    sidebar_container = ft.Container(
        width=int(sidebar_width),
        bgcolor=_c("SIDEBAR_BG"),
        padding=12,
        content=ft.Column(
            [
                ft.Row(
                    [ft.Text(app_title, size=14, weight=ft.FontWeight.W_700, color=_c("TEXT_PRIMARY"))],
                    alignment=ft.MainAxisAlignment.SPACE_BETWEEN,
                ),
                ft.Container(height=8),
                new_chat_button,
                ft.Container(height=10),
                sidebar_nav,
                ft.Container(height=10),
                session_filter_field,
                ft.Container(height=6),
                ft.Text("Chats", size=12, weight=ft.FontWeight.W_600, color=_c("TEXT_MUTED")),
                sidebar_sessions_list,
            ],
            spacing=0,
            expand=True,
        ),
        border=ft.border.only(right=ft.BorderSide(1, _c("BORDER"))),
    )

    model_status = ft.Row(
        [
            model_status_dot,
            model_switch_spinner,
            ft.Text("Model", size=12, color=_c("TEXT_MUTED")),
            search_status_dot,
            ft.Text("API", size=12, color=_c("TEXT_MUTED")),
        ],
        spacing=6,
    )
    telemetry_row = ft.Row([power_pill, ram_pill, cpu_pill, temp_pill, vram_pill], spacing=8)

    top_bar = ft.Container(
        padding=ft.padding.symmetric(horizontal=16, vertical=10),
        bgcolor=_c("SURFACE_ALT"),
        border=ft.border.only(bottom=ft.BorderSide(1, _c("BORDER"))),
        content=ft.Row(
            [
                hamburger_button,
                ft.Container(
                    expand=True,
                    alignment=ft.alignment.center,
                    content=ft.Row(
                        [model_dropdown, refresh_models_button, switch_model_button, palette_button],
                        spacing=6,
                        alignment=ft.MainAxisAlignment.CENTER,
                        vertical_alignment=ft.CrossAxisAlignment.CENTER,
                    ),
                ),
                ft.Column([model_status, telemetry_row], spacing=6, horizontal_alignment=ft.CrossAxisAlignment.END),
            ],
            alignment=ft.MainAxisAlignment.SPACE_BETWEEN,
            vertical_alignment=ft.CrossAxisAlignment.CENTER,
        ),
    )

    main_container = ft.Container(expand=True, bgcolor=_c("BG"), content=ft.Column([top_bar, content_holder], expand=True, spacing=0))
    root = ft.Row([sidebar_container, main_container], expand=True, spacing=0)

    def on_resize(_=None):
        apply_responsive_layout()
        try:
            update_bubble_widths()
        except Exception:
            pass


    root_control = root
    kl = getattr(ft, "KeyboardListener", None)
    if kl is not None:
        try:
            root_control = kl(content=root, on_key_event=handle_key_event, autofocus=True)
        except TypeError:
            try:
                root_control = kl(child=root, on_key_event=handle_key_event, autofocus=True)
            except TypeError:
                root_control = root

    return {
        "content_holder": content_holder,
        "sidebar_container": sidebar_container,
        "main_container": main_container,
        "top_bar": top_bar,
        "hamburger_button": hamburger_button,
        "sidebar_visible": sidebar_visible,
        "nav_refs": nav_refs,
        "set_view": set_view,
        "toggle_sidebar": toggle_sidebar,
        "update_nav_styles": update_nav_styles,
        "apply_responsive_layout": apply_responsive_layout,
        "on_resize": on_resize,
        "root_control": root_control,
    }
