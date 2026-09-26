import json
import subprocess
from datetime import UTC, datetime
from pathlib import Path
from uuid import UUID, uuid4

import pytest
from typer.testing import CliRunner

from kylinbootlab.calibrate import (
    CalibrationError,
    GroupStats,
    MarkerPreservingPower,
    delta_percent,
    evaluate,
    group_stats,
    marker_command,
    median_ns,
    run_calibration,
    set_observer_marker,
)
from kylinbootlab.cli import app
from kylinbootlab.experiments.contracts import ExperimentRecord
from kylinbootlab.experiments.queue import ExperimentQueue
from kylinbootlab.store import RunStore
from tests.helpers import create_probe_bundle

runner = CliRunner()


# -- test doubles ------------------------------------------------------------


class RecordingPower:
    """TargetPower double recording every call."""

    def __init__(self) -> None:
        self.calls: list[str] = []

    def power_on(self) -> None:
        self.calls.append("power_on")

    def power_off(self) -> None:
        self.calls.append("power_off")

    def reset(self) -> None:
        self.calls.append("reset")

    def snapshot_create(self, name: str) -> None:
        self.calls.append(f"snapshot_create:{name}")

    def snapshot_restore(self, name: str) -> None:
        self.calls.append(f"snapshot_restore:{name}")

    def guest_alive(self) -> bool:
        self.calls.append("guest_alive")
        return True


class RaisingPower:
    """Fails the test if calibration touches power in summarize-only mode."""

    def power_on(self) -> None:
        raise AssertionError("power_on must not be called")

    def power_off(self) -> None:
        raise AssertionError("power_off must not be called")

    def reset(self) -> None:
        raise AssertionError("reset must not be called")

    def snapshot_create(self, name: str) -> None:
        raise AssertionError("snapshot_create must not be called")

    def snapshot_restore(self, name: str) -> None:
        raise AssertionError("snapshot_restore must not be called")

    def guest_alive(self) -> bool:
        raise AssertionError("guest_alive must not be called")


def _done_record(exp_id: str, profile: str, run_id: UUID) -> ExperimentRecord:
    return ExperimentRecord(
        exp_id=exp_id,
        profile=profile,
        status="done",
        run_id=run_id,
        created_at=datetime(2026, 7, 18, 12, 0, tzinfo=UTC),
    )


def _seed_runs(tmp_path: Path, count: int) -> tuple[RunStore, list[UUID]]:
    store = RunStore(tmp_path / "runs")
    run_ids: list[UUID] = []
    for index in range(count):
        run_id = uuid4()
        store.ingest(create_probe_bundle(tmp_path / f"src-{index}", run_id=run_id))
        run_ids.append(run_id)
    return store, run_ids


def _stats(profile: str, os_total: int, graphical: int | None) -> GroupStats:
    return GroupStats(
        profile=profile,
        runs=10,
        os_total_median_ns=os_total,
        graphical_median_ns=graphical,
    )


# -- marker toggling ----------------------------------------------------------


def test_marker_command_bare_removes_marker() -> None:
    command = marker_command("kbl@target.local", "calib-bare")
    assert command[0] == "ssh"
    assert "kbl@target.local" in command
    assert command[-1] == "rm -f /var/lib/kylinbootlab/observe/enabled"


def test_marker_command_benchmark_touches_marker() -> None:
    command = marker_command("kbl@target.local", "calib-benchmark")
    assert command[-1] == "touch /var/lib/kylinbootlab/observe/enabled"


def test_marker_command_rejects_unknown_profile() -> None:
    with pytest.raises(CalibrationError, match="unknown calibration profile"):
        marker_command("kbl@target.local", "calib-diagnostic")


def test_set_observer_marker_raises_on_ssh_failure() -> None:
    def failing_run(args: list[str]) -> subprocess.CompletedProcess[str]:
        return subprocess.CompletedProcess(args, 255, stdout="", stderr="lost connection")

    with pytest.raises(CalibrationError, match="lost connection"):
        set_observer_marker("kbl@target.local", "calib-bare", run=failing_run)


def test_set_observer_marker_runs_command() -> None:
    calls: list[list[str]] = []

    def fake_run(args: list[str]) -> subprocess.CompletedProcess[str]:
        calls.append(args)
        return subprocess.CompletedProcess(args, 0, stdout="", stderr="")

    set_observer_marker("kbl@target.local", "calib-benchmark", run=fake_run)
    assert len(calls) == 1
    assert "touch" in calls[0][-1]


# -- statistics ----------------------------------------------------------------


def test_median_ns_handles_odd_and_even_counts() -> None:
    assert median_ns([3, 1, 2]) == 2
    assert median_ns([1, 2, 3, 10]) == 2  # int(2.5)


def test_median_ns_rejects_empty() -> None:
    with pytest.raises(CalibrationError, match="zero runs"):
        median_ns([])


def test_delta_percent_signed() -> None:
    assert delta_percent(10_000_000_000, 10_050_000_000) == pytest.approx(0.5)
    assert delta_percent(10_000_000_000, 9_900_000_000) == pytest.approx(-1.0)


