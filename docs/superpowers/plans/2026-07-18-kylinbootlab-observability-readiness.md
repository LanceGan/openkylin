# KylinBootLab Phase 3: Semantic Readiness & Observer Calibration Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Measure the four user-perceived readiness points (`T0`, `Tlogin-ready`, `Tsession`, `Tusable`) on a real openKylin boot via a dual-component Rust observer, and prove <1% benchmark-mode overhead via a three-group calibration protocol.

**Architecture:** One Rust binary (`kbl-bootprobe`) gains two long-running subcommands: `observe` (root systemd unit — replays journald from boot start, polls unit states, injects a real uinput login, writes a `ReadinessEvent` JSONL stream + boot_id-stamped done marker) and `usable-probe` (XDG autostart in the kbl session — process-group polling, AT-SPI enumeration, sentinel-app first-window timing, result file the root observer aggregates). Events ride back as a new optional snapshot artifact; `ProbeManifest` unchanged. Python gains `readiness.py` (T-point derivation), a report timeline section, `wait_for_observer_done` orchestrator gating, and `kbl calibrate`.

**Tech Stack:** Rust 1.85.1 (serde, toml, input-linux [linux-gated]), Python 3.12 (Pydantic 2, Typer), Phase 1/2 pipeline unchanged.

## Global Constraints

- Python 3.12+, Pydantic 2 strict (`extra="forbid"`), mypy strict, ruff clean; Rust 1.85.1, clippy `-D warnings`, fmt clean.
- `ProbeManifest` schema is **frozen** — readiness events enter as capture artifact `readiness-events`, `required: false`.
- All Python synchronous. Rust linux-only facilities (`journalctl` spawn, uinput, AT-SPI, `/proc` scan) gated `#[cfg(target_os = "linux")]`; pure-logic cores compile and test on Windows.
- Timestamps are `monotonic_ns` on the CLOCK_BOOTTIME axis. journald `__MONOTONIC_TIMESTAMP` is **microseconds** → ×1000.
- `kind` enum (13 values, verbatim): `observer_started / unit_active / greeter_started / greeter_ready / login_injected / session_opened / desktop_process_up / atspi_desktop_ready / sentinel_launched / sentinel_window_shown / usable / observer_timeout / error`. `source`: `journald / systemd / probe / atspi`.
- Timeouts (spec §8): greeter 90 s; injection→session 30 s (NO re-injection); session→usable 120 s; orchestrator `wait_for_observer_done` 300 s with fast-degrade (single probe of the `/var/lib/kylinbootlab/observe/enabled` marker — absent means the observer is intentionally off for this boot OR was never deployed; either way no done marker will ever appear, so the gate passes immediately).
- Observer toggling for calibration: `ConditionPathExists=/var/lib/kylinbootlab/observe/enabled` — marker in kbl-group-writable dir, no runtime sudo.
- Done marker `/var/lib/kylinbootlab/observe/done` **contains the boot_id**; consumers compare with current boot to reject stale markers.
- Password charset: lowercase letters + digits only.
- Phase 1/2 modules consumed not modified, EXCEPT: `snapshot.rs` (+1 capture spec), `main.rs` (+observe/usable-probe/readiness-fixture subcommands), `orchestrator.py` (+observer gate), `report.py`/template (+timeline), `cli.py` (+calibrate), `aliveness.py` (+wait_for_observer_done).

## File Map

```text
target/bootprobe/src/events.rs                 ReadinessEvent model + JSONL serialization (pure)
target/bootprobe/src/observe/mod.rs            observe orchestration + state machine driver (linux)
target/bootprobe/src/observe/config.rs         observe.toml parsing (pure)
target/bootprobe/src/observe/journal.rs        journald JSON parsing (pure) + follower spawn (linux)
target/bootprobe/src/observe/keymap.rs         char -> evdev keycode table (pure)
target/bootprobe/src/observe/uinput.rs         virtual keyboard + injection (linux)
target/bootprobe/src/observe/state.rs          readiness state machine (pure)
target/bootprobe/src/usable/mod.rs             usable-probe orchestration (linux paths)
target/bootprobe/src/usable/procscan.rs        process comm scanning (dir-parameterized, testable)
target/bootprobe/src/usable/atspi.rs           AT-SPI checks via busctl/dbus-send subprocess (linux)
target/bootprobe/src/main.rs                   + observe / usable-probe subcommands
target/bootprobe/src/snapshot.rs               + readiness-events capture spec
tests (rust): events.rs, observe_logic.rs, procscan.rs
src/kylinbootlab/readiness.py                  event parsing + T-point derivation
src/kylinbootlab/report.py + templates/        + readiness timeline
src/kylinbootlab/experiments/aliveness.py      + wait_for_observer_done
src/kylinbootlab/experiments/orchestrator.py   + observer gate step 2c
src/kylinbootlab/calibrate.py                  three-group calibration driver + stats
src/kylinbootlab/cli.py                        + kbl calibrate
tests (python): test_readiness.py, test_calibrate.py, orchestrator/report additions
tests/fixtures/readiness-events-v1.jsonl       cross-language fixture
scripts/target/kbl-observe.service             systemd unit
scripts/target/kbl-usable-probe.desktop        XDG autostart
scripts/target/install_observer.sh             one-sudo installer
docs/runbooks/observability-readiness.md       deploy + acceptance runbook
```

## Scope and Exit Criteria

Implements spec `docs/superpowers/specs/2026-07-18-kylinbootlab-observability-readiness.md` (3A + 3C). Complete when:

- `kbl-bootprobe observe` produces valid ReadinessEvent JSONL on openKylin: greeter detection -> uinput login -> session -> usable, with boot_id-stamped done marker.
- `kbl-bootprobe usable-probe` reports process group, AT-SPI enumeration (with documented degradation), sentinel first-window timing.
- Controller derives Tlogin-ready / Tsession / Tusable + sentinel latency into metrics.json and HTML; incomplete/absent data degrades cleanly.
- `kbl calibrate` runs bare/benchmark groups via the Phase 2 queue (diagnostic: documented manual toggle, recorded, never gated); benchmark < 1% on graphical_target_from_t0_ns and os_total_ns medians.
- Real-VM acceptance: full-chain login run; 10+10 calibration (plus optional manual diagnostic 10); wrong-password graceful timeout.

---

### Task 1: ReadinessEvent Model (Rust, pure)

**Files:**
- Create: `target/bootprobe/src/events.rs`
- Modify: `target/bootprobe/src/lib.rs` (add `pub mod events;`)
- Create: `target/bootprobe/tests/events.rs`

**Interfaces:**
- Produces: `ReadinessEvent { schema_version: u32, monotonic_ns: u64, kind: EventKind, detail: String, source: EventSource }`; `EventKind` (13 variants, serde `rename_all = "snake_case"`); `EventSource` (4 variants, snake_case); `ReadinessEvent::new(kind, source, monotonic_ns, detail) -> Self`; `ReadinessEvent::to_jsonl_line(&self) -> String` (compact single-line JSON).

- [ ] **Step 1: Write the failing test**

Create `target/bootprobe/tests/events.rs`:

```rust
use kbl_bootprobe::events::{EventKind, EventSource, ReadinessEvent};

#[test]
fn event_serializes_to_single_jsonl_line() {
    let event = ReadinessEvent::new(
        EventKind::GreeterStarted,
        EventSource::Journald,
        6_713_388_000,
        "lightdm start begin",
    );
    let line = event.to_jsonl_line();
    assert!(!line.contains('\n'));
    assert!(line.contains("\"schema_version\":1"));
    assert!(line.contains("\"kind\":\"greeter_started\""));
    assert!(line.contains("\"source\":\"journald\""));
    assert!(line.contains("\"monotonic_ns\":6713388000"));
}

#[test]
fn event_round_trips_through_serde() {
    let event = ReadinessEvent::new(
        EventKind::Usable, EventSource::Probe, 42_000_000_000, "all conditions met",
    );
    let decoded: ReadinessEvent = serde_json::from_str(&event.to_jsonl_line()).unwrap();
    assert_eq!(decoded, event);
}

#[test]
fn all_thirteen_kinds_serialize_snake_case() {
    let cases = [
        (EventKind::ObserverStarted, "observer_started"),
        (EventKind::UnitActive, "unit_active"),
        (EventKind::GreeterStarted, "greeter_started"),
        (EventKind::GreeterReady, "greeter_ready"),
        (EventKind::LoginInjected, "login_injected"),
        (EventKind::SessionOpened, "session_opened"),
        (EventKind::DesktopProcessUp, "desktop_process_up"),
        (EventKind::AtspiDesktopReady, "atspi_desktop_ready"),
        (EventKind::SentinelLaunched, "sentinel_launched"),
        (EventKind::SentinelWindowShown, "sentinel_window_shown"),
        (EventKind::Usable, "usable"),
        (EventKind::ObserverTimeout, "observer_timeout"),
        (EventKind::Error, "error"),
    ];
    for (kind, expected) in cases {
        let event = ReadinessEvent::new(kind, EventSource::Probe, 1, "");
        assert!(event.to_jsonl_line().contains(&format!("\"kind\":\"{expected}\"")));
    }
}

#[test]
fn unknown_fields_are_rejected() {
    let line = r#"{"schema_version":1,"monotonic_ns":1,"kind":"usable","detail":"","source":"probe","extra":true}"#;
    assert!(serde_json::from_str::<ReadinessEvent>(line).is_err());
}
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cargo test -p kbl-bootprobe --test events`
Expected: FAIL — module `events` does not exist.

- [ ] **Step 3: Implement events.rs**

Create `target/bootprobe/src/events.rs`:

```rust
//! ReadinessEvent v1 — one JSONL line per observed boot-readiness signal.
//! Timestamps are CLOCK_BOOTTIME nanoseconds.  The controller derives
//! T-points from these events; the raw stream is immutable.

use serde::{Deserialize, Serialize};

#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "snake_case")]
pub enum EventKind {
    ObserverStarted,
    UnitActive,
    GreeterStarted,
    GreeterReady,
    LoginInjected,
    SessionOpened,
    DesktopProcessUp,
    AtspiDesktopReady,
    SentinelLaunched,
    SentinelWindowShown,
    Usable,
    ObserverTimeout,
    Error,
}

#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "snake_case")]
pub enum EventSource {
    Journald,
    Systemd,
    Probe,
    Atspi,
}

#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct ReadinessEvent {
    pub schema_version: u32,
    pub monotonic_ns: u64,
    pub kind: EventKind,
    pub detail: String,
    pub source: EventSource,
}

impl ReadinessEvent {
    pub fn new(
        kind: EventKind,
        source: EventSource,
        monotonic_ns: u64,
        detail: impl Into<String>,
    ) -> Self {
        Self {
            schema_version: 1,
            monotonic_ns,
            kind,
            detail: detail.into(),
            source,
        }
    }

    /// Compact single-line JSON — the on-disk JSONL representation.
    pub fn to_jsonl_line(&self) -> String {
        serde_json::to_string(self).expect("ReadinessEvent serialization cannot fail")
    }
}
```

Add `pub mod events;` to `target/bootprobe/src/lib.rs`.

- [ ] **Step 4: Run tests + gates**

Run: `cargo test -p kbl-bootprobe --test events && cargo clippy --workspace --all-targets -- -D warnings && cargo fmt --all -- --check`
Expected: 4 tests pass, gates clean.

- [ ] **Step 5: Commit**

```bash
git add target/bootprobe/src/events.rs target/bootprobe/src/lib.rs target/bootprobe/tests/events.rs
git commit -m "feat: add ReadinessEvent v1 model"
```

---

### Task 2: Python ReadinessEvent Contract + T-Point Derivation

**Files:**
- Create: `src/kylinbootlab/readiness.py`
- Create: `tests/test_readiness.py`
- Create: `tests/fixtures/readiness-events-v1.jsonl`

**Interfaces:**
- Consumes: `ContractModel`, `ProbeManifest` from `kylinbootlab.contracts`; `load_command_capture` from `kylinbootlab.capture`; `BundleError` from `kylinbootlab.store`.
- Produces: `ReadinessEvent` (Pydantic mirror of Rust); `parse_events(text: str) -> list[ReadinessEvent]`; `ReadinessMetrics` with `status: Literal["complete","incomplete","absent"]`, `mode: str | None`, `login_ready_ns / session_ns / usable_ns / sentinel_first_window_ns: NonNegativeInt | None`; `derive_metrics(events) -> ReadinessMetrics`; `load_readiness(run_path: Path, manifest: ProbeManifest) -> ReadinessMetrics` (absent when artifact missing or failed).

Derivation rules (spec §5):
- `login_ready_ns` = max(greeter_ready, last unit_active of {dbus.service, NetworkManager.service, lightdm.service}) — None if any missing.
- `session_ns` = first session_opened; `usable_ns` = first usable.
- `sentinel_first_window_ns` = sentinel_window_shown - sentinel_launched.
- `status`: complete iff login_ready+session+usable all present AND no observer_timeout/error event; absent iff no events; else incomplete.
- `mode` parsed from observer_started detail `mode=<value>`.

- [ ] **Step 1: Write the cross-language fixture**

Create `tests/fixtures/readiness-events-v1.jsonl` — 13 lines, one realistic benchmark boot (values echo recon timings):

```jsonl
{"schema_version":1,"monotonic_ns":3000000000,"kind":"observer_started","detail":"mode=benchmark","source":"probe"}
{"schema_version":1,"monotonic_ns":6613388000,"kind":"greeter_started","detail":"lightdm start begin","source":"journald"}
{"schema_version":1,"monotonic_ns":7000000000,"kind":"unit_active","detail":"dbus.service","source":"systemd"}
{"schema_version":1,"monotonic_ns":7100000000,"kind":"unit_active","detail":"NetworkManager.service","source":"systemd"}
{"schema_version":1,"monotonic_ns":7200000000,"kind":"unit_active","detail":"lightdm.service","source":"systemd"}
{"schema_version":1,"monotonic_ns":8500000000,"kind":"greeter_ready","detail":"ukui-greeter first output","source":"journald"}
{"schema_version":1,"monotonic_ns":9000000000,"kind":"login_injected","detail":"password+enter via uinput","source":"probe"}
{"schema_version":1,"monotonic_ns":11500000000,"kind":"session_opened","detail":"session opened for user kbl","source":"journald"}
{"schema_version":1,"monotonic_ns":16000000000,"kind":"desktop_process_up","detail":"ukui-panel","source":"probe"}
{"schema_version":1,"monotonic_ns":16500000000,"kind":"atspi_desktop_ready","detail":"3 desktop children","source":"atspi"}
{"schema_version":1,"monotonic_ns":16600000000,"kind":"sentinel_launched","detail":"mate-terminal","source":"probe"}
{"schema_version":1,"monotonic_ns":18100000000,"kind":"sentinel_window_shown","detail":"mate-terminal window","source":"atspi"}
{"schema_version":1,"monotonic_ns":18100000000,"kind":"usable","detail":"all three conditions met","source":"probe"}
```

The fixture file must end with exactly one trailing newline — Task 8's byte-identity test compares `println!` output against it.

- [ ] **Step 2: Write the failing tests**

Create `tests/test_readiness.py`:

```python
from pathlib import Path

import pytest
from pydantic import ValidationError

from kylinbootlab.readiness import (
    ReadinessEvent,
    derive_metrics,
    parse_events,
)

FIXTURE = Path("tests/fixtures/readiness-events-v1.jsonl")


def fixture_events() -> list[ReadinessEvent]:
    return parse_events(FIXTURE.read_text(encoding="utf-8"))


def test_parse_events_reads_all_fixture_lines() -> None:
    events = fixture_events()
    assert len(events) == 13
    assert events[0].kind == "observer_started"
    assert events[-1].kind == "usable"
    assert events[1].monotonic_ns == 6_613_388_000


def test_parse_events_rejects_unknown_kind() -> None:
    bad = '{"schema_version":1,"monotonic_ns":1,"kind":"bogus","detail":"","source":"probe"}'
    with pytest.raises(ValidationError, match="kind"):
        parse_events(bad)


def test_parse_events_skips_blank_lines() -> None:
    text = FIXTURE.read_text(encoding="utf-8") + "\n\n"
    assert len(parse_events(text)) == 13


def test_derive_metrics_complete_run() -> None:
    metrics = derive_metrics(fixture_events())
    assert metrics.status == "complete"
    assert metrics.mode == "benchmark"
    assert metrics.login_ready_ns == 8_500_000_000  # max(greeter 8.5s, units <=7.2s)
    assert metrics.session_ns == 11_500_000_000
    assert metrics.usable_ns == 18_100_000_000
    assert metrics.sentinel_first_window_ns == 1_500_000_000


def test_derive_metrics_incomplete_on_timeout() -> None:
    events = fixture_events()[:6]  # through greeter_ready, no login
    events.append(
        ReadinessEvent(
            schema_version=1,
            monotonic_ns=98_500_000_000,
            kind="observer_timeout",
            detail="no session after injection",
            source="probe",
        )
    )
    metrics = derive_metrics(events)
    assert metrics.status == "incomplete"
    assert metrics.login_ready_ns == 8_500_000_000
    assert metrics.session_ns is None
    assert metrics.usable_ns is None


def test_derive_metrics_empty_is_absent() -> None:
    metrics = derive_metrics([])
    assert metrics.status == "absent"
    assert metrics.login_ready_ns is None


def test_derive_metrics_requires_all_three_units() -> None:
    events = [e for e in fixture_events() if e.detail != "NetworkManager.service"]
    metrics = derive_metrics(events)
    assert metrics.login_ready_ns is None
    assert metrics.status == "incomplete"
```

- [ ] **Step 3: Run to verify failure**

Run: `uv run pytest tests/test_readiness.py -v`
Expected: FAIL — `kylinbootlab.readiness` does not exist.

- [ ] **Step 4: Implement readiness.py**

Create `src/kylinbootlab/readiness.py`:

```python
"""ReadinessEvent parsing and T-point derivation.

The Rust observer emits an append-only JSONL event stream on the
CLOCK_BOOTTIME axis.  This module parses it and derives the four
user-perceived readiness points.  Raw events are immutable; every
metric here is recomputable from them.
"""

from pathlib import Path
from typing import Literal

from pydantic import NonNegativeInt

from kylinbootlab.capture import load_command_capture
from kylinbootlab.contracts import ContractModel, ProbeManifest
from kylinbootlab.store import BundleError

_REQUIRED_UNITS = frozenset(
    {"dbus.service", "NetworkManager.service", "lightdm.service"}
)

EventKind = Literal[
    "observer_started", "unit_active", "greeter_started", "greeter_ready",
    "login_injected", "session_opened", "desktop_process_up",
    "atspi_desktop_ready", "sentinel_launched", "sentinel_window_shown",
    "usable", "observer_timeout", "error",
]
EventSource = Literal["journald", "systemd", "probe", "atspi"]


class ReadinessEvent(ContractModel):
    """One observed readiness signal — mirrors Rust events.rs 1:1."""

    schema_version: Literal[1]
    monotonic_ns: NonNegativeInt
    kind: EventKind
    detail: str
    source: EventSource


class ReadinessMetrics(ContractModel):
    """Derived T-points for one boot.  All values are ns from T0."""

    schema_version: Literal[1] = 1
    status: Literal["complete", "incomplete", "absent"]
    mode: str | None = None
    login_ready_ns: NonNegativeInt | None = None
    session_ns: NonNegativeInt | None = None
    usable_ns: NonNegativeInt | None = None
    sentinel_first_window_ns: NonNegativeInt | None = None


def parse_events(text: str) -> list[ReadinessEvent]:
    """Parse a JSONL event stream, skipping blank lines."""
    return [
        ReadinessEvent.model_validate_json(line)
        for line in text.splitlines()
        if line.strip()
    ]


def _first(events: list[ReadinessEvent], kind: str) -> ReadinessEvent | None:
    return next((e for e in events if e.kind == kind), None)


def derive_metrics(events: list[ReadinessEvent]) -> ReadinessMetrics:
    """Derive T-points per spec §5 (rules in the Interfaces block above)."""
    if not events:
        return ReadinessMetrics(status="absent")

    started = _first(events, "observer_started")
    mode = None
    if started is not None and started.detail.startswith("mode="):
        mode = started.detail.removeprefix("mode=")

    greeter_ready = _first(events, "greeter_ready")
    active_units = {e.detail: e.monotonic_ns for e in events if e.kind == "unit_active"}
    login_ready_ns: int | None = None
    if greeter_ready is not None and _REQUIRED_UNITS <= set(active_units):
        login_ready_ns = max(
            greeter_ready.monotonic_ns,
            *(active_units[u] for u in _REQUIRED_UNITS),
        )

    session = _first(events, "session_opened")
    usable = _first(events, "usable")
    launched = _first(events, "sentinel_launched")
    shown = _first(events, "sentinel_window_shown")
    sentinel_ns: int | None = None
    if launched is not None and shown is not None:
        sentinel_ns = shown.monotonic_ns - launched.monotonic_ns

    complete = (
        login_ready_ns is not None
        and session is not None
        and usable is not None
        and not any(e.kind in {"observer_timeout", "error"} for e in events)
    )
    return ReadinessMetrics(
        status="complete" if complete else "incomplete",
        mode=mode,
        login_ready_ns=login_ready_ns,
        session_ns=session.monotonic_ns if session else None,
        usable_ns=usable.monotonic_ns if usable else None,
        sentinel_first_window_ns=sentinel_ns,
    )


def load_readiness(run_path: Path, manifest: ProbeManifest) -> ReadinessMetrics:
    """Load readiness metrics for a stored run.

    Returns ``status="absent"`` when the run predates the observer
    (no ``readiness-events`` artifact) or the capture failed/empty.
    """
    try:
        capture = load_command_capture(run_path, manifest, "readiness-events")
    except BundleError:
        return ReadinessMetrics(status="absent")
    if capture.exit_code != 0 or not capture.stdout.strip():
        return ReadinessMetrics(status="absent")
    return derive_metrics(parse_events(capture.stdout))
```

