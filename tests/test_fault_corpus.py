"""Unit tests for fault corpus driver — command construction only."""

import pytest

from kylinbootlab.analysis.fault_corpus import (
    FAULT_CASES,
    FaultCorpusReport,
    FaultResult,
    build_cleanup_commands,
    build_inject_commands,
)


class TestFaultInjection:
    def test_case1_fake_dependency_structure(self) -> None:
        case = FAULT_CASES[0]
        assert case.name == "critical-path-fake-dep"
        assert case.unit == "NetworkManager.service"
        assert "After=foo-slow.service" in case.drop_in_content
        assert "/etc/systemd/system/NetworkManager.service.d/kbl-fault.conf" in case.drop_in_path

    def test_case2_sleep_delay_structure(self) -> None:
        case = FAULT_CASES[1]
        assert case.name == "exclusive-delay-dbus"
        assert case.unit == "dbus.service"
        assert "/bin/sleep 3" in case.drop_in_content or "ExecStartPre" in case.drop_in_content
        assert "/etc/systemd/system/dbus.service.d/kbl-fault.conf" in case.drop_in_path


class TestCommandConstruction:
    def test_inject_commands_for_case2(self) -> None:
        """Case 2 (dbus sleep) inject commands are well-formed."""
        case = FAULT_CASES[1]
        cmds = build_inject_commands(case)
        assert len(cmds) >= 2
        # mkdir + tee for drop-in
        assert any("mkdir" in c for c in cmds)
        assert any("tee" in c for c in cmds)
        assert any("daemon-reload" in c for c in cmds)
        # The drop-in path should be in the tee command
        tee_cmd = next(c for c in cmds if "tee" in c)
        assert case.drop_in_path in tee_cmd

    def test_cleanup_commands_for_case4(self) -> None:
        """Case 4 (lightdm) cleanup removes drop-in and reloads."""
        case = FAULT_CASES[3]
        cmds = build_cleanup_commands(case)
        assert any("rm -f" in c for c in cmds)
        assert any("daemon-reload" in c for c in cmds)

    def test_inject_commands_for_case1_includes_foo_slow_unit(self) -> None:
        """Case 1 needs both a new unit file AND a drop-in."""
        case = FAULT_CASES[0]
        cmds = build_inject_commands(case)
        assert any("foo-slow" in c for c in cmds)

    def test_cleanup_commands_for_case1_remove_both(self) -> None:
        case = FAULT_CASES[0]
        cmds = build_cleanup_commands(case)
        assert any("foo-slow" in c for c in cmds)
        assert any("NetworkManager" in c for c in cmds)


class TestFaultResult:
    def test_pass_status(self) -> None:
        r = FaultResult(
            case="test-case",
            status="pass",
            actual_ranking=["dbus.service", "NetworkManager.service", "lightdm.service"],
            expected_ranking=[("dbus.service", "1-3")],
        )
        assert r.status == "pass"

    def test_fail_status(self) -> None:
        r = FaultResult(
            case="test-case",
            status="fail",
            actual_ranking=["wpa_supplicant.service"],
            expected_ranking=[("dbus.service", "1-3")],
        )
        assert r.status == "fail"


class TestFaultCorpusReport:
    def test_hit_rate_calculation(self) -> None:
        report = FaultCorpusReport(
            cases=[
                FaultResult(
                    case="c1", status="pass", actual_ranking=["a"],
                    expected_ranking=[("a", "1-1")],
                ),
                FaultResult(
                    case="c2", status="pass", actual_ranking=["b"],
                    expected_ranking=[("b", "1-3")],
                ),
                FaultResult(
                    case="c3", status="fail", actual_ranking=["d"],
                    expected_ranking=[("c", "1-3")],
                ),
            ],
            total_predictions=3,
            correct_predictions=2,
        )
        assert report.hit_rate == pytest.approx(2 / 3)

    def test_hit_rate_zero_when_no_predictions(self) -> None:
        report = FaultCorpusReport(cases=[], total_predictions=0, correct_predictions=0)
        assert report.hit_rate == 0.0
