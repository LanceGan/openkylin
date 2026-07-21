# KylinBootLab Phase 6: Systemd & Kernel Optimization Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Implement five system-level optimization candidates (systemd mask/stagger/parallelize + kernel mitigations + initramfs trim), validate each with an 18-boot ABBA experiment, and deliver at least one ACCEPTED verdict.

**Architecture:** Phase 5's OptimizationPlan + ABBA framework is reused verbatim. Phase 6 adds five new factory functions in `plan.py`, extends `executor.py` with `kernel_param` and `initramfs_trim` branches, and a parameterized acceptance script. Zero new ABBA or statistics code.

**Tech Stack:** Python 3.12, Pydantic 2, Typer, pytest. Phase 5 `ABBAScheduler`, `compute_statistics`, `verdict`, `abba_direct.py` reused unchanged.

---

## Global Constraints

- Python 3.12+, Pydantic 2 strict (`extra="forbid"`), mypy strict, ruff clean.
- Phase 1-5 modules consumed but NOT modified, EXCEPT: `plan.py` (5 new factories + `category` Literal extended), `executor.py` (3 new branches).
- grub changes: write to `/etc/default/grub.d/kbl-phase6.cfg` + `update-grub`. Rollback: `rm` + `update-grub`.
- initramfs changes: write to `/etc/initramfs-tools/conf.d/kbl-phase6` with `MODULES=dep`, then `update-initramfs -u -k all`. Backup initrd before modifying. Rollback: `rm` config + `update-initramfs -u -k all` (from backup if needed).
- All systemd changes through SSH sudo (Phase 5 executor pattern: `echo '<password>' | sudo -S` piped per `sudo` occurrence).
- Five candidates, each with independent 18-boot ABBA experiment (4 blocks × 4 boots + 2 warmup).
- Phase 2 baseline snapshot provides ultimate recovery for grub/initramfs failures.

---

## File Map

```text
src/kylinbootlab/optimization/plan.py       +5 factory functions (phase6_mask_strongswan, phase6_kaiming_stagger, phase6_parallel_kysdk, phase6_mitigations_off, phase6_initramfs_trim)
src/kylinbootlab/optimization/executor.py    +kernel_param branch (grub config) + initramfs_trim branch (mkinitramfs + backup)
tests/test_optimization_plan.py              + category validation + grub/initramfs cmd construction
scripts/abba_direct.py                       unchanged (parameterized candidate name)
profiles/phase6/                             +5 .toml profiles (future reference)
docs/evidence/phase6/                         ABBA experiment results
```

## Scope and Exit Criteria

Implements spec `docs/superpowers/specs/2026-07-20-kylinbootlab-systemd-kernel-optimization.md`. Phase 6 is complete when:

- Five `OptimizationPlan` factory functions added with correct `category` values including `kernel_param` and `initramfs_trim`.
- `ProfileExecutor.apply()` handles `kernel_param` (writes grub config + runs update-grub) and `initramfs_trim` (writes MODULES=dep config + backs up initrd + runs update-initramfs).
- `ProfileExecutor.rollback()` and `verify_applied()` correctly reverse/check both new categories.
- All new branches unit-tested (grub/initramfs command construction).
- At least 3 candidates complete full ABBA experiments; at least 1 reaches `ACCEPTED`.
- All Python gates pass: ruff, mypy strict, pytest (no regression).

---

### Task 1: Extend OptimizationPlan with Phase 6 Factory Functions

**Files:**
- Modify: `src/kylinbootlab/optimization/plan.py`
- Modify: `tests/test_optimization_plan.py`

**Interfaces:**
- Produces: `phase6_mask_strongswan() -> OptimizationPlan`, `phase6_kaiming_stagger() -> OptimizationPlan`, `phase6_parallel_kysdk() -> OptimizationPlan`, `phase6_mitigations_off() -> OptimizationPlan`, `phase6_initramfs_trim() -> OptimizationPlan`
- Category Literal extended with: `"kernel_param"`, `"initramfs_trim"`

- [ ] **Step 1: Write the failing test**

Append to `tests/test_optimization_plan.py`:

