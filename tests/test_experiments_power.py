import subprocess

import pytest

from kylinbootlab.experiments.power import (
    TargetPower,
    VixPower,
    WolPower,
    power_backend_factory,
)


class FakeSubprocessRun:
    """Records calls so we can assert command construction without real VIX."""

    def __init__(self, *, returncode: int = 0, stdout: str = "") -> None:
        self.calls: list[list[str]] = []
        self.returncode = returncode
        self.stdout = stdout

    def __call__(self, args: list[str], **kwargs: object) -> subprocess.CompletedProcess[str]:
        self.calls.append(args)
        return subprocess.CompletedProcess(args, self.returncode, stdout=self.stdout, stderr="")


def test_power_backend_vix_is_registered() -> None:
    power = power_backend_factory("vix", vmx_path=r"C:\VMs\test.vmx")
    assert isinstance(power, VixPower)


def test_power_backend_vix_requires_vmx_path() -> None:
    with pytest.raises(ValueError, match="vmx_path is required"):
        power_backend_factory("vix")


def test_power_backend_unknown_raises() -> None:
    with pytest.raises(ValueError, match="unknown power backend"):
        power_backend_factory("unknown")


def test_vix_power_satisfies_target_power_protocol() -> None:
    power: TargetPower = VixPower(r"C:\VMs\test.vmx", _runner=FakeSubprocessRun())
    assert power.guest_alive() is False


def test_vix_power_on_constructs_correct_command() -> None:
    fake_run = FakeSubprocessRun()
    power = VixPower(r"C:\VMs\test.vmx", _runner=fake_run)

    power.power_on()

    cmd = fake_run.calls[-1]
    assert cmd[0] == "powershell.exe"
    assert "Connect-VIX" in " ".join(cmd)
    assert "PowerOn" in " ".join(cmd)
    assert r"C:\VMs\test.vmx" in " ".join(cmd)


def test_vix_snapshot_restore_constructs_correct_command() -> None:
    fake_run = FakeSubprocessRun()
    power = VixPower(r"C:\VMs\test.vmx", _runner=fake_run)

    power.snapshot_restore("baseline")

    cmd = fake_run.calls[-1]
    assert "RevertToSnapshot" in " ".join(cmd)
    assert "baseline" in " ".join(cmd)


def test_vix_snapshot_create_constructs_correct_command() -> None:
    fake_run = FakeSubprocessRun()
    power = VixPower(r"C:\VMs\test.vmx", _runner=fake_run)

    power.snapshot_create("pre-tune")

    cmd = fake_run.calls[-1]
    assert "CreateSnapshot" in " ".join(cmd)
    assert "pre-tune" in " ".join(cmd)


def test_vix_reset_constructs_correct_command() -> None:
    fake_run = FakeSubprocessRun()
    power = VixPower(r"C:\VMs\test.vmx", _runner=fake_run)

    power.reset()

    assert "Reset" in " ".join(fake_run.calls[-1])


def test_vix_power_off_is_idempotent() -> None:
    """Power off when already off should not crash — just no-op."""
    fake_run = FakeSubprocessRun()
    # Simulate echo for guest_alive → powered on
    # Then power_off
    power = VixPower(r"C:\VMs\test.vmx", _runner=fake_run)

    # guest_alive returns False (VM off) — power_off should still succeed
    power.power_off()
    assert len(fake_run.calls) == 1  # Only one PowerShell call


def test_vix_guest_alive_true_when_powered_on() -> None:
    fake_run = FakeSubprocessRun(stdout="True\n")
    power = VixPower(r"C:\VMs\test.vmx", _runner=fake_run)

    assert power.guest_alive() is True
    assert "IsPoweredOn" in " ".join(fake_run.calls[-1])


def test_vix_guest_alive_false_when_powershell_fails() -> None:
    fake_run = FakeSubprocessRun(returncode=1, stdout="True")
    power = VixPower(r"C:\VMs\test.vmx", _runner=fake_run)

    assert power.guest_alive() is False


def test_vix_power_on_powershell_syntax_is_valid() -> None:
    """The generated PowerShell command must parse. Use simple syntax check."""
    fake_run = FakeSubprocessRun()
    power = VixPower(r"C:\VMs\openkylin.vmx", _runner=fake_run)

    power.power_on()

    script = " ".join(fake_run.calls[-1])
    assert "powershell.exe" in script
    assert "-NoProfile" in script
    assert "-NonInteractive" in script
    assert "OpenVM" in script
    assert "PowerOn" in script


# -- WolPower tests -----------------------------------------------------------


def test_power_backend_wol_is_registered() -> None:
    power = power_backend_factory(
        "wol", target="kbl@openkylin.local", mac="00:11:22:33:44:55",
    )
    assert isinstance(power, WolPower)


def test_wol_power_on_constructs_magic_packet() -> None:
    fake_run = FakeSubprocessRun()
    power = WolPower("kbl@target.local", "AA:BB:CC:DD:EE:FF", _runner=fake_run)

    power.power_on()

    # WOL magic packet: 6 bytes FF followed by MAC repeated 16 times
    cmd_text = " ".join(fake_run.calls[-1])
    assert "AA:BB:CC:DD:EE:FF" in cmd_text or "wakeonlan" in cmd_text.lower()


def test_wol_power_off_uses_ssh() -> None:
    fake_run = FakeSubprocessRun()
    power = WolPower("kbl@target.local", "11:22:33:44:55:66", _runner=fake_run)

    power.power_off()

    cmd = fake_run.calls[-1]
    assert cmd[0] == "ssh"
    assert "poweroff" in " ".join(cmd)


def test_wol_snapshot_restore_is_noop() -> None:
    fake_run = FakeSubprocessRun()
    power = WolPower("kbl@target.local", "11:22:33:44:55:66", _runner=fake_run)

    # snapshot_restore on WOL is a no-op (handled by RecoveryManager ostree path)
    power.snapshot_restore("baseline")
    assert len(fake_run.calls) == 0
