//! /proc scanning for the UKUI process-group readiness condition.
//! Parameterized by the proc root so tests use a temp directory.

use std::fs;
use std::path::Path;

/// Collect the `comm` of every process under *proc_root*.
///
/// Entries that vanish mid-scan (processes exiting) are skipped — a /proc
/// walk is inherently racy and must never fail the probe.  Returns an
/// empty list when the directory itself is unreadable.
pub fn scan_comms(proc_root: &Path) -> Vec<String> {
    let Ok(entries) = fs::read_dir(proc_root) else {
        return Vec::new();
    };
    let mut comms = Vec::new();
    for entry in entries.flatten() {
        let name = entry.file_name();
        let Some(name) = name.to_str() else { continue };
        if name.is_empty() || !name.bytes().all(|byte| byte.is_ascii_digit()) {
            continue;
        }
        if let Ok(comm) = fs::read_to_string(entry.path().join("comm")) {
            comms.push(comm.trim().to_owned());
        }
    }
    comms
}

/// Kernel `comm` values are truncated to 15 bytes (TASK_COMM_LEN - 1), so
/// "ukui-settings-daemon" shows up as "ukui-settings-d".  Compare with the
/// same truncation applied to the required name.
fn comm_matches(comms: &[String], required: &str) -> bool {
    let truncated: String = required.chars().take(15).collect();
    comms.iter().any(|comm| comm == required || *comm == truncated)
}

/// True when every required process currently runs (empty list: trivially true).
pub fn all_present(needed: &[String], comms: &[String]) -> bool {
    needed.iter().all(|process| comm_matches(comms, process))
}

/// The required processes not currently running, in input order.
pub fn missing(needed: &[String], comms: &[String]) -> Vec<String> {
    needed
        .iter()
        .filter(|process| !comm_matches(comms, process))
        .cloned()
        .collect()
}
