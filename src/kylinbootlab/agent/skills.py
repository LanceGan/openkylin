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

    jsonschema.Draft202012Validator(json_schema).validate(data)
    return data
