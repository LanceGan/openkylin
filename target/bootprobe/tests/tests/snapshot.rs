use chrono::{TimeZone, Utc};
use kbl_bootprobe::model::HostInfo;
use kbl_bootprobe::snapshot::{
    CaptureSpec, SnapshotContext, capture_snapshot, default_capture_specs,
};
use tempfile::tempdir;
use uuid::Uuid;

fn echo_spec(required: bool) -> CaptureSpec {
    #[cfg(target_os = "windows")]
    let command = vec!["cmd", "/C", "echo", "snapshot"];
    #[cfg(not(target_os = "windows"))]
    let command = vec!["sh", "-c", "printf snapshot"];

    CaptureSpec {
        name: "systemd-time",
        command: command.into_iter().map(str::to_owned).collect(),
        required,
    }
}

fn context() -> SnapshotContext {
    SnapshotContext {
        boot_id: Uuid::parse_str("22222222-2222-4222-8222-222222222222").unwrap(),
        captured_at_utc: Utc.with_ymd_and_hms(2026, 7, 15, 3, 0, 0).unwrap(),
        boottime_ns: 123_456_789,
        host: HostInfo {
            hostname: "kbl-target".to_owned(),
            kernel_release: "6.6.0-openkylin".to_owned(),
            os_id: "openkylin".to_owned(),
            os_version_id: "2.0".to_owned(),
            architecture: "x86_64".to_owned(),
        },
    }
}

#[test]
fn snapshot_writes_manifest_and_artifacts() {
    let root = tempdir().unwrap();
    let output = root.path().join("run");
    let run_id = Uuid::parse_str("11111111-1111-4111-8111-111111111111").unwrap();

    let manifest = capture_snapshot(&output, run_id, context(), &[echo_spec(true)]).unwrap();

    assert_eq!(manifest.run_id, run_id);
    assert_eq!(manifest.artifacts.len(), 1);
    assert!(output.join("probe-manifest.json").is_file());
    assert!(output.join("captures/systemd-time.json").is_file());
}

#[test]
fn snapshot_refuses_a_nonempty_output_directory() {
    let root = tempdir().unwrap();
    std::fs::write(root.path().join("existing"), "data").unwrap();

    let error =
        capture_snapshot(root.path(), Uuid::new_v4(), context(), &[echo_spec(true)]).unwrap_err();

    assert!(error.to_string().contains("not empty"));
}

#[test]
fn snapshot_fails_when_required_capture_has_nonzero_exit() {
    let root = tempdir().unwrap();
    let output = root.path().join("run");
    let run_id = Uuid::new_v4();

    #[cfg(target_os = "windows")]
    let spec = CaptureSpec {
        name: "failing-cmd",
        command: vec![
            "cmd".to_owned(),
            "/C".to_owned(),
            "exit".to_owned(),
            "1".to_owned(),
        ],
        required: true,
    };
    #[cfg(not(target_os = "windows"))]
    let spec = CaptureSpec {
        name: "failing-cmd",
        command: vec!["sh".to_owned(), "-c".to_owned(), "exit 1".to_owned()],
        required: true,
    };

    let error = capture_snapshot(&output, run_id, context(), &[spec]).unwrap_err();

    assert!(error.to_string().contains("required captures failed"));
    // Manifest should still be written for diagnostics
    assert!(output.join("probe-manifest.json").is_file());
}

#[test]
fn default_specs_include_optional_readiness_events() {
    let specs = default_capture_specs();
    let readiness = specs
        .iter()
        .find(|spec| spec.name == "readiness-events")
        .expect("readiness-events spec present");
    assert!(
        !readiness.required,
        "must stay optional for observer-less targets"
    );
    assert_eq!(
        readiness.command,
        vec![
            "cat".to_owned(),
            "/var/lib/kylinbootlab/observe/current.jsonl".to_owned(),
        ]
    );
}
