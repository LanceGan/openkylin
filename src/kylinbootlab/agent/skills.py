"""Skill loader — parses per-role TOML configs and validates LLM JSON output."""

from __future__ import annotations

import json
import re
import tomllib
from pathlib import Path
from typing import Any

import jsonschema
from pydantic import BaseModel, ConfigDict


class SkillConfig(BaseModel):
    """A single BootAgent role skill loaded from a TOML file."""

    model_config = ConfigDict(extra="forbid")

    name: str
    description: str
    system_prompt: str
    output_schema: dict[str, Any]


def load_skill(path: Path) -> SkillConfig:
    """Parse a role-skill TOML file and return a validated ``SkillConfig``.

    The TOML is expected to follow the structure::

        [role]
        name = "Trace Analyst"
        description = "..."

        [prompt]
        system = \"\"\"
        ...full system prompt...
        \"\"\"

        [output_schema]
        description = "..."
        schema = \"\"\"
        {...JSON Schema matching the model...}
        \"\"\"

    The ``output_schema.schema`` field is parsed as JSON and validated as a
    Draft 2020-12 JSON Schema.
    """
    raw = tomllib.loads(path.read_text(encoding="utf-8"))

    role = raw.get("role", {})
    prompt = raw.get("prompt", {})
    output = raw.get("output_schema", {})

    schema_text = output.get("schema", "")
    if isinstance(schema_text, str):
        try:
            schema_dict = json.loads(schema_text)
        except json.JSONDecodeError as exc:
            raise ValueError(
                f"output_schema.schema in {path} is not valid JSON: {exc}"
            ) from exc
    elif isinstance(schema_text, dict):
        schema_dict = schema_text
    else:
        raise ValueError(
            f"output_schema.schema in {path} must be a JSON string or object"
        )

    # Validate that it is a legitimate JSON Schema (Draft 2020-12)
    try:
        jsonschema.Draft202012Validator.check_schema(schema_dict)
    except jsonschema.SchemaError as exc:
        raise ValueError(
            f"output_schema.schema in {path} is not a valid JSON Schema: {exc}"
        ) from exc

    return SkillConfig(
        name=role.get("name", ""),
        description=role.get("description", ""),
        system_prompt=prompt.get("system", ""),
        output_schema=schema_dict,
    )


_JSON_BLOCK_RE = re.compile(
    r"```(?:json)?\s*([\s\S]*?)```", re.IGNORECASE
)


def validate_output(text: str, json_schema: dict[str, Any]) -> dict[str, Any]:
    """Extract JSON from LLM text output and validate against a JSON Schema.

    Tries (in order):
        1. A `` ```json ... ``` `` fenced code block.
        2. A bare `` ``` ... ``` `` fenced block.
        3. The entire *text* string as raw JSON.

    Returns the parsed and validated dict.

    Raises:
        ValueError: If no valid JSON can be extracted or the data violates
            the schema.
    """
    data: dict[str, Any] | None = None

    # 1. Try ```json ... ``` block
    for match in _JSON_BLOCK_RE.finditer(text):
        candidate = match.group(1).strip()
        try:
            parsed = json.loads(candidate)
            if isinstance(parsed, dict):
                data = parsed
                break
        except json.JSONDecodeError:
            continue

    # 2. Try raw text as JSON
    if data is None:
        stripped = text.strip()
        try:
            parsed = json.loads(stripped)
            if isinstance(parsed, dict):
                data = parsed
        except json.JSONDecodeError:
            pass

    if data is None:
        raise ValueError(
            "Could not extract a JSON object from the response text. "
            "Ensure the output contains a ```json ... ``` block or is "
            "itself valid JSON."
        )

    # Normalize common field-name aliases that small models produce
    data = _normalize_field_aliases(data)

    # Replace null values with type-safe defaults
    _replace_nulls(data)

    # Flatten objects that should be scalars — small models often wrap
    # simple values in {value: X} or {description: "..."} objects
    _flatten_objects(data)

    # Clamp negative values to 0 for fields that look like durations or counts
    _clamp_negatives(data)

    # Fill in missing required fields with defaults
    _fill_defaults(data, json_schema)

    jsonschema.Draft202012Validator(json_schema).validate(data)
    return data