```python
from kylinbootlab.optimization.plan import (
    phase6_kaiming_stagger,
    phase6_mask_strongswan,
    phase6_mitigations_off,
    phase6_initramfs_trim,
    phase6_parallel_kysdk,
)


def test_phase6_mask_strongswan_uses_service_mask_category() -> None:
    p = phase6_mask_strongswan()
    assert p.category == "service_mask"
    assert p.mask_unit == "strongswan-starter.service"


def test_phase6_kaiming_stagger_has_after_multi_user() -> None:
    p = phase6_kaiming_stagger()
    assert p.category == "parallelize"
    assert p.drop_in_content is not None
    assert "After=multi-user.target" in p.drop_in_content
    assert "graphical.target" not in p.drop_in_content


def test_phase6_mitigations_off_uses_kernel_param_category() -> None:
    p = phase6_mitigations_off()
    assert p.category == "kernel_param"
    assert "mitigations=off" in (p.drop_in_content or "")


def test_phase6_initramfs_trim_has_modules_dep() -> None:
    p = phase6_initramfs_trim()
    assert p.category == "initramfs_trim"
    assert "MODULES=dep" in (p.drop_in_content or "")


def test_phase6_parallel_kysdk_targets_kysdk_units() -> None:
    p = phase6_parallel_kysdk()
    assert p.category == "parallelize"
    assert "dbus.service" in (p.drop_in_content or "")
```

- [ ] **Step 2: Run to verify failure**

Run: `uv run pytest tests/test_optimization_plan.py -v -k phase6`
Expected: FAIL — functions do not exist.

- [ ] **Step 3: Implement factory functions**

Add to `src/kylinbootlab/optimization/plan.py` — first extend the `category` Literal:

```python
# In OptimizationPlan class:
category: Literal[
    "service_mask", "socket_activation", "parallelize",
    "exec_delay", "kernel_param", "initramfs_trim",
]
```

Then add five factory functions (append below existing factories):

