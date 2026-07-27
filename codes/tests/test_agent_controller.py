"""Tests for BootAgent controller — four-role pipeline orchestration."""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import MagicMock
from uuid import UUID, uuid4

from kylinbootlab.agent.backend import OllamaBackend
from kylinbootlab.agent.controller import BootAgent
from kylinbootlab.agent.models import BootAgentReport
from kylinbootlab.store import RunStore
from tests.helpers import create_probe_bundle

# ---------------------------------------------------------------------------
# Shared test data
# ---------------------------------------------------------------------------

_BOTTLENECK_REPORT = {
    "run_id": "",
    "bottlenecks": [
        {
            "rank": 1,
            "node": "network.service",
            "blame_ns": 900_000_000,
            "slack_ns": 0,
            "on_critical_path": True,
            "score": 900.0,
            "evidence": "slack=0; on critical path (1 run(s))",
        },
        {
            "rank": 2,
            "node": "dbus.service",
            "blame_ns": 500_000_000,
            "slack_ns": 100_000_000,
            "on_critical_path": True,
            "score": 450.0,
            "evidence": "slack=100000000ns; on critical path (1 run(s))",
        },
    ],
    "critical_path_nodes": [
        "network.service",
        "graphical.target",
        "greeter_started",
        "greeter_ready",
        "session_opened",
        "usable",
    ],
}

# Mock LLM responses — each is valid JSON matching its role's output schema.
# The ```json fence format is what validate_output() extracts first.

_TRACE_RESPONSE = """\
```json
{
  "anomalies": [
    {
      "node": "network.service",
      "blame_ns": 900000000,
      "slack_ns": 0,
      "on_critical_path": true,
      "issue": "NetworkManager blocks graphical.target readiness",
      "evidence": "blame=900ms, slack=0, on critical path"
    }
  ],
  "cross_boot_volatility": "Low volatility across runs",
  "missed_bottlenecks": [],
  "confidence": 0.85
}
```
"""

_SOURCE_RESPONSE = """\
```json
{
  "unit_findings": [
    {
      "unit_name": "network.service",
      "issue": "Unnecessary After=network-online.target dependency",
      "evidence_lines": ["After=network-online.target"],
      "suggested_change": "Remove After=network-online.target to allow earlier start"
    }
  ],
  "relevant_documentation": ["systemd.unit(5)", "systemd.service(5)"],
  "actionable_insights": ["NetworkManager startup can be parallelized with dbus"]
}
```
"""

_EXPERIMENT_RESPONSE = """\
```json
{
  "plan_id": "exp-network-001",
  "hypothesis": "Removing network-online.target dependency reduces userspace boot time by 500ms",
  "predicted_gain_ns": 500000000,
  "evidence_chain": [
    "network.service blame=900ms in systemd-analyze blame",
    "network.service on critical path to usable",
    "Trace Analyst identified as primary anomaly"
  ],
  "drop_in_content": "[Unit]\\nAfter=\\nWants=",
  "rollback": [
    "sudo rm /etc/systemd/system/network.service.d/kbl-exp-001.conf",
    "sudo systemctl daemon-reload"
  ],
  "functional_regression": [
    "Network-dependent services may start before network is ready",
    "Avahi may fail to register on first attempt"
  ],
  "falsification": "Median os_total_ns does not decrease by 200ms vs. baseline over 5 cold boots"
}
```
"""

_SAFETY_RESPONSE = """\
```json
{
  "risk_score": 0.30,
  "concerns": [
    "Service ordering change may delay network availability for login"
  ],
  "functional_regression_risks": [
    "Services depending on network-online.target may fail briefly"
  ],
  "portability_concern": null,
  "recommendation": "APPROVE"
}
```
"""

