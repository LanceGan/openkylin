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
    use std::sync::mpsc::{self, Receiver};
    use std::thread;
    use std::time::Duration;

    use anyhow::{Context, Result};

    use crate::capture::run_command;
    use crate::events::{EventKind, EventSource, ReadinessEvent};
    use crate::observe::config::{DONE_MARKER, EVENTS_FILE, ObserveConfig, USABLE_RESULT_FILE};
    use crate::observe::journal::{parse_journal_json, spawn_journal_follower};
    use crate::observe::state::{ReadinessState, Signal};
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
            let file =
                File::create(path).with_context(|| format!("cannot create {}", path.display()))?;
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
            format!("mode={} dm={}", config.mode.as_str(), config.display_manager_service),
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
        let dm = config.display_manager_service.as_str();
        let required: [&str; 3] = ["dbus.service", "NetworkManager.service", dm];
        let mut pending_units: BTreeSet<&str> = required.iter().copied().collect();

        while !machine.finished() {
            // 1. Drain replayed + live journal lines.
            while let Ok(line) = lines.try_recv() {
                if let Some(parsed) = parse_journal_json(&line) {
                    let events = machine.feed(Signal::Journal(parsed));
                    log.write_all(&events)?;
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
