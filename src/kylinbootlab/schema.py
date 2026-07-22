import json
from importlib import resources
from typing import Any


def load_probe_manifest_schema() -> dict[str, Any]:
    text = (
        resources.files("kylinbootlab.schemas")
        .joinpath("probe-manifest-v1.schema.json")
        .read_text(encoding="utf-8")
    )
    value = json.loads(text)
    if not isinstance(value, dict):
        raise ValueError("packaged probe manifest schema must be an object")
    return value
