"""Benchmark evaluator — structural proxy scoring against a 5-case fault corpus.

The MVP uses *structural proxy scoring* that checks whether the agent
populated each role section, rather than verifying semantic correctness
of the LLM output.  This gives a fast, deterministic signal during
development: 0.0 = pipeline is broken, 1.0 = all sections filled.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from kylinbootlab.agent.models import BootAgentReport


@dataclass
class BenchmarkCase:
    """A single benchmark case with ground truth and structural scoring."""

    id: str
    name: str
    ground_truth: dict[str, str]

    def score(self, report: BootAgentReport) -> float:
        """Structural proxy scoring (MVP).

        Scoring breakdown
        ----------------
        * +0.3  — trace.anomalies is non-empty
        * +0.3  — trace.missed_bottlenecks is non-empty
        * +0.2  — experiment plan is present (not None)
        * +0.2  — safety review is present (not None)

        Returns a float in [0.0, 1.0].  A score of 1.0 means all four
        structural sections are populated; it does **not** mean the
        LLM correctly identified the ground-truth anomaly.
        """
        total = 0.0

        if report.trace is not None:
            if report.trace.anomalies:
                total += 0.3
            if report.trace.missed_bottlenecks:
                total += 0.3

        if report.experiment is not None:
            total += 0.2

        if report.safety is not None:
            total += 0.2

        return total


def load_benchmark(path: Path) -> list[BenchmarkCase]:
    """Load benchmark cases from a JSON file.

    Expects a top-level ``"cases"`` key containing a list of objects,
    each with ``id``, ``name``, and ``ground_truth`` fields.
    """
    raw: dict[str, Any] = json.loads(path.read_text(encoding="utf-8"))
    return [
        BenchmarkCase(
            id=item["id"],
            name=item["name"],
            ground_truth=item["ground_truth"],
        )
        for item in raw["cases"]
    ]


def evaluate(report: BootAgentReport, cases: list[BenchmarkCase]) -> float:
    """Score *report* against every case and return the average.

    Returns 0.0 when *cases* is empty.
    """
    if not cases:
        return 0.0
    total = sum(case.score(report) for case in cases)
    return total / len(cases)
