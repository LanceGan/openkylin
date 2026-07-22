"""Observer-overhead calibration (spec 7).

v1 automates the two groups the <1 % gate needs -- ``calib-bare`` (enabled
marker removed) and ``calib-benchmark`` (marker present; ``mode =
"benchmark"`` is the installed observe.toml default) -- through the
unmodified Phase 2 orchestrator.  The ``diagnostic`` group requires a root
edit of observe.toml, so it stays a documented manual runbook step; its
numbers are recorded, never gated.

Why calibration boots are warm resets: the Phase 2 loop restores the
``baseline`` snapshot before every boot, which would silently revert the
on-disk enabled marker and turn every group into ``bare``.
:class:`MarkerPreservingPower` maps ``power_off``/``snapshot_restore`` to
no-ops so each boot is a guest reset -- identical mechanics for both
groups, which is what a relative-overhead comparison needs.
"""

import json
import statistics
import subprocess
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path
from typing import Literal

from pydantic import NonNegativeInt

from kylinbootlab.contracts import ContractModel
from kylinbootlab.experiments.aliveness import wait_for_ssh
from kylinbootlab.experiments.contracts import ExperimentRecord
from kylinbootlab.experiments.orchestrator import ExperimentOrchestrator
from kylinbootlab.experiments.power import TargetPower
from kylinbootlab.experiments.queue import ExperimentQueue
from kylinbootlab.report import write_baseline_report
from kylinbootlab.store import RunStore

#: Automated calibration groups, in execution order (bare first).
PROFILES: tuple[str, ...] = ("calib-bare", "calib-benchmark")

_ENABLED_MARKER = "/var/lib/kylinbootlab/observe/enabled"
_SSH_OPTIONS = [
    "-o", "BatchMode=yes",
    "-o", "ConnectTimeout=15",
]

type _Runner = Callable[[list[str]], subprocess.CompletedProcess[str]]


class CalibrationError(RuntimeError):
    """Calibration could not produce a verdict (toggle failed, no runs, ...)."""


class GroupStats(ContractModel):
    """Median boot metrics over one calibration group's completed runs."""

    profile: str
    runs: NonNegativeInt
    os_total_median_ns: NonNegativeInt
    graphical_median_ns: NonNegativeInt | None


class CalibrationReport(ContractModel):
    """The <1 % benchmark-overhead verdict (spec 7)."""

    schema_version: Literal[1] = 1
    bare: GroupStats
    benchmark: GroupStats
    os_total_delta_percent: float
    graphical_delta_percent: float | None
    passed: bool


def marker_command(target: str, profile: str) -> list[str]:
    """SSH command toggling the observer marker for *profile*.

    No sudo needed: the state directory is kbl-group-writable by design
    (spec 4.5 permission model).
    """
    if profile == "calib-bare":
        action = f"rm -f {_ENABLED_MARKER}"
    elif profile == "calib-benchmark":
        action = f"touch {_ENABLED_MARKER}"
    else:
        raise CalibrationError(f"unknown calibration profile: {profile}")
    return ["ssh", *_SSH_OPTIONS, target, action]


