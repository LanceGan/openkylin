"""Distribution identity adapter — reads /etc/os-release and maps to DistroInfo."""
from __future__ import annotations
from typing import TypedDict


class DistroInfo(TypedDict):
    os_id: str
    os_version: str
    init_system: str
    pkg_manager: str
    kernel_package: str
    initramfs_tool: str
    initramfs_config_dir: str
    initramfs_rebuild_cmd: str
    grub_config_dir: str
    grub_update_cmd: str


# Pre-computed profiles for the three supported distributions.
PROFILES: dict[str, DistroInfo] = {
    "openkylin": {
        "os_id": "openkylin",
        "os_version": "2.0",
        "init_system": "systemd",
        "pkg_manager": "apt (ostree-guarded)",
        "kernel_package": "linux-image-generic",
        "initramfs_tool": "initramfs-tools",
        "initramfs_config_dir": "/etc/initramfs-tools/conf.d/",
        "initramfs_rebuild_cmd": "update-initramfs -u -k all",
        "grub_config_dir": "/etc/default/grub.d/",
        "grub_update_cmd": "update-grub",
    },
    "ubuntu": {
        "os_id": "ubuntu",
        "os_version": "24.04",
        "init_system": "systemd",
        "pkg_manager": "apt",
        "kernel_package": "linux-image-generic",
        "initramfs_tool": "initramfs-tools",
        "initramfs_config_dir": "/etc/initramfs-tools/conf.d/",
        "initramfs_rebuild_cmd": "update-initramfs -u -k all",
        "grub_config_dir": "/etc/default/grub.d/",
        "grub_update_cmd": "update-grub",
    },
    "fedora": {
        "os_id": "fedora",
        "os_version": "41",
        "init_system": "systemd",
        "pkg_manager": "dnf",
        "kernel_package": "kernel-core",
        "initramfs_tool": "dracut",
        "initramfs_config_dir": "/etc/dracut.conf.d/",
        "initramfs_rebuild_cmd": "dracut --force --regenerate-all",
        "grub_config_dir": "/etc/default/grub.d/",
        "grub_update_cmd": "grub2-mkconfig -o /boot/grub2/grub.cfg",
    },
}


def detect(os_release_text: str) -> DistroInfo:
    """Return the distro profile matching /etc/os-release content."""
    for os_id, profile in PROFILES.items():
        if os_id in os_release_text.lower():
            return profile
    return PROFILES["ubuntu"]  # safe fallback
