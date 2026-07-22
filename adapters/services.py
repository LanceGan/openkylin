"""Service name mapping — openKylin → Ubuntu → Fedora equivalents.

~80% of startup-critical services have identical names.  The ~20% that
differ are mostly desktop-specific daemons.  ``map_unit()`` returns the
service name for a given distribution.
"""
from typing import TypedDict

# (openkylin_name, ubuntu_name, fedora_name)
# ``None`` means no equivalent exists on that distribution.
_SERVICE_TABLE: list[tuple[str, str | None, str | None]] = [
    ("NetworkManager.service", "NetworkManager.service", "NetworkManager.service"),
    ("NetworkManager-wait-online.service", "NetworkManager-wait-online.service", "NetworkManager-wait-online.service"),
    ("dbus.service", "dbus.service", "dbus.service"),
    ("systemd-journald.service", "systemd-journald.service", "systemd-journald.service"),
    ("systemd-udev-trigger.service", "systemd-udev-trigger.service", "systemd-udev-trigger.service"),
    ("strongswan-starter.service", "strongswan-starter.service", "strongswan-starter.service"),
    ("polkit.service", "polkit.service", "polkit.service"),
    ("accounts-daemon.service", "accounts-daemon.service", "accounts-daemon.service"),
    ("rsyslog.service", "rsyslog.service", "rsyslog.service"),
    ("avahi-daemon.service", "avahi-daemon.service", "avahi-daemon.service"),
    ("lightdm.service", "gdm.service", "gdm.service"),
    ("ukui-bluetooth.service", "bluetooth.service", "bluetooth.service"),
    ("biometric-authentication.service", "fprintd.service", "fprintd.service"),
    ("org.kylin.kaiming.service", None, None),
    ("kysdk-conf2.service", None, None),
    ("kysdk-dbus.service", None, None),
    ("kylin-daq.service", None, None),
    ("kylin-fix-boot-grub.service", None, None),
    ("kylin-core-dump-monitor.service", None, None),
]


class ServiceMap(TypedDict):
    openkylin: str | None
    ubuntu: str | None
    fedora: str | None


def map_unit(openkylin_name: str, target_distro: str) -> str | None:
    """Return the service name for *target_distro* ("ubuntu" or "fedora").

    Returns ``None`` when the service has no equivalent on that distribution.
    """
    col = {"ubuntu": 1, "fedora": 2}.get(target_distro)
    if col is None:
        raise ValueError(f"unknown target distribution: {target_distro}")
    for row in _SERVICE_TABLE:
        if row[0] == openkylin_name:
            return row[col]
    return openkylin_name  # not in table → assume identical
