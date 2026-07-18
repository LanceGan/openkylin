from __future__ import annotations

import shutil
import subprocess
from collections.abc import Sequence
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from uuid import UUID

import pytest

from kylinbootlab.experiments.aliveness import wait_for_ssh
from kylinbootlab.experiments.contracts import ExperimentRecord
from kylinbootlab.experiments.orchestrator import (
    ExperimentError,
    ExperimentOrchestrator,
    PowerControlError,
    TargetUnreachableError,
)
from kylinbootlab.experiments.power import TargetPower
from kylinbootlab.experiments.queue import ExperimentQueue
from kylinbootlab.experiments.recovery import RecoveryFailedError, RecoveryManager
from kylinbootlab.store import BundleError, RunStore
from tests.helpers import create_probe_bundle

TARGET = "kbl@stub-target"


# -- test doubles ----------------------------------------------------------


class StubPower:
    """TargetPower double: records every call; guest is never alive."""

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
        return False


def _record(exp_id: str, *, max_attempts: int = 3) -> ExperimentRecord:
    return ExperimentRecord(
        exp_id=exp_id,
        profile="baseline",
        max_attempts=max_attempts,
        created_at=datetime(2026, 7, 18, 12, 0, tzinfo=UTC),
    )


def _orchestrator(
    queue: ExperimentQueue, store: RunStore, power: StubPower, tmp_path: Path
) -> ExperimentOrchestrator:
    return ExperimentOrchestrator(
        queue=queue,
        store=store,
        power=power,
        target=TARGET,
        incoming_root=tmp_path / "incoming",
    )


