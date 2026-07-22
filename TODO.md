# KylinBootLab Submission TODO

Last validation: 2026-07-22, after Claude's first fix pass.

## P0 - Must Fix Before Submission

- [ ] Fully reconcile the `socket-nm-wait` verdict artifact.
  - `docs/evidence/phase5-socket-nm-wait-verdict.json` now has:
    - `"verdict": "REJECTED"`
    - `"functional_passed": false`
    - failed gate: VM SSH became unreachable at boot 7/18
  - But the same JSON still says in `recommendation`:
    - `PROMISING`
    - `functional tests pass`
  - Update the recommendation text so the JSON, technical report, README, and dashboard all agree on the final `REJECTED` result.

- [ ] Fix or clearly downgrade `kbl agent benchmark`.
  - Current command: `uv run kbl agent benchmark`
  - Current result: `Benchmark accuracy: 0.0%`
  - Root cause:
    - `src/kylinbootlab/cli.py` still calls `agent.analyze(None)` for every benchmark case.
    - `BootAgent.analyze(None)` returns an empty placeholder report.
  - Either implement real per-case benchmark input and scoring, or change README/report wording so BootAgent benchmark is not claimed as a completed >=60% validation.

- [ ] Expose Phase 6 plans through `kbl optimize run`, or stop claiming they are runnable through that CLI.
  - Current command: `uv run kbl optimize run phase6-initramfs-trim`
  - Current result: `Unknown plan_id: phase6-initramfs-trim`
  - `src/kylinbootlab/optimization/plan.py` defines Phase 6 factories, but `src/kylinbootlab/cli.py::_load_known_plans()` only registers Phase 5 factories.
  - Register:
    - `phase6-mask-strongswan`
    - `phase6-kaiming-stagger`
    - `phase6-parallel-kysdk`
    - `phase6-mitigations-off`
    - `phase6-initramfs-trim`

- [ ] Make `ProfileExecutor` fail closed on failed apply/rollback commands.
  - `src/kylinbootlab/optimization/executor.py` still ignores return codes from:
    - `systemctl mask`
    - drop-in writes
    - `update-grub`
    - `update-initramfs`
    - rollback commands
  - `verify_applied()` still checks only whether the config file exists for kernel/initramfs plans.
  - Risk: `update-grub` or `update-initramfs` can fail while the candidate is treated as applied.
  - Expected behavior: check return codes, include stderr/stdout in errors, and verify the effective grub/initramfs state where practical.

## P1 - High-Value Submission Improvements

- [ ] Add focused tests for the fixed public entry points.
  - `kbl agent benchmark` should have a test that prevents the `analyze(None)` placeholder path from being reported as a successful benchmark.
  - `kbl optimize run phase6-initramfs-trim` should at least pass plan lookup before any target-side SSH/power operation.
  - `ProfileExecutor` should have tests proving failed `update-grub` / `update-initramfs` causes apply failure.

- [ ] Add a competition requirement traceability table.
  - Map each TASK_4.md requirement to evidence files, CLI commands, code modules, and status.
  - Separate "implemented", "experimentally verified", "manual evidence", and "documented portability" statuses.

- [ ] Add a functional regression evidence matrix.
  - Cover login, NetworkManager, dbus, display manager, desktop panel/launcher/tray, file manager, terminal, settings center, audio, input method, and first-use behavior.
  - Link each row to a run ID, log, screenshot, or command output.

- [ ] Strengthen the boot performance benefit story.
  - Current evidence mostly demonstrates rigorous rejection of noisy single-change candidates.
  - If time allows, run a combined optimization profile ABBA experiment and report the result even if it is only `PROMISING`.

- [ ] Clarify the Phase 7 / Phase 10 boundary.
  - P/E core scheduling, cgroup QoS, io_uring prefetch, full 100-boot endurance, and Ubuntu/Fedora execution are not fully implemented in the current repo.
  - Present them as future work unless real evidence is added.

## P2 - Polish And Consistency

- [ ] Normalize naming across reports and code.
  - Some places say `strongswan.service`; others use `strongswan-starter.service`.
  - Some places describe `kaiming` as 1.4s; recon evidence also shows 3.225s in one capture.

- [ ] Add upstream/submission material for the strongest openKylin-specific finding.
  - Prepare a patch note or issue draft for `org.kylin.kaiming.service` and its unnecessary `After=graphical.target` ordering.

- [ ] Make dashboard evidence match final report claims.
  - Dashboard imports only calibration, two Phase 5 verdicts, and one Phase 6 verdict.
  - Either add all seven candidates or describe dashboard as a curated evidence view.

- [ ] Decide whether `.vscode/` should be ignored or committed if it reappears as untracked.

## Resolved Or Downgraded In Claude Pass 1

- [x] `kbl optimize run-all` no longer raises `NotImplementedError`.
  - It now prints a clear "not yet implemented" message and points users to `kbl optimize run <plan_id>`.
  - This is acceptable if README/report do not claim batch optimization is implemented.

- [x] `FaultCorpusRunner.run_case()` no longer raises `NotImplementedError`.
  - It returns a structured `error` result and points to manual execution via `scripts/fault_corpus_run.py`.
  - This is acceptable only if final docs call the fault corpus manual evidence, not fully automated validation.

- [x] Test count wording is now acceptable.
  - `uv run pytest --collect-only -q` currently collects 318 tests.
  - README says about 320 tests.
  - `docs/evidence/technical-report.md` now says more than 300 Python tests.

## Validation Commands From Latest Review

- `uv run kbl agent benchmark`
  - Failed validation: `Benchmark accuracy: 0.0%`
- `uv run kbl optimize run phase6-initramfs-trim`
  - Failed validation: `Unknown plan_id: phase6-initramfs-trim`
- `uv run kbl optimize run-all`
  - Passed downgrade validation: prints "not yet implemented" instead of crashing.
- `uv run pytest --collect-only -q`
  - Collected 318 tests.
- `npm test` in `dashboard/`
  - Passed 5 tests.
- `npm run build` in `dashboard/`
  - Passed, with existing chunk-size warning.
- `uv run pytest -q`
  - Failed 2 Rust contract tests because `cargo` is not available in the current Windows environment.
  - Re-run in an environment with Rust/Cargo before final submission.
