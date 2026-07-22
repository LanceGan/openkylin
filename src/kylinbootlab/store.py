import hashlib
import json
import os
import shutil
from pathlib import Path
from uuid import UUID

import jsonschema
from pydantic import ValidationError

from kylinbootlab.contracts import ProbeManifest
from kylinbootlab.schema import load_probe_manifest_schema


class BundleError(ValueError):
    """Raised when a probe bundle fails validation — never results in partial import."""


def load_bundle_manifest(bundle: Path) -> ProbeManifest:
    """Load and validate a probe-manifest.json from a bundle directory.

    Validates against both the JSON Schema and Pydantic model (defense in depth).
    """
    manifest_path = bundle / "probe-manifest.json"
    try:
        raw = json.loads(manifest_path.read_text(encoding="utf-8"))
        jsonschema.Draft202012Validator(load_probe_manifest_schema()).validate(raw)
        return ProbeManifest.model_validate(raw)
    except (OSError, json.JSONDecodeError, jsonschema.ValidationError, ValidationError) as error:
        raise BundleError(f"invalid probe manifest: {error}") from error


def artifact_path(root: Path, relative_path: str) -> Path:
    """Resolve a manifest-declared relative_path under *root*.

    The containment check is defense-in-depth — the Pydantic validator in
    contracts.py already rejects ``..`` segments, but this guards against
    future schema changes or hand-crafted manifests that bypass validation.
    """
    result = root.joinpath(*relative_path.split("/"))
    root_resolved = root.resolve()
    result_resolved = result.resolve()
    if not result_resolved.is_relative_to(root_resolved):
        raise BundleError(f"artifact path escapes bundle: {relative_path}")
    return result


class RunStore:
    """Immutable, append-only store for validated probe runs.

    Each run lives at ``<root>/<run_id>/`` with the structure::

        <run_id>/
        ├── manifest.json       # canonical manifest (from in-memory model)
        ├── raw/                # verified artifacts (never modified)
        │   └── captures/
        ├── derived/            # rebuildable metrics
        └── reports/            # rebuildable HTML/JSON reports

    ``ingest()`` uses a 4-phase pipeline (enumerate → copy-to-staging →
    verify-from-staging → atomic-install) to close TOCTOU windows.
    """

    def __init__(self, root: Path) -> None:
        self.root = root

    def ingest(self, bundle: Path) -> Path:
        # --- Phase 0: Pre-conditions ---
        if bundle.is_symlink() or not bundle.is_dir():
            raise BundleError("bundle must be a real directory")

        manifest = load_bundle_manifest(bundle)
        destination = self.root / str(manifest.run_id)
        incoming = self.root / f".incoming-{manifest.run_id}"
        if destination.exists():
            raise BundleError(f"run already exists: {manifest.run_id}")
        if incoming.exists():
            raise BundleError(f"stale incoming run exists: {incoming}")

        # --- Phase 1: Enumerate source (symlink + file-set check) ---
        expected_files = {"probe-manifest.json"}
        expected_files.update(artifact.relative_path for artifact in manifest.artifacts)
        actual_files: set[str] = set()
        for path in bundle.rglob("*"):
            if path.is_symlink():
                raise BundleError(f"bundle contains a symlink: {path}")
            if path.is_file():
                actual_files.add(path.relative_to(bundle).as_posix())
        if actual_files != expected_files:
            raise BundleError(
                "bundle file set does not match manifest: "
                f"expected={sorted(expected_files)} actual={sorted(actual_files)}"
            )

        # --- Phase 2: Copy to staging ---
        self.root.mkdir(parents=True, exist_ok=True)
        try:
            raw_root = incoming / "raw"
            raw_root.mkdir(parents=True)
            # Write manifest from validated in-memory object (not disk copy)
            (incoming / "manifest.json").write_text(
                manifest.model_dump_json(indent=2) + "\n",
                encoding="utf-8",
                newline="\n",
            )
            for artifact in manifest.artifacts:
                source = artifact_path(bundle, artifact.relative_path)
                target = artifact_path(raw_root, artifact.relative_path)
                target.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(source, target)

            # --- Phase 3: Verify FROM STAGING (closes TOCTOU) ---
            for artifact in manifest.artifacts:
                copied = artifact_path(raw_root, artifact.relative_path)
                if copied.is_symlink():
                    raise BundleError(
                        f"artifact resolved to symlink after copy: {artifact.name}"
                    )
                data = copied.read_bytes()
                if len(data) != artifact.size_bytes:
                    raise BundleError(f"size mismatch for {artifact.name}")
                if hashlib.sha256(data).hexdigest() != artifact.sha256:
                    raise BundleError(f"checksum mismatch for {artifact.name}")

            # --- Phase 4: Atomically install ---
            # os.replace is atomic on POSIX (rename syscall) when source and
            # destination are on the same filesystem — which they always are
            # since both incoming and destination live under self.root.
            os.replace(incoming, destination)
        except Exception:
            if incoming.exists():
                shutil.rmtree(incoming)
            raise

        return destination

    def run_path(self, run_id: UUID) -> Path:
        return self.root / str(run_id)

    def derived_path(self, run_id: UUID) -> Path:
        """Return the derived/ subdirectory for a run."""
        return self.run_path(run_id) / "derived"

    def load_manifest(self, run_id: UUID) -> ProbeManifest:
        path = self.run_path(run_id) / "manifest.json"
        try:
            return ProbeManifest.model_validate_json(path.read_text(encoding="utf-8"))
        except (OSError, ValidationError) as error:
            raise BundleError(f"invalid stored manifest for {run_id}: {error}") from error
