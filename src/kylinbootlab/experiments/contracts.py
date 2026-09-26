from typing import Literal
from uuid import UUID

from pydantic import AwareDatetime, Field

from kylinbootlab.contracts import ContractModel


class ExperimentRecord(ContractModel):
    """One experiment in the queue — status tracked via append-only JSONL lines."""

    schema_version: Literal[1] = 1
    exp_id: str = Field(min_length=1, description="Unique experiment identifier")
    profile: str = Field(min_length=1, description="Profile name (baseline, tuned-*, etc.)")
    status: Literal["pending", "running", "done", "failed", "skipped"] = "pending"
    run_id: UUID | None = Field(default=None, description="Associated Phase 1 run ID")
    attempt: int = Field(default=0, ge=0, description="Current attempt number")
    max_attempts: int = Field(default=3, ge=1, description="Max attempts before giving up")
    error: str | None = Field(default=None, description="Last failure reason")
    created_at: AwareDatetime
    started_at: AwareDatetime | None = None
    completed_at: AwareDatetime | None = None
