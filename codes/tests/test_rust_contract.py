import json
import subprocess
from pathlib import Path

import jsonschema

from kylinbootlab.contracts import ProbeManifest
from kylinbootlab.readiness import derive_metrics, parse_events
from kylinbootlab.schema import load_probe_manifest_schema


def test_rust_contract_fixture_matches_python_contract() -> None:
    completed = subprocess.run(
        ["cargo", "run", "--quiet", "-p", "kbl-bootprobe", "--", "contract-fixture"],
        check=True,
        capture_output=True,
        text=True,
    )
    data = json.loads(completed.stdout)

    manifest = ProbeManifest.model_validate(data)
    jsonschema.Draft202012Validator(load_probe_manifest_schema()).validate(data)
    assert str(manifest.run_id) == "11111111-1111-4111-8111-111111111111"


def test_rust_readiness_fixture_matches_checked_in_fixture() -> None:
    completed = subprocess.run(
        ["cargo", "run", "--quiet", "-p", "kbl-bootprobe", "--", "readiness-fixture"],
        check=True,
        capture_output=True,
        text=True,
    )
    expected = Path("tests/fixtures/readiness-events-v1.jsonl").read_text(encoding="utf-8")
    assert completed.stdout == expected  # byte-identical JSONL, field order included

    metrics = derive_metrics(parse_events(completed.stdout))
    assert metrics.status == "complete"
    assert metrics.usable_ns == 18_100_000_000
