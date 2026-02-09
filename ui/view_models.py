import flet as ft


def _card(*, surface: str, border: str, content: ft.Control) -> ft.Control:
    return ft.Container(
        padding=14,
        bgcolor=surface,
        border=ft.border.all(1, border),
        border_radius=14,
        content=content,
    )


def build_models_tab(
    *,
    current_model_info: ft.Control,
    model_dir_button: ft.Control,
    model_dir_label: ft.Control,
    llama_ctx_label: ft.Control,
    ctx_size_field: ft.Control,
    ctx_apply_button: ft.Control,
    autostart_model_switch: ft.Control,
    backend_settings_note_models: ft.Control,
    model_status_text: ft.Control,
    surface: str,
    border: str,
    text_muted: str,
) -> ft.Control:
    return ft.Column(
        [
            _card(
                surface=surface,
                border=border,
                content=ft.Column(
                    [
                        ft.Text("Current model", size=12, weight=ft.FontWeight.W_700, color=text_muted),
                        current_model_info,
                    ],
                    spacing=8,
                ),
            ),
            _card(
                surface=surface,
                border=border,
                content=ft.Column(
                    [
                        ft.Text("Model directory", size=12, weight=ft.FontWeight.W_700, color=text_muted),
                        ft.Row([model_dir_button, model_dir_label], spacing=12, wrap=True),
                        ft.Text(
                            "Changing the model folder updates the list in the top dropdown.",
                            size=11,
                            color=text_muted,
                        ),
                    ],
                    spacing=8,
                ),
            ),
            _card(
                surface=surface,
                border=border,
                content=ft.Column(
                    [
                        ft.Text("Model server", size=12, weight=ft.FontWeight.W_700, color=text_muted),
                        llama_ctx_label,
                        ft.Row([ctx_size_field, ctx_apply_button], spacing=12, wrap=True),
                        ft.Text(
                            "Changing context length requires restarting llama-server and will affect memory usage.",
                            size=11,
                            color=text_muted,
                        ),
                    ],
                    spacing=8,
                ),
            ),
            _card(
                surface=surface,
                border=border,
                content=ft.Column(
                    [
                        ft.Text("Startup", size=12, weight=ft.FontWeight.W_700, color=text_muted),
                        autostart_model_switch,
                        backend_settings_note_models,
                    ],
                    spacing=6,
                ),
            ),
            model_status_text,
        ],
        spacing=12,
        scroll=ft.ScrollMode.AUTO,
    )

