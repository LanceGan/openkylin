from __future__ import annotations

from collections import Counter
from datetime import UTC, datetime
from pathlib import Path
from typing import TYPE_CHECKING, Annotated
from uuid import UUID, uuid4

import typer

from kylinbootlab import __version__
from kylinbootlab.calibrate import run_calibration
from kylinbootlab.experiments.contracts import ExperimentRecord
from kylinbootlab.experiments.orchestrator import ExperimentOrchestrator
from kylinbootlab.experiments.power import power_backend_factory
from kylinbootlab.experiments.queue import ExperimentQueue
from kylinbootlab.remote import SubprocessRunner, collect_target_run
from kylinbootlab.report import write_baseline_report
from kylinbootlab.store import RunStore

if TYPE_CHECKING:
    from kylinbootlab.analysis.graph import CausalGraph

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


@app.command()
def calibrate(
    target: Annotated[str, typer.Option(help="SSH destination")]
    = "kbl@192.168.19.128",
    data_root: DataRoot = Path("var/runs"),
    incoming_root: Annotated[Path, typer.Option(help="Incoming bundle root")]
    = Path("var/incoming"),
    queue_file: QueueFile = Path("var/calibration.jsonl"),
    per_group: Annotated[int, typer.Option(help="Cold boots per group")] = 10,
    backend: Annotated[str, typer.Option(help="Power backend: vix | wol")] = "vix",
    vmx_path: Annotated[str | None, typer.Option(help="VMX path for the vix backend")]
    = None,
    mac: Annotated[str | None, typer.Option(help="MAC address for the wol backend")]
    = None,
    report_out: Annotated[Path, typer.Option(help="Calibration verdict JSON path")]
    = Path("var/calibration-report.json"),
) -> None:
    """Run the bare/benchmark observer-overhead calibration (spec 7)."""
    kwargs: dict[str, str] = {"target": target}
    if vmx_path:
        kwargs["vmx_path"] = vmx_path
    if mac:
        kwargs["mac"] = mac
    power = power_backend_factory(backend, **kwargs)

    verdict = run_calibration(
        queue_file=queue_file,
        store=RunStore(data_root),
        power=power,
        target=target,
        incoming_root=incoming_root,
        per_group=per_group,
    )
    report_out.parent.mkdir(parents=True, exist_ok=True)
    report_out.write_text(
        verdict.model_dump_json(indent=2) + "\n", encoding="utf-8", newline="\n"
    )

    for group in (verdict.bare, verdict.benchmark):
        graphical = (
            f"{group.graphical_median_ns / 1e9:.3f}s"
            if group.graphical_median_ns is not None
            else "n/a"
        )
        typer.echo(
            f"{group.profile}: {group.runs} runs, "
            f"os_total median {group.os_total_median_ns / 1e9:.3f}s, "
            f"graphical median {graphical}"
        )
    graphical_delta = (
        f"{verdict.graphical_delta_percent:+.3f}%"
        if verdict.graphical_delta_percent is not None
        else "n/a"
    )
    typer.echo(
        f"os_total delta {verdict.os_total_delta_percent:+.3f}% / "
        f"graphical delta {graphical_delta}"
    )
    if not verdict.passed:
        typer.echo("CALIBRATION FAIL: benchmark overhead >= 1% (or graphical unmeasured)")
        raise typer.Exit(code=1)
    typer.echo("CALIBRATION PASS: benchmark overhead < 1%")


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


# -- Phase 4 analyze command --------------------------------------------------


def _resolve_analysis_sink(graph: CausalGraph) -> str | None:
    """Determine the sink node for critical path / bottleneck analysis.

    Prefers ``usable`` when the readiness layer is present, otherwise picks
    the first systemd-layer node with no outgoing edges.
    """
    if "usable" in graph.nodes:
        return "usable"
    sinks = [n for n in graph.nodes if not graph.successors(n)]
    if sinks:
        return sinks[0]
    return next(iter(graph.nodes), None)


@app.command("analyze")
def cmd_analyze(
    run_id: str = typer.Argument(..., help="Run UUID to analyze"),
    data_root: DataRoot = Path("var/runs"),  # noqa: B008
) -> None:
    """Build causal graph and bottleneck report from a captured boot run."""
    import json
    import logging
    from uuid import UUID

    from kylinbootlab.analysis.bottleneck import rank_bottlenecks
    from kylinbootlab.analysis.builder import CausalGraphBuilder
    from kylinbootlab.analysis.critical_path import critical_path
    from kylinbootlab.capture import load_command_capture
    from kylinbootlab.readiness import parse_events
    from kylinbootlab.store import RunStore
    from kylinbootlab.systemd import parse_systemd_blame

    logger = logging.getLogger(__name__)

    store = RunStore(data_root)
    rid = UUID(run_id)
    manifest = store.load_manifest(rid)

    # Load DOT from capture artifact
    dot_capture = load_command_capture(
        store.run_path(rid), manifest, "systemd-critical-chain"
    )
    dot_text = dot_capture.stdout

    # Load blame
    blame_capture = load_command_capture(
        store.run_path(rid), manifest, "systemd-blame"
    )
    blame_list = parse_systemd_blame(blame_capture.stdout)

    # Load readiness (optional — absent = empty list)
    readiness_events = []
    try:
        readiness_capture = load_command_capture(
            store.run_path(rid), manifest, "readiness-events"
        )
        readiness_events = parse_events(readiness_capture.stdout)
    except Exception:
        logger.info(
            "No readiness-events artifact found — readiness layer will be empty"
        )

    # Build graph
    builder = CausalGraphBuilder()
    graph = builder.build(dot_text, blame_list, readiness_events or None)

    # Determine sink for critical path / bottleneck analysis
    sink = _resolve_analysis_sink(graph)

    # Compute critical path
    cp: list[str] = []
    cp_length_ns = 0
    if sink is not None:
        try:
            cp = critical_path(graph, sink=sink)
            cp_length_ns = sum(graph.nodes[n].blame_ns for n in cp)
        except ValueError:
            logger.warning("Could not compute critical path to sink '%s'", sink)

    # Rank bottlenecks
    bottlenecks = rank_bottlenecks(graph, sink=sink, top_k=10) if sink else []

    # Write derived files
    derived_dir = store.derived_path(rid)
    derived_dir.mkdir(parents=True, exist_ok=True)

    cg_out = {
        "run_id": str(rid),
        "node_count": len(graph.nodes),
        "edge_count": len(graph.edges),
        "critical_path": cp,
        "critical_path_length_ns": cp_length_ns,
        "graph": graph.to_json_dict(),
    }
    (derived_dir / "causal-graph.json").write_text(
        json.dumps(cg_out, indent=2), encoding="utf-8"
    )

    br_out = [b.model_dump() for b in bottlenecks]
    (derived_dir / "bottleneck-report.json").write_text(
        json.dumps(br_out, indent=2), encoding="utf-8"
    )

    logger.info(
        "Analyzed run %s: %d nodes, %d edges, cp_length=%.3fs, top_bottleneck=%s",
        run_id,
        len(graph.nodes),
        len(graph.edges),
        cp_length_ns / 1e9,
        bottlenecks[0].node if bottlenecks else "none",
    )
    print(f"Critical path: {' -> '.join(cp)}")
    print(
        f"Critical path length: {cp_length_ns / 1e9:.3f}s"
    )
    print(
        f"Top bottleneck: {bottlenecks[0].node} (score={bottlenecks[0].score})"
        if bottlenecks
        else "No bottlenecks found"
    )
    print(f"Reports written to {derived_dir}")
