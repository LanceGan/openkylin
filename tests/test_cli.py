from pathlib import Path

from typer.testing import CliRunner

from kylinbootlab.cli import app
from kylinbootlab.experiments.queue import ExperimentQueue
from tests.helpers import RUN_ID, create_probe_bundle

runner = CliRunner()


def test_version_command_prints_package_version() -> None:
    result = runner.invoke(app, ["version"])

    assert result.exit_code == 0
    assert result.stdout == "0.1.0\n"


def test_ingest_and_report_commands(tmp_path: Path) -> None:
    bundle = create_probe_bundle(tmp_path / "source")
    data_root = tmp_path / "runs"

    ingest_result = runner.invoke(
        app,
        ["ingest", str(bundle), "--data-root", str(data_root)],
    )
    report_result = runner.invoke(
        app,
        ["report", str(RUN_ID), "--data-root", str(data_root)],
    )

    assert ingest_result.exit_code == 0
    assert str(RUN_ID) in ingest_result.stdout
    assert report_result.exit_code == 0
    assert (data_root / str(RUN_ID) / "reports/baseline.html").is_file()


def test_experiment_queue_command(tmp_path: Path) -> None:
    queue_file = tmp_path / "queue.jsonl"

    result = runner.invoke(
        app,
        ["experiment", "queue", "--profile", "baseline", "--count", "3",
         "--queue-file", str(queue_file)],
    )

    assert result.exit_code == 0
    assert queue_file.is_file()
    assert "queued 3 experiments" in result.stdout


def test_experiment_status_command(tmp_path: Path) -> None:
    queue_file = tmp_path / "queue.jsonl"
    queued = runner.invoke(
        app,
        ["experiment", "queue", "--count", "2", "--queue-file", str(queue_file)],
    )
    assert queued.exit_code == 0

    result = runner.invoke(
        app, ["experiment", "status", "--queue-file", str(queue_file)],
    )

    assert result.exit_code == 0
    assert "2 experiments" in result.stdout
    assert "pending: 2" in result.stdout


def test_experiment_retry_command(tmp_path: Path) -> None:
    queue_file = tmp_path / "queue.jsonl"
    queued = runner.invoke(
        app,
        ["experiment", "queue", "--count", "1", "--queue-file", str(queue_file)],
    )
    assert queued.exit_code == 0
    q = ExperimentQueue(queue_file)
    q.update("baseline-000", status="failed", error="test", attempt=2)

    result = runner.invoke(
        app,
        ["experiment", "retry", "baseline-000", "--queue-file", str(queue_file)],
    )

    assert result.exit_code == 0
    assert "reset to pending" in result.stdout
    (record,) = q.list()
    assert record.status == "pending"
    assert record.error is None
    assert record.attempt == 0


def test_experiment_reset_command(tmp_path: Path) -> None:
    queue_file = tmp_path / "queue.jsonl"
    queued = runner.invoke(
        app,
        ["experiment", "queue", "--count", "2", "--queue-file", str(queue_file)],
    )
    assert queued.exit_code == 0
    q = ExperimentQueue(queue_file)
    q.update("baseline-000", status="failed", error="boom")
    q.update("baseline-001", status="failed", error="boom")

    result = runner.invoke(
        app,
        ["experiment", "reset", "--status", "failed", "--queue-file", str(queue_file)],
    )

    assert result.exit_code == 0
    assert all(record.status == "pending" for record in q.list())
    assert all(record.error is None for record in q.list())