_GARBAGE_RESPONSE = "I'm sorry, I cannot process this request right now."

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _ingest_run(store_root: Path) -> tuple[RunStore, UUID]:
    """Create a RunStore with one ingested run + derived/bottleneck-report.json.

    Returns the store and the run's UUID so tests can call ``agent.analyze()``.
    """
    store = RunStore(store_root / "runs")
    run_id = uuid4()
    bundle = create_probe_bundle(store_root / "source", run_id=run_id)
    store.ingest(bundle)

    # Write the bottleneck report that _load_context() reads.
    derived = store.derived_path(run_id)
    derived.mkdir(parents=True)
    report = dict(_BOTTLENECK_REPORT)
    report["run_id"] = str(run_id)
    (derived / "bottleneck-report.json").write_text(
        json.dumps(report, indent=2) + "\n", encoding="utf-8", newline="\n"
    )
    return store, run_id


def _backend_that_returns(*responses: str) -> OllamaBackend:
    """Return a mock OllamaBackend whose ``chat()`` returns *responses* in order."""
    mock = MagicMock(spec=OllamaBackend)
    mock.chat = MagicMock(side_effect=list(responses))
    return mock


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


def test_analyze_pipeline_completes_all_four_roles(tmp_path: Path) -> None:
    """Mock returns valid JSON for every role — report has all four sections."""
    store, run_id = _ingest_run(tmp_path)
    backend = _backend_that_returns(
        _TRACE_RESPONSE,
        _SOURCE_RESPONSE,
        _EXPERIMENT_RESPONSE,
        _SAFETY_RESPONSE,
    )
    agent = BootAgent(backend, store)

    report = agent.analyze(run_id)

    assert report.trace is not None
    assert report.source is not None
    assert report.experiment is not None
    assert report.safety is not None

    # Verify trace content
    assert len(report.trace.anomalies) == 1
    assert report.trace.anomalies[0].node == "network.service"
    assert report.trace.confidence == 0.85

    # Verify source content
    assert len(report.source.unit_findings) == 1
    assert report.source.unit_findings[0].unit_name == "network.service"

    # Verify experiment content
    assert report.experiment.plan_id == "exp-network-001"
    assert report.experiment.predicted_gain_ns == 500000000

    # Verify safety content
    assert report.safety.risk_score == 0.30
    assert report.safety.recommendation == "APPROVE"


def test_role_failure_returns_none_for_that_section(tmp_path: Path) -> None:
    """One role returns garbage — its section is None, others are present."""
    store, run_id = _ingest_run(tmp_path)

    # Source Investigator returns garbage (2nd call to backend.chat)
    backend = _backend_that_returns(
        _TRACE_RESPONSE,       # Trace Analyst succeeds
        _GARBAGE_RESPONSE,     # Source Investigator fails
        _EXPERIMENT_RESPONSE,  # Experiment Designer succeeds
        _SAFETY_RESPONSE,      # Safety Critic succeeds
    )
    agent = BootAgent(backend, store)

    report = agent.analyze(run_id)

    # Trace Analyst should still succeed
    assert report.trace is not None
    assert len(report.trace.anomalies) == 1

    # Source Investigator should be None
    assert report.source is None

    # Downstream roles still run independently
    assert report.experiment is not None
    assert report.safety is not None


def test_pipeline_produces_valid_report_schema(tmp_path: Path) -> None:
    """Full mock run produces a BootAgentReport that passes validation."""
    store, run_id = _ingest_run(tmp_path)
    backend = _backend_that_returns(
        _TRACE_RESPONSE,
        _SOURCE_RESPONSE,
        _EXPERIMENT_RESPONSE,
        _SAFETY_RESPONSE,
    )
    agent = BootAgent(backend, store)

    report = agent.analyze(run_id)

    # Should be a BootAgentReport instance
    assert isinstance(report, BootAgentReport)

    # Serialize round-trip
    dumped = report.model_dump()
    reloaded = BootAgentReport.model_validate(dumped)
    assert reloaded.run_id == report.run_id
    assert reloaded.trace is not None
    assert reloaded.source is not None
    assert reloaded.experiment is not None
    assert reloaded.safety is not None

    # JSON round-trip
    json_text = report.model_dump_json()
    from_json = BootAgentReport.model_validate_json(json_text)
    assert from_json.run_id == report.run_id