def _patch_collect(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """Replace ``collect_target_run`` with a local bundle + ``store.ingest`` stub."""

    def fake_collect(
        *,
        target: str,
        run_id: UUID,
        incoming_root: Path,
        store: RunStore,
        runner: object,
    ) -> Path:
        bundle = create_probe_bundle(tmp_path / "bundles" / str(run_id), run_id=run_id)
        incoming_root.mkdir(parents=True, exist_ok=True)
        staged = incoming_root / str(run_id)
        shutil.copytree(bundle, staged)
        return store.ingest(staged)

    monkeypatch.setattr(
        "kylinbootlab.experiments.orchestrator.collect_target_run", fake_collect
    )


# -- wait_for_ssh (preserved from Task 5) -----------------------------------


def test_wait_for_ssh_returns_false_when_ssh_never_answers(tmp_path: Path) -> None:
    """wait_for_ssh returns False when every attempt fails."""
    result = wait_for_ssh("192.0.2.1", timeout=0.5, interval=0.1)
    assert result is False


def test_wait_for_ssh_returns_true_on_first_success(monkeypatch: pytest.MonkeyPatch) -> None:
    """wait_for_ssh returns True as soon as one call succeeds."""
    call_count = 0

    def fake_run(
        args: Sequence[str],
        **_kwargs: Any,
    ) -> subprocess.CompletedProcess[str]:
        nonlocal call_count
        call_count += 1
        if call_count >= 2:
            return subprocess.CompletedProcess(args, 0, stdout="", stderr="")
        raise OSError("connection refused")

    monkeypatch.setattr("kylinbootlab.experiments.aliveness.subprocess.run", fake_run)

    result = wait_for_ssh("target.local", timeout=10, interval=0.05)
    assert result is True


def test_wait_for_boot_finished_polls_systemd_analyze(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """wait_for_boot_finished runs `systemd-analyze time` and returns True on rc 0."""
    from kylinbootlab.experiments.aliveness import wait_for_boot_finished

    commands: list[list[str]] = []
    call_count = 0

    def fake_run(
        args: Sequence[str],
        **_kwargs: Any,
    ) -> subprocess.CompletedProcess[str]:
        nonlocal call_count
        call_count += 1
        commands.append(list(args))
        if call_count >= 2:  # first poll: boot not finished yet
            return subprocess.CompletedProcess(args, 0, stdout="", stderr="")
        return subprocess.CompletedProcess(args, 1, stdout="", stderr="not finished")

    monkeypatch.setattr("kylinbootlab.experiments.aliveness.subprocess.run", fake_run)

    result = wait_for_boot_finished("target.local", timeout=10, interval=0.05)

    assert result is True
    assert commands[0][-2:] == ["systemd-analyze", "time"]
    assert call_count == 2


# -- error hierarchy ---------------------------------------------------------


def test_error_hierarchy() -> None:
    """Power and reachability errors are retryable ExperimentError subclasses."""
    assert issubclass(ExperimentError, Exception)
    assert issubclass(PowerControlError, ExperimentError)
    assert issubclass(TargetUnreachableError, ExperimentError)


# -- run_queue integration ----------------------------------------------------


def test_run_queue_completes_three_experiments(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A three-experiment queue drains with every record done and a unique run."""
    store = RunStore(tmp_path / "runs")
    queue = ExperimentQueue(tmp_path / "queue.jsonl")
    queue.enqueue([_record(f"exp-{index:03d}") for index in range(3)])

    monkeypatch.setattr(
        "kylinbootlab.experiments.orchestrator.wait_for_ssh",
        lambda target, timeout=120.0: True,
    )
    monkeypatch.setattr(
        "kylinbootlab.experiments.orchestrator.wait_for_boot_finished",
        lambda target, timeout=120.0: True,
    )
    _patch_collect(monkeypatch, tmp_path)

    power = StubPower()
    _orchestrator(queue, store, power, tmp_path).run_queue()

    records = queue.list()
    assert [record.status for record in records] == ["done", "done", "done"]
    run_ids = {record.run_id for record in records}
    assert len(run_ids) == 3
    for record in records:
        assert record.run_id is not None
        assert record.started_at is not None
        assert record.completed_at is not None
        assert record.error is None
        assert (tmp_path / "runs" / str(record.run_id) / "manifest.json").is_file()
    boot_cycle = ["guest_alive", "snapshot_restore:baseline", "power_on", "power_off"]
    assert power.calls == boot_cycle * 3


def test_run_queue_marks_failed_after_attempts_exhausted(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """SSH never comes up: recovery runs between attempts, then the record fails."""
    store = RunStore(tmp_path / "runs")
    queue = ExperimentQueue(tmp_path / "queue.jsonl")
    queue.enqueue([_record("exp-unreachable", max_attempts=2)])

    monkeypatch.setattr(
        "kylinbootlab.experiments.orchestrator.wait_for_ssh",
        lambda target, timeout=120.0: False,
    )

    restore_calls: list[str] = []

    def fake_restore(
        power: TargetPower, target: str, *, runner: object | None = None
    ) -> None:
        restore_calls.append(target)

    monkeypatch.setattr(RecoveryManager, "restore", fake_restore)

    power = StubPower()
    _orchestrator(queue, store, power, tmp_path).run_queue()

    (record,) = queue.list()
    assert record.status == "failed"
    assert record.attempt == 2
    assert record.error is not None
    assert "not SSH-reachable" in record.error
    assert record.completed_at is not None
    # Recovery ran between attempts: once after each retryable failure.
    assert restore_calls == [TARGET, TARGET]
    # Best-effort power_off ran after every boot attempt (2 retries + final).
    assert power.calls.count("power_off") == 3


def test_run_queue_skips_experiment_when_recovery_fails(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """RecoveryFailedError marks the record skipped and the loop moves on."""
    store = RunStore(tmp_path / "runs")
    queue = ExperimentQueue(tmp_path / "queue.jsonl")
    queue.enqueue([_record("exp-a"), _record("exp-b")])

    monkeypatch.setattr(
        "kylinbootlab.experiments.orchestrator.wait_for_ssh",
        lambda target, timeout=120.0: False,
    )

    restore_calls: list[str] = []

    def failing_restore(
        power: TargetPower, target: str, *, runner: object | None = None
    ) -> None:
        restore_calls.append(target)
        raise RecoveryFailedError("both recovery layers failed")

    monkeypatch.setattr(RecoveryManager, "restore", failing_restore)

    power = StubPower()
    _orchestrator(queue, store, power, tmp_path).run_queue()

    records = queue.list()
    assert [record.status for record in records] == ["skipped", "skipped"]
    for record in records:
        assert record.error is not None
        assert "recovery failed after attempt 1" in record.error
        assert record.completed_at is not None
    assert len(restore_calls) == 2


def test_run_queue_requeues_experiment_left_running_by_crashed_controller(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A record stuck ``running`` after a controller crash is re-run to ``done``."""
    store = RunStore(tmp_path / "runs")
    queue = ExperimentQueue(tmp_path / "queue.jsonl")
    queue.enqueue([_record("exp-interrupted")])
    # Simulate a crash mid-experiment: the record was claimed but never finished.
    queue.update("exp-interrupted", status="running")
    assert queue.list("pending") == []

    monkeypatch.setattr(
        "kylinbootlab.experiments.orchestrator.wait_for_ssh",
        lambda target, timeout=120.0: True,
    )
    monkeypatch.setattr(
        "kylinbootlab.experiments.orchestrator.wait_for_boot_finished",
        lambda target, timeout=120.0: True,
    )
    _patch_collect(monkeypatch, tmp_path)

    power = StubPower()
    _orchestrator(queue, store, power, tmp_path).run_queue()

    (record,) = queue.list()
    assert record.status == "done"
    assert record.run_id is not None
    assert record.completed_at is not None
    assert record.error is None


def test_run_queue_retry_succeeds_and_clears_stale_error(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """SSH fails once then recovers: the retried record ends done with no error."""
    store = RunStore(tmp_path / "runs")
    queue = ExperimentQueue(tmp_path / "queue.jsonl")
    queue.enqueue([_record("exp-flaky")])

    ssh_attempts: list[str] = []

    def flaky_wait_for_ssh(target: str, timeout: float = 120.0) -> bool:
        ssh_attempts.append(target)
        return len(ssh_attempts) > 1  # first attempt fails, retry succeeds

    monkeypatch.setattr(
        "kylinbootlab.experiments.orchestrator.wait_for_ssh", flaky_wait_for_ssh
    )
    monkeypatch.setattr(
        "kylinbootlab.experiments.orchestrator.wait_for_boot_finished",
        lambda target, timeout=120.0: True,
    )

    restore_calls: list[str] = []

    def fake_restore(
        power: TargetPower, target: str, *, runner: object | None = None
    ) -> None:
        restore_calls.append(target)

    monkeypatch.setattr(RecoveryManager, "restore", fake_restore)
    _patch_collect(monkeypatch, tmp_path)

    power = StubPower()
    _orchestrator(queue, store, power, tmp_path).run_queue()

    (record,) = queue.list()
    assert record.status == "done"
    assert record.attempt == 1
    assert record.error is None
    assert record.run_id is not None
    assert record.completed_at is not None
    assert restore_calls == [TARGET]
    assert len(ssh_attempts) == 2


def test_run_queue_survives_bundle_error_and_continues(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A corrupt bundle (BundleError) fails the experiment gracefully; the loop moves on."""
    store = RunStore(tmp_path / "runs")
    queue = ExperimentQueue(tmp_path / "queue.jsonl")
    queue.enqueue([_record("exp-corrupt", max_attempts=1), _record("exp-ok")])

    monkeypatch.setattr(
        "kylinbootlab.experiments.orchestrator.wait_for_ssh",
        lambda target, timeout=120.0: True,
    )
    monkeypatch.setattr(
        "kylinbootlab.experiments.orchestrator.wait_for_boot_finished",
        lambda target, timeout=120.0: True,
    )

    def fake_collect(
        *,
        target: str,
        run_id: UUID,
        incoming_root: Path,
        store: RunStore,
        runner: object,
    ) -> Path:
        running = [record.exp_id for record in queue.list() if record.status == "running"]
        if running == ["exp-corrupt"]:
            raise BundleError("manifest checksum mismatch")
        bundle = create_probe_bundle(tmp_path / "bundles" / str(run_id), run_id=run_id)
        incoming_root.mkdir(parents=True, exist_ok=True)
        staged = incoming_root / str(run_id)
        shutil.copytree(bundle, staged)
        return store.ingest(staged)

    monkeypatch.setattr(
        "kylinbootlab.experiments.orchestrator.collect_target_run", fake_collect
    )

    restore_calls: list[str] = []

    def fake_restore(
        power: TargetPower, target: str, *, runner: object | None = None
    ) -> None:
        restore_calls.append(target)

    monkeypatch.setattr(RecoveryManager, "restore", fake_restore)

    power = StubPower()
    _orchestrator(queue, store, power, tmp_path).run_queue()

    by_id = {record.exp_id: record for record in queue.list()}
    corrupt = by_id["exp-corrupt"]
    assert corrupt.status == "failed"
    assert corrupt.error is not None
    assert "collection failed" in corrupt.error
    assert "manifest checksum mismatch" in corrupt.error
    assert corrupt.completed_at is not None
    ok = by_id["exp-ok"]
    assert ok.status == "done"
    assert ok.run_id is not None
    assert ok.error is None
    # Recovery ran once between the corrupt experiment's two attempts.
    assert restore_calls == [TARGET]
