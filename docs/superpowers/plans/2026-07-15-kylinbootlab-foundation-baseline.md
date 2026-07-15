# KylinBootLab Foundation and Baseline Capture MVP Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build the first end-to-end KylinBootLab slice: an openKylin target produces a checksummed boot snapshot, and the controller securely imports it, parses systemd timing, and generates a static baseline report.

**Architecture:** A Rust binary on the target captures low-overhead system metadata and systemd command output into a versioned bundle. A Python 3.12 CLI on the controller validates the same JSON contract, imports the bundle into an immutable run store, parses timing data, and renders JSON/HTML reports. SSH collection is a thin transport layer and does not bypass bundle validation.

**Tech Stack:** Python 3.12, uv, Pydantic 2, JSON Schema 2020-12, Typer, pytest, Jinja2, Rust 1.85.1, clap, serde, cargo test

---

## Scope and Exit Criteria

This plan implements Phase 1 from the program roadmap. It deliberately stops before automated power cycling, semantic graphical readiness, ftrace/eBPF, causal analysis, optimization, and BootAgent. Those features consume the stable bundle and run-store contracts established here.

Phase 1 is complete only when all of the following are true:

- `kbl-bootprobe snapshot` creates a valid manifest and captures systemd time, blame, critical chain, manager timestamps, and monotonic journal output on openKylin.
- Rust-produced JSON passes the Python model and generated JSON Schema.
- The controller rejects path traversal, missing files, size mismatches, checksum mismatches, duplicate runs, and unknown schema fields.
- `kbl collect` retrieves one real target run over SSH and imports it under `var/runs/<run_id>/raw/`.
- `kbl report` writes deterministic `metrics.json` and `baseline.html` outputs.
- Python and Rust quality commands pass on the controller; the target smoke command passes on openKylin.

Use the fixed target identity `kbl@kbl-target.local`. The target installer creates the constrained privileged wrapper `/usr/local/sbin/kbl-capture-run`; the controller never invokes the probe with an arbitrary privileged output path.

## File Map

```text
.cargo/config.toml                              Rust build output location
.github/workflows/ci.yml                        Windows/Linux quality workflow
.editorconfig                                   Shared editor defaults
.gitattributes                                  Stable text normalization
.gitignore                                      Local environments, builds, and run data
README.md                                       Phase-1 setup and command entry points
pyproject.toml                                  Python package, dependencies, and tool config
uv.lock                                         Resolved Python dependency lock
rust-toolchain.toml                             Pinned Rust toolchain
Cargo.toml                                      Rust workspace
Cargo.lock                                      Resolved Rust dependency lock
src/kylinbootlab/__init__.py                    Package version
src/kylinbootlab/cli.py                         Typer command boundary
src/kylinbootlab/contracts.py                   Pydantic persisted contracts
src/kylinbootlab/schema.py                      Packaged JSON Schema loader
src/kylinbootlab/store.py                       Immutable run importer
src/kylinbootlab/capture.py                     Captured-command document reader
src/kylinbootlab/systemd.py                     systemd timing and blame parser
src/kylinbootlab/report.py                      Derived metrics and static report writer
src/kylinbootlab/remote.py                      SSH/SCP transport
src/kylinbootlab/schemas/__init__.py            Schema package marker
src/kylinbootlab/schemas/probe-manifest-v1.schema.json
src/kylinbootlab/templates/baseline.html.j2     Static baseline report template
target/bootprobe/Cargo.toml                     Target probe crate dependencies
target/bootprobe/src/model.rs                    Rust persisted contract types
target/bootprobe/src/system.rs                   boot ID, clock, and host discovery
target/bootprobe/src/capture.rs                  Command capture and hashing
target/bootprobe/src/snapshot.rs                 Snapshot orchestration
target/bootprobe/src/lib.rs                      Probe library boundary
target/bootprobe/src/main.rs                     Probe CLI
target/bootprobe/tests/system_capture.rs         Cross-platform capture tests
target/bootprobe/tests/snapshot.rs               Snapshot orchestration tests
scripts/export_schema.py                         Deterministic schema generator
scripts/check.ps1                                Controller quality gate
scripts/target/install_bootprobe.sh              Constrained target installer
scripts/target/kbl-capture-run                   Privileged fixed-root wrapper
scripts/target/verify_foundation.sh              Target smoke verification
tests/__init__.py                                Test helper package marker
tests/fixtures/probe-manifest-v1.json            Cross-language contract fixture
tests/helpers.py                                 Valid temporary bundle builder
tests/test_cli.py                                CLI smoke and command tests
tests/test_contracts.py                          Contract and schema tests
tests/test_rust_contract.py                      Rust/Python parity test
tests/test_store.py                              Import integrity tests
tests/test_systemd.py                            Parser tests
tests/test_report.py                             Deterministic report tests
tests/test_remote.py                             SSH command construction tests
docs/runbooks/foundation-baseline.md             Exact controller/target procedure
```

### Task 1: Bootstrap the Monorepo and Python CLI

**Files:**
- Create: `.gitignore`
- Create: `.gitattributes`
- Create: `.editorconfig`
- Create: `.cargo/config.toml`
- Create: `rust-toolchain.toml`
- Create: `pyproject.toml`
- Create: `README.md`
- Create: `tests/test_cli.py`
- Create: `src/kylinbootlab/__init__.py`
- Create: `src/kylinbootlab/cli.py`

- [ ] **Step 1: Install and verify the pinned controller toolchains**

Run from an elevated PowerShell only for the two `winget` commands:

```powershell
winget install --id astral-sh.uv --exact
winget install --id Rustlang.Rustup --exact
```

Open a new non-elevated PowerShell, then run:

```powershell
uv python install 3.12
rustup toolchain install 1.85.1
uv --version
uv run --python 3.12 python --version
rustc +1.85.1 --version
```

Expected: `uv` prints a version, Python prints `3.12.x`, and Rust prints `rustc 1.85.1`. Do not use the controller's pre-existing Python 3.4.5.

- [ ] **Step 2: Add repository and tool configuration**

Create `.gitignore`:

```gitignore
.venv/
.cargo-target/
__pycache__/
*.py[cod]
.pytest_cache/
.ruff_cache/
.mypy_cache/
.coverage
htmlcov/
dist/
node_modules/
var/
```

Create `.gitattributes`:

```gitattributes
* text=auto
*.py text eol=lf
*.rs text eol=lf
*.toml text eol=lf
*.json text eol=lf
*.sh text eol=lf
*.md text eol=lf
*.ps1 text eol=crlf
```

Create `.editorconfig`:

```ini
root = true

[*]
charset = utf-8
end_of_line = lf
insert_final_newline = true
indent_style = space
indent_size = 4
trim_trailing_whitespace = true

[*.{json,toml,yml,yaml}]
indent_size = 2

[*.md]
trim_trailing_whitespace = false

[*.ps1]
end_of_line = crlf
```

Create `.cargo/config.toml`:

```toml
[build]
target-dir = ".cargo-target"
```

Create `rust-toolchain.toml`:

```toml
[toolchain]
channel = "1.85.1"
components = ["clippy", "rustfmt"]
profile = "minimal"
```

Create `pyproject.toml`:

```toml
[build-system]
requires = ["hatchling>=1.27,<2"]
build-backend = "hatchling.build"

[project]
name = "kylinbootlab"
version = "0.1.0"
description = "Reproducible Linux desktop boot analysis and optimization"
readme = "README.md"
requires-python = ">=3.12"
dependencies = [
  "jinja2>=3.1.5,<4",
  "jsonschema>=4.23,<5",
  "pydantic>=2.10,<3",
  "typer>=0.15,<1",
]

[dependency-groups]
dev = [
  "mypy>=1.14,<2",
  "pytest>=8.3,<9",
  "pytest-cov>=6,<7",
  "ruff>=0.9,<1",
]

[project.scripts]
kbl = "kylinbootlab.cli:app"

[tool.hatch.build.targets.wheel]
packages = ["src/kylinbootlab"]

[tool.pytest.ini_options]
addopts = "-q"
testpaths = ["tests"]

[tool.ruff]
line-length = 100
target-version = "py312"

[tool.ruff.lint]
select = ["E", "F", "I", "UP", "B", "SIM"]

[tool.mypy]
python_version = "3.12"
strict = true
packages = ["kylinbootlab"]
```

Create `README.md`:

```markdown
# KylinBootLab

KylinBootLab captures, validates, analyzes, and compares Linux desktop boot runs.

The first vertical slice consists of:

- `kbl-bootprobe` on the openKylin target;
- the `kbl` controller CLI;
- immutable run bundles and deterministic baseline reports.

See `docs/runbooks/foundation-baseline.md` for the target setup and first capture.
```

- [ ] **Step 3: Resolve the Python environment**

Run:

```powershell
uv sync --all-groups --python 3.12
```

Expected: uv creates `.venv`, resolves Python 3.12 dependencies, and writes `uv.lock`.

- [ ] **Step 4: Write the failing CLI test**

Create `tests/test_cli.py`:

```python
from typer.testing import CliRunner

from kylinbootlab.cli import app


runner = CliRunner()


def test_version_command_prints_package_version() -> None:
    result = runner.invoke(app, ["version"])

    assert result.exit_code == 0
    assert result.stdout == "0.1.0\n"
```

Run:

```powershell
uv run pytest tests/test_cli.py -v
```

Expected: FAIL with `ModuleNotFoundError: No module named 'kylinbootlab'`.

- [ ] **Step 5: Implement the minimal package and CLI**

Create `src/kylinbootlab/__init__.py`:

```python
__version__ = "0.1.0"
```

Create `src/kylinbootlab/cli.py`:

```python
import typer

from kylinbootlab import __version__


app = typer.Typer(no_args_is_help=True)


@app.command()
def version() -> None:
    """Print the KylinBootLab package version."""
    typer.echo(__version__)
```

- [ ] **Step 6: Run the CLI test and command**

Run:

```powershell
uv run pytest tests/test_cli.py -v
uv run kbl version
```

Expected: the test passes and the command prints `0.1.0`.

- [ ] **Step 7: Run Python static checks**

Run:

```powershell
uv run ruff check .
uv run mypy src tests
```

Expected: both commands exit 0.

- [ ] **Step 8: Commit the bootstrap**

```powershell
git add .gitignore .gitattributes .editorconfig .cargo/config.toml rust-toolchain.toml pyproject.toml uv.lock README.md src/kylinbootlab tests/test_cli.py
git commit -m "chore: bootstrap KylinBootLab workspace"
```

