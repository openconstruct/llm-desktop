import flet as ft


def build_tools_tab(
    *,
    tool_web_search_switch: ft.Control,
    web_search_backoff_label: ft.Control,
    tool_fs_switch: ft.Control,
    files_dir_button: ft.Control,
    files_dir_home_button: ft.Control,
    files_dir_desktop_button: ft.Control,
    files_dir_project_button: ft.Control,
    files_dir_label: ft.Control,
    tool_files_max_bytes_field: ft.Control,
    tool_files_max_bytes_apply_button: ft.Control,
    text_primary: str,
    text_muted: str,
) -> ft.Control:
    return ft.Column(
        [
            ft.Text("Tools", size=18, weight=ft.FontWeight.W_700, color=text_primary),
            ft.Container(height=6),
            tool_web_search_switch,
            web_search_backoff_label,
            tool_fs_switch,
            ft.Container(height=6),
            ft.Row([files_dir_button, files_dir_home_button, files_dir_desktop_button, files_dir_project_button], spacing=8, wrap=True),
            files_dir_label,
            ft.Row([tool_files_max_bytes_field, tool_files_max_bytes_apply_button], spacing=8, wrap=True),
            ft.Text(
                "Note: disabling file tools only affects the model's ability to use fs_list/fs_search/fs_read/fs_write. File attachments still work.",
                size=11,
                color=text_muted,
            ),
        ],
        spacing=10,
        scroll=ft.ScrollMode.AUTO,
    )

