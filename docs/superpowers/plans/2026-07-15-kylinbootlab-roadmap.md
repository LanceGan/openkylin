# KylinBootLab Program Roadmap Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Deliver the approved KylinBootLab competition system as a sequence of independently testable vertical slices, ending with reproducible bare-metal performance results, validated optimizations, BootAgent evaluation, and final competition artifacts.

**Architecture:** A Windows laptop controls an openKylin bare-metal target. Versioned contracts connect a Rust target probe, Python orchestration and analysis packages, C/libbpf collectors, a constrained local-model Agent, and a TypeScript report UI. Each phase preserves immutable run artifacts and extends the same contracts instead of replacing earlier work.

**Tech Stack:** Python 3.12, Rust 1.85.1, C/libbpf, JSON Schema, SQLite, compressed JSONL, pytest, cargo test, Qwen2.5-Coder-7B-Instruct via llama.cpp, TypeScript, Playwright

---

## Why This Is Split

The approved design contains ten substantial subsystems. A single task list would have to guess openKylin release details, UKUI source package paths, kernel capabilities, systemd version, NIC wake behavior, and the first measured bottlenecks before those facts exist. That would make later file paths and tests fictional.

This roadmap therefore fixes the program boundaries and cross-phase contracts now. Each detailed phase plan is written immediately before that phase starts, using the immutable outputs and discovery report from the preceding phase. Every phase must leave working, demonstrable software and a clean commit history.

## Stable Cross-Phase Contracts

The following paths and concepts are stable for the entire program:

```text
src/kylinbootlab/                 Python controller and analysis package
target/bootprobe/                 Rust target-side collection binary
target/bpf/                       C/libbpf diagnostic collectors
agent/                            BootAgent tools, retrieval, roles, and benchmark
adapters/                         Distribution, desktop, and initramfs adapters
profiles/                         Declarative baseline and optimization profiles
dashboard/                        TypeScript interactive report application
tests/                            Python cross-component and acceptance tests
experiments/                      Versioned experiment manifests, never raw mutable data
var/runs/<run_id>/raw/            Immutable imported artifacts, ignored by Git
var/runs/<run_id>/derived/        Rebuildable metrics and graph outputs
var/runs/<run_id>/reports/        Rebuildable HTML and JSON reports
docs/runbooks/                    Operator procedures and recovery instructions
docs/evidence/                    Competition evidence indexes and result summaries
```

All persisted contracts use explicit integer schema versions. A reader must reject an unknown major version rather than silently guessing. Contract migrations create new derived data and never modify files under `raw/`.

The first contract is `ProbeManifest` version 1. Later phases add separate versioned contracts for `Event`, `ReadinessEvent`, `CausalGraph`, `OptimizationPlan`, `ExperimentManifest`, and `ValidationResult`. Existing fields are not repurposed.

## Phase Sequence

### Phase 1: Foundation and Baseline Capture MVP

Detailed plan: `docs/superpowers/plans/2026-07-15-kylinbootlab-foundation-baseline.md`

Build the monorepo, versioned probe manifest, Rust target snapshot command, immutable Python run store, systemd timing parser, SSH collection command, and static baseline report. The phase is complete when one real openKylin boot can be captured on the target and rendered as a verified report on the controller.

### Phase 2: Automated Cold-Boot Testbed and Recovery

Planned document: `docs/superpowers/plans/2026-07-15-kylinbootlab-testbed-recovery.md`

Add Wake-on-LAN, S5 state verification, one-shot GRUB experiment entries, watchdog heartbeats, controller timeouts, recovery-environment status, experiment queue persistence, and interrupted-run classification. The phase is complete after ten unattended smoke cycles plus injected user-space hangs recover without corrupting the experiment root.

### Phase 3: Full Observability and Semantic Readiness

Planned document: `docs/superpowers/plans/2026-07-15-kylinbootlab-observability-readiness.md`

Add diagnostic and benchmark collection modes, ftrace/perf fallback, libbpf CO-RE probes where supported, unified `CLOCK_BOOTTIME` events, display-manager probes, UKUI session probes, AT-SPI checks, `uinput` login, and observer-overhead calibration. The phase is complete when the system measures `T0`, `Tlogin-ready`, `Tsession`, and `Tusable` with less than 1% benchmark-mode median overhead.

### Phase 4: Causal Graph and Simulator

Planned document: `docs/superpowers/plans/2026-07-15-kylinbootlab-causal-simulator.md`

Build dependency normalization, resource-wait attribution, strongly connected component handling, readiness-gated longest paths, slack, criticality probability, cross-run comparison, and the discrete-event what-if simulator. The phase is complete when a reversible fault corpus demonstrates correct Top-3 root-cause localization and calibrated gain estimates.

### Phase 5: Transactional Profiles, Optimizer, and Validator

Planned document: `docs/superpowers/plans/2026-07-15-kylinbootlab-optimizer-validator.md`

Add the `OptimizationPlan` schema, deterministic candidate ranking, systemd generator profiles, versioned package switching, preflight checks, rollback records, randomized ABBA scheduling, bootstrap confidence intervals, functionality gates, first-use non-inferiority, and acceptance decisions. The phase is complete when a synthetic safe optimization is accepted and three unsafe or regressive variants are automatically rejected and rolled back.

