use kbl_bootprobe::capture::{run_command, write_command_capture};
use kbl_bootprobe::system::parse_os_release;
use tempfile::tempdir;

#[test]
fn parses_required_os_release_fields() {
    let values = parse_os_release(
        r#"
NAME="openKylin"
ID=openkylin
VERSION_ID="2.0"
"#,
    );

    assert_eq!(values.get("ID").unwrap(), "openkylin");
    assert_eq!(values.get("VERSION_ID").unwrap(), "2.0");
}

#[test]
fn writes_a_hashed_command_capture() {
    #[cfg(target_os = "windows")]
    let (program, args) = ("cmd", vec!["/C", "echo", "captured"]);
    #[cfg(not(target_os = "windows"))]
    let (program, args) = ("sh", vec!["-c", "printf captured"]);

    let document = run_command(program, &args);
    let directory = tempdir().unwrap();
    let artifact = write_command_capture(directory.path(), "example", true, &document).unwrap();

    assert_eq!(document.exit_code, 0);
    assert!(document.stdout.contains("captured"));
    assert_eq!(artifact.name, "example");
    assert_eq!(artifact.sha256.len(), 64);
    assert!(directory.path().join(artifact.relative_path).is_file());
}
