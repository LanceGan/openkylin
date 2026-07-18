from collections import Counter
from datetime import UTC, datetime
from pathlib import Path
from typing import Annotated
from uuid import UUID, uuid4

import typer

from kylinbootlab import __version__
from kylinbootlab.experiments.contracts import ExperimentRecord
from kylinbootlab.experiments.orchestrator import ExperimentOrchestrator
from kylinbootlab.experiments.power import power_backend_factory
from kylinbootlab.experiments.queue import ExperimentQueue
from kylinbootlab.remote import SubprocessRunner, collect_target_run
from kylinbootlab.report import write_baseline_report
from kylinbootlab.store import RunStore

app = typer.Typer(no_args_is_help=True)
DataRoot = Annotated[Path, typer.Option(help="Immutable KylinBootLab run root")]
QueueFile = Annotated[Path, typer.Option(help="Experiment queue JSONL path")]


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


# -- Phase 2 experiment commands ---------------------------------------------

experiment_app = typer.Typer(no_args_is_help=True)
app.add_typer(experiment_app, name="experiment", help="Experiment queue operations")


@experiment_app.command()
def queue(
    profile: Annotated[str, typer.Option(help="Profile name")] = "baseline",
    count: Annotated[int, typer.Option(help="Number of experiments")] = 10,
    queue_file: QueueFile = Path("var/experiments.jsonl"),
) -> None:
    """Enqueue N experiments at the given profile."""
    records = [
        ExperimentRecord(
            exp_id=f"{profile}-{i:03d}",
            profile=profile,
            status="pending",
            created_at=datetime.now(UTC),
        )
        for i in range(count)
    ]
    ExperimentQueue(queue_file).enqueue(records)
    typer.echo(f"queued {count} experiments with profile '{profile}'")


@experiment_app.command("run")
def run_loop(
    target: Annotated[str, typer.Option(help="SSH destination")]
    = "kbl@192.168.19.128",
    data_root: DataRoot = Path("var/runs"),
    incoming_root: Annotated[Path, typer.Option(help="Incoming bundle root")]
    = Path("var/incoming"),
    queue_file: QueueFile = Path("var/experiments.jsonl"),
    backend: Annotated[str, typer.Option(help="Power backend: vix | wol")] = "vix",
    vmx_path: Annotated[str | None, typer.Option(help="VMX path for the vix backend")]
    = None,
    mac: Annotated[str | None, typer.Option(help="MAC address for the wol backend")]
    = None,
) -> None:
    """Run the experiment queue against a target."""
    kwargs: dict[str, str] = {"target": target}
    if vmx_path:
        kwargs["vmx_path"] = vmx_path
    if mac:
        kwargs["mac"] = mac
    power = power_backend_factory(backend, **kwargs)

    orchestrator = ExperimentOrchestrator(
        queue=ExperimentQueue(queue_file),
        store=RunStore(data_root),
        power=power,
        target=target,
        incoming_root=incoming_root,
    )
    orchestrator.run_queue()
    typer.echo("queue complete")


@experiment_app.command()
def status(queue_file: QueueFile = Path("var/experiments.jsonl")) -> None:
    """Show current experiment queue status."""
    records = ExperimentQueue(queue_file).list()
    counts: Counter[str] = Counter(record.status for record in records)

    typer.echo(f"{len(records)} experiments")
    for name in ("pending", "running", "done", "failed", "skipped"):
        if counts[name]:
            typer.echo(f"  {name}: {counts[name]}")


@experiment_app.command()
def retry(
    exp_id: Annotated[str, typer.Argument(help="Experiment ID to retry")],
    queue_file: QueueFile = Path("var/experiments.jsonl"),
) -> None:
    """Reset a single experiment back to pending for retry."""
    ExperimentQueue(queue_file).update(exp_id, status="pending", error=None, attempt=0)
    typer.echo(f"{exp_id} reset to pending")


@experiment_app.command()
def reset(
    status_filter: Annotated[str, typer.Option("--status", help="Status to reset")]
    = "failed",
    queue_file: QueueFile = Path("var/experiments.jsonl"),
) -> None:
    """Reset all experiments with a given status back to pending."""
    ExperimentQueue(queue_file).reset(status=status_filter, new_status="pending")
    typer.echo(f"reset all '{status_filter}' -> pending")
