# KylinBootLab Phase 2: Automated Cold-Boot Testbed and Recovery

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build an automated cold-boot experiment loop — the controller queues experiments, powers the target on/off via VIX (VM) or WOL (bare-metal), waits for SSH readiness, triggers Phase 1 collection, recovers from failures, and repeats until the queue drains.

**Architecture:** Five new Python modules under `src/kylinbootlab/experiments/` — `ExperimentRecord` contract, JSONL-backed `ExperimentQueue`, `TargetPower` protocol with VIX/WOL backends, SSH-based `wait_for_ssh` alive detector, and `RecoveryManager` with double-layer restore. The `ExperimentOrchestrator` ties them together in a synchronous loop that reuses Phase 1 `collect_target_run`. A new `kbl experiment` CLI group exposes queue and run operations.

**Tech Stack:** Python 3.12, Pydantic 2, Typer, pytest, PowerShell COM (VIX), existing Phase 1 RunStore/remote modules

---

## Global Constraints

- Python 3.12+, Pydantic 2 strict models with `extra="forbid"`, JSON Schema 2020-12 for all persisted records.
- Phase 1 modules (`RunStore`, `remote.py`, `kbl-bootprobe`, `ProbeManifest`) are consumed but NOT modified.
- All new code is synchronous (no asyncio) — consistent with Phase 1 `SubprocessRunner`.
- VIX operations are called via PowerShell subprocess, not native ctypes.
- JSONL queue lines are atomic appends; state queries read the full file and take the last line per `exp_id`.
- Recovery is double-layer: VIX snapshot (first) → ostree rollback (fallback). Both layers are exercised in tests via `FakePower`.
- Experiments default to `max_attempts=3`.

---

## File Map

```text
src/kylinbootlab/experiments/__init__.py      Package marker + public re-exports
src/kylinbootlab/experiments/contracts.py      ExperimentRecord Pydantic model
src/kylinbootlab/experiments/queue.py          JSONL ExperimentQueue
src/kylinbootlab/experiments/power.py          TargetPower protocol + VixPower + WolPower
src/kylinbootlab/experiments/aliveness.py      wait_for_ssh alive detector
src/kylinbootlab/experiments/recovery.py       RecoveryManager (VIX + ostree layers)
src/kylinbootlab/experiments/orchestrator.py   ExperimentOrchestrator main loop
src/kylinbootlab/cli.py                        Modify: add `kbl experiment` subcommand group
tests/test_experiments_contracts.py            ExperimentRecord validation tests
tests/test_experiments_queue.py                ExperimentQueue CRUD + edge cases
tests/test_experiments_power.py                TargetPower command-construction tests
tests/test_experiments_recovery.py             RecoveryManager unit tests
tests/test_experiments_orchestrator.py         Orchestrator integration tests
scripts/target/prepare_recovery.sh             Target-side ostree recovery initialization
```

---

## Scope and Exit Criteria

Phase 2 is complete when all of the following are true:

- `ExperimentRecord` model passes Pydantic validation and JSON Schema generation.
- `ExperimentQueue` supports enqueue, dequeue, update, list, and reset with append-only JSONL persistence.
- `VixPower` backend constructs correct PowerShell COM commands for all six protocol methods.
- `WolPower` backend constructs correct SSH / magic-packet commands for the bare-metal path.
- `wait_for_ssh` polls with configurable timeout and interval, returns True on first success.
- `RecoveryManager.restore()` exercises the double-layer strategy; layer-2 is called only when layer-1 raises.
- `ExperimentOrchestrator.run_queue()` completes a 3-experiment queue against `FakePower` + `FakeRunner`.
- `kbl experiment queue`, `kbl experiment run`, `kbl experiment status`, `kbl experiment retry`, `kbl experiment reset` subcommands respond correctly.
- All Python static checks (`ruff`, `mypy strict`) and tests pass.

---

### Task 1: Define the ExperimentRecord Contract

**Files:**
- Create: `src/kylinbootlab/experiments/__init__.py`
- Create: `src/kylinbootlab/experiments/contracts.py`
- Create: `tests/test_experiments_contracts.py`

**Interfaces:**
- Produces: `ExperimentRecord` Pydantic model — fields `schema_version` (Literal[1]), `exp_id` (str, min_length=1), `profile` (str, min_length=1), `status` (Literal["pending","running","done","failed","skipped"]), `run_id` (UUID | None), `attempt` (int, default 0), `max_attempts` (int, default 3), `error` (str | None), `created_at` (AwareDatetime), `started_at` (AwareDatetime | None), `completed_at` (AwareDatetime | None)

- [ ] **Step 1: Write the failing test**

Create `tests/test_experiments_contracts.py`:

```python
from datetime import UTC, datetime
from uuid import UUID

import pytest
from pydantic import ValidationError

from kylinbootlab.experiments.contracts import ExperimentRecord


def test_experiment_record_accepts_valid_pending_entry() -> None:
    record = ExperimentRecord(
        exp_id="coldboot-baseline-001",
        profile="baseline",
        status="pending",
        created_at=datetime(2026, 7, 18, 10, 0, tzinfo=UTC),
    )

    assert record.schema_version == 1
    assert record.exp_id == "coldboot-baseline-001"
    assert record.attempt == 0
    assert record.max_attempts == 3
    assert record.run_id is None


def test_experiment_record_rejects_invalid_status() -> None:
    with pytest.raises(ValidationError, match="status"):
        ExperimentRecord(
            exp_id="test",
            profile="baseline",
            status="bogus",
            created_at=datetime(2026, 7, 18, 10, 0, tzinfo=UTC),
        )


def test_experiment_record_rejects_empty_exp_id() -> None:
    with pytest.raises(ValidationError, match="exp_id"):
        ExperimentRecord(
            exp_id="",
            profile="baseline",
            status="pending",
            created_at=datetime(2026, 7, 18, 10, 0, tzinfo=UTC),
        )


def test_experiment_record_with_run_id() -> None:
    run_id = UUID("11111111-1111-4111-8111-111111111111")
    record = ExperimentRecord(
        exp_id="coldboot-baseline-002",
        profile="baseline",
        status="done",
        run_id=run_id,
        attempt=1,
        started_at=datetime(2026, 7, 18, 10, 0, 5, tzinfo=UTC),
        completed_at=datetime(2026, 7, 18, 10, 3, 12, tzinfo=UTC),
        created_at=datetime(2026, 7, 18, 10, 0, tzinfo=UTC),
    )

    assert record.run_id == run_id
    assert record.status == "done"
    assert record.attempt == 1
```

- [ ] **Step 2: Run test to verify it fails**

Run:
```powershell
uv run pytest tests/test_experiments_contracts.py -v
```
Expected: FAIL — `ModuleNotFoundError: No module named 'kylinbootlab.experiments'`.

- [ ] **Step 3: Create the package and model**

Create `src/kylinbootlab/experiments/__init__.py`:
```python
from kylinbootlab.experiments.contracts import ExperimentRecord

__all__ = ["ExperimentRecord"]
```

Create `src/kylinbootlab/experiments/contracts.py`:
```python
from datetime import UTC, datetime
from typing import Literal
from uuid import UUID

from pydantic import AwareDatetime, ConfigDict, Field

from kylinbootlab.contracts import ContractModel


class ExperimentRecord(ContractModel):
    """One experiment in the queue — status tracked via append-only JSONL lines."""

    schema_version: Literal[1] = 1
    exp_id: str = Field(min_length=1, description="Unique experiment identifier")
    profile: str = Field(min_length=1, description="Profile name (baseline, tuned-*, etc.)")
    status: Literal["pending", "running", "done", "failed", "skipped"] = "pending"
    run_id: UUID | None = Field(default=None, description="Associated Phase 1 run ID")
    attempt: int = Field(default=0, ge=0, description="Current attempt number")
    max_attempts: int = Field(default=3, ge=1, description="Max attempts before giving up")
    error: str | None = Field(default=None, description="Last failure reason")
    created_at: AwareDatetime
    started_at: AwareDatetime | None = None
    completed_at: AwareDatetime | None = None
```

