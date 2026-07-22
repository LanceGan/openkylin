"""Fault injection corpus driver for causal graph validation.

Defines 5 fault cases per spec §7.  Each case injects a systemd drop-in,
triggers one cold boot, verifies Top-3 bottleneck ranking, and restores
the system.  The ``FaultCorpusRunner`` orchestrates injection, boot,
analysis, verification, and cleanup via SSH.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Literal

if TYPE_CHECKING:
    from kylinbootlab.remote import SubprocessRunner
    from kylinbootlab.store import RunStore

# ---------------------------------------------------------------------------
# Data types
# ---------------------------------------------------------------------------


@dataclass
class FaultInjection:
    """One fault-injection test case."""

    name: str
    unit: str
    drop_in_content: str
    drop_in_path: str
    expected_ranks: list[tuple[str, str]]  # (node_name, "1-3" | "not_in_top3" | "1-2")


@dataclass
class FaultResult:
    """Outcome of one fault-injection case."""

    case: str
    status: Literal["pass", "fail", "error"]
    actual_ranking: list[str]
    expected_ranking: list[tuple[str, str]]
    error_message: str | None = None


@dataclass
class FaultCorpusReport:
    """Aggregate report across all fault cases."""

    cases: list[FaultResult]
    total_predictions: int
    correct_predictions: int

    @property
    def hit_rate(self) -> float:
        if self.total_predictions == 0:
            return 0.0
        return self.correct_predictions / self.total_predictions


# ---------------------------------------------------------------------------
# 5 canonical fault cases (spec §7)
# ---------------------------------------------------------------------------

# Shared prefix for all drop-in files
_DROPIN_HEADER = "[Unit]\nDescription=kbl-fault\n"

# Case 1: Critical-path fake dependency on NetworkManager
CASE1_DROPIN = _DROPIN_HEADER + "After=foo-slow.service\n"
CASE1_FOO_UNIT = "[Unit]\nDescription=kbl-fault-fake-unit\n"

# Case 2: dbus Exclusive delay (sleep 3s)
CASE2_DROPIN = "[Service]\nExecStartPre=/bin/sleep 3\n"

# Case 3: No-op delay on large-slack unit (ukui-bluetooth)
CASE3_DROPIN = "[Service]\nExecStartPre=/bin/sleep 5\n"

# Case 4: lightdm delay
CASE4_DROPIN = "[Service]\nExecStartPre=/bin/sleep 2\n"

# Case 5: Combined dbus + lightdm
CASE5_DBUS_DROPIN = "[Service]\nExecStartPre=/bin/sleep 2\n"
CASE5_LIGHTDM_DROPIN = "[Service]\nExecStartPre=/bin/sleep 2\n"

FAULT_CASES: list[FaultInjection] = [
    FaultInjection(
        name="critical-path-fake-dep",
        unit="NetworkManager.service",
        drop_in_content=CASE1_DROPIN,
        drop_in_path="/etc/systemd/system/NetworkManager.service.d/kbl-fault.conf",
        expected_ranks=[("NetworkManager.service", "1-1")],
    ),
    FaultInjection(
        name="exclusive-delay-dbus",
        unit="dbus.service",
        drop_in_content=CASE2_DROPIN,
        drop_in_path="/etc/systemd/system/dbus.service.d/kbl-fault.conf",
        expected_ranks=[("dbus.service", "1-1")],
    ),
    FaultInjection(
        name="no-op-delay-bluetooth",
        unit="ukui-bluetooth.service",
        drop_in_content=CASE3_DROPIN,
        drop_in_path="/etc/systemd/system/ukui-bluetooth.service.d/kbl-fault.conf",
        expected_ranks=[("ukui-bluetooth.service", "not_in_top3")],
    ),
    FaultInjection(
        name="lightdm-delay",
        unit="lightdm.service",
        drop_in_content=CASE4_DROPIN,
        drop_in_path="/etc/systemd/system/lightdm.service.d/kbl-fault.conf",
        expected_ranks=[("lightdm.service", "1-2")],
    ),
    FaultInjection(
        name="combined-dbus-lightdm",
        unit="dbus.service",  # primary unit (Case 5 has two drop-ins)
        drop_in_content=CASE5_DBUS_DROPIN,
        drop_in_path="/etc/systemd/system/dbus.service.d/kbl-fault.conf",
        expected_ranks=[
            ("dbus.service", "1-2"),
            ("lightdm.service", "1-2"),
        ],
    ),
]

# Additional drop-in for Case 5 (lightdm side)
CASE5_EXTRA_DROPIN = FaultInjection(
    name="combined-dbus-lightdm-lightdm",
    unit="lightdm.service",
    drop_in_content=CASE5_LIGHTDM_DROPIN,
    drop_in_path="/etc/systemd/system/lightdm.service.d/kbl-fault.conf",
    expected_ranks=[],  # covered by the main Case 5 entry
)


# ---------------------------------------------------------------------------
# Command builders (testable without real SSH)
# ---------------------------------------------------------------------------


def build_inject_commands(case: FaultInjection) -> list[str]:
    """Build the SSH command lines for injecting a fault case.

    Returns a list of strings; each is a complete command to run on the
    target (e.g. via ``ssh target ...``).
    """
    cmds: list[str] = []

    # Case 1 special: create the fake foo-slow.service unit first
    if case.name == "critical-path-fake-dep":
        foo_unit = "[Unit]\nDescription=kbl-fault-fake-unit\n"
        cmds.append(
            f"echo '{foo_unit}' | sudo tee /etc/systemd/system/foo-slow.service"
        )
        cmds.append("sudo systemctl daemon-reload")

    # Create drop-in directory
    drop_in_dir = case.drop_in_path.rsplit("/", 1)[0]
    cmds.append(f"sudo mkdir -p {drop_in_dir}")

    # Write drop-in
    escaped = case.drop_in_content.replace("'", "'\\''")
    cmds.append(f"echo '{escaped}' | sudo tee {case.drop_in_path}")

    # Reload systemd
    cmds.append("sudo systemctl daemon-reload")

    # Case 5: also write the lightdm drop-in
    if case.name == "combined-dbus-lightdm":
        lightdm_dir = "/etc/systemd/system/lightdm.service.d"
        lightdm_content = CASE5_LIGHTDM_DROPIN.replace("'", "'\\''")
        cmds.append(f"sudo mkdir -p {lightdm_dir}")
        cmds.append(
            f"echo '{lightdm_content}' | sudo tee {lightdm_dir}/kbl-fault.conf"
        )
        cmds.append("sudo systemctl daemon-reload")

    return cmds


def build_cleanup_commands(case: FaultInjection) -> list[str]:
    """Build the SSH command lines for restoring the target after a case."""
    cmds: list[str] = []

    # Remove drop-in
    cmds.append(f"sudo rm -f {case.drop_in_path}")

    # Case 1: also remove the fake unit
    if case.name == "critical-path-fake-dep":
        cmds.append("sudo rm -f /etc/systemd/system/foo-slow.service")

    # Case 5: also remove lightdm drop-in
    if case.name == "combined-dbus-lightdm":
        cmds.append("sudo rm -f /etc/systemd/system/lightdm.service.d/kbl-fault.conf")

    # Reload
    cmds.append("sudo systemctl daemon-reload")

    return cmds


# ---------------------------------------------------------------------------
# Fault corpus runner (orchestration — full loop in Task 9)
# ---------------------------------------------------------------------------


class FaultCorpusRunner:
    """Orchestrates fault injection, boot, verification, and cleanup on a remote target.

    The full inject-boot-analyze-verify-restore loop is implemented in Task 9.
    Task 8 provides the command builders and data model that Task 9 depends on.
    """

    def __init__(
        self,
        target: str,
        store: RunStore,
        incoming_root: Path,
        runner: SubprocessRunner,
    ) -> None:
        self.target = target
        self.store = store
        self.incoming_root = incoming_root
        self.runner = runner

    def run_case(self, fi: FaultInjection) -> FaultResult:
        """Inject fault, trigger boot, verify ranking, and restore.

        Not yet automated — the 5-case fault corpus was executed manually via
        ``scripts/fault_corpus_run.py`` during Phase 4 acceptance.
        Full automation is planned for Phase 10 (final validation).
        """
        return FaultResult(
            case=fi.name,
            status="error",
            actual_ranking=[],
            expected_ranking=[("see scripts/fault_corpus_run.py", "manual-only")],
            error_message="FaultCorpusRunner.run_case requires a live target; use scripts/fault_corpus_run.py instead.",
        )

    def run_all(self, cases: list[FaultInjection]) -> FaultCorpusReport:
        """Run all fault cases and produce an aggregate report."""
        results: list[FaultResult] = []
        for case in cases:
            try:
                result = self.run_case(case)
                results.append(result)
            except Exception as exc:
                results.append(
                    FaultResult(
                        case=case.name,
                        status="error",
                        actual_ranking=[],
                        expected_ranking=case.expected_ranks,
                        error_message=str(exc),
                    )
                )
        total = len(results)
        correct = sum(1 for r in results if r.status == "pass")
        return FaultCorpusReport(
            cases=results,
            total_predictions=total,
            correct_predictions=correct,
        )
