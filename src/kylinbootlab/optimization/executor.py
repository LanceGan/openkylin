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
        """Execute a single shell command on the target via SSH.

        When *self.password* is set, ``sudo`` commands are prefixed with
        ``echo '<password>' | sudo -S`` so they work in non-interactive mode.
        The *command* is passed as a single string to ``ssh <target> <command>``
        so that pipes, redirects, and compound statements work correctly.
        """
        if self.password is not None and "sudo " in command:
            command = command.replace(
                "sudo ",
                f"echo '{self.password}' | sudo -S ",
                1,
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

    # -- apply ----------------------------------------------------------------

    def apply(self, plan: OptimizationPlan) -> None:
        """Apply the optimization plan on the target.

        For mask plans: runs ``sudo systemctl mask <unit>``.
        For drop-in plans: creates the drop-in directory, writes the .conf file
        via ``sudo tee``, then runs ``sudo systemctl daemon-reload``.
        """
        if plan.mask_unit is not None:
            self._ssh(f"sudo systemctl mask {plan.mask_unit}")
        elif plan.drop_in_content is not None and plan.drop_in_path is not None:
            drop_in_dir = plan.drop_in_path.rsplit("/", 1)[0]
            escaped_content = plan.drop_in_content.replace("'", "'\\''")
            self._ssh(
                f"sudo mkdir -p {drop_in_dir} && "
                f"echo '{escaped_content}' | sudo tee {plan.drop_in_path} > /dev/null && "
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
        """Apply the plan with retries on failure.

        Retries up to *max_retries* times (total attempts = max_retries + 1)
        with a 5-second interval between attempts.  Raises ``RuntimeError``
        if all attempts fail.
        """
        last_error: Exception | None = None
        for attempt in range(max_retries + 1):
            try:
                self.apply(plan)
                # Verify the application succeeded
                if self.verify_applied(plan):
                    return
                raise RuntimeError(
                    f"apply succeeded but verify_applied returned False for {plan.plan_id}"
                )
            except Exception as exc:
                last_error = exc
                if attempt < max_retries:
                    time.sleep(5)
        raise RuntimeError(
            f"Failed to apply plan {plan.plan_id} after {max_retries + 1} attempts: {last_error}"
        )
