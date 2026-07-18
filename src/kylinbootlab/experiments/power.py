"""Target power-control abstraction, VMware vmrun, and Wake-on-LAN backends.

:class:`TargetPower` gives the experiment orchestrator one interface for
power-cycling targets.  :class:`VixPower` drives a VMware Workstation VM
through the ``vmrun`` command-line tool (VIX 1.17.0 / Workstation 17).
:class:`WolPower` controls bare-metal targets via Wake-on-LAN magic-packet
broadcast and SSH shutdown/reset.
"""

import socket
import subprocess
from collections.abc import Callable
from typing import Protocol

type _Runner = Callable[[list[str]], subprocess.CompletedProcess[str]]

#: Default VMware Workstation vmrun binary on the Windows controller.
VMRUN = r"F:\VMware\VMware Workstation\vmrun.exe"


class PowerControlError(RuntimeError):
    """A power backend operation (on/off/reset/snapshot) failed.

    Raised by backends when the underlying tool reports failure.  The
    orchestrator wraps this (like any power-sequencing exception) into its
    retryable experiment-error hierarchy; RecoveryManager's layer-1 snapshot
    restore falls through to the ostree layer when it sees this raised.
    """


class TargetPower(Protocol):
    """Unified power control for physical and virtual targets."""

    def power_on(self) -> None: ...

    def power_off(self) -> None: ...

    def reset(self) -> None: ...

    def snapshot_create(self, name: str) -> None: ...

    def snapshot_restore(self, name: str) -> None: ...

    def guest_alive(self) -> bool: ...


class VixPower:
    """VMware Workstation power control via the ``vmrun`` CLI.

    The VMX file path identifies the virtual machine.  Mutating operations
    (``power_on``/``power_off``/``reset``/``snapshot_*``) raise
    :class:`PowerControlError` when vmrun exits non-zero, with one
    idempotency carve-out: ``stop``/``reset`` failures whose output says the
    VM is "not powered on" are treated as success, so ``power_off`` on an
    already-off VM is a no-op.  (``vmrun start`` on a running VM exits 0, so
    ``power_on`` needs no carve-out.)
    """

    def __init__(
        self,
        vmx_path: str,
        *,
        vmrun_path: str = VMRUN,
        _runner: _Runner | None = None,
    ) -> None:
        self.vmx_path = vmx_path
        self.vmrun_path = vmrun_path
        self._run: _Runner = _runner if _runner is not None else self._real_run

    @staticmethod
    def _real_run(args: list[str]) -> subprocess.CompletedProcess[str]:
        return subprocess.run(args, check=False, capture_output=True, text=True)

    def _vmrun(self, *args: str) -> subprocess.CompletedProcess[str]:
        """Invoke ``vmrun -T ws <verb> [args...]`` and return the raw result."""
        return self._run([self.vmrun_path, "-T", "ws", *args])

    def _vmrun_checked(self, *args: str, tolerate_not_powered_on: bool = False) -> None:
        """Run a mutating vmrun operation; raise :class:`PowerControlError` on failure."""
        result = self._vmrun(*args)
        if result.returncode == 0:
            return
        output = f"{result.stdout}\n{result.stderr}"
        if tolerate_not_powered_on and "not powered on" in output.lower():
            return  # VM already off — idempotent success
        raise PowerControlError(
            f"vmrun {args[0]} failed for {self.vmx_path} "
            f"(exit {result.returncode}): {output.strip()}"
        )

    # -- power control ---------------------------------------------------

    def power_on(self) -> None:
        self._vmrun_checked("start", self.vmx_path, "nogui")

    def power_off(self) -> None:
        self._vmrun_checked("stop", self.vmx_path, "hard", tolerate_not_powered_on=True)

    def reset(self) -> None:
        self._vmrun_checked("reset", self.vmx_path, "hard", tolerate_not_powered_on=True)

    def snapshot_create(self, name: str) -> None:
        self._vmrun_checked("snapshot", self.vmx_path, name)

    def snapshot_restore(self, name: str) -> None:
        self._vmrun_checked("revertToSnapshot", self.vmx_path, name)

    def guest_alive(self) -> bool:
        result = self._vmrun("list")
        return result.returncode == 0 and self.vmx_path.lower() in result.stdout.lower()


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
