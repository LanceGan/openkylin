"""Bootstrap CI calculator, ABBA statistics, and three-tier verdict gate.

``bootstrap_ci`` uses numpy's percentile method with 10K resamples by default.
``verdict`` implements the gate matrix from spec section 8:
ACCEPTED / PROMISING / REJECTED.
"""

from __future__ import annotations

from typing import Literal

import numpy as np

from kylinbootlab.contracts import ContractModel


def bootstrap_ci(
    paired_diffs: list[int],
    n_resamples: int = 10000,
    ci: float = 95,
    seed: int | None = 42,
) -> tuple[int, int]:
    """Compute bootstrap percentile confidence interval for the median of paired differences.

    Args:
        paired_diffs: Per-block B-A difference values (positive = B is slower / A is faster).
        n_resamples: Number of bootstrap resamples.
        ci: Confidence level as percentage (e.g. 95 for 95% CI).
        seed: Random seed for reproducibility.

    Returns:
        (lower, upper) bounds in nanoseconds.
    """
    if not paired_diffs:
        return (0, 0)
    if len(paired_diffs) == 1:
        # With a single diff, CI is degenerate: just the value itself.
        return (paired_diffs[0], paired_diffs[0])

    rng = np.random.RandomState(seed)
    n = len(paired_diffs)
    medians: list[float] = []
    for _ in range(n_resamples):
        sample = rng.choice(paired_diffs, size=n, replace=True)
        medians.append(float(np.median(sample)))

    tail = (100 - ci) / 2
    lower = float(np.percentile(medians, tail))
    upper = float(np.percentile(medians, 100 - tail))
    return (int(lower), int(upper))


class ABBAStatistics(ContractModel):
    """Complete ABBA experiment statistics for one candidate."""

    a_median_ns: int
    b_median_ns: int
    median_improvement_ns: int
    median_improvement_pct: float
    ci_lower_95_ns: int
    ci_upper_95_ns: int
    p95_a_ns: int
    p95_b_ns: int
    paired_diffs_ns: list[int]


def compute_statistics(
    a_samples: list[int],
    b_samples: list[int],
    paired_diffs: list[int],
) -> ABBAStatistics:
    """Compute full ABBA statistics from raw samples and paired differences.

    Args:
        a_samples: Raw boot times (ns) for baseline profile A.
        b_samples: Raw boot times (ns) for optimized profile B.
        paired_diffs: Per-block B-A difference values (ns).

    Returns:
        Complete ``ABBAStatistics`` with medians, percentiles, and CI.
    """
    a_median = int(np.median(a_samples)) if a_samples else 0
    b_median = int(np.median(b_samples)) if b_samples else 0
    improvement_ns = a_median - b_median  # positive = B is faster
    improvement_pct = (improvement_ns / a_median * 100) if a_median > 0 else 0.0

    ci_lower, ci_upper = bootstrap_ci(paired_diffs)

    p95_a = int(np.percentile(a_samples, 95)) if a_samples else 0
    p95_b = int(np.percentile(b_samples, 95)) if b_samples else 0

    return ABBAStatistics(
        a_median_ns=a_median,
        b_median_ns=b_median,
        median_improvement_ns=improvement_ns,
        median_improvement_pct=round(improvement_pct, 3),
        ci_lower_95_ns=ci_lower,
        ci_upper_95_ns=ci_upper,
        p95_a_ns=p95_a,
        p95_b_ns=p95_b,
        paired_diffs_ns=paired_diffs,
    )


def verdict(
    stats: ABBAStatistics,
    functional_passed: bool,
) -> tuple[Literal["ACCEPTED", "PROMISING", "REJECTED"], list[str]]:
    """Apply the three-tier gate matrix (spec section 8).

    Hard gates for ACCEPTED:
      - median_improvement_pct >= 2.0
      - ci_lower_95_ns > 0  (improvement is statistically detectable)
      - p95 regression <= 1%  (p95_b - p95_a <= 1% of p95_a, i.e. worst-case not worse)
      - functional_passed == True

    PROMISING: median_improvement_pct > 0 AND ci_lower_95_ns > 0
               AND functional_passed (but at least one hard gate failed).

    REJECTED: everything else (no improvement, negative CI, or functional failure).

    Returns:
        (verdict_string, list_of_failed_gate_descriptions).
    """
    failed_gates: list[str] = []

    if not functional_passed:
        return ("REJECTED", ["functional regression test failed"])

    # Check hard gates
    if stats.median_improvement_pct < 2.0:
        failed_gates.append(
            f"median improvement {stats.median_improvement_pct:.3f}% < 2.0%"
        )
    if stats.ci_lower_95_ns <= 0:
        failed_gates.append(
            f"CI lower bound {stats.ci_lower_95_ns}ns <= 0 (not statistically detectable)"
        )

    # P95 regression check
    p95_regression_pct = 0.0
    if stats.p95_a_ns > 0:
        p95_regression_pct = (
            (stats.p95_b_ns - stats.p95_a_ns) / stats.p95_a_ns * 100
        )
    if p95_regression_pct > 1.0:
        failed_gates.append(
            f"P95 regression {p95_regression_pct:.3f}% > 1%"
        )

    if not failed_gates:
        return ("ACCEPTED", [])

    # For PROMISING: need positive improvement AND CI lower > 0 AND functional passed
    if (
        stats.median_improvement_pct > 0
        and stats.ci_lower_95_ns > 0
    ):
        return ("PROMISING", failed_gates)

    return ("REJECTED", failed_gates)
