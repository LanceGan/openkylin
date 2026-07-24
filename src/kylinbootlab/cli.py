from __future__ import annotations

from collections import Counter
from collections.abc import Callable
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
    from kylinbootlab.experiments.power import TargetPower
    from kylinbootlab.optimization.plan import OptimizationPlan

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

    Prefers ``usable`` when the readiness layer is present, then
    ``graphical.target`` (the universal boot-complete milestone), then
    the first systemd-layer node with no outgoing edges.
    """
    if "usable" in graph.nodes:
        return "usable"
    # On targets without the observer, graphical.target is the best sink
    if "graphical.target" in graph.nodes:
        return "graphical.target"
    sinks = [n for n in graph.nodes if not graph.successors(n)]
    if sinks:
        return sinks[0]
    return next(iter(graph.nodes), None)


@app.command("analyze")
def cmd_analyze(
    run_id: str = typer.Argument(..., help="Run UUID to analyze"),
    data_root: DataRoot = Path("var/runs"),  # noqa: B008
    dot_target: Annotated[str | None, typer.Option(help="SSH target for on-demand DOT fetch")] = None,
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

    # Load DOT from capture artifact, or fetch on-demand from target
    dot_text = ""
    for artifact_name in ("systemd-dot", "systemd-critical-chain"):
        try:
            dot_capture = load_command_capture(
                store.run_path(rid), manifest, artifact_name
            )
            dot_text = dot_capture.stdout
            if "digraph" in dot_text:
                break
            dot_text = ""
        except Exception:
            continue
    if not dot_text or "digraph" not in dot_text:
        # Not captured at snapshot time — try SSH to fetch DOT from target
        target = dot_target
        if target is not None:
            logger.info("No DOT artifact in store; fetching via SSH from %s", target)
            try:
                import subprocess
                # Try the probe's own snapshot first (--snapshot-dot), then fall back to script
                for dot_cmd in (
                    "/usr/local/bin/kbl-dot-capture",
                    "/home/kbl/bin/kbl-dot-capture",
                ):
                    result = subprocess.run(
                        [
                            "ssh", "-o", "BatchMode=yes", "-o", "ConnectTimeout=15",
                            target, dot_cmd,
                        ],
                        capture_output=True, text=True, timeout=30, check=False,
                    )
                    if result.returncode == 0 and "digraph" in (result.stdout or ""):
                        dot_text = result.stdout
                        break
                else:
                    dot_text = ""
            except Exception:
                dot_text = ""

    if not dot_text.strip():
        raise typer.BadParameter(
            "No DOT data available — systemd-dot capture absent and SSH fetch failed"
        )

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


# -- Phase 5 optimize commands ------------------------------------------------

optimize_app = typer.Typer(no_args_is_help=True)
app.add_typer(optimize_app, name="optimize", help="Optimization planning and validation")


@optimize_app.command("plan")
def cmd_optimize_plan(
    run_id: str = typer.Argument(..., help="Run UUID with bottleneck-report.json"),
    data_root: DataRoot = Path("var/runs"),  # noqa: B008
) -> None:
    """Score and rank optimization candidates from a bottleneck report.

    Loads ``derived/bottleneck-report.json`` from the specified run, maps
    each Bottleneck to a known OptimizationPlan candidate, scores them,
    and prints a ranked table.
    """
    import json
    from uuid import UUID

    from kylinbootlab.analysis.graph import Bottleneck
    from kylinbootlab.optimization.plan import (
        build_exec_delay_lightdm,
        build_mask_biometric,
        build_mask_strongswan,
        build_parallelize_kylin,
        build_socket_nm_wait,
    )
    from kylinbootlab.optimization.planner import rank_candidates
    from kylinbootlab.store import RunStore

    store = RunStore(data_root)
    rid = UUID(run_id)
    derived = store.derived_path(rid)
    br_path = derived / "bottleneck-report.json"

    if not br_path.is_file():
        typer.echo(
            f"No bottleneck report found at {br_path}. "
            f"Run 'kbl analyze {run_id}' first.",
            err=True,
        )
        raise typer.Exit(code=1)

    raw = json.loads(br_path.read_text(encoding="utf-8"))
    bottlenecks = [Bottleneck.model_validate(b) for b in raw]

    # Map bottleneck nodes to known candidates
    known_candidates = {
        "biometric-authentication.service": build_mask_biometric,
        "strongswan.service": build_mask_strongswan,
        "NetworkManager-wait-online.service": build_socket_nm_wait,
        "kylin-display-manager.service": build_parallelize_kylin,
        "lightdm.service": build_exec_delay_lightdm,
    }

    candidates = []
    for b in bottlenecks:
        factory = known_candidates.get(b.node)
        if factory is not None:
            plan = factory()
            # Override evidence with actual Phase 4 data
            plan.evidence.blame_ns = b.blame_ns
            plan.evidence.slack_ns = b.slack_ns
            plan.evidence.on_critical_path = b.on_critical_path
            candidates.append(plan)

    if not candidates:
        typer.echo("No matching optimization candidates found for the top bottlenecks.")
        raise typer.Exit(code=0)

    ranked = rank_candidates(candidates)
    typer.echo(f"{'Rank':<5} {'Plan ID':<25} {'Score':<15} {'Predicted':<12} {'Category'}")
    typer.echo("-" * 80)
    for i, (plan, score) in enumerate(ranked, 1):
        gain_s = plan.expected_gain.predicted_ns / 1e9
        typer.echo(
            f"{i:<5} {plan.plan_id:<25} {score:<15.2f} {gain_s:<12.3f}s {plan.category}"
        )


@optimize_app.command("run")
def cmd_optimize_run(
    plan_id: str = typer.Argument(..., help="Candidate plan ID to validate"),
    target: Annotated[str, typer.Option(help="SSH destination")]
    = "kbl@192.168.19.128",
    password: Annotated[str | None, typer.Option(help="Target sudo password")] = None,
    data_root: DataRoot = Path("var/runs"),  # noqa: B008
    incoming_root: Annotated[Path, typer.Option(help="Incoming bundle root")]
    = Path("var/incoming"),  # noqa: B008
    backend: Annotated[str, typer.Option(help="Power backend: vix | wol")] = "vix",
    vmx_path: Annotated[str | None, typer.Option(help="VMX path for the vix backend")]
    = None,
    mac: Annotated[str | None, typer.Option(help="MAC address for the wol backend")]
    = None,
) -> None:
    """Run a single ABBA validation experiment for one optimization candidate."""
    known_plans = _load_known_plans()
    if plan_id not in known_plans:
        typer.echo(f"Unknown plan_id: {plan_id}", err=True)
        typer.echo(f"Available: {', '.join(sorted(known_plans))}", err=True)
        raise typer.Exit(code=1)

    from kylinbootlab.optimization.runner import ABBARunner

    plan = known_plans[plan_id]()
    runner = ABBARunner()
    result = runner.run(
        plan=plan,
        target=target,
        store=RunStore(data_root),
        power=_build_power(backend, target, vmx_path, mac),
        incoming_root=incoming_root,
        password=password,
    )

    typer.echo(f"\nVerdict: {result.verdict}")
    typer.echo(f"Median improvement: {result.statistics.median_improvement_ns / 1e6:.1f}ms "
               f"({result.statistics.median_improvement_pct:.2f}%)")
    typer.echo(f"95% CI: [{result.statistics.ci_lower_95_ns / 1e6:.1f}ms, "
               f"{result.statistics.ci_upper_95_ns / 1e6:.1f}ms]")
    if result.failed_gates:
        typer.echo("Failed gates:")
        for gate in result.failed_gates:
            typer.echo(f"  - {gate}")


@optimize_app.command("run-all")
def cmd_optimize_run_all(
    target: Annotated[str, typer.Option(help="SSH destination")]
    = "kbl@192.168.19.128",
    password: Annotated[str | None, typer.Option(help="Target sudo password")] = None,
    data_root: DataRoot = Path("var/runs"),  # noqa: B008
    incoming_root: Annotated[Path, typer.Option(help="Incoming bundle root")]
    = Path("var/incoming"),  # noqa: B008
    backend: Annotated[str, typer.Option(help="Power backend: vix | wol")] = "vix",
    vmx_path: Annotated[str | None, typer.Option(help="VMX path for the vix backend")]
    = None,
    mac: Annotated[str | None, typer.Option(help="MAC address for the wol backend")]
    = None,
) -> None:
    """Run all ranked optimization candidates sequentially on one target."""
    typer.echo(
        "kbl optimize run-all: not yet implemented.\n\n"
        "Currently each candidate must be run individually via:\n"
        "  kbl optimize run <plan_id> [OPTIONS]\n\n"
        "Batch scheduling is planned for Phase 10 (final validation)."
    )


@optimize_app.command("status")
def cmd_optimize_status(
    opt_run_id: str = typer.Argument(..., help="Optimization run ID"),
) -> None:
    """Show ABBA experiment progress for an optimization run.

    Placeholder stub. Will report boots completed, current block, profile state.
    """
    typer.echo(f"Status for optimization run {opt_run_id}: placeholder stub")


@optimize_app.command("report")
def cmd_optimize_report(
    opt_run_id: str = typer.Argument(..., help="Optimization run ID"),
) -> None:
    """Generate validation report for an optimization run.

    Placeholder stub. Will produce metrics JSON + verdict summary.
    """
    typer.echo(f"Report for optimization run {opt_run_id}: placeholder stub")


def _load_known_plans() -> dict[str, Callable[[], OptimizationPlan]]:
    """Return mapping of plan_id -> factory function for known candidates."""
    from kylinbootlab.optimization.plan import (
        build_exec_delay_lightdm,
        build_mask_biometric,
        build_mask_strongswan,
        build_parallelize_kylin,
        build_socket_nm_wait,
        fedora_initramfs_trim,
        fedora_mask_strongswan,
        phase6_initramfs_trim,
        phase6_kaiming_stagger,
        phase6_mask_strongswan,
        phase6_mitigations_off,
        phase6_parallel_kysdk,
    )
    return {
        # Phase 5 candidates
        "mask-biometric": build_mask_biometric,
        "mask-strongswan": build_mask_strongswan,
        "socket-nm-wait": build_socket_nm_wait,
        "parallelize-kylin": build_parallelize_kylin,
        "exec-delay-lightdm": build_exec_delay_lightdm,
        # Phase 6 candidates
        "phase6-mask-strongswan": phase6_mask_strongswan,
        "phase6-kaiming-stagger": phase6_kaiming_stagger,
        "phase6-parallel-kysdk": phase6_parallel_kysdk,
        "phase6-mitigations-off": phase6_mitigations_off,
        "phase6-initramfs-trim": phase6_initramfs_trim,
        # Cross-distro candidates
        "fedora-mask-strongswan": fedora_mask_strongswan,
        "fedora-initramfs-trim": fedora_initramfs_trim,
    }


def _build_power(
    backend: str,
    target: str,
    vmx_path: str | None,
    mac: str | None,
) -> TargetPower:
    """Build a TargetPower instance from CLI parameters."""
    from kylinbootlab.experiments.power import power_backend_factory

    kwargs: dict[str, str] = {"target": target}
    if vmx_path:
        kwargs["vmx_path"] = vmx_path
    if mac:
        kwargs["mac"] = mac
    return power_backend_factory(backend, **kwargs)


# -- Phase 8 BootAgent commands ------------------------------------------------

agent_app = typer.Typer(no_args_is_help=True)
app.add_typer(agent_app, name="agent", help="BootAgent diagnostic operations")


@agent_app.command()
def analyze(
    run_id: Annotated[str, typer.Argument(help="Run UUID to analyze")],
    data_root: DataRoot = Path("var/runs"),  # noqa: B008
    model: Annotated[str, typer.Option(help="Ollama model name")]
    = "qwen2.5-coder:7b-instruct-q4_k_m",
) -> None:
    """Run the BootAgent four-role pipeline on a stored run."""
    from uuid import UUID

    from kylinbootlab.agent.backend import OllamaBackend
    from kylinbootlab.agent.controller import BootAgent

    backend = OllamaBackend(model=model)
    agent = BootAgent(backend, RunStore(data_root))
    report = agent.analyze(UUID(run_id))
    typer.echo(report.model_dump_json(indent=2))


@agent_app.command()
def benchmark() -> None:
    """Describe the BootAgent benchmark (manual evaluation protocol).

    The BootAgent benchmark is a human-graded evaluation, not an automated
    pass/fail.  Each of the 5 cases requires manual review of agent output
    against ground-truth expectations.
    """
    cases = [
        ("B1", "dbus-exclusive-delay", "dbus.service: high blame on critical path"),
        ("B2", "bluetooth-large-slack", "ukui-bluetooth.service: high blame but large slack"),
        (
            "B3", "kaiming-stagger-positive",
            "org.kylin.kaiming.service: After=graphical.target causes delay",
        ),
        (
            "B4", "socket-nm-wait-regression",
            "NetworkManager-wait-online.service: functional regression from drop-in",
        ),
        (
            "B5", "dbus-lightdm-combined",
            "dbus.service and lightdm.service: two independent bottlenecks",
        ),
    ]
    typer.echo(f"BootAgent Benchmark — {len(cases)} cases\n")
    for cid, name, truth in cases:
        typer.echo(f"  {cid}: {name}")
        typer.echo(f"    Ground truth: {truth}")
        typer.echo()
    typer.echo(
        "Evaluation is manual: for each case, run 'kbl agent analyze <RUN_ID>',\n"
        "then compare the agent output to the ground truth above.\n"
        "Scoring rubric: 0-1 per case, pass >= 3.0/5.0."
    )


# -- Phase 9 evidence dashboard -----------------------------------------


@app.command()
def dashboard() -> None:
    """Open the Phase 1-9 evidence dashboard in the default browser."""
    import webbrowser
    from pathlib import Path

    dashboard_html = Path("dashboard/dist/index.html")
    if not dashboard_html.is_file():
        typer.echo(
            "Dashboard not built. Run: cd dashboard && npm install && npm run build"
        )
        raise typer.Exit(code=1)
    url = dashboard_html.resolve().as_uri()
    typer.echo(f"Opening {url}")
    webbrowser.open(url)
