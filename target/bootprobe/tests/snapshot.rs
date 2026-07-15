use chrono::{TimeZone, Utc};
use kbl_bootprobe::model::HostInfo;
use kbl_bootprobe::snapshot::{CaptureSpec, SnapshotContext, capture_snapshot};
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