```python
def phase6_mask_strongswan() -> OptimizationPlan:
    return OptimizationPlan(
        plan_id="phase6-mask-strongswan",
        title="Mask strongswan-starter.service (IPSec, unused on VM)",
        category="service_mask",
        description="Disable IPSec daemon — unused on single-NIC desktop VM.",
        evidence=BottleneckEvidence(
            node="strongswan-starter.service",
            blame_ns=450_000_000, slack_ns=0,
            on_critical_path=True, action_kind="service_mask",
        ),
        expected_gain=GainEstimate(
            predicted_ns=450_000_000, upper_bound_ns=450_000_000, confidence=0.9,
        ),
        mask_unit="strongswan-starter.service",
        rollback=["sudo systemctl unmask strongswan-starter.service"],
        functional_regression=[
            "systemctl is-active NetworkManager dbus lightdm",
        ],
        portability=0.8, stability_risk=0.1, verification_cost=18,
        falsification="If strongswan-starter.service still shows in systemd-analyze blame, plan failed.",
    )


def phase6_kaiming_stagger() -> OptimizationPlan:
    return OptimizationPlan(
        plan_id="phase6-kaiming-stagger",
        title="Move kaiming from graphical.target → multi-user.target",
        category="parallelize",
        description=(
            "org.kylin.kaiming.service waits for graphical.target (1.4s blame) "
            "but is a dbus-activated daemon. Move to multi-user.target to run "
            "in parallel with NM/lightdm instead of blocking the graphical target."
        ),
        evidence=BottleneckEvidence(
            node="org.kylin.kaiming.service",
            blame_ns=1_420_000_000, slack_ns=0,
            on_critical_path=True, action_kind="parallelize",
        ),
        expected_gain=GainEstimate(
            predicted_ns=1_400_000_000, upper_bound_ns=1_420_000_000, confidence=0.9,
        ),
        drop_in_content=(
            "# KylinBootLab Phase 6 — run kaiming before graphical target\n"
            "[Unit]\n"
            "After=\n"
            "After=multi-user.target\n"
        ),
        drop_in_path="/etc/systemd/system/org.kylin.kaiming.service.d/kbl-phase6.conf",
        rollback=[
            "sudo rm -f /etc/systemd/system/org.kylin.kaiming.service.d/kbl-phase6.conf",
            "sudo systemctl daemon-reload",
        ],
        functional_regression=[
            "systemctl is-active org.kylin.kaiming",
        ],
        portability=0.5, stability_risk=0.3, verification_cost=18,
        falsification="If graphical.target critical path does not shorten, plan failed.",
    )


def phase6_parallel_kysdk() -> OptimizationPlan:
    """Relax serial After= constraints on kysdk daemons."""
    targets = [
        "kysdk-conf2.service", "kysdk-dbus.service", "kysdk-timer.service",
        "kysdk-basecommon.service", "kysdk-systime.service",
    ]
    drop_in = (
        "# KylinBootLab Phase 6 — parallelize kysdk startup\n"
        "[Unit]\n"
        "After=dbus.service basic.target\n"
        "Wants=dbus.service\n"
    )
    rollback = [
        f"sudo rm -f /etc/systemd/system/{t}/kbl-phase6.conf"
        for t in targets
    ] + ["sudo systemctl daemon-reload"]
    regression = [
        f"systemctl is-active {t}" for t in targets
    ]
    return OptimizationPlan(
        plan_id="phase6-parallel-kysdk",
        title="Parallelize kysdk daemon startup",
        category="parallelize",
        description=(
            "Multiple kysdk daemons have serial After= constraints totaling "
            "~500ms. Relax to After=dbus.service + basic.target with Wants= "
            "so they start in parallel."
        ),
        evidence=BottleneckEvidence(
            node="kysdk-conf2.service",
            blame_ns=500_000_000, slack_ns=0,
            on_critical_path=True, action_kind="parallelize",
        ),
        expected_gain=GainEstimate(
            predicted_ns=400_000_000, upper_bound_ns=500_000_000, confidence=0.7,
        ),
        drop_in_content=drop_in,
        drop_in_path="/etc/systemd/system/kysdk-conf2.service.d/kbl-phase6.conf",
        rollback=rollback,
        functional_regression=regression,
        portability=0.5, stability_risk=0.3, verification_cost=18,
        falsification="If no blame reduction on kysdk* units, plan failed.",
    )


def phase6_mitigations_off() -> OptimizationPlan:
    return OptimizationPlan(
        plan_id="phase6-mitigations-off",
        title="Disable CPU vulnerability mitigations via kernel cmdline",
        category="kernel_param",
        description=(
            "Add mitigations=off to kernel command line. Spectre/Meltdown "
            "mitigations are unnecessary on a single-purpose VM and add "
            "~200-500ms to kernel startup."
        ),
        evidence=BottleneckEvidence(
            node="kernel (mitigations overhead)",
            blame_ns=300_000_000, slack_ns=0,
            on_critical_path=True, action_kind="kernel_param",
        ),
        expected_gain=GainEstimate(
            predicted_ns=300_000_000, upper_bound_ns=500_000_000, confidence=0.8,
        ),
        drop_in_content=(
            'GRUB_CMDLINE_LINUX_DEFAULT="$GRUB_CMDLINE_LINUX_DEFAULT mitigations=off"\n'
        ),
        drop_in_path="/etc/default/grub.d/kbl-phase6.cfg",
        rollback=[
            "sudo rm -f /etc/default/grub.d/kbl-phase6.cfg",
            "sudo update-grub",
        ],
        functional_regression=["systemctl is-system-running | grep -q running"],
        portability=1.0, stability_risk=0.1, verification_cost=18,
        falsification="If kernel_ns does not decrease, plan failed.",
    )


def phase6_initramfs_trim() -> OptimizationPlan:
    return OptimizationPlan(
        plan_id="phase6-initramfs-trim",
        title="Trim initramfs to minimal module set (MODULES=dep)",
        category="initramfs_trim",
        description=(
            "Switch from MODULES=most to MODULES=dep in initramfs-tools, "
            "reducing the initramfs image size and module load time by "
            "~300-800ms on VM with no exotic hardware."
        ),
        evidence=BottleneckEvidence(
            node="initramfs (module loading)",
            blame_ns=500_000_000, slack_ns=0,
            on_critical_path=True, action_kind="initramfs_trim",
        ),
        expected_gain=GainEstimate(
            predicted_ns=500_000_000, upper_bound_ns=800_000_000, confidence=0.6,
        ),
        drop_in_content="MODULES=dep\n",
        drop_in_path="/etc/initramfs-tools/conf.d/kbl-phase6",
        rollback=[
            "sudo rm -f /etc/initramfs-tools/conf.d/kbl-phase6",
            "sudo update-initramfs -u -k all",
        ],
        functional_regression=[
            "dmesg | grep -q 'failed to load' && exit 1 || true",
        ],
        portability=0.8, stability_risk=0.5, verification_cost=18,
        falsification="If failed to load modules appear in dmesg, plan failed.",
    )
```

