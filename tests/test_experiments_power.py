import subprocess

import pytest

from kylinbootlab.experiments.power import (
    VMRUN,
    PowerControlError,
    TargetPower,
    VixPower,
    WolPower,
    power_backend_factory,
)

VMX = r"C:\VMs\test.vmx"


class FakeSubprocessRun:
    """Records calls so we can assert command construction without real vmrun."""

    def __init__(self, *, returncode: int = 0, stdout: str = "", stderr: str = "") -> None:
        self.calls: list[list[str]] = []
        self.returncode = returncode
        self.stdout = stdout
        self.stderr = stderr

    def __call__(self, args: list[str], **kwargs: object) -> subprocess.CompletedProcess[str]:
        self.calls.append(args)
        return subprocess.CompletedProcess(
            args, self.returncode, stdout=self.stdout, stderr=self.stderr
        )


def _assert_vmrun_prefix(cmd: list[str]) -> None:
    """Every VixPower call is ``<...>/vmrun.exe -T ws <verb> ...``."""
    assert cmd[0].endswith("vmrun.exe")
    assert cmd[1:3] == ["-T", "ws"]


def test_power_backend_vix_is_registered() -> None:
    power = power_backend_factory("vix", vmx_path=VMX)
    assert isinstance(power, VixPower)


def test_power_backend_vix_requires_vmx_path() -> None:
    with pytest.raises(ValueError, match="vmx_path is required"):
        power_backend_factory("vix")


def test_power_backend_unknown_raises() -> None:
    with pytest.raises(ValueError, match="unknown power backend"):
        power_backend_factory("unknown")


def test_vix_power_satisfies_target_power_protocol() -> None:
    power: TargetPower = VixPower(VMX, _runner=FakeSubprocessRun())
    assert power.guest_alive() is False


def test_vix_uses_default_vmrun_path() -> None:
    fake_run = FakeSubprocessRun()
    power = VixPower(VMX, _runner=fake_run)

    power.power_on()

    assert fake_run.calls[-1][0] == VMRUN


def test_vix_vmrun_path_is_configurable() -> None:
    fake_run = FakeSubprocessRun()
    power = VixPower(VMX, vmrun_path=r"D:\tools\vmrun.exe", _runner=fake_run)

    power.power_on()

    assert fake_run.calls[-1][0] == r"D:\tools\vmrun.exe"


def test_vix_power_on_constructs_vmrun_command() -> None:
    fake_run = FakeSubprocessRun()
    power = VixPower(VMX, _runner=fake_run)

    power.power_on()

    cmd = fake_run.calls[-1]
    _assert_vmrun_prefix(cmd)
    assert cmd[3:] == ["start", VMX, "nogui"]


def test_vix_power_off_constructs_vmrun_command() -> None:
    fake_run = FakeSubprocessRun()
    power = VixPower(VMX, _runner=fake_run)

    power.power_off()

    cmd = fake_run.calls[-1]
    _assert_vmrun_prefix(cmd)
    assert cmd[3:] == ["stop", VMX, "hard"]


def test_vix_reset_constructs_vmrun_command() -> None:
    fake_run = FakeSubprocessRun()
    power = VixPower(VMX, _runner=fake_run)

    power.reset()

    cmd = fake_run.calls[-1]
    _assert_vmrun_prefix(cmd)
    assert cmd[3:] == ["reset", VMX, "hard"]


def test_vix_snapshot_create_constructs_vmrun_command() -> None:
    fake_run = FakeSubprocessRun()
    power = VixPower(VMX, _runner=fake_run)

    power.snapshot_create("pre-tune")

    cmd = fake_run.calls[-1]
    _assert_vmrun_prefix(cmd)
    assert cmd[3:] == ["snapshot", VMX, "pre-tune"]


def test_vix_snapshot_restore_constructs_vmrun_command() -> None:
    fake_run = FakeSubprocessRun()
    power = VixPower(VMX, _runner=fake_run)

    power.snapshot_restore("baseline")

    cmd = fake_run.calls[-1]
    _assert_vmrun_prefix(cmd)
    assert cmd[3:] == ["revertToSnapshot", VMX, "baseline"]


@pytest.mark.parametrize(
    ("method", "args"),
    [
        ("power_on", ()),
        ("power_off", ()),
        ("reset", ()),
        ("snapshot_create", ("baseline",)),
        ("snapshot_restore", ("baseline",)),
    ],
)
def test_vix_mutating_op_failure_raises(method: str, args: tuple[str, ...]) -> None:
    """vmrun non-zero exit on any mutating operation must fail loud."""
    fake_run = FakeSubprocessRun(returncode=255, stderr="Error: The operation was canceled")
    power = VixPower(VMX, _runner=fake_run)

    with pytest.raises(PowerControlError, match="vmrun"):
        getattr(power, method)(*args)


def test_vix_power_off_already_off_is_idempotent() -> None:
    """vmrun stop on an off VM says 'not powered on' — treated as success."""
    fake_run = FakeSubprocessRun(
        returncode=255,
        stdout="Error: The virtual machine is not powered on: " + VMX,
    )
    power = VixPower(VMX, _runner=fake_run)

    power.power_off()  # must not raise

    assert len(fake_run.calls) == 1


def test_vix_reset_already_off_is_idempotent() -> None:
    """Same carve-out for reset, and it applies to stderr output too."""
    fake_run = FakeSubprocessRun(
        returncode=255,
        stderr="Error: The virtual machine is not powered on: " + VMX,
    )
    power = VixPower(VMX, _runner=fake_run)

    power.reset()  # must not raise

    assert len(fake_run.calls) == 1


def test_vix_guest_alive_constructs_list_command() -> None:
    fake_run = FakeSubprocessRun(stdout="Total running VMs: 0\n")
    power = VixPower(VMX, _runner=fake_run)

    power.guest_alive()

    cmd = fake_run.calls[-1]
    _assert_vmrun_prefix(cmd)
    assert cmd[3:] == ["list"]


def test_vix_guest_alive_true_when_vm_listed() -> None:
    """The vmx path comparison is case-insensitive."""
    fake_run = FakeSubprocessRun(stdout="Total running VMs: 1\nC:\\VMs\\TEST.VMX\n")
    power = VixPower(VMX, _runner=fake_run)

    assert power.guest_alive() is True


def test_vix_guest_alive_false_when_vm_not_listed() -> None:
    fake_run = FakeSubprocessRun(stdout="Total running VMs: 1\nC:\\VMs\\other.vmx\n")
    power = VixPower(VMX, _runner=fake_run)

    assert power.guest_alive() is False


def test_vix_guest_alive_false_when_vmrun_fails() -> None:
    fake_run = FakeSubprocessRun(returncode=1, stdout=VMX)
    power = VixPower(VMX, _runner=fake_run)

    assert power.guest_alive() is False


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
