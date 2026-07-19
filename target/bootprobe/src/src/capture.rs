use std::fs;
use std::path::Path;
use std::process::Command;

use anyhow::{Context, Result, bail};
use serde::{Deserialize, Serialize};
use sha2::{Digest, Sha256};

use crate::model::ArtifactRecord;

/// Fixed `PATH` used by every subprocess the probe spawns.
///
/// This is the same path that the `kbl-capture-run` wrapper sets, providing
/// defense-in-depth in case the wrapper's environment is somehow bypassed.
pub const FIXED_PATH: &str = "/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin";

#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct CommandCapture {
    pub command: Vec<String>,
    pub exit_code: i32,
    pub stdout: String,
    pub stderr: String,
}

/// Execute a command with a fixed safe `PATH` and `LC_ALL=C`.
///
/// Returns a `CommandCapture` even when the command fails to start or exits
/// non-zero — the probe never panics on a misbehaving subprocess.  The SSH
/// transport layer in the controller enforces a 60 s deadline on the overall
/// session; per-command timeouts can be added in a future Rust toolchain
/// version via `Child::wait_timeout` or the `wait-timeout` crate.
pub fn run_command(program: &str, args: &[&str]) -> CommandCapture {
    let command: Vec<String> = std::iter::once(program.to_owned())
        .chain(args.iter().map(|value| (*value).to_owned()))
        .collect();

    match Command::new(program)
        .args(args)
        .env("PATH", FIXED_PATH)
        .env("LC_ALL", "C")
        .output()
    {
        Ok(output) => CommandCapture {
            command,
            exit_code: output.status.code().unwrap_or(-1),
            stdout: String::from_utf8_lossy(&output.stdout).into_owned(),
            stderr: String::from_utf8_lossy(&output.stderr).into_owned(),
        },
        Err(error) => CommandCapture {
            command,
            exit_code: 127,
            stdout: String::new(),
            stderr: error.to_string(),
        },
    }
}

pub fn write_command_capture(
    root: &Path,
    name: &str,
    required: bool,
    capture: &CommandCapture,
) -> Result<ArtifactRecord> {
    let mut characters = name.chars();
    let valid_start = characters
        .next()
        .is_some_and(|character| character.is_ascii_lowercase() || character.is_ascii_digit());
    let valid_rest = characters.all(|character| {
        character.is_ascii_lowercase() || character.is_ascii_digit() || character == '-'
    });
    if !valid_start || !valid_rest {
        bail!("invalid artifact name: {name}");
    }

    let relative_path = format!("captures/{name}.json");
    let output_path = root.join(&relative_path);
    let parent = output_path.parent().context("capture path has no parent")?;
    fs::create_dir_all(parent)?;

    let mut encoded = serde_json::to_vec_pretty(capture)?;
    encoded.push(b'\n');
    fs::write(&output_path, &encoded)
        .with_context(|| format!("failed to write {}", output_path.display()))?;

    Ok(ArtifactRecord {
        name: name.to_owned(),
        relative_path,
        sha256: hex::encode(Sha256::digest(&encoded)),
        size_bytes: u64::try_from(encoded.len())?,
        command: capture.command.clone(),
        exit_code: capture.exit_code,
        required,
    })
}