- [ ] **Step 4: Run tests to verify they pass**

Run:
```powershell
uv run pytest tests/test_experiments_contracts.py -v
```
Expected: 4 tests PASS.

- [ ] **Step 5: Run static checks**

```powershell
uv run ruff check src/kylinbootlab/experiments tests/test_experiments_contracts.py
uv run mypy src/kylinbootlab/experiments tests/test_experiments_contracts.py
```
Expected: both exit 0.

- [ ] **Step 6: Commit**

```powershell
git add src/kylinbootlab/experiments tests/test_experiments_contracts.py
git commit -m "feat: add ExperimentRecord contract"
```

---

### Task 2: Build the ExperimentQueue

**Files:**
- Create: `src/kylinbootlab/experiments/queue.py`
- Create: `tests/test_experiments_queue.py`
- Modify: `src/kylinbootlab/experiments/__init__.py`

**Interfaces:**
- Consumes: `ExperimentRecord` from Task 1
- Produces: `ExperimentQueue(root: Path)` class with methods `enqueue(records: list[ExperimentRecord]) -> None`, `dequeue(status: str = "pending") -> ExperimentRecord | None`, `update(exp_id: str, **fields: object) -> None`, `list(status: str | None = None) -> list[ExperimentRecord]`, `reset(*, status: str, new_status: str = "pending") -> None`

- [ ] **Step 1: Write the failing test**

Create `tests/test_experiments_queue.py`:

```python
import json
from datetime import UTC, datetime
from pathlib import Path
from uuid import UUID

import pytest

from kylinbootlab.experiments.contracts import ExperimentRecord
from kylinbootlab.experiments.queue import ExperimentQueue


def _make_record(exp_id: str, status: str = "pending") -> ExperimentRecord:
    return ExperimentRecord(
        exp_id=exp_id,
        profile="baseline",
        status=status,
        created_at=datetime(2026, 7, 18, 10, 0, tzinfo=UTC),
    )


def test_enqueue_appends_and_list_returns_latest_state(tmp_path: Path) -> None:
    queue = ExperimentQueue(tmp_path / "queue.jsonl")

    queue.enqueue([_make_record("exp-001"), _make_record("exp-002")])

    records = queue.list()
    assert len(records) == 2
    assert {r.exp_id for r in records} == {"exp-001", "exp-002"}
    assert all(r.status == "pending" for r in records)
    # Verify file was written
    assert (tmp_path / "queue.jsonl").is_file()


def test_dequeue_grabs_one_and_marks_running(tmp_path: Path) -> None:
    queue = ExperimentQueue(tmp_path / "queue.jsonl")
    queue.enqueue([_make_record("exp-001"), _make_record("exp-002")])

    dequeued = queue.dequeue("pending")

    assert dequeued is not None
    assert dequeued.exp_id == "exp-001"

    # The queued record should now be "running" in the file
    records = queue.list()
    exp = next(r for r in records if r.exp_id == "exp-001")
    assert exp.status == "running"


def test_dequeue_returns_none_when_no_pending(tmp_path: Path) -> None:
    queue = ExperimentQueue(tmp_path / "queue.jsonl")

    assert queue.dequeue("pending") is None


def test_update_merges_and_appends_new_line(tmp_path: Path) -> None:
    queue = ExperimentQueue(tmp_path / "queue.jsonl")
    queue.enqueue([_make_record("exp-001")])
    run_id = UUID("11111111-1111-4111-8111-111111111111")

    queue.update("exp-001", status="done", run_id=run_id,
                 completed_at=datetime(2026, 7, 18, 10, 3, tzinfo=UTC))

    records = queue.list()
    done = next(r for r in records if r.exp_id == "exp-001")
    assert done.status == "done"
    assert done.run_id == run_id
    # File should have 2 lines: pending→done
    line_count = (tmp_path / "queue.jsonl").read_text(encoding="utf-8").strip().count("\n") + 1
    assert line_count == 2


def test_update_raises_for_unknown_exp_id(tmp_path: Path) -> None:
    queue = ExperimentQueue(tmp_path / "queue.jsonl")

    with pytest.raises(KeyError, match="unknown exp_id"):
        queue.update("nonexistent", status="done")


def test_list_can_filter_by_status(tmp_path: Path) -> None:
    queue = ExperimentQueue(tmp_path / "queue.jsonl")
    queue.enqueue([_make_record("exp-001"), _make_record("exp-002")])
    queue.dequeue("pending")  # exp-001 → running

    pending = queue.list("pending")
    running = queue.list("running")

    assert len(pending) == 1
    assert pending[0].exp_id == "exp-002"
    assert len(running) == 1
    assert running[0].exp_id == "exp-001"


def test_reset_changes_status_for_all_matching(tmp_path: Path) -> None:
    queue = ExperimentQueue(tmp_path / "queue.jsonl")
    queue.enqueue([_make_record("exp-001"), _make_record("exp-002")])
    queue.update("exp-001", status="failed", error="timeout")
    queue.update("exp-002", status="failed", error="crash")

    queue.reset(status="failed", new_status="pending")

    records = queue.list()
    assert all(r.status == "pending" for r in records)


def test_enqueue_rejects_duplicate_exp_id(tmp_path: Path) -> None:
    queue = ExperimentQueue(tmp_path / "queue.jsonl")
    queue.enqueue([_make_record("exp-001")])

    with pytest.raises(ValueError, match="already in queue"):
        queue.enqueue([_make_record("exp-001")])
```

- [ ] **Step 2: Run test to verify it fails**

Run:
```powershell
uv run pytest tests/test_experiments_queue.py -v
```
Expected: FAIL — `ModuleNotFoundError: No module named 'kylinbootlab.experiments.queue'`.

- [ ] **Step 3: Write minimal working ExperimentQueue**

Create `src/kylinbootlab/experiments/queue.py`:

```python
import json
from datetime import UTC, datetime
from pathlib import Path

from kylinbootlab.experiments.contracts import ExperimentRecord


class ExperimentQueue:
    """Append-only JSONL experiment queue.

    Each line is a snapshot of one experiment's current state.  The "current"
    state for any ``exp_id`` is the *last* line bearing that id — earlier
    lines are historical.  This means every mutation appends, never overwrites,
    so a crash during a write can at worst lose the in-progress line (the state
    falls back to the previous line).
    """

    def __init__(self, path: Path) -> None:
        self.path = path

    # ------------------------------------------------------------------
    def _read_all(self) -> dict[str, ExperimentRecord]:
        """Return the latest record for every exp_id in the file."""
        by_id: dict[str, ExperimentRecord] = {}
        if self.path.is_file():
            for line in self.path.read_text(encoding="utf-8").splitlines():
                if not line.strip():
                    continue
                record = ExperimentRecord.model_validate_json(line)
                by_id[record.exp_id] = record
        return by_id

    def _write_line(self, record: ExperimentRecord) -> None:
        line = record.model_dump_json() + "\n"
        with open(self.path, "a", encoding="utf-8", newline="\n") as fh:
            fh.write(line)

    # ------------------------------------------------------------------
    def enqueue(self, records: list[ExperimentRecord]) -> None:
        existing = self._read_all()
        for record in records:
            if record.exp_id in existing:
                raise ValueError(f"exp_id already in queue: {record.exp_id}")
            self._write_line(record)

    def dequeue(self, status: str = "pending") -> ExperimentRecord | None:
        by_id = self._read_all()
        for record in by_id.values():
            if record.status == status:
                record.status = "running"
                record.started_at = datetime.now(UTC)
                self._write_line(record)
                return record
        return None

    def update(self, exp_id: str, **fields: object) -> None:
        by_id = self._read_all()
        if exp_id not in by_id:
            raise KeyError(f"unknown exp_id: {exp_id}")
        updated = by_id[exp_id].model_copy(update=fields)
        self._write_line(updated)

    def list(self, status: str | None = None) -> list[ExperimentRecord]:
        records = list(self._read_all().values())
        if status is not None:
            records = [r for r in records if r.status == status]
        return records

    def reset(self, *, status: str, new_status: str = "pending") -> None:
        for record in self._read_all().values():
            if record.status == status:
                record.status = new_status
                record.error = None
                self._write_line(record)
```

