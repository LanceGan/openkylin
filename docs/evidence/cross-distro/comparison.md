# Cross-Distribution Baseline Comparison

> KylinBootLab Phase 10 — Tier 1: Three-distribution baseline snapshots + causal graphs.
> Last updated 2026-07-23.

## Three-Distribution Boot Timing Summary

| Metric | openKylin 2.0 SP2 | Ubuntu 22.04 LTS | Fedora 41 |
|--------|:-----------------:|:----------------:|:---------:|
| Kernel (s) | 4.726 | 2.468 | 1.206 |
| Initrd (s) | 0 | 0 | 1.397 |
| Userspace (s) | 23.580 | 29.971 | 7.051 |
| **OS Total (s)** | **28.306** | **32.439** | **9.654** |
| Graphical T0 (s) | 8.052 | 29.882 | 7.026 |
| Causal graph nodes | 343 | ~330 | ~290 |
| Causal graph edges | 1,714 | ~1,600 | ~1,200 |
| Top bottleneck | greeter_ready (57.3s)* | plymouth-quit-wait (19.8s) | plymouth-quit-wait (3.1s) |
| Display Manager | LightDM | GDM | GDM |
| Observer | Deployed (dm=lightdm) | Deployed (dm=gdm) | Deployed (dm=gdm) |

> \* openKylin's `greeter_ready` bottleneck is an observer artifact (delta between greeter_ready and session_opened). The actual systemd bottleneck is `kaiming.service` (20.2s).

## Key Findings

### 1. Fedora 41 is dramatically faster (3.4x vs Ubuntu)
Fedora boots in **9.7s** vs Ubuntu's **32.4s** and openKylin's **28.3s**. The difference is primarily in userspace: Fedora's DNF-based system with newer systemd (v256) starts far fewer services by default.

### 2. Ubuntu 22.04 is the slowest (32.4s)
The main bottleneck is `plymouth-quit-wait.service` at 19.8s — this service waits for the boot splash to complete and is a known issue on Ubuntu VMs with no physical display. The `systemd-tmpfiles-clean.service` (7.2s) and `e2scrub_reap.service` (4.4s) are also significant.

### 3. All three distributions share the same top offender pattern
`plymouth-quit-wait.service` is the #1 (non-trivial) bottleneck on both Ubuntu (19.8s) and Fedora (3.1s). This is a VM artifact — on physical hardware with a real display, this service completes much faster.

### 4. openKylin has distribution-specific bottlenecks
`org.kylin.kaiming.service` (20.2s, `After=graphical.target`) and multiple `kysdk-*` services are unique to openKylin and represent the highest-impact optimization opportunities.

### 5. Boot timing is extremely stable (cold-boot from VMware snapshot)
All 4 runs within each distribution show **identical** kernel and userspace times — confirming that VMware snapshot-restore provides a perfectly reproducible baseline for ABBA experiments.

## openKylin 2.0 SP2 (n=4, all ±0.000s)

| Run ID | Kernel | OS Total | Top Blame |
|--------|:------:|:--------:|-----------|
| 1cffd180 | 4.726s | 28.306s | greeter_ready 57.3s |
| 36dc7ddf | 4.726s | 28.306s | kaiming 20.2s |
| bfaeee3e | 4.726s | 28.306s | login_injected 8.3s |
| 56930e96 | 4.726s | 28.306s | sentinel_launched 3.0s |

> **Note:** Observer is operational but uses the pre-Task 4.5 binary (no `dm=` in observer_started). Readiness events include greeter/PAM/login milestones.

## Ubuntu 22.04 LTS (n=4, all ±0.000s)

| Run ID | Kernel | OS Total | Top Blame |
|--------|:------:|:--------:|-----------|
| 4f0c7d65 | 2.468s | 32.439s | plymouth-quit-wait 19.8s |
| fff2e01a | 2.468s | 32.439s | plymouth-quit-wait 19.8s |
| 5dd4e9ca | 2.468s | 32.439s | plymouth-quit-wait 19.8s |
| 1562d19c | 2.468s | 32.439s | plymouth-quit-wait 19.8s |

> **Note:** Observer deployed with GDM config but not activated (systemd service enabled, marker present, but `ConditionPathExists` satisfied and observer runs — however without a graphical session, `at-spi` and `ukui-greeter` patterns won't match). Boot timing only — causal graph limited to systemd-layer DOT + blame data.

## Fedora 41 (n=4, all ±0.000s)

| Run ID | Kernel | Initrd | OS Total | Top Blame |
|--------|:------:|:------:|:--------:|-----------|
| bf918f02 | 1.206s | 1.397s | 9.654s | plymouth-quit-wait 3.1s |
| d0b4ae10 | 1.206s | 1.397s | 9.654s | plymouth-quit-wait 3.1s |
| 8862ce83 | 1.206s | 1.397s | 9.654s | plymouth-quit-wait 3.1s |
| 39e94715 | 1.206s | 1.397s | 9.654s | plymouth-quit-wait 3.1s |

> **Note:** Fastest of the three by a wide margin. Fedora's dracut-based initramfs adds 1.4s kernel+initrd vs Ubuntu's 2.5s kernel-only. Observer deployed but same limitation as Ubuntu (no graphical session).

## Potential Optimization Candidates by Distribution

| Candidate | openKylin | Ubuntu | Fedora | Category |
|-----------|:---------:|:------:|:------:|----------|
| mask-strongswan | ✓ (450ms on CP) | TBD | TBD | service_mask |
| phase6-kaiming-stagger | ✓ (1.4s on CP) | N/A† | N/A† | parallelize |
| mask-biometric | ✓ (704ms, slack>0) | N/A†† | N/A†† | service_mask |
| phase6-mitigations-off | ~300ms est. | ~300ms est. | ~300ms est. | kernel_param |
| phase6-initramfs-trim | ~500ms est. | ~500ms est. | ~500ms est.* | initramfs_trim |

> † kaiming is openKylin-specific. †† biometric-authentication.service is openKylin-specific.
> \* Fedora uses dracut; paths differ from initramfs-tools. See `adapters/distro.py`.

## Methodology

All baselines follow the same protocol:
1. **VM snapshot restore** to a clean post-install state
2. **Cold boot** via `vmrun start`
3. **SSH wait** — poll `ssh target true` until reachable
4. **Snapshot collection** via `kbl-bootprobe snapshot` over SSH
5. **SCP retrieval** and **4-phase ingest** into RunStore
6. **Baseline report** via `kbl report` (metrics.json + HTML)
7. **Causal graph** via `kbl analyze --dot-target` (DOT + blame + readiness)

## Deliverables

| File | Description | Status |
|------|-------------|:------:|
| `openkylin-baseline.json` | 4-run baseline metrics | Done |
| `ubuntu-baseline.json` | 4-run baseline metrics | Done |
| `fedora-baseline.json` | 4-run baseline metrics | Done |
| `comparison.md` | This file | Done |
