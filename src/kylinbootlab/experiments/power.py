"""Target power-control abstraction and the VMware VIX backend.

:class:`TargetPower` gives the experiment orchestrator one interface for
power-cycling targets.  :class:`VixPower` drives a VMware VM through the VIX
COM API via short PowerShell one-liners; a Wake-on-LAN backend for physical
targets arrives in a later task.
"""

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


def power_backend_factory(backend: str, **kwargs: str) -> TargetPower:
    """Return a TargetPower instance for the named backend.

    Supported values: ``"vix"``.  ``"wol"`` arrives in a later task, so it —
    like any other name — raises ``ValueError`` for now.
    """
    if backend == "vix":
        vmx = kwargs.get("vmx_path")
        if not vmx:
            raise ValueError("vmx_path is required for the vix backend")
        return VixPower(vmx)
    raise ValueError(f"unknown power backend: {backend}")
