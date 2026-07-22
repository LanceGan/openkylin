//! Pure readiness state machine — every observation source feeds `Signal`s
//! in, `ReadinessEvent`s come out.  No I/O, no clocks: fully unit-testable.

use std::collections::BTreeSet;

use crate::events::{EventKind, EventSource, ReadinessEvent};
use crate::observe::config::ObserveConfig;
use crate::observe::journal::JournalLine;

/// Spec §8 timeouts, all on the CLOCK_BOOTTIME axis.
pub const GREETER_TIMEOUT_NS: u64 = 90_000_000_000;
pub const SESSION_TIMEOUT_NS: u64 = 30_000_000_000;
pub const USABLE_TIMEOUT_NS: u64 = 300_000_000_000;

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