### Task 2: Define and Generate the Probe Manifest Contract

**Files:**
- Create: `src/kylinbootlab/contracts.py`
- Create: `src/kylinbootlab/schema.py`
- Create: `src/kylinbootlab/schemas/__init__.py`
- Create: `scripts/export_schema.py`
- Create: `tests/fixtures/probe-manifest-v1.json`
- Create: `tests/test_contracts.py`
- Generate: `src/kylinbootlab/schemas/probe-manifest-v1.schema.json`

- [ ] **Step 1: Write the valid cross-language fixture**

Create `tests/fixtures/probe-manifest-v1.json`:

```json
{
  "schema_version": 1,
  "run_id": "11111111-1111-4111-8111-111111111111",
  "boot_id": "22222222-2222-4222-8222-222222222222",
  "captured_at_utc": "2026-07-15T03:00:00Z",
  "boottime_ns": 123456789,
  "host": {
    "hostname": "kbl-target",
    "kernel_release": "6.6.0-openkylin",
    "os_id": "openkylin",
    "os_version_id": "2.0",
    "architecture": "x86_64"
  },
  "artifacts": [
    {
      "name": "systemd-time",
      "relative_path": "captures/systemd-time.json",
      "sha256": "0000000000000000000000000000000000000000000000000000000000000000",
      "size_bytes": 123,
      "command": ["systemd-analyze", "--no-pager", "time"],
      "exit_code": 0,
      "required": true
    }
  ]
}
```

- [ ] **Step 2: Write failing model and schema tests**

Create `tests/test_contracts.py`:

```python
import json
import subprocess
import sys
from importlib import resources
from pathlib import Path

import jsonschema
import pytest
from pydantic import ValidationError

from kylinbootlab.contracts import ProbeManifest


FIXTURE = Path("tests/fixtures/probe-manifest-v1.json")


def fixture_data() -> dict[str, object]:
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


def test_generated_schema_is_current() -> None:
    subprocess.run(
        [sys.executable, "scripts/export_schema.py", "--check"],
        check=True,
    )
```

Run:

```powershell
uv run pytest tests/test_contracts.py -v
```

Expected: FAIL because `kylinbootlab.contracts` does not exist.

- [ ] **Step 3: Implement strict persisted models**

Create `src/kylinbootlab/contracts.py`:

```python
from pathlib import PurePosixPath
from typing import Annotated, Literal, Self
from uuid import UUID

from pydantic import (
    AwareDatetime,
    BaseModel,
    ConfigDict,
    Field,
    NonNegativeInt,
    StringConstraints,
    field_validator,
    model_validator,
)


ArtifactName = Annotated[
    str,
    StringConstraints(pattern=r"^[a-z0-9][a-z0-9-]*$"),
]
Sha256 = Annotated[
    str,
    StringConstraints(pattern=r"^[0-9a-f]{64}$"),
]
Command = Annotated[list[str], Field(min_length=1)]


class ContractModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class HostInfo(ContractModel):
    hostname: Annotated[str, Field(min_length=1)]
    kernel_release: Annotated[str, Field(min_length=1)]
    os_id: Annotated[str, Field(min_length=1)]
    os_version_id: Annotated[str, Field(min_length=1)]
    architecture: Annotated[str, Field(min_length=1)]


class ArtifactRecord(ContractModel):
    name: ArtifactName
    relative_path: str
    sha256: Sha256
    size_bytes: NonNegativeInt
    command: Command
    exit_code: int
    required: bool

    @field_validator("relative_path")
    @classmethod
    def validate_relative_path(cls, value: str) -> str:
        parts = value.split("/")
        path = PurePosixPath(value)
        if (
            not value
            or path.is_absolute()
            or "\\" in value
            or any(part in {"", ".", ".."} for part in parts)
            or ":" in parts[0]
        ):
            raise ValueError("relative_path must be a normalized relative POSIX path")
        return value


class ProbeManifest(ContractModel):
    schema_version: Literal[1]
    run_id: UUID
    boot_id: UUID
    captured_at_utc: AwareDatetime
    boottime_ns: NonNegativeInt
    host: HostInfo
    artifacts: Annotated[list[ArtifactRecord], Field(min_length=1)]

    @model_validator(mode="after")
    def reject_duplicate_artifacts(self) -> Self:
        names = [artifact.name for artifact in self.artifacts]
        paths = [artifact.relative_path for artifact in self.artifacts]
        if len(names) != len(set(names)):
            raise ValueError("artifact names must be unique")
        if len(paths) != len(set(paths)):
            raise ValueError("artifact relative paths must be unique")
        return self
```

- [ ] **Step 4: Implement deterministic schema export and loading**

Create the empty package marker `src/kylinbootlab/schemas/__init__.py`.

Create `scripts/export_schema.py`:

```python
import argparse
import json
from pathlib import Path

from kylinbootlab.contracts import ProbeManifest


ROOT = Path(__file__).resolve().parents[1]
OUTPUT = ROOT / "src/kylinbootlab/schemas/probe-manifest-v1.schema.json"


def rendered_schema() -> str:
    schema = ProbeManifest.model_json_schema(mode="validation")
    schema["$schema"] = "https://json-schema.org/draft/2020-12/schema"
    schema["$id"] = "https://kylinbootlab.dev/schema/probe-manifest-v1.json"
    return json.dumps(schema, indent=2, sort_keys=True) + "\n"


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()
    expected = rendered_schema()

    if args.check:
        if not OUTPUT.exists() or OUTPUT.read_text(encoding="utf-8") != expected:
            raise SystemExit("probe manifest schema is stale; run scripts/export_schema.py")
        return 0

    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT.write_text(expected, encoding="utf-8", newline="\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
```

Create `src/kylinbootlab/schema.py`:

```python
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
```

Generate the schema:

```powershell
uv run python scripts/export_schema.py
```

Expected: `src/kylinbootlab/schemas/probe-manifest-v1.schema.json` is created.

- [ ] **Step 5: Run contract tests and static checks**

```powershell
uv run pytest tests/test_contracts.py -v
uv run ruff check src tests scripts
uv run mypy src tests
```

Expected: all commands exit 0.

- [ ] **Step 6: Commit the v1 contract**

```powershell
git add src/kylinbootlab/contracts.py src/kylinbootlab/schema.py src/kylinbootlab/schemas scripts/export_schema.py tests/fixtures tests/test_contracts.py
git commit -m "feat: define probe manifest contract"
```

### Task 3: Add Rust Contract Types and Cross-Language Parity

**Files:**
- Create: `Cargo.toml`
- Create: `target/bootprobe/Cargo.toml`
- Create: `target/bootprobe/src/lib.rs`
- Create: `target/bootprobe/src/model.rs`
- Create: `target/bootprobe/src/main.rs`
- Create: `tests/test_rust_contract.py`

- [ ] **Step 1: Write the failing Rust/Python parity test**

Create `tests/test_rust_contract.py`:

```python
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
```

Run:

```powershell
uv run pytest tests/test_rust_contract.py -v
```

Expected: FAIL because the Cargo workspace and `kbl-bootprobe` do not exist.

- [ ] **Step 2: Create the Rust workspace and crate manifests**

Create `Cargo.toml`:

```toml
[workspace]
resolver = "2"
members = ["target/bootprobe"]
```

Create `target/bootprobe/Cargo.toml`:

```toml
[package]
name = "kbl-bootprobe"
version = "0.1.0"
edition = "2024"
license = "Apache-2.0"

[dependencies]
anyhow = "1.0.95"
chrono = { version = "0.4.39", features = ["serde"] }
clap = { version = "4.5.27", features = ["derive"] }
serde = { version = "1.0.217", features = ["derive"] }
serde_json = "1.0.137"
uuid = { version = "1.12.1", features = ["serde", "v4"] }
```

- [ ] **Step 3: Implement the shared Rust model**

Create `target/bootprobe/src/model.rs`:

```rust
use chrono::{DateTime, Utc};
use serde::{Deserialize, Serialize};
use uuid::Uuid;

#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct HostInfo {
    pub hostname: String,
    pub kernel_release: String,
    pub os_id: String,
    pub os_version_id: String,
    pub architecture: String,
}

#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct ArtifactRecord {
    pub name: String,
    pub relative_path: String,
    pub sha256: String,
    pub size_bytes: u64,
    pub command: Vec<String>,
    pub exit_code: i32,
    pub required: bool,
}

#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct ProbeManifest {
    pub schema_version: u32,
    pub run_id: Uuid,
    pub boot_id: Uuid,
    pub captured_at_utc: DateTime<Utc>,
    pub boottime_ns: u64,
    pub host: HostInfo,
    pub artifacts: Vec<ArtifactRecord>,
}

pub fn contract_fixture() -> ProbeManifest {
    ProbeManifest {
        schema_version: 1,
        run_id: Uuid::parse_str("11111111-1111-4111-8111-111111111111").unwrap(),
        boot_id: Uuid::parse_str("22222222-2222-4222-8222-222222222222").unwrap(),
        captured_at_utc: DateTime::parse_from_rfc3339("2026-07-15T03:00:00Z")
            .unwrap()
            .with_timezone(&Utc),
        boottime_ns: 123_456_789,
        host: HostInfo {
            hostname: "kbl-target".to_owned(),
            kernel_release: "6.6.0-openkylin".to_owned(),
            os_id: "openkylin".to_owned(),
            os_version_id: "2.0".to_owned(),
            architecture: "x86_64".to_owned(),
        },
        artifacts: vec![ArtifactRecord {
            name: "systemd-time".to_owned(),
            relative_path: "captures/systemd-time.json".to_owned(),
            sha256: "0".repeat(64),
            size_bytes: 123,
            command: vec![
                "systemd-analyze".to_owned(),
                "--no-pager".to_owned(),
                "time".to_owned(),
            ],
            exit_code: 0,
            required: true,
        }],
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn fixture_round_trips_without_unknown_fields() {
        let fixture = contract_fixture();
        let encoded = serde_json::to_string(&fixture).unwrap();
        let decoded: ProbeManifest = serde_json::from_str(&encoded).unwrap();

        assert_eq!(decoded, fixture);
        assert_eq!(decoded.schema_version, 1);
    }
}
```

Create `target/bootprobe/src/lib.rs`:

```rust
pub mod model;
```

Create `target/bootprobe/src/main.rs`:

```rust
use anyhow::Result;
use clap::{Parser, Subcommand};
use kbl_bootprobe::model::contract_fixture;

#[derive(Debug, Parser)]
#[command(name = "kbl-bootprobe", version)]
struct Cli {
    #[command(subcommand)]
    command: Command,
}

#[derive(Debug, Subcommand)]
enum Command {
    ContractFixture,
}

fn main() -> Result<()> {
    let cli = Cli::parse();
    match cli.command {
        Command::ContractFixture => {
            println!("{}", serde_json::to_string_pretty(&contract_fixture())?);
        }
    }
    Ok(())
}
```

- [ ] **Step 4: Run Rust tests and cross-language validation**

```powershell
cargo fmt --all
cargo test --workspace
uv run pytest tests/test_rust_contract.py -v
```

Expected: Rust tests pass and Python validates the Rust fixture.

- [ ] **Step 5: Run Rust lints**

```powershell
cargo fmt --all -- --check
cargo clippy --workspace --all-targets -- -D warnings
```

Expected: both commands exit 0.

- [ ] **Step 6: Commit Rust/Python contract parity**

```powershell
git add Cargo.toml Cargo.lock target/bootprobe tests/test_rust_contract.py
git commit -m "feat: add Rust probe contract types"
```

### Task 4: Capture Host State and Command Artifacts

**Files:**
- Modify: `target/bootprobe/Cargo.toml`
- Modify: `target/bootprobe/src/lib.rs`
- Create: `target/bootprobe/src/system.rs`
- Create: `target/bootprobe/src/capture.rs`
- Create: `target/bootprobe/tests/system_capture.rs`

- [ ] **Step 1: Write failing cross-platform capture tests**

Create `target/bootprobe/tests/system_capture.rs`:

```rust
use kbl_bootprobe::capture::{run_command, write_command_capture};
use kbl_bootprobe::system::parse_os_release;
use tempfile::tempdir;

#[test]
fn parses_required_os_release_fields() {
    let values = parse_os_release(
        r#"
NAME="openKylin"
ID=openkylin
VERSION_ID="2.0"
"#,
    );

    assert_eq!(values.get("ID").unwrap(), "openkylin");
    assert_eq!(values.get("VERSION_ID").unwrap(), "2.0");
}

#[test]
fn writes_a_hashed_command_capture() {
    #[cfg(target_os = "windows")]
    let (program, args) = ("cmd", vec!["/C", "echo", "captured"]);
    #[cfg(not(target_os = "windows"))]
    let (program, args) = ("sh", vec!["-c", "printf captured"]);

    let document = run_command(program, &args);
    let directory = tempdir().unwrap();
    let artifact = write_command_capture(directory.path(), "example", true, &document).unwrap();

    assert_eq!(document.exit_code, 0);
    assert!(document.stdout.contains("captured"));
    assert_eq!(artifact.name, "example");
    assert_eq!(artifact.sha256.len(), 64);
    assert!(directory.path().join(artifact.relative_path).is_file());
}
```

Temporarily add these declarations to `target/bootprobe/src/lib.rs` below `pub mod model;`:

```rust
pub mod capture;
pub mod system;
```

Run:

```powershell
cargo test -p kbl-bootprobe --test system_capture
```

Expected: FAIL because `capture.rs` and `system.rs` do not exist.

- [ ] **Step 2: Add hashing, clock, and test dependencies**

Replace `target/bootprobe/Cargo.toml` with:

```toml
[package]
name = "kbl-bootprobe"
version = "0.1.0"
edition = "2024"
license = "Apache-2.0"

[dependencies]
anyhow = "1.0.95"
chrono = { version = "0.4.39", features = ["serde"] }
clap = { version = "4.5.27", features = ["derive"] }
hex = "0.4.3"
serde = { version = "1.0.217", features = ["derive"] }
serde_json = "1.0.137"
sha2 = "0.10.8"
uuid = { version = "1.12.1", features = ["serde", "v4"] }

[target.'cfg(target_os = "linux")'.dependencies]
nix = { version = "0.29.0", features = ["time"] }

[dev-dependencies]
tempfile = "3.15.0"
```

- [ ] **Step 3: Implement system discovery**

Create `target/bootprobe/src/system.rs`:

```rust
use std::collections::BTreeMap;
use std::fs;
use std::path::Path;
#[cfg(target_os = "linux")]
use std::process::Command;

use anyhow::{Context, Result, anyhow};
use uuid::Uuid;

use crate::model::HostInfo;

pub fn parse_os_release(input: &str) -> BTreeMap<String, String> {
    input
        .lines()
        .filter_map(|line| {
            let line = line.trim();
            if line.is_empty() || line.starts_with('#') {
                return None;
            }
            let (key, raw_value) = line.split_once('=')?;
            let value = raw_value.trim();
            let unquoted = if value.len() >= 2
                && ((value.starts_with('"') && value.ends_with('"'))
                    || (value.starts_with('\'') && value.ends_with('\'')))
            {
                &value[1..value.len() - 1]
            } else {
                value
            };
            Some((key.to_owned(), unquoted.to_owned()))
        })
        .collect()
}

#[cfg(target_os = "linux")]
fn command_stdout(program: &str, args: &[&str]) -> Result<String> {
    let output = Command::new(program)
        .args(args)
        .env("LC_ALL", "C")
        .output()
        .with_context(|| format!("failed to execute {program}"))?;
    if !output.status.success() {
        anyhow::bail!(
            "{program} failed: {}",
            String::from_utf8_lossy(&output.stderr).trim()
        );
    }
    Ok(String::from_utf8(output.stdout)?.trim().to_owned())
}

pub fn read_boot_id(path: &Path) -> Result<Uuid> {
    let value = fs::read_to_string(path)
        .with_context(|| format!("failed to read {}", path.display()))?;
    Uuid::parse_str(value.trim()).context("invalid Linux boot_id")
}

#[cfg(target_os = "linux")]
pub fn boottime_ns() -> Result<u64> {
    use nix::time::{ClockId, clock_gettime};

    let value = clock_gettime(ClockId::CLOCK_BOOTTIME)?;
    let seconds = u64::try_from(value.tv_sec()).context("negative CLOCK_BOOTTIME seconds")?;
    let nanoseconds = u64::try_from(value.tv_nsec()).context("negative nanoseconds")?;
    Ok(seconds * 1_000_000_000 + nanoseconds)
}

#[cfg(not(target_os = "linux"))]
pub fn boottime_ns() -> Result<u64> {
    Err(anyhow!("CLOCK_BOOTTIME capture is supported only on Linux"))
}

#[cfg(target_os = "linux")]
pub fn current_host_info() -> Result<HostInfo> {
    let os_release = fs::read_to_string("/etc/os-release")
        .context("failed to read /etc/os-release")?;
    let values = parse_os_release(&os_release);
    let required = |key: &str| {
        values
            .get(key)
            .cloned()
            .ok_or_else(|| anyhow!("/etc/os-release is missing {key}"))
    };

    Ok(HostInfo {
        hostname: fs::read_to_string("/etc/hostname")
            .context("failed to read /etc/hostname")?
            .trim()
            .to_owned(),
        kernel_release: command_stdout("uname", &["-r"])?,
        os_id: required("ID")?,
        os_version_id: required("VERSION_ID")?,
        architecture: command_stdout("uname", &["-m"])?,
    })
}

#[cfg(not(target_os = "linux"))]
pub fn current_host_info() -> Result<HostInfo> {
    Err(anyhow!("live host discovery is supported only on Linux"))
}
```

- [ ] **Step 4: Implement command capture and hashing**

Create `target/bootprobe/src/capture.rs`:

```rust
use std::fs;
use std::path::Path;
use std::process::Command;

use anyhow::{Context, Result, bail};
use serde::{Deserialize, Serialize};
use sha2::{Digest, Sha256};

use crate::model::ArtifactRecord;

#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct CommandCapture {
    pub command: Vec<String>,
    pub exit_code: i32,
    pub stdout: String,
    pub stderr: String,
}

pub fn run_command(program: &str, args: &[&str]) -> CommandCapture {
    let command = std::iter::once(program.to_owned())
        .chain(args.iter().map(|value| (*value).to_owned()))
        .collect();

    match Command::new(program)
        .args(args)
        .env("LC_ALL", "C")
        .output()
    {
        Ok(output) => CommandCapture {
            command,
            exit_code: output.status.code().unwrap_or(-1),
            stdout: String::from_utf8_lossy(&output.stdout).into_owned(),
            stderr: String::from_utf8_lossy(&output.stderr).into_owned(),
        },
        Err(error) => CommandCapture {
            command,
            exit_code: 127,
            stdout: String::new(),
            stderr: error.to_string(),
        },
    }
}

pub fn write_command_capture(
    root: &Path,
    name: &str,
    required: bool,
    capture: &CommandCapture,
) -> Result<ArtifactRecord> {
    let mut characters = name.chars();
    let valid_start = characters
        .next()
        .is_some_and(|character| character.is_ascii_lowercase() || character.is_ascii_digit());
    let valid_rest = characters.all(|character| {
        character.is_ascii_lowercase() || character.is_ascii_digit() || character == '-'
    });
    if !valid_start || !valid_rest {
        bail!("invalid artifact name: {name}");
    }

    let relative_path = format!("captures/{name}.json");
    let output_path = root.join(&relative_path);
    let parent = output_path.parent().context("capture path has no parent")?;
    fs::create_dir_all(parent)?;

    let mut encoded = serde_json::to_vec_pretty(capture)?;
    encoded.push(b'\n');
    fs::write(&output_path, &encoded)
        .with_context(|| format!("failed to write {}", output_path.display()))?;

    Ok(ArtifactRecord {
        name: name.to_owned(),
        relative_path,
        sha256: hex::encode(Sha256::digest(&encoded)),
        size_bytes: u64::try_from(encoded.len())?,
        command: capture.command.clone(),
        exit_code: capture.exit_code,
        required,
    })
}
```

Ensure `target/bootprobe/src/lib.rs` is:

```rust
pub mod capture;
pub mod model;
pub mod system;
```

- [ ] **Step 5: Run capture tests and lints**

```powershell
cargo fmt --all
cargo test -p kbl-bootprobe --test system_capture
cargo clippy --workspace --all-targets -- -D warnings
```

Expected: all commands exit 0 on Windows. Live clock and host functions compile but are not executed there.

- [ ] **Step 6: Commit target capture primitives**

