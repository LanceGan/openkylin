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
    action_kind: Literal[
        "remove_edge", "reduce_blame", "service_mask",
        "kernel_param", "initramfs_trim", "parallelize",
    ]


class OptimizationPlan(ContractModel):
    """One independent optimization candidate -- a single systemd configuration change."""

    schema_version: Literal[1] = 1
    plan_id: str
    title: str
    category: Literal[
        "service_mask", "socket_activation", "parallelize",
        "exec_delay", "kernel_param", "initramfs_trim",
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


# -- Phase 6 candidate factories ------------------------------------------------


def phase6_mask_strongswan() -> OptimizationPlan:
    """Mask strongswan-starter.service (IPSec, unused on single-NIC desktop VM)."""
    return OptimizationPlan(
        plan_id="phase6-mask-strongswan",
        title="Mask strongswan-starter.service (IPSec, unused on VM)",
        category="service_mask",
        description="Disable IPSec daemon -- unused on single-NIC desktop VM.",
        evidence=BottleneckEvidence(
            node="strongswan-starter.service",
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
        mask_unit="strongswan-starter.service",
        rollback=["sudo systemctl unmask strongswan-starter.service"],
        functional_regression=[
            "systemctl is-active NetworkManager dbus lightdm",
        ],
        portability=0.8,
        stability_risk=0.1,
        verification_cost=18,
        falsification=(
            "If strongswan-starter.service still shows in systemd-analyze blame, "
            "plan failed."
        ),
    )


def phase6_kaiming_stagger() -> OptimizationPlan:
    """Move org.kylin.kaiming.service from graphical.target to multi-user.target."""
    return OptimizationPlan(
        plan_id="phase6-kaiming-stagger",
        title="Move kaiming from graphical.target → multi-user.target",
        category="parallelize",
        description=(
            "org.kylin.kaiming.service waits for graphical.target (1.4s blame) "
            "but is a dbus-activated daemon. Move to multi-user.target to run "
            "in parallel with NM/lightdm instead of blocking the graphical target."
        ),
        evidence=BottleneckEvidence(
            node="org.kylin.kaiming.service",
            blame_ns=1_420_000_000,
            slack_ns=0,
            on_critical_path=True,
            action_kind="parallelize",
        ),
        expected_gain=GainEstimate(
            predicted_ns=1_400_000_000,
            upper_bound_ns=1_420_000_000,
            confidence=0.9,
        ),
        drop_in_content=(
            "# KylinBootLab Phase 6 -- run kaiming before graphical target\n"
            "[Unit]\n"
            "After=\n"
            "After=multi-user.target\n"
        ),
        drop_in_path="/etc/systemd/system/org.kylin.kaiming.service.d/kbl-phase6.conf",
        rollback=[
            "sudo rm -f /etc/systemd/system/org.kylin.kaiming.service.d/kbl-phase6.conf",
            "sudo systemctl daemon-reload",
        ],
        functional_regression=[
            "systemctl is-active org.kylin.kaiming",
        ],
        portability=0.5,
        stability_risk=0.3,
        verification_cost=18,
        falsification=(
            "If graphical.target critical path does not shorten, plan failed."
        ),
    )


def phase6_parallel_kysdk() -> OptimizationPlan:
    """Relax serial After= constraints on kysdk daemons."""
    targets = [
        "kysdk-conf2.service", "kysdk-dbus.service", "kysdk-timer.service",
        "kysdk-basecommon.service", "kysdk-systime.service",
    ]
    drop_in = (
        "# KylinBootLab Phase 6 -- parallelize kysdk startup\n"
        "[Unit]\n"
        "After=dbus.service basic.target\n"
        "Wants=dbus.service\n"
    )
    rollback = [
        f"sudo rm -f /etc/systemd/system/{t}/kbl-phase6.conf"
        for t in targets
    ] + ["sudo systemctl daemon-reload"]
    regression = [
        f"systemctl is-active {t}" for t in targets
    ]
    return OptimizationPlan(
        plan_id="phase6-parallel-kysdk",
        title="Parallelize kysdk daemon startup",
        category="parallelize",
        description=(
            "Multiple kysdk daemons have serial After= constraints totaling "
            "~500ms. Relax to After=dbus.service + basic.target with Wants= "
            "so they start in parallel."
        ),
        evidence=BottleneckEvidence(
            node="kysdk-conf2.service",
            blame_ns=500_000_000,
            slack_ns=0,
            on_critical_path=True,
            action_kind="parallelize",
        ),
        expected_gain=GainEstimate(
            predicted_ns=400_000_000,
            upper_bound_ns=500_000_000,
            confidence=0.7,
        ),
        drop_in_content=drop_in,
        drop_in_path="/etc/systemd/system/kysdk-conf2.service.d/kbl-phase6.conf",
        rollback=rollback,
        functional_regression=regression,
        portability=0.5,
        stability_risk=0.3,
        verification_cost=18,
        falsification="If no blame reduction on kysdk* units, plan failed.",
    )


def phase6_mitigations_off() -> OptimizationPlan:
    """Disable CPU vulnerability mitigations via kernel command line."""
    return OptimizationPlan(
        plan_id="phase6-mitigations-off",
        title="Disable CPU vulnerability mitigations via kernel cmdline",
        category="kernel_param",
        description=(
            "Add mitigations=off to kernel command line. Spectre/Meltdown "
            "mitigations are unnecessary on a single-purpose VM and add "
            "~200-500ms to kernel startup."
        ),
        evidence=BottleneckEvidence(
            node="kernel (mitigations overhead)",
            blame_ns=300_000_000,
            slack_ns=0,
            on_critical_path=True,
            action_kind="kernel_param",
        ),
        expected_gain=GainEstimate(
            predicted_ns=300_000_000,
            upper_bound_ns=500_000_000,
            confidence=0.8,
        ),
        drop_in_content=(
            'GRUB_CMDLINE_LINUX_DEFAULT="$GRUB_CMDLINE_LINUX_DEFAULT mitigations=off"\n'
        ),
        drop_in_path="/etc/default/grub.d/kbl-phase6.cfg",
        rollback=[
            "sudo rm -f /etc/default/grub.d/kbl-phase6.cfg",
            "sudo update-grub",
        ],
        functional_regression=["systemctl is-system-running | grep -q running"],
        portability=1.0,
        stability_risk=0.1,
        verification_cost=18,
        falsification="If kernel_ns does not decrease, plan failed.",
    )


def phase6_initramfs_trim() -> OptimizationPlan:
    """Trim initramfs to minimal module set (MODULES=dep)."""
    return OptimizationPlan(
        plan_id="phase6-initramfs-trim",
        title="Trim initramfs to minimal module set (MODULES=dep)",
        category="initramfs_trim",
        description=(
            "Switch from MODULES=most to MODULES=dep in initramfs-tools, "
            "reducing the initramfs image size and module load time by "
            "~300-800ms on VM with no exotic hardware."
        ),
        evidence=BottleneckEvidence(
            node="initramfs (module loading)",
            blame_ns=500_000_000,
            slack_ns=0,
            on_critical_path=True,
            action_kind="initramfs_trim",
        ),
        expected_gain=GainEstimate(
            predicted_ns=500_000_000,
            upper_bound_ns=800_000_000,
            confidence=0.6,
        ),
        drop_in_content="MODULES=dep\n",
        drop_in_path="/etc/initramfs-tools/conf.d/kbl-phase6",
        rollback=[
            "sudo rm -f /etc/initramfs-tools/conf.d/kbl-phase6",
            "sudo update-initramfs -u -k all",
        ],
        functional_regression=[
            "dmesg | grep -q 'failed to load' && exit 1 || true",
        ],
        portability=0.8,
        stability_risk=0.5,
        verification_cost=18,
        falsification="If failed to load modules appear in dmesg, plan failed.",
    )
