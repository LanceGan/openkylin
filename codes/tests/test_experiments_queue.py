from datetime import UTC, datetime
from pathlib import Path
from typing import Literal
from uuid import UUID

import pytest

from kylinbootlab.experiments.contracts import ExperimentRecord
from kylinbootlab.experiments.queue import ExperimentQueue

_Status = Literal["pending", "running", "done", "failed", "skipped"]


def _make_record(exp_id: str, status: _Status = "pending") -> ExperimentRecord:
    return ExperimentRecord(
        exp_id=exp_id,
        profile="baseline",
        status=status,
        created_at=datetime(2026, 7, 18, 10, 0, tzinfo=UTC),
    )


def test_enqueue_appends_and_list_returns_latest_state(tmp_path: Path) -> None:
    queue = ExperimentQueue(tmp_path / "queue.jsonl")

    queue.enqueue([_make_record("exp-001"), _make_record("exp-002")])

    records = queue.list()
    assert len(records) == 2
    assert {r.exp_id for r in records} == {"exp-001", "exp-002"}
    assert all(r.status == "pending" for r in records)
    # Verify file was written
    assert (tmp_path / "queue.jsonl").is_file()


def test_dequeue_grabs_one_and_marks_running(tmp_path: Path) -> None:
    queue = ExperimentQueue(tmp_path / "queue.jsonl")
    queue.enqueue([_make_record("exp-001"), _make_record("exp-002")])

    dequeued = queue.dequeue("pending")

    assert dequeued is not None
    assert dequeued.exp_id == "exp-001"

    # The queued record should now be "running" in the file
    records = queue.list()
    exp = next(r for r in records if r.exp_id == "exp-001")
    assert exp.status == "running"


def test_dequeue_returns_none_when_no_pending(tmp_path: Path) -> None:
    queue = ExperimentQueue(tmp_path / "queue.jsonl")

    assert queue.dequeue("pending") is None


def test_update_merges_and_appends_new_line(tmp_path: Path) -> None:
    queue = ExperimentQueue(tmp_path / "queue.jsonl")
    queue.enqueue([_make_record("exp-001")])
    run_id = UUID("11111111-1111-4111-8111-111111111111")

    queue.update(
        "exp-001",
        status="done",
        run_id=run_id,
        completed_at=datetime(2026, 7, 18, 10, 3, tzinfo=UTC),
    )

    records = queue.list()
    done = next(r for r in records if r.exp_id == "exp-001")
    assert done.status == "done"
    assert done.run_id == run_id
    # File should have 2 lines: pending→done
    line_count = (tmp_path / "queue.jsonl").read_text(encoding="utf-8").strip().count("\n") + 1
    assert line_count == 2


def test_update_raises_for_unknown_exp_id(tmp_path: Path) -> None:
    queue = ExperimentQueue(tmp_path / "queue.jsonl")

    with pytest.raises(KeyError, match="unknown exp_id"):
        queue.update("nonexistent", status="done")


def test_list_can_filter_by_status(tmp_path: Path) -> None:
    queue = ExperimentQueue(tmp_path / "queue.jsonl")
    queue.enqueue([_make_record("exp-001"), _make_record("exp-002")])
    queue.dequeue("pending")  # exp-001 → running

    pending = queue.list("pending")
    running = queue.list("running")

    assert len(pending) == 1
    assert pending[0].exp_id == "exp-002"
    assert len(running) == 1
    assert running[0].exp_id == "exp-001"


def test_reset_changes_status_for_all_matching(tmp_path: Path) -> None:
    queue = ExperimentQueue(tmp_path / "queue.jsonl")
    queue.enqueue([_make_record("exp-001"), _make_record("exp-002")])
    queue.update("exp-001", status="failed", error="timeout")
    queue.update("exp-002", status="failed", error="crash")

    queue.reset(status="failed", new_status="pending")

    records = queue.list()
    assert all(r.status == "pending" for r in records)


def test_enqueue_rejects_duplicate_exp_id(tmp_path: Path) -> None:
    queue = ExperimentQueue(tmp_path / "queue.jsonl")
    queue.enqueue([_make_record("exp-001")])

    with pytest.raises(ValueError, match="already in queue"):
        queue.enqueue([_make_record("exp-001")])
