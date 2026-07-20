"""Unit tests for OptimizationPlan, GainEstimate, and BottleneckEvidence models."""

import pytest
from pydantic import ValidationError

from kylinbootlab.optimization.plan import (
    BottleneckEvidence,
    GainEstimate,
    OptimizationPlan,
    build_exec_delay_lightdm,
    build_mask_biometric,
    build_mask_strongswan,
    build_parallelize_kylin,
    build_socket_nm_wait,
)


class TestGainEstimate:
    def test_valid_estimate(self) -> None:
        ge = GainEstimate(predicted_ns=500_000_000, upper_bound_ns=706_000_000, confidence=0.6)
        assert ge.predicted_ns == 500_000_000
        assert ge.upper_bound_ns == 706_000_000
        assert ge.confidence == 0.6

    def test_default_confidence(self) -> None:
        ge = GainEstimate(predicted_ns=100_000, upper_bound_ns=200_000)
        assert ge.confidence == 1.0

    def test_rejects_negative_predicted(self) -> None:
        with pytest.raises(ValidationError):
            GainEstimate(predicted_ns=-1, upper_bound_ns=100_000)


class TestBottleneckEvidence:
    def test_valid_evidence(self) -> None:
        be = BottleneckEvidence(
            node="foo.service",
            blame_ns=500_000_000,
            slack_ns=100_000_000,
            on_critical_path=True,
            action_kind="service_mask",
        )
        assert be.node == "foo.service"
        assert be.blame_ns == 500_000_000

    def test_rejects_unknown_action_kind(self) -> None:
        with pytest.raises(ValidationError):
            BottleneckEvidence(
                node="foo.service",
                blame_ns=0,
                slack_ns=0,
                on_critical_path=False,
                action_kind="invalid_kind",  # type: ignore[arg-type]
            )


class TestOptimizationPlan:
    def test_valid_plan(self) -> None:
        plan = build_mask_biometric()
        assert plan.plan_id == "mask-biometric"
        assert plan.category == "service_mask"
        assert plan.schema_version == 1
        assert plan.verification_cost == 18

    def test_rejects_unknown_category(self) -> None:
        data = build_mask_biometric().model_dump()
        data["category"] = "unknown_category"
        with pytest.raises(ValidationError):
            OptimizationPlan(**data)

    def test_all_five_candidates_valid(self) -> None:
        for factory in [
            build_mask_biometric,
            build_mask_strongswan,
            build_socket_nm_wait,
            build_parallelize_kylin,
            build_exec_delay_lightdm,
        ]:
            plan = factory()
            # Each plan must have either drop_in or mask_unit, but not both missing
            assert plan.drop_in_content is not None or plan.mask_unit is not None, (
                f"{plan.plan_id}: must have drop_in_content or mask_unit"
            )
            assert plan.stability_risk > 0
            assert plan.verification_cost == 18
            assert len(plan.falsification) > 0

    def test_mask_plan_has_no_drop_in(self) -> None:
        plan = build_mask_biometric()
        assert plan.mask_unit is not None
        assert plan.drop_in_content is None
        assert plan.drop_in_path is None

    def test_drop_in_plan_has_no_mask_unit(self) -> None:
        plan = build_socket_nm_wait()
        assert plan.mask_unit is None
        assert plan.drop_in_content is not None
        assert plan.drop_in_path is not None
