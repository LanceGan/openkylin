import json
import subprocess

import jsonschema

from kylinbootlab.contracts import ProbeManifest
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
