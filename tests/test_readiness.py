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
