import flet as ft


def _card(*, surface: str, border: str, content: ft.Control) -> ft.Control:
    return ft.Container(
        padding=ft.padding.symmetric(horizontal=12, vertical=10),
        bgcolor=surface,
        border=ft.border.all(1, border),
        border_radius=14,
        content=content,
    )


def build_settings_tab(
    *,
    theme_dropdown: ft.Control,
    density_dropdown: ft.Control,
    appearance_apply_button: ft.Control,
    assistant_name_field: ft.Control,
    assistant_tone_field: ft.Control,
    temperature_field: ft.Control,
    max_tokens_field: ft.Control,
    top_p_field: ft.Control,
    top_k_field: ft.Control,
    stop_sequences_field: ft.Control,
    llama_args_field: ft.Control,
    llama_args_apply_button: ft.Control,
    llama_args_restart_switch: ft.Control,
    llama_args_note: ft.Control,
    llama_restart_needed_label: ft.Control,
    llama_status_label: ft.Control,
    llama_running_args_label: ft.Control,
    llama_cmdline_label: ft.Control,
    backend_settings_note_settings: ft.Control,
    power_idle_field: ft.Control,
    power_max_field: ft.Control,
    power_apply_button: ft.Control,
    surface: str,
    border: str,
    text_muted: str,
) -> ft.Control:
    return ft.ListView(
        controls=[
            _card(
                surface=surface,
                border=border,
                content=ft.Column(
                    [
                        ft.Text("Appearance", size=12, weight=ft.FontWeight.W_600, color=text_muted),
                        ft.Row([theme_dropdown, density_dropdown, appearance_apply_button], spacing=10, wrap=True),
                    ],
                    spacing=8,
                ),
            ),
            _card(
                surface=surface,
                border=border,
                content=ft.Column(
                    [
                        ft.Text("Assistant", size=12, weight=ft.FontWeight.W_600, color=text_muted),
                        ft.Row([assistant_name_field, assistant_tone_field], spacing=10, wrap=True),
                        ft.Text(
                            "These settings affect the first line of the system prompt used for new generations.",
                            size=11,
                            color=text_muted,
                        ),
                    ],
                    spacing=8,
                ),
            ),
            ft.Row([temperature_field, max_tokens_field, top_p_field, top_k_field]),
            stop_sequences_field,
            _card(
                surface=surface,
                border=border,
                content=ft.Column(
                    [
                        ft.Text("Model server", size=12, weight=ft.FontWeight.W_600, color=text_muted),
                        ft.Row([llama_args_field, llama_args_apply_button], spacing=10),
                        llama_args_restart_switch,
                        llama_args_note,
                        llama_restart_needed_label,
                        llama_status_label,
                        llama_running_args_label,
                        llama_cmdline_label,
                        backend_settings_note_settings,
                    ],
                    spacing=8,
                ),
            ),
            _card(
                surface=surface,
                border=border,
                content=ft.Column(
                    [
                        ft.Text("Telemetry", size=12, weight=ft.FontWeight.W_600, color=text_muted),
                        ft.Row([power_idle_field, power_max_field, power_apply_button], spacing=10, wrap=True),
                        ft.Text(
                            "Power utilization is estimated between idle and max. If the PWR pill looks wrong, calibrate these values.",
                            size=11,
                            color=text_muted,
                        ),
                    ],
                    spacing=6,
                ),
            ),
        ],
        spacing=12,
        expand=True,
    )

