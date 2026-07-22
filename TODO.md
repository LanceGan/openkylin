# KylinBootLab Submission TODO

## P0 - Must Fix Before Submission

- [ ] Reconcile the `socket-nm-wait` verdict inconsistency.
  - `docs/evidence/technical-report.md` says `socket-nm-wait` is `REJECTED`.
  - `docs/evidence/phase5-socket-nm-wait-verdict.json` says it is `PROMISING`.
  - Decide the authoritative result and update the technical report, README, dashboard data, and any summary tables to match.

- [ ] Remove or clearly label incomplete public command paths.
  - `kbl optimize run-all` currently raises `NotImplementedError`.
  - `FaultCorpusRunner.run_case()` currently raises `NotImplementedError`.
  - Either implement these paths or mark them as planned/future work so the submitted CLI does not promise unsupported automation.

- [ ] Align claimed test counts with the current repository.
  - README says about 320 Python tests, which matches the current collection closely.
  - `docs/evidence/technical-report.md` says about 330 Python tests.
  - `uv run pytest --collect-only -q` currently collects 318 tests.
  - Update the technical report or add the missing tests before final packaging.

## P1 - High-Value Submission Improvements

- [ ] Add a competition requirement traceability table.
  - Map each TASK_4.md requirement to evidence files, CLI commands, code modules, and status.
  - Separate "implemented", "experimentally verified", and "documented portability" statuses.

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

- [ ] Decide whether `.vscode/` should be ignored or committed.
  - It is currently untracked.
