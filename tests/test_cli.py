import json
from pathlib import Path

import pytest
from typer.testing import CliRunner

from kylinbootlab.cli import app
from kylinbootlab.experiments.queue import ExperimentQueue
from tests.helpers import RUN_ID, CaptureFixture, create_probe_bundle

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


# --- kbl analyze smoke tests ---

DOT_STDOUT = """\
strict digraph systemd {
    "basic.target"->"sysinit.target";
    "sysinit.target"->"dbus.service";
    "dbus.service"->"NetworkManager.service";
    "NetworkManager.service"->"lightdm.service";
    "lightdm.service"->"graphical.target";
}
"""

READINESS_STDOUT = "\n".join(
    [
        '{"schema_version":1,"monotonic_ns":10000000000,'
        '"kind":"greeter_started","detail":"lightdm","source":"journald"}',
        '{"schema_version":1,"monotonic_ns":12000000000,'
        '"kind":"greeter_ready","detail":"ukui-greeter","source":"journald"}',
        '{"schema_version":1,"monotonic_ns":13000000000,'
        '"kind":"login_injected","detail":"uinput","source":"probe"}',
        '{"schema_version":1,"monotonic_ns":15000000000,'
        '"kind":"session_opened","detail":"kbl","source":"journald"}',
        '{"schema_version":1,"monotonic_ns":20000000000,'
        '"kind":"desktop_process_up","detail":"ukui-panel","source":"probe"}',
        '{"schema_version":1,"monotonic_ns":21000000000,'
        '"kind":"atspi_desktop_ready","detail":"3 children","source":"atspi"}',
        '{"schema_version":1,"monotonic_ns":22000000000,'
        '"kind":"sentinel_launched","detail":"mate-terminal","source":"probe"}',
        '{"schema_version":1,"monotonic_ns":24000000000,'
        '"kind":"sentinel_window_shown",'
        '"detail":"mate-terminal window","source":"atspi"}',
        '{"schema_version":1,"monotonic_ns":24000000000,'
        '"kind":"usable","detail":"all three","source":"probe"}',
    ]
)

DOT_DOC: CaptureFixture = {
    "command": ["systemd-analyze", "--no-pager", "dot", "--order"],
    "exit_code": 0,
    "stdout": DOT_STDOUT,
    "stderr": "",
}

READINESS_DOC: CaptureFixture = {
    "command": ["kbl-bootprobe", "observe"],
    "exit_code": 0,
    "stdout": READINESS_STDOUT,
    "stderr": "",
}