- [ ] **Step 5: Run tests + gates**

Run: `uv run pytest tests/test_readiness.py -v && uv run ruff check src tests && uv run mypy src tests`
Expected: 7 tests pass, ruff/mypy clean.

- [ ] **Step 6: Commit**

```bash
git add src/kylinbootlab/readiness.py tests/test_readiness.py tests/fixtures/readiness-events-v1.jsonl
git commit -m "feat: add ReadinessEvent contract and T-point derivation"
```

---

### Task 3: Observer Config (Rust, pure)

**Files:**
- Create: `target/bootprobe/src/observe/mod.rs` (module shell: `pub mod config;`)
- Create: `target/bootprobe/src/observe/config.rs`
- Modify: `target/bootprobe/src/lib.rs` (add `pub mod observe;`)
- Modify: `target/bootprobe/Cargo.toml` (add `toml = "0.8"` to `[dependencies]`)

**Interfaces:**
- Produces: state-dir file-name constants shared by both components and the controller: `ENABLED_MARKER = "enabled"`, `EVENTS_FILE = "current.jsonl"`, `DONE_MARKER = "done"`, `USABLE_RESULT_FILE = "usable-result.jsonl"`.
- Produces: `Mode` (`Benchmark` default | `Diagnostic`, serde snake_case) with `poll_interval_ms(self) -> u64` (500 | 50) and `as_str(self) -> &'static str`.
- Produces: `ObserveConfig { password: String, mode: Mode, target_user: String, sentinel_command: Vec<String>, desktop_processes: Vec<String>, greeter_ready_pattern: String, session_opened_pattern: String }` with `deny_unknown_fields`; `ObserveConfig::from_toml_str(input: &str) -> anyhow::Result<Self>` (rejects empty password, chars outside `[a-z0-9]`, empty sentinel_command); `ObserveConfig::probe_defaults() -> Self` (fallback for the session probe when the root-0600 file is unreadable); manual `Debug` impl that redacts the password.

Defaults: `mode = benchmark`, `target_user = "kbl"`, `sentinel_command = ["mate-terminal"]`, `desktop_processes = []` (populated at deployment — recon had no live graphical session to enumerate), `greeter_ready_pattern = "ukui-greeter"`, `session_opened_pattern = "session opened for user"`. Patterns live in config so acceptance can tune them against the real journal **without recompiling**.

**Spec §6 deviation (v1, deliberate):** v1 diagnostic = interval-only; process-tree snapshots and per-event journal context land with Phase 4 prep (3B deep tracing) where their consumer lives. `Mode::Diagnostic` in this phase changes nothing but the poll interval (500 → 50 ms) — do NOT add capture machinery now.

- [ ] **Step 1: Add the toml dependency**

In `target/bootprobe/Cargo.toml`, extend `[dependencies]` (alphabetical order):

```toml
toml = "0.8"
```

- [ ] **Step 2: Write the failing tests (inline unit tests)**

Create `target/bootprobe/src/observe/mod.rs`:

```rust
//! Observer component modules (`kbl-bootprobe observe`).

pub mod config;
```

Create `target/bootprobe/src/observe/config.rs` with ONLY the test module for now:

```rust
#[cfg(test)]
mod tests {
    use super::*;

    const FULL: &str = r#"
password = "kbl123"
mode = "diagnostic"
target_user = "kbl"
sentinel_command = ["mate-terminal", "--disable-factory"]
desktop_processes = ["ukui-panel", "ukui-settings-daemon"]
greeter_ready_pattern = "ukui-greeter"
session_opened_pattern = "session opened for user"
"#;

    #[test]
    fn full_config_parses() {
        let config = ObserveConfig::from_toml_str(FULL).unwrap();
        assert_eq!(config.mode, Mode::Diagnostic);
        assert_eq!(config.password, "kbl123");
        assert_eq!(config.sentinel_command[0], "mate-terminal");
        assert_eq!(config.desktop_processes.len(), 2);
    }

    #[test]
    fn minimal_config_applies_defaults() {
        let config = ObserveConfig::from_toml_str("password = \"secret9\"\n").unwrap();
        assert_eq!(config.mode, Mode::Benchmark);
        assert_eq!(config.target_user, "kbl");
        assert_eq!(config.sentinel_command, vec!["mate-terminal".to_owned()]);
        assert!(config.desktop_processes.is_empty());
        assert_eq!(config.greeter_ready_pattern, "ukui-greeter");
        assert_eq!(config.session_opened_pattern, "session opened for user");
    }

    #[test]
    fn poll_intervals_follow_mode() {
        assert_eq!(Mode::Benchmark.poll_interval_ms(), 500);
        assert_eq!(Mode::Diagnostic.poll_interval_ms(), 50);
        assert_eq!(Mode::Benchmark.as_str(), "benchmark");
        assert_eq!(Mode::Diagnostic.as_str(), "diagnostic");
    }

    #[test]
    fn empty_password_is_rejected() {
        let error = ObserveConfig::from_toml_str("password = \"\"\n").unwrap_err();
        assert!(error.to_string().contains("password"));
    }

    #[test]
    fn uppercase_password_is_rejected() {
        let error = ObserveConfig::from_toml_str("password = \"Secret1\"\n").unwrap_err();
        assert!(error.to_string().contains("unsupported character"));
    }

    #[test]
    fn symbol_password_is_rejected() {
        assert!(ObserveConfig::from_toml_str("password = \"abc!23\"\n").is_err());
    }

    #[test]
    fn unknown_keys_are_rejected() {
        let error =
            ObserveConfig::from_toml_str("password = \"abc123\"\nbogus = 1\n").unwrap_err();
        assert!(error.to_string().contains("invalid observe.toml"));
    }

    #[test]
    fn debug_output_redacts_password() {
        let config = ObserveConfig::from_toml_str("password = \"topsecret1\"\n").unwrap();
        let debug = format!("{config:?}");
        assert!(debug.contains("<redacted>"));
        assert!(!debug.contains("topsecret1"));
    }
}
```

Add `pub mod observe;` to `target/bootprobe/src/lib.rs` (after `pub mod model;`, alphabetical).

- [ ] **Step 3: Run tests to verify they fail**

Run: `cargo test -p kbl-bootprobe --lib`
Expected: FAIL — `ObserveConfig` / `Mode` do not exist.

- [ ] **Step 4: Implement config.rs**

Prepend to `target/bootprobe/src/observe/config.rs` (above the test module):

```rust
//! observe.toml — deployment-time configuration for both observer components.
//!
//! The file lives at `/etc/kylinbootlab/observe.toml`, root-owned 0600 (it
//! contains the login password).  The session-side usable-probe reads the
//! same file when readable and silently falls back to `probe_defaults()`
//! otherwise; nothing except the password is security-sensitive.

use anyhow::{Context, Result, bail};
use serde::Deserialize;

/// File names inside the observer state directory
/// (`/var/lib/kylinbootlab/observe`).  Shared by both binary components and
/// the Python controller (`aliveness.py`, `calibrate.py` marker toggling).
pub const ENABLED_MARKER: &str = "enabled";
pub const EVENTS_FILE: &str = "current.jsonl";
pub const DONE_MARKER: &str = "done";
pub const USABLE_RESULT_FILE: &str = "usable-result.jsonl";

#[derive(Debug, Clone, Copy, PartialEq, Eq, Default, Deserialize)]
#[serde(rename_all = "snake_case")]
pub enum Mode {
    #[default]
    Benchmark,
    Diagnostic,
}

impl Mode {
    /// Benchmark keeps polling light (spec §6): 500 ms; diagnostic densifies to 50 ms.
    pub fn poll_interval_ms(self) -> u64 {
        match self {
            Mode::Benchmark => 500,
            Mode::Diagnostic => 50,
        }
    }

    pub fn as_str(self) -> &'static str {
        match self {
            Mode::Benchmark => "benchmark",
            Mode::Diagnostic => "diagnostic",
        }
    }
}

#[derive(Clone, PartialEq, Eq, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct ObserveConfig {
    pub password: String,
    #[serde(default)]
    pub mode: Mode,
    #[serde(default = "default_target_user")]
    pub target_user: String,
    #[serde(default = "default_sentinel_command")]
    pub sentinel_command: Vec<String>,
    #[serde(default)]
    pub desktop_processes: Vec<String>,
    #[serde(default = "default_greeter_ready_pattern")]
    pub greeter_ready_pattern: String,
    #[serde(default = "default_session_opened_pattern")]
    pub session_opened_pattern: String,
}

fn default_target_user() -> String {
    "kbl".to_owned()
}

fn default_sentinel_command() -> Vec<String> {
    vec!["mate-terminal".to_owned()]
}

fn default_greeter_ready_pattern() -> String {
    "ukui-greeter".to_owned()
}

fn default_session_opened_pattern() -> String {
    "session opened for user".to_owned()
}

impl ObserveConfig {
    pub fn from_toml_str(input: &str) -> Result<Self> {
        let config: Self = toml::from_str(input).context("invalid observe.toml")?;
        if config.password.is_empty() {
            bail!("observe.toml: password must not be empty");
        }
        if let Some(bad) = config
            .password
            .chars()
            .find(|c| !c.is_ascii_lowercase() && !c.is_ascii_digit())
        {
            bail!(
                "observe.toml: password contains unsupported character {bad:?} \
                 (lowercase letters and digits only — spec keyboard-layout constraint)"
            );
        }
        if config.sentinel_command.is_empty() {
            bail!("observe.toml: sentinel_command must not be empty");
        }
        Ok(config)
    }

    /// Built-in defaults for the session-side probe when observe.toml is
    /// unreadable (root 0600).  The placeholder password is never used by
    /// the usable-probe.
    pub fn probe_defaults() -> Self {
        Self {
            password: "unused0".to_owned(),
            mode: Mode::default(),
            target_user: default_target_user(),
            sentinel_command: default_sentinel_command(),
            desktop_processes: Vec::new(),
            greeter_ready_pattern: default_greeter_ready_pattern(),
            session_opened_pattern: default_session_opened_pattern(),
        }
    }
}

/// Redact the password anywhere Debug output could leak it (logs, panics).
impl std::fmt::Debug for ObserveConfig {
    fn fmt(&self, formatter: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        formatter
            .debug_struct("ObserveConfig")
            .field("password", &"<redacted>")
            .field("mode", &self.mode)
            .field("target_user", &self.target_user)
            .field("sentinel_command", &self.sentinel_command)
            .field("desktop_processes", &self.desktop_processes)
            .field("greeter_ready_pattern", &self.greeter_ready_pattern)
            .field("session_opened_pattern", &self.session_opened_pattern)
            .finish()
    }
}
```

- [ ] **Step 5: Run tests + gates**

Run: `cargo test -p kbl-bootprobe --lib && cargo clippy --workspace --all-targets -- -D warnings && cargo fmt --all -- --check`
Expected: 8 unit tests pass, gates clean.

- [ ] **Step 6: Commit**

```bash
git add target/bootprobe/Cargo.toml target/bootprobe/src/lib.rs target/bootprobe/src/observe
git commit -m "feat: add observe.toml config model"
```

---

### Task 4: Journald Parsing (Rust, pure core + linux follower)

**Files:**
- Create: `target/bootprobe/src/observe/journal.rs`
- Modify: `target/bootprobe/src/observe/mod.rs` (add `pub mod journal;`)
- Create: `target/bootprobe/tests/observe_logic.rs`

**Interfaces:**
- Produces: `JournalLine { monotonic_ns: u64, unit: Option<String>, comm: Option<String>, message: String }`.
- Produces: `parse_journal_json(line: &str) -> Option<JournalLine>` — tolerant: `__MONOTONIC_TIMESTAMP` may be a JSON string or number (journald exports **microseconds** → ×1000 to ns); `MESSAGE` may be a string or a byte array (non-UTF-8 payloads → `from_utf8_lossy`); missing `_SYSTEMD_UNIT`/`_COMM` tolerated; garbage → `None`, never an abort.
- Produces (linux-only): `spawn_journal_follower() -> anyhow::Result<std::process::Child>` running `journalctl -b 0 -f -o json --no-pager` with piped stdout, `PATH=FIXED_PATH`, `LC_ALL=C`.

**Key insight (state in code comments):** `-b 0 -f` REPLAYS every entry since boot start before following live, so a late observer start loses no greeter/PAM signal and every entry keeps its original `__MONOTONIC_TIMESTAMP`. Only the uinput injection is live-timing-sensitive.

- [ ] **Step 1: Write the failing tests**

Create `target/bootprobe/tests/observe_logic.rs`:

```rust
use kbl_bootprobe::observe::journal::parse_journal_json;

const LIGHTDM_LINE: &str = r#"{"__MONOTONIC_TIMESTAMP":"6613388","_SYSTEMD_UNIT":"lightdm.service","_COMM":"ukui-greeter","SYSLOG_IDENTIFIER":"lightdm","MESSAGE":"start begin!!"}"#;
const PAM_LINE: &str = r#"{"__MONOTONIC_TIMESTAMP":"11500000","_SYSTEMD_UNIT":"lightdm.service","_COMM":"lightdm","MESSAGE":"pam_unix(lightdm:session): session opened for user kbl(uid=1000) by (uid=0)"}"#;

#[test]
fn parses_lightdm_line_with_microsecond_conversion() {
    let line = parse_journal_json(LIGHTDM_LINE).unwrap();
    assert_eq!(line.monotonic_ns, 6_613_388_000); // journald µs -> ns (x1000)
    assert_eq!(line.unit.as_deref(), Some("lightdm.service"));
    assert_eq!(line.comm.as_deref(), Some("ukui-greeter"));
    assert_eq!(line.message, "start begin!!");
}

#[test]
fn parses_pam_session_line() {
    let line = parse_journal_json(PAM_LINE).unwrap();
    assert_eq!(line.monotonic_ns, 11_500_000_000);
    assert!(line.message.contains("session opened for user kbl"));
}

#[test]
fn parses_numeric_monotonic_timestamp() {
    let raw = r#"{"__MONOTONIC_TIMESTAMP":6613388,"MESSAGE":"hello"}"#;
    assert_eq!(parse_journal_json(raw).unwrap().monotonic_ns, 6_613_388_000);
}

#[test]
fn decodes_byte_array_message_lossily() {
    let raw = r#"{"__MONOTONIC_TIMESTAMP":"1000","MESSAGE":[104,105,255]}"#;
    let line = parse_journal_json(raw).unwrap();
    assert!(line.message.starts_with("hi"));
}

#[test]
fn missing_unit_and_comm_are_tolerated() {
    let raw = r#"{"__MONOTONIC_TIMESTAMP":"1000","MESSAGE":"kernel: hello"}"#;
    let line = parse_journal_json(raw).unwrap();
    assert_eq!(line.unit, None);
    assert_eq!(line.comm, None);
}

#[test]
fn garbage_lines_yield_none() {
    assert!(parse_journal_json("not json").is_none());
    assert!(parse_journal_json("{}").is_none());
    assert!(parse_journal_json(r#"{"MESSAGE":"no timestamp"}"#).is_none());
    assert!(parse_journal_json(r#"{"__MONOTONIC_TIMESTAMP":"x","MESSAGE":"bad"}"#).is_none());
}
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cargo test -p kbl-bootprobe --test observe_logic`
Expected: FAIL — module `journal` does not exist.

- [ ] **Step 3: Implement journal.rs**

Create `target/bootprobe/src/observe/journal.rs`:

```rust
//! journald JSON parsing (pure) and the boot-replay follower (linux).
//!
//! The follower runs `journalctl -b 0 -f -o json`: it REPLAYS every entry
//! since boot start before following live, so even if the observer unit
//! starts late no greeter/PAM signal is lost, and every entry keeps its
//! original `__MONOTONIC_TIMESTAMP`.  Only uinput injection is
//! live-timing-sensitive.

use serde_json::Value;

/// One journal entry reduced to the fields the state machine needs.
/// `monotonic_ns` is CLOCK_BOOTTIME nanoseconds (journald exports
/// microseconds; converted here — spec constraint ×1000).
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct JournalLine {
    pub monotonic_ns: u64,
    pub unit: Option<String>,
    pub comm: Option<String>,
    pub message: String,
}

/// Parse one `journalctl -o json` line.  Returns `None` for anything that
/// does not carry both a monotonic timestamp and a message — the follower
/// skips noise, it never aborts the observation.
pub fn parse_journal_json(line: &str) -> Option<JournalLine> {
    let value: Value = serde_json::from_str(line).ok()?;
    let object = value.as_object()?;

    let monotonic_us = match object.get("__MONOTONIC_TIMESTAMP")? {
        Value::String(text) => text.parse::<u64>().ok()?,
        Value::Number(number) => number.as_u64()?,
        _ => return None,
    };
    let message = match object.get("MESSAGE")? {
        Value::String(text) => text.clone(),
        // journald exports non-UTF-8 payloads as byte arrays.
        Value::Array(bytes) => {
            let raw: Vec<u8> = bytes
                .iter()
                .filter_map(|byte| byte.as_u64().and_then(|v| u8::try_from(v).ok()))
                .collect();
            String::from_utf8_lossy(&raw).into_owned()
        }
        _ => return None,
    };

    let field = |name: &str| object.get(name).and_then(Value::as_str).map(str::to_owned);
    Some(JournalLine {
        monotonic_ns: monotonic_us * 1000,
        unit: field("_SYSTEMD_UNIT"),
        comm: field("_COMM"),
        message,
    })
}

#[cfg(target_os = "linux")]
pub fn spawn_journal_follower() -> anyhow::Result<std::process::Child> {
    use std::process::{Command, Stdio};

    use anyhow::Context;

    use crate::capture::FIXED_PATH;

    Command::new("journalctl")
        .args(["-b", "0", "-f", "-o", "json", "--no-pager"])
        .env("PATH", FIXED_PATH)
        .env("LC_ALL", "C")
        .stdout(Stdio::piped())
        .stderr(Stdio::null())
        .spawn()
        .context("failed to spawn journalctl follower")
}
```

Add `pub mod journal;` to `target/bootprobe/src/observe/mod.rs`.

- [ ] **Step 4: Run tests + gates (including the linux cross-check)**

One-time setup on the Windows dev box (validates linux-gated code without a VM):

Run: `rustup target add x86_64-unknown-linux-gnu`

Then:

Run: `cargo test -p kbl-bootprobe --test observe_logic && cargo clippy --workspace --all-targets -- -D warnings && cargo check -p kbl-bootprobe --target x86_64-unknown-linux-gnu && cargo fmt --all -- --check`
Expected: 6 tests pass, clippy clean, linux target type-checks, fmt clean.

- [ ] **Step 5: Commit**

```bash
git add target/bootprobe/src/observe/journal.rs target/bootprobe/src/observe/mod.rs target/bootprobe/tests/observe_logic.rs
git commit -m "feat: add journald JSON parsing and boot-replay follower"
```

---

### Task 5: Keymap + uinput Virtual Keyboard (Rust)

**Files:**
- Create: `target/bootprobe/src/observe/keymap.rs` (pure)
- Create: `target/bootprobe/src/observe/uinput.rs` (linux-gated, `#![cfg(target_os = "linux")]`)
- Modify: `target/bootprobe/src/observe/mod.rs` (add `pub mod keymap;` and `pub mod uinput;`)
- Modify: `target/bootprobe/Cargo.toml` (add `input-linux = "0.7"` under linux target deps)
- Modify: `target/bootprobe/tests/observe_logic.rs` (append keymap tests)

**Interfaces:**
- Produces (keymap, pure): `pub const KEY_ENTER: u16 = 28`; `keycode_for(character: char) -> Option<u16>` for `[a-z0-9]` using Linux input-event-codes values (a=30, z=44, 1=2, 0=11, ...), `None` for uppercase/symbols; `login_keycodes(password: &str) -> Option<Vec<u16>>` (password chars then Enter); `all_supported_keycodes() -> Vec<u16>` (full charset + Enter, used for device registration).
- Produces (uinput, linux): `UinputKeyboard::create() -> anyhow::Result<Self>` — opens `/dev/uinput` (**this IS the Tlogin-ready injection self-check gate**), registers EV_KEY + EV_SYN + all charset keys + Enter, creates the device, sleeps 500 ms so X11 enumerates it; `type_password_and_enter(&mut self, password: &str) -> anyhow::Result<()>` — press+release per key with 50 ms inter-key delay and a SYN_REPORT after each event; `Drop` destroys the device.
- Dependency note (binding): use `input-linux = "0.7"`. If its API fights at implementation time, the documented fallback is raw `nix` ioctls (`ui_set_evbit`, `ui_set_keybit`, `ui_dev_setup`, `ui_dev_create`, then `write(2)` of `input_event` structs) — the implementer may switch internals but MUST keep the public `UinputKeyboard` interface above.

- [ ] **Step 1: Write the failing keymap tests**

Append to `target/bootprobe/tests/observe_logic.rs`:

```rust
mod keymap_tests {
    use kbl_bootprobe::observe::keymap::{KEY_ENTER, keycode_for, login_keycodes};

    #[test]
    fn maps_letters_and_digits_to_evdev_codes() {
        // Values from <linux/input-event-codes.h>.
        let cases = [
            ('a', 30),
            ('s', 31),
            ('l', 38),
            ('z', 44),
            ('m', 50),
            ('q', 16),
            ('p', 25),
            ('1', 2),
            ('9', 10),
            ('0', 11),
        ];
        for (character, expected) in cases {
            assert_eq!(keycode_for(character), Some(expected), "char {character:?}");
        }
    }

    #[test]
    fn rejects_unsupported_characters() {
        for character in ['A', 'Z', '!', ' ', '-', '_', 'é'] {
            assert_eq!(keycode_for(character), None, "char {character:?}");
        }
    }

    #[test]
    fn login_sequence_is_password_then_enter() {
        let codes = login_keycodes("kbl123").unwrap();
        assert_eq!(codes, vec![37, 48, 38, 2, 3, 4, KEY_ENTER]);
    }

    #[test]
    fn login_sequence_rejects_bad_charset() {
        assert!(login_keycodes("Pass!").is_none());
    }
}
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cargo test -p kbl-bootprobe --test observe_logic`
Expected: FAIL — module `keymap` does not exist (journal tests still pass).

