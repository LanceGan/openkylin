# KylinBootLab Submission TODO

Last validation: 2026-07-22, after Claude's latest fix pass and Codex acceptance review.

No open P0 blockers remain.

## P1 - Must Fix Before Submission

- [ ] Strengthen the new fail-closed executor tests.
  - [tests/test_optimization_scheduler.py](tests/test_optimization_scheduler.py) currently checks that `_ssh` exists and that `ProfileApplyError` inherits `RuntimeError`, but it does not force `subprocess.run()` to return `rc=1`.
  - Add hermetic tests that monkeypatch `subprocess.run` and assert `pytest.raises(ProfileApplyError)` for both `_ssh()` and `_ssh_slow()`.
  - Avoid real `ssh t` calls in unit tests; `verify_applied()` should be tested with a stubbed `_ssh(..., raise_on_error=False)`.

- [ ] Tighten the Phase 6 CLI mapping smoke test.
  - [tests/test_cli.py](tests/test_cli.py) currently allows any non-zero exit code for `phase6-initramfs-trim --backend invalid`.
  - Assert that the failure is specifically `unknown power backend` / invalid backend handling.
  - Assert that output does not contain `Unknown plan_id`, so the test truly protects Phase 6 plan lookup.

- [ ] Make dashboard evidence match final report claims.
  - README and `docs/evidence/technical-report.md` claim 7 optimization candidates and a Phase 1-9 evidence dashboard.
  - `dashboard/src/data/index.js` currently imports only 3 ABBA verdict JSON files: `mask-biometric`, `socket-nm-wait`, and `phase6-initramfs-trim`.
  - Either add/import all seven candidate verdict artifacts, or describe the dashboard as a curated evidence view.

## P2 - Polish And Consistency

- [ ] Normalize strongSwan naming across code and reports.
  - Most evidence and plans use `strongswan-starter.service`.
  - `src/kylinbootlab/cli.py` still maps bottleneck candidates from `strongswan.service`, so `kbl optimize plan` may miss the real Phase 4 node.
  - Some titles/docstrings still say `strongswan.service` while the actual masked unit is `strongswan-starter.service`.

- [ ] Clarify the kaiming timing source.
  - README and the technical report use 1.4s / 1.427s median.
  - `docs/evidence/phase4-recon/recon-report.md` and `blame.txt` show a single-capture 3.225s value.
  - Add one sentence explaining that 1.427s is the multi-run median while 3.225s is the Phase 4 reconnaissance capture.

- [ ] Strengthen the boot performance benefit story if time allows.
  - Current evidence mainly demonstrates rigorous rejection of noisy single-change candidates.
  - A combined optimization profile ABBA experiment would make the performance narrative stronger, even if the verdict is only `PROMISING`.

- [ ] Decide whether `.vscode/` should be ignored or committed if it reappears as untracked.

## Resolved Or Downgraded

- [x] `socket-nm-wait` verdict artifact is self-consistent.
  - JSON verdict and recommendation both say `REJECTED`.
  - Functional gate failure is reflected in the artifact text.

- [x] `kbl agent benchmark` is now a manual evaluation protocol.
  - It no longer reports a fabricated automated score.
  - It prints the case list and manual scoring rubric.

- [x] Phase 6 plans are exposed through `kbl optimize run`.
  - `_load_known_plans()` includes all Phase 6 factories.
  - `phase6-initramfs-trim` resolves correctly in CLI lookup.

- [x] `ProfileExecutor` implementation now fails closed on SSH and slow-system commands.
  - `_ssh()` raises `ProfileApplyError` on non-zero return codes by default.
  - `_ssh_slow()` raises `ProfileApplyError` on non-zero return codes.
  - Remaining work is test quality, not the implementation path itself.

- [x] Competition requirement traceability table was added.
  - `docs/evidence/technical-report.md` now includes Appendix A mapping TASK_4-style requirements to evidence.

- [x] Functional regression evidence matrix was added.
  - `docs/evidence/technical-report.md` now includes Appendix B.
  - Several desktop functions remain explicitly marked as package-installed but not automatically checked in every ABBA run, which is acceptable if presented as a known limitation.

- [x] Phase 7 / Phase 10 boundary was clarified.
  - `docs/evidence/technical-report.md` now marks P/E scheduling, cgroup QoS, io_uring prefetch, 100-boot endurance, and larger-N ABBA as deferred/future work.

- [x] Upstream/submission material for kaiming was added.
  - `docs/evidence/upstream-kaiming-after-fix.md` exists and explains the proposed `After=multi-user.target` change.

- [x] `kbl optimize run-all` remains explicitly marked as future work.
  - It prints a clear not-yet-implemented message instead of crashing.

- [x] `FaultCorpusRunner.run_case()` remains explicitly marked as manual-only.
  - It returns a structured error result pointing to the manual script path.

- [x] Test count wording is acceptable.
  - `uv run pytest --collect-only -q` previously collected 318 tests.
  - README says about 320 tests.
  - `docs/evidence/technical-report.md` says more than 300 Python tests.

## Validation Commands From Latest Review

- `uv run pytest -q --ignore=tests/test_rust_contract.py`
  - Passed.
- `uv run pytest -q tests/test_cli.py tests/test_agent_benchmark.py tests/test_optimization_scheduler.py`
  - Passed, but some new tests are too weak and are listed above.
- `npm test` in `dashboard/`
  - Passed 5 tests.
- `npm run build` in `dashboard/`
  - Passed, with the existing chunk-size warning.
- `uv run kbl agent benchmark`
  - Passed protocol validation: prints the manual benchmark cases and scoring rubric.
- `uv run kbl optimize run phase6-initramfs-trim --backend invalid`
  - Passed plan lookup, then failed at the expected invalid backend check.
- `uv run pytest -q`
  - Still blocked only by the Rust contract tests in this Windows environment because `cargo` is unavailable here.