- [ ] **Step 4: Run tests to verify they pass**

Run:
```powershell
uv run pytest tests/test_experiments_queue.py -v
```
Expected: 8 tests PASS.

- [ ] **Step 5: Update __init__.py exports**

Edit `src/kylinbootlab/experiments/__init__.py`:
```python
from kylinbootlab.experiments.contracts import ExperimentRecord
from kylinbootlab.experiments.queue import ExperimentQueue

__all__ = ["ExperimentRecord", "ExperimentQueue"]
```

- [ ] **Step 6: Run static checks**

```powershell
uv run ruff check src/kylinbootlab/experiments tests/test_experiments_queue.py
uv run mypy src/kylinbootlab/experiments tests/test_experiments_queue.py
```
Expected: both exit 0.

- [ ] **Step 7: Commit**

```powershell
git add src/kylinbootlab/experiments/queue.py src/kylinbootlab/experiments/__init__.py tests/test_experiments_queue.py
git commit -m "feat: add JSONL ExperimentQueue"
```

---

### Task 3: Build the TargetPower Protocol and VixPower Backend

**Files:**
- Create: `src/kylinbootlab/experiments/power.py`
- Create: `tests/test_experiments_power.py`

**Interfaces:**
- Produces: `TargetPower` Protocol with methods `power_on() -> None`, `power_off() -> None`, `reset() -> None`, `snapshot_create(name: str) -> None`, `snapshot_restore(name: str) -> None`, `guest_alive() -> bool`
- Produces: `VixPower(vmx_path: str)` class implementing TargetPower — constructs PowerShell COM commands and runs them via `subprocess.run`
- Produces: `power_backend_factory(backend: str, **kwargs: str) -> TargetPower` — factory that returns VixPower or raises on "wol" (not implemented in this task)

- [ ] **Step 1: Write the failing test**

Create `tests/test_experiments_power.py`:

```python
import subprocess
from pathlib import Path

import pytest

from kylinbootlab.experiments.power import (
    TargetPower,
    VixPower,
    power_backend_factory,
)


class FakeSubprocessRun:
    """Records calls so we can assert command construction without real VI/V."""
    def __init__(self) -> None:
        self.calls: list[list[str]] = []

    def __call__(
        self, args: list[str], **kwargs: object
    ) -> subprocess.CompletedProcess[str]:
        self.calls.append(args)
        return subprocess.CompletedProcess(args, 0, stdout="", stderr="")


def test_power_backend_vix_is_registered() -> None:
    power = power_backend_factory("vix",
        vmx_path=r"C:\VMs\test.vmx")
    assert isinstance(power, VixPower)


def test_power_backend_unknown_raises() -> None:
    with pytest.raises(ValueError, match="unknown power backend"):
        power_backend_factory("unknown")


def test_vix_power_on_constructs_correct_command() -> None:
    fake_run = FakeSubprocessRun()
    power = VixPower(r"C:\VMs\test.vmx", _runner=fake_run)

    power.power_on()

    cmd = fake_run.calls[-1]
    assert cmd[0] == "powershell.exe"
    assert "Connect-VIX" in " ".join(cmd)
    assert "PowerOn" in " ".join(cmd)
    assert r"C:\VMs\test.vmx" in " ".join(cmd)


def test_vix_snapshot_restore_constructs_correct_command() -> None:
    fake_run = FakeSubprocessRun()
    power = VixPower(r"C:\VMs\test.vmx", _runner=fake_run)

    power.snapshot_restore("baseline")

    cmd = fake_run.calls[-1]
    assert "RevertToSnapshot" in " ".join(cmd)
    assert "baseline" in " ".join(cmd)


def test_vix_power_off_is_idempotent() -> None:
    """Power off when already off should not crash — just no-op."""
    fake_run = FakeSubprocessRun()
    # Simulate echo for guest_alive → powered on
    # Then power_off
    power = VixPower(r"C:\VMs\test.vmx", _runner=fake_run)

    # guest_alive returns False (VM off) — power_off should still succeed
    power.power_off()
    assert len(fake_run.calls) == 1  # Only one PowerShell call


def test_vix_power_on_powershell_syntax_is_valid() -> None:
    """The generated PowerShell command must parse. Use simple syntax check."""
    fake_run = FakeSubprocessRun()
    power = VixPower(r"C:\VMs\openkylin.vmx", _runner=fake_run)

    power.power_on()

    script = " ".join(fake_run.calls[-1])
    assert "powershell.exe" in script
    assert "-NoProfile" in script
    assert "-NonInteractive" in script
    assert "OpenVM" in script
    assert "PowerOn" in script
```

- [ ] **Step 2: Run test to verify it fails**

Run:
```powershell
uv run pytest tests/test_experiments_power.py -v
```
Expected: FAIL — `ModuleNotFoundError: No module named 'kylinbootlab.experiments.power'`.

- [ ] **Step 3: Write the module**

Create `src/kylinbootlab/experiments/power.py`:

