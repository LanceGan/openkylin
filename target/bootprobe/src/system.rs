use std::collections::BTreeMap;
use std::fs;
use std::path::Path;
#[cfg(target_os = "linux")]
use std::process::Command;

use anyhow::{Context, Result, anyhow};
use uuid::Uuid;

use crate::model::HostInfo;

pub fn parse_os_release(input: &str) -> BTreeMap<String, String> {
    input
        .lines()
        .filter_map(|line| {
            let line = line.trim();
            if line.is_empty() || line.starts_with('#') {
                return None;
            }
            let (key, raw_value) = line.split_once('=')?;
            let value = raw_value.trim();
            let unquoted = if value.len() >= 2
                && ((value.starts_with('"') && value.ends_with('"'))
                    || (value.starts_with('\'') && value.ends_with('\'')))
            {
                &value[1..value.len() - 1]
            } else {
                value
            };
            Some((key.to_owned(), unquoted.to_owned()))
        })
        .collect()
}

#[cfg(target_os = "linux")]
fn command_stdout(program: &str, args: &[&str]) -> Result<String> {
    let output = Command::new(program)
        .args(args)
        .env("LC_ALL", "C")
        .output()
        .with_context(|| format!("failed to execute {program}"))?;
    if !output.status.success() {
        anyhow::bail!(
            "{program} failed: {}",
            String::from_utf8_lossy(&output.stderr).trim()
        );
    }
    Ok(String::from_utf8(output.stdout)?.trim().to_owned())
}

pub fn read_boot_id(path: &Path) -> Result<Uuid> {
    let value =
        fs::read_to_string(path).with_context(|| format!("failed to read {}", path.display()))?;
    Uuid::parse_str(value.trim()).context("invalid Linux boot_id")
}

#[cfg(target_os = "linux")]
pub fn boottime_ns() -> Result<u64> {
    use nix::time::{ClockId, clock_gettime};

    let value = clock_gettime(ClockId::CLOCK_BOOTTIME)?;
    let seconds = u64::try_from(value.tv_sec()).context("negative CLOCK_BOOTTIME seconds")?;
    let nanoseconds = u64::try_from(value.tv_nsec()).context("negative nanoseconds")?;
    Ok(seconds * 1_000_000_000 + nanoseconds)
}

#[cfg(not(target_os = "linux"))]
pub fn boottime_ns() -> Result<u64> {
    Err(anyhow!("CLOCK_BOOTTIME capture is supported only on Linux"))
}

#[cfg(target_os = "linux")]
pub fn current_host_info() -> Result<HostInfo> {
    let os_release =
        fs::read_to_string("/etc/os-release").context("failed to read /etc/os-release")?;
    let values = parse_os_release(&os_release);
    let required = |key: &str| {
        values
            .get(key)
            .cloned()
            .ok_or_else(|| anyhow!("/etc/os-release is missing {key}"))
    };

    Ok(HostInfo {
        hostname: fs::read_to_string("/etc/hostname")
            .context("failed to read /etc/hostname")?
            .trim()
            .to_owned(),
        kernel_release: command_stdout("uname", &["-r"])?,
        os_id: required("ID")?,
        os_version_id: required("VERSION_ID")?,
        architecture: command_stdout("uname", &["-m"])?,
    })
}

#[cfg(not(target_os = "linux"))]
pub fn current_host_info() -> Result<HostInfo> {
    Err(anyhow!("live host discovery is supported only on Linux"))
}
