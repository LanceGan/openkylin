"""Desktop + greeter adapter — per-distribution display manager settings.

Each profile maps the Phase 3 observer's greeter_ready_pattern and
usable-probe core_processes to distribution-specific values.
"""
from typing import TypedDict


class DesktopInfo(TypedDict):
    display_manager: str
    dm_service: str
    greeter_binary: str
    greeter_ready_journald_pattern: str
    desktop_session: str
    autostart_dir: str
    core_processes: list[str]
    sentinel_app: str


PROFILES: dict[str, DesktopInfo] = {
    "openkylin": {
        "display_manager": "lightdm",
        "dm_service": "lightdm.service",
        "greeter_binary": "ukui-greeter",
        "greeter_ready_journald_pattern": "pam_env(lightdm-greeter:session)",
        "desktop_session": "ukui",
        "autostart_dir": "~/.config/autostart/",
        "core_processes": ["ukui-panel", "ukui-settings-daemon"],
        "sentinel_app": "mate-terminal",
    },
    "ubuntu": {
        "display_manager": "gdm3",
        "dm_service": "gdm.service",
        "greeter_binary": "gdm-session-worker",
        "greeter_ready_journald_pattern": "pam_unix(gdm-password:session)",
        "desktop_session": "ubuntu (GNOME)",
        "autostart_dir": "~/.config/autostart/",
        "core_processes": ["gnome-shell", "gnome-settings-daemon"],
        "sentinel_app": "gnome-terminal",
    },
    "fedora": {
        "display_manager": "gdm",
        "dm_service": "gdm.service",
        "greeter_binary": "gdm-session-worker",
        "greeter_ready_journald_pattern": "pam_unix(gdm-password:session)",
        "desktop_session": "gnome",
        "autostart_dir": "~/.config/autostart/",
        "core_processes": ["gnome-shell", "gnome-settings-daemon"],
        "sentinel_app": "gnome-terminal",
    },
}


def for_distro(os_id: str) -> DesktopInfo:
    return PROFILES.get(os_id, PROFILES["ubuntu"])