```powershell
git add target/bootprobe Cargo.lock
git commit -m "feat: add target capture primitives"
```

### Task 5: Implement the Live Snapshot Command

**Files:**
- Modify: `target/bootprobe/src/lib.rs`
- Modify: `target/bootprobe/src/main.rs`
- Create: `target/bootprobe/src/snapshot.rs`
- Create: `target/bootprobe/tests/snapshot.rs`

- [ ] **Step 1: Write failing snapshot tests**

Create `target/bootprobe/tests/snapshot.rs`:

```rust
use chrono::{TimeZone, Utc};
use kbl_bootprobe::model::HostInfo;
use kbl_bootprobe::snapshot::{CaptureSpec, SnapshotContext, capture_snapshot};
use tempfile::tempdir;
use uuid::Uuid;

fn echo_spec(required: bool) -> CaptureSpec {
    #[cfg(target_os = "windows")]
    let command = vec!["cmd", "/C", "echo", "snapshot"];
    #[cfg(not(target_os = "windows"))]
    let command = vec!["sh", "-c", "printf snapshot"];

    CaptureSpec {
        name: "systemd-time",
        command: command.into_iter().map(str::to_owned).collect(),
        required,
    }
}

fn context() -> SnapshotContext {
    SnapshotContext {
        boot_id: Uuid::parse_str("22222222-2222-4222-8222-222222222222").unwrap(),
        captured_at_utc: Utc.with_ymd_and_hms(2026, 7, 15, 3, 0, 0).unwrap(),
        boottime_ns: 123_456_789,
        host: HostInfo {
            hostname: "kbl-target".to_owned(),
            kernel_release: "6.6.0-openkylin".to_owned(),
            os_id: "openkylin".to_owned(),
            os_version_id: "2.0".to_owned(),
            architecture: "x86_64".to_owned(),
        },
    }
}

#[test]
fn snapshot_writes_manifest_and_artifacts() {
    let root = tempdir().unwrap();
    let output = root.path().join("run");
    let run_id = Uuid::parse_str("11111111-1111-4111-8111-111111111111").unwrap();

    let manifest = capture_snapshot(&output, run_id, context(), &[echo_spec(true)]).unwrap();

    assert_eq!(manifest.run_id, run_id);
    assert_eq!(manifest.artifacts.len(), 1);
    assert!(output.join("probe-manifest.json").is_file());
    assert!(output.join("captures/systemd-time.json").is_file());
}

#[test]
fn snapshot_refuses_a_nonempty_output_directory() {
    let root = tempdir().unwrap();
    std::fs::write(root.path().join("existing"), "data").unwrap();

    let error = capture_snapshot(
        root.path(),
        Uuid::new_v4(),
        context(),
        &[echo_spec(true)],
    )
    .unwrap_err();

    assert!(error.to_string().contains("not empty"));
}
```

Add `pub mod snapshot;` to `target/bootprobe/src/lib.rs`, then run:

```powershell
cargo test -p kbl-bootprobe --test snapshot
```

Expected: FAIL because `snapshot.rs` does not exist.

- [ ] **Step 2: Implement snapshot orchestration and default captures**

Create `target/bootprobe/src/snapshot.rs`:

```rust
use std::fs;
use std::path::Path;

use anyhow::{Context, Result, bail};
use chrono::{DateTime, Utc};
use uuid::Uuid;

use crate::capture::{run_command, write_command_capture};
use crate::model::{HostInfo, ProbeManifest};
use crate::system::{boottime_ns, current_host_info, read_boot_id};

#[derive(Debug, Clone)]
pub struct CaptureSpec {
    pub name: &'static str,
    pub command: Vec<String>,
    pub required: bool,
}

#[derive(Debug, Clone)]
pub struct SnapshotContext {
    pub boot_id: Uuid,
    pub captured_at_utc: DateTime<Utc>,
    pub boottime_ns: u64,
    pub host: HostInfo,
}

pub fn default_capture_specs() -> Vec<CaptureSpec> {
    vec![
        CaptureSpec {
            name: "systemd-time",
            command: words(&["systemd-analyze", "--no-pager", "time"]),
            required: true,
        },
        CaptureSpec {
            name: "systemd-blame",
            command: words(&["systemd-analyze", "--no-pager", "blame"]),
            required: true,
        },
        CaptureSpec {
            name: "systemd-critical-chain",
            command: words(&["systemd-analyze", "--no-pager", "critical-chain"]),
            required: false,
        },
        CaptureSpec {
            name: "systemd-manager",
            command: words(&[
                "systemctl",
                "--no-pager",
                "show",
                "--property=KernelTimestampMonotonic",
                "--property=InitRDTimestampMonotonic",
                "--property=UserspaceTimestampMonotonic",
                "--property=FinishTimestampMonotonic",
            ]),
            required: false,
        },
        CaptureSpec {
            name: "journal-monotonic",
            command: words(&[
                "journalctl",
                "--boot=0",
                "--output=short-monotonic",
                "--no-pager",
            ]),
            required: false,
        },
    ]
}

fn words(values: &[&str]) -> Vec<String> {
    values.iter().map(|value| (*value).to_owned()).collect()
}

pub fn live_context() -> Result<SnapshotContext> {
    Ok(SnapshotContext {
        boot_id: read_boot_id(Path::new("/proc/sys/kernel/random/boot_id"))?,
        captured_at_utc: Utc::now(),
        boottime_ns: boottime_ns()?,
        host: current_host_info()?,
    })
}

pub fn capture_snapshot(
    output: &Path,
    run_id: Uuid,
    context: SnapshotContext,
    specs: &[CaptureSpec],
) -> Result<ProbeManifest> {
    if output.exists() && fs::read_dir(output)?.next().is_some() {
        bail!("snapshot output directory is not empty: {}", output.display());
    }
    fs::create_dir_all(output)?;

    let mut artifacts = Vec::with_capacity(specs.len());
    for spec in specs {
        let (program, args) = spec
            .command
            .split_first()
            .context("capture command must not be empty")?;
        let args: Vec<&str> = args.iter().map(String::as_str).collect();
        let capture = run_command(program, &args);
        artifacts.push(write_command_capture(
            output,
            spec.name,
            spec.required,
            &capture,
        )?);
    }

    let manifest = ProbeManifest {
        schema_version: 1,
        run_id,
        boot_id: context.boot_id,
        captured_at_utc: context.captured_at_utc,
        boottime_ns: context.boottime_ns,
        host: context.host,
        artifacts,
    };

    let manifest_path = output.join("probe-manifest.json");
    let mut encoded = serde_json::to_vec_pretty(&manifest)?;
    encoded.push(b'\n');
    fs::write(&manifest_path, encoded)
        .with_context(|| format!("failed to write {}", manifest_path.display()))?;

    let failed: Vec<&str> = manifest
        .artifacts
        .iter()
        .filter(|artifact| artifact.required && artifact.exit_code != 0)
        .map(|artifact| artifact.name.as_str())
        .collect();
    if !failed.is_empty() {
        bail!("required captures failed: {}", failed.join(", "));
    }

    Ok(manifest)
}
```

- [ ] **Step 3: Expose the live snapshot CLI**

Replace `target/bootprobe/src/lib.rs` with:

```rust
pub mod capture;
pub mod model;
pub mod snapshot;
pub mod system;
```

Replace `target/bootprobe/src/main.rs` with:

```rust
use std::path::PathBuf;

use anyhow::Result;
use clap::{Parser, Subcommand};
use kbl_bootprobe::model::contract_fixture;
use kbl_bootprobe::snapshot::{capture_snapshot, default_capture_specs, live_context};
use uuid::Uuid;

#[derive(Debug, Parser)]
#[command(name = "kbl-bootprobe", version)]
struct Cli {
    #[command(subcommand)]
    command: Command,
}

#[derive(Debug, Subcommand)]
enum Command {
    ContractFixture,
    Snapshot {
        #[arg(long)]
        run_id: Uuid,
        #[arg(long)]
        output: PathBuf,
    },
}

fn main() -> Result<()> {
    let cli = Cli::parse();
    match cli.command {
        Command::ContractFixture => {
            println!("{}", serde_json::to_string_pretty(&contract_fixture())?);
        }
        Command::Snapshot { run_id, output } => {
            let manifest = capture_snapshot(
                &output,
                run_id,
                live_context()?,
                &default_capture_specs(),
            )?;
            println!("{}", manifest.run_id);
        }
    }
    Ok(())
}
```

- [ ] **Step 4: Run snapshot tests and CLI help**

```powershell
cargo fmt --all
cargo test --workspace
cargo run --quiet -p kbl-bootprobe -- --help
cargo clippy --workspace --all-targets -- -D warnings
```

Expected: all tests pass; help lists `contract-fixture` and `snapshot`; clippy exits 0.

- [ ] **Step 5: Commit the snapshot command**

```powershell
git add target/bootprobe Cargo.lock
git commit -m "feat: capture target boot snapshot"
```

### Task 6: Build the Immutable Run Store

**Files:**
- Create: `tests/helpers.py`
- Create: `tests/test_store.py`
- Create: `src/kylinbootlab/store.py`

- [ ] **Step 1: Add a valid temporary bundle builder**

Create `tests/helpers.py`:

```python
import hashlib
import json
from datetime import UTC, datetime
from pathlib import Path
from typing import TypedDict
from uuid import UUID

from kylinbootlab.contracts import ArtifactRecord, HostInfo, ProbeManifest


RUN_ID = UUID("11111111-1111-4111-8111-111111111111")
BOOT_ID = UUID("22222222-2222-4222-8222-222222222222")


class CaptureFixture(TypedDict):
    command: list[str]
    exit_code: int
    stdout: str
    stderr: str


CAPTURES: dict[str, CaptureFixture] = {
    "systemd-time": {
        "command": ["systemd-analyze", "--no-pager", "time"],
        "exit_code": 0,
        "stdout": (
            "Startup finished in 1.000s (kernel) + 2.000s (userspace) = 3.000s\n"
            "graphical.target reached after 1.500s in userspace.\n"
        ),
        "stderr": "",
    },
    "systemd-blame": {
        "command": ["systemd-analyze", "--no-pager", "blame"],
        "exit_code": 0,
        "stdout": "900ms NetworkManager.service\n250ms dbus.service\n",
        "stderr": "",
    },
}


def create_probe_bundle(root: Path, run_id: UUID = RUN_ID) -> Path:
    bundle = root / "bundle"
    captures = bundle / "captures"
    captures.mkdir(parents=True)
    artifacts: list[ArtifactRecord] = []

    for name, document in CAPTURES.items():
        encoded = (json.dumps(document, indent=2, sort_keys=True) + "\n").encode()
        relative_path = f"captures/{name}.json"
        (bundle / relative_path).write_bytes(encoded)
        artifacts.append(
            ArtifactRecord(
                name=name,
                relative_path=relative_path,
                sha256=hashlib.sha256(encoded).hexdigest(),
                size_bytes=len(encoded),
                command=document["command"],
                exit_code=document["exit_code"],
                required=True,
            )
        )

    manifest = ProbeManifest(
        schema_version=1,
        run_id=run_id,
        boot_id=BOOT_ID,
        captured_at_utc=datetime(2026, 7, 15, 3, 0, tzinfo=UTC),
        boottime_ns=3_100_000_000,
        host=HostInfo(
            hostname="kbl-target",
            kernel_release="6.6.0-openkylin",
            os_id="openkylin",
            os_version_id="2.0",
            architecture="x86_64",
        ),
        artifacts=artifacts,
    )
    (bundle / "probe-manifest.json").write_text(
        manifest.model_dump_json(indent=2) + "\n",
        encoding="utf-8",
        newline="\n",
    )
    return bundle
```

- [ ] **Step 2: Write failing integrity and atomicity tests**

Create `tests/test_store.py`:

```python
from pathlib import Path

import pytest

from kylinbootlab.store import BundleError, RunStore
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
```

Run:

```powershell
uv run pytest tests/test_store.py -v
```

Expected: FAIL because `kylinbootlab.store` does not exist.

- [ ] **Step 3: Implement strict manifest loading and immutable import**

Create `src/kylinbootlab/store.py`:

```python
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
            os.replace(incoming, destination)
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
```

- [ ] **Step 4: Make the tests package importable**

Create an empty `tests/__init__.py`, then run:

```powershell
uv run pytest tests/test_store.py -v
uv run ruff check src tests
uv run mypy src tests
```

Expected: all tests and checks pass.

- [ ] **Step 5: Commit the immutable store**

```powershell
git add src/kylinbootlab/store.py tests/__init__.py tests/helpers.py tests/test_store.py
git commit -m "feat: add immutable run store"
```

### Task 7: Parse systemd Timing and Unit Blame

**Files:**
- Create: `src/kylinbootlab/capture.py`
- Create: `src/kylinbootlab/systemd.py`
- Create: `tests/test_systemd.py`

- [ ] **Step 1: Write failing duration, timing, and blame tests**

Create `tests/test_systemd.py`:

```python
from uuid import UUID

import pytest

from kylinbootlab.systemd import (
    parse_duration_ns,
    parse_systemd_blame,
    parse_systemd_time,
)


RUN_ID = UUID("11111111-1111-4111-8111-111111111111")


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        ("500ms", 500_000_000),
        ("1.250s", 1_250_000_000),
        ("1min 2.500s", 62_500_000_000),
        ("250us", 250_000),
    ],
)
def test_parse_duration_ns(value: str, expected: int) -> None:
    assert parse_duration_ns(value) == expected


def test_parse_systemd_time_excludes_firmware_and_loader() -> None:
    output = (
        "Startup finished in 2.000s (firmware) + 1.000s (loader) + "
        "3.000s (kernel) + 500ms (initrd) + 4.000s (userspace) = 10.500s\n"
        "graphical.target reached after 3.250s in userspace.\n"
    )

    metrics = parse_systemd_time(RUN_ID, output)

    assert metrics.kernel_ns == 3_000_000_000
    assert metrics.initrd_ns == 500_000_000
    assert metrics.userspace_ns == 4_000_000_000
    assert metrics.os_total_ns == 7_500_000_000
    assert metrics.graphical_target_from_t0_ns == 6_750_000_000


def test_parse_systemd_blame_ranks_units() -> None:
    units = parse_systemd_blame(
        "1min 2.500s slow.service\n900ms NetworkManager.service\n250ms dbus.service\n"
    )

    assert [unit.unit for unit in units] == [
        "slow.service",
        "NetworkManager.service",
        "dbus.service",
    ]
    assert units[0].rank == 1
    assert units[0].duration_ns == 62_500_000_000


def test_parse_duration_rejects_unknown_text() -> None:
    with pytest.raises(ValueError, match="invalid systemd duration"):
        parse_duration_ns("about one second")
```

Run:

```powershell
uv run pytest tests/test_systemd.py -v
```

Expected: FAIL because `kylinbootlab.systemd` does not exist.

- [ ] **Step 2: Implement captured-command document validation**

Create `src/kylinbootlab/capture.py`:

```python
from pathlib import Path

from kylinbootlab.contracts import ArtifactRecord, Command, ContractModel, ProbeManifest
from kylinbootlab.store import BundleError, artifact_path


class CommandCapture(ContractModel):
    command: Command
    exit_code: int
    stdout: str
    stderr: str


def find_artifact(manifest: ProbeManifest, name: str) -> ArtifactRecord:
    matches = [artifact for artifact in manifest.artifacts if artifact.name == name]
    if len(matches) != 1:
        raise BundleError(f"expected one artifact named {name}, found {len(matches)}")
    return matches[0]


def load_command_capture(run_path: Path, manifest: ProbeManifest, name: str) -> CommandCapture:
    artifact = find_artifact(manifest, name)
    path = artifact_path(run_path / "raw", artifact.relative_path)
    capture = CommandCapture.model_validate_json(path.read_text(encoding="utf-8"))
    if capture.command != artifact.command or capture.exit_code != artifact.exit_code:
        raise BundleError(f"capture metadata disagrees with manifest for {name}")
    if capture.exit_code != 0 and artifact.required:
        raise BundleError(f"required capture failed for {name}: {capture.stderr.strip()}")
    return capture
```

- [ ] **Step 3: Implement exact systemd duration and timing parsing**

Create `src/kylinbootlab/systemd.py`:

```python
import re
from decimal import Decimal
from typing import Literal
from uuid import UUID

from pydantic import NonNegativeInt

from kylinbootlab.contracts import ContractModel


_TOKEN = re.compile(r"(?P<value>\d+(?:\.\d+)?)(?P<unit>min|ms|us|s)")
_PHASE = re.compile(r"^(?P<duration>.+?) \((?P<phase>[^)]+)\)$")
_BLAME = re.compile(
    r"^\s*(?P<duration>(?:\d+(?:\.\d+)?(?:min|ms|us|s)\s*)+)\s+"
    r"(?P<unit>\S+)\s*$"
)
_FACTORS = {
    "min": Decimal(60_000_000_000),
    "s": Decimal(1_000_000_000),
    "ms": Decimal(1_000_000),
    "us": Decimal(1_000),
}


class BootMetrics(ContractModel):
    schema_version: Literal[1] = 1
    run_id: UUID
    kernel_ns: NonNegativeInt
    initrd_ns: NonNegativeInt
    userspace_ns: NonNegativeInt
    os_total_ns: NonNegativeInt
    graphical_target_from_t0_ns: NonNegativeInt | None


class UnitTiming(ContractModel):
    rank: int
    unit: str
    duration_ns: NonNegativeInt


def parse_duration_ns(text: str) -> int:
    total = Decimal(0)
    consumed: list[tuple[int, int]] = []
    for match in _TOKEN.finditer(text):
        total += Decimal(match.group("value")) * _FACTORS[match.group("unit")]
        consumed.append(match.span())

    remainder = list(text)
    for start, end in consumed:
        remainder[start:end] = " " * (end - start)
    if not consumed or "".join(remainder).strip():
        raise ValueError(f"invalid systemd duration: {text}")
    return int(total)


def parse_systemd_time(run_id: UUID, output: str) -> BootMetrics:
    startup = next(
        (line for line in output.splitlines() if line.startswith("Startup finished in ")),
        None,
    )
    if startup is None:
        raise ValueError("systemd-analyze output has no startup line")

    phase_text = startup.removeprefix("Startup finished in ").split(" = ", maxsplit=1)[0]
    phases: dict[str, int] = {}
    for segment in phase_text.split(" + "):
        match = _PHASE.fullmatch(segment.strip())
        if match is None:
            raise ValueError(f"invalid systemd startup phase: {segment}")
        phases[match.group("phase")] = parse_duration_ns(match.group("duration"))

    if "kernel" not in phases or "userspace" not in phases:
        raise ValueError("systemd startup output must contain kernel and userspace phases")
    initrd_ns = phases.get("initrd", 0)
    pre_userspace_ns = phases["kernel"] + initrd_ns

    graphical_target_ns: int | None = None
    graphical = re.search(
        r"^graphical\.target reached after (?P<duration>.+?) in userspace\.$",
        output,
        flags=re.MULTILINE,
    )
    if graphical is not None:
        graphical_target_ns = pre_userspace_ns + parse_duration_ns(graphical.group("duration"))

    return BootMetrics(
        run_id=run_id,
        kernel_ns=phases["kernel"],
        initrd_ns=initrd_ns,
        userspace_ns=phases["userspace"],
        os_total_ns=pre_userspace_ns + phases["userspace"],
        graphical_target_from_t0_ns=graphical_target_ns,
    )


def parse_systemd_blame(output: str) -> list[UnitTiming]:
    parsed: list[tuple[str, int]] = []
    for line in output.splitlines():
        if not line.strip():
            continue
        match = _BLAME.fullmatch(line)
        if match is None:
            raise ValueError(f"invalid systemd blame line: {line}")
        parsed.append((match.group("unit"), parse_duration_ns(match.group("duration"))))

    parsed.sort(key=lambda item: item[1], reverse=True)
    return [
        UnitTiming(rank=index, unit=unit, duration_ns=duration_ns)
        for index, (unit, duration_ns) in enumerate(parsed, start=1)
    ]
```

- [ ] **Step 4: Run parser tests and static checks**

```powershell
uv run pytest tests/test_systemd.py -v
uv run ruff check src tests
uv run mypy src tests
```

Expected: all tests and checks pass.

- [ ] **Step 5: Commit deterministic systemd parsing**

```powershell
git add src/kylinbootlab/capture.py src/kylinbootlab/systemd.py tests/test_systemd.py
git commit -m "feat: parse systemd baseline metrics"
```

### Task 8: Generate Deterministic Baseline Reports

