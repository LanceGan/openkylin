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
        for character in ['A', 'Z', '!', ' ', '-', '_', '\u{e9}'] {
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

mod state_tests {
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
        assert_eq!(
            state.feed(unit_active("dbus.service", 7_000_000_000)).len(),
            1
        );
        assert!(
            state
                .feed(unit_active("dbus.service", 7_500_000_000))
                .is_empty()
        );
        assert!(
            state
                .feed(unit_active("cron.service", 7_600_000_000))
                .is_empty()
        );
    }

    #[test]
    fn greeter_timeout_fires_at_90s() {
        let mut state = ReadinessState::new(START_NS, &config());
        assert!(
            state
                .feed(Signal::Tick {
                    monotonic_ns: START_NS + GREETER_TIMEOUT_NS - 1,
                })
                .is_empty()
        );
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

    #[test]
    fn empty_journal_produces_no_events() {
        let mut state = ReadinessState::new(START_NS, &config());
        let emitted = state.feed(journal(
            5_000_000_000,
            Some("cron.service"),
            Some("cron"),
            "some unrelated message",
        ));
        assert!(emitted.is_empty());
        // GreeterStarted requires lightdm unit AND "start begin"
        let emitted2 = state.feed(journal(
            5_500_000_000,
            Some("lightdm.service"),
            Some("lightdm"),
            "some other lightdm message",
        ));
        assert!(
            emitted2.is_empty(),
            "no start begin means no greeter_started"
        );
    }
}
