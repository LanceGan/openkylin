"""SSH-based alive detection for experiment orchestration."""

import subprocess
import time


def wait_for_ssh(
    target: str,
    timeout: float = 120,
    interval: float = 5,
) -> bool:
    """Poll *target* via SSH until successful or *timeout* seconds elapse.

    Returns ``True`` as soon as ``ssh target true`` exits 0; ``False`` if
    the deadline is reached without a successful connection.
    """
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        try:
            result = subprocess.run(
                [
                    "ssh",
                    "-o", "BatchMode=yes",
                    "-o", "ConnectTimeout=10",
                    target,
                    "true",
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
