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
