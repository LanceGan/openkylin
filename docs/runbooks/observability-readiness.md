# Runbook: Phase 3 Observability & Readiness

Deploy and verify the dual-component readiness observer on an openKylin
2.0 SP2 target that already passed the Phase 1/2 runbooks.

## 1. Prerequisites

- Phase 1 foundation deployed (`install_bootprobe.sh` done, `kbl collect` works).
- Phase 2 testbed verified (`kbl experiment run` drains a queue).
- Target packages: `busctl` (systemd), `dbus-send` (dbus-bin), `mate-terminal`.
  Check: `ssh kbl@kbl-target.local 'command -v busctl dbus-send mate-terminal'`.
- The kbl account password uses ONLY lowercase letters and digits (spec section 10);
  change it first if needed: `passwd`.

## 2. Build and install

On the target (native build avoids cross toolchains):

    git clone https://github.com/LanceGan/openkylin.git && cd openkylin
    git checkout worktree-kylinbootlab-phase1
    cargo build --release -p kbl-bootprobe
    sudo bash scripts/target/install_observer.sh \
        target/release/kbl-bootprobe kbl <password>
    history -c   # the password appeared on the command line

The installer leaves the observer ENABLED (marker present). Disable at any
time without sudo: `rm /var/lib/kylinbootlab/observe/enabled`.

## 3. First supervised observation

From the controller (VMware example):

    & 'F:\VMware\VMware Workstation\vmrun.exe' -T ws reset "<path>.vmx" hard

Watch on the target console or a second SSH session after boot:

    ssh kbl@kbl-target.local 'cat /var/lib/kylinbootlab/observe/current.jsonl'
    ssh kbl@kbl-target.local 'cat /var/lib/kylinbootlab/observe/done'
    ssh kbl@kbl-target.local 'cat /proc/sys/kernel/random/boot_id'

Expect: `observer_started` then `greeter_started` then `unit_active` x3 then
`greeter_ready` then `login_injected` then `session_opened` then probe events then
`usable`; the done marker equals the current boot_id; the greeter visibly
logged in by itself (no autologin configured -- check
`/etc/lightdm/lightdm.conf` has no `autologin-user`).

## 4. Pattern and process-list refinement (expected on first deploy)

All matchers are config, not code -- tune without recompiling:

1. Greeter signals: `ssh kbl@kbl-target.local \
   'journalctl -b 0 --no-pager | grep -inE "lightdm|greeter" | head -40'`.
   If `greeter_ready` fires too early (first greeter log line vs UI painted),
   set `greeter_ready_pattern` in `/etc/kylinbootlab/observe.toml` to a
   later, paint-time message fragment.
2. Desktop process group (needs one real login):
   `ssh kbl@kbl-target.local 'ps -e -o comm= | grep -i ukui | sort -u'`,
   then set `desktop_processes` in observe.toml (sudo).
