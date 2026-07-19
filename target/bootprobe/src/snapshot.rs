use std::fs;
use std::path::Path;

use anyhow::{Context, Result, bail};
use chrono::{DateTime, Utc};
use uuid::Uuid;

use crate::capture::{run_command, write_command_capture};
use crate::model::{HostInfo, ProbeManifest};
use crate::system::{boottime_ns, current_host_info, read_boot_id};

#[derive(Debug, Clone)]
pub struct CaptureSpec {
    pub name: &'static str,
    pub command: Vec<String>,
    pub required: bool,
}

#[derive(Debug, Clone)]
pub struct SnapshotContext {
    pub boot_id: Uuid,
    pub captured_at_utc: DateTime<Utc>,
    pub boottime_ns: u64,
    pub host: HostInfo,
}

pub fn default_capture_specs() -> Vec<CaptureSpec> {
    vec![
        CaptureSpec {
            name: "systemd-time",
            command: words(&["systemd-analyze", "--no-pager", "time"]),
            required: true,
        },
        CaptureSpec {
            name: "systemd-blame",
            command: words(&["systemd-analyze", "--no-pager", "blame"]),
            required: true,
        },
        CaptureSpec {
            name: "systemd-critical-chain",
            command: words(&["systemd-analyze", "--no-pager", "critical-chain"]),
            required: false,
        },
        CaptureSpec {
            name: "systemd-manager",
            command: words(&[
                "systemctl",
                "--no-pager",
                "show",
                "--property=KernelTimestampMonotonic",
                "--property=InitRDTimestampMonotonic",
                "--property=UserspaceTimestampMonotonic",
                "--property=FinishTimestampMonotonic",
            ]),
            required: false,
        },
        CaptureSpec {
            name: "journal-monotonic",
            command: words(&[
                "journalctl",
                "--boot=0",
                "--output=short-monotonic",
                "--no-pager",
            ]),
            required: false,
        },
        CaptureSpec {
            name: "readiness-events",
            command: words(&["cat", "/var/lib/kylinbootlab/observe/current.jsonl"]),
            required: false,
        },
    ]
}

fn words(values: &[&str]) -> Vec<String> {
    values.iter().map(|value| (*value).to_owned()).collect()
}

pub fn live_context() -> Result<SnapshotContext> {
    Ok(SnapshotContext {
        boot_id: read_boot_id(Path::new("/proc/sys/kernel/random/boot_id"))?,
        captured_at_utc: Utc::now(),
        boottime_ns: boottime_ns()?,
        host: current_host_info()?,
    })
}

pub fn capture_snapshot(
    output: &Path,
    run_id: Uuid,
    context: SnapshotContext,
    specs: &[CaptureSpec],
) -> Result<ProbeManifest> {
    if output.exists() && fs::read_dir(output)?.next().is_some() {
        bail!(
            "snapshot output directory is not empty: {}",
            output.display()
        );
    }
    fs::create_dir_all(output)?;

    let mut artifacts = Vec::with_capacity(specs.len());
    for spec in specs {
        let (program, args) = spec
            .command
            .split_first()
            .context("capture command must not be empty")?;
        let args: Vec<&str> = args.iter().map(String::as_str).collect();
        let capture = run_command(program, &args);
        artifacts.push(write_command_capture(
            output,
            spec.name,
            spec.required,
            &capture,
        )?);
    }

    let manifest = ProbeManifest {
        schema_version: 1,
        run_id,
        boot_id: context.boot_id,
        captured_at_utc: context.captured_at_utc,
        boottime_ns: context.boottime_ns,
        host: context.host,
        artifacts,
    };

    let manifest_path = output.join("probe-manifest.json");
    let mut encoded = serde_json::to_vec_pretty(&manifest)?;
    encoded.push(b'\n');
    fs::write(&manifest_path, encoded)
        .with_context(|| format!("failed to write {}", manifest_path.display()))?;

    let failed: Vec<&str> = manifest
        .artifacts
        .iter()
        .filter(|artifact| artifact.required && artifact.exit_code != 0)
        .map(|artifact| artifact.name.as_str())
        .collect();
    if !failed.is_empty() {
        bail!("required captures failed: {}", failed.join(", "));
    }

    Ok(manifest)
}
