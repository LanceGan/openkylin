use std::fs;

use kbl_bootprobe::usable::procscan::{all_present, missing, scan_comms};
use tempfile::tempdir;

fn fake_proc(entries: &[(&str, Option<&str>)]) -> tempfile::TempDir {
    let root = tempdir().unwrap();
    for (pid, comm) in entries {
        let dir = root.path().join(pid);
        fs::create_dir(&dir).unwrap();
        if let Some(comm) = comm {
            fs::write(dir.join("comm"), format!("{comm}\n")).unwrap();
        }
    }
    root
}

#[test]
fn scan_reads_comm_of_numeric_pid_dirs_only() {
    let proc_root = fake_proc(&[
        ("1", Some("systemd")),
        ("4242", Some("ukui-panel")),
        ("self", Some("ignored")),
        ("acpi", Some("ignored")),
    ]);
    let mut comms = scan_comms(proc_root.path());
    comms.sort();
    assert_eq!(comms, vec!["systemd".to_owned(), "ukui-panel".to_owned()]);
}

#[test]
fn scan_skips_pid_dirs_without_comm() {
    let proc_root = fake_proc(&[("7", None), ("8", Some("bash"))]);
    assert_eq!(scan_comms(proc_root.path()), vec!["bash".to_owned()]);
}

#[test]
fn scan_of_missing_root_is_empty() {
    let root = tempdir().unwrap();
    assert!(scan_comms(&root.path().join("no-such-proc")).is_empty());
}

#[test]
fn all_present_matches_kernel_truncated_comm() {
    // The kernel truncates comm to 15 bytes: ukui-settings-daemon shows as
    // ukui-settings-d.  The required-list entry must still match.
    let needed = vec!["ukui-settings-daemon".to_owned(), "ukui-panel".to_owned()];
    let comms = vec!["ukui-settings-d".to_owned(), "ukui-panel".to_owned()];
    assert!(all_present(&needed, &comms));
}

#[test]
fn missing_lists_absent_processes_in_input_order() {
    let needed = vec!["ukui-panel".to_owned(), "peony".to_owned()];
    let comms = vec!["ukui-panel".to_owned()];
    assert_eq!(missing(&needed, &comms), vec!["peony".to_owned()]);
}

#[test]
fn empty_needed_is_trivially_present() {
    assert!(all_present(&[], &["anything".to_owned()]));
}
