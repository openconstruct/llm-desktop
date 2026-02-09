import flet as ft


def build_keyboard_tab(
    *,
    keyboard_last_event_label: ft.Control,
    surface: str,
    border: str,
    text_primary: str,
    text_muted: str,
) -> ft.Control:
    keyboard_shortcuts = [
        ("Ctrl+Enter", "Send message"),
        ("Esc", "Stop generation"),
        ("Ctrl+A", "Attach file(s)"),
        ("Ctrl+S", "Save current session"),
        ("Ctrl+N", "New chat"),
        ("Ctrl+O", "Open session (Sessions tab; loads selected if any)"),
        ("Ctrl+M", "Focus model dropdown (select and press Enter to switch)"),
        ("Ctrl+R", "Reload model list"),
        ("Ctrl+K / Ctrl+P / F1", "Command palette"),
    ]

    return ft.Column(
        [
            ft.Text("Keyboard shortcuts", size=18, weight=ft.FontWeight.W_700, color=text_primary),
            ft.Container(height=8),
            keyboard_last_event_label,
            ft.Container(height=10),
            ft.Container(
                padding=14,
                bgcolor=surface,
                border=ft.border.all(1, border),
                border_radius=14,
                content=ft.Column(
                    [
                        ft.Row(
                            [
                                ft.Text(k, size=12, weight=ft.FontWeight.W_700, color=text_primary),
                                ft.Text(v, size=12, color=text_muted),
                            ],
                            alignment=ft.MainAxisAlignment.SPACE_BETWEEN,
                        )
                        for (k, v) in keyboard_shortcuts
                    ],
                    spacing=10,
                ),
            ),
        ],
        spacing=0,
        scroll=ft.ScrollMode.AUTO,
    )

