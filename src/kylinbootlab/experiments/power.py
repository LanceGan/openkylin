"""Target power-control abstraction, VMware VIX, and Wake-on-LAN backends.

:class:`TargetPower` gives the experiment orchestrator one interface for
power-cycling targets.  :class:`VixPower` drives a VMware VM through the VIX
COM API via short PowerShell one-liners.  :class:`WolPower` controls bare-metal
targets via Wake-on-LAN magic-packet broadcast and SSH shutdown/reset.
"""

import socket
import subprocess
from collections.abc import Callable
from typing import Protocol

type _Runner = Callable[[list[str]], subprocess.CompletedProcess[str]]


class TargetPower(Protocol):
    """Unified power control for physical and virtual targets."""

    def power_on(self) -> None: ...

    def power_off(self) -> None: ...

    def reset(self) -> None: ...

    def snapshot_create(self, name: str) -> None: ...

    def snapshot_restore(self, name: str) -> None: ...

    def guest_alive(self) -> bool: ...


def _pwsh(code: str) -> list[str]:
    """Wrap one-liner PowerShell code into a subprocess-ready command list."""
    return [
        "powershell.exe",
        "-NoProfile",
        "-NonInteractive",
        "-Command",
        code,
    ]


class VixPower:
    """VMware VIX power control via PowerShell COM.

    The VMX file path identifies the virtual machine.  All operations are
    idempotent — calling ``power_on`` on an already-running VM is a no-op
    at the VIX level.
    """

    def __init__(self, vmx_path: str, *, _runner: _Runner | None = None) -> None:
        self.vmx_path = vmx_path
        self._run: _Runner = _runner if _runner is not None else self._real_run

    @staticmethod
    def _real_run(args: list[str]) -> subprocess.CompletedProcess[str]:
        return subprocess.run(args, check=False, capture_output=True, text=True)

    def _vix(self, operation: str) -> subprocess.CompletedProcess[str]:
        """Open the VM through VIX and invoke one COM ``operation`` on it."""
        return self._run(
            _pwsh(
                f'$vm = (Connect-VIX -Host localhost).OpenVM("{self.vmx_path}"); '
                f"$vm.{operation}"
            )
        )

    # -- power control ---------------------------------------------------

    def power_on(self) -> None:
        self._vix("PowerOn()")

    def power_off(self) -> None:
        self._vix("PowerOff()")

    def reset(self) -> None:
        self._vix("Reset()")

    def snapshot_create(self, name: str) -> None:
        self._vix(f'CreateSnapshot("{name}")')

    def snapshot_restore(self, name: str) -> None:
        self._vix(f'RevertToSnapshot("{name}")')

    def guest_alive(self) -> bool:
        result = self._vix("IsPoweredOn")
        return result.returncode == 0 and "True" in result.stdout


class WolPower:
    """Bare-metal power control via Wake-on-LAN and SSH.

    ``power_on`` broadcasts a magic packet to the target's MAC address.
    ``power_off`` and ``reset`` use SSH.  ``snapshot_*`` are no-ops —
    bare-metal recovery is handled at the ostree level by RecoveryManager.
    """

    def __init__(
        self,
        target: str,
        mac: str,
        *,
        _runner: _Runner | None = None,
    ) -> None:
        self.target = target
        self.mac = mac
        self._run: _Runner = _runner if _runner is not None else self._real_run

    @staticmethod
    def _real_run(args: list[str]) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            args, check=False, capture_output=True, text=True, timeout=30,
        )

    # -- power control ---------------------------------------------------

    def power_on(self) -> None:
        """Send a Wake-on-LAN magic packet to the target's MAC."""
        hex_str = self.mac.replace(":", "").replace("-", "").replace(" ", "")
        if len(hex_str) != 12:
            raise ValueError(f"invalid MAC address: {self.mac}")
        addr_bytes = bytes.fromhex(hex_str)
        magic = b"\xff" * 6 + addr_bytes * 16

        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as sock:
            sock.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
            sock.sendto(magic, ("255.255.255.255", 9))
        # Also try wakeonlan CLI as fallback (non-fatal if missing)
        self._run(["wakeonlan", self.mac])

    def power_off(self) -> None:
        self._run([
            "ssh", "-o", "BatchMode=yes", "-o", "ConnectTimeout=15",
            self.target, "sudo", "poweroff",
        ])

    def reset(self) -> None:
        self.power_off()

    def snapshot_create(self, name: str) -> None:
        """Not supported on bare metal — handled by ostree rollback."""
        pass

    def snapshot_restore(self, name: str) -> None:
        """Not supported on bare metal — handled by ostree rollback."""
        pass

    def guest_alive(self) -> bool:
        result = self._run([
            "ssh", "-o", "BatchMode=yes", "-o", "ConnectTimeout=10",
            self.target, "true",
        ])
        return result.returncode == 0


def power_backend_factory(backend: str, **kwargs: str) -> TargetPower:
    """Return a TargetPower instance for the named backend.

    Supported values: ``"vix"``, ``"wol"``.
    """
    if backend == "vix":
        vmx = kwargs.get("vmx_path")
        if not vmx:
            raise ValueError("vmx_path is required for the vix backend")
        return VixPower(vmx)
    if backend == "wol":
        target = kwargs.get("target")
        mac = kwargs.get("mac")
        if not target or not mac:
            raise ValueError("target and mac are required for the wol backend")
        return WolPower(target, mac)
    raise ValueError(f"unknown power backend: {backend}")
