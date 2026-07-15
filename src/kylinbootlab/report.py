import json
from dataclasses import dataclass
from importlib import resources
from pathlib import Path
from uuid import UUID

from jinja2 import Environment, StrictUndefined, select_autoescape

from kylinbootlab.capture import load_command_capture
from kylinbootlab.store import RunStore
from kylinbootlab.systemd import BootMetrics, UnitTiming, parse_systemd_blame, parse_systemd_time


@dataclass(frozen=True)
class ReportPaths:
    metrics_json: Path
    html: Path


def analyze_run(store: RunStore, run_id: UUID) -> tuple[BootMetrics, list[UnitTiming]]:
    run_path = store.run_path(run_id)
    manifest = store.load_manifest(run_id)
    timing = load_command_capture(run_path, manifest, "systemd-time")
    blame = load_command_capture(run_path, manifest, "systemd-blame")
    return (
        parse_systemd_time(run_id, timing.stdout),
        parse_systemd_blame(blame.stdout),
    )


def seconds(nanoseconds: int | None) -> str:
    if nanoseconds is None:
        return "not reported"
    return f"{nanoseconds / 1_000_000_000:.3f} s"


def write_baseline_report(store: RunStore, run_id: UUID) -> ReportPaths:
    run_path = store.run_path(run_id)
    manifest = store.load_manifest(run_id)
    boot, units = analyze_run(store, run_id)
    derived = run_path / "derived"
    reports = run_path / "reports"
    derived.mkdir(exist_ok=True)
    reports.mkdir(exist_ok=True)

    payload = {
        "schema_version": 1,
        "run_id": str(run_id),
        "boot_id": str(manifest.boot_id),
        "host": manifest.host.model_dump(mode="json"),
        "boot": boot.model_dump(mode="json"),
        "units": [unit.model_dump(mode="json") for unit in units],
    }
    metrics_path = derived / "metrics.json"
    metrics_path.write_text(
        json.dumps(payload, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
        newline="\n",
    )

    template_text = (
        resources.files("kylinbootlab")
        .joinpath("templates")
        .joinpath("baseline.html.j2")
        .read_text(encoding="utf-8")
    )
    environment = Environment(
        autoescape=select_autoescape(default=True),
        undefined=StrictUndefined,
    )
    template = environment.from_string(template_text)
    html_path = reports / "baseline.html"
    html_path.write_text(
        template.render(
            run_id=str(run_id),
            boot_id=str(manifest.boot_id),
            hostname=manifest.host.hostname,
            os_name=f"{manifest.host.os_id} {manifest.host.os_version_id}",
            kernel=manifest.host.kernel_release,
            kernel_time=seconds(boot.kernel_ns),
            initrd_time=seconds(boot.initrd_ns),
            userspace_time=seconds(boot.userspace_ns),
            total_time=seconds(boot.os_total_ns),
            graphical_time=seconds(boot.graphical_target_from_t0_ns),
            units=[
                {"rank": unit.rank, "name": unit.unit, "duration": seconds(unit.duration_ns)}
                for unit in units[:20]
            ],
        )
        + "\n",
        encoding="utf-8",
        newline="\n",
    )
    return ReportPaths(metrics_json=metrics_path, html=html_path)
