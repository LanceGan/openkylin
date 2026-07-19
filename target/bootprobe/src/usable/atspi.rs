//! AT-SPI desktop checks via `busctl` / `dbus-send` subprocesses.
//!
//! No native D-Bus dependency: the probe shells out and parses the textual
//! replies with the pure functions below (unit-tested cross-platform).
//! The probe runs inside the kbl session, so `DBUS_SESSION_BUS_ADDRESS`
//! and `XDG_RUNTIME_DIR` are inherited from the session environment.

/// Extract the a11y bus address from
/// `busctl --user --json=short call org.a11y.Bus /org/a11y/bus org.a11y.Bus GetAddress`.
/// Reply shape: `{"type":"s","data":["unix:path=/run/user/1000/at-spi/bus_0"]}`.
pub fn parse_bus_address(json_reply: &str) -> Option<String> {
    let value: serde_json::Value = serde_json::from_str(json_reply.trim()).ok()?;
    let address = value.get("data")?.get(0)?.as_str()?;
    address.starts_with("unix:").then(|| address.to_owned())
}

/// Extract the child count from a `dbus-send --print-reply` reply — the
/// last integer token, e.g. `   variant       int32 3`.
pub fn parse_child_count(reply: &str) -> Option<u32> {
    reply
        .split_whitespace()
        .rev()
        .find_map(|token| token.parse().ok())
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
    /// `ChildCount` is a property of `org.a11y.atspi.Accessible` (the
    /// interface has no `GetChildCount` method), hence `Properties.Get`.
    pub fn desktop_child_count(address: &str) -> Result<u32> {
        let address_arg = format!("--address={address}");
        let capture = run_command(
            "dbus-send",
            &[
                &address_arg,
                "--print-reply",
                "--dest=org.a11y.atspi.Registry",
                "/org/a11y/atspi/accessible/root",
                "org.freedesktop.DBus.Properties.Get",
                "string:org.a11y.atspi.Accessible",
                "string:ChildCount",
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
    fn parses_dbus_send_child_count_reply() {
        let reply = concat!(
            "method return time=1721288.123 sender=:1.5 -> destination=:1.42 ",
            "serial=42 reply_serial=2\n",
            "   variant       int32 3\n",
        );
        assert_eq!(parse_child_count(reply), Some(3));
    }

    #[test]
    fn child_count_of_zero_parses() {
        assert_eq!(parse_child_count("   variant       int32 0\n"), Some(0));
    }

    #[test]
    fn unparseable_reply_yields_none() {
        assert_eq!(parse_child_count("no numbers here"), None);
    }
}
