"""Candidate scoring and ranking engine for Phase 5A.

``score_plan`` implements the weighted formula from the Phase 5 spec section 5.
``rank_candidates`` sorts by descending score, preserving stable ordering for ties.
"""

from __future__ import annotations

from kylinbootlab.optimization.plan import OptimizationPlan


def score_plan(plan: OptimizationPlan) -> float:
    """Compute a multi-factor optimization score for a single candidate.

    Formula (spec section 5)::

        score = predicted_ns * confidence * portability
              / max(stability_risk, 0.01)
              / max(verification_cost, 1)

    Returns a float where higher = more promising candidate.  The denominator
    uses ``max(x, epsilon)`` to avoid division by zero for edge-case plans
    with zero risk or cost, though in practice all factory plans have
    ``stability_risk >= 0.1`` and ``verification_cost == 18``.
    """
    numerator = (
        plan.expected_gain.predicted_ns
        * plan.expected_gain.confidence
        * plan.portability
    )
    denominator = max(plan.stability_risk, 0.01) * max(plan.verification_cost, 1)
    return numerator / denominator


def rank_candidates(
    plans: list[OptimizationPlan],
) -> list[tuple[OptimizationPlan, float]]:
    """Sort candidates by descending score.

    Returns a list of ``(plan, score)`` tuples.  Ties are broken by
    ``plan_id`` alphabetical order for deterministic output.
    """
    scored = [(plan, score_plan(plan)) for plan in plans]
    scored.sort(key=lambda item: (-item[1], item[0].plan_id))
    return scored