```python
"""Target power-control abstraction with VIX (VMware) and WOL backends."""

import subprocess
from pathlib import Path
from typing import Protocol


class TargetPower(Protocol):
    """Unified power control for physical and virtual targets."""

    def power_on(self) -> None: ...
    def power_off(self) -> None: ...
    def reset(self) -> None: ...
    def snapshot_create(self, name: str) -> None: ...
    def snapshot_restore(self, name: str) -> None: ...
    def guest_alive(self) -> bool: ...


def _pwsh(code: str) -> list[str]:
    """Wrap one-liner PowerShell code into a subprocess-ready command list."""
    return [
        "powershell.exe",
        "-NoProfile",
        "-NonInteractive",
        "-Command",
        code,
    ]


class VixPower:
    """VMware VIX power control via PowerShell COM.

    The VMX file path identifies the virtual machine.  All operations are
    idempotent — calling ``power_on`` on an already-running VM is a no-op
    at the VI/V level.
    """

    def __init__(self, vmx_path: str, *, _runner: object = None) -> None:
        self.vmx_path = vmx_path
        self._run = _runner if _runner is not None else self._real_run

    @staticmethod
    def _real_run(args: list[str]) -> subprocess.CompletedProcess[str]:
        return subprocess.run(args, check=False, capture_output=True, text=True)

    # -- power control ---------------------------------------------------

    def power_on(self) -> None:
        self._run(_pwsh(
            f'$vm = (Connect-VIX -Host localhost).OpenVM("{self.vmx_path}"); '
            "$vm.PowerOn()"
        ))

    def power_off(self) -> None:
        self._run(_pwsh(
            f'$vm = (Connect-VIX -Host localhost).OpenVM("{self.vmx_path}"); '
            "$vm.PowerOff()"
        ))

    def reset(self) -> None:
        self._run(_pwsh(
            f'$vm = (Connect-VIX -Host localhost).OpenVM("{self.vmx_path}"); '
            "$vm.Reset()"
        ))

    def snapshot_create(self, name: str) -> None:
        self._run(_pwsh(
            f'$vm = (Connect-VIX -Host localhost).OpenVM("{self.vmx_path}"); '
            f'$vm.CreateSnapshot("{name}")'
        ))

    def snapshot_restore(self, name: str) -> None:
        self._run(_pwsh(
            f'$vm = (Connect-VIX -Host localhost).OpenVM("{self.vmx_path}"); '
            f'$vm.RevertToSnapshot("{name}")'
        ))

    def guest_alive(self) -> bool:
        result = self._run(_pwsh(
            f'$vm = (Connect-VIX -Host localhost).OpenVM("{self.vmx_path}"); '
            "$vm.IsPoweredOn"
        ))
        return result.returncode == 0 and "True" in result.stdout


def power_backend_factory(backend: str, **kwargs: str) -> TargetPower:
    """Return a TargetPower instance for the named backend.

    Supported values: ``"vix"`` (default), ``"wol"`` (not yet implemented).
    """
    if backend == "vix":
        vmx = kwargs.get("vmx_path")
        if not vmx:
            raise ValueError("vmx_path is required for VI/X backend")
        return VixPower(vmx)
    raise ValueError(f"unknown power backend: {backend}")
```

- [ ] **Step 4: Run tests to verify they pass**

Run:
```powershell
uv run pytest tests/test_experiments_power.py -v
```
Expected: 6 tests PASS.

- [ ] **Step 5: Run static checks**

```powershell
uv run ruff check src/kylinbootlab/experiments/power.py tests/test_experiments_power.py
uv run mypy src/kylinbootlab/experiments/power.py tests/test_experiments_power.py
```
Expected: both exit 0.

- [ ] **Step 6: Commit**

```powershell
git add src/kylinbootlab/experiments/power.py tests/test_experiments_power.py
git commit -m "feat: add TargetPower protocol and VixPower backend"
```

---

### Task 4: Add WolPower Backend

**Files:**
- Modify: `src/kylinbootlab/experiments/power.py`
- Modify: `tests/test_experiments_power.py`

**Interfaces:**
- Produces: `WolPower(target: str, mac: str)` — `power_on` sends magic packet, `power_off`/`reset` use SSH, `snapshot_*` are no-ops / ostree-based. `guest_alive` probes SSH.

- [ ] **Step 1: Write the failing test**

Append to `tests/test_experiments_power.py`:

```python
from kylinbootlab.experiments.power import WolPower, power_backend_factory


def test_power_backend_wol_is_registered() -> None:
    power = power_backend_factory("wol",
        target="kbl@openkylin.local", mac="00:11:22:33:44:55")
    assert isinstance(power, WolPower)


def test_wol_power_on_constructs_magic_packet() -> None:
    fake_run = FakeSubprocessRun()
    power = WolPower("kbl@target.local", "AA:BB:CC:DD:EE:FF", _runner=fake_run)

    power.power_on()

    # WOL magic packet: 6 bytes FF followed by MAC repeated 16 times
    cmd_text = " ".join(fake_run.calls[-1])
    assert "AA:BB:CC:DD:EE:FF" in cmd_text or "wakeonlan" in cmd_text.lower()


def test_wol_power_off_uses_ssh() -> None:
    fake_run = FakeSubprocessRun()
    power = WolPower("kbl@target.local", "11:22:33:44:55:66", _runner=fake_run)

    power.power_off()

    cmd = fake_run.calls[-1]
    assert cmd[0] == "ssh"
    assert "poweroff" in " ".join(cmd)


def test_wol_snapshot_restore_is_noop() -> None:
    fake_run = FakeSubprocessRun()
    power = WolPower("kbl@target.local", "11:22:33:44:55:66", _runner=fake_run)

    # snapshot_restore on WOL is a no-op (handled by RecoveryManager ostree path)
    power.snapshot_restore("baseline")
    assert len(fake_run.calls) == 0
```

- [ ] **Step 2: Run test to verify it fails**

Run:
```powershell
uv run pytest tests/test_experiments_power.py::test_power_backend_wol_is_registered -v
```
Expected: FAIL — ValueError because "wol" backend not implemented yet.

- [ ] **Step 3: Implement WolPower**

Append to `src/kylinbootlab/experiments/power.py`:

```python
import socket
import struct


class WolPower:
    """Bare-metal power control via Wake-on-LAN and SSH.

    ``power_on`` broadcasts a magic packet to the target's MAC address.
    ``power_off`` and ``reset`` use SSH.  ``snapshot_*`` are no-ops —
    bare-metal recovery is handled at the ostree level by RecoveryManager.
    """

    def __init__(
        self,
        target: str,
        mac: str,
        *,
        _runner: object = None,
    ) -> None:
        self.target = target
        self.mac = mac
        self._run = _runner if _runner is not None else self._real_run

    @staticmethod
    def _real_run(args: list[str]) -> subprocess.CompletedProcess[str]:
        return subprocess.run(args, check=False, capture_output=True, text=True,
                              timeout=30)

    # -- power control ---------------------------------------------------

    def power_on(self) -> None:
        """Send a Wake-on-LAN magic packet to the target's MAC."""
        hex_str = self.mac.replace(":", "").replace("-", "").replace(" ", "")
        if len(hex_str) != 12:
            raise ValueError(f"invalid MAC address: {self.mac}")
        addr_bytes = bytes.fromhex(hex_str)
        magic = b"\xff" * 6 + addr_bytes * 16

        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as sock:
            sock.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
            sock.sendto(magic, ("255.255.255.255", 9))
        # Also try wakeonlan CLI as fallback (non-fatal if missing)
        self._run(["wakeonlan", self.mac])

    def power_off(self) -> None:
        self._run([
            "ssh", "-o", "BatchMode=yes", "-o", "ConnectTimeout=15",
            self.target, "sudo", "poweroff",
        ])

    def reset(self) -> None:
        self.power_off()

    def snapshot_create(self, name: str) -> None:
        """Not supported on bare metal — handled by ostree rollback."""
        pass

    def snapshot_restore(self, name: str) -> None:
        """Not supported on bare metal — handled by ostree rollback."""
        pass

    def guest_alive(self) -> bool:
        result = self._run([
            "ssh", "-o", "BatchMode=yes", "-o", "ConnectTimeout=10",
            self.target, "true",
        ])
        return result.returncode == 0
```

Update `power_backend_factory` to handle `"wol"`:

```python
def power_backend_factory(backend: str, **kwargs: str) -> TargetPower:
    """Return a TargetPower instance for the named backend."""
    if backend == "vix":
        vmx = kwargs.get("vmx_path")
        if not vmx:
            raise ValueError("vmx_path is required for VI/X backend")
        return VixPower(vmx)
    if backend == "wol":
        target = kwargs.get("target")
        mac = kwargs.get("mac")
        if not target or not mac:
            raise ValueError("target and mac are required for WOL back-end")
        return WolPower(target, mac)
    raise ValueError(f"unknown power backend: {backend}")
```

- [ ] **Step 4: Run all power tests**

Run:
```powershell
uv run pytest tests/test_experiments_power.py -v
```
Expected: 10 tests PASS.

