"""BootAgent four-role controller — orchestrates LLM-assisted boot analysis."""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import TYPE_CHECKING
from uuid import UUID

from pydantic import BaseModel

from kylinbootlab.agent.backend import OllamaBackend
from kylinbootlab.agent.models import (
    BootAgentReport,
    ExperimentPlan,
    SafetyReview,
    SourceReport,
    TraceAnalysis,
)
from kylinbootlab.agent.skills import load_skill, validate_output

if TYPE_CHECKING:
    from kylinbootlab.store import RunStore

logger = logging.getLogger(__name__)

_SKILLS_DIR = Path("agent/skills")


class BootAgent:
    """Four-role pipeline: Trace Analyst -> Source Investigator -> Experiment
    Designer -> Safety Critic.

    Each role failure results in ``None`` for that section — the pipeline
    never aborts.
    """

    def __init__(self, backend: OllamaBackend, store: RunStore) -> None:
        self.backend = backend
        self.store = store

    def analyze(self, run_id: UUID | None) -> BootAgentReport:
        """Run the full four-role pipeline on a stored run.

        When *run_id* is ``None``, returns a minimal placeholder report
        (used by the benchmark command for structural scoring MVP).
        """
        if run_id is None:
            return BootAgentReport(run_id="benchmark")

        rid = run_id
        run_id_str = str(rid)

        # Load bottleneck data from the store
        bottleneck_text = self._load_context(rid)

        # --- Role 1: Trace Analyst ---
        trace = self._run_role(
            skill_file="trace-analyst.toml",
            context=bottleneck_text,
            model_cls=TraceAnalysis,
        )

        # --- Role 2: Source Investigator ---
        source = self._run_role(
            skill_file="source-investigator.toml",
            context=bottleneck_text,
            model_cls=SourceReport,
        )

        # --- Role 3: Experiment Designer ---
        experiment = self._run_role(
            skill_file="experiment-designer.toml",
            context=bottleneck_text,
            model_cls=ExperimentPlan,
        )

        # --- Role 4: Safety Critic ---
        safety = self._run_role(
            skill_file="safety-critic.toml",
            context=bottleneck_text,
            model_cls=SafetyReview,
        )

        return BootAgentReport(
            run_id=run_id_str,
            trace=trace,  # type: ignore[arg-type]
            source=source,  # type: ignore[arg-type]
            experiment=experiment,  # type: ignore[arg-type]
            safety=safety,  # type: ignore[arg-type]
        )

    # -- internal helpers --------------------------------------------------------

    def _load_context(self, run_id: UUID) -> str:
        """Load bottleneck-report.json from the store and format as context text."""
        derived = self.store.derived_path(run_id)
        br_path = derived / "bottleneck-report.json"
        if br_path.is_file():
            raw = json.loads(br_path.read_text(encoding="utf-8"))
            return json.dumps(raw, indent=2)
        # Fall back to just manifest info
        try:
            manifest = self.store.load_manifest(run_id)
            return (
                f"Run {run_id}: host {manifest.host.hostname}, "
                f"{len(manifest.artifacts)} artifacts"
            )
        except Exception:
            return f"Run {run_id}: no data available"

    def _run_role(
        self,
        skill_file: str,
        context: str,
        model_cls: type[BaseModel],
    ) -> BaseModel | None:
        """Load a skill, call the backend, validate output, return model instance.

        Returns ``None`` when the backend call fails, the output is malformed,
        or validation fails — the pipeline continues.
        """
        try:
            skill = load_skill(_SKILLS_DIR / skill_file)
            raw_text = self.backend.chat(
                system_prompt=skill.system_prompt, user_message=context
            )
            data = validate_output(raw_text, skill.output_schema)
            # Keep only fields that the Pydantic model accepts
            valid_fields = set(model_cls.model_fields.keys())
            data = {k: v for k, v in data.items() if k in valid_fields}
            return model_cls.model_validate(data)
        except Exception:
            logger.warning(
                "Role '%s' failed — continuing pipeline", skill_file, exc_info=True
            )
            return None
