"""Pydantic data models for BootAgent structured outputs.

Every model extends ``ContractModel`` so undeclared fields are rejected,
matching the same defence-in-depth pattern used by the probe manifest.
"""

from typing import Literal

from pydantic import Field, NonNegativeInt

from kylinbootlab.contracts import ContractModel

# -- Leaf value objects --------------------------------------------------------


class Anomaly(ContractModel):
    """A single bottleneck anomaly identified by the Trace Analyst."""

    node: str
    blame_ns: NonNegativeInt
    slack_ns: NonNegativeInt
    on_critical_path: bool
    issue: str
    evidence: str


class UnitFinding(ContractModel):
    """One actionable finding from inspecting a systemd unit file."""

    unit_name: str
    issue: str
    evidence_lines: list[str]
    suggested_change: str | None = None


# -- Role outputs --------------------------------------------------------------


class TraceAnalysis(ContractModel):
    """Trace Analyst structured output — anomalies, volatility, missed items."""

    anomalies: list[Anomaly]
    cross_boot_volatility: str
    missed_bottlenecks: list[str]
    confidence: float = Field(ge=0.0, le=1.0)


class SourceReport(ContractModel):
    """Source Investigator structured output — unit findings and insights."""

    unit_findings: list[UnitFinding]
    relevant_documentation: list[str]
    actionable_insights: list[str]


class ExperimentPlan(ContractModel):
    """Experiment Designer structured output — a single proposed experiment."""

    plan_id: str
    hypothesis: str
    predicted_gain_ns: NonNegativeInt
    evidence_chain: list[str]
    drop_in_content: str | None = None
    rollback: list[str]
    functional_regression: list[str]
    falsification: str


class SafetyReview(ContractModel):
    """Safety Critic structured output — risk assessment and recommendation."""

    risk_score: float = Field(ge=0.0, le=1.0)
    concerns: list[str]
    functional_regression_risks: list[str]
    portability_concern: str | None = None
    recommendation: Literal["APPROVE", "REVIEW", "REJECT"]


# -- Aggregate report ----------------------------------------------------------


class BootAgentReport(ContractModel):
    """Top-level report aggregating all four role outputs (nullable)."""

    run_id: str
    trace: TraceAnalysis | None = None
    source: SourceReport | None = None
    experiment: ExperimentPlan | None = None
    safety: SafetyReview | None = None
