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
    if greeter_ready is not None and set(active_units) >= _REQUIRED_UNITS:
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