- [ ] **Step 5: Commit**

```powershell
git add src/kylinbootlab/experiments/power.py tests/test_experiments_power.py
git commit -m "feat: add WolPower bare-metal backend"
```

---

### Task 5: Build the Alive Detector

**Files:**
- Create: `src/kylinbootlab/experiments/aliveness.py`
- Modify: `tests/test_experiments_orchestrator.py` (create with a single focused test for now)

**Interfaces:**
- Produces: `wait_for_ssh(target: str, timeout: float = 120, interval: float = 5) -> bool`

- [ ] **Step 1: Create the module with test inside orchestrator test file**

Create `src/kylinbootlab/experiments/aliveness.py`:

```python
"""SSH-based alive detection for experiment orchestration."""

import subprocess
import time


def wait_for_ssh(
    target: str,
    timeout: float = 120,
    interval: float = 5,
) -> bool:
    """Poll *target* via SSH until successful or *timeout* seconds elapse.

    Returns ``True`` as soon as ``ssh target true`` exits 0; ``False`` if
    the deadline is reached without a successful connection.
    """
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        try:
            result = subprocess.run(
                [
                    "ssh",
                    "-o", "BatchMode=yes",
                    "-o", "ConnectTimeout=10",
                    target,
                    "true",
                ],
                check=False,
                capture_output=True,
                timeout=10,
            )
            if result.returncode == 0:
                return True
        except (OSError, subprocess.TimeoutExpired):
            pass
        time.sleep(interval)
    return False
```

Create `tests/test_experiments_orchestrator.py`:

```python
import subprocess
from pathlib import Path

from kylinbootlab.experiments.aliveness import wait_for_ssh


def test_wait_for_ssh_returns_false_when_ssh_never_answers(tmp_path: Path) -> None:
    """wait_for_ssh returns False when every attempt fails."""
    result = wait_for_ssh("192.0.2.1", timeout=0.5, interval=0.1)
    assert result is False


def test_wait_for_ssh_returns_true_on_first_success(monkeypatch) -> None:
    """wait_for_ssh returns True as soon as one call succeeds."""
    call_count = 0

    def fake_run(args, **_kwargs):
        nonlocal call_count
        call_count += 1
        if call_count >= 2:
            return subprocess.CompletedProcess(args, 0, stdout="", stderr="")
        raise OSError("connection refused")

    monkeypatch.setattr("kylinbootlab.experiments.aliveness.subprocess.run", fake_run)

    result = wait_for_ssh("target.local", timeout=10, interval=0.05)
    assert result is True
```

- [ ] **Step 2: Run tests**

Run:
```powershell
uv run pytest tests/test_experiments_orchestrator.py -v
```
Expected: 2 tests PASS.

- [ ] **Step 3: Static checks and commit**

```powershell
uv run ruff check src/kylinbootlab/experiments/aliveness.py tests/test_experiments_orchestrator.py
uv run mypy src/kylinbootlab/experiments/aliveness.py tests/test_experiments_orchestrator.py
git add src/kylinbootlab/experiments/aliveness.py tests/test_experiments_orchestrator.py
git commit -m "feat: add SSH alive detector (wait_for_ssh)"
```
Expected: checks exit 0.

---

### Task 6: Build the RecoveryManager

**Files:**
- Create: `src/kylinbootlab/experiments/recovery.py`
- Create: `tests/test_experiments_recovery.py`

**Interfaces:**
- Consumes: `TargetPower` from Task 3/4
- Produces: `RecoveryManager.restore(power: TargetPower, target: str) -> None` — tries VIX snapshot restore first, falls back to SSH-triggered ostree rollback on failure

- [ ] **Step 1: Write the failing test**

Create `tests/test_experiments_recovery.py`:

```python
import subprocess
from pathlib import Path

import pytest

from kylinbootlab.experiments.recovery import RecoveryFailedError, RecoveryManager


class StubPower:
    """Stub TargetPower recording calls and allowing injection of failures."""

    def __init__(self) -> None:
        self.calls: list[str] = []
        self._snapshot_recoverable = True

    def snapshot_restore(self, name: str) -> None:
        self.calls.append(f"snap:{name}")
        if not self._snapshot_recoverable:
            raise RuntimeError("VIX not responding")

    def power_on(self) -> None:
        self.calls.append("power_on")

    def power_off(self) -> None:
        self.calls.append("power_off")

    def reset(self) -> None:
        self.calls.append("reset")

    def snapshot_create(self, name: str) -> None:
        self.calls.append(f"snap_create:{name}")

    def guest_alive(self) -> bool:
        return False


class StubRunner:
    """Stub subprocess runner for SSH-triggered ostree commands."""

    def __init__(self, *, succeed: bool = True) -> None:
        self.calls: list[list[str]] = []
        self.succeed = succeed

    def __call__(self, args: list[str]) -> subprocess.CompletedProcess[str]:
        self.calls.append(args)
        rc = 0 if self.succeed else 1
        return subprocess.CompletedProcess(args, rc, stdout="", stderr="")


def test_snapshot_restore_is_first_layer() -> None:
    power = StubPower()
    RecoveryManager.restore(power, "kbl@target.local")

    assert "snap:baseline" in power.calls
    assert power.calls[0] == "snap:baseline"


def test_ostree_fallback_when_snapshot_fails() -> None:
    power = StubPower()
    power._snapshot_recoverable = False
    runner = StubRunner()

    RecoveryManager.restore(power, "kbl@target.local", runner=runner)

    assert power.calls == ["snap:baseline"]  # tried and failed
    # Fallback should have triggered SSH commands
    assert any("ostree" in " ".join(c) for c in runner.calls)


def test_both_layers_fail_raises_recovery_failed() -> None:
    power = StubPower()
    power._snapshot_recoverable = False
    runner = StubRunner(succeed=False)

    with pytest.raises(RecoveryFailedError):
        RecoveryManager.restore(power, "kbl@target.local", runner=runner)
```

- [ ] **Step 2: Run test to verify it fails**

Run:
```powershell
uv run pytest tests/test_experiments_recovery.py -v
```
Expected: FAIL — `ModuleNotFoundError`.

- [ ] **Step 3: Implement RecoveryManager**

Create `src/kylinbootlab/experiments/recovery.py`:

```python
"""Double-layer recovery: VIX snapshot (fast) → ostree rollback (fallback)."""

import subprocess
from pathlib import Path

from kylinbootlab.experiments.power import TargetPower


class RecoveryFailedError(RuntimeError):
    """Both recovery layers failed — manual intervention required."""


class RecoveryManager:
    """Stateless recovery orchestrator.

    Layer 1: VMware snapshot restore (seconds, no OS dependency).
    Layer 2: ostree admin undeploy + reboot (minutes, requires SSH).
    """

    @staticmethod
    def restore(
        power: TargetPower,
        target: str,
        *,
        runner: object = None,
    ) -> None:
        """Attempt recovery.  Raises ``RecoveryFailedError`` only if both layers fail."""
        if runner is None:
            runner = RecoveryManager._ssh_run

        # Layer 1: VIX snapshot
        try:
            power.snapshot_restore("baseline")
            power.power_on()
            return
        except Exception:
            pass

        # Layer 2: ostree rollback via SSH
        try:
            result = runner([
                "ssh", "-o", "BatchMode=yes", "-o", "ConnectTimeout=15",
                target,
                (
                    "sudo ostree admin undeploy 1 && "
                    "sudo grub-set-default 0 && "
                    "sudo reboot"
                ),
            ])
            if result.returncode != 0:
                raise RecoveryFailedError(
                    f"ostree rollback failed: {result.stderr}"
                )
        except Exception as exc:
            raise RecoveryFailedError(
                f"both recovery layers failed: {exc}"
            ) from exc

    @staticmethod
    def _ssh_run(args: list[str]) -> subprocess.CompletedProcess[str]:
        return subprocess.run(args, check=False, capture_output=True, text=True,
                              timeout=30)
```

