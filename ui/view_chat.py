import flet as ft


def build_chat_tab(*, chat_scroller: ft.Control, empty_state: ft.Control, composer_outer: ft.Control) -> ft.Control:
    chat_area = ft.Stack([chat_scroller, empty_state], expand=True)
    return ft.Column(
        [
            chat_area,
            ft.Row([composer_outer], alignment=ft.MainAxisAlignment.CENTER),
            ft.Container(height=14),
        ],
        expand=True,
        spacing=0,
    )

