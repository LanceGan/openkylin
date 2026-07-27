"""Unit tests for skill loader — TOML parsing, JSON Schema validation, output extraction."""

from __future__ import annotations

from pathlib import Path

import pytest

from kylinbootlab.agent.skills import load_skill, validate_output

SKILLS_DIR = Path("agent/skills")


# -- skill loading -------------------------------------------------------------


@pytest.mark.parametrize(
    "filename,expected_name",
    [
        ("trace-analyst.toml", "Trace Analyst"),
        ("source-investigator.toml", "Source Investigator"),
        ("experiment-designer.toml", "Experiment Designer"),
        ("safety-critic.toml", "Safety Critic"),
    ],
)
def test_load_skill_parses_toml(filename: str, expected_name: str) -> None:
    """Each of the four bundled TOML skills parses into a valid SkillConfig."""
    path = SKILLS_DIR / filename
    skill = load_skill(path)

    assert skill.name == expected_name
    assert len(skill.description) > 0
    assert len(skill.system_prompt) > 100
    assert isinstance(skill.output_schema, dict)
    assert "$schema" in skill.output_schema or "type" in skill.output_schema


def test_load_all_four_skills() -> None:
    """All four bundled TOML skill files load without error."""
    paths = [
        SKILLS_DIR / "trace-analyst.toml",
        SKILLS_DIR / "source-investigator.toml",
        SKILLS_DIR / "experiment-designer.toml",
        SKILLS_DIR / "safety-critic.toml",
    ]
    skills = [load_skill(p) for p in paths]
    assert len(skills) == 4
    assert all(isinstance(s.output_schema, dict) for s in skills)


def test_load_skill_rejects_invalid_json_schema() -> None:
    """A TOML with an invalid JSON Schema in output_schema.schema raises ValueError."""
    import tempfile

    with tempfile.NamedTemporaryFile(
        mode="w", suffix=".toml", delete=False, encoding="utf-8"
    ) as f:
        f.write("""\
[role]
name = "Bad"
description = "bad"

[prompt]
system = "x"

[output_schema]
description = "b"
schema = '''
{"type": "not-a-valid-type"}
'''
""")
        tmp_path = Path(f.name)

    try:
        with pytest.raises(ValueError, match="not a valid JSON Schema"):
            load_skill(tmp_path)
    finally:
        tmp_path.unlink()


def test_load_skill_rejects_bad_json_syntax() -> None:
    """A TOML with malformed JSON in output_schema.schema raises ValueError."""
    import tempfile

    with tempfile.NamedTemporaryFile(
        mode="w", suffix=".toml", delete=False, encoding="utf-8"
    ) as f:
        f.write("""\
[role]
name = "Bad"
description = "bad"

[prompt]
system = "x"

[output_schema]
description = "b"
schema = '''not json'''
""")
        tmp_path = Path(f.name)

    try:
        with pytest.raises(ValueError, match="not valid JSON"):
            load_skill(tmp_path)
    finally:
        tmp_path.unlink()


# -- validate_output -----------------------------------------------------------


def test_validate_output_extracts_from_json_fence() -> None:
    """validate_output extracts JSON from a ```json ... ``` fenced block."""
    schema = {
        "type": "object",
        "properties": {"name": {"type": "string"}},
        "required": ["name"],
        "additionalProperties": False,
    }
    text = """Here is my analysis:

```json
{"name": "test-node"}
```

Hope that helps!"""

    result = validate_output(text, schema)
    assert result == {"name": "test-node"}


def test_validate_output_extracts_from_bare_fence() -> None:
    """validate_output also extracts JSON from a bare ``` ... ``` block."""
    schema = {
        "type": "object",
        "properties": {"value": {"type": "integer"}},
        "required": ["value"],
        "additionalProperties": False,
    }
    text = """```
{"value": 42}
```"""

    result = validate_output(text, schema)
    assert result == {"value": 42}


def test_validate_output_rejects_no_json() -> None:
    """validate_output raises ValueError when no JSON can be found."""
    schema = {"type": "object", "additionalProperties": False}
    text = "This is just plain text, no JSON here."

    with pytest.raises(ValueError, match="Could not extract"):
        validate_output(text, schema)


def test_validate_output_rejects_schema_violation() -> None:
    """validate_output raises jsonschema.ValidationError for schema violations."""
    import jsonschema

    schema = {
        "type": "object",
        "properties": {"score": {"type": "number", "minimum": 0.0, "maximum": 1.0}},
        "required": ["score"],
        "additionalProperties": False,
    }
    text = '{"score": 99.0}'  # out of range

    with pytest.raises(jsonschema.ValidationError):
        validate_output(text, schema)


def test_validate_output_accepts_raw_json_text() -> None:
    """validate_output falls back to parsing the entire text as raw JSON."""
    schema = {
        "type": "object",
        "properties": {"ok": {"type": "boolean"}},
        "required": ["ok"],
        "additionalProperties": False,
    }
    text = '{"ok": true}'

    result = validate_output(text, schema)
    assert result == {"ok": True}


def test_validate_output_handles_newlines_in_fence() -> None:
    """validate_output handles JSON blocks with leading/trailing whitespace."""
    schema = {
        "type": "object",
        "properties": {"key": {"type": "string"}},
        "required": ["key"],
    }
    text = """```json

{"key": "value"}

```"""

    result = validate_output(text, schema)
    assert result == {"key": "value"}