- [ ] **Step 4: Run tests**

Run:
```powershell
uv run pytest tests/test_experiments_recovery.py -v
```
Expected: 3 tests PASS.

- [ ] **Step 5: Commit**

```powershell
uv run ruff check src/kylinbootlab/experiments/recovery.py tests/test_experiments_recovery.py
uv run mypy src/kylinbootlab/experiments/recovery.py tests/test_experiments_recovery.py
git add src/kylinbootlab/experiments/recovery.py tests/test_experiments_recovery.py
git commit -m "feat: add RecoveryManager with double-layer restore"
```
Expected: ruff and mypy exit 0.

---

### Task 7: Build the ExperimentOrchestrator

**Files:**
- Create: `src/kylinbootlab/experiments/orchestrator.py`
- Modify: `tests/test_experiments_orchestrator.py` (replace with full integration tests)

**Interfaces:**
- Consumes: `ExperimentQueue`, `RunStore`, `TargetPower`, `RecoveryManager`, `wait_for_ssh`, `collect_target_run` from Phase 1
- Produces: `ExperimentOrchestrator(...).run_queue() -> None` — main loop
- Produces: `ExperimentError`, `PowerControlError`, `TargetUnreachableError`

- [ ] **Step 1: Write the orchestrator + errors**

Create `src/kylinbootlab/experiments/orchestrator.py`:

```python
"""Experiment loop: dequeue → power-cycle → collect → evaluate → repeat."""

import time
from pathlib import Path
from uuid import uuid4

from kylinbootlab.experiments.aliveness import wait_for_ssh
from kylinbootlab.experiments.queue import ExperimentQueue
from kylinbootlab.experiments.power import TargetPower
from kylinbootlab.experiments.recovery import RecoveryManager, RecoveryFailedError
from kylinbootlab.remote import (
    RemoteCollectionError,
    SubprocessRunner,
    collect_target_run,
)
from kylinbootlab.store import RunStore


# -- error hierarchy ---------------------------------------------------------

class ExperimentError(Exception):
    """Base for all experiment-related errors."""


class PowerControlError(ExperimentError):
    """A power operation (on/off/reset) failed."""


class TargetUnreachableError(ExperimentError):
    """Target did not become SSH-reachable within the deadline."""


# -- orchestrator ------------------------------------------------------------

class ExperimentOrchestrator:
    """Run an experiment queue against one target, looping until drained."""

    def __init__(
        self,
        queue: ExperimentQueue,
        store: RunStore,
        power: TargetPower,
        target: str,
        incoming_root: Path,
    ) -> None:
        self.queue = queue
        self.store = store
        self.power = power
        self.target = target
        self.incoming_root = incoming_root

    def run_queue(self) -> None:
        while (exp := self.queue.dequeue("pending")) is not None:
            self.queue.update(exp.exp_id, status="running")

            try:
                self._run_one_experiment(exp.exp_id)
            except ExperimentError as exc:
                exp_record = self._current(exp.exp_id)
                if exp_record and exp_record.attempt < exp_record.max_attempts:
                    self.queue.update(exp.exp_id, attempt=exp_record.attempt + 1)
                    try:
                        RecoveryManager.restore(self.power, self.target)
                    except RecoveryFailedError:
                        self.queue.update(
                            exp.exp_id, status="skipped",
                            error="recovery failed after attempt "
                                  f"{exp_record.attempt}",
                        )
                        continue
                else:
                    self.queue.update(exp.exp_id, status="failed",
                                      error=str(exc))
            finally:
                try:
                    self.power.power_off()
                except Exception:
                    pass  # best-effort shutdown

    # -- internal ------------------------------------------------------------

    def _current(self, exp_id: str) -> object | None:
        records = [r for r in self.queue.list() if r.exp_id == exp_id]
        return records[0] if records else None

    def _run_one_experiment(self, exp_id: str) -> None:
        # 1. Ensure target boots from clean state
        if not self.power.guest_alive():
            self.power.snapshot_restore("baseline")
            self.power.power_on()
        else:
            self.power.reset()

        # 2. Wait for SSH (120 s deadline)
        if not wait_for_ssh(self.target, timeout=120):
            raise TargetUnreachableError(
                f"SSH not reachable within 120 s for {exp_id}"
            )

        # 3. Collect via Phase 1 pipeline
        run_id = uuid4()
        try:
            collect_target_run(
                target=self.target,
                run_id=run_id,
                incoming_root=self.incoming_root,
                store=self.store,
                runner=SubprocessRunner(),
            )
        except RemoteCollectionError as exc:
            raise ExperimentError(
                f"collection failed for {exp_id}: {exc}"
            ) from exc

        # 4. Success
        self.queue.update(exp_id, status="done", run_id=run_id)
```

- [ ] **Step 2: Write the integration tests**

Replace `tests/test_experiments_orchestrator.py`:

