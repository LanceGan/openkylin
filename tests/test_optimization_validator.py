"""Unit tests for bootstrap CI, ABBA statistics, and three-tier verdict gate."""

from kylinbootlab.optimization.validator import (
    ABBAStatistics,
    bootstrap_ci,
    compute_statistics,
    verdict,
)


class TestBootstrapCI:
    def test_known_diff_positive(self) -> None:
        """With consistently positive diffs, CI should be above zero."""
        diffs = [50_000_000, 55_000_000, 48_000_000, 52_000_000]  # ~50ms each
        lower, upper = bootstrap_ci(diffs, n_resamples=5000, seed=42)
        # All diffs are ~50ms positive -- CI should be positive
        assert lower > 0
        assert upper > lower

    def test_known_diff_negative(self) -> None:
        """With consistently negative diffs, CI should be below zero."""
        diffs = [-50_000_000, -55_000_000, -48_000_000, -52_000_000]
        lower, upper = bootstrap_ci(diffs, n_resamples=5000, seed=42)
        assert upper < 0
        assert lower < upper

    def test_empty_diffs(self) -> None:
        lower, upper = bootstrap_ci([], n_resamples=1000, seed=42)
        assert lower == 0
        assert upper == 0

    def test_single_diff(self) -> None:
        lower, upper = bootstrap_ci([42_000_000], n_resamples=1000, seed=42)
        assert lower == 42_000_000
        assert upper == 42_000_000

    def test_ci_bounds_between_min_and_max(self) -> None:
        import random
        random.seed(123)
        diffs = [random.randint(-100_000_000, 100_000_000) for _ in range(20)]
        lower, upper = bootstrap_ci(diffs, n_resamples=2000, seed=42)
        assert min(diffs) <= lower <= max(diffs)
        assert min(diffs) <= upper <= max(diffs)


class TestComputeStatistics:
    def test_positive_improvement(self) -> None:
        a = [10_000_000_000, 10_100_000_000, 9_900_000_000, 10_000_000_000]
        b = [9_700_000_000, 9_800_000_000, 9_600_000_000, 9_700_000_000]
        # Per-block diffs: pair them in order
        diffs = [
            b[0] - a[0],  # -300ms
            b[1] - a[1],  # -300ms
            b[2] - a[2],  # -300ms
            b[3] - a[3],  # -300ms
        ]
        stats = compute_statistics(a, b, diffs)
        # B is faster: a_median > b_median
        assert stats.a_median_ns > stats.b_median_ns
        assert stats.median_improvement_ns > 0
        assert stats.median_improvement_pct > 0

    def test_no_improvement(self) -> None:
        a = [10_000_000_000, 10_000_000_000]
        b = [10_000_000_000, 10_000_000_000]
        diffs = [b[0] - a[0], b[1] - a[1]]
        stats = compute_statistics(a, b, diffs)
        assert stats.median_improvement_ns == 0
        assert stats.median_improvement_pct == 0.0

    def test_ci_included(self) -> None:
        a = [10_000_000_000, 10_000_000_000, 10_000_000_000, 10_000_000_000]
        b = [9_900_000_000, 9_900_000_000, 9_900_000_000, 9_900_000_000]
        diffs = [b[i] - a[i] for i in range(4)]
        stats = compute_statistics(a, b, diffs)
        assert isinstance(stats.ci_lower_95_ns, int)
        assert isinstance(stats.ci_upper_95_ns, int)
        assert stats.ci_lower_95_ns <= stats.ci_upper_95_ns


class TestVerdict:
    def _make_stats(
        self,
        a_median: int = 10_000_000_000,
        b_median: int = 9_700_000_000,  # 3% improvement
        improvement_ns: int = 300_000_000,
        improvement_pct: float = 3.0,
        ci_lower: int = 100_000_000,
        ci_upper: int = 500_000_000,
        p95_a: int = 10_500_000_000,
        p95_b: int = 10_400_000_000,  # no regression
    ) -> ABBAStatistics:
        return ABBAStatistics(
            a_median_ns=a_median,
            b_median_ns=b_median,
            median_improvement_ns=improvement_ns,
            median_improvement_pct=improvement_pct,
            ci_lower_95_ns=ci_lower,
            ci_upper_95_ns=ci_upper,
            p95_a_ns=p95_a,
            p95_b_ns=p95_b,
            paired_diffs_ns=[improvement_ns // 4] * 4,
        )

    def test_accepted_meets_all_gates(self) -> None:
        stats = self._make_stats(improvement_pct=3.0, ci_lower=100_000_000)
        v, failed = verdict(stats, functional_passed=True)
        assert v == "ACCEPTED"
        assert failed == []

    def test_accepted_boundary_2percent(self) -> None:
        """At exactly 2.0% improvement with positive CI, should be ACCEPTED."""
        stats = self._make_stats(improvement_pct=2.0, ci_lower=1)
        v, failed = verdict(stats, functional_passed=True)
        assert v == "ACCEPTED"
        assert failed == []

    def test_promising_below_2percent(self) -> None:
        """At 0.5% improvement with positive CI and functional pass -> PROMISING."""
        stats = self._make_stats(improvement_pct=0.5, ci_lower=1)
        v, failed = verdict(stats, functional_passed=True)
        assert v == "PROMISING"
        assert len(failed) > 0
        assert any("2.0%" in g for g in failed)

    def test_rejected_negative_improvement(self) -> None:
        stats = self._make_stats(
            improvement_pct=-1.0, improvement_ns=-100_000_000,
            ci_lower=-200_000_000, ci_upper=0,
        )
        v, failed = verdict(stats, functional_passed=True)
        assert v == "REJECTED"
        assert len(failed) > 0

    def test_rejected_functional_failure(self) -> None:
        stats = self._make_stats(improvement_pct=5.0, ci_lower=100_000_000)
        v, failed = verdict(stats, functional_passed=False)
        assert v == "REJECTED"
        assert "functional" in failed[0].lower()

    def test_rejected_ci_not_detectable(self) -> None:
        """Even with 3% median improvement, if CI includes zero -> REJECTED."""
        stats = self._make_stats(improvement_pct=3.0, ci_lower=-100)
        v, failed = verdict(stats, functional_passed=True)
        # ci_lower <= 0 fails both the hard gate AND the PROMISING precondition
        assert v == "REJECTED"

    def test_zero_improvement_rejected(self) -> None:
        stats = self._make_stats(
            improvement_pct=0.0, improvement_ns=0,
            ci_lower=0, ci_upper=0,
        )
        v, failed = verdict(stats, functional_passed=True)
        assert v == "REJECTED"

    def test_p95_regression_triggers_failed_gate(self) -> None:
        """P95 B is 2.5% worse than P95 A -> gate fails."""
        stats = self._make_stats(
            improvement_pct=3.0, ci_lower=100_000_000,
            p95_a=10_000_000_000, p95_b=10_250_000_000,  # 2.5% regression
        )
        v, failed = verdict(stats, functional_passed=True)
        # median and CI pass, but P95 gate fails -> PROMISING
        assert v == "PROMISING"
        assert any("P95" in g for g in failed)
