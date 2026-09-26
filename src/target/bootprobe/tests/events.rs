use kbl_bootprobe::events::{EventKind, EventSource, ReadinessEvent, readiness_fixture};

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
        EventKind::Usable,
        EventSource::Probe,
        42_000_000_000,
        "all conditions met",
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

#[test]
fn readiness_fixture_is_monotonic_and_complete() {
    let fixture = readiness_fixture();
    assert_eq!(fixture.len(), 13);
    let mut previous = 0;
    for event in &fixture {
        assert!(event.monotonic_ns >= previous, "fixture must be time-ordered");
        previous = event.monotonic_ns;
    }
    assert_eq!(fixture[0].kind, EventKind::ObserverStarted);
    assert_eq!(fixture[12].kind, EventKind::Usable);
}
