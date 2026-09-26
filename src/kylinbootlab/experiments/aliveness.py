"""SSH-based alive detection for experiment orchestration."""

import subprocess
import time

#: Observer state directory on the target (kbl-group-writable, Phase 3).
OBSERVE_STATE_DIR = "/var/lib/kylinbootlab/observe"

#: Enabled marker — also the observer unit's ``ConditionPathExists``.
#: Absent means the observer is off for this boot (calibration bare group
#: removes only this marker; the directory stays) or was never deployed;
#: either way no done marker will ever appear.
_ENABLED_MARKER = f"{OBSERVE_STATE_DIR}/enabled"

#: Remote test: the done marker exists AND carries the CURRENT boot_id, so
#: a stale marker left by a previous boot can never satisfy the gate.
_DONE_MATCHES_BOOT = (
    f'test "$(cat {OBSERVE_STATE_DIR}/done 2>/dev/null)" '
    '= "$(cat /proc/sys/kernel/random/boot_id)"'
)


def _ssh_once(target: str, command: list[str]) -> bool:
    """One SSH probe; True iff the remote command exits 0."""
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
    except (OSError, subprocess.TimeoutExpired):
        return False
    return result.returncode == 0


def _poll_ssh(target: str, command: list[str], timeout: float, interval: float) -> bool:
    """Poll an SSH command until it exits 0 or *timeout* seconds elapse."""
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if _ssh_once(target, command):
            return True
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


def wait_for_observer_done(
    target: str,
    timeout: float = 300,
    interval: float = 5,
) -> bool:
    """Gate collection on the Phase 3 observer's boot_id-stamped done marker.

    Fast-degrade (spec §4.3): a single probe of the ``enabled`` marker —
    absent means the observer will not run this boot, either because it is
    intentionally off (calibration bare group: the marker is removed but
    the state directory remains, and ``ConditionPathExists`` keeps the
    unit from starting) or because it was never deployed.  In both cases
    no ``done`` marker will ever appear, so the gate passes immediately;
    one probe covers both, and pre-Phase-3 targets work unchanged.

    When the marker is present, polls until ``done`` exists and its
    content equals the current boot_id (stale markers from earlier boots
    never match).  The 300 s default covers the worst-case chain: greeter
    90 s + injection 30 s + usable 120 s + margin (spec §4.3).  Call only
    after ``wait_for_boot_finished`` succeeded, so SSH flakiness cannot
    be mistaken for a missing deployment.
    """
    if not _ssh_once(target, ["test", "-f", _ENABLED_MARKER]):
        return True
    return _poll_ssh(target, [_DONE_MATCHES_BOOT], timeout, interval)
