"""ABBA experiment runner -- wraps Phase 2 orchestrator for optimization validation.

``ABBARunner.run()`` drives a complete ABBA experiment for one candidate:
warmup boots (discarded), then 4 blocks of A-B-B-A boots with profile switching,
collecting boot times and computing bootstrap statistics and verdict.
"""

from __future__ import annotations

import contextlib
import tempfile
from datetime import UTC, datetime
from pathlib import Path
from typing import Literal

from kylinbootlab.contracts import ContractModel
from kylinbootlab.experiments.contracts import ExperimentRecord
from kylinbootlab.experiments.orchestrator import ExperimentOrchestrator
from kylinbootlab.experiments.power import TargetPower
from kylinbootlab.experiments.queue import ExperimentQueue
from kylinbootlab.optimization.executor import ProfileExecutor
from kylinbootlab.optimization.plan import OptimizationPlan
from kylinbootlab.optimization.scheduler import (
    ABBAScheduler,
    ProfileStateMachine,
)
from kylinbootlab.optimization.validator import (
    ABBAStatistics,
    compute_statistics,
    verdict,
)
from kylinbootlab.store import RunStore
from kylinbootlab.store import artifact_path as resolve_artifact


class ValidationResult(ContractModel):
    """Complete ABBA validation result for one optimization candidate."""

    schema_version: Literal[1] = 1
    plan_id: str
    verdict: Literal["ACCEPTED", "PROMISING", "REJECTED"]
    statistics: ABBAStatistics
    functional_passed: bool
    first_use_regression: bool | None = None
    failed_gates: list[str] = []
    recommendation: str = ""


