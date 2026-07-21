"""Profile executor -- apply and rollback systemd drop-ins and masks via SSH.

All commands use the same SSH hardening as ``remote.py``:
``BatchMode=yes``, ``ConnectTimeout=15``, ``ServerAliveInterval=15``,
``ServerAliveCountMax=3``.

The executor is idempotent: ``apply()`` when already applied is a no-op;
``rollback()`` when not applied is a no-op.  ``apply_with_retry`` retries
with a 5-second interval before raising ``RuntimeError``.
"""

from __future__ import annotations

import subprocess
import time

from kylinbootlab.optimization.plan import OptimizationPlan
from kylinbootlab.remote import _SSH_OPTIONS


class ProfileExecutor:
    """Apply and rollback systemd configuration changes on a target via SSH."""

    def __init__(self, target: str, password: str | None = None) -> None:
        self.target = target
        self.password = password

    # -- SSH helpers ----------------------------------------------------------

    def _ssh(self, command: str) -> subprocess.CompletedProcess[str]:
        """Execute a single shell command on the target via SSH."""
        if self.password is not None:
            command = command.replace(
                "sudo ",
                f"echo '{self.password}' | sudo -S ",
            )
        return subprocess.run(
            ["ssh", *_SSH_OPTIONS, self.target, command],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=30,
            check=False,
        )

    def _ssh_slow(self, command: str) -> subprocess.CompletedProcess[str]:
        """Same as _ssh but with 120s timeout for slow operations."""
        if self.password is not None:
            command = command.replace(
                "sudo ",
                f"echo '{self.password}' | sudo -S ",
            )
        return subprocess.run(
            ["ssh", *_SSH_OPTIONS, self.target, command],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=120,
            check=False,
        )

    # -- apply ----------------------------------------------------------------

    def apply(self, plan: OptimizationPlan) -> None:
        """Apply the optimization plan on the target."""
        if plan.mask_unit is not None:
            self._ssh(f"sudo systemctl mask {plan.mask_unit}")
        elif plan.drop_in_content is not None and plan.drop_in_path is not None:
            if plan.category == "kernel_param":
                # Write grub config + update-grub
                escaped = plan.drop_in_content.replace("'", "'\\''")
                self._ssh(
                    f"sudo mkdir -p $(dirname {plan.drop_in_path}) && "
                    f"echo '{escaped}' | sudo tee {plan.drop_in_path} > /dev/null"
                )
                self._ssh_slow("sudo update-grub")
            elif plan.category == "initramfs_trim":
                # Write config + backup initrd (fast), then rebuild (slow)
                escaped = plan.drop_in_content.replace("'", "'\\''")
                kernel = "$(uname -r)"
                self._ssh(
                    f"sudo mkdir -p $(dirname {plan.drop_in_path}) && "
                    f"echo '{escaped}' | sudo tee {plan.drop_in_path} > /dev/null && "
                    f"sudo cp /boot/initrd.img-{kernel} /boot/initrd.img-{kernel}.kbl-backup"
                )
                self._ssh_slow("sudo update-initramfs -u -k all")
            else:
                # Standard drop-in (Phase 5 path)
                drop_in_dir = plan.drop_in_path.rsplit("/", 1)[0]
                escaped = plan.drop_in_content.replace("'", "'\\''")
                self._ssh(
                    f"sudo mkdir -p {drop_in_dir} && "
                    f"echo '{escaped}' | sudo tee {plan.drop_in_path} > /dev/null && "
                    f"sudo systemctl daemon-reload"
                )
        else:
            raise ValueError(
                f"Plan {plan.plan_id} has neither mask_unit nor drop_in content"
            )

    def rollback(self, plan: OptimizationPlan) -> None:
        """Roll back the optimization plan on the target.

        For mask plans: runs ``sudo systemctl unmask <unit>``.
        For drop-in plans: deletes the drop-in file and runs
        ``sudo systemctl daemon-reload``.
        """
        if plan.mask_unit is not None:
            self._ssh(f"sudo systemctl unmask {plan.mask_unit}")
        elif plan.drop_in_path is not None:
            if plan.category == "kernel_param":
                self._ssh_slow(
                    f"sudo rm -f {plan.drop_in_path} && sudo update-grub"
                )
            elif plan.category == "initramfs_trim":
                self._ssh_slow(
                    f"sudo rm -f {plan.drop_in_path} && sudo update-initramfs -u -k all"
                )
            else:
                self._ssh(
                    f"sudo rm -f {plan.drop_in_path} && "
                    f"sudo systemctl daemon-reload"
                )

    def verify_applied(self, plan: OptimizationPlan) -> bool:
        """Check whether the optimization is currently applied on the target."""
        if plan.mask_unit is not None:
            r = self._ssh(f"systemctl is-enabled {plan.mask_unit} 2>&1")
            return "masked" in (r.stdout or "")
        if plan.drop_in_path is not None:
            r = self._ssh(f"test -f {plan.drop_in_path}")
            return r.returncode == 0
        return False

    def apply_with_retry(
        self, plan: OptimizationPlan, max_retries: int = 2
    ) -> None:
        last_error: Exception | None = None
        for attempt in range(max_retries + 1):
            try:
                self.apply(plan)
                time.sleep(1)
                if self.verify_applied(plan):
                    return
                last_error = RuntimeError(
                    f"apply OK but verify_applied=False for {plan.plan_id}"
                )
                if attempt < max_retries:
                    time.sleep(5)
            except Exception as exc:
                last_error = exc
                if attempt < max_retries:
                    time.sleep(5)
        raise RuntimeError(
            f"Failed to apply plan {plan.plan_id} after {max_retries + 1} attempts: {last_error}"
        )