def _flatten_objects(data: dict[str, Any]) -> None:
    """Extract scalar values from overly-nested object structures.

    Small models sometimes emit ``{value: N, evidence_chain: [...]}``
    when asked for a simple integer, or ``{description: "..."}`` when
    a plain string is expected.  This extracts the obvious inner value.
    """
    for key, value in list(data.items()):
        if isinstance(value, dict):
            is_duration = key.endswith("_ns") and "value" in value
            is_gain = key == "predicted_gain_ns" and "value" in value
            if is_duration or is_gain:
                data[key] = value["value"]
            else:
                _flatten_objects(value)
        elif isinstance(value, list):
            for i, item in enumerate(value):
                if isinstance(item, dict):
                    if "description" in item and len(item) <= 2:
                        value[i] = item.get("description", str(item))
                    elif "feature" in item and "impact" in item:
                        # {feature: "X", impact: "Y"} → "X: Y"
                        value[i] = f"{item['feature']}: {item['impact']}"
                    else:
                        _flatten_objects(item)


def _clamp_negatives(data: dict[str, Any]) -> None:
    """Recursively clamp negative integers to 0 for *_ns and *_count fields."""
    for key, value in list(data.items()):
        if isinstance(value, int) and value < 0 and (
            key.endswith("_ns") or key.endswith("_count") or key == "slack_ns"
        ):
            data[key] = 0
        elif isinstance(value, dict):
            _clamp_negatives(value)
        elif isinstance(value, list):
            for item in value:
                if isinstance(item, dict):
                    _clamp_negatives(item)


def _replace_nulls(data: dict[str, Any]) -> None:
    """Recursively replace JSON null values with type-safe defaults."""
    for key, value in list(data.items()):
        if value is None:
            data[key] = _null_default(key)
        elif isinstance(value, dict):
            _replace_nulls(value)
        elif isinstance(value, list):
            for i, item in enumerate(value):
                if item is None:
                    value[i] = {}
                elif isinstance(item, dict):
                    _replace_nulls(item)


def _null_default(key: str) -> object:
    """Guess a reasonable default for a null field by common name suffix."""
    if key.endswith("_ns") or key.endswith("_ms") or key == "predicted_gain_ns":
        return 0
    if key == "confidence" or key == "risk_score":
        return 0.0
    if key == "on_critical_path":
        return False
    return ""


def _fill_defaults(data: dict[str, Any], schema: dict[str, Any]) -> None:
    """Recursively fill missing required properties with type-safe defaults."""
    if "properties" not in schema:
        return
    for prop_name, prop_schema in schema["properties"].items():
        if prop_name not in data:
            if "default" in prop_schema:
                data[prop_name] = prop_schema["default"]
            elif prop_schema.get("type") == "string":
                data[prop_name] = ""
            elif prop_schema.get("type") == "array":
                data[prop_name] = []
            elif prop_schema.get("type") == "object":
                data[prop_name] = {}
            elif prop_schema.get("type") == "number" or prop_schema.get("type") == "integer":
                data[prop_name] = 0
            elif prop_schema.get("type") == "boolean":
                data[prop_name] = False
        # Recurse into nested objects and arrays
        if isinstance(data.get(prop_name), dict):
            _fill_defaults(data[prop_name], prop_schema)
        elif (
            isinstance(data.get(prop_name), list)
            and "items" in prop_schema
            and isinstance(prop_schema["items"], dict)
        ):
            for item in data[prop_name]:
                if isinstance(item, dict):
                    _fill_defaults(item, prop_schema["items"])


_FIELD_ALIASES = {
    "node_name": "node",
    "service_name": "node",
    "service": "node",
    "unit": "node",
    "blame_ms": "blame_ns",
    "duration_ns": "blame_ns",
    "duration_ms": "blame_ns",
    "slack_ms": "slack_ns",
}


def _normalize_field_aliases(data: dict[str, Any]) -> dict[str, Any]:
    """Rename known field-name aliases that small LLMs frequently produce.

    Operates recursively on nested dicts and lists of dicts.
    """
    if isinstance(data, dict):
        result = {}
        for key, value in data.items():
            new_key = _FIELD_ALIASES.get(key, key)
            result[new_key] = _normalize_field_aliases(value)
        return result
    if isinstance(data, list):
        return [_normalize_field_aliases(item) for item in data]
    return data