- [ ] **Step 3: Implement keymap.rs**

Create `target/bootprobe/src/observe/keymap.rs`:

```rust
//! Character → Linux evdev key-code mapping for uinput injection.
//!
//! Only lowercase ASCII letters and digits are supported by design: the
//! test password is constrained to that charset (spec §10) so injection is
//! independent of keyboard layout (QWERTY scancode positions).

/// `KEY_ENTER` from `<linux/input-event-codes.h>`.
pub const KEY_ENTER: u16 = 28;

/// evdev codes are contiguous along physical QWERTY rows.
const ROWS: [(&str, u16); 3] = [
    ("qwertyuiop", 16), // KEY_Q..KEY_P
    ("asdfghjkl", 30),  // KEY_A..KEY_L
    ("zxcvbnm", 44),    // KEY_Z..KEY_M
];

/// evdev key code for one password character; `None` outside `[a-z0-9]`.
pub fn keycode_for(character: char) -> Option<u16> {
    match character {
        '0' => return Some(11),                                      // KEY_0
        '1'..='9' => return Some(character as u16 - '1' as u16 + 2), // KEY_1..KEY_9
        _ => {}
    }
    for (row, first) in ROWS {
        if let Some(index) = row.find(character) {
            return Some(first + u16::try_from(index).expect("row index fits in u16"));
        }
    }
    None
}

/// Key sequence for a full login: every password character, then Enter.
/// `None` if any character falls outside the supported charset.
pub fn login_keycodes(password: &str) -> Option<Vec<u16>> {
    let mut codes: Vec<u16> = password.chars().map(keycode_for).collect::<Option<_>>()?;
    codes.push(KEY_ENTER);
    Some(codes)
}

/// Every key code the virtual keyboard must register (charset + Enter).
pub fn all_supported_keycodes() -> Vec<u16> {
    let mut codes: Vec<u16> = "abcdefghijklmnopqrstuvwxyz0123456789"
        .chars()
        .filter_map(keycode_for)
        .collect();
    codes.push(KEY_ENTER);
    codes
}
```

Add `pub mod keymap;` to `target/bootprobe/src/observe/mod.rs`.

- [ ] **Step 4: Run keymap tests**

Run: `cargo test -p kbl-bootprobe --test observe_logic`
Expected: 10 tests pass (6 journal + 4 keymap).

- [ ] **Step 5: Add the input-linux dependency and implement uinput.rs**

In `target/bootprobe/Cargo.toml`, extend the linux target section:

```toml
[target.'cfg(target_os = "linux")'.dependencies]
input-linux = "0.7"
nix = { version = "0.29.0", features = ["time"] }
```

Create `target/bootprobe/src/observe/uinput.rs`:

```rust
//! Virtual keyboard via /dev/uinput — types the real password into the real
//! greeter, driving genuine PAM authentication (no autologin shortcut).
#![cfg(target_os = "linux")]

use std::fs::{File, OpenOptions};
use std::thread::sleep;
use std::time::Duration;

use anyhow::{Context, Result};
use input_linux::{
    EventKind, EventTime, InputEvent, InputId, Key, KeyEvent, KeyState, SynchronizeEvent,
    SynchronizeKind, UInputHandle,
};

use crate::observe::keymap;

/// X11/libinput need a moment to enumerate a hot-plugged keyboard.
const DEVICE_SETTLE: Duration = Duration::from_millis(500);
/// Inter-key delay — far slower than the input pipeline, far faster than a human.
const KEY_DELAY: Duration = Duration::from_millis(50);

pub struct UinputKeyboard {
    handle: UInputHandle<File>,
}

impl UinputKeyboard {
    /// Open /dev/uinput and create the virtual device.
    ///
    /// This doubles as the injection self-check required by the
    /// Tlogin-ready gate (spec §4.2): success here proves keystrokes can be
    /// delivered.  Requires root — the kbl-observe.service unit provides it.
    pub fn create() -> Result<Self> {
        let file = OpenOptions::new()
            .read(true)
            .write(true)
            .open("/dev/uinput")
            .context("open /dev/uinput failed (observer must run as root)")?;
        let handle = UInputHandle::new(file);
        handle.set_evbit(EventKind::Key).context("EV_KEY")?;
        handle.set_evbit(EventKind::Synchronize).context("EV_SYN")?;
        for code in keymap::all_supported_keycodes() {
            let key = Key::from_code(code).context("unmapped key code")?;
            handle.set_keybit(key).context("UI_SET_KEYBIT")?;
        }
        let id = InputId {
            bustype: input_linux::sys::BUS_VIRTUAL,
            vendor: 0x4b42,  // "KB"
            product: 0x4c50, // "LP"
            version: 1,
        };
        handle
            .create(&id, b"kbl-bootprobe-virtual-keyboard", 0, &[])
            .context("UI_DEV_CREATE failed")?;
        sleep(DEVICE_SETTLE);
        Ok(Self { handle })
    }

    /// Type the password followed by Enter — exactly once.  The caller must
    /// never retry a failed login (account-lockout protection, spec §8).
    pub fn type_password_and_enter(&mut self, password: &str) -> Result<()> {
        let codes = keymap::login_keycodes(password)
            .context("password contains characters outside [a-z0-9]")?;
        for code in codes {
            let key = Key::from_code(code).context("unmapped key code")?;
            self.emit(key, KeyState::PRESSED)?;
            sleep(KEY_DELAY);
            self.emit(key, KeyState::RELEASED)?;
            sleep(KEY_DELAY);
        }
        Ok(())
    }

    fn emit(&mut self, key: Key, state: KeyState) -> Result<()> {
        let time = EventTime::new(0, 0);
        let events = [
            *InputEvent::from(KeyEvent::new(time, key, state)).as_raw(),
            *InputEvent::from(SynchronizeEvent::new(time, SynchronizeKind::Report, 0)).as_raw(),
        ];
        self.handle.write(&events).context("uinput write failed")?;
        Ok(())
    }
}

impl Drop for UinputKeyboard {
    fn drop(&mut self) {
        let _ = self.handle.dev_destroy();
    }
}
```

Add `pub mod uinput;` to `target/bootprobe/src/observe/mod.rs` (the file-level `#![cfg]` empties it on non-linux, so the unconditional declaration is safe).

uinput has NO unit tests — it needs a real `/dev/uinput` and is covered by the real-VM acceptance in Task 13.

- [ ] **Step 6: Run gates (linux cross-check is the real compile test here)**

Run: `cargo test -p kbl-bootprobe --test observe_logic && cargo check -p kbl-bootprobe --target x86_64-unknown-linux-gnu && cargo clippy -p kbl-bootprobe --all-targets --target x86_64-unknown-linux-gnu -- -D warnings && cargo clippy --workspace --all-targets -- -D warnings && cargo fmt --all -- --check`
Expected: 10 tests pass; the linux-target check/clippy compiles uinput.rs. If input-linux 0.7 signatures differ from the code above, fix call sites here (or switch to the documented nix-ioctl fallback) while keeping the `UinputKeyboard` public interface.

- [ ] **Step 7: Commit**

```bash
git add target/bootprobe/Cargo.toml target/bootprobe/src/observe/keymap.rs target/bootprobe/src/observe/uinput.rs target/bootprobe/src/observe/mod.rs target/bootprobe/tests/observe_logic.rs
git commit -m "feat: add keymap and uinput virtual keyboard"
```

---

### Task 6: Readiness State Machine (Rust, pure) + observe Driver (linux)

**Files:**
- Create: `target/bootprobe/src/observe/state.rs` (pure)
- Modify: `target/bootprobe/src/observe/mod.rs` (add `pub mod state;` + `run_observe` driver)
- Modify: `target/bootprobe/tests/observe_logic.rs` (append `mod state_machine` tests)

**Interfaces:**
- Produces (state.rs, pure — no I/O, no clocks):
  - Constants: `GREETER_TIMEOUT_NS: u64 = 90_000_000_000`, `SESSION_TIMEOUT_NS: u64 = 30_000_000_000`, `USABLE_TIMEOUT_NS: u64 = 120_000_000_000` (spec §8); `REQUIRED_UNITS: [&str; 3] = ["dbus.service", "NetworkManager.service", "lightdm.service"]` (MUST stay aligned with `_REQUIRED_UNITS` in `src/kylinbootlab/readiness.py`); `ATSPI_UNAVAILABLE: &str = "atspi_unavailable"` (degradation marker embedded in event details, spec §8).
  - `Signal` enum: `Journal(JournalLine)`, `UnitActive { unit: String, monotonic_ns: u64 }`, `UinputReady { monotonic_ns: u64 }`, `LoginInjected { monotonic_ns: u64 }`, `UsableResult { events: Vec<ReadinessEvent>, monotonic_ns: u64 }`, `Tick { monotonic_ns: u64 }`.
  - `ReadinessState::new(started_ns: u64, config: &ObserveConfig) -> Self`; `feed(&mut self, signal: Signal) -> Vec<ReadinessEvent>`; `take_injection_request(&mut self) -> bool` (true exactly once when the Tlogin-ready gate opens — latches, guaranteeing single injection); `finished(&self) -> bool`.
- Produces (mod.rs): `run_observe(config_path: &Path, state_dir: &Path) -> anyhow::Result<()>` — linux driver; non-linux stub bails (same pattern as `system.rs`).

Matching rules (spec §4.2/§5, patterns from config so acceptance can tune without recompile):
- `greeter_started`: first line with `unit == "lightdm.service"` AND message contains `"start begin"` (recon: ukui-greeter logs `start begin!!` under the lightdm unit).
- `greeter_ready`: first line whose `comm` or message contains `greeter_ready_pattern` (default `ukui-greeter`).
- `session_opened`: message contains `"{session_opened_pattern} {target_user}"` AND `unit == "lightdm.service"`. The unit filter is load-bearing: the controller polls over SSH during boot and **sshd logs the same PAM phrase** — without the filter, an SSH login would fake an early Tsession.
- Injection gate: greeter_ready seen AND all 3 units active AND uinput self-check passed → inject once. NO re-injection ever.
- Timeouts on `Tick`: no gate within 90 s of start → `observer_timeout` + finish; no session within 30 s of injection → `error` (wrong password / keymap, spec §8) + finish; no usable-result within 120 s of session → `observer_timeout` + finish.
- `UsableResult`: re-emit the probe's events verbatim, then emit the final `usable` event iff no `error` event is present AND (a `sentinel_window_shown` exists → detail `"all three conditions met"`, or any detail contains `atspi_unavailable` → detail `"process group only (atspi_unavailable)"`); `usable` timestamp = max event timestamp. Always finish.

- [ ] **Step 1: Write the failing state-machine tests**

Append to `target/bootprobe/tests/observe_logic.rs` (self-contained module — no edits to existing imports):

```rust
mod state_machine {
    use kbl_bootprobe::events::{EventKind, EventSource, ReadinessEvent};
    use kbl_bootprobe::observe::config::ObserveConfig;
    use kbl_bootprobe::observe::journal::JournalLine;
    use kbl_bootprobe::observe::state::{
        GREETER_TIMEOUT_NS, ReadinessState, SESSION_TIMEOUT_NS, Signal, USABLE_TIMEOUT_NS,
    };

    const START_NS: u64 = 3_000_000_000;

    fn config() -> ObserveConfig {
        ObserveConfig::from_toml_str("password = \"kbl123\"\n").unwrap()
    }

    fn journal(monotonic_ns: u64, unit: Option<&str>, comm: Option<&str>, message: &str) -> Signal {
        Signal::Journal(JournalLine {
            monotonic_ns,
            unit: unit.map(str::to_owned),
            comm: comm.map(str::to_owned),
            message: message.to_owned(),
        })
    }

    fn unit_active(unit: &str, monotonic_ns: u64) -> Signal {
        Signal::UnitActive {
            unit: unit.to_owned(),
            monotonic_ns,
        }
    }

    /// Drive greeter + units + uinput so the injection gate is satisfied.
    fn open_gate(state: &mut ReadinessState) -> Vec<ReadinessEvent> {
        let mut emitted = Vec::new();
        emitted.extend(state.feed(journal(
            6_613_388_000,
            Some("lightdm.service"),
            Some("lightdm"),
            "start begin!!",
        )));
        emitted.extend(state.feed(journal(
            8_500_000_000,
            Some("lightdm.service"),
            Some("ukui-greeter"),
            "load user list done",
        )));
        emitted.extend(state.feed(unit_active("dbus.service", 7_000_000_000)));
        emitted.extend(state.feed(unit_active("NetworkManager.service", 7_100_000_000)));
        emitted.extend(state.feed(unit_active("lightdm.service", 7_200_000_000)));
        emitted.extend(state.feed(Signal::UinputReady {
            monotonic_ns: 4_000_000_000,
        }));
        emitted
    }

    #[test]
    fn happy_path_reaches_usable() {
        let mut state = ReadinessState::new(START_NS, &config());
        let gate_events = open_gate(&mut state);
        let kinds: Vec<EventKind> = gate_events.iter().map(|e| e.kind).collect();
        assert_eq!(
            kinds,
            vec![
                EventKind::GreeterStarted,
                EventKind::GreeterReady,
                EventKind::UnitActive,
                EventKind::UnitActive,
                EventKind::UnitActive,
            ]
        );

        assert!(state.take_injection_request());
        assert!(!state.take_injection_request(), "injection must latch");

        let injected = state.feed(Signal::LoginInjected {
            monotonic_ns: 9_000_000_000,
        });
        assert_eq!(injected[0].kind, EventKind::LoginInjected);

        let session = state.feed(journal(
            11_500_000_000,
            Some("lightdm.service"),
            Some("lightdm"),
            "pam_unix(lightdm:session): session opened for user kbl(uid=1000) by (uid=0)",
        ));
        assert_eq!(session[0].kind, EventKind::SessionOpened);
        assert_eq!(session[0].monotonic_ns, 11_500_000_000);

        let probe_events = vec![
            ReadinessEvent::new(
                EventKind::DesktopProcessUp,
                EventSource::Probe,
                16_000_000_000,
                "ukui-panel",
            ),
            ReadinessEvent::new(
                EventKind::AtspiDesktopReady,
                EventSource::Atspi,
                16_500_000_000,
                "3 desktop children",
            ),
            ReadinessEvent::new(
                EventKind::SentinelLaunched,
                EventSource::Probe,
                16_600_000_000,
                "mate-terminal",
            ),
            ReadinessEvent::new(
                EventKind::SentinelWindowShown,
                EventSource::Atspi,
                18_100_000_000,
                "mate-terminal window",
            ),
        ];
        let merged = state.feed(Signal::UsableResult {
            events: probe_events,
            monotonic_ns: 18_200_000_000,
        });
        assert_eq!(merged.len(), 5);
        let usable = merged.last().unwrap();
        assert_eq!(usable.kind, EventKind::Usable);
        assert_eq!(usable.monotonic_ns, 18_100_000_000); // max probe timestamp
        assert_eq!(usable.detail, "all three conditions met");
        assert!(state.finished());
    }

    #[test]
    fn sshd_session_line_is_ignored() {
        let mut state = ReadinessState::new(START_NS, &config());
        open_gate(&mut state);
        let emitted = state.feed(journal(
            5_000_000_000,
            Some("ssh.service"),
            Some("sshd"),
            "pam_unix(sshd:session): session opened for user kbl(uid=1000) by (uid=0)",
        ));
        assert!(emitted.is_empty(), "sshd PAM lines must not fake Tsession");
    }

    #[test]
    fn injection_gate_requires_all_three_units() {
        let mut state = ReadinessState::new(START_NS, &config());
        state.feed(journal(
            8_500_000_000,
            Some("lightdm.service"),
            Some("ukui-greeter"),
            "greeter up",
        ));
        state.feed(Signal::UinputReady {
            monotonic_ns: 4_000_000_000,
        });
        state.feed(unit_active("dbus.service", 7_000_000_000));
        state.feed(unit_active("lightdm.service", 7_200_000_000));
        assert!(!state.take_injection_request());
        state.feed(unit_active("NetworkManager.service", 7_300_000_000));
        assert!(state.take_injection_request());
    }

    #[test]
    fn duplicate_and_foreign_unit_signals_emit_nothing() {
        let mut state = ReadinessState::new(START_NS, &config());
        assert_eq!(state.feed(unit_active("dbus.service", 7_000_000_000)).len(), 1);
        assert!(state.feed(unit_active("dbus.service", 7_500_000_000)).is_empty());
        assert!(state.feed(unit_active("cron.service", 7_600_000_000)).is_empty());
    }

    #[test]
    fn greeter_timeout_fires_at_90s() {
        let mut state = ReadinessState::new(START_NS, &config());
        assert!(state
            .feed(Signal::Tick {
                monotonic_ns: START_NS + GREETER_TIMEOUT_NS - 1,
            })
            .is_empty());
        let emitted = state.feed(Signal::Tick {
            monotonic_ns: START_NS + GREETER_TIMEOUT_NS,
        });
        assert_eq!(emitted[0].kind, EventKind::ObserverTimeout);
        assert!(state.finished());
        assert!(state.feed(unit_active("dbus.service", 1)).is_empty());
    }

    #[test]
    fn injection_timeout_emits_error_and_never_retries() {
        let mut state = ReadinessState::new(START_NS, &config());
        open_gate(&mut state);
        assert!(state.take_injection_request());
        state.feed(Signal::LoginInjected {
            monotonic_ns: 9_000_000_000,
        });
        let emitted = state.feed(Signal::Tick {
            monotonic_ns: 9_000_000_000 + SESSION_TIMEOUT_NS,
        });
        assert_eq!(emitted[0].kind, EventKind::Error);
        assert!(state.finished());
        assert!(!state.take_injection_request());
    }

    #[test]
    fn usable_timeout_fires_120s_after_session() {
        let mut state = ReadinessState::new(START_NS, &config());
        open_gate(&mut state);
        assert!(state.take_injection_request());
        state.feed(Signal::LoginInjected {
            monotonic_ns: 9_000_000_000,
        });
        state.feed(journal(
            11_500_000_000,
            Some("lightdm.service"),
            Some("lightdm"),
            "pam_unix(lightdm:session): session opened for user kbl(uid=1000) by (uid=0)",
        ));
        let emitted = state.feed(Signal::Tick {
            monotonic_ns: 11_500_000_000 + USABLE_TIMEOUT_NS,
        });
        assert_eq!(emitted[0].kind, EventKind::ObserverTimeout);
        assert!(state.finished());
    }

    #[test]
    fn degraded_usable_result_still_emits_usable() {
        let mut state = ReadinessState::new(START_NS, &config());
        let probe_events = vec![ReadinessEvent::new(
            EventKind::DesktopProcessUp,
            EventSource::Probe,
            16_000_000_000,
            "process group complete (atspi_unavailable)",
        )];
        let merged = state.feed(Signal::UsableResult {
            events: probe_events,
            monotonic_ns: 16_100_000_000,
        });
        let usable = merged.last().unwrap();
        assert_eq!(usable.kind, EventKind::Usable);
        assert_eq!(usable.detail, "process group only (atspi_unavailable)");
        assert!(state.finished());
    }

    #[test]
    fn failed_usable_result_merges_without_usable() {
        let mut state = ReadinessState::new(START_NS, &config());
        let probe_events = vec![ReadinessEvent::new(
            EventKind::Error,
            EventSource::Probe,
            16_000_000_000,
            "sentinel window not observed before deadline",
        )];
        let merged = state.feed(Signal::UsableResult {
            events: probe_events,
            monotonic_ns: 16_100_000_000,
        });
        assert_eq!(merged.len(), 1);
        assert_eq!(merged[0].kind, EventKind::Error);
        assert!(state.finished());
    }
}
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cargo test -p kbl-bootprobe --test observe_logic`
Expected: FAIL — module `state` does not exist.

- [ ] **Step 3: Implement state.rs**

Create `target/bootprobe/src/observe/state.rs`:

```rust
//! Pure readiness state machine — every observation source feeds `Signal`s
//! in, `ReadinessEvent`s come out.  No I/O, no clocks: fully unit-testable.

use std::collections::BTreeSet;

use crate::events::{EventKind, EventSource, ReadinessEvent};
use crate::observe::config::ObserveConfig;
use crate::observe::journal::JournalLine;

/// Spec §8 timeouts, all on the CLOCK_BOOTTIME axis.
pub const GREETER_TIMEOUT_NS: u64 = 90_000_000_000;
pub const SESSION_TIMEOUT_NS: u64 = 30_000_000_000;
pub const USABLE_TIMEOUT_NS: u64 = 120_000_000_000;

/// Units that must be active before login injection (spec §4.2).
/// MUST stay aligned with `_REQUIRED_UNITS` in `src/kylinbootlab/readiness.py`.
pub const REQUIRED_UNITS: [&str; 3] =
    ["dbus.service", "NetworkManager.service", "lightdm.service"];

/// Degradation marker the usable-probe embeds in event details when AT-SPI
/// is unreachable (spec §8); the usable decision below recognises it.
pub const ATSPI_UNAVAILABLE: &str = "atspi_unavailable";

#[derive(Debug, Clone)]
pub enum Signal {
    Journal(JournalLine),
    UnitActive { unit: String, monotonic_ns: u64 },
    UinputReady { monotonic_ns: u64 },
    LoginInjected { monotonic_ns: u64 },
    UsableResult { events: Vec<ReadinessEvent>, monotonic_ns: u64 },
    Tick { monotonic_ns: u64 },
}

pub struct ReadinessState {
    started_ns: u64,
    greeter_ready_pattern: String,
    session_needle: String,
    greeter_started: bool,
    greeter_ready: bool,
    units_active: BTreeSet<String>,
    uinput_ready: bool,
    injection_requested: bool,
    injected_ns: Option<u64>,
    session_ns: Option<u64>,
    finished: bool,
}

impl ReadinessState {
    pub fn new(started_ns: u64, config: &ObserveConfig) -> Self {
        Self {
            started_ns,
            greeter_ready_pattern: config.greeter_ready_pattern.clone(),
            session_needle: format!(
                "{} {}",
                config.session_opened_pattern, config.target_user
            ),
            greeter_started: false,
            greeter_ready: false,
            units_active: BTreeSet::new(),
            uinput_ready: false,
            injection_requested: false,
            injected_ns: None,
            session_ns: None,
            finished: false,
        }
    }

    pub fn finished(&self) -> bool {
        self.finished
    }

    /// True exactly once, when the Tlogin-ready gate is satisfied:
    /// greeter ready + all three units active + uinput self-check passed.
    /// Latches — later calls return false (single-injection guarantee).
    pub fn take_injection_request(&mut self) -> bool {
        let due = !self.finished
            && !self.injection_requested
            && self.greeter_ready
            && self.uinput_ready
            && self.units_active.len() == REQUIRED_UNITS.len();
        if due {
            self.injection_requested = true;
        }
        due
    }

    pub fn feed(&mut self, signal: Signal) -> Vec<ReadinessEvent> {
        if self.finished {
            return Vec::new();
        }
        match signal {
            Signal::Journal(line) => self.on_journal(&line),
            Signal::UnitActive { unit, monotonic_ns } => {
                self.on_unit_active(&unit, monotonic_ns)
            }
            Signal::UinputReady { .. } => {
                self.uinput_ready = true;
                Vec::new()
            }
            Signal::LoginInjected { monotonic_ns } => {
                self.injected_ns = Some(monotonic_ns);
                vec![ReadinessEvent::new(
                    EventKind::LoginInjected,
                    EventSource::Probe,
                    monotonic_ns,
                    "password+enter via uinput",
                )]
            }
            Signal::UsableResult { events, monotonic_ns } => {
                self.on_usable(events, monotonic_ns)
            }
            Signal::Tick { monotonic_ns } => self.on_tick(monotonic_ns),
        }
    }

    fn on_journal(&mut self, line: &JournalLine) -> Vec<ReadinessEvent> {
        let mut emitted = Vec::new();
        let from_lightdm = line.unit.as_deref() == Some("lightdm.service");

        if !self.greeter_started && from_lightdm && line.message.contains("start begin") {
            self.greeter_started = true;
            emitted.push(ReadinessEvent::new(
                EventKind::GreeterStarted,
                EventSource::Journald,
                line.monotonic_ns,
                truncate(&line.message),
            ));
        }
        let ready_match = line
            .comm
            .as_deref()
            .is_some_and(|comm| comm.contains(&self.greeter_ready_pattern))
            || line.message.contains(&self.greeter_ready_pattern);
        if !self.greeter_ready && ready_match {
            self.greeter_ready = true;
            emitted.push(ReadinessEvent::new(
                EventKind::GreeterReady,
                EventSource::Journald,
                line.monotonic_ns,
                truncate(&line.message),
            ));
        }
        // Only lightdm's PAM stack counts: the controller polls over SSH
        // during boot and sshd logs the same "session opened for user kbl"
        // phrase — matching it would fake an early Tsession.
        if self.session_ns.is_none()
            && from_lightdm
            && line.message.contains(&self.session_needle)
        {
            self.session_ns = Some(line.monotonic_ns);
            emitted.push(ReadinessEvent::new(
                EventKind::SessionOpened,
                EventSource::Journald,
                line.monotonic_ns,
                truncate(&line.message),
            ));
        }
        emitted
    }

    fn on_unit_active(&mut self, unit: &str, monotonic_ns: u64) -> Vec<ReadinessEvent> {
        if !REQUIRED_UNITS.contains(&unit) || !self.units_active.insert(unit.to_owned()) {
            return Vec::new();
        }
        vec![ReadinessEvent::new(
            EventKind::UnitActive,
            EventSource::Systemd,
            monotonic_ns,
            unit,
        )]
    }

    fn on_usable(
        &mut self,
        events: Vec<ReadinessEvent>,
        monotonic_ns: u64,
    ) -> Vec<ReadinessEvent> {
        self.finished = true;
        let failed = events.iter().any(|event| event.kind == EventKind::Error);
        let degraded = events
            .iter()
            .any(|event| event.detail.contains(ATSPI_UNAVAILABLE));
        let window_shown = events
            .iter()
            .any(|event| event.kind == EventKind::SentinelWindowShown);
        let last_ns = events
            .iter()
            .map(|event| event.monotonic_ns)
            .max()
            .unwrap_or(monotonic_ns);

        let mut emitted = events;
        if !failed && window_shown {
            emitted.push(ReadinessEvent::new(
                EventKind::Usable,
                EventSource::Probe,
                last_ns,
                "all three conditions met",
            ));
        } else if !failed && degraded {
            emitted.push(ReadinessEvent::new(
                EventKind::Usable,
                EventSource::Probe,
                last_ns,
                "process group only (atspi_unavailable)",
            ));
        }
        emitted
    }

    fn on_tick(&mut self, now_ns: u64) -> Vec<ReadinessEvent> {
        if !self.injection_requested
            && now_ns.saturating_sub(self.started_ns) >= GREETER_TIMEOUT_NS
        {
            self.finished = true;
            return vec![ReadinessEvent::new(
                EventKind::ObserverTimeout,
                EventSource::Probe,
                now_ns,
                "login-ready gate not satisfied within 90s of observer start",
            )];
        }
        if self.session_ns.is_none()
            && self
                .injected_ns
                .is_some_and(|injected| now_ns.saturating_sub(injected) >= SESSION_TIMEOUT_NS)
        {
            self.finished = true;
            return vec![ReadinessEvent::new(
                EventKind::Error,
                EventSource::Probe,
                now_ns,
                "no session within 30s of injection (wrong password or keymap?); \
                 injection is never retried",
            )];
        }
        if self
            .session_ns
            .is_some_and(|session| now_ns.saturating_sub(session) >= USABLE_TIMEOUT_NS)
        {
            self.finished = true;
            return vec![ReadinessEvent::new(
                EventKind::ObserverTimeout,
                EventSource::Probe,
                now_ns,
                "usable-probe result not seen within 120s of session open",
            )];
        }
        Vec::new()
    }
}

/// Details carry journal text; keep lines bounded for the JSONL stream.
fn truncate(message: &str) -> String {
    const LIMIT: usize = 120;
    if message.chars().count() <= LIMIT {
        message.to_owned()
    } else {
        let head: String = message.chars().take(LIMIT).collect();
        format!("{head}...")
    }
}
```

Add `pub mod state;` to `target/bootprobe/src/observe/mod.rs`.

- [ ] **Step 4: Run the state-machine tests**

Run: `cargo test -p kbl-bootprobe --test observe_logic`
Expected: 19 tests pass (6 journal + 4 keymap + 9 state machine).

- [ ] **Step 5: Implement the observe driver**

Replace `target/bootprobe/src/observe/mod.rs` in full:

```rust
//! Observer components: config, journald parsing, keymap, uinput, the pure
//! readiness state machine, and the root-side `observe` driver.

pub mod config;
pub mod journal;
pub mod keymap;
pub mod state;
pub mod uinput;

#[cfg(target_os = "linux")]
pub use driver::run_observe;

#[cfg(not(target_os = "linux"))]
pub fn run_observe(
    _config_path: &std::path::Path,
    _state_dir: &std::path::Path,
) -> anyhow::Result<()> {
    anyhow::bail!("observe is supported only on Linux")
}

#[cfg(target_os = "linux")]
mod driver {
    use std::collections::BTreeSet;
    use std::fs::{self, File};
    use std::io::{BufRead, BufReader, Write};
    use std::path::Path;
    use std::sync::mpsc::{self, Receiver, TryRecvError};
    use std::thread;
    use std::time::Duration;

    use anyhow::{Context, Result};

    use crate::capture::run_command;
    use crate::events::{EventKind, EventSource, ReadinessEvent};
    use crate::observe::config::{DONE_MARKER, EVENTS_FILE, ObserveConfig, USABLE_RESULT_FILE};
    use crate::observe::journal::{parse_journal_json, spawn_journal_follower};
    use crate::observe::state::{REQUIRED_UNITS, ReadinessState, Signal};
    use crate::observe::uinput::UinputKeyboard;
    use crate::system::{boottime_ns, read_boot_id};

    /// Append-only JSONL event log; flushed after every write so the stream
    /// survives an observer crash and the done marker never precedes data.
    struct EventLog {
        file: File,
    }

    impl EventLog {
        fn create(path: &Path) -> Result<Self> {
            // Truncates the previous boot's stream by design.
            let file = File::create(path)
                .with_context(|| format!("cannot create {}", path.display()))?;
            Ok(Self { file })
        }

        fn write_all(&mut self, events: &[ReadinessEvent]) -> Result<()> {
            for event in events {
                self.file.write_all(event.to_jsonl_line().as_bytes())?;
                self.file.write_all(b"\n")?;
            }
            self.file.flush()?;
            Ok(())
        }
    }

    /// Pump follower stdout into a channel so the poll loop never blocks on
    /// a quiet journal.
    fn start_line_pump(child: &mut std::process::Child) -> Result<Receiver<String>> {
        let stdout = child.stdout.take().context("journalctl stdout not piped")?;
        let (sender, receiver) = mpsc::channel();
        thread::spawn(move || {
            for line in BufReader::new(stdout).lines() {
                let Ok(line) = line else { break };
                if sender.send(line).is_err() {
                    break;
                }
            }
        });
        Ok(receiver)
    }

    pub fn run_observe(config_path: &Path, state_dir: &Path) -> Result<()> {
        let raw = fs::read_to_string(config_path)
            .with_context(|| format!("cannot read {}", config_path.display()))?;
        let config = ObserveConfig::from_toml_str(&raw)?;

        fs::create_dir_all(state_dir)?;
        // Stale artifacts from the previous boot must never satisfy this one.
        let _ = fs::remove_file(state_dir.join(DONE_MARKER));
        let _ = fs::remove_file(state_dir.join(USABLE_RESULT_FILE));
        let mut log = EventLog::create(&state_dir.join(EVENTS_FILE))?;

        let started_ns = boottime_ns()?;
        log.write_all(&[ReadinessEvent::new(
            EventKind::ObserverStarted,
            EventSource::Probe,
            started_ns,
            format!("mode={}", config.mode.as_str()),
        )])?;

        let mut machine = ReadinessState::new(started_ns, &config);

        // uinput self-check up front — part of the Tlogin-ready definition.
        // On failure the gate can never open, the 90 s greeter timeout ends
        // the run, and the greeter/unit timeline stays valid regardless.
        let mut keyboard = match UinputKeyboard::create() {
            Ok(keyboard) => {
                let events = machine.feed(Signal::UinputReady {
                    monotonic_ns: boottime_ns()?,
                });
                log.write_all(&events)?;
                Some(keyboard)
            }
            Err(error) => {
                log.write_all(&[ReadinessEvent::new(
                    EventKind::Error,
                    EventSource::Probe,
                    boottime_ns()?,
                    format!("uinput self-check failed: {error:#}"),
                )])?;
                None
            }
        };

        let mut follower = spawn_journal_follower()?;
        let lines = start_line_pump(&mut follower)?;
        let interval = Duration::from_millis(config.mode.poll_interval_ms());
        let mut pending_units: BTreeSet<&str> = REQUIRED_UNITS.iter().copied().collect();

        while !machine.finished() {
            // 1. Drain replayed + live journal lines.
            loop {
                match lines.try_recv() {
                    Ok(line) => {
                        if let Some(parsed) = parse_journal_json(&line) {
                            let events = machine.feed(Signal::Journal(parsed));
                            log.write_all(&events)?;
                        }
                    }
                    Err(TryRecvError::Empty | TryRecvError::Disconnected) => break,
                }
            }

            // 2. Poll unit states — one subprocess per tick, and none at all
            // once every required unit went active (overhead hygiene).
            if !pending_units.is_empty() {
                let units: Vec<&str> = pending_units.iter().copied().collect();
                let mut args = vec!["is-active"];
                args.extend(units.iter().copied());
                let capture = run_command("systemctl", &args);
                let now = boottime_ns()?;
                for (unit, status) in units.iter().zip(capture.stdout.lines()) {
                    if status.trim() == "active" {
                        pending_units.remove(*unit);
                        let events = machine.feed(Signal::UnitActive {
                            unit: (*unit).to_owned(),
                            monotonic_ns: now,
                        });
                        log.write_all(&events)?;
                    }
                }
            }

            // 3. Fire the one-shot injection when the gate opens.
            if machine.take_injection_request() {
                let keyboard = keyboard
                    .as_mut()
                    .expect("injection gate requires a successful uinput self-check");
                match keyboard.type_password_and_enter(&config.password) {
                    Ok(()) => {
                        let events = machine.feed(Signal::LoginInjected {
                            monotonic_ns: boottime_ns()?,
                        });
                        log.write_all(&events)?;
                    }
                    Err(error) => {
                        log.write_all(&[ReadinessEvent::new(
                            EventKind::Error,
                            EventSource::Probe,
                            boottime_ns()?,
                            format!("injection failed: {error:#}"),
                        )])?;
                        break; // done marker below still lands for diagnostics
                    }
                }
            }

            // 4. Merge the usable-probe result when it appears (the probe
            // publishes it atomically via rename, so no partial reads).
            let result_path = state_dir.join(USABLE_RESULT_FILE);
            if result_path.is_file() {
                let raw = fs::read_to_string(&result_path).unwrap_or_default();
                let events: Vec<ReadinessEvent> = raw
                    .lines()
                    .filter(|line| !line.trim().is_empty())
                    .filter_map(|line| serde_json::from_str(line).ok())
                    .collect();
                let emitted = machine.feed(Signal::UsableResult {
                    events,
                    monotonic_ns: boottime_ns()?,
                });
                log.write_all(&emitted)?;
            }

            // 5. Deadline checks.
            let events = machine.feed(Signal::Tick {
                monotonic_ns: boottime_ns()?,
            });
            log.write_all(&events)?;

            thread::sleep(interval);
        }

        // Done marker carries the boot_id so a stale marker from a previous
        // boot can never satisfy the controller's gate (spec §4.3).
        let boot_id = read_boot_id(Path::new("/proc/sys/kernel/random/boot_id"))?;
        fs::write(state_dir.join(DONE_MARKER), format!("{boot_id}\n"))?;
        let _ = follower.kill();
        let _ = follower.wait();
        Ok(())
    }
}
```

The driver has no unit tests (linux-only, thin over the tested state machine); it is compile-checked via the linux target and exercised by Task 13 acceptance.

- [ ] **Step 6: Run all gates**

Run: `cargo test --workspace && cargo clippy --workspace --all-targets -- -D warnings && cargo clippy -p kbl-bootprobe --all-targets --target x86_64-unknown-linux-gnu -- -D warnings && cargo fmt --all -- --check`
Expected: all tests pass on Windows; linux-target clippy compiles the driver clean.

- [ ] **Step 7: Commit**

```bash
git add target/bootprobe/src/observe target/bootprobe/tests/observe_logic.rs
git commit -m "feat: add readiness state machine and observe driver"
```

---

### Task 7: usable-probe (procscan pure + AT-SPI subprocess + orchestration)

**Files:**
- Create: `target/bootprobe/src/usable/mod.rs`
- Create: `target/bootprobe/src/usable/procscan.rs` (pure, dir-parameterized)
- Create: `target/bootprobe/src/usable/atspi.rs` (parsers pure + inline tests; subprocess calls linux-gated)
- Modify: `target/bootprobe/src/lib.rs` (add `pub mod usable;`)
- Create: `target/bootprobe/tests/procscan.rs`

