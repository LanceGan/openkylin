"""Phase 5 acceptance: single-candidate ABBA experiment with file output."""
import json
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from kylinbootlab.experiments.power import VixPower
from kylinbootlab.optimization.plan import build_mask_biometric
from kylinbootlab.optimization.runner import ABBARunner
from kylinbootlab.store import RunStore

PLAN = build_mask_biometric()
POWER = VixPower(r"F:\VMware\Vitural machine\openkylin\openkylin.vmx")
STORE = RunStore(Path("var/runs"))
RUNNER = ABBARunner()

t0 = time.time()
print(f"Starting {PLAN.plan_id} ABBA experiment...", flush=True)
result = RUNNER.run(
    plan=PLAN, target="kbl@192.168.19.128", store=STORE,
    power=POWER, incoming_root=Path("var/incoming"), password="12345678"
)
elapsed = time.time() - t0

s = result.statistics
report = {
    "plan_id": result.plan_id,
    "verdict": result.verdict,
    "elapsed_s": int(elapsed),
    "a_median_s": round(s.a_median_ns / 1e9, 3),
    "b_median_s": round(s.b_median_ns / 1e9, 3),
    "improvement_s": round(s.median_improvement_ns / 1e9, 3),
    "improvement_pct": round(s.median_improvement_pct, 2),
    "ci_lower_s": round(s.ci_lower_95_ns / 1e9, 3),
    "ci_upper_s": round(s.ci_upper_95_ns / 1e9, 3),
    "p95_a_s": round(s.p95_a_ns / 1e9, 3),
    "p95_b_s": round(s.p95_b_ns / 1e9, 3),
    "functional_passed": result.functional_passed,
    "failed_gates": result.failed_gates,
    "recommendation": result.recommendation,
}
out = Path("var/acceptance-mask-biometric.json")
out.write_text(json.dumps(report, indent=2), encoding="utf-8")
print(json.dumps(report, indent=2), flush=True)
print(f"Saved to {out}", flush=True)
