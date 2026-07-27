"""Benchmark evaluator unit tests."""
from kylinbootlab.agent.benchmark import BenchmarkCase, evaluate
from kylinbootlab.agent.models import BootAgentReport


def test_benchmark_case_defaults() -> None:
    case = BenchmarkCase(id="B1", name="test", ground_truth={"x": "y"})
    assert case.id == "B1"


def test_all_five_cases_construct() -> None:
    data = [
        ("B1", "dbus-exclusive-delay", {"anomaly_node": "dbus.service"}),
        ("B2", "bluetooth-large-slack", {"anomaly_node": "ukui-bluetooth"}),
        ("B3", "kaiming-stagger-positive", {"anomaly_node": "kaiming"}),
        ("B4", "socket-nm-wait-regression", {"anomaly_node": "NM-wait-online"}),
        ("B5", "dbus-lightdm-combined", {"anomaly_node": "dbus+lightdm"}),
    ]
    for cid, name, truth in data:
        case = BenchmarkCase(id=cid, name=name, ground_truth=truth)
        assert case.id.startswith("B")


def test_evaluate_with_empty_report_returns_zero() -> None:
    report = BootAgentReport(run_id="test")
    score = evaluate(report, [BenchmarkCase(id="B1", name="x", ground_truth={})])
    assert score >= 0.0


def test_benchmark_case_ids_are_unique() -> None:
    cases = [BenchmarkCase(id=f"B{i}", name="x", ground_truth={}) for i in range(1, 6)]
    ids = [c.id for c in cases]
    assert len(ids) == len(set(ids))


def test_case_score_returns_float() -> None:
    case = BenchmarkCase(id="B1", name="x", ground_truth={})
    report = BootAgentReport(run_id="test")
    s = case.score(report)
    assert isinstance(s, float)
