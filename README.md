# KylinBootLab

> 开放原子开源大赛 — openKylin 赛题第四题：操作系统启动性能分析与优化
>
> A full-chain Linux boot performance analysis, optimization, and validation system.

## Overview

KylinBootLab measures, explains, optimizes, and validates Linux desktop boot performance — from kernel startup through systemd initialization to UKUI desktop readiness — using causal-graph modeling, randomized ABBA experiments, and a local-LLM diagnostic assistant (BootAgent).

**Target platform:** openKylin 2.0 SP2 (ostree-based, UKUI desktop, lightdm, systemd 255)  
**Controller:** Windows 10 + Python 3.12 + Rust 1.85.1 + Ollama  
**Architecture:** Dual-machine closed-loop — Windows controller orchestrates experiments on an openKylin VM

## Quick Start

```powershell
# Install toolchain
winget install --id astral-sh.uv --exact
winget install --id Rustlang.Rustup --exact
uv python install 3.12

# Clone and build
git clone https://github.com/LanceGan/openkylin.git
cd openkylin
git checkout worktree-kylinbootlab-phase1
uv sync --all-groups --python 3.12

# Run quality gates
uv run ruff check . && uv run mypy src tests && uv run pytest -q --ignore=tests/test_rust_contract.py
cargo fmt --all -- --check && cargo clippy --workspace --all-targets -- -D warnings && cargo test --workspace

# Open evidence dashboard
uv run kbl dashboard
```

## Project Structure

```
KylinBootLab/
├── src/kylinbootlab/           # Python controller — analysis, storage, CLI
│   ├── cli.py                  # kbl version/ingest/report/collect/calibrate/optimize/agent/dashboard
│   ├── contracts.py            # Pydantic data contracts (v1, frozen schema)
│   ├── store.py                # Immutable RunStore (4-phase validation pipeline)
│   ├── systemd.py              # Deterministic systemd-analyze parser
│   ├── report.py               # Baseline HTML/JSON report generator
│   ├── readiness.py            # Phase 3 readiness event parser + T-point derivation
│   ├── remote.py               # SSH/SCP transport (BatchMode, timeouts)
│   ├── calibrate.py            # Phase 3C observer overhead calibration
│   ├── analysis/               # Phase 4 causal graph + simulator
│   │   ├── dot.py              # systemd DOT graph parser
│   │   ├── graph.py            # CausalNode / CausalEdge / CausalGraph models
│   │   ├── builder.py          # DOT + blame + readiness → hybrid causal graph
│   │   ├── critical_path.py    # Topological DP critical path + slack (O(V+E))
│   │   ├── bottleneck.py       # Scored bottleneck ranking engine
│   │   ├── simulator.py        # WhatIfSimulator (remove_edge, reduce_blame)
│   │   └── compare.py          # Cross-run GraphDiff
│   ├── experiments/            # Phase 2 automated experiment orchestration
│   │   ├── contracts.py        # ExperimentRecord Pydantic model
│   │   ├── queue.py            # JSONL-persisted experiment queue
│   │   ├── orchestrator.py     # Main experiment loop (power → wait → collect → repeat)
│   │   ├── power.py            # TargetPower protocol + VixPower (vmrun) + WolPower backends
│   │   ├── aliveness.py        # SSH-based alive detection (wait_for_ssh, wait_for_boot_finished)
│   │   └── recovery.py         # Double-layer recovery (VM snapshot + ostree rollback)
│   ├── optimization/           # Phase 5-6 optimization planner + validator
│   │   ├── plan.py             # OptimizationPlan + 10 factory functions
│   │   ├── planner.py          # Candidate scoring (gain × confidence × portability ÷ risk ÷ cost)
│   │   ├── scheduler.py        # ABBA sequence generator + profile state machine
│   │   ├── executor.py         # SSH drop-in/mask/grub/initramfs executor
│   │   ├── validator.py        # Bootstrap CI + three-tier verdict (ACCEPTED/PROMISING/REJECTED)
│   │   └── runner.py           # ABBA experiment runner (Phase 2 orchestrator integration)
│   └── agent/                  # Phase 8 BootAgent (local LLM diagnostic)
│       ├── backend.py           # Ollama HTTP API backend (Qwen2.5-Coder-7B, CPU)
│       ├── models.py            # TraceAnalysis / SourceReport / ExperimentPlan / SafetyReview
│       ├── skills.py            # TOML skill loader + JSON Schema validator + output normalizer
│       ├── controller.py        # Four-role sequential pipeline controller
│       └── benchmark.py         # 5-case fault benchmark evaluator
├── target/bootprobe/           # Rust target probe
│   └── src/
│       ├── main.rs             # CLI (contract-fixture, snapshot, observe, usable-probe)
│       ├── model.rs            # Rust contract types (1:1 with Python Pydantic)
│       ├── snapshot.rs         # Snapshot orchestration (systemd time/blame/chain/journal)
│       ├── events.rs           # ReadinessEvent v1 model + JSONL serialization
│       ├── observe/            # Root-side boot observer
│       │   ├── config.rs       # observe.toml parser
│       │   ├── journal.rs      # journald JSON line parser
│       │   ├── keymap.rs       # char → evdev keycode table
│       │   ├── uinput.rs       # Virtual keyboard driver (/dev/uinput)
│       │   └── state.rs        # Pure readiness state machine
│       └── usable/             # Session-side desktop probe
│           ├── procscan.rs     # Process comm scanner
│           └── atspi.rs        # AT-SPI busctl child count + sentinel detection
├── tests/                      # Python test suite (~320 tests, 100% pass)
├── dashboard/                  # Phase 9 evidence SPA (React + Recharts + Tailwind)
├── agent/skills/               # BootAgent TOML skill configurations (4 roles)
├── scripts/                    # Quality gates, target installers, calibration
├── docs/
│   ├── superpowers/specs/      # Phase 1-9 design specifications
│   ├── superpowers/plans/      # Phase 1-9 implementation plans
│   ├── runbooks/               # Target setup + Phase 3 observer deployment
│   └── evidence/               # Phase 3-6 calibration + ABBA verdicts + fault corpus
└── profiles/                   # Declarative optimization profiles (→ Phase 10)
```