```python
# Re-run wait_for_ssh+orchestrator tests: power simulation + queue flow
import shutil
import subprocess
import time
from collections.abc import Sequence
from pathlib import Path
from uuid import uuid4

from kylinbootlab.experiments.aliveness import wait_for_ssh
from kylinbootlab.experiments.contracts import ExperimentRecord
from kylinbootlab.experiments.orchestrator import (
    ExperimentError,
    ExperimentOrchestrator,
    PowerControlError,
    TargetUnreachableError,
)
from kylinbootlab.experiments.queue import ExperimentQueue
from kylinbootlab.store import RunStore
from tests.helpers import RUN_ID, create_probe_bundle


# -- Test doubles ------------------------------------------------------------

class StubPower:
    """Minimal TargetPower that succeeds at everything."""
    def power_on(self) -> None: pass
    def power_off(self) -> None: pass
    def reset(self) -> None: pass
    def snapshot_create(self, name: str) -> None: pass
    def snapshot_restore(self, name: str) -> None: pass
    def guest_alive(self) -> bool: return False


class StubCollector:
    """Stub for collect_target_run that records calls and can be set to fail."""
    def __init__(self) -> None:
        self.calls: list[str] = []
        self._should_fail = False
        self._hang = False

    def __call__(self, *, target: str, run_id, incoming_root, store, runner):
        self.calls.append(str(run_id))
        if self._should_fail:
            from kylinbootlab.remote import RemoteCollectionError
            raise RemoteCollectionError("stub failure")
        if self._hang:
            time.sleep(9999)
        # Simulate successful import by creating a bundle
        import shutil
        bundle_src = None  # not needed for these tests


class FakeOrchestrator(ExperimentOrchestrator):
    """Orchestrator that uses stubs for power, SSH, and collection."""
    def __init__(self, queue, store, power, collector, target="kbl@stub"):
        self.queue = queue
        self.store = store
        self.power = power
        self.target = target
        self.incoming_root = Path("/tmp/incoming")
        self._collector = collector


# -- Unit test: wait_for_ssh -------------------------------------------------

def test_wait_for_ssh_returns_false_on_timeout() -> None:
    assert wait_for_ssh("192.0.2.1", timeout=0.3, interval=0.1) is False


def test_wait_for_ssh_returns_true_on_success(monkeypatch) -> None:
    calls = 0
    def fake_run(args, **_kw):
        nonlocal calls; calls += 1
        if calls >= 2:
            return subprocess.CompletedProcess(args, 0, stdout="", stderr="")
        raise OSError()
    monkeypatch.setattr("kylinbootlab.experiments.aliveness.subprocess.run",
                         fake_run)
    assert wait_for_ssh("t", timeout=5, interval=0.01) is True


# -- Integration test: happy-path 3-experiment queue -------------------------

def test_run_queue_completes_three_experiments(tmp_path: Path) -> None:
    from datetime import UTC, datetime

    store = RunStore(tmp_path / "runs")
    queue = ExperimentQueue(tmp_path / "queue.jsonl")

    # Pre-populate queue
    queue.enqueue([
        ExperimentRecord(exp_id=f"exp-{i:03d}", profile="baseline",
                         status="pending",
                         created_at=datetime(2026, 7, 18, 12, 0, tzinfo=UTC))
        for i in range(3)
    ])

    # Ingest a reusable bundle so collect_target_run has something to import
    bundle = create_probe_bundle(tmp_path / "source", run_id=RUN_ID)

    # Use FakeRunner from test_remote pattern
    class FakeRunner:
        def __init__(self, bundle_path):
            self.bundle = bundle_path
            self.calls = []
        def run(self, args):
            self.calls.append(list(args))
            if args[0] == "scp":
                dst = Path(args[-1]) / str(RUN_ID) if len(args) > 1 else Path(".")
                shutil.copytree(self.bundle, dst)
                return subprocess.CompletedProcess([], 0, "", "")
            return subprocess.CompletedProcess([], 0, "", "")

    runner = FakeRunner(bundle)

    # Patch wait_for_ssh to always succeed
    import kylinbootlab.experiments.orchestrator as orch
    original_wait = orch.wait_for_ssh
    orch.wait_for_ssh = lambda target, timeout=120: True

    # Patch collect_target_run
    from kylinbootlab.remote import collect_target_run as orig_collect
    def stub_collect(*, target, run_id, incoming_root, store, runner):
        import shutil, os
        import uuid
        rid = run_id or uuid.uuid4()
        dst = incoming_root / str(rid)
        if not dst.exists():
            shutil.copytree(bundle, dst)
        return store.ingest(dst)
    orch.collect_target_run = stub_collect

    try:
        power = StubPower()
        orch_instance = orch.ExperimentOrchestrator(
            queue=queue, store=store, power=power,
            target="kbl@stub", incoming_root=tmp_path / "incoming",
        )
        orch_instance.run_queue()
    finally:
        orch.wait_for_ssh = original_wait
        orch.collect_target_run = orig_collect

    # All experiments should be done
    records = queue.list()
    assert len(records) == 3
    assert all(r.status == "done" for r in records)
    assert all(r.run_id is not None for r in records)
```

- [ ] **Step 3: Run tests to verify orchestration**

Run:
```powershell
uv run pytest tests/test_experiments_orchestrator.py -v
```
Expected: 3 tests PASS.

- [ ] **Step 4: Commit**

```powershell
uv run ruff check src/kylinbootlab/experiments/orchestrator.py tests/test_experiments_orchestrator.py
uv run mypy src/kylinbootlab/experiments/orchestrator.py tests/test_experiments_orchestrator.py

git add src/kylinbootlab/experiments/orchestrator.py tests/test_experiments_orchestrator.py
git commit -m "feat: add ExperimentOrchestrator with main loop"
```

---

### Task 8: Add CLI Subcommands

**Files:**
- Modify: `src/kylinbootlab/cli.py`

**Interfaces:**
- Consumes: `ExperimentQueue`, `ExperimentRecord`, `ExperimentOrchestrator`, `power_backend_factory`, `RunStore`
- Produces: `kbl experiment queue`, `kbl experiment run`, `kbl experiment status`, `kbl experiment retry`, `kbl experiment reset`

- [ ] **Step 1: Add CLI commands**

Replace `src/kylinbootlab/cli.py` with the complete file including experiment commands (insert below the existing `collect` command):

```python
from pathlib import Path
from typing import Annotated
from uuid import UUID, uuid4

import typer

from kylinbootlab import __version__
from kylinbootlab.remote import SubprocessRunner, collect_target_run
from kylinbootlab.report import write_baseline_report
from kylinbootlab.store import RunStore

app = typer.Typer(no_args_is_help=True)
DataRoot = Annotated[Path, typer.Option(help="Immutable KylinBootLab run root")]

# -- Phase 1 commands --------------------------------------------------------

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


@app.command()
def collect(
    target: Annotated[str, typer.Option(help="SSH destination")]
    = "kbl@kbl-target.local",
    data_root: DataRoot = Path("var/runs"),
    incoming_root: Annotated[Path, typer.Option(help="Untrusted incoming bundle root")]
    = Path("var/incoming"),
    probe_cmd: Annotated[
        str,
        typer.Option(help="Path to kbl-bootprobe on the target"),
    ] = "/usr/local/bin/kbl-bootprobe",
    remote_dir: Annotated[
        str,
        typer.Option(help="Scratch directory for snapshots on the target"),
    ] = "/var/lib/kylinbootlab/runs",
) -> None:
    """Capture, retrieve, validate, and import one target boot."""
    run_id = uuid4()
    run_path = collect_target_run(
        target=target,
        run_id=run_id,
        incoming_root=incoming_root,
        store=RunStore(data_root),
        runner=SubprocessRunner(),
        probe_cmd=probe_cmd,
        remote_dir=remote_dir,
    )
    typer.echo(run_path.name)


# -- Phase 2 experiment commands ---------------------------------------------

experiment_app = typer.Typer(no_args_is_help=True)
app.add_typer(experiment_app, name="experiment")


@experiment_app.command()
def queue(
    profile: Annotated[str, typer.Option(help="Profile name")] = "baseline",
    count: Annotated[int, typer.Option(help="Number of experiments")] = 10,
    queue_file: Annotated[Path, typer.Option(help="Queue JSONL path")]
    = Path("var/experiments.jsonl"),
) -> None:
    """Enqueue N experiments at the given profile."""
    from datetime import UTC, datetime

    from kylinbootlab.experiments.contracts import ExperimentRecord
    from kylinbootlab.experiments.queue import ExperimentQueue

    q = ExperimentQueue(queue_file)
    records = [
        ExperimentRecord(
            exp_id=f"{profile}-{i:03d}",
            profile=profile,
            status="pending",
            created_at=datetime.now(UTC),
        )
        for i in range(count)
    ]
    q.enqueue(records)
    typer.echo(f"queued {count} experiments with profile '{profile}'")


@experiment_app.command()
def run_loop(
    target: Annotated[str, typer.Option(help="SSH destination")]
    = "kbl@192.168.19.128",
    data_root: DataRoot = Path("var/runs"),
    incoming_root: Annotated[Path, typer.Option(help="Incoming bundle root")]
    = Path("var/incoming"),
    queue_file: Annotated[Path, typer.Option(help="Queue JSONL path")]
    = Path("var/experiments.jsonl"),
    backend: Annotated[str, typer.Option(help="Power backend: vix | wol")]
    = "vix",
    vmx_path: Annotated[str | None, typer.Option(help="VMX path for VI/X backend")]
    = None,
    mac: Annotated[str | None, typer.Option(help="MAC address for WOL backend")]
    = None,
) -> None:
    """Run the experiment queue against a target."""
    from kylinbootlab.experiments.orchestrator import ExperimentOrchestrator
    from kylinbootlab.experiments.power import power_backend_factory
    from kylinbootlab.experiments.queue import ExperimentQueue

    kwargs: dict[str, str] = {}
    if vmx_path:
        kwargs["vmx_path"] = vmx_path
    if mac:
        kwargs["mac"] = mac

    power = power_backend_factory(backend, **kwargs)
    queue_obj = ExperimentQueue(queue_file)
    store = RunStore(data_root)

    orch = ExperimentOrchestrator(
        queue=queue_obj,
        store=store,
        power=power,
        target=target,
        incoming_root=incoming_root,
    )
    orch.run_queue()
    typer.echo("queue complete")


@experiment_app.command()
def status(
    queue_file: Annotated[Path, typer.Option(help="Queue JSONL path")]
    = Path("var/experiments.jsonl"),
) -> None:
    """Show current experiment queue status."""
    from collections import Counter

    from kylinbootlab.experiments.queue import ExperimentQueue

    q = ExperimentQueue(queue_file)
    records = q.list()
    counts = Counter(r.status for r in records)

    typer.echo(f"{len(records)} experiments")
    for st in ("pending", "running", "done", "failed", "skipped"):
        if counts[st]:
            typer.echo(f"  {st}: {counts[st]}")


@experiment_app.command()
def retry(
    exp_id: Annotated[str, typer.Argument(help="Experiment ID to retry")],
    queue_file: Annotated[Path, typer.Option(help="Queue JSONL path")]
    = Path("var/experiments.jsonl"),
) -> None:
    """Reset a single experiment back to pending for retry."""
    from kylinbootlab.experiments.queue import ExperimentQueue

    q = ExperimentQueue(queue_file)
    q.update(exp_id, status="pending", error=None, attempt=0)
    typer.echo(f"{exp_id} reset to pending")


@experiment_app.command()
def reset(
    status_filter: Annotated[str, typer.Option(
        "--status", help="Status to reset"
    )] = "failed",
    queue_file: Annotated[Path, typer.Option(help="Queue JSONL path")]
    = Path("var/experiments.jsonl"),
) -> None:
    """Reset all experiments with a given status back to pending."""
    from kylinbootlab.experiments.queue import ExperimentQueue

    q = ExperimentQueue(queue_file)
    q.reset(status=status_filter, new_status="pending")
    typer.echo(f"reset all '{status_filter}' → pending")
```

