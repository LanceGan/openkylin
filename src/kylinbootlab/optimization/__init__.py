"""KylinBootLab Phase 5: Optimization Planner, Scheduler & Executor.

Public API re-exports for the optimization subpackage.
"""

from kylinbootlab.optimization.executor import ProfileExecutor
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
from kylinbootlab.optimization.planner import rank_candidates, score_plan

__all__ = [
    "BottleneckEvidence",
    "GainEstimate",
    "OptimizationPlan",
    "ProfileExecutor",
    "build_exec_delay_lightdm",
    "build_mask_biometric",
    "build_mask_strongswan",
    "build_parallelize_kylin",
    "build_socket_nm_wait",
    "rank_candidates",
    "score_plan",
]
