# Cross-Distribution Validation Experiment Design

> KylinBootLab — 赛题第四维度：适配质量与跨发行版泛化能力

**Status:** Draft → Implementation
**Date:** 2026-07-22
**Author:** LanceGan

---

## 1. Motivation

### Current State
`adapters/` 目录提供了设计良好的三发行版适配器代码（distro.py、desktop.py、services.py、README.md），但**零次实际跨发行版实验**——没有任何一个 ABBA 实验在 Ubuntu 或 Fedora 上运行过。

### Problem
赛题评分第四维度 "适配质量与跨发行版泛化能力" 占 20 分。当前仅有设计文档，评委可能认定该项为 "设计良好但未验证"，预估 11–13 分。

### Goal
通过三发行版增量实验验证 KylinBootLab 分析管道的跨平台通用性，将第四维度评分从 11–13 分提升至 17–19 分。

---

## 2. Design Principles

1. **用数据说话，不用代码**——评委看的是实验结果，不是 Python 文件
2. **渐进式验证**——Tier 1→2→3，每层独立有产出，任一中断都有价值
3. **突出方法论泛化能力**——核心分析管道（DOT 解析、DP 关键路径、ABBA 协议、BootAgent）零代码修改即可跨发行版运行

---

## 3. Experiment Tiers

### Tier 1: Three-Distribution Baseline Comparison (required, ~2h)

**Hypothesis:** KylinBootLab's core analysis pipeline (`kbl collect` → `kbl analyze`) works identically across openKylin, Ubuntu, and Fedora with zero code changes.

| ID | Step | Platform | Command | Output |
|----|------|----------|---------|--------|
| 1.0 | Baseline exists | openKylin 2.0 SP2 | — | Existing data in RunStore |
| 1.1 | Deploy probe | Ubuntu 24.04 VM | `install_bootprobe.sh` | `kbl-bootprobe snapshot` runs |
| 1.2 | Collect baseline | Ubuntu 24.04 VM | `kbl collect --target ubuntu-vm` | RunStore entry |
| 1.3 | Build causal graph | Ubuntu 24.04 VM | `kbl analyze <RUN_ID>` | `causal-graph.json` + `bottleneck-report.json` |
| 1.4 | Deploy probe | Fedora 41 VM | `install_bootprobe.sh` | `kbl-bootprobe snapshot` runs |
| 1.5 | Collect baseline | Fedora 41 VM | `kbl collect --target fedora-vm` | RunStore entry |
| 1.6 | Build causal graph | Fedora 41 VM | `kbl analyze <RUN_ID>` | `causal-graph.json` + `bottleneck-report.json` |
| 1.7 | Compare | All three | Cross-run graph comparison | `docs/evidence/cross-distro/comparison.md` |

**Key comparison dimensions (Tier 1):**

| Dimension | Why it matters |
|-----------|---------------|
| Node count / edge count | Validates DOT parser on different systemd unit sets |
| Critical path length | Validates DP algorithm on different dependency graphs |
| Top-5 bottlenecks | openKylin-specific issues vs cross-distro patterns |
| `systemd-analyze` output format | Validates parser robustness |

**Degradation behavior:** `CausalGraphBuilder.build()` gracefully handles missing readiness events — the systemd-layer graph alone (333 nodes / 1651 edges for openKylin) is sufficient to prove the pipeline's cross-distro generality. No observer deployment needed for Tier 1.

---

### Tier 2: Ubuntu ABBA Experiment (high value, ~2h)

**Hypothesis:** The ABBA experiment protocol (`kbl optimize run`) produces valid verdicts on Ubuntu, proving the optimization validation pipeline is distribution-independent.

**Candidate:** `mask-strongswan` — most portable candidate:
- `strongswan-starter.service` has identical name on all three distributions
- `systemctl mask/unmask` is a standard systemd operation
- No initramfs/GRUB dependency
- No openKylin-specific service dependency

| ID | Step | Platform | Command | Output |
|----|------|----------|---------|--------|
| 2.0 | Baseline exists | openKylin 2.0 SP2 | — | `phase5-mask-strongswan-verdict.json` (from existing git data or re-run) |
| 2.1 | Deploy observer | Ubuntu 24.04 VM | `install_observer.sh` | Observer starts on boot |
| 2.2 | Create VM snapshot | Ubuntu 24.04 VM | `vmrun -T ws snapshot ubuntu.vmx baseline` | Clean restore point |
| 2.3 | Run ABBA (18 boots) | Ubuntu 24.04 VM | `kbl optimize run phase6-mask-strongswan --target ubuntu-vm` | 16 measured cold boots |
| 2.4 | Generate verdict | Control host | — | `docs/evidence/cross-distro/ubuntu-mask-strongswan-verdict.json` |
| 2.5 | Compare verdicts | openKylin vs Ubuntu | Manual analysis | `docs/evidence/cross-distro/comparison.md` |

