use chrono::{DateTime, Utc};
use serde::{Deserialize, Serialize};
use uuid::Uuid;

#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct HostInfo {
    pub hostname: String,
    pub kernel_release: String,
    pub os_id: String,
    pub os_version_id: String,
    pub architecture: String,
}

#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct ArtifactRecord {
    pub name: String,
    pub relative_path: String,
    pub sha256: String,
    pub size_bytes: u64,
    pub command: Vec<String>,
    pub exit_code: i32,
    pub required: bool,
}

#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct ProbeManifest {
    pub schema_version: u32,
    pub run_id: Uuid,
    pub boot_id: Uuid,
    pub captured_at_utc: DateTime<Utc>,
    pub boottime_ns: u64,
    pub host: HostInfo,
    pub artifacts: Vec<ArtifactRecord>,
}

pub fn contract_fixture() -> ProbeManifest {
    ProbeManifest {
        schema_version: 1,
        run_id: Uuid::parse_str("11111111-1111-4111-8111-111111111111").unwrap(),
        boot_id: Uuid::parse_str("22222222-2222-4222-8222-222222222222").unwrap(),
        captured_at_utc: DateTime::parse_from_rfc3339("2026-07-15T03:00:00Z")
            .unwrap()
            .with_timezone(&Utc),
        boottime_ns: 123_456_789,
        host: HostInfo {
            hostname: "kbl-target".to_owned(),
            kernel_release: "6.6.0-openkylin".to_owned(),
            os_id: "openkylin".to_owned(),
            os_version_id: "2.0".to_owned(),
            architecture: "x86_64".to_owned(),
        },
        artifacts: vec![ArtifactRecord {
            name: "systemd-time".to_owned(),
            relative_path: "captures/systemd-time.json".to_owned(),
            sha256: "0".repeat(64),
            size_bytes: 123,
            command: vec![
                "systemd-analyze".to_owned(),
                "--no-pager".to_owned(),
                "time".to_owned(),
            ],
            exit_code: 0,
            required: true,
        }],
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn fixture_round_trips_without_unknown_fields() {
        let fixture = contract_fixture();
        let encoded = serde_json::to_string(&fixture).unwrap();
        let decoded: ProbeManifest = serde_json::from_str(&encoded).unwrap();

        assert_eq!(decoded, fixture);
        assert_eq!(decoded.schema_version, 1);
    }
}
