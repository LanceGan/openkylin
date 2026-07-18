from pathlib import Path
from typing import Annotated
from uuid import UUID, uuid4

import typer

from kylinbootlab import __version__
from kylinbootlab.remote import SubprocessRunner, collect_target_run
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


@app.command()
def collect(
    target: Annotated[str, typer.Option(help="SSH destination")]
    = "kbl@kbl-target.local",
    data_root: DataRoot = Path("var/runs"),
    incoming_root: Annotated[Path, typer.Option(help="Untrusted incoming bundle root")]
    = Path("var/incoming"),
    probe_cmd: Annotated[
        str,
        typer.Option(help="Path to kbl-bootprobe on the target"),
    ] = "/usr/local/bin/kbl-bootprobe",
    remote_dir: Annotated[
        str,
        typer.Option(help="Scratch directory for snapshots on the target"),
    ] = "/var/lib/kylinbootlab/runs",
) -> None:
    """Capture, retrieve, validate, and import one target boot."""
    run_id = uuid4()
    run_path = collect_target_run(
        target=target,
        run_id=run_id,
        incoming_root=incoming_root,
        store=RunStore(data_root),
        runner=SubprocessRunner(),
        probe_cmd=probe_cmd,
        remote_dir=remote_dir,
    )
    typer.echo(run_path.name)
