//! observe.toml — deployment-time configuration for both observer components.
//!
//! The file lives at `/etc/kylinbootlab/observe.toml`, root-owned 0600 (it
//! contains the login password).  The session-side usable-probe reads the
//! same file when readable and silently falls back to `probe_defaults()`
//! otherwise; nothing except the password is security-sensitive.

use anyhow::{Context, Result, bail};
use serde::Deserialize;

/// File names inside the observer state directory
/// (`/var/lib/kylinbootlab/observe`).  Shared by both binary components and
/// the Python controller (`aliveness.py`, `calibrate.py` marker toggling).
pub const ENABLED_MARKER: &str = "enabled";
pub const EVENTS_FILE: &str = "current.jsonl";
pub const DONE_MARKER: &str = "done";
pub const USABLE_RESULT_FILE: &str = "usable-result.jsonl";

#[derive(Debug, Clone, Copy, PartialEq, Eq, Default, Deserialize)]
#[serde(rename_all = "snake_case")]
pub enum Mode {
    #[default]
    Benchmark,
    Diagnostic,
}

impl Mode {
    /// Benchmark keeps polling light (spec §6): 500 ms; diagnostic densifies to 50 ms.
    pub fn poll_interval_ms(self) -> u64 {
        match self {
            Mode::Benchmark => 500,
            Mode::Diagnostic => 50,
        }
    }

    pub fn as_str(self) -> &'static str {
        match self {
            Mode::Benchmark => "benchmark",
            Mode::Diagnostic => "diagnostic",
        }
    }
}

#[derive(Clone, PartialEq, Eq, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct ObserveConfig {
    pub password: String,
    #[serde(default)]
    pub mode: Mode,
    #[serde(default = "default_target_user")]
    pub target_user: String,
    #[serde(default = "default_sentinel_command")]
    pub sentinel_command: Vec<String>,
    #[serde(default)]
    pub desktop_processes: Vec<String>,
    #[serde(default = "default_greeter_ready_pattern")]
    pub greeter_ready_pattern: String,
    #[serde(default = "default_session_opened_pattern")]
    pub session_opened_pattern: String,
}

fn default_target_user() -> String {
    "kbl".to_owned()
}

fn default_sentinel_command() -> Vec<String> {
    vec!["mate-terminal".to_owned()]
}

fn default_greeter_ready_pattern() -> String {
    "ukui-greeter".to_owned()
}

fn default_session_opened_pattern() -> String {
    "session opened for user".to_owned()
}

impl ObserveConfig {
    pub fn from_toml_str(input: &str) -> Result<Self> {
        let config: Self = toml::from_str(input).context("invalid observe.toml")?;
        if config.password.is_empty() {
            bail!("observe.toml: password must not be empty");
        }
        if let Some(bad) = config
            .password
            .chars()
            .find(|c| !c.is_ascii_lowercase() && !c.is_ascii_digit())
        {
            bail!(
                "observe.toml: password contains unsupported character {bad:?} \
                 (lowercase letters and digits only — spec keyboard-layout constraint)"
            );
        }
        if config.sentinel_command.is_empty() {
            bail!("observe.toml: sentinel_command must not be empty");
        }
        Ok(config)
    }

    /// Built-in defaults for the session-side probe when observe.toml is
    /// unreadable (root 0600).  The placeholder password is never used by
    /// the usable-probe.
    pub fn probe_defaults() -> Self {
        Self {
            password: "unused0".to_owned(),
            mode: Mode::default(),
            target_user: default_target_user(),
            sentinel_command: default_sentinel_command(),
            desktop_processes: Vec::new(),
            greeter_ready_pattern: default_greeter_ready_pattern(),
            session_opened_pattern: default_session_opened_pattern(),
        }
    }
}

/// Redact the password anywhere Debug output could leak it (logs, panics).
impl std::fmt::Debug for ObserveConfig {
    fn fmt(&self, formatter: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        formatter
            .debug_struct("ObserveConfig")
            .field("password", &"<redacted>")
            .field("mode", &self.mode)
            .field("target_user", &self.target_user)
            .field("sentinel_command", &self.sentinel_command)
            .field("desktop_processes", &self.desktop_processes)
            .field("greeter_ready_pattern", &self.greeter_ready_pattern)
            .field("session_opened_pattern", &self.session_opened_pattern)
            .finish()
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    const FULL: &str = r#"
password = "kbl123"
mode = "diagnostic"
target_user = "kbl"
sentinel_command = ["mate-terminal", "--disable-factory"]
desktop_processes = ["ukui-panel", "ukui-settings-daemon"]
greeter_ready_pattern = "ukui-greeter"
session_opened_pattern = "session opened for user"
"#;

    #[test]
    fn full_config_parses() {
        let config = ObserveConfig::from_toml_str(FULL).unwrap();
        assert_eq!(config.mode, Mode::Diagnostic);
        assert_eq!(config.password, "kbl123");
        assert_eq!(config.sentinel_command[0], "mate-terminal");
        assert_eq!(config.desktop_processes.len(), 2);
    }

    #[test]
    fn minimal_config_applies_defaults() {
        let config = ObserveConfig::from_toml_str("password = \"secret9\"\n").unwrap();
        assert_eq!(config.mode, Mode::Benchmark);
        assert_eq!(config.target_user, "kbl");
        assert_eq!(config.sentinel_command, vec!["mate-terminal".to_owned()]);
        assert!(config.desktop_processes.is_empty());
        assert_eq!(config.greeter_ready_pattern, "ukui-greeter");
        assert_eq!(config.session_opened_pattern, "session opened for user");
    }

    #[test]
    fn poll_intervals_follow_mode() {
        assert_eq!(Mode::Benchmark.poll_interval_ms(), 500);
        assert_eq!(Mode::Diagnostic.poll_interval_ms(), 50);
        assert_eq!(Mode::Benchmark.as_str(), "benchmark");
        assert_eq!(Mode::Diagnostic.as_str(), "diagnostic");
    }

    #[test]
    fn empty_password_is_rejected() {
        let error = ObserveConfig::from_toml_str("password = \"\"\n").unwrap_err();
        assert!(error.to_string().contains("password"));
    }

    #[test]
    fn uppercase_password_is_rejected() {
        let error = ObserveConfig::from_toml_str("password = \"Secret1\"\n").unwrap_err();
        assert!(error.to_string().contains("unsupported character"));
    }

    #[test]
    fn symbol_password_is_rejected() {
        assert!(ObserveConfig::from_toml_str("password = \"abc!23\"\n").is_err());
    }

    #[test]
    fn unknown_keys_are_rejected() {
        let error =
            ObserveConfig::from_toml_str("password = \"abc123\"\nbogus = 1\n").unwrap_err();
        assert!(error.to_string().contains("invalid observe.toml"));
    }

    #[test]
    fn debug_output_redacts_password() {
        let config = ObserveConfig::from_toml_str("password = \"topsecret1\"\n").unwrap();
        let debug = format!("{config:?}");
        assert!(debug.contains("<redacted>"));
        assert!(!debug.contains("topsecret1"));
    }
}
