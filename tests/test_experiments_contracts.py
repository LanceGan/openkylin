from datetime import UTC, datetime
from uuid import UUID

import pytest
from pydantic import ValidationError

from kylinbootlab.experiments.contracts import ExperimentRecord


def test_experiment_record_accepts_valid_pending_entry() -> None:
    record = ExperimentRecord(
        exp_id="coldboot-baseline-001",
        profile="baseline",
        status="pending",
        created_at=datetime(2026, 7, 18, 10, 0, tzinfo=UTC),
    )

    assert record.schema_version == 1
    assert record.exp_id == "coldboot-baseline-001"
    assert record.attempt == 0
    assert record.max_attempts == 3
    assert record.run_id is None


def test_experiment_record_rejects_invalid_status() -> None:
    with pytest.raises(ValidationError, match="status"):
        ExperimentRecord(
            exp_id="test",
            profile="baseline",
            status="bogus",  # type: ignore[arg-type]
            created_at=datetime(2026, 7, 18, 10, 0, tzinfo=UTC),
        )


def test_experiment_record_rejects_empty_exp_id() -> None:
    with pytest.raises(ValidationError, match="exp_id"):
        ExperimentRecord(
            exp_id="",
            profile="baseline",
            status="pending",
            created_at=datetime(2026, 7, 18, 10, 0, tzinfo=UTC),
        )


def test_experiment_record_with_run_id() -> None:
    run_id = UUID("11111111-1111-4111-8111-111111111111")
    record = ExperimentRecord(
        exp_id="coldboot-baseline-002",
        profile="baseline",
        status="done",
        run_id=run_id,
        attempt=1,
        started_at=datetime(2026, 7, 18, 10, 0, 5, tzinfo=UTC),
        completed_at=datetime(2026, 7, 18, 10, 3, 12, tzinfo=UTC),
        created_at=datetime(2026, 7, 18, 10, 0, tzinfo=UTC),
    )

    assert record.run_id == run_id
    assert record.status == "done"
    assert record.attempt == 1
