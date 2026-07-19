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
    assert_eq!(
        parse_journal_json(raw).unwrap().monotonic_ns,
        6_613_388_000
    );
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
    assert!(
        parse_journal_json(r#"{"__MONOTONIC_TIMESTAMP":"x","MESSAGE":"bad"}"#).is_none()
    );
}