class ABBARunner:
    """Run an ABBA experiment for one optimization candidate.

    Wraps Phase 2 ``ExperimentOrchestrator`` for cold-boot cycling,
    ``ProfileExecutor`` for systemd configuration changes, and
    ``ABBAScheduler`` for block-sequence management.
    """

    def __init__(self) -> None:
        pass

    def run(
        self,
        plan: OptimizationPlan,
        target: str,
        store: RunStore,
        power: TargetPower,
        incoming_root: Path,
        password: str | None = None,
    ) -> ValidationResult:
        """Execute the full ABBA validation loop for *plan*.

        1. Inject the optimized profile and run 2 warmup boots (discarded).
        2. Generate ABBA sequence (4 blocks = 16 measured boots).
        3. For each measured boot: apply correct profile if needed,
           cold-boot via orchestrator, collect boot time.
        4. Compute paired differences per block.
        5. Bootstrap CI, compute statistics, apply three-tier verdict.
        6. Rollback the plan (restore baseline).

        Returns a ``ValidationResult`` with the final verdict and statistics.
        """
        executor = ProfileExecutor(target=target, password=password)
        scheduler = ABBAScheduler(total_blocks=4, warmup_boots=2)
        state_machine = ProfileStateMachine(initial="A")

        sequence = scheduler.generate_sequence()  # 18 elements
        total_boots = len(sequence)

        # Measured boot indices are [warmup_boots:] (indices 2-17 for default config)
        measured_start = scheduler.warmup_boots  # 2
        measured_count = total_boots - measured_start  # 16

        boot_times_a: list[int] = []  # boot times in ns for profile A
        boot_times_b: list[int] = []  # boot times in ns for profile B

        # Create a temporary experiment queue file
        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".jsonl", delete=False
        ) as tmp:
            queue_path = Path(tmp.name)

        try:
            for boot_index in range(total_boots):
                desired_profile = scheduler.current_profile(sequence, boot_index)

                # Switch profile if needed (no-op if already correct)
                if desired_profile != state_machine.current:
                    if desired_profile == "A":
                        executor.rollback(plan)
                    else:
                        executor.apply_with_retry(plan)
                    state_machine.switch_to(desired_profile)

                # Create experiment queue with one record
                exp_id = f"{plan.plan_id}-{boot_index:03d}"
                eq = ExperimentQueue(queue_path)
                eq.enqueue([
                    ExperimentRecord(
                        exp_id=exp_id,
                        profile=f"{plan.plan_id}-{desired_profile}",
                        status="pending",
                        created_at=datetime.now(UTC),
                    )
                ])

                # Run one cold boot via orchestrator
                orchestrator = ExperimentOrchestrator(
                    queue=eq,
                    store=store,
                    power=power,
                    target=target,
                    incoming_root=incoming_root,
                )
                orchestrator.run_queue()

                # Collect the boot time from the resulting run
                boot_time_ns = self._extract_boot_time(
                    eq, exp_id, store
                )

                # Record boot time (skip warmup boots from statistics)
                if boot_index >= measured_start and boot_time_ns is not None:
                    if desired_profile == "A":
                        boot_times_a.append(boot_time_ns)
                    else:
                        boot_times_b.append(boot_time_ns)

            # Verify we have the expected number of measured boots
            if len(boot_times_a) < measured_count // 2 or len(boot_times_b) < measured_count // 2:
                raise RuntimeError(
                    f"Insufficient measured boots: "
                    f"got {len(boot_times_a)} A / {len(boot_times_b)} B, "
                    f"expected {measured_count // 2} each"
                )

            # Compute paired differences per block
            paired_diffs = self._compute_paired_diffs(
                boot_times_a, boot_times_b, scheduler.total_blocks
            )

            # Functional regression check
            functional_passed = self._check_functional(executor, plan)

            # Statistics
            stats = compute_statistics(boot_times_a, boot_times_b, paired_diffs)

            # Verdict
            v, failed = verdict(stats, functional_passed)

            # Build recommendation
            recommendation = self._build_recommendation(v, failed, stats)

            return ValidationResult(
                plan_id=plan.plan_id,
                verdict=v,
                statistics=stats,
                functional_passed=functional_passed,
                failed_gates=failed,
                recommendation=recommendation,
            )

        finally:
            # Always rollback the plan
            with contextlib.suppress(Exception):
                executor.rollback(plan)
            # Clean up temp queue file
            with contextlib.suppress(Exception):
                queue_path.unlink(missing_ok=True)

    # -- internal helpers -------------------------------------------------------

    @staticmethod
    def _extract_boot_time(
        queue: ExperimentQueue,
        exp_id: str,
        store: RunStore,
    ) -> int | None:
        """Extract the os_total boot time from the experiment's stored run.

        Looks up the experiment record to find run_id, then loads the
        manifest and artifacts to get ``systemd-analyze time`` output.
        """
        records = [r for r in queue.list() if r.exp_id == exp_id]
        if not records:
            return None
        latest = records[-1]
        if latest.run_id is None:
            return None
        run_id = latest.run_id
        manifest = store.load_manifest(run_id)
        run_path = store.run_path(run_id)

        for artifact in manifest.artifacts:
            if artifact.name == "systemd-time":
                apath = resolve_artifact(run_path / "raw", artifact.relative_path)
                stdout = apath.read_text(encoding="utf-8")
                # Parse: "Startup finished in ... = X.XXXs"
                for line in stdout.splitlines():
                    if "Startup finished in" in line and "=" in line:
                        parts = line.split("=")
                        if len(parts) == 2:
                            time_str = parts[1].strip().rstrip("s")
                            try:
                                return int(float(time_str) * 1_000_000_000)
                            except ValueError:
                                return None
        return None

    @staticmethod
    def _compute_paired_diffs(
        a_times: list[int],
        b_times: list[int],
        total_blocks: int,
    ) -> list[int]:
        """Compute B-A difference for each block (pair of A,B medians).

        Each block has 2 A boots and 2 B boots. We pair the median of
        B boots minus median of A boots within each block.
        """
        import statistics as stats_lib

        diffs: list[int] = []
        half_block = 2
        for block in range(total_blocks):
            a_start = block * half_block
            b_start = block * half_block
            a_block = a_times[a_start : a_start + half_block]
            b_block = b_times[b_start : b_start + half_block]
            if a_block and b_block:
                a_med = int(stats_lib.median(a_block))
                b_med = int(stats_lib.median(b_block))
                diffs.append(b_med - a_med)
        return diffs

    @staticmethod
    def _check_functional(
        executor: ProfileExecutor, plan: OptimizationPlan
    ) -> bool:
        """Run functional regression checks from the plan.

        Returns True if all checks pass (exit code 0), False otherwise.
        """
        if not plan.functional_regression:
            return True
        for check_cmd in plan.functional_regression:
            result = executor._ssh(check_cmd)  # noqa: SLF001
            if result.returncode != 0:
                return False
        return True

    @staticmethod
    def _build_recommendation(
        verdict_str: str,
        failed_gates: list[str],
        stats: ABBAStatistics,
    ) -> str:
        """Build a human-readable recommendation based on verdict and stats."""
        if verdict_str == "ACCEPTED":
            return (
                f"Apply {stats.median_improvement_pct:.2f}% boot-time improvement "
                f"(median {stats.median_improvement_ns / 1e6:.1f}ms faster). "
                f"95% CI [{stats.ci_lower_95_ns / 1e6:.1f}, "
                f"{stats.ci_upper_95_ns / 1e6:.1f}]ms."
            )
        elif verdict_str == "PROMISING":
            return (
                f"Statistically detectable improvement "
                f"({stats.median_improvement_pct:.2f}%) but gates failed: "
                f"{'; '.join(failed_gates)}. Consider increasing sample size "
                f"or combining with other candidates."
            )
        else:
            return (
                f"No reliable improvement detected. Gates failed: "
                f"{'; '.join(failed_gates)}. Review candidate or discard."
            )