def _run_ssh(args: list[str]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(args, check=False, capture_output=True, text=True, timeout=30)


def set_observer_marker(target: str, profile: str, run: _Runner | None = None) -> None:
    """Toggle the on-target enabled marker; raises on SSH failure."""
    execute = run if run is not None else _run_ssh
    result = execute(marker_command(target, profile))
    if result.returncode != 0:
        raise CalibrationError(
            f"failed to toggle observer marker for {profile}: {result.stderr.strip()}"
        )


def median_ns(values: list[int]) -> int:
    if not values:
        raise CalibrationError("cannot take the median of zero runs")
    return int(statistics.median(values))


def delta_percent(bare: int, benchmark: int) -> float:
    if bare == 0:
        raise CalibrationError("bare median is zero; cannot compute overhead")
    return (benchmark - bare) / bare * 100.0


def evaluate(bare: GroupStats, benchmark: GroupStats) -> CalibrationReport:
    """Verdict per spec 7: BOTH medians must differ by < 1 % (signed --
    a faster benchmark group passes; missing graphical data fails because
    the spec metric must be provable)."""
    os_delta = delta_percent(bare.os_total_median_ns, benchmark.os_total_median_ns)
    graphical_delta: float | None = None
    if bare.graphical_median_ns is not None and benchmark.graphical_median_ns is not None:
        graphical_delta = delta_percent(
            bare.graphical_median_ns, benchmark.graphical_median_ns
        )
    passed = os_delta < 1.0 and graphical_delta is not None and graphical_delta < 1.0
    return CalibrationReport(
        bare=bare,
        benchmark=benchmark,
        os_total_delta_percent=os_delta,
        graphical_delta_percent=graphical_delta,
        passed=passed,
    )


def group_stats(store: RunStore, queue: ExperimentQueue, profile: str) -> GroupStats:
    """Medians over every ``done`` run of *profile*, read from each run's
    regenerated metrics.json (``write_baseline_report`` is deterministic
    and idempotent)."""
    os_totals: list[int] = []
    graphicals: list[int] = []
    runs = 0
    for record in queue.list("done"):
        if record.profile != profile or record.run_id is None:
            continue
        paths = write_baseline_report(store, record.run_id)
        payload = json.loads(paths.metrics_json.read_text(encoding="utf-8"))
        boot = payload["boot"]
        os_totals.append(int(boot["os_total_ns"]))
        if boot["graphical_target_from_t0_ns"] is not None:
            graphicals.append(int(boot["graphical_target_from_t0_ns"]))
        runs += 1
    if runs == 0:
        raise CalibrationError(f"no completed runs for profile {profile}")
    # Only report a graphical median when EVERY run reported the metric --
    # a mixed group would skew the comparison.
    graphical_median = median_ns(graphicals) if len(graphicals) == runs else None
    return GroupStats(
        profile=profile,
        runs=runs,
        os_total_median_ns=median_ns(os_totals),
        graphical_median_ns=graphical_median,
    )


class MarkerPreservingPower:
    """TargetPower decorator for calibration boots.

    ``power_off`` and ``snapshot_restore`` become no-ops so the guest stays
    up between experiments and the orchestrator's boot step takes the
    ``reset()`` branch -- a hard reboot that preserves the on-disk enabled
    marker, which a baseline-snapshot restore would silently revert.
    Everything else passes through.
    """

    def __init__(self, inner: TargetPower) -> None:
        self._inner = inner

    def power_on(self) -> None:
        self._inner.power_on()

    def power_off(self) -> None:
        """Keep the guest (and the observer marker) alive between boots."""

    def reset(self) -> None:
        self._inner.reset()

    def snapshot_create(self, name: str) -> None:
        self._inner.snapshot_create(name)

    def snapshot_restore(self, name: str) -> None:
        """Never revert the disk mid-calibration -- the marker must survive."""

    def guest_alive(self) -> bool:
        return self._inner.guest_alive()


def _ensure_guest_up(power: TargetPower, target: str) -> None:
    if not power.guest_alive():
        power.power_on()
    if not wait_for_ssh(target, timeout=180):
        raise CalibrationError(f"target {target} not reachable to toggle the marker")


def run_calibration(
    queue_file: Path,
    store: RunStore,
    power: TargetPower,
    target: str,
    incoming_root: Path,
    per_group: int = 10,
) -> CalibrationReport:
    """Drive both groups through the Phase 2 loop and return the verdict.

    Groups run strictly in sequence and each is enqueued only when its
    predecessor has drained, so the shared queue never holds pending
    records of two profiles at once -- the marker toggled before a group
    can never leak into the other group's boots.  Re-running resumes:
    existing exp_ids are kept, fully finished groups are only summarized
    (no SSH, no power operations).
    """
    queue = ExperimentQueue(queue_file)
    calibration_power = MarkerPreservingPower(power)

    for profile in PROFILES:
        known = {record.exp_id for record in queue.list()}
        fresh = [
            ExperimentRecord(
                exp_id=f"{profile}-{index:03d}",
                profile=profile,
                status="pending",
                created_at=datetime.now(UTC),
            )
            for index in range(per_group)
            if f"{profile}-{index:03d}" not in known
        ]
        if fresh:
            queue.enqueue(fresh)
        has_work = any(
            record.profile == profile and record.status in {"pending", "running"}
            for record in queue.list()
        )
        if not has_work:
            continue  # group already finished -- summarize later
        _ensure_guest_up(power, target)
        set_observer_marker(target, profile)
        ExperimentOrchestrator(
            queue=queue,
            store=store,
            power=calibration_power,
            target=target,
            incoming_root=incoming_root,
        ).run_queue()

    return evaluate(
        group_stats(store, queue, "calib-bare"),
        group_stats(store, queue, "calib-benchmark"),
    )