**Files:**
- Modify: `src/kylinbootlab/cli.py`
- Create: `src/kylinbootlab/report.py`
- Create: `src/kylinbootlab/templates/baseline.html.j2`
- Create: `tests/test_report.py`
- Modify: `tests/test_cli.py`

- [ ] **Step 1: Write failing report tests**

Create `tests/test_report.py`:

```python
import json
from pathlib import Path

from kylinbootlab.report import write_baseline_report
from kylinbootlab.store import RunStore
from tests.helpers import RUN_ID, create_probe_bundle


def test_report_writes_metrics_and_html_deterministically(tmp_path: Path) -> None:
    store = RunStore(tmp_path / "runs")
    store.ingest(create_probe_bundle(tmp_path / "source"))

    first = write_baseline_report(store, RUN_ID)
    first_json = first.metrics_json.read_bytes()
    first_html = first.html.read_bytes()
    second = write_baseline_report(store, RUN_ID)

    metrics = json.loads(first.metrics_json.read_text(encoding="utf-8"))
    assert metrics["boot"]["os_total_ns"] == 3_000_000_000
    assert metrics["units"][0]["unit"] == "NetworkManager.service"
    assert "KylinBootLab Baseline" in first.html.read_text(encoding="utf-8")
    assert second.metrics_json.read_bytes() == first_json
    assert second.html.read_bytes() == first_html
```

Replace `tests/test_cli.py` with the complete final file so imports remain at the top:

```python
from pathlib import Path

from typer.testing import CliRunner

from kylinbootlab.cli import app
from tests.helpers import RUN_ID, create_probe_bundle


runner = CliRunner()


def test_version_command_prints_package_version() -> None:
    result = runner.invoke(app, ["version"])

    assert result.exit_code == 0
    assert result.stdout == "0.1.0\n"


def test_ingest_and_report_commands(tmp_path: Path) -> None:
    bundle = create_probe_bundle(tmp_path / "source")
    data_root = tmp_path / "runs"

    ingest_result = runner.invoke(
        app,
        ["ingest", str(bundle), "--data-root", str(data_root)],
    )
    report_result = runner.invoke(
        app,
        ["report", str(RUN_ID), "--data-root", str(data_root)],
    )

    assert ingest_result.exit_code == 0
    assert str(RUN_ID) in ingest_result.stdout
    assert report_result.exit_code == 0
    assert (data_root / str(RUN_ID) / "reports/baseline.html").is_file()
```

Run:

```powershell
uv run pytest tests/test_report.py tests/test_cli.py -v
```

Expected: FAIL because `kylinbootlab.report` and the new CLI commands do not exist.

- [ ] **Step 2: Implement run analysis and deterministic output**

Create `src/kylinbootlab/report.py`:

```python
import json
from dataclasses import dataclass
from importlib import resources
from pathlib import Path
from uuid import UUID

from jinja2 import Environment, StrictUndefined, select_autoescape

from kylinbootlab.capture import load_command_capture
from kylinbootlab.store import RunStore
from kylinbootlab.systemd import BootMetrics, UnitTiming, parse_systemd_blame, parse_systemd_time


@dataclass(frozen=True)
class ReportPaths:
    metrics_json: Path
    html: Path


def analyze_run(store: RunStore, run_id: UUID) -> tuple[BootMetrics, list[UnitTiming]]:
    run_path = store.run_path(run_id)
    manifest = store.load_manifest(run_id)
    timing = load_command_capture(run_path, manifest, "systemd-time")
    blame = load_command_capture(run_path, manifest, "systemd-blame")
    return (
        parse_systemd_time(run_id, timing.stdout),
        parse_systemd_blame(blame.stdout),
    )


def seconds(nanoseconds: int | None) -> str:
    if nanoseconds is None:
        return "not reported"
    return f"{nanoseconds / 1_000_000_000:.3f} s"


def write_baseline_report(store: RunStore, run_id: UUID) -> ReportPaths:
    run_path = store.run_path(run_id)
    manifest = store.load_manifest(run_id)
    boot, units = analyze_run(store, run_id)
    derived = run_path / "derived"
    reports = run_path / "reports"
    derived.mkdir(exist_ok=True)
    reports.mkdir(exist_ok=True)

    payload = {
        "schema_version": 1,
        "run_id": str(run_id),
        "boot_id": str(manifest.boot_id),
        "host": manifest.host.model_dump(mode="json"),
        "boot": boot.model_dump(mode="json"),
        "units": [unit.model_dump(mode="json") for unit in units],
    }
    metrics_path = derived / "metrics.json"
    metrics_path.write_text(
        json.dumps(payload, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
        newline="\n",
    )

    template_text = (
        resources.files("kylinbootlab")
        .joinpath("templates")
        .joinpath("baseline.html.j2")
        .read_text(encoding="utf-8")
    )
    environment = Environment(
        autoescape=select_autoescape(default=True),
        undefined=StrictUndefined,
    )
    template = environment.from_string(template_text)
    html_path = reports / "baseline.html"
    html_path.write_text(
        template.render(
            run_id=str(run_id),
            boot_id=str(manifest.boot_id),
            hostname=manifest.host.hostname,
            os_name=f"{manifest.host.os_id} {manifest.host.os_version_id}",
            kernel=manifest.host.kernel_release,
            kernel_time=seconds(boot.kernel_ns),
            initrd_time=seconds(boot.initrd_ns),
            userspace_time=seconds(boot.userspace_ns),
            total_time=seconds(boot.os_total_ns),
            graphical_time=seconds(boot.graphical_target_from_t0_ns),
            units=[
                {"rank": unit.rank, "name": unit.unit, "duration": seconds(unit.duration_ns)}
                for unit in units[:20]
            ],
        )
        + "\n",
        encoding="utf-8",
        newline="\n",
    )
    return ReportPaths(metrics_json=metrics_path, html=html_path)
```

- [ ] **Step 3: Add the static HTML template**

Create `src/kylinbootlab/templates/baseline.html.j2`:

```html
<!doctype html>
<html lang="en">
  <head>
    <meta charset="utf-8">
    <meta name="viewport" content="width=device-width, initial-scale=1">
    <title>KylinBootLab Baseline {{ run_id }}</title>
    <style>
      :root { color-scheme: light; font-family: Georgia, "Times New Roman", serif; }
      body { margin: 0; background: #f4f5f2; color: #1d2421; }
      main { width: min(960px, calc(100% - 32px)); margin: 32px auto; }
      h1, h2 { letter-spacing: 0; }
      h1 { margin-bottom: 8px; font-size: 32px; }
      .meta { color: #52605a; overflow-wrap: anywhere; }
      .metrics { display: grid; grid-template-columns: repeat(auto-fit, minmax(150px, 1fr)); border-block: 1px solid #aeb7b1; }
      .metric { padding: 16px 12px; }
      .metric strong { display: block; margin-top: 6px; font-size: 22px; }
      table { width: 100%; border-collapse: collapse; font-family: Consolas, monospace; font-size: 14px; }
      th, td { padding: 9px 8px; border-bottom: 1px solid #ccd2ce; text-align: left; }
      th:first-child, td:first-child { width: 56px; }
      @media (max-width: 520px) { main { margin-top: 20px; } h1 { font-size: 26px; } }
    </style>
  </head>
  <body>
    <main>
      <h1>KylinBootLab Baseline</h1>
      <p class="meta">Run {{ run_id }} · Boot {{ boot_id }}</p>
      <p class="meta">{{ hostname }} · {{ os_name }} · {{ kernel }}</p>
      <section class="metrics" aria-label="Boot timing">
        <div class="metric">Kernel<strong>{{ kernel_time }}</strong></div>
        <div class="metric">Initrd<strong>{{ initrd_time }}</strong></div>
        <div class="metric">Userspace<strong>{{ userspace_time }}</strong></div>
        <div class="metric">OS total<strong>{{ total_time }}</strong></div>
        <div class="metric">Graphical target<strong>{{ graphical_time }}</strong></div>
      </section>
      <h2>Longest systemd units</h2>
      <table>
        <thead><tr><th>Rank</th><th>Unit</th><th>Duration</th></tr></thead>
        <tbody>
          {% for unit in units %}
          <tr><td>{{ unit.rank }}</td><td>{{ unit.name }}</td><td>{{ unit.duration }}</td></tr>
          {% endfor %}
        </tbody>
      </table>
    </main>
  </body>
</html>
```

- [ ] **Step 4: Expose ingest and report commands**

Replace `src/kylinbootlab/cli.py` with:

```python
from pathlib import Path
from typing import Annotated
from uuid import UUID

import typer

from kylinbootlab import __version__
from kylinbootlab.report import write_baseline_report
from kylinbootlab.store import RunStore


app = typer.Typer(no_args_is_help=True)
DataRoot = Annotated[Path, typer.Option(help="Immutable KylinBootLab run root")]


@app.command()
def version() -> None:
    """Print the KylinBootLab package version."""
    typer.echo(__version__)


@app.command()
def ingest(bundle: Path, data_root: DataRoot = Path("var/runs")) -> None:
    """Validate and import a target probe bundle."""
    run_path = RunStore(data_root).ingest(bundle)
    typer.echo(run_path.name)


@app.command()
def report(run_id: UUID, data_root: DataRoot = Path("var/runs")) -> None:
    """Generate deterministic baseline metrics and HTML."""
    paths = write_baseline_report(RunStore(data_root), run_id)
    typer.echo(paths.html)
```

- [ ] **Step 5: Run report and CLI tests**

```powershell
uv run pytest tests/test_report.py tests/test_cli.py -v
uv run ruff check src tests
uv run mypy src tests
```

Expected: all tests and checks pass.

- [ ] **Step 6: Commit baseline reporting**

```powershell
git add src/kylinbootlab/cli.py src/kylinbootlab/report.py src/kylinbootlab/templates tests/test_cli.py tests/test_report.py
git commit -m "feat: generate baseline boot report"
```

### Task 9: Install the Probe Safely on openKylin

**Files:**
- Create: `scripts/target/kbl-capture-run`
- Create: `scripts/target/install_bootprobe.sh`
- Create: `scripts/target/verify_foundation.sh`
- Create: `docs/runbooks/foundation-baseline.md`

- [ ] **Step 1: Create the constrained privileged wrapper**

Create `scripts/target/kbl-capture-run`:

```bash
#!/usr/bin/env bash
set -euo pipefail

readonly uuid_pattern='^[0-9a-f]{8}-[0-9a-f]{4}-[1-5][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$'

if [[ $# -ne 1 || ! "$1" =~ $uuid_pattern ]]; then
  printf 'usage: kbl-capture-run UUID\n' >&2
  exit 64
fi

readonly run_id="$1"
readonly output="/var/lib/kylinbootlab/runs/${run_id}"
if [[ -e "$output" ]]; then
  printf 'run output already exists: %s\n' "$output" >&2
  exit 73
fi

umask 0027
exec /usr/local/bin/kbl-bootprobe snapshot --run-id "$run_id" --output "$output"
```

The wrapper accepts exactly one RFC 4122 UUID and constructs the privileged path itself. It never accepts an output path from SSH.

- [ ] **Step 2: Create the idempotent target installer**

Create `scripts/target/install_bootprobe.sh`:

```bash
#!/usr/bin/env bash
set -euo pipefail

if [[ $EUID -ne 0 || $# -ne 2 ]]; then
  printf 'usage: sudo install_bootprobe.sh BINARY TARGET_USER\n' >&2
  exit 64
fi

readonly binary="$1"
readonly target_user="$2"
readonly script_dir="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"

if [[ ! -x "$binary" ]]; then
  printf 'probe binary is not executable: %s\n' "$binary" >&2
  exit 66
fi
if ! id "$target_user" >/dev/null 2>&1; then
  printf 'target user does not exist: %s\n' "$target_user" >&2
  exit 67
fi

getent group kbl >/dev/null 2>&1 || groupadd --system kbl
usermod --append --groups kbl "$target_user"
install -o root -g root -m 0755 "$binary" /usr/local/bin/kbl-bootprobe
install -o root -g root -m 0755 "$script_dir/kbl-capture-run" /usr/local/sbin/kbl-capture-run
install -d -o root -g kbl -m 2750 /var/lib/kylinbootlab
install -d -o root -g kbl -m 2750 /var/lib/kylinbootlab/runs

sudoers_temp="$(mktemp)"
trap 'rm -f "$sudoers_temp"' EXIT
printf '%s ALL=(root) NOPASSWD: /usr/local/sbin/kbl-capture-run *\n' "$target_user" \
  >"$sudoers_temp"
chmod 0440 "$sudoers_temp"
visudo -cf "$sudoers_temp"
install -o root -g root -m 0440 "$sudoers_temp" /etc/sudoers.d/kylinbootlab

printf 'installed kbl-bootprobe for %s; log out and back in to refresh group membership\n' \
  "$target_user"
```

- [ ] **Step 3: Create a target-side smoke verifier**

Create `scripts/target/verify_foundation.sh`:

```bash
#!/usr/bin/env bash
set -euo pipefail

run_id="$(cat /proc/sys/kernel/random/uuid)"
sudo /usr/local/sbin/kbl-capture-run "$run_id"
manifest="/var/lib/kylinbootlab/runs/${run_id}/probe-manifest.json"

python3 - "$manifest" "$run_id" <<'PY'
import json
import pathlib
import sys

manifest_path = pathlib.Path(sys.argv[1])
expected_run_id = sys.argv[2]
manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
assert manifest["schema_version"] == 1
assert manifest["run_id"] == expected_run_id
artifacts = {item["name"]: item for item in manifest["artifacts"]}
assert artifacts["systemd-time"]["exit_code"] == 0
assert artifacts["systemd-blame"]["exit_code"] == 0
for artifact in artifacts.values():
    assert (manifest_path.parent / artifact["relative_path"]).is_file()
print(expected_run_id)
PY
```

- [ ] **Step 4: Write the exact target setup runbook**

Create `docs/runbooks/foundation-baseline.md`:

````markdown
# Foundation Baseline Runbook

## 1. Install openKylin

Install the current official stable openKylin standard image on the dedicated SSD. During installation create the account `kbl`, use the default graphical desktop, and keep Secure Boot and storage settings unchanged after the first baseline. Set the hostname at the physical console:

```bash
sudo hostnamectl set-hostname kbl-target
sudo apt-get update
sudo apt-get install -y avahi-daemon build-essential curl openssh-server python3
sudo systemctl enable --now avahi-daemon ssh
```

Record the ISO hash on the Windows controller:

```powershell
$iso = Get-ChildItem "$HOME\Downloads" -File |
    Where-Object { $_.Name -match '^openKylin.*\.iso$' } |
    Sort-Object LastWriteTime -Descending |
    Select-Object -First 1
if ($null -eq $iso) { throw "No openKylin ISO found in Downloads" }
Get-FileHash -Algorithm SHA256 $iso.FullName
```

Record the installed platform facts on the target:

```bash
cat /etc/os-release
uname -a
systemd --version
```

Store that output in the experiment notebook associated with the first real run. Do not update packages during one A/B block.

## 2. Configure controller SSH authentication

On the Windows controller, create a default key only when one does not exist:

```powershell
if (-not (Test-Path "$HOME\.ssh\id_ed25519")) {
    ssh-keygen -t ed25519 -f "$HOME\.ssh\id_ed25519" -N ''
}
scp "$HOME\.ssh\id_ed25519.pub" kbl@kbl-target.local:/tmp/controller.pub
```

At the target console:

```bash
install -d -m 0700 "$HOME/.ssh"
touch "$HOME/.ssh/authorized_keys"
grep -qxF "$(cat /tmp/controller.pub)" "$HOME/.ssh/authorized_keys" || \
  cat /tmp/controller.pub >>"$HOME/.ssh/authorized_keys"
chmod 0600 "$HOME/.ssh/authorized_keys"
rm /tmp/controller.pub
```

Back on the controller:

```powershell
ssh -o BatchMode=yes kbl@kbl-target.local true
```

Expected: exit code 0 without a password prompt.

## 3. Build and install the target probe

Copy the Rust workspace from the controller:

```powershell
ssh kbl@kbl-target.local "mkdir -p ~/KylinBootLab/.cargo ~/KylinBootLab/target ~/KylinBootLab/scripts"
scp Cargo.toml Cargo.lock rust-toolchain.toml kbl@kbl-target.local:KylinBootLab/
scp .cargo/config.toml kbl@kbl-target.local:KylinBootLab/.cargo/
scp -r target/bootprobe kbl@kbl-target.local:KylinBootLab/target/
scp -r scripts/target kbl@kbl-target.local:KylinBootLab/scripts/
```

Build and install at the target console:

```bash
curl --proto '=https' --tlsv1.2 -sSf https://sh.rustup.rs | \
  sh -s -- -y --default-toolchain 1.85.1 --profile minimal
source "$HOME/.cargo/env"
cd "$HOME/KylinBootLab"
cargo test --workspace
cargo build --release -p kbl-bootprobe
chmod +x scripts/target/*.sh scripts/target/kbl-capture-run
sudo scripts/target/install_bootprobe.sh .cargo-target/release/kbl-bootprobe kbl
```

Log out and back in, then verify:

```bash
cd "$HOME/KylinBootLab"
bash -n scripts/target/install_bootprobe.sh
bash -n scripts/target/kbl-capture-run
bash -n scripts/target/verify_foundation.sh
scripts/target/verify_foundation.sh
```

Expected: the final command prints one UUID and all required capture exit codes are zero.

## 4. Controller smoke capture

Once Task 10 is complete, capture the command output directly into a PowerShell variable:

```powershell
$runId = (uv run kbl collect --target kbl@kbl-target.local --data-root var/runs --incoming-root var/incoming).Trim()
uv run kbl report $runId --data-root var/runs
Test-Path "var/runs/$runId/derived/metrics.json"
Test-Path "var/runs/$runId/reports/baseline.html"
```

Both `Test-Path` commands must print `True`.
````

- [ ] **Step 5: Validate scripts on openKylin**

Run on the target from the repository root:

```bash
bash -n scripts/target/install_bootprobe.sh
bash -n scripts/target/kbl-capture-run
bash -n scripts/target/verify_foundation.sh
scripts/target/verify_foundation.sh
```

Expected: syntax checks exit 0; smoke verification prints a UUID whose bundle contains successful `systemd-time` and `systemd-blame` artifacts.

- [ ] **Step 6: Commit target installation and runbook**

```powershell
git add scripts/target docs/runbooks/foundation-baseline.md
git commit -m "docs: add safe target probe setup"
```

### Task 10: Collect and Import a Target Run over SSH

**Files:**
- Create: `src/kylinbootlab/remote.py`
- Modify: `src/kylinbootlab/cli.py`
- Create: `tests/test_remote.py`

- [ ] **Step 1: Write failing transport command and collection tests**

Create `tests/test_remote.py`:

```python
import shutil
import subprocess
from collections.abc import Sequence
from pathlib import Path

import pytest

from kylinbootlab.remote import (
    RemoteCollectionError,
    collect_target_run,
    scp_command,
    ssh_snapshot_command,
)
from kylinbootlab.store import RunStore
from tests.helpers import RUN_ID, create_probe_bundle


class FakeRunner:
    def __init__(
        self,
        bundle: Path,
        *,
        snapshot_returncode: int = 0,
        scp_returncode: int = 0,
    ) -> None:
        self.bundle = bundle
        self.snapshot_returncode = snapshot_returncode
        self.scp_returncode = scp_returncode
        self.calls: list[list[str]] = []

    def run(self, args: Sequence[str]) -> subprocess.CompletedProcess[str]:
        command = list(args)
        self.calls.append(command)
        if command[0] == "scp":
            if self.scp_returncode == 0:
                incoming_root = Path(command[-1])
                shutil.copytree(self.bundle, incoming_root / str(RUN_ID))
            return subprocess.CompletedProcess(
                command,
                self.scp_returncode,
                stdout="",
                stderr="copy failed" if self.scp_returncode else "",
            )
        return subprocess.CompletedProcess(
            command,
            self.snapshot_returncode,
            stdout="",
            stderr="capture failed" if self.snapshot_returncode else "",
        )


def test_transport_commands_are_noninteractive_and_fixed_path() -> None:
    assert ssh_snapshot_command("kbl@kbl-target.local", RUN_ID) == [
        "ssh",
        "-o",
        "BatchMode=yes",
        "kbl@kbl-target.local",
        "sudo",
        "/usr/local/sbin/kbl-capture-run",
        str(RUN_ID),
    ]
    assert scp_command("kbl@kbl-target.local", RUN_ID, Path("incoming")) == [
        "scp",
        "-o",
        "BatchMode=yes",
        "-r",
        f"kbl@kbl-target.local:/var/lib/kylinbootlab/runs/{RUN_ID}",
        "incoming",
    ]


def test_collect_transports_then_imports_bundle(tmp_path: Path) -> None:
    bundle = create_probe_bundle(tmp_path / "remote", run_id=RUN_ID)
    runner = FakeRunner(bundle)
    store = RunStore(tmp_path / "runs")

    run_path = collect_target_run(
        target="kbl@kbl-target.local",
        run_id=RUN_ID,
        incoming_root=tmp_path / "incoming",
        store=store,
        runner=runner,
    )

    assert run_path == store.run_path(RUN_ID)
    assert [call[0] for call in runner.calls] == ["ssh", "scp"]


def test_snapshot_failure_imports_diagnostics_then_raises(tmp_path: Path) -> None:
    bundle = create_probe_bundle(tmp_path / "remote", run_id=RUN_ID)
    runner = FakeRunner(bundle, snapshot_returncode=1)
    store = RunStore(tmp_path / "runs")

    with pytest.raises(RemoteCollectionError, match="diagnostic bundle was imported"):
        collect_target_run(
            target="kbl@kbl-target.local",
            run_id=RUN_ID,
            incoming_root=tmp_path / "incoming",
            store=store,
            runner=runner,
        )

    assert store.run_path(RUN_ID).is_dir()


def test_scp_failure_does_not_create_a_stored_run(tmp_path: Path) -> None:
    bundle = create_probe_bundle(tmp_path / "remote", run_id=RUN_ID)
    runner = FakeRunner(bundle, scp_returncode=1)
    store = RunStore(tmp_path / "runs")

    with pytest.raises(RemoteCollectionError, match="scp failed"):
        collect_target_run(
            target="kbl@kbl-target.local",
            run_id=RUN_ID,
            incoming_root=tmp_path / "incoming",
            store=store,
            runner=runner,
        )

    assert not store.run_path(RUN_ID).exists()
```

