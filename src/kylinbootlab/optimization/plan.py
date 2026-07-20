"""Optimization plan data models -- candidate definition, gain estimation, evidence.

All models extend ``ContractModel`` for strict serialization.  Factory functions
produce the five known Phase 5 candidates with realistic pre-populated fields.
"""

from __future__ import annotations

from typing import Literal

from pydantic import NonNegativeInt

from kylinbootlab.contracts import ContractModel


class GainEstimate(ContractModel):
    """Expected improvement from a single optimization candidate."""

    predicted_ns: NonNegativeInt
    upper_bound_ns: NonNegativeInt
    confidence: float = 1.0


class BottleneckEvidence(ContractModel):
    """Evidence linking an optimization plan to a Phase 4 bottleneck node."""

    node: str
    blame_ns: NonNegativeInt
    slack_ns: NonNegativeInt
    on_critical_path: bool
    action_kind: Literal["remove_edge", "reduce_blame", "service_mask"]


class OptimizationPlan(ContractModel):
    """One independent optimization candidate -- a single systemd configuration change."""

    schema_version: Literal[1] = 1
    plan_id: str
    title: str
    category: Literal[
        "service_mask", "socket_activation", "parallelize", "exec_delay", "kernel_param"
    ]
    description: str
    evidence: BottleneckEvidence
    expected_gain: GainEstimate
    drop_in_content: str | None = None
    drop_in_path: str | None = None
    mask_unit: str | None = None
    preconditions: list[str] = []
    rollback: list[str] = []
    functional_regression: list[str] = []
    portability: float = 1.0
    stability_risk: float
    verification_cost: int = 18
    falsification: str


# -- Known candidate factories ------------------------------------------------


def build_mask_biometric() -> OptimizationPlan:
    """Mask biometric-authentication.service (706ms blame, slack > 0)."""
    return OptimizationPlan(
        plan_id="mask-biometric",
        title="Mask biometric-authentication.service",
        category="service_mask",
        description=(
            "Disable biometric-authentication.service via systemctl mask. "
            "This service accounts for ~706ms of boot blame but has positive slack, "
            "so removal may not translate to full wall-clock savings on the critical path."
        ),
        evidence=BottleneckEvidence(
            node="biometric-authentication.service",
            blame_ns=706_000_000,
            slack_ns=200_000_000,
            on_critical_path=False,
            action_kind="service_mask",
        ),
        expected_gain=GainEstimate(
            predicted_ns=500_000_000,
            upper_bound_ns=706_000_000,
            confidence=0.6,
        ),
        mask_unit="biometric-authentication.service",
        rollback=["sudo systemctl unmask biometric-authentication.service"],
        functional_regression=[
            (
                "sudo systemctl status biometric-authentication.service 2>&1"
                " | grep -q 'Loaded:.*masked'"
            )
        ],
        portability=1.0,
        stability_risk=0.1,
        verification_cost=18,
        falsification=(
            "If biometric-authentication.service does not appear in Top-5 "
            "blame after optimization, the plan is wrong."
        ),
    )


def build_mask_strongswan() -> OptimizationPlan:
    """Mask strongswan.service (IPsec, typically unused on desktop VMs)."""
    return OptimizationPlan(
        plan_id="mask-strongswan",
        title="Mask strongswan.service",
        category="service_mask",
        description=(
            "Disable strongswan.service (IPsec VPN daemon). "
            "Typically unused on single-NIC desktop VMs -- safe to mask."
        ),
        evidence=BottleneckEvidence(
            node="strongswan.service",
            blame_ns=450_000_000,
            slack_ns=0,
            on_critical_path=True,
            action_kind="service_mask",
        ),
        expected_gain=GainEstimate(
            predicted_ns=450_000_000,
            upper_bound_ns=450_000_000,
            confidence=0.9,
        ),
        mask_unit="strongswan.service",
        rollback=["sudo systemctl unmask strongswan.service"],
        functional_regression=[],
        portability=0.8,
        stability_risk=0.1,
        verification_cost=18,
        falsification=(
            "If strongswan.service is not present on the target, the plan is wrong."
        ),
    )