### Phase 6: systemd and UKUI Source Optimizations

Planned document: `docs/superpowers/plans/2026-07-15-kylinbootlab-systemd-ukui-optimization.md`

Use measured critical paths to remove false ordering constraints, introduce safe activation, repair blocking desktop calls, parallelize independent UKUI initialization, add readiness signals, and package source patches. The phase is complete after at least three independent accepted improvements have reproducible evidence and upstream-quality patch series.

### Phase 7: Resource, Prefetch, and initramfs Optimizations

Planned document: `docs/superpowers/plans/2026-07-15-kylinbootlab-deep-optimization.md`

Add P/E topology discovery, cgroup-based boot QoS, homogeneous-x86 fallback, stable critical-file learning, pressure-aware io_uring prefetch, initramfs driver closure, compression experiments, and device-wait analysis. The phase is complete when each enabled mechanism independently passes the optimizer hard gates and their combination is tested for interference.

### Phase 8: BootAgent and Agent Benchmark

Planned document: `docs/superpowers/plans/2026-07-15-kylinbootlab-agent.md`

Add schema-constrained tools, source/document retrieval, Trace Analyst, Source Investigator, Experiment Designer, Safety Critic, approval gates, fixed llama.cpp inference, and the known-root-cause benchmark. The phase is complete when BootAgent beats both raw systemd output and a generic log-reading LLM on predeclared accuracy and safety metrics.

### Phase 9: Interactive Evidence Dashboard

Planned document: `docs/superpowers/plans/2026-07-15-kylinbootlab-dashboard.md`

Build a static-exportable TypeScript dashboard for timelines, causal graphs, A/B distributions, optimization evidence, functional results, and run provenance. The phase is complete when Playwright validates desktop/mobile layouts and every displayed value links to a run ID and generated data artifact.

### Phase 10: Portability, Endurance, and Competition Package

Planned document: `docs/superpowers/plans/2026-07-15-kylinbootlab-final-validation.md`

Add Ubuntu bare-metal and Fedora virtual-machine adapters, perform the 30-versus-30 formal benchmark, execute 100 optimized cold boots, finish fault recovery, regenerate all reports from raw data, assemble SBOM and licenses, index upstream submissions, and rehearse the offline demonstration. The phase is complete only when the approved design success criteria are either met or explicitly reported with evidence.

## Dependency Flow

```text
Foundation
    ↓
Automated testbed → Full observability → Causal graph
                                         ↓
                          Optimizer and validator
                              ↓               ↓
                    systemd/UKUI       Deep optimization
                              \               /
                               BootAgent tools
                                     ↓
                            Evidence dashboard
                                     ↓
                       Portability and final validation
```

No phase may consume an undocumented internal representation from another phase. Shared data crosses boundaries only through versioned models or command interfaces covered by contract tests.

## Scoring Coverage

| Competition dimension | Primary phases | Required evidence |
|---|---|---|
| Startup performance, 25 | 3, 6, 7, 10 | Formal cold-boot distributions and accepted optimization effects |
| Correctness and stability, 20 | 2, 5, 10 | Functional matrices, first-use tests, recovery tests, 100-boot result |
| Analysis and innovation, 25 | 3, 4, 8 | Semantic readiness, probabilistic causal graph, simulator, Agent benchmark |
| Adaptation and portability, 20 | 6, 7, 10 | openKylin patches, generic fallbacks, Ubuntu/Fedora reports |
| Engineering and reproducibility, 10 | All | Contracts, immutable data, exact commands, CI checks, documentation, SBOM |

## Approved-Spec Traceability

| Approved design area | Implementing phases |
|---|---|
| Double-machine architecture and immutable data flow | 1, 2 |
| `T0`, login-ready, session, desktop-ready, and usable measurements | 3 |
| Randomized benchmark protocol and statistical hard gates | 5, 10 |
| Semantic causal graph and what-if simulation | 4 |
| Kernel/initramfs, systemd, resource, prefetch, and UKUI optimization | 6, 7 |
| Constrained evidence-driven BootAgent and fault benchmark | 8 |
| Transactional execution, watchdog recovery, and functional regression | 2, 5, 10 |
| Ubuntu/Fedora portability and adapter boundaries | 10 |
| Static and interactive evidence, reproducibility package, SBOM, and demo | 9, 10 |

## Program-Level Verification

Every phase ends with these commands, extended as the repository grows:

```powershell
uv run ruff check .
uv run mypy src tests
uv run pytest -q
cargo fmt --all -- --check
cargo clippy --workspace --all-targets -- -D warnings
cargo test --workspace
git diff --check
```

Expected result: every command exits 0. Platform-specific tests use explicit markers and run on openKylin in the target acceptance step; they are never silently skipped in the final competition verification.

## Commit Policy

Each detailed task ends in one focused commit. Generated raw experiment data remains outside Git under `var/`; small deterministic fixtures and result summaries are committed. Existing competition documents remain untouched unless a later plan explicitly adds them as cited source material.
