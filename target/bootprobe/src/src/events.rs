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

/// Cross-language fixture stream — byte-for-byte identical to
/// `tests/fixtures/readiness-events-v1.jsonl` on the Python side
/// (verified by `tests/test_rust_contract.py`).
pub fn readiness_fixture() -> Vec<ReadinessEvent> {
    use EventKind as K;
    use EventSource as S;
    vec![
        ReadinessEvent::new(
            K::ObserverStarted,
            S::Probe,
            3_000_000_000,
            "mode=benchmark",
        ),
        ReadinessEvent::new(
            K::GreeterStarted,
            S::Journald,
            6_613_388_000,
            "lightdm start begin",
        ),
        ReadinessEvent::new(K::UnitActive, S::Systemd, 7_000_000_000, "dbus.service"),
        ReadinessEvent::new(
            K::UnitActive,
            S::Systemd,
            7_100_000_000,
            "NetworkManager.service",
        ),
        ReadinessEvent::new(K::UnitActive, S::Systemd, 7_200_000_000, "lightdm.service"),
        ReadinessEvent::new(
            K::GreeterReady,
            S::Journald,
            8_500_000_000,
            "ukui-greeter first output",
        ),
        ReadinessEvent::new(
            K::LoginInjected,
            S::Probe,
            9_000_000_000,
            "password+enter via uinput",
        ),
        ReadinessEvent::new(
            K::SessionOpened,
            S::Journald,
            11_500_000_000,
            "session opened for user kbl",
        ),
        ReadinessEvent::new(K::DesktopProcessUp, S::Probe, 16_000_000_000, "ukui-panel"),
        ReadinessEvent::new(
            K::AtspiDesktopReady,
            S::Atspi,
            16_500_000_000,
            "3 desktop children",
        ),
        ReadinessEvent::new(
            K::SentinelLaunched,
            S::Probe,
            16_600_000_000,
            "mate-terminal",
        ),
        ReadinessEvent::new(
            K::SentinelWindowShown,
            S::Atspi,
            18_100_000_000,
            "mate-terminal window",
        ),
        ReadinessEvent::new(
            K::Usable,
            S::Probe,
            18_100_000_000,
            "all three conditions met",
        ),
    ]
}
