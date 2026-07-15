from pathlib import Path
from typing import Annotated
from uuid import UUID

import typer

from kylinbootlab import __version__
from kylinbootlab.report import write_baseline_report
from kylinbootlab.store import RunStore

app = typer.Typer(no_args_is_help=True)
DataRoot = Annotated[Path, typer.Option(help="Immutable KylinBootLab run root")]


@app.command()
def version() -> None:
    """Print the KylinBootLab package version."""
    typer.echo(__version__)


@app.command()
def ingest(bundle: Path, data_root: DataRoot = Path("var/runs")) -> None:
    """Validate and import a target probe bundle."""
    run_path = RunStore(data_root).ingest(bundle)
    typer.echo(run_path.name)


@app.command()
def report(run_id: UUID, data_root: DataRoot = Path("var/runs")) -> None:
    """Generate deterministic baseline metrics and HTML."""
    paths = write_baseline_report(RunStore(data_root), run_id)
    typer.echo(paths.html)