- [ ] **Step 4: Run tests + gates**

Run: `uv run pytest tests/test_optimization_plan.py -v && uv run ruff check src tests && uv run mypy src tests`
Expected: all pass.

- [ ] **Step 5: Commit**

```bash
git add src/kylinbootlab/optimization/plan.py tests/test_optimization_plan.py
git commit -m "feat: add Phase 6 optimization candidate factories (5 plans)"
```

---

### Task 2: Extend ProfileExecutor for grub + initramfs

**Files:**
- Modify: `src/kylinbootlab/optimization/executor.py`
- Append: `tests/test_optimization_scheduler.py` (command construction tests)

**Interfaces:**
- Consumes: `OptimizationPlan` with `category` in `{"kernel_param", "initramfs_trim"}`
- Modifies: `ProfileExecutor.apply()` — adds two branches for `plan.drop_in_path` variations
- Modifies: `ProfileExecutor.rollback()` — handles `kernel_param` (rm + update-grub) and `initramfs_trim` (rm + update-initramfs)
- Modifies: `ProfileExecutor.verify_applied()` — checks for grub config file or initramfs config file

- [ ] **Step 1: Read current executor.py to understand apply/rollback/verify_applied structure**

Important: grub and initramfs plans have a **two-step apply**: (1) write config file, (2) run update-grub or update-initramfs. Both steps need sudo password piping. The current executor's `apply()` method writes the drop-in via echo+tee; for grub/initramfs, add one extra SSH call after the echo+tee.

- [ ] **Step 2: Write the command construction tests**

Append to `tests/test_optimization_scheduler.py`:

```python
from kylinbootlab.optimization.plan import (
    phase6_mitigations_off,
    phase6_initramfs_trim,
)


class TestPhase6ExecutorCommands:
    def test_mitigations_off_apply_writes_grub_config(self) -> None:
        from kylinbootlab.optimization.executor import ProfileExecutor

        e = ProfileExecutor(target="kbl@target", password="testpass")
        plan = phase6_mitigations_off()

        # We can't test real SSH, but we can inspect command construction
        # by replacing _ssh with a recording callable.
        calls: list[str] = []

        def record(cmd: str) -> Any:
            calls.append(cmd)
            return subprocess.CompletedProcess([], 0, stdout="", stderr="")

        e._ssh = record  # type: ignore[method-assign]
        e.apply(plan)

        assert any("kbl-phase6.cfg" in c and "tee" in c for c in calls)
        assert any("update-grub" in c for c in calls)

    def test_initramfs_trim_apply_writes_config_and_runs_update_initramfs(self) -> None:
        from kylinbootlab.optimization.executor import ProfileExecutor

        e = ProfileExecutor(target="kbl@target", password="testpass")
        plan = phase6_initramfs_trim()
        calls: list[str] = []

        def record(cmd: str) -> Any:
            calls.append(cmd)
            return subprocess.CompletedProcess([], 0, stdout="", stderr="")

        e._ssh = record  # type: ignore[method-assign]
        e.apply(plan)

        assert any("MODULES=dep" in c for c in calls)
        assert any("update-initramfs" in c for c in calls)
        assert any("cp /boot/initrd" in c and ".kbl-backup" in c for c in calls)

    def test_mitigations_off_rollback_removes_config_and_updates_grub(self) -> None:
        from kylinbootlab.optimization.executor import ProfileExecutor

        e = ProfileExecutor(target="kbl@target", password="testpass")
        plan = phase6_mitigations_off()
        calls: list[str] = []

        def record(cmd: str) -> Any:
            calls.append(cmd)
            return subprocess.CompletedProcess([], 0, stdout="", stderr="")

        e._ssh = record  # type: ignore[method-assign]
        e.rollback(plan)

        assert any("rm -f" in c and "kbl-phase6.cfg" in c for c in calls)
        assert any("update-grub" in c for c in calls)
```

- [ ] **Step 3: Run to verify failure**

Run: `uv run pytest tests/test_optimization_scheduler.py -v -k Phase6`
Expected: FAIL — the `kernel_param` branch does not exist yet in apply/rollback.

- [ ] **Step 4: Implement executor extensions**

