"""Double-layer recovery: VIX snapshot (fast) -> ostree rollback (fallback)."""

import subprocess
from collections.abc import Callable

from kylinbootlab.experiments.power import TargetPower

type _Runner = Callable[[list[str]], subprocess.CompletedProcess[str]]


class RecoveryFailedError(RuntimeError):
    """Both recovery layers failed — manual intervention required."""


class RecoveryManager:
    """Stateless recovery orchestrator.

    Layer 1: VMware snapshot restore (seconds, no OS dependency).
    Layer 2: ostree admin undeploy + reboot (minutes, requires SSH).
    """

    @staticmethod
    def restore(
        power: TargetPower,
        target: str,
        *,
        runner: _Runner | None = None,
    ) -> None:
        """Attempt recovery.  Raise ``RecoveryFailedError`` only if both layers fail."""
        run: _Runner = runner if runner is not None else RecoveryManager._ssh_run

        # Layer 1: VIX snapshot restore, then power the guest back on.
        try:
            power.snapshot_restore("baseline")
            power.power_on()
            return
        except Exception as exc:  # fall through to layer 2
            snapshot_error: Exception = exc

        # Layer 2: ostree rollback via SSH.
        try:
            result = run([
                "ssh", "-o", "BatchMode=yes", "-o", "ConnectTimeout=15",
                target,
                (
                    "sudo ostree admin undeploy 1 && "
                    "sudo grub-set-default 0 && "
                    "sudo reboot"
                ),
            ])
        except Exception as exc:
            raise RecoveryFailedError(
                f"both recovery layers failed: snapshot restore: {snapshot_error}; "
                f"ostree rollback: {exc}"
            ) from exc
        if result.returncode != 0:
            raise RecoveryFailedError(
                f"both recovery layers failed: snapshot restore: {snapshot_error}; "
                f"ostree rollback exited {result.returncode}: {result.stderr}"
            )

    @staticmethod
    def _ssh_run(args: list[str]) -> subprocess.CompletedProcess[str]:
        return subprocess.run(args, check=False, capture_output=True, text=True, timeout=30)
