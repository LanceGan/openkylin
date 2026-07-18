import json
import subprocess
import sys
from importlib import resources
from pathlib import Path
from typing import Any

import jsonschema
import pytest
from pydantic import ValidationError

from kylinbootlab.contracts import ProbeManifest

FIXTURE = Path("tests/fixtures/probe-manifest-v1.json")


def fixture_data() -> Any:
    return json.loads(FIXTURE.read_text(encoding="utf-8"))


def test_probe_manifest_accepts_v1_fixture() -> None:
    manifest = ProbeManifest.model_validate(fixture_data())

    assert manifest.schema_version == 1
    assert manifest.host.os_id == "openkylin"
    assert manifest.artifacts[0].name == "systemd-time"


def test_probe_manifest_rejects_parent_path() -> None:
    data = fixture_data()
    artifacts = data["artifacts"]
    assert isinstance(artifacts, list)
    artifacts[0]["relative_path"] = "../outside.json"

    with pytest.raises(ValidationError, match="relative_path"):
        ProbeManifest.model_validate(data)


def test_packaged_json_schema_validates_fixture() -> None:
    schema_text = (
        resources.files("kylinbootlab.schemas")
        .joinpath("probe-manifest-v1.schema.json")
        .read_text(encoding="utf-8")
    )
    schema = json.loads(schema_text)
    jsonschema.Draft202012Validator.check_schema(schema)
    jsonschema.Draft202012Validator(schema).validate(fixture_data())


def test_probe_manifest_rejects_unknown_field() -> None:
    data = fixture_data()
    data["untrusted"] = True

    with pytest.raises(ValidationError, match="untrusted"):
        ProbeManifest.model_validate(data)


@pytest.mark.parametrize(
    "bad_path",
    [
        "captures/C:outside.json",
        "a:b/c.json",
        "captures/D:evil.json",
    ],
)
def test_relative_path_rejects_colon_in_any_segment(bad_path: str) -> None:
    data = fixture_data()
    artifacts = data["artifacts"]
    assert isinstance(artifacts, list)
    artifacts[0]["relative_path"] = bad_path

    with pytest.raises(ValidationError, match="relative_path"):
        ProbeManifest.model_validate(data)


def test_generated_schema_is_current() -> None:
    subprocess.run(
        [sys.executable, "scripts/export_schema.py", "--check"],
        check=True,
    )