- [ ] **Step 2: Update test_cli.py with experiment command tests**

Append to `tests/test_cli.py`:

```python
def test_experiment_queue_command(tmp_path: Path) -> None:
    queue_file = tmp_path / "queue.jsonl"
    result = runner.invoke(
        app,
        ["experiment", "queue", "--profile", "baseline", "--count", "3",
         "--queue-file", str(queue_file)],
    )
    assert result.exit_code == 0
    assert queue_file.is_file()
    assert "queued 3 experiments" in result.stdout


def test_experiment_status_command(tmp_path: Path) -> None:
    queue_file = tmp_path / "queue.jsonl"
    # Queue first
    runner.invoke(
        app,
        ["experiment", "queue", "--count", "2", "--queue-file", str(queue_file)],
    )
    result = runner.invoke(
        app, ["experiment", "status", "--queue-file", str(queue_file)],
    )
    assert result.exit_code == 0
    assert "2 experiments" in result.stdout
    assert "pending: 2" in result.stdout


def test_experiment_retry_command(tmp_path: Path) -> None:
    queue_file = tmp_path / "queue.jsonl"
    runner.invoke(app, ["experiment", "queue", "--count", "1",
                         "--queue-file", str(queue_file)])
    # Mark as failed
    from kylinbootlab.experiments.queue import ExperimentQueue
    q = ExperimentQueue(queue_file)
    q.update("baseline-000", status="failed", error="test")

    result = runner.invoke(
        app, ["experiment", "retry", "baseline-000",
              "--queue-file", str(queue_file)],
    )
    assert result.exit_code == 0
    assert "reset to pending" in result.stdout
```

- [ ] **Step 3: Run all CLI tests**

Run:
```powershell
uv run pytest tests/test_cli.py -v
```
Expected: all tests (old + new) PASS.

- [ ] **Step 4: Run full test suite**

```powershell
uv run pytest tests/ -q --ignore=tests/test_rust_contract.py
```
Expected: all tests PASS.

- [ ] **Step 5: Commit**

```powershell
uv run ruff check src tests
uv run mypy src tests
git add src/kylinbootlab/cli.py tests/test_cli.py
git commit -m "feat: add kbl experiment CLI subcommands"
```

---

### Task 9: Target-Side Recovery Initialization Script

**Files:**
- Create: `scripts/target/prepare_recovery.sh`

- [ ] **Step 1: Write the recovery preparation script**

Create `scripts/target/prepare_recovery.sh`:

```bash
#!/usr/bin/env bash
set -euo pipefail

# prepare_recovery.sh — set up ostree recovery baseline for KylinBootLab
#
# Pins the current deployment as the recovery baseline.  After running
# this script, ``ostree admin status`` will show one deployment with
# ``Pinned: yes`` — the recovery target used by Phase 2 RecoveryManager.

if [[ $EUID -ne 0 ]]; then
  printf 'usage: sudo prepare_recovery.sh\n' >&2
  exit 64
fi

echo "=== Current ostree status ==="
ostree admin status

readonly current="$(ostree admin status | grep '^\*' | head -1 | awk '{print $2}')"
if [[ -z "$current" ]]; then
  printf 'error: could not determine current deployment\n' >&2
  exit 1
fi

echo ""
echo "Pinning deployment ${current} as recovery baseline ..."
ostree admin pin 0

echo ""
echo "=== Updated ostree status ==="
ostree admin status

echo ""
echo "Recovery baseline set. Verify with: ostree admin status"
echo "The pinned deployment will be used by Phase 2 RecoveryManager."
```

On the target, run:
```bash
sudo bash scripts/target/prepare_recovery.sh
```
Expected: the current deployment is pinned as recovery baseline.

- [ ] **Step 2: Validate script syntax**

```bash
bash -n scripts/target/prepare_recovery.sh
```
Expected: exit 0.

- [ ] **Step 3: Commit**

```powershell
git add scripts/target/prepare_recovery.sh
git commit -m "feat: add ostree recovery preparation script"
```

---

### Task 10: Quality Gates and Real-Target Acceptance

- [ ] **Step 1: Run the full quality gate**

```powershell
uv run python scripts/export_schema.py --check
uv run ruff check .
uv run mypy src tests
uv run pytest tests/ -q --ignore=tests/test_rust_contract.py
```
Expected: all exit 0.

- [ ] **Step 2: Verify kab experiment CLI help**

```powershell
uv run kbl experiment --help
```
Expected: lists queue, run, status, retry, reset subcommands.

- [ ] **Step 3: Run a 5-experiment dry-run against the real VM**

First, ensure the VM is running and SSH is reachable.

```powershell
# Create a queue
uv run kbl experiment queue --profile baseline --count 5

# Check status
uv run kbl experiment status

# Run (with VIX backend — requires VMX path)
uv run kbl experiment run --target kbl@192.168.19.128 --backend vix --vmx-path "C:\path\to\openkylin.vmx"

# Check results
uv run kbl experiment status
```

- [ ] **Step 4: Verify Phase 2 exit criteria**

- All Python tests pass (ruff, mypy, pytest).
- `kbl experiment queue/status/retry/reset` subcommands respond correctly.
- The experiment orchestrator loop completes without unhandled exceptions.
- On the real VM: 5+ experiments run end-to-end, each producing a valid RunStore entry.

- [ ] **Step 5: Record the Phase 2 commit**

```powershell
git log --oneline -10
git status --short
```
Expected: focused commits following the approved design spec.