## Phase Summary

| Phase | Deliverable | Key Result |
|-------|------------|------------|
| **1** | Baseline capture MVP | Rust probe + Python pipeline + 30 tests, 91% coverage |
| **2** | Automated cold-boot testbed | 10 unattended cold-boot cycles; fault injection auto-recovery |
| **3** | Semantic readiness probing | Tlogin-ready=15.0s, Tsession=67.0s, Tusable=78.3s (real uinput login) |
| **4** | Causal graph + what-if simulator | 333-node DOT graph → topological DP → bottleneck ranking (O(V+E)) |
| **5** | Optimization planner + validator | ABBA protocol (4 blocks × 4 boots), bootstrap CI, three-tier verdict |
| **6** | Systemd + kernel optimization | 5 candidates × 18 boots ABBA evaluated (~85 real-VM cold boots) |
| **7** | — deferred | P/E core scheduling, cgroup QoS, io_uring prefetch (requires bare-metal) |
| **8** | BootAgent (local LLM diagnostic) | Qwen2.5-Coder-7B CPU inference, 4-role prompt pipeline, 5-case benchmark |
| **9** | Interactive evidence dashboard | React + Recharts + Tailwind SPA, `kbl dashboard` one-click launch |

## Key Findings

### Boot Readiness (Phase 3)
Real uinput login on openKylin SP2: greeter starts at 6.6s, ready at 15.0s, PAM session opened at 67.0s, desktop usable at 78.3s (AT-SPI enumeration confirmed).

### Optimization Insights (Phases 5-6)
Seven independent optimization candidates tested across ~100 real-VM cold boots. **Every single-systemd-config change was REJECTED** — the ~9.5s boot is dominated by kernel+initramfs (~5s), not by user-space service ordering. The ABBA framework correctly rejects noise in all cases. The combined evidence points to multi-change strategies (Phase 10) as the path to measurable improvement.

### Causal Analysis (Phase 4)
333-node / 1651-edge systemd dependency graph computed. `org.kylin.kaiming.service` (1.4s blame, After=graphical.target bypass) is the single highest-value optimization target — its After= constraint is unnecessary for a dbus-activated service.

### Agent Validation (Phase 8)
Qwen2.5-Coder-7B (CPU-only, ~4.5GB RAM) successfully produces structured diagnostic reports through a 4-role prompt pipeline. The validation pipeline normalizes 7B-model output quirks (field-name aliases, nested objects, null defaults, negative values) into valid Pydantic JSON.

## Safety Architecture

```
Controller (Windows)              Target (openKylin VM)
─────────────────────              ─────────────────────
• Experiment orchestrator          • kbl-bootprobe (read-only snapshot)
• Causal graph analyzer            • Boot observer (journald + uinput)
• BootAgent (local LLM)            • Systemd drop-in executor
• ABBA validator                   • Phase 2 baseline snapshot (ultimate recovery)
       │                                   │
       └──── SSH (BatchMode, timeout) ─────┘
```

- Agent **never** executes shell commands — outputs JSON schemas only
- All optimization changes are idempotent systemd drop-ins (mask/unmask)
- Phase 2 VMware snapshot provides sub-second recovery from any failure
- Immutable run storage (TOCTOU-protected 4-phase pipeline)

## Competition Scoring Alignment

| Dimension (points) | Evidence |
|-------------------|----------|
| Boot performance (25) | 7 candidates × ABBA validation, calibration overhead <1% |
| Correctness & stability (20) | Functional regression gates, recovery testing, 100+ unattended boots |
| Analysis & innovation (25) | Causal graph (DP), semantic readiness probing (uinput), BootAgent (LLM) |
| Portability (20) | `TargetPower` protocol (VMware/bare-metal), systemd-analyze standard output |
| Engineering (10) | 83 commits, ~320 tests, ruff/mypy strict, immutable data store, one-click dashboard |

## Commands

```bash
kbl version                    # Print package version
kbl collect --target HOST      # SSH capture from target
kbl ingest BUNDLE              # Validate + import probe bundle
kbl report RUN_ID              # Generate baseline HTML/JSON report
kbl experiment queue/run/status # Queued experiment orchestration
kbl calibrate                  # Observer overhead calibration
kbl optimize plan/run          # Optimization candidate ranking + ABBA validation
kbl analyze RUN_ID             # Causal graph bottleneck analysis
kbl agent analyze/benchmark    # BootAgent LLM diagnostic pipeline
kbl dashboard                  # Open Phase 1-9 evidence dashboard
```

## License

Apache-2.0
