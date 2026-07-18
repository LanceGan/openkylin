from pathlib import Path

import pytest

from kylinbootlab.store import BundleError, RunStore, artifact_path
from tests.helpers import RUN_ID, create_probe_bundle


def test_ingest_verifies_and_moves_bundle_into_raw_store(tmp_path: Path) -> None:
    bundle = create_probe_bundle(tmp_path / "source")
    store = RunStore(tmp_path / "runs")

    run_path = store.ingest(bundle)

    assert run_path == tmp_path / "runs" / str(RUN_ID)
    assert (run_path / "manifest.json").is_file()
    assert (run_path / "raw/captures/systemd-time.json").is_file()
    assert store.load_manifest(RUN_ID).run_id == RUN_ID


def test_ingest_rejects_checksum_mismatch_without_partial_run(tmp_path: Path) -> None:
    bundle = create_probe_bundle(tmp_path / "source")
    capture = bundle / "captures/systemd-time.json"
    data = bytearray(capture.read_bytes())
    data[0] = ord("[")
    capture.write_bytes(data)
    store = RunStore(tmp_path / "runs")

    with pytest.raises(BundleError, match="checksum mismatch"):
        store.ingest(bundle)

    assert not (tmp_path / "runs" / str(RUN_ID)).exists()


def test_ingest_rejects_unlisted_file(tmp_path: Path) -> None:
    bundle = create_probe_bundle(tmp_path / "source")
    (bundle / "unexpected.txt").write_text("not declared", encoding="utf-8")

    with pytest.raises(BundleError, match="file set does not match"):
        RunStore(tmp_path / "runs").ingest(bundle)


def test_ingest_rejects_duplicate_run_id(tmp_path: Path) -> None:
    bundle = create_probe_bundle(tmp_path / "source")
    store = RunStore(tmp_path / "runs")
    store.ingest(bundle)

    with pytest.raises(BundleError, match="already exists"):
        store.ingest(bundle)


def test_ingest_rejects_missing_artifact(tmp_path: Path) -> None:
    bundle = create_probe_bundle(tmp_path / "source")
    (bundle / "captures/systemd-time.json").unlink()

    with pytest.raises(BundleError, match="file set does not match"):
        RunStore(tmp_path / "runs").ingest(bundle)


def test_ingest_rejects_size_mismatch(tmp_path: Path) -> None:
    import json

    bundle = create_probe_bundle(tmp_path / "source")
    manifest_path = bundle / "probe-manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["artifacts"][0]["size_bytes"] += 1
    manifest_path.write_text(
        json.dumps(manifest, indent=2) + "\n",
        encoding="utf-8",
        newline="\n",
    )

    with pytest.raises(BundleError, match="size mismatch"):
        RunStore(tmp_path / "runs").ingest(bundle)


def test_artifact_path_rejects_escape_via_containment(tmp_path: Path) -> None:
    root = tmp_path / "bundle"
    root.mkdir()

    # The contracts validator rejects ".." segments, but artifact_path's
    # containment check provides defense-in-depth. Test with a path that
    # joinpath would resolve above root.
    with pytest.raises(BundleError, match="artifact path escapes bundle"):
        artifact_path(root, "../../outside.json")


def test_ingest_cleans_up_incoming_on_verification_failure(tmp_path: Path) -> None:
    bundle = create_probe_bundle(tmp_path / "source")
    # Tamper with an artifact AFTER copy by crafting a manifest with wrong checksum
    import json

    manifest_path = bundle / "probe-manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["artifacts"][0]["sha256"] = "0" * 64
    manifest_path.write_text(
        json.dumps(manifest, indent=2) + "\n",
        encoding="utf-8",
        newline="\n",
    )
    store = RunStore(tmp_path / "runs")

    with pytest.raises(BundleError, match="checksum mismatch"):
        store.ingest(bundle)

    # Verify no partial state — destination was never created
    assert not (tmp_path / "runs" / str(RUN_ID)).exists()
    # Verify incoming staging was cleaned up
    incoming = tmp_path / "runs" / f".incoming-{RUN_ID}"
    assert not incoming.exists()