def build_socket_nm_wait() -> OptimizationPlan:
    """Socket-activate NM-wait-online.service (703ms on critical path)."""
    return OptimizationPlan(
        plan_id="socket-nm-wait",
        title="Replace NM-wait-online.service with socket activation",
        category="socket_activation",
        description=(
            "NetworkManager-wait-online.service blocks graphical.target for ~703ms. "
            "On single-NIC VMs this delay is unnecessary. Replace with socket "
            "activation via drop-in that reduces timeout to zero."
        ),
        evidence=BottleneckEvidence(
            node="NetworkManager-wait-online.service",
            blame_ns=703_000_000,
            slack_ns=0,
            on_critical_path=True,
            action_kind="reduce_blame",
        ),
        expected_gain=GainEstimate(
            predicted_ns=650_000_000,
            upper_bound_ns=703_000_000,
            confidence=0.95,
        ),
        drop_in_content=(
            "# KylinBootLab Phase 5 -- skip wait-online on single-NIC VM\n"
            "[Service]\n"
            "ExecStart=\n"
            "ExecStart=/usr/bin/nm-online -s -q --timeout=0\n"
        ),
        drop_in_path=(
            "/etc/systemd/system/NetworkManager-wait-online.service.d/kbl-opt.conf"
        ),
        rollback=[
            "sudo rm -f /etc/systemd/system/NetworkManager-wait-online.service.d/kbl-opt.conf",
            "sudo systemctl daemon-reload",
        ],
        functional_regression=[
            "systemctl is-active NetworkManager.service",
            "nmcli networking connectivity check",
        ],
        portability=0.8,
        stability_risk=0.3,
        verification_cost=18,
        falsification=(
            "If NetworkManager-wait-online.service still appears in "
            "systemd-analyze blame after optimization, the drop-in did not apply."
        ),
    )


def build_parallelize_kylin() -> OptimizationPlan:
    """Parallelize kylin-specific services via drop-in dependency relaxation."""
    return OptimizationPlan(
        plan_id="parallelize-kylin",
        title="Parallelize kylin-display-manager.service startup",
        category="parallelize",
        description=(
            "Relax After= dependencies for kylin-display-manager.service to allow "
            "parallel startup with non-critical services. Drop-in overrides the "
            "unit's After= line to remove the serialization constraint."
        ),
        evidence=BottleneckEvidence(
            node="kylin-display-manager.service",
            blame_ns=520_000_000,
            slack_ns=0,
            on_critical_path=True,
            action_kind="remove_edge",
        ),
        expected_gain=GainEstimate(
            predicted_ns=400_000_000,
            upper_bound_ns=520_000_000,
            confidence=0.7,
        ),
        drop_in_content=(
            "# KylinBootLab Phase 5 -- relax serialization for faster DM startup\n"
            "[Unit]\n"
            "After=\n"
            "After=multi-user.target\n"
        ),
        drop_in_path=(
            "/etc/systemd/system/kylin-display-manager.service.d/kbl-opt.conf"
        ),
        rollback=[
            "sudo rm -f /etc/systemd/system/kylin-display-manager.service.d/kbl-opt.conf",
            "sudo systemctl daemon-reload",
        ],
        functional_regression=[
            "systemctl is-active kylin-display-manager.service",
            "loginctl list-sessions | grep -q seat0",
        ],
        portability=0.5,
        stability_risk=0.3,
        verification_cost=18,
        falsification=(
            "If kylin-display-manager.service blame does not decrease by >=100ms, "
            "the dependency relaxation had no effect."
        ),
    )


def build_exec_delay_lightdm() -> OptimizationPlan:
    """Reduce ExecStartPre delay in LightDM via drop-in."""
    return OptimizationPlan(
        plan_id="exec-delay-lightdm",
        title="Reduce LightDM ExecStartPre delay",
        category="exec_delay",
        description=(
            "LightDM has an ExecStartPre sleep or polling loop that adds ~350ms. "
            "Override with a reduced-delay ExecStartPre via drop-in."
        ),
        evidence=BottleneckEvidence(
            node="lightdm.service",
            blame_ns=1_200_000_000,
            slack_ns=0,
            on_critical_path=True,
            action_kind="reduce_blame",
        ),
        expected_gain=GainEstimate(
            predicted_ns=350_000_000,
            upper_bound_ns=500_000_000,
            confidence=0.5,
        ),
        drop_in_content=(
            "# KylinBootLab Phase 5 -- reduce LightDM ExecStartPre delay\n"
            "[Service]\n"
            "ExecStartPre=\n"
            "ExecStartPre=-/bin/sleep 0.1\n"
        ),
        drop_in_path="/etc/systemd/system/lightdm.service.d/kbl-opt.conf",
        rollback=[
            "sudo rm -f /etc/systemd/system/lightdm.service.d/kbl-opt.conf",
            "sudo systemctl daemon-reload",
        ],
        functional_regression=[
            "systemctl is-active lightdm.service",
            "loginctl list-sessions | grep -q seat0",
        ],
        portability=0.7,
        stability_risk=0.3,
        verification_cost=18,
        falsification=(
            "If lightdm.service blame does not decrease by >=200ms, "
            "the ExecStartPre reduction had no effect."
        ),
    )
