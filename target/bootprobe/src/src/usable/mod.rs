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
                format!(
                    "usable deadline: processes still missing: {}",
                    pending.join(", ")
                ),
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