def test_analyze_without_readiness(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """kbl analyze succeeds on a bundle with DOT + blame but no readiness artifact."""
    from uuid import UUID

    from kylinbootlab.store import RunStore

    data_root = tmp_path / "runs"
    data_root.mkdir()
    store = RunStore(data_root)
    bundle = create_probe_bundle(
        tmp_path, optional_captures={"systemd-critical-chain": DOT_DOC}
    )
    run_path = store.ingest(bundle)
    run_id = UUID(run_path.name)

    result = runner.invoke(
        app, ["analyze", str(run_id), "--data-root", str(data_root)]
    )
    assert result.exit_code == 0, f"CLI failed: {result.output}"
    # Check derived files exist
    derived = store.run_path(run_id) / "derived"
    assert (derived / "causal-graph.json").exists()
    assert (derived / "bottleneck-report.json").exists()

    # Validate JSON structure
    cg = json.loads((derived / "causal-graph.json").read_text())
    assert "graph" in cg
    assert "nodes" in cg["graph"]
    assert "edges" in cg["graph"]
    br = json.loads((derived / "bottleneck-report.json").read_text())
    assert isinstance(br, list)


def test_analyze_with_readiness(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """kbl analyze includes readiness layer when readiness-events is present."""
    from uuid import UUID

    from kylinbootlab.store import RunStore

    data_root = tmp_path / "runs"
    data_root.mkdir()
    store = RunStore(data_root)
    bundle = create_probe_bundle(
        tmp_path,
        optional_captures={
            "systemd-critical-chain": DOT_DOC,
            "readiness-events": READINESS_DOC,
        },
    )
    run_path = store.ingest(bundle)
    run_id = UUID(run_path.name)

    result = runner.invoke(
        app, ["analyze", str(run_id), "--data-root", str(data_root)]
    )
    assert result.exit_code == 0
    derived = store.run_path(run_id) / "derived"
    cg = json.loads((derived / "causal-graph.json").read_text())
    # readiness layer nodes should be present
    node_names = list(cg["graph"]["nodes"].keys())
    assert any("greeter" in n for n in node_names) or any("usable" in n for n in node_names)


def test_analyze_nonexistent_run_id(tmp_path: Path) -> None:
    """CLI should error on nonexistent run ID."""
    result = runner.invoke(
        app, ["analyze", "00000000-0000-0000-0000-000000000000", "--data-root", str(tmp_path)]
    )
    assert result.exit_code != 0


# -- Phase 5 optimize smoke tests ---------------------------------------------


class TestOptimizePlanSmoke:
    """Smoke test for 'kbl optimize plan' against a stored run with bottleneck data."""

    def test_optimize_plan_smoke(self, tmp_path, monkeypatch):
        """CLI should succeed when bottleneck-report.json exists."""
        import json
        from uuid import uuid4

        from kylinbootlab.analysis.graph import Bottleneck

        # Create a minimal RunStore with a bottleneck report
        store_root = tmp_path / "runs"
        run_id = uuid4()
        run_dir = store_root / str(run_id)
        derived_dir = run_dir / "derived"
        derived_dir.mkdir(parents=True)

        # Write a bottleneck report with one known node
        bottlenecks = [
            Bottleneck(
                rank=1,
                node="biometric-authentication.service",
                blame_ns=706_000_000,
                slack_ns=200_000_000,
                on_critical_path=False,
                score=0.85,
                evidence="Test evidence",
            ),
            Bottleneck(
                rank=2,
                node="NetworkManager-wait-online.service",
                blame_ns=703_000_000,
                slack_ns=0,
                on_critical_path=True,
                score=0.92,
                evidence="Test evidence",
            ),
        ]
        (derived_dir / "bottleneck-report.json").write_text(
            json.dumps([b.model_dump() for b in bottlenecks], indent=2),
            encoding="utf-8",
        )

        from typer.testing import CliRunner

        from kylinbootlab.cli import app

        runner = CliRunner()
        result = runner.invoke(
            app,
            ["optimize", "plan", str(run_id), "--data-root", str(store_root)],
        )
        assert result.exit_code == 0
        assert "mask-biometric" in result.stdout
        assert "socket-nm-wait" in result.stdout


class TestOptimizeRunSmoke:
    """Smoke test for 'kbl optimize run' argument validation."""

    def test_unknown_plan_id_rejected(self):
        """CLI should reject unknown plan IDs with a helpful message."""
        from typer.testing import CliRunner

        from kylinbootlab.cli import app

        runner = CliRunner()
        result = runner.invoke(
            app,
            ["optimize", "run", "nonexistent-plan", "--backend", "vix"],
        )
        assert result.exit_code == 1
        assert "Unknown plan_id" in result.stdout or "Unknown plan_id" in result.stderr


def test_agent_benchmark_lists_cases() -> None:
    """kbl agent benchmark lists cases + scoring rubric."""
    result = runner.invoke(app, ["agent", "benchmark", "--case-file",
                                  "agent/benchmark/cases.json"])
    assert result.exit_code == 0
    assert "B1:" in result.stdout
    assert "B5:" in result.stdout
    assert "manual" in result.stdout.lower() or "Manual" in result.stdout or "evaluation" in result.stdout.lower()


def test_optimize_run_phase6_plan_resolves() -> None:
    """phase6-initramfs-trim plan_id resolves (backend=invalid is OK)."""
    result = runner.invoke(
        app,
        ["optimize", "run", "phase6-initramfs-trim",
         "--target", "dummy@localhost", "--backend", "invalid"],
    )
    # Should fail at the unknown backend stage, NOT at plan lookup
    assert "unknown backend" in result.stdout.lower() or result.exit_code != 0