**Expected comparison points (Tier 2):**
- Verdict agreement: Does Ubuntu produce the same verdict as openKylin?
- Median improvement magnitude
- 95% CI width (indicates measurement noise level)
- Functional regression: all checks pass on Ubuntu?

---

### Tier 3: Fedora dracut Toolchain Validation (bonus, ~2h)

**Hypothesis:** The initramfs toolchain adapter correctly abstracts `initramfs-tools` (openKylin/Ubuntu) vs `dracut` (Fedora), enabling initramfs-level optimization candidates to run on Fedora.

| ID | Step | Platform | Command | Output |
|----|------|----------|---------|--------|
| 3.1 | Deploy probe + observer | Fedora 41 VM | Install scripts | Functional observer |
| 3.2 | Create VM snapshot | Fedora 41 VM | `vmrun -T ws snapshot fedora.vmx baseline` | Clean restore point |
| 3.3 | Run ABBA (18 boots) | Fedora 41 VM | `kbl optimize run phase6-initramfs-trim --target fedora-vm` | 16 measured cold boots |
| 3.4 | Generate verdict | Control host | — | `docs/evidence/cross-distro/fedora-initramfs-trim-verdict.json` |
| 3.5 | Compare verdicts | openKylin vs Fedora | Manual analysis | `docs/evidence/cross-distro/comparison.md` |

**Special value:** `phase6-initramfs-trim` was REJECTED on openKylin (1.21%, CI crosses zero). Fedora's dracut has different module handling — the result may differ, demonstrating cross-distro scientific value.

---

## 4. Output Structure

```
docs/evidence/cross-distro/
├── comparison.md                          # Synthesis: comparison table + analysis narrative
├── ubuntu-baseline/
│   ├── causal-graph.json                  # Tier 1.3 output
│   └── bottleneck-report.json             # Tier 1.3 output
├── ubuntu-mask-strongswan-verdict.json    # Tier 2.4 output
├── fedora-baseline/
│   ├── causal-graph.json                  # Tier 1.6 output
│   └── bottleneck-report.json             # Tier 1.6 output
└── fedora-initramfs-trim-verdict.json     # Tier 3.4 output
```

---

## 5. Infrastructure Requirements

| Resource | Purpose | Status |
|----------|---------|--------|
| Ubuntu 24.04 VM (VMware) | Tier 1 + Tier 2 | Need to create |
| Fedora 41 VM (VMware) | Tier 1 + Tier 3 | Need to create |
| SSH key on control host → both VMs | All tiers | Need to configure |
| VMware snapshot capability | All tiers | Already working (vix backend) |

---

## 6. Risk Assessment

| Risk | Severity | Mitigation |
|------|----------|------------|
| Cannot provision Ubuntu/Fedora VMs in time | High | Download ISOs in advance; use pre-built cloud images |
| Rust cross-compilation issues (probe needs Linux to build) | Medium | Build probe binary inside each VM with `rustup`; use `scripts/target/install_bootprobe.sh` |
| Observer greeter pattern mismatch on Ubuntu/Fedora | Medium | `adapters/desktop.py` already documents correct patterns; test with `journalctl -b 0 | grep -i pam` first |
| dracut commands differ from initramfs-tools | Low | `adapters/distro.py` already has correct dracut commands; `ProfileExecutor` already supports initramfs backend override |
| Time running out | Medium | Tier 1 alone provides value; Tier 2-3 are additive |

---

## 7. Scoring Impact

| Dimension | Full Score | Before | After | Gain |
|-----------|:---------:|:------:|:-----:|:----:|
| 适配质量与跨发行版泛化能力 | 20 | 11–13 | 17–19 | **+5–7** |
| Total (all dimensions) | 100 | ~75 | ~82 | **~+7** |

Rationale for +5–7 point gain on Dimension 4:
- Tier 1 alone (+3): Proves analysis pipeline runs on 3 distros — directly addresses "方案具备可迁移性"
- Tier 1+2 (+5): Adds ABBA validation on second distro — proves "向其他 x86 Linux 平台迁移复用的能力"
- Tier 1+2+3 (+7): Full initramfs toolchain verification — demonstrates adapter abstraction is correct end-to-end

---

## 8. Self-Review Checklist

- [x] No TBD or TODO placeholders
- [x] All three tiers have concrete steps with commands and expected outputs
- [x] Risk table covers infrastructure, compatibility, and time constraints
- [x] Output structure defined explicitly
- [x] Scoring impact grounded in rubric dimensions from TASK_4.md
- [x] Does NOT require code changes to adapters/ — adapters are already correct; this validates them experimentally
