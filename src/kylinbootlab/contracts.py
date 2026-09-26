from pathlib import PurePosixPath
from typing import Annotated, Literal, Self
from uuid import UUID

from pydantic import (
    AwareDatetime,
    BaseModel,
    ConfigDict,
    Field,
    NonNegativeInt,
    StringConstraints,
    field_validator,
    model_validator,
)

ArtifactName = Annotated[
    str,
    StringConstraints(pattern=r"^[a-z0-9][a-z0-9-]*$"),
]
Sha256 = Annotated[
    str,
    StringConstraints(pattern=r"^[0-9a-f]{64}$"),
]
Command = Annotated[list[str], Field(min_length=1)]


class ContractModel(BaseModel):
    """Base for all persisted KylinBootLab models — forbids undeclared fields."""

    model_config = ConfigDict(extra="forbid")


class HostInfo(ContractModel):
    """Identifies the target machine: hostname, kernel, OS, and architecture."""

    hostname: Annotated[str, Field(min_length=1)]
    kernel_release: Annotated[str, Field(min_length=1)]
    os_id: Annotated[str, Field(min_length=1)]
    os_version_id: Annotated[str, Field(min_length=1)]
    architecture: Annotated[str, Field(min_length=1)]


class ArtifactRecord(ContractModel):
    """One captured artifact within a probe snapshot — metadata and integrity hash."""

    name: ArtifactName
    relative_path: str
    sha256: Sha256
    size_bytes: NonNegativeInt
    command: Command
    exit_code: int
    required: bool

    @field_validator("relative_path")
    @classmethod
    def validate_relative_path(cls, value: str) -> str:
        """Reject absolute paths, parent traversal, backslashes, and colons.

        Colons are rejected in every path segment to block Windows drive-letter
        escapes (C:, D:) regardless of position.
        """
        parts = value.split("/")
        path = PurePosixPath(value)
        if (
            not value
            or path.is_absolute()
            or "\\" in value
            or any(part in {"", ".", ".."} for part in parts)
            or any(":" in part for part in parts)
        ):
            raise ValueError("relative_path must be a normalized relative POSIX path")
        return value


class ProbeManifest(ContractModel):
    """Top-level v1 probe snapshot manifest — binds a run to its artifacts."""

    schema_version: Literal[1]
    run_id: UUID
    boot_id: UUID
    captured_at_utc: AwareDatetime
    boottime_ns: NonNegativeInt
    host: HostInfo
    artifacts: Annotated[list[ArtifactRecord], Field(min_length=1)]

    @model_validator(mode="after")
    def reject_duplicate_artifacts(self) -> Self:
        """Ensure no two artifacts share the same name or relative path."""
        names = [artifact.name for artifact in self.artifacts]
        paths = [artifact.relative_path for artifact in self.artifacts]
        if len(names) != len(set(names)):
            raise ValueError("artifact names must be unique")
        if len(paths) != len(set(paths)):
            raise ValueError("artifact relative paths must be unique")
        return self