def test_delta_percent_rejects_zero_baseline() -> None:
    with pytest.raises(CalibrationError, match="zero"):
        delta_percent(0, 1)


def test_evaluate_passes_under_one_percent() -> None:
    report = evaluate(
        _stats("calib-bare", 10_000_000_000, 8_000_000_000),
        _stats("calib-benchmark", 10_099_000_000, 8_070_000_000),
    )
    assert report.passed
    assert report.os_total_delta_percent == pytest.approx(0.99)


def test_evaluate_fails_at_exactly_one_percent() -> None:
    report = evaluate(
        _stats("calib-bare", 10_000_000_000, 8_000_000_000),
        _stats("calib-benchmark", 10_100_000_000, 8_000_000_000),
    )
    assert not report.passed


def test_evaluate_negative_overhead_passes() -> None:
    report = evaluate(
        _stats("calib-bare", 10_000_000_000, 8_000_000_000),
        _stats("calib-benchmark", 9_500_000_000, 7_600_000_000),
    )
    assert report.passed


def test_evaluate_fails_without_graphical_medians() -> None:
    report = evaluate(
        _stats("calib-bare", 10_000_000_000, None),
        _stats("calib-benchmark", 10_000_000_000, None),
    )
    assert report.graphical_delta_percent is None
    assert not report.passed


# -- marker-preserving power wrapper -------------------------------------------


def test_marker_preserving_power_noops_off_and_restore() -> None:
    inner = RecordingPower()
    wrapper = MarkerPreservingPower(inner)

    wrapper.power_off()
    wrapper.snapshot_restore("baseline")
    wrapper.reset()
    wrapper.power_on()
    assert wrapper.guest_alive() is True

    assert inner.calls == ["reset", "power_on", "guest_alive"]


# -- group statistics from the store -------------------------------------------


def test_group_stats_reads_metrics_for_done_runs(tmp_path: Path) -> None:
    store, run_ids = _seed_runs(tmp_path, 2)
    queue = ExperimentQueue(tmp_path / "queue.jsonl")
    queue.enqueue(
        [
            _done_record("calib-bare-000", "calib-bare", run_ids[0]),
            _done_record("calib-bare-001", "calib-bare", run_ids[1]),
        ]
    )

    stats = group_stats(store, queue, "calib-bare")

    assert stats.runs == 2
    assert stats.os_total_median_ns == 3_000_000_000  # helpers fixture total
    assert stats.graphical_median_ns == 2_500_000_000  # 1.0s kernel + 1.5s graphical


def test_group_stats_rejects_profile_without_runs(tmp_path: Path) -> None:
    store = RunStore(tmp_path / "runs")
    queue = ExperimentQueue(tmp_path / "queue.jsonl")
    with pytest.raises(CalibrationError, match="no completed runs"):
        group_stats(store, queue, "calib-bare")


# -- run_calibration resume path ------------------------------------------------


def _seed_finished_calibration(tmp_path: Path) -> tuple[RunStore, Path]:
    store, run_ids = _seed_runs(tmp_path, 4)
    queue_file = tmp_path / "calibration.jsonl"
    queue = ExperimentQueue(queue_file)
    queue.enqueue(
        [
            _done_record("calib-bare-000", "calib-bare", run_ids[0]),
            _done_record("calib-bare-001", "calib-bare", run_ids[1]),
            _done_record("calib-benchmark-000", "calib-benchmark", run_ids[2]),
            _done_record("calib-benchmark-001", "calib-benchmark", run_ids[3]),
        ]
    )
    return store, queue_file


def test_run_calibration_summarizes_finished_queue_without_power(tmp_path: Path) -> None:
    """All experiments done: no SSH, no power calls -- pure summarization."""
    store, queue_file = _seed_finished_calibration(tmp_path)

    report = run_calibration(
        queue_file=queue_file,
        store=store,
        power=RaisingPower(),
        target="kbl@stub",
        incoming_root=tmp_path / "incoming",
        per_group=2,
    )

    assert report.passed  # identical fixture medians -> 0% delta
    assert report.bare.runs == 2
    assert report.benchmark.runs == 2
    assert report.os_total_delta_percent == pytest.approx(0.0)


def test_cli_calibrate_summarizes_and_writes_report(tmp_path: Path) -> None:
    store, queue_file = _seed_finished_calibration(tmp_path)
    report_out = tmp_path / "calibration-report.json"

    result = runner.invoke(
        app,
        [
            "calibrate",
            "--target", "kbl@stub",
            "--backend", "vix",
            "--vmx-path", "C:/vm/openkylin.vmx",
            "--queue-file", str(queue_file),
            "--data-root", str(tmp_path / "runs"),
            "--incoming-root", str(tmp_path / "incoming"),
            "--per-group", "2",
            "--report-out", str(report_out),
        ],
    )

    assert result.exit_code == 0, result.stdout
    assert "CALIBRATION PASS" in result.stdout
    payload = json.loads(report_out.read_text(encoding="utf-8"))
    assert payload["passed"] is True
    assert payload["bare"]["runs"] == 2
