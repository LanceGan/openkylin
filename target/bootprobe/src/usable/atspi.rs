//! AT-SPI desktop checks via `busctl` subprocess.
//!
//! No native D-Bus dependency: the probe shells out to `busctl` and parses
//! its textual output with the pure functions below (unit-tested cross-platform).
//! The probe runs inside the kbl session, so `DBUS_SESSION_BUS_ADDRESS`
//! and `XDG_RUNTIME_DIR` are inherited from the session environment.
//!
//! v1 limitation: sentinel detection uses a child-count increase heuristic
//! rather than per-child name matching.  The acceptance refinement (Task 13
//! runbook) documents when and how to replace it with `busctl get-property`
//! per-child `Name` enumeration.

/// Extract the a11y bus address from
/// `busctl --user --json=short call org.a11y.Bus /org/a11y/bus org.a11y.Bus GetAddress`.
/// Reply shape: `{"type":"s","data":["unix:path=/run/user/1000/at-spi/bus_0"]}`.
pub fn parse_bus_address(json_reply: &str) -> Option<String> {
    let value: serde_json::Value = serde_json::from_str(json_reply.trim()).ok()?;
    let address = value.get("data")?.get(0)?.as_str()?;
    address.starts_with("unix:").then(|| address.to_owned())
}

/// Extract the child count from a `busctl get-property` reply — the
/// integer after the D-Bus type prefix, e.g. `"i 11"` or `"i 3"`.
pub fn parse_child_count(reply: &str) -> Option<u32> {
    reply
        .trim()
        .strip_prefix("i ")
        .or_else(|| {
            reply
                .split_whitespace()
                .last()
                .and_then(|s| if s == "i" { Some("") } else { None })
        })
        .and_then(|digits| digits.trim().parse().ok())
}

#[cfg(target_os = "linux")]
mod calls {
    use anyhow::{Context, Result, bail};

    use super::{parse_bus_address, parse_child_count};
    use crate::capture::run_command;

    /// Ask the session bus where the accessibility bus lives.
    pub fn a11y_bus_address() -> Result<String> {
        let capture = run_command(
            "busctl",
            &[
                "--user",
                "--json=short",
                "call",
                "org.a11y.Bus",
                "/org/a11y/bus",
                "org.a11y.Bus",
                "GetAddress",
            ],
        );
        if capture.exit_code != 0 {
            bail!("org.a11y.Bus GetAddress failed: {}", capture.stderr.trim());
        }
        parse_bus_address(&capture.stdout).context("unparseable GetAddress reply")
    }

    /// Number of applications registered on the AT-SPI registry root.
    ///
    /// Uses `busctl get-property` (not `dbus-send`): on openKylin SP2 the
    /// latter cannot reach the AT-SPI bus while `busctl --address=` works
    /// reliably from within the session environment.
    pub fn desktop_child_count(address: &str) -> Result<u32> {
        let capture = run_command(
            "busctl",
            &[
                "--address",
                address,
                "get-property",
                "org.a11y.atspi.Registry",
                "/org/a11y/atspi/accessible/root",
                "org.a11y.atspi.Accessible",
                "ChildCount",
            ],
        );
        if capture.exit_code != 0 {
            bail!("ChildCount query failed: {}", capture.stderr.trim());
        }
        parse_child_count(&capture.stdout).context("unparseable ChildCount reply")
    }
}

#[cfg(target_os = "linux")]
pub use calls::{a11y_bus_address, desktop_child_count};

#[cfg(test)]
mod tests {
    use super::{parse_bus_address, parse_child_count};

    #[test]
    fn parses_busctl_json_address() {
        let reply = r#"{"type":"s","data":["unix:path=/run/user/1000/at-spi/bus_0"]}"#;
        assert_eq!(
            parse_bus_address(reply).as_deref(),
            Some("unix:path=/run/user/1000/at-spi/bus_0")
        );
    }

    #[test]
    fn rejects_non_unix_address_and_garbage() {
        assert!(parse_bus_address(r#"{"type":"s","data":["tcp:host=evil"]}"#).is_none());
        assert!(parse_bus_address("not json").is_none());
        assert!(parse_bus_address(r#"{"data":[]}"#).is_none());
    }

    #[test]
    fn parses_busctl_get_property_child_count() {
        // Real output from VM acceptance: `busctl get-property ... ChildCount` → `i 11`
        assert_eq!(parse_child_count("i 11"), Some(11));
        assert_eq!(parse_child_count("i 3\n"), Some(3));
        assert_eq!(parse_child_count("i 0"), Some(0));
    }

    #[test]
    fn child_count_tolerates_whitespace() {
        assert_eq!(parse_child_count("  i 7  \n"), Some(7));
    }

    #[test]
    fn unparseable_reply_yields_none() {
        assert_eq!(parse_child_count("no numbers here"), None);
        assert_eq!(parse_child_count(""), None);
        assert_eq!(parse_child_count("Error: No reply"), None);
    }
}
