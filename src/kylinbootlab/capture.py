from pathlib import Path

from kylinbootlab.contracts import ArtifactRecord, Command, ContractModel, ProbeManifest
from kylinbootlab.store import BundleError, artifact_path


class CommandCapture(ContractModel):
    command: Command
    exit_code: int
    stdout: str
    stderr: str


def find_artifact(manifest: ProbeManifest, name: str) -> ArtifactRecord:
    matches = [artifact for artifact in manifest.artifacts if artifact.name == name]
    if len(matches) != 1:
        raise BundleError(f"expected one artifact named {name}, found {len(matches)}")
    return matches[0]


def load_command_capture(run_path: Path, manifest: ProbeManifest, name: str) -> CommandCapture:
    """Load and validate one command capture from the run's raw artifacts.

    Raises ``BundleError`` when the capture is missing, its metadata disagrees
    with the manifest, or a *required* capture has a non-zero exit code.
    Optional captures with non-zero exit codes are returned but flagged
    with ``stderr`` containing the failure reason.
    """
    artifact = find_artifact(manifest, name)
    path = artifact_path(run_path / "raw", artifact.relative_path)
    capture = CommandCapture.model_validate_json(path.read_text(encoding="utf-8"))
    if capture.command != artifact.command or capture.exit_code != artifact.exit_code:
        raise BundleError(f"capture metadata disagrees with manifest for {name}")
    if capture.exit_code != 0 and artifact.required:
        raise BundleError(f"required capture failed for {name}: {capture.stderr.strip()}")
    return capture
