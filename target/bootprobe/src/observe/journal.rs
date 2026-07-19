//! journald JSON parsing (pure) and the boot-replay follower (linux).
//!
//! The follower runs `journalctl -b 0 -f -o json`: it REPLAYS every entry
//! since boot start before following live, so even if the observer unit
//! starts late no greeter/PAM signal is lost, and every entry keeps its
//! original `__MONOTONIC_TIMESTAMP`.  Only uinput injection is
//! live-timing-sensitive.

use serde_json::Value;

/// One journal entry reduced to the fields the state machine needs.
/// `monotonic_ns` is CLOCK_BOOTTIME nanoseconds (journald exports
/// microseconds; converted here — spec constraint ×1000).
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct JournalLine {
    pub monotonic_ns: u64,
    pub unit: Option<String>,
    pub comm: Option<String>,
    pub message: String,
}

/// Parse one `journalctl -o json` line.  Returns `None` for anything that
/// does not carry both a monotonic timestamp and a message — the follower
/// skips noise, it never aborts the observation.
pub fn parse_journal_json(line: &str) -> Option<JournalLine> {
    let value: Value = serde_json::from_str(line).ok()?;
    let object = value.as_object()?;

    let monotonic_us = match object.get("__MONOTONIC_TIMESTAMP")? {
        Value::String(text) => text.parse::<u64>().ok()?,
        Value::Number(number) => number.as_u64()?,
        _ => return None,
    };
    let message = match object.get("MESSAGE")? {
        Value::String(text) => text.clone(),
        // journald exports non-UTF-8 payloads as byte arrays.
        Value::Array(bytes) => {
            let raw: Vec<u8> = bytes
                .iter()
                .filter_map(|byte| byte.as_u64().and_then(|v| u8::try_from(v).ok()))
                .collect();
            String::from_utf8_lossy(&raw).into_owned()
        }
        _ => return None,
    };

    let field = |name: &str| object.get(name).and_then(Value::as_str).map(str::to_owned);
    Some(JournalLine {
        monotonic_ns: monotonic_us * 1000,
        unit: field("_SYSTEMD_UNIT"),
        comm: field("_COMM"),
        message,
    })
}

#[cfg(target_os = "linux")]
pub fn spawn_journal_follower() -> anyhow::Result<std::process::Child> {
    use std::process::{Command, Stdio};

    use anyhow::Context;

    use crate::capture::FIXED_PATH;

    Command::new("journalctl")
        .args(["-b", "0", "-f", "-o", "json", "--no-pager"])
        .env("PATH", FIXED_PATH)
        .env("LC_ALL", "C")
        .stdout(Stdio::piped())
        .stderr(Stdio::null())
        .spawn()
        .context("failed to spawn journalctl follower")
}
