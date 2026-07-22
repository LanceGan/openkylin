# KylinBootLab Submission TODO

Last validation: 2026-07-22, after Claude's second fix pass.

No open P0 blockers remain after the latest review.

## P1 - High-Value Submission Improvements

- [ ] Add focused tests for the fixed public entry points.
  - `kbl agent benchmark` now documents a manual evaluation protocol; add a test that locks that behavior and prevents the old `analyze(None)` placeholder path from coming back.
  - `kbl optimize run phase6-initramfs-trim` now resolves the plan ID; add a smoke test that protects the new Phase 6 CLI mapping.
  - `ProfileExecutor` should have tests proving failed `update-grub` / `update-initramfs` raises a failure instead of silently passing.

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

## Resolved Or Downgraded In Claude Pass 2

- [x] `socket-nm-wait` verdict artifact is now self-consistent.
  - JSON verdict and recommendation now both say `REJECTED`.
  - Functional gate failure is reflected in the artifact text.

- [x] `kbl agent benchmark` was downgraded from a fake automated score to a manual evaluation protocol.
  - It no longer reports a fabricated `0.0%` pass/fail result.
  - It now prints the case list and the manual scoring rubric.

- [x] Phase 6 plans are now exposed through `kbl optimize run`.
  - `_load_known_plans()` now includes all Phase 6 factories.
  - `phase6-initramfs-trim` resolves correctly in CLI lookup.

- [x] `ProfileExecutor` now fails closed on SSH and slow-system commands.
  - SSH return codes now raise `ProfileApplyError`.
  - `update-grub` and `update-initramfs` failures are no longer ignored.

- [x] `kbl optimize run-all` remains explicitly marked as future work.
  - It prints a clear not-yet-implemented message instead of crashing.

- [x] `FaultCorpusRunner.run_case()` remains explicitly marked as manual-only.
  - It returns a structured error result pointing to the manual script path.

- [x] Test count wording is acceptable.
  - `uv run pytest --collect-only -q` currently collects 318 tests.
  - README says about 320 tests.
  - `docs/evidence/technical-report.md` now says more than 300 Python tests.

## Validation Commands From Latest Review

- `uv run kbl agent benchmark`
  - Passed protocol validation: prints the manual benchmark cases and scoring rubric.
- `uv run kbl optimize run phase6-initramfs-trim --backend invalid`
  - Passed plan lookup, then failed at the expected invalid backend check.
- `uv run kbl optimize run-all`
  - Passed downgrade validation: prints "not yet implemented" instead of crashing.
- `uv run pytest --collect-only -q`
  - Collected 318 tests.
- `uv run pytest -q --ignore=tests/test_rust_contract.py`
  - Passed.
- `npm test` in `dashboard/`
  - Passed 5 tests.
- `npm run build` in `dashboard/`
  - Passed, with the existing chunk-size warning.
- `uv run pytest -q`
  - Still blocked only by the Rust contract tests in this Windows environment because `cargo` is unavailable here.