**Interfaces:**
- Produces (procscan): `scan_comms(proc_root: &Path) -> Vec<String>` — reads `<proc_root>/<pid>/comm` for numeric dirs only, skips vanished entries (a /proc walk is racy by nature), empty on unreadable root; `all_present(needed: &[String], comms: &[String]) -> bool` (empty `needed` is trivially true); `missing(needed: &[String], comms: &[String]) -> Vec<String>`. Comparison is aware that the kernel truncates `comm` to 15 bytes (`ukui-settings-daemon` → `ukui-settings-d`).
- Produces (atspi, pure): `parse_bus_address(json_reply: &str) -> Option<String>` for `busctl --user --json=short call org.a11y.Bus /org/a11y/bus org.a11y.Bus GetAddress` (extracts `data[0]`, requires `unix:` prefix); `parse_child_count(reply: &str) -> Option<u32>` for `dbus-send --print-reply` output (last integer token).
- Produces (atspi, linux): `a11y_bus_address() -> anyhow::Result<String>`; `desktop_child_count(address: &str) -> anyhow::Result<u32>` via `dbus-send --address=<addr> --print-reply --dest=org.a11y.atspi.Registry /org/a11y/atspi/accessible/root org.freedesktop.DBus.Properties.Get string:org.a11y.atspi.Accessible string:ChildCount` (note: `ChildCount` is a **property** of `org.a11y.atspi.Accessible` — the interface has no `GetChildCount` method, hence `Properties.Get` carries the count query). Session env (`DBUS_SESSION_BUS_ADDRESS`, `DISPLAY`) is inherited — the probe runs inside the kbl session.
- Produces (mod.rs): `run_usable_probe(config_path: &Path, state_dir: &Path) -> anyhow::Result<()>` — linux; non-linux stub bails.
- **v1 sentinel heuristic (documented):** first window = AT-SPI registry root child-count increase after launching the sentinel (`count_before < count_after`). Exact-name matching of the new child is an acceptance refinement (Task 13).
- **Session-side start timestamp (spec §4.1):** the first event the probe publishes in `usable-result.jsonl` is `kind="observer_started"`, `source="probe"`, `detail="usable-probe session start"`, stamped with the probe's `started_ns` — this maps the spec's "记录会话侧启动时间戳" line into the event stream instead of keeping it internal. The kind enum is unchanged, and `derive_metrics` takes the FIRST `observer_started` for `mode` (the root observer's, emitted at boot), so this second, later `observer_started` in the merged stream is harmless.

Probe flow: exit 0 immediately if the `enabled` marker is absent (bare group = zero session footprint) → read observe.toml (root 0600 → unreadable as kbl → fall back to `ObserveConfig::probe_defaults()`; the runbook documents `chgrp kbl + chmod 0640` as the opt-in for custom `desktop_processes`) → emit `observer_started` (detail `usable-probe session start`) as the result stream's first event → poll `/proc` until every `desktop_processes` entry runs (`desktop_process_up` per process, detail = process name) → AT-SPI address + child count ≥ 1 (`atspi_desktop_ready`, detail `"N desktop children"`) → launch sentinel (`sentinel_launched`) → poll for child-count increase (`sentinel_window_shown`) → publish `usable-result.jsonl` **atomically** (write `.partial`, rename). On AT-SPI failure: emit `desktop_process_up` with detail `"process group complete (atspi_unavailable)"` and publish (root observer emits the degraded `usable`). On the 120 s deadline: emit `error` with what was still pending, publish partial results.

- [ ] **Step 1: Write the failing procscan tests**

Create `target/bootprobe/tests/procscan.rs`:

```rust
use std::fs;

use kbl_bootprobe::usable::procscan::{all_present, missing, scan_comms};
use tempfile::tempdir;

fn fake_proc(entries: &[(&str, Option<&str>)]) -> tempfile::TempDir {
    let root = tempdir().unwrap();
    for (pid, comm) in entries {
        let dir = root.path().join(pid);
        fs::create_dir(&dir).unwrap();
        if let Some(comm) = comm {
            fs::write(dir.join("comm"), format!("{comm}\n")).unwrap();
        }
    }
    root
}

#[test]
fn scan_reads_comm_of_numeric_pid_dirs_only() {
    let proc_root = fake_proc(&[
        ("1", Some("systemd")),
        ("4242", Some("ukui-panel")),
        ("self", Some("ignored")),
        ("acpi", Some("ignored")),
    ]);
    let mut comms = scan_comms(proc_root.path());
    comms.sort();
    assert_eq!(comms, vec!["systemd".to_owned(), "ukui-panel".to_owned()]);
}

#[test]
fn scan_skips_pid_dirs_without_comm() {
    let proc_root = fake_proc(&[("7", None), ("8", Some("bash"))]);
    assert_eq!(scan_comms(proc_root.path()), vec!["bash".to_owned()]);
}

#[test]
fn scan_of_missing_root_is_empty() {
    let root = tempdir().unwrap();
    assert!(scan_comms(&root.path().join("no-such-proc")).is_empty());
}

#[test]
fn all_present_matches_kernel_truncated_comm() {
    // The kernel truncates comm to 15 bytes: ukui-settings-daemon shows as
    // ukui-settings-d.  The required-list entry must still match.
    let needed = vec!["ukui-settings-daemon".to_owned(), "ukui-panel".to_owned()];
    let comms = vec!["ukui-settings-d".to_owned(), "ukui-panel".to_owned()];
    assert!(all_present(&needed, &comms));
}

#[test]
fn missing_lists_absent_processes_in_input_order() {
    let needed = vec!["ukui-panel".to_owned(), "peony".to_owned()];
    let comms = vec!["ukui-panel".to_owned()];
    assert_eq!(missing(&needed, &comms), vec!["peony".to_owned()]);
}

#[test]
fn empty_needed_is_trivially_present() {
    assert!(all_present(&[], &["anything".to_owned()]));
}
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cargo test -p kbl-bootprobe --test procscan`
Expected: FAIL — module `usable` does not exist.

- [ ] **Step 3: Implement procscan.rs and atspi.rs**

Create `target/bootprobe/src/usable/procscan.rs`:

```rust
//! /proc scanning for the UKUI process-group readiness condition.
//! Parameterized by the proc root so tests use a temp directory.

use std::fs;
use std::path::Path;

/// Collect the `comm` of every process under *proc_root*.
///
/// Entries that vanish mid-scan (processes exiting) are skipped — a /proc
/// walk is inherently racy and must never fail the probe.  Returns an
/// empty list when the directory itself is unreadable.
pub fn scan_comms(proc_root: &Path) -> Vec<String> {
    let Ok(entries) = fs::read_dir(proc_root) else {
        return Vec::new();
    };
    let mut comms = Vec::new();
    for entry in entries.flatten() {
        let name = entry.file_name();
        let Some(name) = name.to_str() else { continue };
        if name.is_empty() || !name.bytes().all(|byte| byte.is_ascii_digit()) {
            continue;
        }
        if let Ok(comm) = fs::read_to_string(entry.path().join("comm")) {
            comms.push(comm.trim().to_owned());
        }
    }
    comms
}

/// Kernel `comm` values are truncated to 15 bytes (TASK_COMM_LEN - 1), so
/// "ukui-settings-daemon" shows up as "ukui-settings-d".  Compare with the
/// same truncation applied to the required name.
fn comm_matches(comms: &[String], required: &str) -> bool {
    let truncated: String = required.chars().take(15).collect();
    comms.iter().any(|comm| comm == required || *comm == truncated)
}

/// True when every required process currently runs (empty list: trivially true).
pub fn all_present(needed: &[String], comms: &[String]) -> bool {
    needed.iter().all(|process| comm_matches(comms, process))
}

/// The required processes not currently running, in input order.
pub fn missing(needed: &[String], comms: &[String]) -> Vec<String> {
    needed
        .iter()
        .filter(|process| !comm_matches(comms, process))
        .cloned()
        .collect()
}
```

Create `target/bootprobe/src/usable/atspi.rs`:

```rust
//! AT-SPI desktop checks via `busctl` / `dbus-send` subprocesses.
//!
//! No native D-Bus dependency: the probe shells out and parses the textual
//! replies with the pure functions below (unit-tested cross-platform).
//! The probe runs inside the kbl session, so `DBUS_SESSION_BUS_ADDRESS`
//! and `XDG_RUNTIME_DIR` are inherited from the session environment.

/// Extract the a11y bus address from
/// `busctl --user --json=short call org.a11y.Bus /org/a11y/bus org.a11y.Bus GetAddress`.
/// Reply shape: `{"type":"s","data":["unix:path=/run/user/1000/at-spi/bus_0"]}`.
pub fn parse_bus_address(json_reply: &str) -> Option<String> {
    let value: serde_json::Value = serde_json::from_str(json_reply.trim()).ok()?;
    let address = value.get("data")?.get(0)?.as_str()?;
    address.starts_with("unix:").then(|| address.to_owned())
}

/// Extract the child count from a `dbus-send --print-reply` reply — the
/// last integer token, e.g. `   variant       int32 3`.
pub fn parse_child_count(reply: &str) -> Option<u32> {
    reply
        .split_whitespace()
        .rev()
        .find_map(|token| token.parse().ok())
}

#[cfg(target_os = "linux")]
mod calls {
    use anyhow::{Context, Result, bail};

    use super::{parse_bus_address, parse_child_count};
    use crate::capture::run_command;

    /// Ask the session bus where the accessibility bus lives.
    pub fn a11y_bus_address() -> Result<String> {
        let capture = run_command(
            "busctl",
            &[
                "--user",
                "--json=short",
                "call",
                "org.a11y.Bus",
                "/org/a11y/bus",
                "org.a11y.Bus",
                "GetAddress",
            ],
        );
        if capture.exit_code != 0 {
            bail!("org.a11y.Bus GetAddress failed: {}", capture.stderr.trim());
        }
        parse_bus_address(&capture.stdout).context("unparseable GetAddress reply")
    }

    /// Number of applications registered on the AT-SPI registry root.
    /// `ChildCount` is a property of `org.a11y.atspi.Accessible` (the
    /// interface has no `GetChildCount` method), hence `Properties.Get`.
    pub fn desktop_child_count(address: &str) -> Result<u32> {
        let address_arg = format!("--address={address}");
        let capture = run_command(
            "dbus-send",
            &[
                &address_arg,
                "--print-reply",
                "--dest=org.a11y.atspi.Registry",
                "/org/a11y/atspi/accessible/root",
                "org.freedesktop.DBus.Properties.Get",
                "string:org.a11y.atspi.Accessible",
                "string:ChildCount",
            ],
        );
        if capture.exit_code != 0 {
            bail!("ChildCount query failed: {}", capture.stderr.trim());
        }
        parse_child_count(&capture.stdout).context("unparseable ChildCount reply")
    }
}

#[cfg(target_os = "linux")]
pub use calls::{a11y_bus_address, desktop_child_count};

#[cfg(test)]
mod tests {
    use super::{parse_bus_address, parse_child_count};

    #[test]
    fn parses_busctl_json_address() {
        let reply = r#"{"type":"s","data":["unix:path=/run/user/1000/at-spi/bus_0"]}"#;
        assert_eq!(
            parse_bus_address(reply).as_deref(),
            Some("unix:path=/run/user/1000/at-spi/bus_0")
        );
    }

    #[test]
    fn rejects_non_unix_address_and_garbage() {
        assert!(parse_bus_address(r#"{"type":"s","data":["tcp:host=evil"]}"#).is_none());
        assert!(parse_bus_address("not json").is_none());
        assert!(parse_bus_address(r#"{"data":[]}"#).is_none());
    }

    #[test]
    fn parses_dbus_send_child_count_reply() {
        let reply = concat!(
            "method return time=1721288.123 sender=:1.5 -> destination=:1.42 ",
            "serial=42 reply_serial=2\n",
            "   variant       int32 3\n",
        );
        assert_eq!(parse_child_count(reply), Some(3));
    }

    #[test]
    fn child_count_of_zero_parses() {
        assert_eq!(parse_child_count("   variant       int32 0\n"), Some(0));
    }

    #[test]
    fn unparseable_reply_yields_none() {
        assert_eq!(parse_child_count("no numbers here"), None);
    }
}
```

- [ ] **Step 4: Implement the probe orchestration**

Create `target/bootprobe/src/usable/mod.rs`:

```rust
//! Session-side `usable-probe` — runs from XDG autostart inside the kbl
//! session, measures the three Tusable conditions (process group + AT-SPI
//! enumeration + sentinel first window), and publishes a result file the
//! root observer merges into the event stream.

pub mod atspi;
pub mod procscan;

#[cfg(target_os = "linux")]
pub use probe::run_usable_probe;

#[cfg(not(target_os = "linux"))]
pub fn run_usable_probe(
    _config_path: &std::path::Path,
    _state_dir: &std::path::Path,
) -> anyhow::Result<()> {
    anyhow::bail!("usable-probe is supported only on Linux")
}

#[cfg(target_os = "linux")]
mod probe {
    use std::fs;
    use std::path::Path;
    use std::process::{Command, Stdio};
    use std::thread::sleep;
    use std::time::Duration;

    use anyhow::{Context, Result};

    use crate::events::{EventKind, EventSource, ReadinessEvent};
    use crate::observe::config::{ENABLED_MARKER, ObserveConfig, USABLE_RESULT_FILE};
    use crate::observe::state::{ATSPI_UNAVAILABLE, USABLE_TIMEOUT_NS};
    use crate::system::boottime_ns;
    use crate::usable::{atspi, procscan};

    /// GetAddress attempts before declaring AT-SPI unavailable (spec §8
    /// degradation) — spaced at least 500 ms apart.
    const ATSPI_ATTEMPTS: u32 = 5;

    pub fn run_usable_probe(config_path: &Path, state_dir: &Path) -> Result<()> {
        // Observer disabled (bare calibration group): zero session footprint.
        if !state_dir.join(ENABLED_MARKER).is_file() {
            return Ok(());
        }
        // observe.toml is root 0600; the session probe falls back to
        // defaults when unreadable (the password is irrelevant here).
        let config = fs::read_to_string(config_path)
            .ok()
            .and_then(|raw| ObserveConfig::from_toml_str(&raw).ok())
            .unwrap_or_else(ObserveConfig::probe_defaults);

        let started_ns = boottime_ns()?;
        let deadline_ns = started_ns + USABLE_TIMEOUT_NS;
        let interval = Duration::from_millis(config.mode.poll_interval_ms());
        let mut events: Vec<ReadinessEvent> = Vec::new();

        // Spec §4.1: session-side start timestamp — first line of the
        // result file.  derive_metrics keeps the FIRST observer_started
        // (the root observer's), so this later one never overrides `mode`.
        events.push(ReadinessEvent::new(
            EventKind::ObserverStarted,
            EventSource::Probe,
            started_ns,
            "usable-probe session start",
        ));

        // Condition 1: UKUI process group complete (one event per process).
        let mut pending: Vec<String> = config.desktop_processes.clone();
        while !pending.is_empty() && boottime_ns()? < deadline_ns {
            let comms = procscan::scan_comms(Path::new("/proc"));
            let now = boottime_ns()?;
            pending.retain(|process| {
                if procscan::all_present(std::slice::from_ref(process), &comms) {
                    events.push(ReadinessEvent::new(
                        EventKind::DesktopProcessUp,
                        EventSource::Probe,
                        now,
                        process.as_str(),
                    ));
                    false
                } else {
                    true
                }
            });
            if !pending.is_empty() {
                sleep(interval);
            }
        }
        if !pending.is_empty() {
            events.push(ReadinessEvent::new(
                EventKind::Error,
                EventSource::Probe,
                boottime_ns()?,
                format!("usable deadline: processes still missing: {}", pending.join(", ")),
            ));
            return publish(state_dir, &events);
        }

        // Conditions 2 + 3: AT-SPI enumeration, then sentinel first window.
        match wait_for_atspi(deadline_ns, interval)? {
            Some(address) => {
                let mut count = atspi::desktop_child_count(&address).unwrap_or(0);
                while count == 0 && boottime_ns()? < deadline_ns {
                    sleep(interval);
                    count = atspi::desktop_child_count(&address).unwrap_or(0);
                }
                if count == 0 {
                    events.push(ReadinessEvent::new(
                        EventKind::Error,
                        EventSource::Atspi,
                        boottime_ns()?,
                        "AT-SPI registry still empty at deadline",
                    ));
                    return publish(state_dir, &events);
                }
                events.push(ReadinessEvent::new(
                    EventKind::AtspiDesktopReady,
                    EventSource::Atspi,
                    boottime_ns()?,
                    format!("{count} desktop children"),
                ));
                run_sentinel(&config, &address, deadline_ns, interval, &mut events)?;
            }
            None => {
                // Spec §8: degrade to a pure process-group signal; the root
                // observer recognises the marker and emits a degraded usable.
                events.push(ReadinessEvent::new(
                    EventKind::DesktopProcessUp,
                    EventSource::Probe,
                    boottime_ns()?,
                    format!("process group complete ({ATSPI_UNAVAILABLE})"),
                ));
            }
        }
        publish(state_dir, &events)
    }

    fn wait_for_atspi(deadline_ns: u64, interval: Duration) -> Result<Option<String>> {
        for _ in 0..ATSPI_ATTEMPTS {
            if boottime_ns()? >= deadline_ns {
                break;
            }
            if let Ok(address) = atspi::a11y_bus_address() {
                return Ok(Some(address));
            }
            sleep(interval.max(Duration::from_millis(500)));
        }
        Ok(None)
    }

    fn run_sentinel(
        config: &ObserveConfig,
        address: &str,
        deadline_ns: u64,
        interval: Duration,
        events: &mut Vec<ReadinessEvent>,
    ) -> Result<()> {
        let count_before = atspi::desktop_child_count(address).unwrap_or(0);
        let (program, args) = config
            .sentinel_command
            .split_first()
            .context("sentinel_command must not be empty")?;
        // Session env (DISPLAY, DBUS_SESSION_BUS_ADDRESS, PATH) inherited on
        // purpose — the sentinel must launch exactly like a user app would.
        let spawned = Command::new(program)
            .args(args)
            .stdout(Stdio::null())
            .stderr(Stdio::null())
            .spawn();
        let launched_ns = boottime_ns()?;
        if let Err(error) = spawned {
            events.push(ReadinessEvent::new(
                EventKind::Error,
                EventSource::Probe,
                launched_ns,
                format!("sentinel exec failed: {error}"),
            ));
            return Ok(());
        }
        // The child is intentionally left running: killing it could race the
        // window registration, and the boot is over — the orchestrator
        // power-cycles the target before the next experiment anyway.
        events.push(ReadinessEvent::new(
            EventKind::SentinelLaunched,
            EventSource::Probe,
            launched_ns,
            config.sentinel_command.join(" "),
        ));

        // v1 heuristic (documented): the sentinel's first accessible window
        // registers as a new child on the registry root, so a child-count
        // increase marks first-window.  Exact-name matching is an
        // acceptance refinement (Task 13).
        loop {
            let now = boottime_ns()?;
            if now >= deadline_ns {
                events.push(ReadinessEvent::new(
                    EventKind::Error,
                    EventSource::Probe,
                    now,
                    "sentinel window not observed before deadline",
                ));
                return Ok(());
            }
            let count = atspi::desktop_child_count(address).unwrap_or(count_before);
            if count > count_before {
                events.push(ReadinessEvent::new(
                    EventKind::SentinelWindowShown,
                    EventSource::Atspi,
                    now,
                    format!("{program} window (registry children {count_before} -> {count})"),
                ));
                return Ok(());
            }
            sleep(interval);
        }
    }

    /// Atomic publish: the root observer treats the result file's presence
    /// as probe-finished, so it must never see a half-written file.
    fn publish(state_dir: &Path, events: &[ReadinessEvent]) -> Result<()> {
        let mut body = String::new();
        for event in events {
            body.push_str(&event.to_jsonl_line());
            body.push('\n');
        }
        let temporary = state_dir.join(format!("{USABLE_RESULT_FILE}.partial"));
        fs::write(&temporary, body)
            .with_context(|| format!("cannot write {}", temporary.display()))?;
        fs::rename(&temporary, state_dir.join(USABLE_RESULT_FILE))
            .context("cannot publish usable result")?;
        Ok(())
    }
}
```

Add `pub mod usable;` to `target/bootprobe/src/lib.rs` (after `pub mod system;`).

- [ ] **Step 5: Run tests + gates**

Run: `cargo test -p kbl-bootprobe && cargo clippy --workspace --all-targets -- -D warnings && cargo clippy -p kbl-bootprobe --all-targets --target x86_64-unknown-linux-gnu -- -D warnings && cargo fmt --all -- --check`
Expected: 6 procscan tests + 5 atspi inline tests pass alongside all earlier tests; linux-target clippy compiles the probe clean.

- [ ] **Step 6: Commit**

```bash
git add target/bootprobe/src/usable target/bootprobe/src/lib.rs target/bootprobe/tests/procscan.rs
git commit -m "feat: add usable-probe (procscan, AT-SPI, orchestration)"
```

---

### Task 8: CLI Wiring + Snapshot Artifact + Cross-Language Fixture

**Files:**
- Modify: `target/bootprobe/src/main.rs` (add `observe`, `usable-probe`, `readiness-fixture` subcommands)
- Modify: `target/bootprobe/src/snapshot.rs` (append the `readiness-events` capture spec)
- Modify: `target/bootprobe/src/events.rs` (add `readiness_fixture()`)
- Modify: `target/bootprobe/tests/snapshot.rs` (spec-presence test)
- Modify: `target/bootprobe/tests/events.rs` (fixture sanity test)
- Modify: `tests/test_rust_contract.py` (Rust stream → Python contract validation, spec §9)

**Interfaces:**
- Produces: `kbl-bootprobe observe --config <path> --state-dir <path>` (defaults `/etc/kylinbootlab/observe.toml`, `/var/lib/kylinbootlab/observe`); `kbl-bootprobe usable-probe` with the same two options and defaults; `kbl-bootprobe readiness-fixture` printing the 13-event JSONL stream byte-identical to `tests/fixtures/readiness-events-v1.jsonl`.
- Produces: `events::readiness_fixture() -> Vec<ReadinessEvent>`.
- Modifies: `default_capture_specs()` gains `CaptureSpec { name: "readiness-events", command: ["cat", "/var/lib/kylinbootlab/observe/current.jsonl"], required: false }` — `required: false` keeps observer-less targets fully working (`ProbeManifest` frozen, artifact optional).

- [ ] **Step 1: Check that no Python test pins the capture-spec count**

Run: `rg -n "systemd-time|artifacts\)" tests/test_store.py tests/test_contracts.py tests/helpers.py | head -20`
Expected: Python tests build their own two-capture bundles via `tests/helpers.py` and never assert the Rust default-spec count — no Python updates needed for the new spec. (If a count assert ever appears, update it here.)

- [ ] **Step 2: Write the failing Rust tests**

Append to `target/bootprobe/tests/snapshot.rs` (extend the existing `use kbl_bootprobe::snapshot::{...}` line with `default_capture_specs`):

```rust
#[test]
fn default_specs_include_optional_readiness_events() {
    let specs = default_capture_specs();
    let readiness = specs
        .iter()
        .find(|spec| spec.name == "readiness-events")
        .expect("readiness-events spec present");
    assert!(!readiness.required, "must stay optional for observer-less targets");
    assert_eq!(
        readiness.command,
        vec![
            "cat".to_owned(),
            "/var/lib/kylinbootlab/observe/current.jsonl".to_owned(),
        ]
    );
}
```

Append to `target/bootprobe/tests/events.rs`:

```rust
#[test]
fn readiness_fixture_is_monotonic_and_complete() {
    let fixture = kbl_bootprobe::events::readiness_fixture();
    assert_eq!(fixture.len(), 13);
    let mut previous = 0;
    for event in &fixture {
        assert!(event.monotonic_ns >= previous, "fixture must be time-ordered");
        previous = event.monotonic_ns;
    }
    assert_eq!(fixture[0].kind, EventKind::ObserverStarted);
    assert_eq!(fixture[12].kind, EventKind::Usable);
}
```

Run: `cargo test -p kbl-bootprobe --test snapshot --test events`
Expected: FAIL — no `readiness-events` spec, no `readiness_fixture`.

- [ ] **Step 3: Implement the spec, the fixture, and the subcommands**

In `target/bootprobe/src/snapshot.rs`, append to the vector in `default_capture_specs()` (after the `journal-monotonic` spec):

```rust
        CaptureSpec {
            name: "readiness-events",
            command: words(&["cat", "/var/lib/kylinbootlab/observe/current.jsonl"]),
            required: false,
        },
```

In `target/bootprobe/src/events.rs`, append:

```rust
/// Cross-language fixture stream — byte-for-byte identical to
/// `tests/fixtures/readiness-events-v1.jsonl` on the Python side
/// (verified by `tests/test_rust_contract.py`).
pub fn readiness_fixture() -> Vec<ReadinessEvent> {
    use EventKind as K;
    use EventSource as S;
    vec![
        ReadinessEvent::new(K::ObserverStarted, S::Probe, 3_000_000_000, "mode=benchmark"),
        ReadinessEvent::new(K::GreeterStarted, S::Journald, 6_613_388_000, "lightdm start begin"),
        ReadinessEvent::new(K::UnitActive, S::Systemd, 7_000_000_000, "dbus.service"),
        ReadinessEvent::new(K::UnitActive, S::Systemd, 7_100_000_000, "NetworkManager.service"),
        ReadinessEvent::new(K::UnitActive, S::Systemd, 7_200_000_000, "lightdm.service"),
        ReadinessEvent::new(K::GreeterReady, S::Journald, 8_500_000_000, "ukui-greeter first output"),
        ReadinessEvent::new(K::LoginInjected, S::Probe, 9_000_000_000, "password+enter via uinput"),
        ReadinessEvent::new(K::SessionOpened, S::Journald, 11_500_000_000, "session opened for user kbl"),
        ReadinessEvent::new(K::DesktopProcessUp, S::Probe, 16_000_000_000, "ukui-panel"),
        ReadinessEvent::new(K::AtspiDesktopReady, S::Atspi, 16_500_000_000, "3 desktop children"),
        ReadinessEvent::new(K::SentinelLaunched, S::Probe, 16_600_000_000, "mate-terminal"),
        ReadinessEvent::new(K::SentinelWindowShown, S::Atspi, 18_100_000_000, "mate-terminal window"),
        ReadinessEvent::new(K::Usable, S::Probe, 18_100_000_000, "all three conditions met"),
    ]
}
```

Replace `target/bootprobe/src/main.rs` in full:

```rust
use std::path::PathBuf;

use anyhow::Result;
use clap::{Parser, Subcommand};
use kbl_bootprobe::events::readiness_fixture;
use kbl_bootprobe::model::contract_fixture;
use kbl_bootprobe::observe::run_observe;
use kbl_bootprobe::snapshot::{capture_snapshot, default_capture_specs, live_context};
use kbl_bootprobe::usable::run_usable_probe;
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
    /// Print the ReadinessEvent v1 cross-language fixture (JSONL).
    ReadinessFixture,
    Snapshot {
        #[arg(long)]
        run_id: Uuid,
        #[arg(long)]
        output: PathBuf,
    },
    /// Root-side readiness observer (systemd unit kbl-observe.service).
    Observe {
        #[arg(long, default_value = "/etc/kylinbootlab/observe.toml")]
        config: PathBuf,
        #[arg(long, default_value = "/var/lib/kylinbootlab/observe")]
        state_dir: PathBuf,
    },
    /// Session-side usable probe (XDG autostart in the kbl session).
    UsableProbe {
        #[arg(long, default_value = "/etc/kylinbootlab/observe.toml")]
        config: PathBuf,
        #[arg(long, default_value = "/var/lib/kylinbootlab/observe")]
        state_dir: PathBuf,
    },
}

fn main() -> Result<()> {
    let cli = Cli::parse();
    match cli.command {
        Command::ContractFixture => {
            println!("{}", serde_json::to_string_pretty(&contract_fixture())?);
        }
        Command::ReadinessFixture => {
            for event in readiness_fixture() {
                println!("{}", event.to_jsonl_line());
            }
        }
        Command::Snapshot { run_id, output } => {
            let manifest =
                capture_snapshot(&output, run_id, live_context()?, &default_capture_specs())?;
            println!("{}", manifest.run_id);
        }
        Command::Observe { config, state_dir } => {
            run_observe(&config, &state_dir)?;
        }
        Command::UsableProbe { config, state_dir } => {
            run_usable_probe(&config, &state_dir)?;
        }
    }
    Ok(())
}
```

- [ ] **Step 4: Add the cross-language contract test (spec §9)**

Append to `tests/test_rust_contract.py`:

```python
from pathlib import Path

from kylinbootlab.readiness import derive_metrics, parse_events


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
```

(Move the new `from pathlib import Path` / `from kylinbootlab.readiness import ...` lines into the import block at the top of the file — ruff enforces import placement.)

- [ ] **Step 5: Verify byte-identity manually once**

Run: `cargo run --quiet -p kbl-bootprobe -- readiness-fixture`
Expected: 13 JSONL lines; the first is exactly
`{"schema_version":1,"monotonic_ns":3000000000,"kind":"observer_started","detail":"mode=benchmark","source":"probe"}`
(Rust struct field order matches the fixture file: schema_version, monotonic_ns, kind, detail, source.)

Run: `cargo run --quiet -p kbl-bootprobe -- observe --state-dir ./tmp-observe`
Expected on Windows: exits non-zero with `observe is supported only on Linux` (stub path works; no files created).

- [ ] **Step 6: Run all gates**

Run: `cargo test --workspace && cargo clippy --workspace --all-targets -- -D warnings && cargo clippy -p kbl-bootprobe --all-targets --target x86_64-unknown-linux-gnu -- -D warnings && cargo fmt --all -- --check`
Expected: clean.

Run: `uv run pytest tests/test_rust_contract.py -v`
Expected: 2 tests pass (needs `cargo` on PATH — same caveat as Phase 1).

- [ ] **Step 7: Commit**

```bash
git add target/bootprobe/src/main.rs target/bootprobe/src/snapshot.rs target/bootprobe/src/events.rs target/bootprobe/tests/snapshot.rs target/bootprobe/tests/events.rs tests/test_rust_contract.py
git commit -m "feat: wire observe/usable-probe CLI and readiness-events capture"
```

---

### Task 9: Orchestrator Observer Gate (Python)

**Files:**
- Modify: `src/kylinbootlab/experiments/aliveness.py` (add `_ssh_once` + `wait_for_observer_done`)
- Modify: `src/kylinbootlab/experiments/orchestrator.py` (step 2c)
- Modify: `tests/test_experiments_orchestrator.py` (gate patches + new tests)

**Interfaces:**
- Produces: `wait_for_observer_done(target: str, timeout: float = 300, interval: float = 5) -> bool` — first a SINGLE fast probe `ssh target test -f /var/lib/kylinbootlab/observe/enabled`: marker absent means the observer is intentionally off for this boot (calibration bare group removes only the marker — the state directory stays, and `ConditionPathExists` keeps the unit from running) OR was never deployed → return `True` immediately (fast-degrade, spec §4.3; the single marker probe covers both cases, so pre-Phase-3 targets and calib-bare boots keep working with zero queue noise). Otherwise poll one combined remote test until the `done` file content equals the CURRENT boot_id (`cat /proc/sys/kernel/random/boot_id`) — a stale marker from the previous boot never matches. Timeout → `False`.
- Produces (internal): `_ssh_once(target: str, command: list[str]) -> bool`; `_poll_ssh` is refactored on top of it (existing monkeypatches of `aliveness.subprocess.run` keep working unchanged).
- Modifies: `ExperimentOrchestrator._run_one_experiment` gains step 2c after `wait_for_boot_finished`: gate failure raises `TargetUnreachableError("observer did not finish ...")` → normal retry/recovery path.

- [ ] **Step 1: Write the failing aliveness tests**

Append to `tests/test_experiments_orchestrator.py` (below the existing `wait_for_boot_finished` test):

```python
def test_wait_for_observer_done_passes_when_marker_absent(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """No enabled marker = observer off or never deployed: gate passes immediately."""
    from kylinbootlab.experiments.aliveness import wait_for_observer_done

    commands: list[list[str]] = []

    def fake_run(
        args: Sequence[str],
        **_kwargs: Any,
    ) -> subprocess.CompletedProcess[str]:
        commands.append(list(args))
        return subprocess.CompletedProcess(args, 1, stdout="", stderr="")

    monkeypatch.setattr("kylinbootlab.experiments.aliveness.subprocess.run", fake_run)

    assert wait_for_observer_done("target.local", timeout=5, interval=0.01) is True
    assert len(commands) == 1  # single fast-degrade probe, no polling
    assert commands[0][-3:] == ["test", "-f", "/var/lib/kylinbootlab/observe/enabled"]


def test_wait_for_observer_done_polls_boot_id_stamped_marker(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Enabled: polls the done-marker/boot_id comparison until it succeeds."""
    from kylinbootlab.experiments.aliveness import wait_for_observer_done

    commands: list[list[str]] = []

    def fake_run(
        args: Sequence[str],
        **_kwargs: Any,
    ) -> subprocess.CompletedProcess[str]:
        commands.append(list(args))
        # Call 1: enabled-marker probe succeeds.  Call 2: done not ready.  Call 3: ready.
        returncode = 0 if len(commands) in (1, 3) else 1
        return subprocess.CompletedProcess(args, returncode, stdout="", stderr="")

    monkeypatch.setattr("kylinbootlab.experiments.aliveness.subprocess.run", fake_run)

    assert wait_for_observer_done("target.local", timeout=10, interval=0.01) is True
    assert len(commands) == 3
    marker_check = commands[-1][-1]
    assert "/var/lib/kylinbootlab/observe/done" in marker_check
    assert "/proc/sys/kernel/random/boot_id" in marker_check


def test_wait_for_observer_done_times_out(monkeypatch: pytest.MonkeyPatch) -> None:
    """Enabled but the done marker never matches: returns False at timeout."""
    from kylinbootlab.experiments.aliveness import wait_for_observer_done

    call_count = 0

    def fake_run(
        args: Sequence[str],
        **_kwargs: Any,
    ) -> subprocess.CompletedProcess[str]:
        nonlocal call_count
        call_count += 1
        returncode = 0 if call_count == 1 else 1  # marker present, done never ready
        return subprocess.CompletedProcess(args, returncode, stdout="", stderr="")

    monkeypatch.setattr("kylinbootlab.experiments.aliveness.subprocess.run", fake_run)

    assert wait_for_observer_done("target.local", timeout=0.05, interval=0.01) is False
```

Run: `uv run pytest tests/test_experiments_orchestrator.py -k observer_done -v`
Expected: FAIL — `wait_for_observer_done` does not exist.

- [ ] **Step 2: Implement in aliveness.py**

Replace `src/kylinbootlab/experiments/aliveness.py` in full:

```python
"""SSH-based alive detection for experiment orchestration."""

import subprocess
import time

#: Observer state directory on the target (kbl-group-writable, Phase 3).
OBSERVE_STATE_DIR = "/var/lib/kylinbootlab/observe"

#: Enabled marker — also the observer unit's ``ConditionPathExists``.
#: Absent means the observer is off for this boot (calibration bare group
#: removes only this marker; the directory stays) or was never deployed;
#: either way no done marker will ever appear.
_ENABLED_MARKER = f"{OBSERVE_STATE_DIR}/enabled"

#: Remote test: the done marker exists AND carries the CURRENT boot_id, so
#: a stale marker left by a previous boot can never satisfy the gate.
_DONE_MATCHES_BOOT = (
    f'test "$(cat {OBSERVE_STATE_DIR}/done 2>/dev/null)" '
    '= "$(cat /proc/sys/kernel/random/boot_id)"'
)


def _ssh_once(target: str, command: list[str]) -> bool:
    """One SSH probe; True iff the remote command exits 0."""
    try:
        result = subprocess.run(
            [
                "ssh",
                "-o", "BatchMode=yes",
                "-o", "ConnectTimeout=10",
                target,
                *command,
            ],
            check=False,
            capture_output=True,
            timeout=10,
        )
    except (OSError, subprocess.TimeoutExpired):
        return False
    return result.returncode == 0


def _poll_ssh(target: str, command: list[str], timeout: float, interval: float) -> bool:
    """Poll an SSH command until it exits 0 or *timeout* seconds elapse."""
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if _ssh_once(target, command):
            return True
        time.sleep(interval)
    return False


def wait_for_ssh(
    target: str,
    timeout: float = 120,
    interval: float = 5,
) -> bool:
    """Poll *target* via SSH until successful or *timeout* seconds elapse.

    Returns ``True`` as soon as ``ssh target true`` exits 0; ``False`` if
    the deadline is reached without a successful connection.
    """
    return _poll_ssh(target, ["true"], timeout, interval)


def wait_for_boot_finished(
    target: str,
    timeout: float = 120,
    interval: float = 5,
) -> bool:
    """Poll until systemd reports startup finished on *target*.

    SSH becomes reachable several seconds before systemd finishes booting;
    collecting in that window makes ``systemd-analyze time`` fail with
    "Bootup is not yet finished".  This helper polls ``systemd-analyze time``
    itself — exit 0 means the exact command the probe needs is now ready.
    Requires *target* to already be SSH-reachable (call ``wait_for_ssh``
    first).
    """
    return _poll_ssh(target, ["systemd-analyze", "time"], timeout, interval)


def wait_for_observer_done(
    target: str,
    timeout: float = 300,
    interval: float = 5,
) -> bool:
    """Gate collection on the Phase 3 observer's boot_id-stamped done marker.

    Fast-degrade (spec §4.3): a single probe of the ``enabled`` marker —
    absent means the observer will not run this boot, either because it is
    intentionally off (calibration bare group: the marker is removed but
    the state directory remains, and ``ConditionPathExists`` keeps the
    unit from starting) or because it was never deployed.  In both cases
    no ``done`` marker will ever appear, so the gate passes immediately;
    one probe covers both, and pre-Phase-3 targets work unchanged.

    When the marker is present, polls until ``done`` exists and its
    content equals the current boot_id (stale markers from earlier boots
    never match).  The 300 s default covers the worst-case chain: greeter
    90 s + injection 30 s + usable 120 s + margin (spec §4.3).  Call only
    after ``wait_for_boot_finished`` succeeded, so SSH flakiness cannot
    be mistaken for a missing deployment.
    """
    if not _ssh_once(target, ["test", "-f", _ENABLED_MARKER]):
        return True
    return _poll_ssh(target, [_DONE_MATCHES_BOOT], timeout, interval)
```

Run: `uv run pytest tests/test_experiments_orchestrator.py -k observer_done -v`
Expected: 3 tests pass.

- [ ] **Step 3: Add orchestrator step 2c**

In `src/kylinbootlab/experiments/orchestrator.py`:

1. Extend the aliveness import:

```python
from kylinbootlab.experiments.aliveness import (
    wait_for_boot_finished,
    wait_for_observer_done,
    wait_for_ssh,
)
```

2. Add the module constant below `_SSH_DEADLINE_SECONDS`:

```python
_OBSERVER_DEADLINE_SECONDS: float = 300.0
```

3. Insert step 2c in `_run_one_experiment`, between step 2b and step 3:

```python
        # 2c. Phase 3 observer gate.  wait_for_observer_done fast-degrades
        # to True when the enabled marker is absent (observer off for this
        # boot — e.g. the calibration bare group — or never deployed), so
        # those boots skip straight to collection.  When enabled,
        # collecting before the boot_id-stamped done marker would truncate
        # the readiness event stream mid-boot.
        if not wait_for_observer_done(self.target, timeout=_OBSERVER_DEADLINE_SECONDS):
            raise TargetUnreachableError(
                f"observer did not finish within "
                f"{_OBSERVER_DEADLINE_SECONDS:.0f}s on {self.target} for {exp_id}"
            )
```

- [ ] **Step 4: Patch the gate in every existing orchestrator test**

Real SSH from unit tests must never happen. In `tests/test_experiments_orchestrator.py`, add this monkeypatch alongside each existing `wait_for_boot_finished` patch (4 tests: `test_run_queue_completes_three_experiments`, `test_run_queue_requeues_experiment_left_running_by_crashed_controller`, `test_run_queue_retry_succeeds_and_clears_stale_error`, `test_run_queue_survives_bundle_error_and_continues`):

```python
    monkeypatch.setattr(
        "kylinbootlab.experiments.orchestrator.wait_for_observer_done",
        lambda target, timeout=300.0: True,
    )
```

(The `wait_for_ssh`-failure tests never reach step 2c and need no patch.)

Then add the retry-path test:

```python
def test_run_queue_fails_when_observer_never_finishes(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Observer gate timeout is retryable: recovery runs, then the record fails."""
    store = RunStore(tmp_path / "runs")
    queue = ExperimentQueue(tmp_path / "queue.jsonl")
    queue.enqueue([_record("exp-observer-stuck", max_attempts=2)])

    monkeypatch.setattr(
        "kylinbootlab.experiments.orchestrator.wait_for_ssh",
        lambda target, timeout=120.0: True,
    )
    monkeypatch.setattr(
        "kylinbootlab.experiments.orchestrator.wait_for_boot_finished",
        lambda target, timeout=120.0: True,
    )
    monkeypatch.setattr(
        "kylinbootlab.experiments.orchestrator.wait_for_observer_done",
        lambda target, timeout=300.0: False,
    )

    restore_calls: list[str] = []

    def fake_restore(
        power: TargetPower, target: str, *, runner: object | None = None
    ) -> None:
        restore_calls.append(target)

    monkeypatch.setattr(RecoveryManager, "restore", fake_restore)

    power = StubPower()
    _orchestrator(queue, store, power, tmp_path).run_queue()

    (record,) = queue.list()
    assert record.status == "failed"
    assert record.attempt == 2
    assert record.error is not None
    assert "observer did not finish" in record.error
    # Recovery ran between attempts, exactly as for other retryable failures.
    assert restore_calls == [TARGET, TARGET]
```

- [ ] **Step 5: Run tests + gates**

Run: `uv run pytest tests/test_experiments_orchestrator.py -v && uv run ruff check src tests && uv run mypy src tests`
Expected: all orchestrator tests pass (existing 10 + 4 new = 14), ruff/mypy clean.

- [ ] **Step 6: Commit**

```bash
git add src/kylinbootlab/experiments/aliveness.py src/kylinbootlab/experiments/orchestrator.py tests/test_experiments_orchestrator.py
git commit -m "feat: gate collection on observer done marker"
```

---

### Task 10: Readiness Timeline in the Baseline Report (Python)

**Files:**
- Modify: `src/kylinbootlab/report.py`
- Modify: `src/kylinbootlab/templates/baseline.html.j2`
- Modify: `tests/helpers.py` (optional-capture support)
- Modify: `tests/test_report.py`

**Interfaces:**
- Consumes: `load_readiness(run_path, manifest)` and `ReadinessMetrics` from Task 2.
- Produces: `readiness_seconds(nanoseconds: int | None) -> str` — timeline formatting, `"not measured"` for `None`.
- Modifies: `write_baseline_report` — metrics.json payload gains `"readiness": readiness.model_dump(mode="json")`; the HTML gains a "User-perceived readiness" section (Login ready / Session / Desktop usable / Sentinel first window cards mirroring the existing metrics grid; a plain "observer not deployed" paragraph when `status == "absent"`). Byte-for-byte determinism is preserved.
- Modifies: `tests/helpers.create_probe_bundle` gains `optional_captures: dict[str, CaptureFixture] | None = None` — extra artifacts written with `required=False` (existing callers unchanged).

- [ ] **Step 1: Extend the test helper**

In `tests/helpers.py`, replace `create_probe_bundle` with:

```python
def create_probe_bundle(
    root: Path,
    run_id: UUID = RUN_ID,
    optional_captures: dict[str, CaptureFixture] | None = None,
) -> Path:
    bundle = root / "bundle"
    captures = bundle / "captures"
    captures.mkdir(parents=True)
    artifacts: list[ArtifactRecord] = []

    documents: list[tuple[str, CaptureFixture, bool]] = [
        (name, document, True) for name, document in CAPTURES.items()
    ]
    documents.extend(
        (name, document, False)
        for name, document in (optional_captures or {}).items()
    )
    for name, document, required in documents:
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
                required=required,
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

- [ ] **Step 2: Write the failing report tests**

Append to `tests/test_report.py` (extend the import block: `from kylinbootlab.report import readiness_seconds, seconds, write_baseline_report`; add `from tests.helpers import CaptureFixture`):

```python
FIXTURE_EVENTS = Path("tests/fixtures/readiness-events-v1.jsonl").read_text(encoding="utf-8")


def _readiness_capture(stdout: str) -> CaptureFixture:
    return {
        "command": ["cat", "/var/lib/kylinbootlab/observe/current.jsonl"],
        "exit_code": 0,
        "stdout": stdout,
        "stderr": "",
    }


def test_readiness_seconds_formats_none_as_not_measured() -> None:
    assert readiness_seconds(None) == "not measured"
    assert readiness_seconds(18_100_000_000) == "18.100 s"


def test_report_includes_complete_readiness_timeline(tmp_path: Path) -> None:
    store = RunStore(tmp_path / "runs")
    store.ingest(
        create_probe_bundle(
            tmp_path / "source",
            optional_captures={"readiness-events": _readiness_capture(FIXTURE_EVENTS)},
        )
    )

    paths = write_baseline_report(store, RUN_ID)

    metrics = json.loads(paths.metrics_json.read_text(encoding="utf-8"))
    assert metrics["readiness"]["status"] == "complete"
    assert metrics["readiness"]["mode"] == "benchmark"
    assert metrics["readiness"]["login_ready_ns"] == 8_500_000_000
    assert metrics["readiness"]["usable_ns"] == 18_100_000_000
    html = paths.html.read_text(encoding="utf-8")
    assert "User-perceived readiness" in html
    assert "18.100 s" in html  # Tusable
    assert "11.500 s" in html  # Tsession


def test_report_marks_absent_readiness(tmp_path: Path) -> None:
    store = RunStore(tmp_path / "runs")
    store.ingest(create_probe_bundle(tmp_path / "source"))

    paths = write_baseline_report(store, RUN_ID)

    metrics = json.loads(paths.metrics_json.read_text(encoding="utf-8"))
    assert metrics["readiness"]["status"] == "absent"
    assert "observer not deployed" in paths.html.read_text(encoding="utf-8")


def test_report_renders_incomplete_readiness_as_not_measured(tmp_path: Path) -> None:
    # Events through session_opened only — no usable, no timeout marker yet.
    truncated = "\n".join(FIXTURE_EVENTS.splitlines()[:8]) + "\n"
    store = RunStore(tmp_path / "runs")
    store.ingest(
        create_probe_bundle(
            tmp_path / "source",
            optional_captures={"readiness-events": _readiness_capture(truncated)},
        )
    )

    paths = write_baseline_report(store, RUN_ID)

    metrics = json.loads(paths.metrics_json.read_text(encoding="utf-8"))
    assert metrics["readiness"]["status"] == "incomplete"
    assert metrics["readiness"]["usable_ns"] is None
    html = paths.html.read_text(encoding="utf-8")
    assert "not measured" in html  # usable + sentinel cards
    assert "11.500 s" in html  # session still shown
```

Run: `uv run pytest tests/test_report.py -v`
Expected: FAIL — `readiness_seconds` does not exist, no `readiness` key in metrics.

- [ ] **Step 3: Implement report.py changes**

In `src/kylinbootlab/report.py`:

1. Add the import:

```python
from kylinbootlab.readiness import load_readiness
```

2. Add below `seconds`:

```python
def readiness_seconds(nanoseconds: int | None) -> str:
    """Timeline formatting: absent measurements render as "not measured"."""
    if nanoseconds is None:
        return "not measured"
    return f"{nanoseconds / 1_000_000_000:.3f} s"
```

3. In `write_baseline_report`, after `boot, units = analyze_run(store, run_id)` add:

```python
    readiness = load_readiness(run_path, manifest)
```

4. Extend the metrics payload dict:

```python
        "readiness": readiness.model_dump(mode="json"),
```

5. Extend `template.render(...)` with:

```python
            readiness_status=readiness.status,
            readiness_mode=readiness.mode or "n/a",
            login_ready_time=readiness_seconds(readiness.login_ready_ns),
            session_time=readiness_seconds(readiness.session_ns),
            usable_time=readiness_seconds(readiness.usable_ns),
            sentinel_time=readiness_seconds(readiness.sentinel_first_window_ns),
```

- [ ] **Step 4: Extend the HTML template**

In `src/kylinbootlab/templates/baseline.html.j2`, insert between the boot-timing `</section>` and `<h2>Methodology</h2>`:

```html
      <h2>User-perceived readiness</h2>
      {% if readiness_status == "absent" %}
      <p class="meta">No readiness event stream in this run — observer not deployed (optional Phase 3 artifact).</p>
      {% else %}
      <p class="meta">Observer mode: {{ readiness_mode }} · status: {{ readiness_status }}</p>
      <section class="metrics" aria-label="Readiness timeline">
        <div class="metric">Login ready<strong>{{ login_ready_time }}</strong></div>
        <div class="metric">Session<strong>{{ session_time }}</strong></div>
        <div class="metric">Desktop usable<strong>{{ usable_time }}</strong></div>
        <div class="metric">Sentinel first window<strong>{{ sentinel_time }}</strong></div>
      </section>
      {% endif %}
```

Also extend the Methodology paragraph's final sentence with the readiness provenance — replace `Each run is checksummed end-to-end and stored immutably.` with:

```html
Each run is checksummed end-to-end and stored immutably. Readiness T-points (login ready, session, usable) are derived from the immutable ReadinessEvent JSONL stream captured by the on-target observer; diagnostic-mode runs are labeled and excluded from formal statistics.
```

- [ ] **Step 5: Run tests + gates**

Run: `uv run pytest tests/test_report.py tests/test_store.py tests/test_cli.py -v && uv run ruff check src tests && uv run mypy src tests`
Expected: all pass — including the pre-existing determinism test (absent branch renders identically twice) and the store/CLI tests over the extended helper.

- [ ] **Step 6: Commit**

```bash
git add src/kylinbootlab/report.py src/kylinbootlab/templates/baseline.html.j2 tests/helpers.py tests/test_report.py
git commit -m "feat: add readiness timeline to baseline report"
```

---

### Task 11: kbl calibrate (Python)

**Files:**
- Create: `src/kylinbootlab/calibrate.py`
- Modify: `src/kylinbootlab/cli.py` (add `kbl calibrate`)
- Create: `tests/test_calibrate.py`

**Interfaces:**
- Produces: `GroupStats { profile: str, runs: NonNegativeInt, os_total_median_ns: NonNegativeInt, graphical_median_ns: NonNegativeInt | None }`; `CalibrationReport { schema_version: Literal[1], bare: GroupStats, benchmark: GroupStats, os_total_delta_percent: float, graphical_delta_percent: float | None, passed: bool }`; `CalibrationError(RuntimeError)`.
- Produces: `marker_command(target: str, profile: str) -> list[str]`; `set_observer_marker(target, profile, run=None) -> None`; `median_ns(values: list[int]) -> int`; `delta_percent(bare: int, benchmark: int) -> float`; `evaluate(bare: GroupStats, benchmark: GroupStats) -> CalibrationReport`; `group_stats(store: RunStore, queue: ExperimentQueue, profile: str) -> GroupStats`; `MarkerPreservingPower(inner: TargetPower)`; `run_calibration(queue_file: Path, store: RunStore, power: TargetPower, target: str, incoming_root: Path, per_group: int = 10) -> CalibrationReport`.
- Produces: `kbl calibrate` CLI command — prints per-group medians + deltas + PASS/FAIL, writes the verdict JSON, exits 1 on fail.

**Binding scope decision (v1):** two automated groups — `calib-bare` (marker removed via `ssh rm -f .../observe/enabled`) and `calib-benchmark` (`ssh touch` marker; `mode = "benchmark"` is the installed observe.toml default). The **diagnostic** group requires a root edit of observe.toml (`mode = "diagnostic"`), so it stays a documented manual step in the runbook (Task 12); its numbers are recorded, never gated.

**Correctness note (why `MarkerPreservingPower` exists):** the Phase 2 loop restores the `baseline` snapshot before every boot, which would silently revert the on-disk `enabled` marker and turn every group into `bare` (the calibration would trivially "pass" at 0%). The wrapper maps `power_off`/`snapshot_restore` to no-ops so the guest stays up between experiments and the orchestrator's boot step takes the `reset()` branch — a hard reboot that preserves the marker. Both groups boot with identical mechanics, which is exactly what a relative-overhead comparison needs. Group isolation invariant: groups are enqueued lazily and strictly in sequence, so the shared queue never holds pending records of two profiles at once and a group's marker can never leak into the other group's boots. Pass criterion is **signed** delta `< 1.0 %` for BOTH `os_total_ns` and `graphical_target_from_t0_ns` medians (a faster benchmark group passes; missing graphical data fails — the spec metric must be provable). The same no-op mapping weakens layer-1 recovery during calibration — `snapshot_restore` does nothing and `power_on` on a running VM is a no-op, so a hung guest cannot be revived and the record fails once retries exhaust — which is acceptable for calibration because failed runs are excluded from the statistics (`group_stats` already requires completed runs).

- [ ] **Step 1: Write the failing tests**

Create `tests/test_calibrate.py`:

```python
import json
import subprocess
from datetime import UTC, datetime
from pathlib import Path
from uuid import UUID, uuid4

import pytest
from typer.testing import CliRunner

from kylinbootlab.calibrate import (
    CalibrationError,
    GroupStats,
    MarkerPreservingPower,
    delta_percent,
    evaluate,
    group_stats,
    marker_command,
    median_ns,
    run_calibration,
    set_observer_marker,
)
from kylinbootlab.cli import app
from kylinbootlab.experiments.contracts import ExperimentRecord
from kylinbootlab.experiments.queue import ExperimentQueue
from kylinbootlab.store import RunStore
from tests.helpers import create_probe_bundle

runner = CliRunner()


# -- test doubles ------------------------------------------------------------


class RecordingPower:
    """TargetPower double recording every call."""

    def __init__(self) -> None:
        self.calls: list[str] = []

    def power_on(self) -> None:
        self.calls.append("power_on")

    def power_off(self) -> None:
        self.calls.append("power_off")

    def reset(self) -> None:
        self.calls.append("reset")

    def snapshot_create(self, name: str) -> None:
        self.calls.append(f"snapshot_create:{name}")

    def snapshot_restore(self, name: str) -> None:
        self.calls.append(f"snapshot_restore:{name}")

    def guest_alive(self) -> bool:
        self.calls.append("guest_alive")
        return True


class RaisingPower:
    """Fails the test if calibration touches power in summarize-only mode."""

    def power_on(self) -> None:
        raise AssertionError("power_on must not be called")

    def power_off(self) -> None:
        raise AssertionError("power_off must not be called")

    def reset(self) -> None:
        raise AssertionError("reset must not be called")

    def snapshot_create(self, name: str) -> None:
        raise AssertionError("snapshot_create must not be called")

    def snapshot_restore(self, name: str) -> None:
        raise AssertionError("snapshot_restore must not be called")

    def guest_alive(self) -> bool:
        raise AssertionError("guest_alive must not be called")


def _done_record(exp_id: str, profile: str, run_id: UUID) -> ExperimentRecord:
    return ExperimentRecord(
        exp_id=exp_id,
        profile=profile,
        status="done",
        run_id=run_id,
        created_at=datetime(2026, 7, 18, 12, 0, tzinfo=UTC),
    )


def _seed_runs(tmp_path: Path, count: int) -> tuple[RunStore, list[UUID]]:
    store = RunStore(tmp_path / "runs")
    run_ids: list[UUID] = []
    for index in range(count):
        run_id = uuid4()
        store.ingest(create_probe_bundle(tmp_path / f"src-{index}", run_id=run_id))
        run_ids.append(run_id)
    return store, run_ids


def _stats(profile: str, os_total: int, graphical: int | None) -> GroupStats:
    return GroupStats(
        profile=profile,
        runs=10,
        os_total_median_ns=os_total,
        graphical_median_ns=graphical,
    )


# -- marker toggling ----------------------------------------------------------


def test_marker_command_bare_removes_marker() -> None:
    command = marker_command("kbl@target.local", "calib-bare")
    assert command[0] == "ssh"
    assert "kbl@target.local" in command
    assert command[-1] == "rm -f /var/lib/kylinbootlab/observe/enabled"


def test_marker_command_benchmark_touches_marker() -> None:
    command = marker_command("kbl@target.local", "calib-benchmark")
    assert command[-1] == "touch /var/lib/kylinbootlab/observe/enabled"


def test_marker_command_rejects_unknown_profile() -> None:
    with pytest.raises(CalibrationError, match="unknown calibration profile"):
        marker_command("kbl@target.local", "calib-diagnostic")


def test_set_observer_marker_raises_on_ssh_failure() -> None:
    def failing_run(args: list[str]) -> subprocess.CompletedProcess[str]:
        return subprocess.CompletedProcess(args, 255, stdout="", stderr="lost connection")

    with pytest.raises(CalibrationError, match="lost connection"):
        set_observer_marker("kbl@target.local", "calib-bare", run=failing_run)


def test_set_observer_marker_runs_command() -> None:
    calls: list[list[str]] = []

    def fake_run(args: list[str]) -> subprocess.CompletedProcess[str]:
        calls.append(args)
        return subprocess.CompletedProcess(args, 0, stdout="", stderr="")

    set_observer_marker("kbl@target.local", "calib-benchmark", run=fake_run)
    assert len(calls) == 1
    assert "touch" in calls[0][-1]


# -- statistics ----------------------------------------------------------------


def test_median_ns_handles_odd_and_even_counts() -> None:
    assert median_ns([3, 1, 2]) == 2
    assert median_ns([1, 2, 3, 10]) == 2  # int(2.5)


def test_median_ns_rejects_empty() -> None:
    with pytest.raises(CalibrationError, match="zero runs"):
        median_ns([])


def test_delta_percent_signed() -> None:
    assert delta_percent(10_000_000_000, 10_050_000_000) == pytest.approx(0.5)
    assert delta_percent(10_000_000_000, 9_900_000_000) == pytest.approx(-1.0)


def test_delta_percent_rejects_zero_baseline() -> None:
    with pytest.raises(CalibrationError, match="zero"):
        delta_percent(0, 1)


def test_evaluate_passes_under_one_percent() -> None:
    report = evaluate(
        _stats("calib-bare", 10_000_000_000, 8_000_000_000),
        _stats("calib-benchmark", 10_099_000_000, 8_070_000_000),
    )
    assert report.passed
    assert report.os_total_delta_percent == pytest.approx(0.99)


def test_evaluate_fails_at_exactly_one_percent() -> None:
    report = evaluate(
        _stats("calib-bare", 10_000_000_000, 8_000_000_000),
        _stats("calib-benchmark", 10_100_000_000, 8_000_000_000),
    )
    assert not report.passed


def test_evaluate_negative_overhead_passes() -> None:
    report = evaluate(
        _stats("calib-bare", 10_000_000_000, 8_000_000_000),
        _stats("calib-benchmark", 9_500_000_000, 7_600_000_000),
    )
    assert report.passed


def test_evaluate_fails_without_graphical_medians() -> None:
    report = evaluate(
        _stats("calib-bare", 10_000_000_000, None),
        _stats("calib-benchmark", 10_000_000_000, None),
    )
    assert report.graphical_delta_percent is None
    assert not report.passed


# -- marker-preserving power wrapper -------------------------------------------


def test_marker_preserving_power_noops_off_and_restore() -> None:
    inner = RecordingPower()
    wrapper = MarkerPreservingPower(inner)

    wrapper.power_off()
    wrapper.snapshot_restore("baseline")
    wrapper.reset()
    wrapper.power_on()
    assert wrapper.guest_alive() is True

    assert inner.calls == ["reset", "power_on", "guest_alive"]


# -- group statistics from the store -------------------------------------------


def test_group_stats_reads_metrics_for_done_runs(tmp_path: Path) -> None:
    store, run_ids = _seed_runs(tmp_path, 2)
    queue = ExperimentQueue(tmp_path / "queue.jsonl")
    queue.enqueue(
        [
            _done_record("calib-bare-000", "calib-bare", run_ids[0]),
            _done_record("calib-bare-001", "calib-bare", run_ids[1]),
        ]
    )

    stats = group_stats(store, queue, "calib-bare")

    assert stats.runs == 2
    assert stats.os_total_median_ns == 3_000_000_000  # helpers fixture total
    assert stats.graphical_median_ns == 2_500_000_000  # 1.0s kernel + 1.5s graphical


def test_group_stats_rejects_profile_without_runs(tmp_path: Path) -> None:
    store = RunStore(tmp_path / "runs")
    queue = ExperimentQueue(tmp_path / "queue.jsonl")
    with pytest.raises(CalibrationError, match="no completed runs"):
        group_stats(store, queue, "calib-bare")


# -- run_calibration resume path ------------------------------------------------


def _seed_finished_calibration(tmp_path: Path) -> tuple[RunStore, Path]:
    store, run_ids = _seed_runs(tmp_path, 4)
    queue_file = tmp_path / "calibration.jsonl"
    queue = ExperimentQueue(queue_file)
    queue.enqueue(
        [
            _done_record("calib-bare-000", "calib-bare", run_ids[0]),
            _done_record("calib-bare-001", "calib-bare", run_ids[1]),
            _done_record("calib-benchmark-000", "calib-benchmark", run_ids[2]),
            _done_record("calib-benchmark-001", "calib-benchmark", run_ids[3]),
        ]
    )
    return store, queue_file


def test_run_calibration_summarizes_finished_queue_without_power(tmp_path: Path) -> None:
    """All experiments done: no SSH, no power calls — pure summarization."""
    store, queue_file = _seed_finished_calibration(tmp_path)

    report = run_calibration(
        queue_file=queue_file,
        store=store,
        power=RaisingPower(),
        target="kbl@stub",
        incoming_root=tmp_path / "incoming",
        per_group=2,
    )

    assert report.passed  # identical fixture medians -> 0% delta
    assert report.bare.runs == 2
    assert report.benchmark.runs == 2
    assert report.os_total_delta_percent == pytest.approx(0.0)


def test_cli_calibrate_summarizes_and_writes_report(tmp_path: Path) -> None:
    store, queue_file = _seed_finished_calibration(tmp_path)
    report_out = tmp_path / "calibration-report.json"

    result = runner.invoke(
        app,
        [
            "calibrate",
            "--target", "kbl@stub",
            "--backend", "vix",
            "--vmx-path", "C:/vm/openkylin.vmx",
            "--queue-file", str(queue_file),
            "--data-root", str(tmp_path / "runs"),
            "--incoming-root", str(tmp_path / "incoming"),
            "--per-group", "2",
            "--report-out", str(report_out),
        ],
    )

    assert result.exit_code == 0, result.stdout
    assert "CALIBRATION PASS" in result.stdout
    payload = json.loads(report_out.read_text(encoding="utf-8"))
    assert payload["passed"] is True
    assert payload["bare"]["runs"] == 2
```

Run: `uv run pytest tests/test_calibrate.py -v`
Expected: FAIL — `kylinbootlab.calibrate` does not exist.

- [ ] **Step 2: Implement calibrate.py**

Create `src/kylinbootlab/calibrate.py`:

```python
"""Observer-overhead calibration (spec §7).

v1 automates the two groups the <1 % gate needs — ``calib-bare`` (enabled
marker removed) and ``calib-benchmark`` (marker present; ``mode =
"benchmark"`` is the installed observe.toml default) — through the
unmodified Phase 2 orchestrator.  The ``diagnostic`` group requires a root
edit of observe.toml, so it stays a documented manual runbook step; its
numbers are recorded, never gated.

Why calibration boots are warm resets: the Phase 2 loop restores the
``baseline`` snapshot before every boot, which would silently revert the
on-disk enabled marker and turn every group into ``bare``.
:class:`MarkerPreservingPower` maps ``power_off``/``snapshot_restore`` to
no-ops so each boot is a guest reset — identical mechanics for both
groups, which is what a relative-overhead comparison needs.
"""

import json
import statistics
import subprocess
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path
from typing import Literal

from pydantic import NonNegativeInt

from kylinbootlab.contracts import ContractModel
from kylinbootlab.experiments.aliveness import wait_for_ssh
from kylinbootlab.experiments.contracts import ExperimentRecord
from kylinbootlab.experiments.orchestrator import ExperimentOrchestrator
from kylinbootlab.experiments.power import TargetPower
from kylinbootlab.experiments.queue import ExperimentQueue
from kylinbootlab.report import write_baseline_report
from kylinbootlab.store import RunStore

#: Automated calibration groups, in execution order (bare first).
PROFILES: tuple[str, ...] = ("calib-bare", "calib-benchmark")

_ENABLED_MARKER = "/var/lib/kylinbootlab/observe/enabled"
_SSH_OPTIONS = [
    "-o", "BatchMode=yes",
    "-o", "ConnectTimeout=15",
]

type _Runner = Callable[[list[str]], subprocess.CompletedProcess[str]]


class CalibrationError(RuntimeError):
    """Calibration could not produce a verdict (toggle failed, no runs, ...)."""


class GroupStats(ContractModel):
    """Median boot metrics over one calibration group's completed runs."""

    profile: str
    runs: NonNegativeInt
    os_total_median_ns: NonNegativeInt
    graphical_median_ns: NonNegativeInt | None


class CalibrationReport(ContractModel):
    """The <1 % benchmark-overhead verdict (spec §7)."""

    schema_version: Literal[1] = 1
    bare: GroupStats
    benchmark: GroupStats
    os_total_delta_percent: float
    graphical_delta_percent: float | None
    passed: bool


def marker_command(target: str, profile: str) -> list[str]:
    """SSH command toggling the observer marker for *profile*.

    No sudo needed: the state directory is kbl-group-writable by design
    (spec §4.5 permission model).
    """
    if profile == "calib-bare":
        action = f"rm -f {_ENABLED_MARKER}"
    elif profile == "calib-benchmark":
        action = f"touch {_ENABLED_MARKER}"
    else:
        raise CalibrationError(f"unknown calibration profile: {profile}")
    return ["ssh", *_SSH_OPTIONS, target, action]


def _run_ssh(args: list[str]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(args, check=False, capture_output=True, text=True, timeout=30)


def set_observer_marker(target: str, profile: str, run: _Runner | None = None) -> None:
    """Toggle the on-target enabled marker; raises on SSH failure."""
    execute = run if run is not None else _run_ssh
    result = execute(marker_command(target, profile))
    if result.returncode != 0:
        raise CalibrationError(
            f"failed to toggle observer marker for {profile}: {result.stderr.strip()}"
        )


def median_ns(values: list[int]) -> int:
    if not values:
        raise CalibrationError("cannot take the median of zero runs")
    return int(statistics.median(values))


def delta_percent(bare: int, benchmark: int) -> float:
    if bare == 0:
        raise CalibrationError("bare median is zero; cannot compute overhead")
    return (benchmark - bare) / bare * 100.0


def evaluate(bare: GroupStats, benchmark: GroupStats) -> CalibrationReport:
    """Verdict per spec §7: BOTH medians must differ by < 1 % (signed —
    a faster benchmark group passes; missing graphical data fails because
    the spec metric must be provable)."""
    os_delta = delta_percent(bare.os_total_median_ns, benchmark.os_total_median_ns)
    graphical_delta: float | None = None
    if bare.graphical_median_ns is not None and benchmark.graphical_median_ns is not None:
        graphical_delta = delta_percent(
            bare.graphical_median_ns, benchmark.graphical_median_ns
        )
    passed = os_delta < 1.0 and graphical_delta is not None and graphical_delta < 1.0
    return CalibrationReport(
        bare=bare,
        benchmark=benchmark,
        os_total_delta_percent=os_delta,
        graphical_delta_percent=graphical_delta,
        passed=passed,
    )


def group_stats(store: RunStore, queue: ExperimentQueue, profile: str) -> GroupStats:
    """Medians over every ``done`` run of *profile*, read from each run's
    regenerated metrics.json (``write_baseline_report`` is deterministic
    and idempotent)."""
    os_totals: list[int] = []
    graphicals: list[int] = []
    runs = 0
    for record in queue.list("done"):
        if record.profile != profile or record.run_id is None:
            continue
        paths = write_baseline_report(store, record.run_id)
        payload = json.loads(paths.metrics_json.read_text(encoding="utf-8"))
        boot = payload["boot"]
        os_totals.append(int(boot["os_total_ns"]))
        if boot["graphical_target_from_t0_ns"] is not None:
            graphicals.append(int(boot["graphical_target_from_t0_ns"]))
        runs += 1
    if runs == 0:
        raise CalibrationError(f"no completed runs for profile {profile}")
    # Only report a graphical median when EVERY run reported the metric —
    # a mixed group would skew the comparison.
    graphical_median = median_ns(graphicals) if len(graphicals) == runs else None
    return GroupStats(
        profile=profile,
        runs=runs,
        os_total_median_ns=median_ns(os_totals),
        graphical_median_ns=graphical_median,
    )


class MarkerPreservingPower:
    """TargetPower decorator for calibration boots.

    ``power_off`` and ``snapshot_restore`` become no-ops so the guest stays
    up between experiments and the orchestrator's boot step takes the
    ``reset()`` branch — a hard reboot that preserves the on-disk enabled
    marker, which a baseline-snapshot restore would silently revert.
    Everything else passes through.
    """

    def __init__(self, inner: TargetPower) -> None:
        self._inner = inner

    def power_on(self) -> None:
        self._inner.power_on()

    def power_off(self) -> None:
        """Keep the guest (and the observer marker) alive between boots."""

    def reset(self) -> None:
        self._inner.reset()

    def snapshot_create(self, name: str) -> None:
        self._inner.snapshot_create(name)

    def snapshot_restore(self, name: str) -> None:
        """Never revert the disk mid-calibration — the marker must survive."""

    def guest_alive(self) -> bool:
        return self._inner.guest_alive()


def _ensure_guest_up(power: TargetPower, target: str) -> None:
    if not power.guest_alive():
        power.power_on()
    if not wait_for_ssh(target, timeout=180):
        raise CalibrationError(f"target {target} not reachable to toggle the marker")


def run_calibration(
    queue_file: Path,
    store: RunStore,
    power: TargetPower,
    target: str,
    incoming_root: Path,
    per_group: int = 10,
) -> CalibrationReport:
    """Drive both groups through the Phase 2 loop and return the verdict.

    Groups run strictly in sequence and each is enqueued only when its
    predecessor has drained, so the shared queue never holds pending
    records of two profiles at once — the marker toggled before a group
    can never leak into the other group's boots.  Re-running resumes:
    existing exp_ids are kept, fully finished groups are only summarized
    (no SSH, no power operations).
    """
    queue = ExperimentQueue(queue_file)
    calibration_power = MarkerPreservingPower(power)

    for profile in PROFILES:
        known = {record.exp_id for record in queue.list()}
        fresh = [
            ExperimentRecord(
                exp_id=f"{profile}-{index:03d}",
                profile=profile,
                status="pending",
                created_at=datetime.now(UTC),
            )
            for index in range(per_group)
            if f"{profile}-{index:03d}" not in known
        ]
        if fresh:
            queue.enqueue(fresh)
        has_work = any(
            record.profile == profile and record.status in {"pending", "running"}
            for record in queue.list()
        )
        if not has_work:
            continue  # group already finished — summarize later
        _ensure_guest_up(power, target)
        set_observer_marker(target, profile)
        ExperimentOrchestrator(
            queue=queue,
            store=store,
            power=calibration_power,
            target=target,
            incoming_root=incoming_root,
        ).run_queue()

    return evaluate(
        group_stats(store, queue, "calib-bare"),
        group_stats(store, queue, "calib-benchmark"),
    )
```

- [ ] **Step 3: Add the CLI command**

In `src/kylinbootlab/cli.py`, add the import:

```python
from kylinbootlab.calibrate import run_calibration
```

and append below the `collect` command (before the Phase 2 experiment group):

```python
@app.command()
def calibrate(
    target: Annotated[str, typer.Option(help="SSH destination")]
    = "kbl@192.168.19.128",
    data_root: DataRoot = Path("var/runs"),
    incoming_root: Annotated[Path, typer.Option(help="Incoming bundle root")]
    = Path("var/incoming"),
    queue_file: QueueFile = Path("var/calibration.jsonl"),
    per_group: Annotated[int, typer.Option(help="Cold boots per group")] = 10,
    backend: Annotated[str, typer.Option(help="Power backend: vix | wol")] = "vix",
    vmx_path: Annotated[str | None, typer.Option(help="VMX path for the vix backend")]
    = None,
    mac: Annotated[str | None, typer.Option(help="MAC address for the wol backend")]
    = None,
    report_out: Annotated[Path, typer.Option(help="Calibration verdict JSON path")]
    = Path("var/calibration-report.json"),
) -> None:
    """Run the bare/benchmark observer-overhead calibration (spec §7)."""
    kwargs: dict[str, str] = {"target": target}
    if vmx_path:
        kwargs["vmx_path"] = vmx_path
    if mac:
        kwargs["mac"] = mac
    power = power_backend_factory(backend, **kwargs)

    verdict = run_calibration(
        queue_file=queue_file,
        store=RunStore(data_root),
        power=power,
        target=target,
        incoming_root=incoming_root,
        per_group=per_group,
    )
    report_out.parent.mkdir(parents=True, exist_ok=True)
    report_out.write_text(
        verdict.model_dump_json(indent=2) + "\n", encoding="utf-8", newline="\n"
    )

    for group in (verdict.bare, verdict.benchmark):
        graphical = (
            f"{group.graphical_median_ns / 1e9:.3f}s"
            if group.graphical_median_ns is not None
            else "n/a"
        )
        typer.echo(
            f"{group.profile}: {group.runs} runs, "
            f"os_total median {group.os_total_median_ns / 1e9:.3f}s, "
            f"graphical median {graphical}"
        )
    graphical_delta = (
        f"{verdict.graphical_delta_percent:+.3f}%"
        if verdict.graphical_delta_percent is not None
        else "n/a"
    )
    typer.echo(
        f"os_total delta {verdict.os_total_delta_percent:+.3f}% / "
        f"graphical delta {graphical_delta}"
    )
    if not verdict.passed:
        typer.echo("CALIBRATION FAIL: benchmark overhead >= 1% (or graphical unmeasured)")
        raise typer.Exit(code=1)
    typer.echo("CALIBRATION PASS: benchmark overhead < 1%")
```

- [ ] **Step 4: Run tests + gates**

Run: `uv run pytest tests/test_calibrate.py -v && uv run pytest -q --ignore=tests/test_rust_contract.py && uv run ruff check src tests && uv run mypy src tests`
Expected: 18 calibrate tests pass, full suite green, ruff/mypy clean.

- [ ] **Step 5: Commit**

```bash
git add src/kylinbootlab/calibrate.py src/kylinbootlab/cli.py tests/test_calibrate.py
git commit -m "feat: add kbl calibrate overhead protocol"
```

---

### Task 12: Target Install Assets + Runbook

**Files:**
- Create: `scripts/target/kbl-observe.service`
- Create: `scripts/target/kbl-usable-probe.desktop`
- Create: `scripts/target/install_observer.sh`
- Create: `docs/runbooks/observability-readiness.md`

**Interfaces:**
- Produces: `install_observer.sh BINARY TARGET_USER PASSWORD` — one-sudo idempotent installer (style of `install_bootprobe.sh`): installs the binary, writes `/etc/kylinbootlab/observe.toml` (root 0600), installs + enables the systemd unit, installs the autostart entry into `/home/<user>/.config/autostart/`, creates the kbl-group-writable state dir, touches the enabled marker, prints next steps. Root check exits 64; password charset validated.
- Produces: the runbook — deploy procedure, pattern refinement (tunable in observe.toml without recompile), calibration how-to (incl. the manual diagnostic group), wrong-password drill, troubleshooting.

- [ ] **Step 1: Write the systemd unit**

Create `scripts/target/kbl-observe.service`:

```ini
[Unit]
Description=KylinBootLab boot readiness observer (Phase 3)
# Toggled by the controller WITHOUT sudo: the marker lives in the
# kbl-group-writable state dir.  Marker absent = bare boot, zero overhead.
ConditionPathExists=/var/lib/kylinbootlab/observe/enabled
After=systemd-journald.service

[Service]
Type=simple
ExecStart=/usr/local/bin/kbl-bootprobe observe
# A restart would pollute the readiness timeline (spec §8): never restart.
# A late start is harmless: journalctl -b 0 -f replays from boot start.
Restart=no
Nice=10

[Install]
WantedBy=graphical.target
```

- [ ] **Step 2: Write the autostart entry**

Create `scripts/target/kbl-usable-probe.desktop`:

```ini
[Desktop Entry]
Type=Application
Name=KBL Usable Probe
Comment=KylinBootLab session-side readiness probe (Phase 3)
Exec=/usr/local/bin/kbl-bootprobe usable-probe
X-GNOME-Autostart-enabled=true
NoDisplay=true
```

(The probe itself exits instantly when the enabled marker is absent, so the autostart entry costs nothing on bare boots.)

- [ ] **Step 3: Write the installer**

Create `scripts/target/install_observer.sh`:

```bash
#!/usr/bin/env bash
set -euo pipefail

# install_observer.sh — one-sudo installer for the Phase 3 readiness observer.
# Installs the probe binary, the root observer unit, the session usable-probe
# autostart entry, the root-only observe.toml, and the shared state dir.

if [[ $EUID -ne 0 || $# -ne 3 ]]; then
  printf 'usage: sudo install_observer.sh BINARY TARGET_USER PASSWORD\n' >&2
  printf '  PASSWORD: TARGET_USER login password, lowercase letters+digits only\n' >&2
  exit 64
fi

readonly binary="$1"
readonly target_user="$2"
readonly password="$3"
readonly script_dir="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"

if [[ ! -x "$binary" ]]; then
  printf 'probe binary is not executable: %s\n' "$binary" >&2
  exit 66
fi
if ! id "$target_user" >/dev/null 2>&1; then
  printf 'target user does not exist: %s\n' "$target_user" >&2
  exit 67
fi
if [[ ! "$password" =~ ^[a-z0-9]+$ ]]; then
  printf 'password must be lowercase letters and digits only (spec constraint)\n' >&2
  exit 65
fi

getent group kbl >/dev/null 2>&1 || groupadd --system kbl
usermod --append --groups kbl "$target_user"
install -o root -g root -m 0755 "$binary" /usr/local/bin/kbl-bootprobe

# Shared state dir: root observer writes the stream, the kbl session probe
# writes its result file, the controller toggles the enabled marker over
# plain SSH — hence group-writable with setgid (no runtime sudo anywhere).
install -d -o root -g kbl -m 2750 /var/lib/kylinbootlab
install -d -o root -g kbl -m 2775 /var/lib/kylinbootlab/observe

install -d -o root -g root -m 0755 /etc/kylinbootlab
config_temp="$(mktemp)"
trap 'rm -f "$config_temp"' EXIT
cat >"$config_temp" <<EOF
# KylinBootLab Phase 3 observer configuration (root 0600 — contains the
# login password).  Omitted fields use built-in defaults.
mode = "benchmark"
target_user = "${target_user}"
password = "${password}"
# Refine after the first real login (see runbook section 4):
# desktop_processes = ["ukui-panel", "ukui-settings-daemon"]
# sentinel_command = ["mate-terminal"]
# greeter_ready_pattern = "ukui-greeter"
# session_opened_pattern = "session opened for user"
EOF
install -o root -g root -m 0600 "$config_temp" /etc/kylinbootlab/observe.toml

install -o root -g root -m 0644 "$script_dir/kbl-observe.service" \
  /etc/systemd/system/kbl-observe.service
systemctl daemon-reload
systemctl enable kbl-observe.service

readonly autostart_dir="/home/${target_user}/.config/autostart"
install -d -o "$target_user" -g "$target_user" "$autostart_dir"
install -o "$target_user" -g "$target_user" -m 0644 \
  "$script_dir/kbl-usable-probe.desktop" "$autostart_dir/kbl-usable-probe.desktop"

touch /var/lib/kylinbootlab/observe/enabled
chgrp kbl /var/lib/kylinbootlab/observe/enabled
chmod 0664 /var/lib/kylinbootlab/observe/enabled

printf 'observer installed and enabled (marker present -> observes next boot)\n'
printf 'next steps:\n'
printf '  1. verify unit: systemctl cat kbl-observe.service\n'
printf '  2. reboot, then inspect /var/lib/kylinbootlab/observe/current.jsonl\n'
printf '  3. refine desktop_processes/patterns in /etc/kylinbootlab/observe.toml\n'
printf 'NOTE: the password was passed on the command line; clear your shell history\n'
```

- [ ] **Step 4: Validate script syntax**

Run: `bash -n scripts/target/install_observer.sh`
Expected: exit 0.

- [ ] **Step 5: Write the runbook**

Create `docs/runbooks/observability-readiness.md`:

```markdown
# Runbook: Phase 3 Observability & Readiness

Deploy and verify the dual-component readiness observer on an openKylin
2.0 SP2 target that already passed the Phase 1/2 runbooks.

## 1. Prerequisites

- Phase 1 foundation deployed (`install_bootprobe.sh` done, `kbl collect` works).
- Phase 2 testbed verified (`kbl experiment run` drains a queue).
- Target packages: `busctl` (systemd), `dbus-send` (dbus-bin), `mate-terminal`.
  Check: `ssh kbl@kbl-target.local 'command -v busctl dbus-send mate-terminal'`.
- The kbl account password uses ONLY lowercase letters and digits (spec §10);
  change it first if needed: `passwd`.

## 2. Build and install

On the target (native build avoids cross toolchains):

    git clone https://github.com/LanceGan/openkylin.git && cd openkylin
    git checkout worktree-kylinbootlab-phase1
    cargo build --release -p kbl-bootprobe
    sudo bash scripts/target/install_observer.sh \
        target/release/kbl-bootprobe kbl <password>
    history -c   # the password appeared on the command line

The installer leaves the observer ENABLED (marker present). Disable at any
time without sudo: `rm /var/lib/kylinbootlab/observe/enabled`.

## 3. First supervised observation

From the controller (VMware example):

    & 'F:\VMware\VMware Workstation\vmrun.exe' -T ws reset "<path>.vmx" hard

Watch on the target console or a second SSH session after boot:

    ssh kbl@kbl-target.local 'cat /var/lib/kylinbootlab/observe/current.jsonl'
    ssh kbl@kbl-target.local 'cat /var/lib/kylinbootlab/observe/done'
    ssh kbl@kbl-target.local 'cat /proc/sys/kernel/random/boot_id'

Expect: `observer_started` → `greeter_started` → `unit_active` ×3 →
`greeter_ready` → `login_injected` → `session_opened` → probe events →
`usable`; the done marker equals the current boot_id; the greeter visibly
logged in by itself (no autologin configured — check
`/etc/lightdm/lightdm.conf` has no `autologin-user`).

## 4. Pattern and process-list refinement (expected on first deploy)

All matchers are config, not code — tune without recompiling:

1. Greeter signals: `ssh kbl@kbl-target.local \
   'journalctl -b 0 --no-pager | grep -inE "lightdm|greeter" | head -40'`.
   If `greeter_ready` fires too early (first greeter log line vs UI painted),
   set `greeter_ready_pattern` in `/etc/kylinbootlab/observe.toml` to a
   later, paint-time message fragment.
2. Desktop process group (needs one real login):
   `ssh kbl@kbl-target.local 'ps -e -o comm= | grep -i ukui | sort -u'`,
   then set `desktop_processes` in observe.toml (sudo).
3. The session probe cannot read root-0600 observe.toml and runs with
   built-in defaults (empty process list). To feed it the refined list:
   `sudo chgrp kbl /etc/kylinbootlab/observe.toml` and
   `sudo chmod 0640 /etc/kylinbootlab/observe.toml`.
   Trade-off: the kbl group can then read the kbl password — acceptable on
   a dedicated lab target (it is kbl's own password); document if not.
4. Sentinel: keep `mate-terminal` unless missing; any AT-SPI-visible app
   with a fast first window works.

## 5. Collect and report

    uv run kbl collect --target kbl@kbl-target.local
    uv run kbl report <run-id>

`derived/metrics.json` gains a `readiness` block; `reports/baseline.html`
shows the "User-perceived readiness" timeline. Runs without the observer
show `status: absent` — never an error.

## 6. Calibration (spec §7)

    uv run kbl calibrate --target kbl@<ip> --backend vix \
        --vmx-path "<path>.vmx" --per-group 10

Runs calib-bare (marker removed) then calib-benchmark (marker present),
10 warm-reset boots each, prints medians + deltas, writes
`var/calibration-report.json`, exits 1 unless BOTH `os_total_ns` and
`graphical_target_from_t0_ns` median deltas are < 1%.

Notes:
- Calibration boots are guest resets, not snapshot restores — a restore
  would revert the enabled marker (see `calibrate.py` docstring). Journald
  growth over 20 boots affects both groups equally; medians absorb it.
- Diagnostic group (manual, recorded only, never gated; results are for
  Phase 4 analysis only). Unlike `kbl calibrate`, a raw `kbl experiment
  run` powers off and restores the `baseline` snapshot before EVERY boot,
  so a live edit of observe.toml would be silently reverted on the first
  restore — the mode edit must be baked into the snapshot first:
  1. At the VM console (or SSH while the guest is up):
     `sudo sed -i 's/^mode = "benchmark"/mode = "diagnostic"/' /etc/kylinbootlab/observe.toml`
  2. Re-create the baseline snapshot AFTER the edit, so every restore
     boots in diagnostic mode:
     `vmrun -T ws stop "<path>.vmx" soft`, then
     `vmrun -T ws deleteSnapshot "<path>.vmx" baseline`, then
     `vmrun -T ws snapshot "<path>.vmx" baseline`.
  3. Queue and run with a dedicated queue file (NEVER the default
     `var/experiments.jsonl`) and an explicit VMX path (the vix backend
     raises without one):
     `uv run kbl experiment queue --profile calib-diagnostic --count 10 --queue-file var/diagnostic.jsonl`, then
     `uv run kbl experiment run --target kbl@<ip> --backend vix --vmx-path "<path>.vmx" --queue-file var/diagnostic.jsonl`.
  4. Revert: sed the mode back to `"benchmark"`, then repeat step 2 so
     the baseline snapshot is benchmark-mode again.
  Diagnostic runs are labeled `mode=diagnostic` in their event stream and
  excluded from formal statistics.

## 7. Wrong-password drill (error-path acceptance)

    sudo sed -i 's/^password = .*/password = "wrongpw1"/' /etc/kylinbootlab/observe.toml
    # reboot, then:
    ssh kbl@kbl-target.local 'tail -3 /var/lib/kylinbootlab/observe/current.jsonl'

Expect an `error` event ("no session within 30s of injection"), a done
marker (bundle still collectable), NO second injection attempt, and no
account lockout (`sudo pam_tally2 --user kbl` or `faillock --user kbl`).
Restore the real password afterwards and verify one clean run.

## 8. Troubleshooting

| Symptom | Likely cause | Fix |
|---|---|---|
| No `current.jsonl` after boot | marker absent or unit disabled | `touch .../observe/enabled`; `systemctl status kbl-observe` |
| `error: uinput self-check failed` | not running as root / no uinput | unit must be the installed one; `ls -l /dev/uinput` |
| `observer_timeout` at 90 s, greeter events present | injection gate blocked: check which of units/greeter_ready/uinput is missing in the stream | tune `greeter_ready_pattern`; `systemctl is-active dbus NetworkManager lightdm` |
| `session_opened` never appears, password correct | greeter focus/keymap | verify manually typing works at greeter; keep password [a-z0-9] |
| Probe events missing, `observer_timeout` after 120 s | usable-probe not started | autostart entry in `~kbl/.config/autostart/`; check `~/.xsession-errors` |
| `atspi_unavailable` in details | AT-SPI bus not up | acceptable degraded mode; check `busctl --user` inside the session |
| Stale `done` ignored by controller | boot_id mismatch (by design) | none — that is the staleness protection working |

## 9. Acceptance checklist (Phase 3 exit)

- [ ] Full chain on real openKylin: cold boot → auto login → all four
      T-points present and monotonically increasing.
- [ ] `kbl report` renders the readiness timeline; absent-observer run
      degrades to `status: absent`.
- [ ] `kbl calibrate` 10+10 completes; benchmark < 1% on both medians.
- [ ] Wrong-password drill: graceful `error` + timeout, no lockout, no
      re-injection.
- [ ] Refinements recorded in observe.toml and committed to the runbook.
```

- [ ] **Step 6: Commit**

```bash
git add scripts/target/kbl-observe.service scripts/target/kbl-usable-probe.desktop scripts/target/install_observer.sh docs/runbooks/observability-readiness.md
git commit -m "feat: add observer install assets and runbook"
```

---

### Task 13: Quality Gates + Real-VM Acceptance

No new code — verification only. Steps 3+ require the openKylin VM and mirror runbook sections 3-7.

- [ ] **Step 1: Full quality gates (controller)**

Run:
```powershell
uv run python scripts/export_schema.py --check
uv run ruff check .
uv run mypy src tests
uv run pytest -q --ignore=tests/test_rust_contract.py
uv run pytest -q tests/test_rust_contract.py
cargo fmt --all -- --check
cargo clippy --workspace --all-targets -- -D warnings
cargo clippy -p kbl-bootprobe --all-targets --target x86_64-unknown-linux-gnu -- -D warnings
cargo test --workspace
```
Expected: all exit 0. The schema check MUST pass untouched — `ProbeManifest` is frozen; readiness rides in as an optional artifact only.

- [ ] **Step 2: CLI surface check**

Run: `uv run kbl --help && uv run kbl calibrate --help`
Expected: `calibrate` listed with target/backend/per-group/report-out options; existing commands unchanged.

- [ ] **Step 3: Deploy to the VM and run one supervised observation**

Follow runbook sections 2-3: build on target, `sudo bash scripts/target/install_observer.sh target/release/kbl-bootprobe kbl <password>`, `vmrun ... reset ... hard`, then verify `current.jsonl` and the boot_id-stamped `done` marker.

Acceptance assertions on the event stream (run on the controller after `kbl collect`):

```powershell
$runId = (uv run kbl collect --target kbl@kbl-target.local).Trim()
uv run kbl report $runId
uv run python -c "import json,sys,pathlib; p=pathlib.Path('var/runs')/sys.argv[1]/'derived/metrics.json'; r=json.loads(p.read_text())['readiness']; assert r['status']=='complete', r; assert r['login_ready_ns'] < r['session_ns'] < r['usable_ns'], r; print('T-points monotonic:', r)" $runId
```
Expected: `status complete`, Tlogin-ready < Tsession < Tusable, HTML timeline populated.

- [ ] **Step 4: Wrong-password drill**

Runbook section 7. Expected: `error` event, done marker written, controller marks readiness `incomplete`, no lockout, password restored, one clean run afterwards.

- [ ] **Step 5: Calibration 10+10**

Run: `uv run kbl calibrate --target kbl@<ip> --backend vix --vmx-path "<path>.vmx" --per-group 10`
Expected: exit 0, `CALIBRATION PASS`, `var/calibration-report.json` with both deltas < 1%. Attach the report to the acceptance record.

Optional manual diagnostic group: runbook section 6. Acceptance note (spec §6 deviation): v1 diagnostic = interval-only; process-tree snapshots and per-event journal context land with Phase 4 prep (3B deep tracing) where their consumer lives — do not fail acceptance on their absence.

- [ ] **Step 6: Record expected refinements**

Acceptance is EXPECTED to produce three config refinements (not code changes) — record each in observe.toml and runbook section 4:
- `greeter_ready_pattern` tuned from the real journal (first greeter line vs paint-time line).
- `desktop_processes` filled from the live session (`ps -e -o comm=` after login; remember the 15-byte comm truncation).
- Sentinel verified (`command -v mate-terminal`) or replaced. Exact-name AT-SPI matching for the sentinel window (replacing the v1 child-count heuristic) goes to the Phase 4 backlog if the heuristic proves noisy.

- [ ] **Step 7: Verify exit criteria and close out**

Check every item in "Scope and Exit Criteria" at the top of this plan, plus runbook section 9. Then:

```powershell
git log --oneline -15
git status --short
```
Expected: one focused commit per task, clean tree, Phase 3 acceptance evidence (metrics.json excerpt + calibration-report.json) referenced in the runbook checklist.