Run:

```powershell
uv run pytest tests/test_remote.py -v
```

Expected: FAIL because `kylinbootlab.remote` does not exist.

- [ ] **Step 2: Implement explicit SSH/SCP transport**

Create `src/kylinbootlab/remote.py`:

```python
import subprocess
from collections.abc import Sequence
from pathlib import Path
from typing import Protocol
from uuid import UUID

from kylinbootlab.store import RunStore


class RemoteCollectionError(RuntimeError):
    pass


class Runner(Protocol):
    def run(self, args: Sequence[str]) -> subprocess.CompletedProcess[str]: ...


class SubprocessRunner:
    def run(self, args: Sequence[str]) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            list(args),
            check=False,
            capture_output=True,
            text=True,
        )


def ssh_snapshot_command(target: str, run_id: UUID) -> list[str]:
    return [
        "ssh",
        "-o",
        "BatchMode=yes",
        target,
        "sudo",
        "/usr/local/sbin/kbl-capture-run",
        str(run_id),
    ]


def scp_command(target: str, run_id: UUID, incoming_root: Path) -> list[str]:
    return [
        "scp",
        "-o",
        "BatchMode=yes",
        "-r",
        f"{target}:/var/lib/kylinbootlab/runs/{run_id}",
        str(incoming_root),
    ]


def collect_target_run(
    *,
    target: str,
    run_id: UUID,
    incoming_root: Path,
    store: RunStore,
    runner: Runner,
) -> Path:
    incoming_root.mkdir(parents=True, exist_ok=True)
    bundle = incoming_root / str(run_id)
    if bundle.exists():
        raise RemoteCollectionError(f"incoming bundle already exists: {bundle}")

    snapshot = runner.run(ssh_snapshot_command(target, run_id))
    copied = runner.run(scp_command(target, run_id, incoming_root))
    if copied.returncode != 0:
        raise RemoteCollectionError(f"scp failed: {copied.stderr.strip()}")

    run_path = store.ingest(bundle)
    if snapshot.returncode != 0:
        raise RemoteCollectionError(
            f"target snapshot failed but diagnostic bundle was imported at {run_path}: "
            f"{snapshot.stderr.strip()}"
        )
    return run_path
```

- [ ] **Step 3: Expose the collect command**

Add these imports to `src/kylinbootlab/cli.py`:

```python
from uuid import UUID, uuid4

from kylinbootlab.remote import SubprocessRunner, collect_target_run
```

Replace the existing `from uuid import UUID` import rather than adding a duplicate. Append this command:

```python
@app.command()
def collect(
    target: Annotated[str, typer.Option(help="SSH destination")]
    = "kbl@kbl-target.local",
    data_root: DataRoot = Path("var/runs"),
    incoming_root: Annotated[Path, typer.Option(help="Untrusted incoming bundle root")]
    = Path("var/incoming"),
) -> None:
    """Capture, retrieve, validate, and import one target boot."""
    run_id = uuid4()
    run_path = collect_target_run(
        target=target,
        run_id=run_id,
        incoming_root=incoming_root,
        store=RunStore(data_root),
        runner=SubprocessRunner(),
    )
    typer.echo(run_path.name)
```

- [ ] **Step 4: Run transport tests and checks**

```powershell
uv run pytest tests/test_remote.py tests/test_cli.py -v
uv run ruff check src tests
uv run mypy src tests
```

Expected: all tests and checks pass.

- [ ] **Step 5: Run one real SSH collection**

Run from the controller after completing Task 9:

```powershell
$runId = (uv run kbl collect --target kbl@kbl-target.local --data-root var/runs --incoming-root var/incoming).Trim()
Test-Path "var/runs/$runId/manifest.json"
```

Expected: `$runId` contains one UUID, `Test-Path` prints `True`, and the stored manifest identifies the real openKylin host with successful required artifacts.

- [ ] **Step 6: Commit remote collection**

```powershell
git add src/kylinbootlab/remote.py src/kylinbootlab/cli.py tests/test_remote.py
git commit -m "feat: collect target snapshots over SSH"
```

### Task 11: Add Quality Gates and Complete the Real-Target Acceptance

**Files:**
- Modify: `tests/test_contracts.py`
- Modify: `tests/test_store.py`
- Create: `scripts/check.ps1`
- Create: `.github/workflows/ci.yml`

- [ ] **Step 1: Add the remaining negative contract and bundle tests**

Append to `tests/test_contracts.py`:

```python
def test_probe_manifest_rejects_unknown_field() -> None:
    data = fixture_data()
    data["untrusted"] = True

    with pytest.raises(ValidationError, match="untrusted"):
        ProbeManifest.model_validate(data)
```

Append to `tests/test_store.py`:

```python
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
```

Run:

```powershell
uv run pytest tests/test_contracts.py tests/test_store.py -v
```

Expected: all negative tests pass. The test modifies only the manifest size field, so the importer reaches the explicit size check.

- [ ] **Step 2: Add the complete local quality script**

Create `scripts/check.ps1`:

```powershell
$ErrorActionPreference = "Stop"

uv run python scripts/export_schema.py --check
uv run ruff format --check .
uv run ruff check .
uv run mypy src tests
uv run pytest --cov=kylinbootlab --cov-report=term-missing
cargo fmt --all -- --check
cargo clippy --workspace --all-targets -- -D warnings
cargo test --workspace
git diff --check
```

Run:

```powershell
uv run ruff format .
cargo fmt --all
powershell -ExecutionPolicy Bypass -File scripts/check.ps1
```

Expected: every command exits 0. Review formatting changes before staging them.

- [ ] **Step 3: Add Windows/Linux continuous integration**

Create `.github/workflows/ci.yml`:

```yaml
name: ci

on:
  push:
  pull_request:

jobs:
  quality:
    strategy:
      fail-fast: false
      matrix:
        os: [ubuntu-24.04, windows-latest]
    runs-on: ${{ matrix.os }}
    steps:
      - uses: actions/checkout@v4
      - uses: astral-sh/setup-uv@v5
        with:
          python-version: "3.12"
          enable-cache: true
      - uses: actions-rust-lang/setup-rust-toolchain@v1
        with:
          toolchain: "1.85.1"
          components: rustfmt, clippy
      - run: uv sync --all-groups --frozen
      - run: uv run python scripts/export_schema.py --check
      - run: uv run ruff format --check .
      - run: uv run ruff check .
      - run: uv run mypy src tests
      - run: uv run pytest --cov=kylinbootlab --cov-report=term-missing
      - run: cargo fmt --all -- --check
      - run: cargo clippy --workspace --all-targets -- -D warnings
      - run: cargo test --workspace
```

Expected: both jobs pass. Linux-only live snapshot behavior remains covered by the real-target acceptance below; CI does not pretend a hosted runner is openKylin.

- [ ] **Step 4: Execute the real openKylin target acceptance**

On the target:

```bash
cd "$HOME/KylinBootLab"
scripts/target/verify_foundation.sh
```

On the controller:

```powershell
$runId = (uv run kbl collect --target kbl@kbl-target.local --data-root var/runs --incoming-root var/incoming).Trim()
uv run kbl report $runId --data-root var/runs
$metrics = Get-Content -Raw "var/runs/$runId/derived/metrics.json" | ConvertFrom-Json
$metrics.run_id
$metrics.host.os_id
$metrics.boot.os_total_ns
Test-Path "var/runs/$runId/reports/baseline.html"
```

Expected: printed run ID equals `$runId`, OS ID is `openkylin`, total time is a positive integer, and `Test-Path` prints `True`.

- [ ] **Step 5: Verify the phase exit criteria from a clean checkout**

Run on the controller:

```powershell
git status --short
powershell -ExecutionPolicy Bypass -File scripts/check.ps1
uv run kbl version
```

Expected: before staging Task 11, `git status` lists only intended Task 11 files; all checks pass; version prints `0.1.0`. Raw files under `var/` do not appear because they are ignored.

- [ ] **Step 6: Commit the Phase 1 quality gate**

```powershell
git add .github/workflows/ci.yml scripts/check.ps1 tests/test_contracts.py tests/test_store.py
git commit -m "test: add foundation quality gates"
```

- [ ] **Step 7: Record the exact Phase 1 commit and start Phase 2 planning**

Run:

```powershell
git log --oneline --decorate -11
git status --short
```

Expected: eleven focused implementation commits follow the approved design/plan commits, and the worktree contains no generated build or run data. Use the real target manifest, openKylin version, systemd version, NIC Wake-on-LAN capability, watchdog availability, and disk layout as evidence when authoring `docs/superpowers/plans/2026-07-15-kylinbootlab-testbed-recovery.md`.
