from collections.abc import Mapping
from datetime import UTC, datetime
from pathlib import Path

from kylinbootlab.experiments.contracts import ExperimentRecord


class ExperimentQueue:
    """Append-only JSONL experiment queue.

    Each line is a full snapshot of one experiment's state.  The current state
    for any ``exp_id`` is the *last* line bearing that id — earlier lines are
    historical.  Every mutation appends, never rewrites, so an interrupted
    write can at worst lose the in-progress line (the experiment's state falls
    back to its previous line).
    """

    def __init__(self, path: Path) -> None:
        self.path = path

    # -- persistence helpers -------------------------------------------------

    def _read_all(self) -> dict[str, ExperimentRecord]:
        """Return the latest record per exp_id, keyed in first-seen (enqueue) order."""
        by_id: dict[str, ExperimentRecord] = {}
        if self.path.is_file():
            for line in self.path.read_text(encoding="utf-8").splitlines():
                if not line.strip():
                    continue
                record = ExperimentRecord.model_validate_json(line)
                by_id[record.exp_id] = record
        return by_id

    def _write_line(self, record: ExperimentRecord) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.path.open("a", encoding="utf-8", newline="\n") as fh:
            fh.write(record.model_dump_json() + "\n")

    @staticmethod
    def _updated(record: ExperimentRecord, fields: Mapping[str, object]) -> ExperimentRecord:
        """Merge ``fields`` into ``record``, re-validating so no invalid line is persisted."""
        return ExperimentRecord.model_validate({**record.model_dump(), **fields})

    # -- queue operations ----------------------------------------------------

    def enqueue(self, records: list[ExperimentRecord]) -> None:
        """Append new experiments; the whole batch is rejected on any duplicate exp_id."""
        seen = self._read_all()
        for record in records:
            if record.exp_id in seen:
                raise ValueError(f"exp_id already in queue: {record.exp_id}")
            seen[record.exp_id] = record
        for record in records:
            self._write_line(record)

    def dequeue(self, status: str = "pending") -> ExperimentRecord | None:
        """Claim the oldest record with ``status``: mark it running and return it.

        Returns ``None`` when no record currently has ``status``.
        """
        for record in self._read_all().values():
            if record.status == status:
                claimed = self._updated(
                    record, {"status": "running", "started_at": datetime.now(UTC)}
                )
                self._write_line(claimed)
                return claimed
        return None

    def update(self, exp_id: str, **fields: object) -> None:
        """Merge ``fields`` into the latest record for ``exp_id`` and append the result."""
        by_id = self._read_all()
        if exp_id not in by_id:
            raise KeyError(f"unknown exp_id: {exp_id}")
        self._write_line(self._updated(by_id[exp_id], fields))

    def list(self, status: str | None = None) -> list[ExperimentRecord]:
        """Latest state of every experiment, optionally filtered by ``status``."""
        records = [*self._read_all().values()]
        if status is None:
            return records
        return [record for record in records if record.status == status]

    def reset(self, *, status: str, new_status: str = "pending") -> None:
        """Move every record with ``status`` to ``new_status``, clearing its error."""
        for record in self._read_all().values():
            if record.status == status:
                self._write_line(self._updated(record, {"status": new_status, "error": None}))
