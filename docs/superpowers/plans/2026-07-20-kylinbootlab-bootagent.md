# KylinBootLab Phase 8: BootAgent Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended). Steps use checkbox syntax.

**Goal:** Build a constraint-based local LLM diagnostic system — a four-role sequential pipeline using Ollama + Qwen2.5-Coder-7B CPU inference, validated against a 5-case fault benchmark (≥60% accuracy).

**Architecture:** Python-only. Ollama HTTP API via `requests`. TOML-based skill configs. Prompt templates with pre-loaded data (no function-calling). BootAgent controller orchestrates the pipeline.

**Tech Stack:** Python 3.12, Pydantic 2, `requests`, `tomllib` (stdlib), Phase 4-6 data modules.

## Global Constraints

- Python 3.12+, Pydantic 2 strict, mypy strict, ruff clean.
- Agent NEVER executes shell commands. Only reads data and produces JSON.
- Ollama model: `qwen2.5-coder:7b-instruct-q4_k_m`.
- Temperature = 0.0 (deterministic).
- All agent output validates against JSON Schemas in TOML skill configs.
- Benchmark scoring: human-graded 0-1 per case. Pass ≥ 0.6 (3.0/5.0).

## File Map

```
agent/skills/                                      4 TOML skill configs
agent/benchmark/cases.json                         5 ground-truth cases
src/kylinbootlab/agent/__init__.py
src/kylinbootlab/agent/backend.py                  OllamaBackend (HTTP API)
src/kylinbootlab/agent/models.py                   5 Pydantic output models
src/kylinbootlab/agent/skills.py                   TOML loader + JSON Schema validator
src/kylinbootlab/agent/controller.py               BootAgent four-role pipeline
src/kylinbootlab/agent/benchmark.py                5-case benchmark evaluator
src/kylinbootlab/cli.py                            + kbl agent analyze/benchmark
tests/test_agent_backend.py
tests/test_agent_skills.py
tests/test_agent_controller.py
tests/test_agent_benchmark.py
```

## Scope and Exit Criteria

Implements spec `docs/superpowers/specs/2026-07-20-kylinbootlab-bootagent.md`. Complete when:

- `OllamaBackend.chat()` returns structured JSON from local model (mock-tested).
- All 4 skills load correctly; output validation rejects malformed JSON.
- `BootAgent.analyze(run_id)` produces `BootAgentReport` with four role outputs.
- 5-case benchmark accuracy ≥ 60%.
- `kbl agent analyze` and `kbl agent benchmark` CLI work.
- All gates pass: ruff, mypy strict, pytest.

---

### Task 1: OllamaBackend + Agent Models

**Files:** Create `src/kylinbootlab/agent/__init__.py`, `backend.py`, `models.py`, `skills.py`; `tests/test_agent_backend.py`, `tests/test_agent_skills.py`; 4 TOML files under `agent/skills/`.

**Interfaces:** Produces `OllamaBackend(model, base_url).chat(system, user, temp=0.0) -> str`; `TraceAnalysis`, `SourceReport`, `ExperimentPlan`, `SafetyReview`, `BootAgentReport` Pydantic models; `load_skill(path) -> SkillConfig`; `validate_output(text, schema) -> dict` (extracts JSON from markdown code blocks).

- [ ] Step 1: Write backend + models + skills + 4 TOML files following the spec §3.3 pattern. Each TOML has `[role]`, `[prompt]`, `[output_schema]` sections. The trace-analyst system prompt focuses on bottleneck anomalies and slack analysis. The source-investigator focuses on unit file inspection and actionable changes. The experiment-designer focuses on hypothesis formation and what-if design. The safety-critic focuses on risk assessment without veto power.
- [ ] Step 2: Tests — mock Ollama HTTP endpoint (5 tests), load all 4 skills (3 tests), validate_output edge cases (4 tests), model validation tests (6 tests).
- [ ] Step 3: Run `uv run pytest tests/test_agent_backend.py tests/test_agent_skills.py -v`. All pass.
- [ ] Step 4: Commit `feat: add OllamaBackend, agent models, skill loader, 4 TOML configs`

### Task 2: BootAgent Controller

**Files:** Create `src/kylinbootlab/agent/controller.py`, `tests/test_agent_controller.py`.

**Interfaces:** `BootAgent(backend, store).analyze(run_id) -> BootAgentReport`. Loads blame + DOT + readiness from RunStore, builds CausalGraph, runs bottlenecks, feeds data to each role, aggregates report. Each role failure → None for that section, doesn't abort pipeline.

- [ ] Step 1: Write controller.py with `_run_role()` helper that loads skill → calls backend.chat → validates output → returns model. `_gather_unit_info()` stub (returns {} for MVP).
- [ ] Step 2: Tests — mock backend returning valid JSON for each role (1 test), mock backend returning garbage → returns None for that role (1 test), pipeline produces report with partial data (1 test).
- [ ] Step 3: Run + commit `feat: add BootAgent four-role controller`

### Task 3: Benchmark + CLI

**Files:** Create `agent/benchmark/cases.json`, `src/kylinbootlab/agent/benchmark.py`; modify `src/kylinbootlab/cli.py`; create `tests/test_agent_benchmark.py`.

**Interfaces:** `BenchmarkCase.score(report) -> float` (structural proxy scoring: +0.3 anomalies present, +0.3 missed_bottlenecks present, +0.2 experiment plan, +0.2 safety review). `evaluate(report, cases) -> float`. `kbl agent analyze RUN_ID`, `kbl agent benchmark`.

- [ ] Step 1: Write cases.json (5 cases from Phase 4-6 real data). Write benchmark.py. Write CLI commands.
- [ ] Step 2: Tests — load cases (1 test), structural scoring (2 tests), CLI smoke (1 test).
- [ ] Step 3: Run + commit `feat: add benchmark evaluator + kbl agent CLI`

### Task 4: Real-Model Acceptance

- [ ] Step 1: Verify `ollama list | grep qwen2.5-coder` shows model.
- [ ] Step 2: Run `kbl agent analyze <VALID_RUN_ID>`. Verify JSON output with 4 roles.
- [ ] Step 3: Run `kbl agent benchmark`. Score manually for 5 cases. Record results.
- [ ] Step 4: Commit evidence to `docs/evidence/phase8/`.

### Task 5: Quality Gates

- [ ] `uv run pytest tests/ -q --ignore=tests/test_rust_contract.py` — all pass.
- [ ] `uv run ruff check . && uv run mypy src tests` — clean.
- [ ] No Phase 1-6 regression.
- [ ] Commit final state.
