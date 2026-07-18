"""Experiment loop: dequeue -> power-cycle -> wait -> collect -> repeat.

:class:`ExperimentOrchestrator` drives a persisted :class:`ExperimentQueue`
against one target until no pending experiment remains.  Every failure is an
:class:`ExperimentError`; retryable failures re-queue the experiment after a
:class:`RecoveryManager` restore, exhausted or unrecoverable ones are marked
``failed`` / ``skipped`` so the loop always makes forward progress.
"""

import contextlib
from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

from kylinbootlab.experiments.aliveness import wait_for_ssh
from kylinbootlab.experiments.contracts import ExperimentRecord
from kylinbootlab.experiments.power import TargetPower
from kylinbootlab.experiments.queue import ExperimentQueue
from kylinbootlab.experiments.recovery import RecoveryFailedError, RecoveryManager
from kylinbootlab.remote import (
    RemoteCollectionError,
    SubprocessRunner,
    collect_target_run,
)
from kylinbootlab.store import RunStore

_SSH_DEADLINE_SECONDS: float = 120.0


# -- error hierarchy -----------------------------------------------------


class ExperimentError(Exception):
    """Base for all experiment-related errors."""


class PowerControlError(ExperimentError):
    """A power operation (on/off/reset/snapshot) failed."""


class TargetUnreachableError(ExperimentError):
    """Target did not become SSH-reachable within the deadline."""


# -- orchestrator ---------------------------------------------------------


class ExperimentOrchestrator:
    """Run an experiment queue against one target, looping until drained.

    Interrupted experiments (status=running from a crashed controller) are
    automatically re-queued as pending at run_queue() entry; the attempt
    counter is preserved so retry limits still apply.  This is safe because
    Phase 2 assumes a single controller per queue file, so any ``running``
    record seen at loop entry can only be a leftover, never a live claim.
    """

    def __init__(
        self,
        queue: ExperimentQueue,
        store: RunStore,
        power: TargetPower,
        target: str,
        incoming_root: Path,
    ) -> None:
        self.queue = queue
        self.store = store
        self.power = power
        self.target = target
        self.incoming_root = incoming_root

    def run_queue(self) -> None:
        """Drain the queue: run every pending experiment until none remain.

        ``dequeue`` claims the record (marks it ``running`` and stamps
        ``started_at``); on retryable failure the record is re-queued as
        ``pending`` so a later iteration picks it up again.
        """
        # Re-queue experiments a crashed controller left behind (see class docstring).
        self.queue.reset(status="running", new_status="pending")
        while (claimed := self.queue.dequeue("pending")) is not None:
            try:
                self._run_one_experiment(claimed.exp_id)
            except ExperimentError as exc:
                self._handle_failure(claimed.exp_id, exc)
            finally:
                # Best-effort shutdown between experiments; never abort the loop.
                with contextlib.suppress(Exception):
                    self.power.power_off()

    # -- internal ----------------------------------------------------------

    def _current(self, exp_id: str) -> ExperimentRecord | None:
        """Latest queue state for ``exp_id``, or ``None`` if unknown."""
        for record in self.queue.list():
            if record.exp_id == exp_id:
                return record
        return None

    def _run_one_experiment(self, exp_id: str) -> None:
        # 1. Boot the target from a clean state.
        try:
            if self.power.guest_alive():
                self.power.reset()
            else:
                self.power.snapshot_restore("baseline")
                self.power.power_on()
        except Exception as exc:
            raise PowerControlError(f"power sequencing failed for {exp_id}: {exc}") from exc

        # 2. Wait for the target to become SSH-reachable.
        if not wait_for_ssh(self.target, timeout=_SSH_DEADLINE_SECONDS):
            raise TargetUnreachableError(
                f"target {self.target} not SSH-reachable within "
                f"{_SSH_DEADLINE_SECONDS:.0f}s for {exp_id}"
            )

        # 3. Collect a boot snapshot through the Phase 1 pipeline.
        run_id = uuid4()
        try:
            collect_target_run(
                target=self.target,
                run_id=run_id,
                incoming_root=self.incoming_root,
                store=self.store,
                runner=SubprocessRunner(),
            )
        except RemoteCollectionError as exc:
            raise ExperimentError(f"collection failed for {exp_id}: {exc}") from exc

        # 4. Success.
        self.queue.update(
            exp_id,
            status="done",
            run_id=run_id,
            error=None,  # clear the last failure reason from earlier attempts
            completed_at=datetime.now(UTC),
        )

    def _handle_failure(self, exp_id: str, exc: ExperimentError) -> None:
        """Retry with recovery while attempts remain; otherwise mark failed."""
        record = self._current(exp_id)
        if record is None:  # queue rewritten externally mid-run; nothing to update
            return
        if record.attempt >= record.max_attempts:
            self.queue.update(
                exp_id,
                status="failed",
                error=str(exc),
                completed_at=datetime.now(UTC),
            )
            return

        self.queue.update(exp_id, attempt=record.attempt + 1)
        try:
            RecoveryManager.restore(self.power, self.target)
        except RecoveryFailedError as recovery_exc:
            self.queue.update(
                exp_id,
                status="skipped",
                error=(
                    f"recovery failed after attempt {record.attempt + 1}: {recovery_exc}"
                ),
                completed_at=datetime.now(UTC),
            )
            return
        # Recovered: make the experiment claimable again, keeping the last error.
        self.queue.update(exp_id, status="pending", error=str(exc))
