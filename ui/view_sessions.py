import flet as ft


def build_sessions_tab(
    *,
    save_session_button: ft.Control,
    load_session_button: ft.Control,
    delete_session_button: ft.Control,
    export_session_button: ft.Control,
    import_session_button: ft.Control,
    session_name_input: ft.Control,
    export_format_dropdown: ft.Control,
    export_dir_button: ft.Control,
    export_dir_label: ft.Control,
    import_dir_button: ft.Control,
    import_dir_label: ft.Control,
    import_file_dropdown: ft.Control,
    sessions_list: ft.Control,
) -> ft.Control:
    return ft.Column(
        [
            ft.Row([save_session_button, load_session_button, delete_session_button, export_session_button, import_session_button]),
            session_name_input,
            export_format_dropdown,
            ft.Row([export_dir_button, export_dir_label]),
            ft.Row([import_dir_button, import_dir_label, import_file_dropdown]),
            sessions_list,
        ],
        expand=True,
        spacing=12,
        scroll=ft.ScrollMode.AUTO,
    )

