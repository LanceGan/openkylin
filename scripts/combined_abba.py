"""Phase 10 combined optimization ABBA: kaiming-stagger + mask-strongswan + mask-biometric."""
import sys, json, time, subprocess
from pathlib import Path
from uuid import uuid4
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from kylinbootlab.optimization.executor import ProfileExecutor
from kylinbootlab.optimization.scheduler import ABBAScheduler, ProfileStateMachine
from kylinbootlab.optimization.validator import bootstrap_ci, compute_statistics, verdict
from kylinbootlab.remote import collect_target_run, SubprocessRunner
from kylinbootlab.store import RunStore
from kylinbootlab.systemd import parse_systemd_time
from kylinbootlab.capture import load_command_capture

TARGET = "kbl@192.168.19.128"
PASSWORD = "12345678"
VMX = r"F:\VMware\Vitural machine\openkylin\openkylin.vmx"
VMRUN = r"F:\VMware\VMware Workstation\vmrun.exe"
STORE = RunStore(Path("var/runs"))
INCOMING = Path("var/incoming")

# Hardcoded combined optimizations
KAIMING_DROPIN = "[Unit]\nAfter=\nAfter=multi-user.target\n"
KAIMING_PATH = "/etc/systemd/system/org.kylin.kaiming.service.d/kbl-phase10.conf"
STRONGSWAN = "strongswan-starter.service"
BIOMETRIC = "biometric-authentication.service"


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
    return parse_systemd_time(run_id, cap.stdout).os_total_ns


def wait_for_boot_finished():
    """Poll systemd-analyze time until startup is complete."""
    for _ in range(24):
        r = subprocess.run(["ssh", "-o", "BatchMode=yes", "-o", "ConnectTimeout=10",
            TARGET, "systemd-analyze", "time"], capture_output=True, text=True, timeout=15)
        if r.returncode == 0:
            return True
        time.sleep(5)
    return False


def apply_combo(ex):
    d = KAIMING_PATH.rsplit("/", 1)[0]
    ex._ssh(f"sudo mkdir -p {d} && echo '{KAIMING_DROPIN}' | sudo tee {KAIMING_PATH} > /dev/null && sudo systemctl daemon-reload")
    ex._ssh(f"sudo systemctl mask {STRONGSWAN}")
    ex._ssh(f"sudo systemctl mask {BIOMETRIC}")


def rollback_combo(ex):
    ex._ssh(f"sudo rm -f {KAIMING_PATH} && sudo systemctl daemon-reload")
    ex._ssh(f"sudo systemctl unmask {STRONGSWAN}")
    ex._ssh(f"sudo systemctl unmask {BIOMETRIC}")


print("=" * 60)
print("COMBINED OPTIMIZATION ABBA")
t0 = time.time()
e = ProfileExecutor(target=TARGET, password=PASSWORD)
scheduler = ABBAScheduler(total_blocks=4, warmup_boots=2)
sequence = scheduler.generate_sequence()
state = ProfileStateMachine(initial="A")
boot_times_a, boot_times_b = [], []

try:
    apply_combo(e)
    state.switch_to("B")

    for boot_idx, letter in enumerate(sequence):
        measured = boot_idx >= scheduler.warmup_boots
        print(f"Boot {boot_idx}/{len(sequence)}: {letter} {'M' if measured else 'W'}", flush=True)

        if letter != state.current:
            power_off()
            time.sleep(3)
            if not power_on_wait():
                raise RuntimeError("VM not reachable for profile switch")
            rollback_combo(e) if letter == "A" else apply_combo(e)
            state.switch_to(letter)

        power_off()
        time.sleep(3)
        if not power_on_wait():
            raise RuntimeError(f"VM not reachable for boot {boot_idx}")

        # Wait for systemd to finish booting before collecting
        wait_for_boot_finished()
        run_id = uuid4()
        try:
            collect_target_run(target=TARGET, run_id=run_id,
                               incoming_root=INCOMING, store=STORE,
                               runner=SubprocessRunner())
        except Exception as exc:
            print(f"  ERR: {exc}", flush=True)
            continue

        if measured:
            bt = collect_boot_time(run_id)
            if bt:
                if letter == "A": boot_times_a.append(bt)
                else: boot_times_b.append(bt)
                print(f"  {bt/1e9:.3f}s", flush=True)

finally:
    if not power_on_wait():
        power_on_wait()
    rollback_combo(e)

elapsed = time.time() - t0
print(f"\nElapsed: {elapsed:.0f}s  A={len(boot_times_a)} B={len(boot_times_b)}")

paired = [b - a for a, b in zip(boot_times_a, boot_times_b)]
stats = compute_statistics(boot_times_a, boot_times_b, paired)
ci_l, ci_u = bootstrap_ci(paired)
stats.ci_lower_95_ns, stats.ci_upper_95_ns = ci_l, ci_u

power_on_wait()
r = subprocess.run(["ssh", "-o", "BatchMode=yes", TARGET,
    "systemctl is-active NetworkManager dbus lightdm org.kylin.kaiming"],
    capture_output=True, text=True, timeout=10)
fn_ok = all(s.strip() == "active" for s in r.stdout.strip().split("\n") if s.strip())
v, gates = verdict(stats, functional_passed=fn_ok)

result = {
    "plan_id": "combo-kaiming-strongswan-biometric",
    "verdict": v, "elapsed_s": int(elapsed),
    "a_samples": [int(x) for x in boot_times_a],
    "b_samples": [int(x) for x in boot_times_b],
    "a_median_s": round(stats.a_median_ns/1e9, 3),
    "b_median_s": round(stats.b_median_ns/1e9, 3),
    "improvement_s": round(stats.median_improvement_ns/1e9, 3),
    "improvement_pct": round(stats.median_improvement_pct, 2),
    "ci_lower_s": round(ci_l/1e9, 3),
    "ci_upper_s": round(ci_u/1e9, 3),
    "functional_passed": fn_ok, "failed_gates": gates,
}
Path("var/acceptance-combo.json").write_text(json.dumps(result, indent=2), encoding="utf-8")
print(json.dumps(result, indent=2))
