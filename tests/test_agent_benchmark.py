"""Unit tests for benchmark evaluator — case loading, structural scoring, CLI smoke."""

from __future__ import annotations

from pathlib import Path

import pytest

from kylinbootlab.agent.benchmark import BenchmarkCase, evaluate, load_benchmark
from kylinbootlab.agent.models import (
    Anomaly,
    BootAgentReport,
    ExperimentPlan,
    SafetyReview,
    TraceAnalysis,
)

# -- helpers -------------------------------------------------------------------

CASES_PATH = Path("agent/benchmark/cases.json")


def _make_anomaly(node: str = "dbus.service") -> Anomaly:
    return Anomaly(
        node=node,
        blame_ns=900_000_000,
        slack_ns=100_000_000,
        on_critical_path=True,
        issue="high blame on critical path",
        evidence="systemd-analyze blame: 900ms",
    )


def _make_full_trace() -> TraceAnalysis:
    return TraceAnalysis(
        anomalies=[_make_anomaly("dbus.service"), _make_anomaly("lightdm.service")],
        cross_boot_volatility="stable across 5 cold boots",
        missed_bottlenecks=["NetworkManager-wait-online.service"],
        confidence=0.85,
    )


def _make_experiment() -> ExperimentPlan:
    return ExperimentPlan(
        plan_id="mask-bluetooth",
        hypothesis="Masking ukui-bluetooth saves 500ms",
        predicted_gain_ns=500_000_000,
        evidence_chain=["blame data", "slack analysis"],
        drop_in_content=None,
        rollback=["sudo rm /etc/systemd/system/ukui-bluetooth.service.d/override.conf"],
        functional_regression=["Bluetooth audio unavailable"],
        falsification="If boot time does not decrease by >=400ms, hypothesis is false",
    )


def _make_safety() -> SafetyReview:
    return SafetyReview(
        risk_score=0.2,
        concerns=["Bluetooth audio will be unavailable"],
        functional_regression_risks=["No Bluetooth on login"],
        portability_concern=None,
        recommendation="APPROVE",
    )


# -- load_benchmark tests ------------------------------------------------------


def test_load_benchmark_loads_five_cases() -> None:
    """cases.json contains exactly 5 benchmark cases with expected fields."""
    cases = load_benchmark(CASES_PATH)
    assert len(cases) == 5
    for case in cases:
        assert isinstance(case, BenchmarkCase)
        assert case.id.startswith("B")
        assert len(case.name) > 0
        assert "anomaly_node" in case.ground_truth
        assert "expected_issue" in case.ground_truth


def test_load_benchmark_case_ids_are_unique() -> None:
    """All benchmark case IDs are unique."""
    cases = load_benchmark(CASES_PATH)
    ids = [c.id for c in cases]
    assert len(ids) == len(set(ids))


def test_load_benchmark_ground_truth_values() -> None:
    """Each ground truth has the expected shape."""
    cases = load_benchmark(CASES_PATH)
    b1 = next(c for c in cases if c.id == "B1")
    assert b1.ground_truth["anomaly_node"] == "dbus.service"
    assert "critical path" in b1.ground_truth["expected_issue"]

    b5 = next(c for c in cases if c.id == "B5")
    assert "dbus.service" in b5.ground_truth["anomaly_node"]
    assert "lightdm.service" in b5.ground_truth["anomaly_node"]


# -- structural scoring tests --------------------------------------------------


def test_score_full_report_returns_one() -> None:
    """A report with all four sections populated scores 1.0."""
    report = BootAgentReport(
        run_id="test-run",
        trace=_make_full_trace(),
        source=None,  # source is not scored
        experiment=_make_experiment(),
        safety=_make_safety(),
    )
    case = BenchmarkCase(
        id="B1",
        name="test",
        ground_truth={"anomaly_node": "dbus.service", "expected_issue": "test"},
    )
    assert case.score(report) == pytest.approx(1.0)


def test_score_empty_report_returns_zero() -> None:
    """A report with all sections None scores 0.0."""
    report = BootAgentReport(run_id="test-run")
    case = BenchmarkCase(
        id="B1",
        name="test",
        ground_truth={"anomaly_node": "dbus.service", "expected_issue": "test"},
    )
    assert case.score(report) == pytest.approx(0.0)


def test_score_partial_report_anomalies_only() -> None:
    """Anomalies present but no missed_bottlenecks, experiment, or safety -> 0.3."""
    report = BootAgentReport(
        run_id="test-run",
        trace=TraceAnalysis(
            anomalies=[_make_anomaly()],
            cross_boot_volatility="low",
            missed_bottlenecks=[],
            confidence=0.5,
        ),
    )
    case = BenchmarkCase(
        id="B1",
        name="test",
        ground_truth={"anomaly_node": "x", "expected_issue": "x"},
    )
    assert case.score(report) == pytest.approx(0.3)


def test_score_experiment_and_safety_only() -> None:
    """No trace, but experiment + safety -> 0.4."""
    report = BootAgentReport(
        run_id="test-run",
        experiment=_make_experiment(),
        safety=_make_safety(),
    )
    case = BenchmarkCase(
        id="B1",
        name="test",
        ground_truth={"anomaly_node": "x", "expected_issue": "x"},
    )
    assert case.score(report) == pytest.approx(0.4)


def test_score_trace_with_both_fields() -> None:
    """Both anomalies and missed_bottlenecks present -> 0.6 from trace alone."""
    report = BootAgentReport(
        run_id="test-run",
        trace=TraceAnalysis(
            anomalies=[_make_anomaly()],
            cross_boot_volatility="low",
            missed_bottlenecks=["something.service"],
            confidence=0.5,
        ),
    )
    case = BenchmarkCase(
        id="B1",
        name="test",
        ground_truth={"anomaly_node": "x", "expected_issue": "x"},
    )
    assert case.score(report) == pytest.approx(0.6)


# -- evaluate tests ------------------------------------------------------------


def test_evaluate_returns_average() -> None:
    """evaluate() averages scores across all cases."""
    report = BootAgentReport(
        run_id="test-run",
        trace=_make_full_trace(),
        experiment=_make_experiment(),
        safety=_make_safety(),
    )
    cases = load_benchmark(CASES_PATH)
    result = evaluate(report, cases)
    assert result == pytest.approx(1.0)


def test_evaluate_empty_cases_returns_zero() -> None:
    """evaluate with an empty list returns 0.0."""
    report = BootAgentReport(run_id="test-run")
    assert evaluate(report, []) == 0.0


# -- CLI smoke tests -----------------------------------------------------------


def test_cli_agent_help() -> None:
    """``kbl agent --help`` exits cleanly."""
    from typer.testing import CliRunner

    from kylinbootlab.cli import app

    runner = CliRunner()
    result = runner.invoke(app, ["agent", "--help"])
    assert result.exit_code == 0
    assert "BootAgent" in result.stdout


def test_cli_agent_benchmark_help() -> None:
    """``kbl agent benchmark --help`` exits cleanly and shows option text."""
    from typer.testing import CliRunner

    from kylinbootlab.cli import app

    runner = CliRunner()
    result = runner.invoke(app, ["agent", "benchmark", "--help"])
    assert result.exit_code == 0
    assert "benchmark" in result.stdout.lower()


def test_cli_agent_analyze_help() -> None:
    """``kbl agent analyze --help`` exits cleanly and shows argument text."""
    from typer.testing import CliRunner

    from kylinbootlab.cli import app

    runner = CliRunner()
    result = runner.invoke(app, ["agent", "analyze", "--help"])
    assert result.exit_code == 0
    assert "run_id" in result.stdout.lower()