3. The session probe cannot read root-0600 observe.toml and runs with
   built-in defaults (empty process list). To feed it the refined list:
   `sudo chgrp kbl /etc/kylinbootlab/observe.toml` and
   `sudo chmod 0640 /etc/kylinbootlab/observe.toml`.
   Trade-off: the kbl group can then read the kbl password -- acceptable on
   a dedicated lab target (it is kbl's own password); document if not.
4. Sentinel: keep `mate-terminal` unless missing; any AT-SPI-visible app
   with a fast first window works.

## 5. Collect and report

    uv run kbl collect --target kbl@kbl-target.local
    uv run kbl report <run-id>

`derived/metrics.json` gains a `readiness` block; `reports/baseline.html`
shows the "User-perceived readiness" timeline. Runs without the observer
show `status: absent` -- never an error.

## 6. Calibration (spec section 7)

    uv run kbl calibrate --target kbl@<ip> --backend vix \
        --vmx-path "<path>.vmx" --per-group 10

Runs calib-bare (marker removed) then calib-benchmark (marker present),
10 warm-reset boots each, prints medians + deltas, writes
`var/calibration-report.json`, exits 1 unless BOTH `os_total_ns` and
`graphical_target_from_t0_ns` median deltas are < 1%.

Notes:
- Calibration boots are guest resets, not snapshot restores -- a restore
  would revert the enabled marker (see `calibrate.py` docstring). Journald
  growth over 20 boots affects both groups equally; medians absorb it.
- Diagnostic group (manual, recorded only, never gated; results are for
  Phase 4 analysis only). Unlike `kbl calibrate`, a raw `kbl experiment
  run` powers off and restores the `baseline` snapshot before EVERY boot,
  so a live edit of observe.toml would be silently reverted on the first
  restore -- the mode edit must be baked into the snapshot first:
  1. At the VM console (or SSH while the guest is up):
     `sudo sed -i 's/^mode = "benchmark"/mode = "diagnostic"/' /etc/kylinbootlab/observe.toml`
  2. Re-create the baseline snapshot AFTER the edit, so every restore
     boots in diagnostic mode:
     `vmrun -T ws stop "<path>.vmx" soft`, then
     `vmrun -T ws deleteSnapshot "<path>.vmx" baseline`, then
     `vmrun -T ws snapshot "<path>.vmx" baseline`.
  3. Queue and run with a dedicated queue file (NEVER the default
     `var/experiments.jsonl`) and an explicit VMX path (the vix backend
     raises without one):
     `uv run kbl experiment queue --profile calib-diagnostic --count 10 --queue-file var/diagnostic.jsonl`, then
     `uv run kbl experiment run --target kbl@<ip> --backend vix --vmx-path "<path>.vmx" --queue-file var/diagnostic.jsonl`.
  4. Revert: sed the mode back to `"benchmark"`, then repeat step 2 so
     the baseline snapshot is benchmark-mode again.
  Diagnostic runs are labeled `mode=diagnostic` in their event stream and
  excluded from formal statistics.

## 7. Wrong-password drill (error-path acceptance)

    sudo sed -i 's/^password = .*/password = "wrongpw1"/' /etc/kylinbootlab/observe.toml
    # reboot, then:
    ssh kbl@kbl-target.local 'tail -3 /var/lib/kylinbootlab/observe/current.jsonl'

Expect an `error` event ("no session within 30s of injection"), a done
marker (bundle still collectable), NO second injection attempt, and no
account lockout (`sudo pam_tally2 --user kbl` or `faillock --user kbl`).
Restore the real password afterwards and verify one clean run.

## 8. Troubleshooting

| Symptom | Likely cause | Fix |
|---|---|---|
| No `current.jsonl` after boot | marker absent or unit disabled | `touch .../observe/enabled`; `systemctl status kbl-observe` |
| `error: uinput self-check failed` | not running as root / no uinput | unit must be the installed one; `ls -l /dev/uinput` |
| `observer_timeout` at 90 s, greeter events present | injection gate blocked: check which of units/greeter_ready/uinput is missing in the stream | tune `greeter_ready_pattern`; `systemctl is-active dbus NetworkManager lightdm` |
| `session_opened` never appears, password correct | greeter focus/keymap | verify manually typing works at greeter; keep password [a-z0-9] |
| Probe events missing, `observer_timeout` after 120 s | usable-probe not started | autostart entry in `~kbl/.config/autostart/`; check `~/.xsession-errors` |
| `atspi_unavailable` in details | AT-SPI bus not up | acceptable degraded mode; check `busctl --user` inside the session |
| Stale `done` ignored by controller | boot_id mismatch (by design) | none -- that is the staleness protection working |

## 9. Acceptance checklist (Phase 3 exit)

- [ ] Full chain on real openKylin: cold boot, auto login, all four
      T-points present and monotonically increasing.
- [ ] `kbl report` renders the readiness timeline; absent-observer run
      degrades to `status: absent`.
- [ ] `kbl calibrate` 10+10 completes; benchmark < 1% on both medians.
- [ ] Wrong-password drill: graceful `error` + timeout, no lockout, no
      re-injection.
- [ ] Refinements recorded in observe.toml and committed to the runbook.
