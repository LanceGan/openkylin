import subprocess

import pytest

from kylinbootlab.experiments.recovery import RecoveryFailedError, RecoveryManager


class StubPower:
    """Stub TargetPower recording calls and allowing injection of failures."""

    def __init__(self) -> None:
        self.calls: list[str] = []
        self._snapshot_recoverable = True

    def snapshot_restore(self, name: str) -> None:
        self.calls.append(f"snap:{name}")
        if not self._snapshot_recoverable:
            raise RuntimeError("VIX not responding")

    def power_on(self) -> None:
        self.calls.append("power_on")

    def power_off(self) -> None:
        self.calls.append("power_off")

    def reset(self) -> None:
        self.calls.append("reset")

    def snapshot_create(self, name: str) -> None:
        self.calls.append(f"snap_create:{name}")

    def guest_alive(self) -> bool:
        return False


class StubRunner:
    """Stub subprocess runner for SSH-triggered ostree commands."""

    def __init__(self, *, succeed: bool = True) -> None:
        self.calls: list[list[str]] = []
        self.succeed = succeed

    def __call__(self, args: list[str]) -> subprocess.CompletedProcess[str]:
        self.calls.append(args)
        rc = 0 if self.succeed else 1
        return subprocess.CompletedProcess(args, rc, stdout="", stderr="")


def test_snapshot_restore_is_first_layer() -> None:
    power = StubPower()
    RecoveryManager.restore(power, "kbl@target.local")

    assert "snap:baseline" in power.calls
    assert power.calls[0] == "snap:baseline"
    assert "power_on" in power.calls


def test_ostree_fallback_when_snapshot_fails() -> None:
    power = StubPower()
    power._snapshot_recoverable = False
    runner = StubRunner()

    RecoveryManager.restore(power, "kbl@target.local", runner=runner)

    assert power.calls == ["snap:baseline"]  # tried and failed
    # Fallback should have triggered SSH commands
    assert any("ostree" in " ".join(c) for c in runner.calls)


def test_both_layers_fail_raises_recovery_failed() -> None:
    power = StubPower()
    power._snapshot_recoverable = False
    runner = StubRunner(succeed=False)

    with pytest.raises(RecoveryFailedError):
        RecoveryManager.restore(power, "kbl@target.local", runner=runner)
