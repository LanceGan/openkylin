"""Unit tests for the optimization candidate scoring and ranking engine."""

import pytest

from kylinbootlab.optimization.plan import (
    BottleneckEvidence,
    GainEstimate,
    OptimizationPlan,
    build_mask_biometric,
    build_socket_nm_wait,
)
from kylinbootlab.optimization.planner import rank_candidates, score_plan


def _make_plan(
    plan_id: str = "test-plan",
    predicted_ns: int = 1_000_000_000,
    confidence: float = 1.0,
    portability: float = 1.0,
    stability_risk: float = 0.3,
    verification_cost: int = 18,
) -> OptimizationPlan:
    """Build a minimal OptimizationPlan for scoring tests."""
    return OptimizationPlan(
        plan_id=plan_id,
        title="Test Plan",
        category="service_mask",
        description="Scoring test candidate",
        evidence=BottleneckEvidence(
            node="test.service",
            blame_ns=predicted_ns,
            slack_ns=0,
            on_critical_path=True,
            action_kind="service_mask",
        ),
        expected_gain=GainEstimate(
            predicted_ns=predicted_ns,
            upper_bound_ns=predicted_ns,
            confidence=confidence,
        ),
        mask_unit="test.service",
        rollback=["sudo systemctl unmask test.service"],
        functional_regression=[],
        portability=portability,
        stability_risk=stability_risk,
        verification_cost=verification_cost,
        falsification="If test.service not in blame, plan is wrong.",
    )


class TestScorePlan:
    def test_higher_gain_scores_higher(self) -> None:
        low = _make_plan("low", predicted_ns=100_000_000)
        high = _make_plan("high", predicted_ns=1_000_000_000)
        assert score_plan(high) > score_plan(low)

    def test_higher_confidence_scores_higher(self) -> None:
        low = _make_plan("low", predicted_ns=500_000_000, confidence=0.2)
        high = _make_plan("high", predicted_ns=500_000_000, confidence=0.9)
        assert score_plan(high) > score_plan(low)

    def test_higher_risk_scores_lower(self) -> None:
        low = _make_plan("low", stability_risk=0.1)
        high = _make_plan("high", stability_risk=0.7)
        assert score_plan(low) > score_plan(high)

    def test_higher_cost_scores_lower(self) -> None:
        low = _make_plan("low", verification_cost=36)
        high = _make_plan("high", verification_cost=18)
        assert score_plan(high) > score_plan(low)

    def test_lower_portability_scores_lower(self) -> None:
        low = _make_plan("low", portability=0.3)
        high = _make_plan("high", portability=1.0)
        assert score_plan(high) > score_plan(low)

    def test_zero_risk_clamped(self) -> None:
        """max(stability_risk, 0.01) prevents division by zero."""
        plan = _make_plan("zero-risk", stability_risk=0.0)
        result = score_plan(plan)
        assert result > 0
        assert result == pytest.approx(
            (1_000_000_000 * 1.0 * 1.0) / (0.01 * 18)
        )


class TestRankCandidates:
    def test_rank_returns_sorted_descending(self) -> None:
        plans = [
            _make_plan("low", predicted_ns=100_000_000),
            _make_plan("mid", predicted_ns=500_000_000),
            _make_plan("high", predicted_ns=1_000_000_000),
        ]
        ranked = rank_candidates(plans)
        assert ranked[0][0].plan_id == "high"
        assert ranked[1][0].plan_id == "mid"
        assert ranked[2][0].plan_id == "low"
        # Scores should be strictly descending
        assert ranked[0][1] > ranked[1][1] > ranked[2][1]

    def test_rank_empty_list(self) -> None:
        assert rank_candidates([]) == []

    def test_factory_plans_all_score_positive(self) -> None:
        plans = [build_mask_biometric(), build_socket_nm_wait()]
        ranked = rank_candidates(plans)
        for plan, score in ranked:
            assert score > 0, f"{plan.plan_id} scored {score}"
