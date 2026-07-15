use std::path::PathBuf;

use anyhow::Result;
use clap::{Parser, Subcommand};
use kbl_bootprobe::model::contract_fixture;
use kbl_bootprobe::snapshot::{capture_snapshot, default_capture_specs, live_context};
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
    Snapshot {
        #[arg(long)]
        run_id: Uuid,
        #[arg(long)]
        output: PathBuf,
    },
}

fn main() -> Result<()> {
    let cli = Cli::parse();
    match cli.command {
        Command::ContractFixture => {
            println!("{}", serde_json::to_string_pretty(&contract_fixture())?);
        }
        Command::Snapshot { run_id, output } => {
            let manifest =
                capture_snapshot(&output, run_id, live_context()?, &default_capture_specs())?;
            println!("{}", manifest.run_id);
        }
    }
    Ok(())
}
