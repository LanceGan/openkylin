"""Phase 5 acceptance: bare-bones ABBA — no orchestrator, just power + collect."""
import json
import subprocess
import sys
import time
from pathlib import Path
from uuid import uuid4

sys.path.insert(0, "src")

from kylinbootlab.capture import load_command_capture
from kylinbootlab.optimization.executor import ProfileExecutor
from kylinbootlab.optimization.plan import build_mask_biometric, build_socket_nm_wait
from kylinbootlab.optimization.scheduler import ABBAScheduler, ProfileStateMachine
from kylinbootlab.optimization.validator import bootstrap_ci, compute_statistics, verdict
from kylinbootlab.remote import SubprocessRunner, collect_target_run
from kylinbootlab.store import RunStore
from kylinbootlab.systemd import parse_systemd_time

TARGET = "kbl@192.168.19.128"
PASSWORD = "12345678"
VMX = r"F:\VMware\Vitural machine\openkylin\openkylin.vmx"
VMRUN = r"F:\VMware\VMware Workstation\vmrun.exe"
STORE = RunStore(Path("var/runs"))
INCOMING = Path("var/incoming")


def power_on_wait():
    subprocess.run([VMRUN, "-T", "ws", "start", VMX, "nogui"], capture_output=True)
    for _ in range(30):
        r = subprocess.run(["ssh", "-o", "BatchMode=yes", "-o", "ConnectTimeout=5",
            TARGET, "true"], capture_output=True)
        if r.returncode == 0:
            return True
        time.sleep(5)
    return False


def power_off():
    subprocess.run([VMRUN, "-T", "ws", "stop", VMX, "hard"], capture_output=True)


def collect_boot_time(run_id):
    m = STORE.load_manifest(run_id)
    cap = load_command_capture(STORE.run_path(run_id), m, "systemd-time")
    metrics = parse_systemd_time(run_id, cap.stdout)
    return metrics.os_total_ns


def run_abba(plan_name, plan_func):
    print(f"\n{'='*60}\nABBA: {plan_name}")
    t0 = time.time()

    plan = plan_func()
    executor = ProfileExecutor(target=TARGET, password=PASSWORD)
    scheduler = ABBAScheduler(total_blocks=4, warmup_boots=2)
    sequence = scheduler.generate_sequence()
    state = ProfileStateMachine(initial="A")

    boot_times_a = []
    boot_times_b = []

    try:
        # Apply B profile first for warmup (it'll be rolled back for A boots)
        executor.apply_with_retry(plan)
        state.switch_to("B")

        for boot_idx, letter in enumerate(sequence):
            measured = boot_idx >= scheduler.warmup_boots
            mark = "[MEASURED]" if measured else "[WARMUP]"
            print(f"Boot {boot_idx}/{len(sequence)}: {letter} {mark}", flush=True)

            # Profile switch — always power OFF first so changes take
            # effect on the NEXT cold boot (no live systemd-modify race).
            if letter != state.current:
                power_off()
                time.sleep(3)
                if not power_on_wait():
                    raise RuntimeError("VM not reachable for profile switch")
                if letter == "A":
                    executor.rollback(plan)
                else:
                    executor.apply_with_retry(plan)
                state.switch_to(letter)

            # Cold boot: power off, then on, then collect
            power_off()
            time.sleep(3)
            if not power_on_wait():
                raise RuntimeError(f"VM not reachable for boot {boot_idx}")

            run_id = uuid4()
            try:
                collect_target_run(
                    target=TARGET, run_id=run_id, incoming_root=INCOMING,
                    store=STORE, runner=SubprocessRunner(),
                )
            except Exception as exc:
                print(f"  collect failed: {exc}", flush=True)
                power_off()
                continue

            if measured:
                bt = collect_boot_time(run_id)
                if bt:
                    if letter == "A": boot_times_a.append(bt)
                    else: boot_times_b.append(bt)
                    print(f"  time={bt/1e9:.3f}s", flush=True)

    finally:
        if not power_on_wait():
            power_on_wait()
        executor.rollback(plan)

    elapsed = time.time() - t0
    print(f"\nElapsed: {elapsed:.0f}s")
    print(f"A ({len(boot_times_a)}): {[round(t/1e9,3) for t in boot_times_a]}")
    print(f"B ({len(boot_times_b)}): {[round(t/1e9,3) for t in boot_times_b]}")

    paired = [b - a for a, b in zip(boot_times_a, boot_times_b)]
    stats = compute_statistics(boot_times_a, boot_times_b, paired)
    ci_l, ci_u = bootstrap_ci(paired)
    stats.ci_lower_95_ns, stats.ci_upper_95_ns = ci_l, ci_u

    # Functional check: SSH + NM after last boot
    power_on_wait()
    r = subprocess.run(["ssh", "-o", "BatchMode=yes", TARGET,
        "systemctl is-active NetworkManager dbus lightdm"], capture_output=True, text=True, timeout=10)
    functional_ok = all(s.strip() == "active" for s in r.stdout.strip().split("\n") if s.strip())

    v, gates = verdict(stats, functional_passed=functional_ok)

    result = {
        "plan_id": plan_name, "verdict": v, "elapsed_s": int(elapsed),
        "a_samples": [int(x) for x in boot_times_a],
        "b_samples": [int(x) for x in boot_times_b],
        "a_median_s": round(stats.a_median_ns/1e9, 3),
        "b_median_s": round(stats.b_median_ns/1e9, 3),
        "improvement_s": round(stats.median_improvement_ns/1e9, 3),
        "improvement_pct": round(stats.median_improvement_pct, 2),
        "ci_lower_s": round(ci_l/1e9, 3), "ci_upper_s": round(ci_u/1e9, 3),
        "functional_passed": functional_ok,
        "failed_gates": gates,
    }
    Path(f"var/acceptance-{plan_name}.json").write_text(json.dumps(result, indent=2), encoding="utf-8")
    print(json.dumps(result, indent=2))
    return result


c = sys.argv[1] if len(sys.argv) > 1 else "socket-nm-wait"
if c in ("mask-biometric", "both"):
    run_abba("mask-biometric", build_mask_biometric)
if c in ("socket-nm-wait", "both"):
    run_abba("socket-nm-wait", build_socket_nm_wait)