Add to `ProfileExecutor.apply()` after the existing drop-in path:

```python
elif plan.drop_in_content is not None and plan.drop_in_path is not None:
    if plan.category == "kernel_param":
        # Write grub config + update-grub
        escaped = plan.drop_in_content.replace("'", "'\\''")
        self._ssh(
            f"sudo mkdir -p $(dirname {plan.drop_in_path}) && "
            f"echo '{escaped}' | sudo tee {plan.drop_in_path} > /dev/null && "
            f"sudo update-grub"
        )
    elif plan.category == "initramfs_trim":
        # Backup current initrd, write config, rebuild initramfs
        escaped = plan.drop_in_content.replace("'", "'\\''")
        kernel = "$(uname -r)"
        self._ssh(
            f"sudo mkdir -p $(dirname {plan.drop_in_path}) && "
            f"echo '{escaped}' | sudo tee {plan.drop_in_path} > /dev/null && "
            f"sudo cp /boot/initrd.img-{kernel} /boot/initrd.img-{kernel}.kbl-backup && "
            f"sudo update-initramfs -u -k all"
        )
    else:
        # Standard drop-in (Phase 5 path)
        drop_in_dir = plan.drop_in_path.rsplit("/", 1)[0]
        escaped = plan.drop_in_content.replace("'", "'\\''")
        self._ssh(
            f"sudo mkdir -p {drop_in_dir} && "
            f"echo '{escaped}' | sudo tee {plan.drop_in_path} > /dev/null && "
            f"sudo systemctl daemon-reload"
        )
```

Add to `rollback()`:
```python
if plan.category == "kernel_param" and plan.drop_in_path is not None:
    self._ssh(
        f"sudo rm -f {plan.drop_in_path} && sudo update-grub"
    )
elif plan.category == "initramfs_trim" and plan.drop_in_path is not None:
    self._ssh(
        f"sudo rm -f {plan.drop_in_path} && sudo update-initramfs -u -k all"
    )
```

- [ ] **Step 5: Run tests + gates + commit**

Run: `uv run pytest tests/ -q --ignore=tests/test_rust_contract.py && uv run ruff check src tests && uv run mypy src tests`
Expected: all pass.

```bash
git add src/kylinbootlab/optimization/executor.py tests/test_optimization_scheduler.py
git commit -m "feat: extend ProfileExecutor for grub/initramfs categories"
```

---

### Task 3: Real-VM ABBA Acceptance (5 Candidates)

**Files:**
- Use: `scripts/abba_direct.py` (Phase 5 — run as-is with different function imports)

No new code. Modify `abba_direct.py` to accept a factory function directly:

```python
# Near the top, replace hardcoded imports with dynamic dispatch:
CANDIDATES = {
    "mask-strongswan": phase6_mask_strongswan,
    "kaiming-stagger": phase6_kaiming_stagger,
    "parallel-kysdk": phase6_parallel_kysdk,
    "mitigations-off": phase6_mitigations_off,
    "initramfs-trim": phase6_initramfs_trim,
}
```

Execute each candidate with `python scripts/abba_direct.py <candidate-name>` using the Phase 5 script. Results saved to `var/acceptance-<candidate>.json`.

**Prerequisites:** VM running, baseline snapshot exists, SSH reachable.

**For each candidate:**
1. `python scripts/abba_direct.py <candidate-name>` (18 cold boots, ~35 min)
2. Record verdict + statistics
3. Commit result to `docs/evidence/phase6/<candidate>-verdict.json`

**Exit criterion:** >=3 candidates complete, >=1 ACCEPTED.

No new code → no TDD steps. This is a runbook task. Commit evidence files after each candidate completes.

---

### Task 4: Quality Gates

- [ ] **Step 1: Run full gates**

```bash
uv run python scripts/export_schema.py --check
uv run ruff check .
uv run mypy src tests
uv run pytest tests/ -q --ignore=tests/test_rust_contract.py
```

Expected: all pass (pre-existing ruff warnings on plot scripts acceptable).

- [ ] **Step 2: Verify Phase 1-5 no regression**

```bash
uv run kbl version
uv run kbl experiment --help
uv run kbl optimize --help
```

Expected: all CLI groups respond correctly.

- [ ] **Step 3: Commit final state**

```bash
git add -A
git commit -m "chore: Phase 6 quality gates + evidence"
```
