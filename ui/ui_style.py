TEXT_PRIMARY = "#E6EDF3"
TEXT_MUTED = "#9AA6B2"


BG = "#0F1115"
SIDEBAR_BG = "#0B0D10"
SURFACE = "#151A22"
SURFACE_ALT = "#11151B"
SURFACE_ELEV = "#171D26"
BORDER = "#2A3342"

ACCENT = "#10A37F"
ACCENT_SOFT = "#0D2F28"
SUCCESS = "#22C55E"
WARNING = "#F59E0B"
DANGER = "#EF4444"

STATUS_LABEL_COLOR = TEXT_MUTED


def status_color(severity: str) -> str:
    return {
        "idle": SURFACE_ALT,
        "ok": "#203142",
        "warn": "#3A2E1B",
        "alert": "#3A1F23",
    }.get(severity, SURFACE_ALT)


def status_text_color(severity: str) -> str:
    return {
        "idle": TEXT_MUTED,
        "ok": TEXT_PRIMARY,
        "warn": TEXT_PRIMARY,
        "alert": TEXT_PRIMARY,
    }.get(severity, TEXT_MUTED)

