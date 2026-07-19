use std::path::PathBuf;

use anyhow::Result;
use clap::{Parser, Subcommand};
use kbl_bootprobe::events::readiness_fixture;
use kbl_bootprobe::model::contract_fixture;
use kbl_bootprobe::observe::run_observe;
use kbl_bootprobe::snapshot::{capture_snapshot, default_capture_specs, live_context};
use kbl_bootprobe::usable::run_usable_probe;
use uuid::Uuid;

#[derive(Debug, Parser)]
#[command(name = "kbl-bootprobe", version)]
struct Cli {
    #[command(subcommand)]
    command: Command,
}

#[derive(Debug, Subcommand)]
enum Command {
    ContractFixture,
    /// Print the ReadinessEvent v1 cross-language fixture (JSONL).
    ReadinessFixture,
    Snapshot {
        #[arg(long)]
        run_id: Uuid,
        #[arg(long)]
        output: PathBuf,
    },
    /// Root-side readiness observer (systemd unit kbl-observe.service).
    Observe {
        #[arg(long, default_value = "/etc/kylinbootlab/observe.toml")]
        config: PathBuf,
        #[arg(long, default_value = "/var/lib/kylinbootlab/observe")]
        state_dir: PathBuf,
    },
    /// Session-side usable probe (XDG autostart in the kbl session).
    UsableProbe {
        #[arg(long, default_value = "/etc/kylinbootlab/observe.toml")]
        config: PathBuf,
        #[arg(long, default_value = "/var/lib/kylinbootlab/observe")]
        state_dir: PathBuf,
    },
}

fn main() -> Result<()> {
    let cli = Cli::parse();
    match cli.command {
        Command::ContractFixture => {
            println!("{}", serde_json::to_string_pretty(&contract_fixture())?);
        }
        Command::ReadinessFixture => {
            for event in readiness_fixture() {
                println!("{}", event.to_jsonl_line());
            }
        }
        Command::Snapshot { run_id, output } => {
            let manifest =
                capture_snapshot(&output, run_id, live_context()?, &default_capture_specs())?;
            println!("{}", manifest.run_id);
        }
        Command::Observe { config, state_dir } => {
            run_observe(&config, &state_dir)?;
        }
        Command::UsableProbe { config, state_dir } => {
            run_usable_probe(&config, &state_dir)?;
        }
    }
    Ok(())
}
