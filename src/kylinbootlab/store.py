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
    pass


def load_bundle_manifest(bundle: Path) -> ProbeManifest:
    manifest_path = bundle / "probe-manifest.json"
    try:
        raw = json.loads(manifest_path.read_text(encoding="utf-8"))
        jsonschema.Draft202012Validator(load_probe_manifest_schema()).validate(raw)
        return ProbeManifest.model_validate(raw)
    except (OSError, json.JSONDecodeError, jsonschema.ValidationError, ValidationError) as error:
        raise BundleError(f"invalid probe manifest: {error}") from error


def artifact_path(root: Path, relative_path: str) -> Path:
    return root.joinpath(*relative_path.split("/"))


class RunStore:
    def __init__(self, root: Path) -> None:
        self.root = root

    def ingest(self, bundle: Path) -> Path:
        if bundle.is_symlink() or not bundle.is_dir():
            raise BundleError("bundle must be a real directory")

        manifest = load_bundle_manifest(bundle)
        destination = self.root / str(manifest.run_id)
        incoming = self.root / f".incoming-{manifest.run_id}"
        if destination.exists():
            raise BundleError(f"run already exists: {manifest.run_id}")
        if incoming.exists():
            raise BundleError(f"stale incoming run exists: {incoming}")

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

        for artifact in manifest.artifacts:
            source = artifact_path(bundle, artifact.relative_path)
            data = source.read_bytes()
            if len(data) != artifact.size_bytes:
                raise BundleError(f"size mismatch for {artifact.name}")
            if hashlib.sha256(data).hexdigest() != artifact.sha256:
                raise BundleError(f"checksum mismatch for {artifact.name}")

        self.root.mkdir(parents=True, exist_ok=True)
        try:
            raw_root = incoming / "raw"
            raw_root.mkdir(parents=True)
            shutil.copy2(bundle / "probe-manifest.json", incoming / "manifest.json")
            for artifact in manifest.artifacts:
                source = artifact_path(bundle, artifact.relative_path)
                target = artifact_path(raw_root, artifact.relative_path)
                target.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(source, target)
            shutil.move(str(incoming), str(destination))
        except Exception:
            if incoming.exists():
                shutil.rmtree(incoming)
            raise

        return destination

    def run_path(self, run_id: UUID) -> Path:
        return self.root / str(run_id)

    def load_manifest(self, run_id: UUID) -> ProbeManifest:
        path = self.run_path(run_id) / "manifest.json"
        try:
            return ProbeManifest.model_validate_json(path.read_text(encoding="utf-8"))
        except (OSError, ValidationError) as error:
            raise BundleError(f"invalid stored manifest for {run_id}: {error}") from error
