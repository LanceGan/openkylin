"""Phase 5 acceptance: simple ABBA without runner wrapper.

Runs 2 warmup + 16 measured boots (4 blocks of A-B-B-A) for one candidate,
using Phase 2 experiment queue directly.  Profile switching is done between
each experiment record by the controller (not the runner).
"""
import json
import subprocess
import sys
import time
from datetime import UTC, datetime
from pathlib import Path

sys.path.insert(0, "src")
from kylinbootlab.capture import load_command_capture
from kylinbootlab.experiments.contracts import ExperimentRecord
from kylinbootlab.experiments.orchestrator import ExperimentOrchestrator
from kylinbootlab.experiments.power import VixPower
from kylinbootlab.experiments.queue import ExperimentQueue
from kylinbootlab.optimization.executor import ProfileExecutor
from kylinbootlab.optimization.plan import build_mask_biometric, build_socket_nm_wait
from kylinbootlab.optimization.scheduler import ABBAScheduler, ProfileStateMachine
from kylinbootlab.optimization.validator import bootstrap_ci, compute_statistics, verdict
from kylinbootlab.store import RunStore

TARGET = "kbl@192.168.19.128"
PASSWORD = "12345678"
VMX = r"F:\VMware\Vitural machine\openkylin\openkylin.vmx"
STORE = RunStore(Path("var/runs"))
INCOMING = Path("var/incoming")

def collect_boot_time(store, run_id):
    """Extract os_total_ns from a stored run."""
    m = store.load_manifest(run_id)
    cap = load_command_capture(store.run_path(run_id), m, "systemd-time")
    # Parse from stdout
    for line in cap.stdout.splitlines():
        if "Startup finished in" in line:
            # Extract userspace time
            import re
            match = re.search(r"(\d+\.\d+)s \(userspace\)", line)
            if match:
                return int(float(match.group(1)) * 1e9)
    return None

def run_abba(plan_name, plan_func):
    print(f"\n{'='*60}")
    print(f"ABBA: {plan_name}")
    start_time = time.time()

    plan = plan_func()
    executor = ProfileExecutor(target=TARGET, password=PASSWORD)
    power = VixPower(VMX)
    scheduler = ABBAScheduler(total_blocks=4, warmup_boots=2)
    state = ProfileStateMachine(initial="A")
    sequence = scheduler.generate_sequence()

    boot_times_a = []
    boot_times_b = []

    # Ensure VM is up
    if not power.guest_alive():
        power.power_on()
        for _ in range(24):
            r = subprocess.run(["ssh", "-o", "BatchMode=yes", "-o", "ConnectTimeout=5",
                TARGET, "true"], capture_output=True)
            if r.returncode == 0:
                break
            time.sleep(5)

    # Apply optimized profile for warmup + all B boots
    executor.apply_with_retry(plan)
    state.switch_to("B")

    try:
        for boot_idx, profile_letter in enumerate(sequence):
            measured = boot_idx >= scheduler.warmup_boots
            status_mark = "  [MEASURED]" if measured else "  [WARMUP]"
            print(f"Boot {boot_idx}/{len(sequence)}: {profile_letter}{status_mark}", flush=True)

            # Switch profile if needed
            if profile_letter != state.current:
                # Always force power-on before SSH operations.
                # guest_alive() can be stale (VM powered but SSH not answering).
                power.power_on()
                for _ in range(30):
                    r = subprocess.run(["ssh", "-o", "BatchMode=yes", "-o", "ConnectTimeout=5",
                        TARGET, "true"], capture_output=True)
                    if r.returncode == 0:
                        break
                    time.sleep(5)
                if profile_letter == "A":
                    executor.rollback(plan)
                else:
                    executor.apply_with_retry(plan)
                state.switch_to(profile_letter)

            # Do one cold boot via orchestrator
            queue_file = Path(f"/tmp/kbl-abba-{plan_name}.jsonl")
            if queue_file.exists():
                queue_file.unlink()
            eq = ExperimentQueue(queue_file)
            eq.enqueue([ExperimentRecord(
                exp_id=f"{plan_name}-{boot_idx:03d}",
                profile=f"{plan_name}-{profile_letter}",
                status="pending",
                created_at=datetime.now(UTC),
            )])

            orch = ExperimentOrchestrator(
                queue=eq, store=STORE, power=power,
                target=TARGET, incoming_root=INCOMING,
            )
            orch.run_queue()

            if measured:
                # Orchestrator generates its own run_id — find it from the queue record
                records = eq.list()
                actual_run_id = None
                for r in records:
                    if r.exp_id == f"{plan_name}-{boot_idx:03d}" and r.run_id:
                        actual_run_id = r.run_id
                        break
                if actual_run_id is None:
                    print("  WARNING: no run_id in queue record", flush=True)
                    continue
                bt = collect_boot_time(STORE, actual_run_id)
                if bt:
                    if profile_letter == "A":
                        boot_times_a.append(bt)
                    else:
                        boot_times_b.append(bt)
                    print(f"  time={bt/1e9:.3f}s", flush=True)
                else:
                    print(f"  WARNING: no boot time for {run_id}", flush=True)
            else:
                # Make sure run exists
                pass

    finally:
        executor.rollback(plan)

    elapsed = time.time() - start_time
    print(f"\nElapsed: {elapsed:.0f}s", flush=True)
    print(f"A samples ({len(boot_times_a)}): {[f'{t/1e9:.3f}s' for t in boot_times_a]}", flush=True)
    print(f"B samples ({len(boot_times_b)}): {[f'{t/1e9:.3f}s' for t in boot_times_b]}", flush=True)

    # Compute statistics
    paired_diffs = [b - a for a, b in zip(boot_times_a, boot_times_b)]
    stats = compute_statistics(boot_times_a, boot_times_b, paired_diffs)
    ci_lower, ci_upper = bootstrap_ci(paired_diffs)
    stats.ci_lower_95_ns = ci_lower
    stats.ci_upper_95_ns = ci_upper
    v, gates = verdict(stats, functional_passed=True)

    result = {
        "plan_id": plan_name,
        "verdict": v,
        "elapsed_s": int(elapsed),
        "a_samples": [int(x) for x in boot_times_a],
        "b_samples": [int(x) for x in boot_times_b],
        "a_median_s": round(stats.a_median_ns / 1e9, 3),
        "b_median_s": round(stats.b_median_ns / 1e9, 3),
        "improvement_s": round(stats.median_improvement_ns / 1e9, 3),
        "improvement_pct": round(stats.median_improvement_pct, 2),
        "ci_lower_s": round(ci_lower / 1e9, 3),
        "ci_upper_s": round(ci_upper / 1e9, 3),
        "failed_gates": gates,
        "recommendation": f"{v} — {', '.join(gates) if gates else 'all gates passed'}",
    }
    Path(f"var/acceptance-{plan_name}.json").write_text(json.dumps(result, indent=2), encoding="utf-8")
    print(json.dumps(result, indent=2), flush=True)
    return result

candidate = sys.argv[1] if len(sys.argv) > 1 else "mask-biometric"
if candidate in ("mask-biometric", "both"):
    run_abba("mask-biometric", build_mask_biometric)
if candidate in ("socket-nm-wait", "both"):
    run_abba("socket-nm-wait", build_socket_nm_wait)
