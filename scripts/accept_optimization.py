"""Phase 5 real-VM acceptance: run ABBA experiments for 2 candidates."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from kylinbootlab.experiments.power import VixPower
from kylinbootlab.optimization.plan import build_mask_biometric, build_socket_nm_wait
from kylinbootlab.optimization.runner import ABBARunner
from kylinbootlab.store import RunStore

TARGET = "kbl@192.168.19.128"
PASSWORD = "12345678"
VMX = r"F:\VMware\Vitural machine\openkylin\openkylin.vmx"
STORE_ROOT = Path("var/runs")
INCOMING = Path("var/incoming")


def run_candidate(plan, name):
    print(f"\n{'='*60}")
    print(f"ABBA EXPERIMENT: {name}")
    print(f"{'='*60}")
    power = VixPower(VMX)
    store = RunStore(STORE_ROOT)
    runner = ABBARunner()

    result = runner.run(plan=plan, target=TARGET, store=store,
                        power=power, incoming_root=INCOMING, password=PASSWORD)
    print(f"\nVERDICT: {result.verdict}")
    print(f"Failed gates: {result.failed_gates}")
    s = result.statistics
    print(f"A median: {s.a_median_ns/1e9:.3f}s  B median: {s.b_median_ns/1e9:.3f}s")
    print(f"Improvement: {s.median_improvement_ns/1e9:.3f}s ({s.median_improvement_pct:+.2f}%)")
    print(f"CI: [{s.ci_lower_95_ns/1e9:.3f}s, {s.ci_upper_95_ns/1e9:.3f}s]")
    print(f"P95 A: {s.p95_a_ns/1e9:.3f}s  P95 B: {s.p95_b_ns/1e9:.3f}s")
    print(f"Functional: {result.functional_passed}")
    print(f"Recommendation: {result.recommendation}")
    return result

if __name__ == "__main__":
    candidate = sys.argv[1] if len(sys.argv) > 1 else "mask-biometric"
    if candidate in ("mask-biometric", "both"):
        run_candidate(build_mask_biometric(), "mask-biometric")
    if candidate in ("socket-nm-wait", "both"):
        run_candidate(build_socket_nm_wait(), "socket-nm-wait")
