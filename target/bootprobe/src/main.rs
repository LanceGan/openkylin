use anyhow::Result;
use clap::{Parser, Subcommand};
use kbl_bootprobe::model::contract_fixture;

#[derive(Debug, Parser)]
#[command(name = "kbl-bootprobe", version)]
struct Cli {
    #[command(subcommand)]
    command: Command,
}

#[derive(Debug, Subcommand)]
enum Command {
    ContractFixture,
}

fn main() -> Result<()> {
    let cli = Cli::parse();
    match cli.command {
        Command::ContractFixture => {
            println!("{}", serde_json::to_string_pretty(&contract_fixture())?);
        }
    }
    Ok(())
}
