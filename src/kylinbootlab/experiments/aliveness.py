"""SSH-based alive detection for experiment orchestration."""

import subprocess
import time


def _poll_ssh(target: str, command: list[str], timeout: float, interval: float) -> bool:
    """Poll an SSH command until it exits 0 or *timeout* seconds elapse."""
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        try:
            result = subprocess.run(
                [
                    "ssh",
                    "-o", "BatchMode=yes",
                    "-o", "ConnectTimeout=10",
                    target,
                    *command,
                ],
                check=False,
                capture_output=True,
                timeout=10,
            )
            if result.returncode == 0:
                return True
        except (OSError, subprocess.TimeoutExpired):
            pass
        time.sleep(interval)
    return False


def wait_for_ssh(
    target: str,
    timeout: float = 120,
    interval: float = 5,
) -> bool:
    """Poll *target* via SSH until successful or *timeout* seconds elapse.

    Returns ``True`` as soon as ``ssh target true`` exits 0; ``False`` if
    the deadline is reached without a successful connection.
    """
    return _poll_ssh(target, ["true"], timeout, interval)


def wait_for_boot_finished(
    target: str,
    timeout: float = 120,
    interval: float = 5,
) -> bool:
    """Poll until systemd reports startup finished on *target*.

    SSH becomes reachable several seconds before systemd finishes booting;
    collecting in that window makes ``systemd-analyze time`` fail with
    "Bootup is not yet finished".  This helper polls ``systemd-analyze time``
    itself — exit 0 means the exact command the probe needs is now ready.
    Requires *target* to already be SSH-reachable (call ``wait_for_ssh``
    first).
    """
    return _poll_ssh(target, ["systemd-analyze", "time"], timeout, interval)
