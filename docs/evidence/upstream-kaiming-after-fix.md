# Upstream Patch Note: org.kylin.kaiming.service After=graphical.target

**Project:** KylinBootLab — openKylin Boot Performance Analysis  
**Finding:** `org.kylin.kaiming.service` causes unnecessary boot delay  
**Date:** 2026-07-22  

## Issue

`org.kylin.kaiming.service` currently declares:

```ini
[Unit]
After=graphical.target

[Service]
Type=dbus
BusName=org.kylin.kaiming
ExecStart=/opt/kaiming-tools/bin/kaiming-system-dbus
Restart=always
RestartSec=3

[Install]
WantedBy=graphical.target
```

The `After=graphical.target` constraint forces kaiming to wait until LightDM, UKUI greeter, and
all graphical services have fully started before it begins its own initialization.  

**Measured impact:** kaiming takes a median 1.427s to initialise (n=176 cold boots, range 0.27–30.25s).
The `Restart=always` + `RestartSec=3` pattern suggests a D-Bus activation race that
occasionally causes restart loops (worst observed boot: 30.2s).

## Root Cause

Kaiming is a **D-Bus activated daemon** (`Type=dbus`, `BusName=org.kylin.kaiming`).  It does
not need the full graphical target — it needs D-Bus (which is available at `basic.target`) and
any desktop services that *consume* its D-Bus interface.

The `After=graphical.target` constraint delays kaiming's startup by 3.1s (the time from
systemd init to graphical.target) *plus* the time kaiming takes to become ready after starting.

## Proposed Fix

Change the ordering constraint from `After=graphical.target` to `After=multi-user.target`:

```ini
[Unit]
After=multi-user.target
```

This moves kaiming's startup point ~3 seconds earlier (to coincide with NetworkManager,
D-Bus, and other multi-user services), allowing it to run in parallel with the greeter/desktop
startup rather than after it.

## Expected Benefit

- kaiming completes its initialization concurrently with LightDM and UKUI greeter
- Worst-case restart-loop spikes are limited to the `RestartSec=3` × `StartLimitBurst` cap
- `graphical.target` critical path is shortened by 1.4s (kaiming's blame, now parallel)

## Verification

A drop-in override (`/etc/systemd/system/org.kylin.kaiming.service.d/kbl-phase6.conf`)
with `After=multi-user.target` was tested in the KylinBootLab ABBA protocol (Phase 6,
`kaiming-stagger` candidate).  Results: +3.85% boot-time improvement (direction correct,
bootstrap CI crossed zero with N=16 — larger N needed for statistical significance).
No functional regression observed — kaiming D-Bus service available after boot.

## D-Bus Activation Race (Follow-up)

The `Restart=always` + `RestartSec=3` pattern, combined with the observed 0.27s–30.25s
blame range, strongly suggests a D-Bus activation race: when kaiming starts before its
D-Bus consumers are ready, it may exit and be restarted.  An `ExecStartPost=/bin/sleep 1`
or a D-Bus `Activates=` dependency on the consuming service would eliminate the race
and remove the need for `Restart=always` entirely — this is a deeper fix for the
openKylin packaging team to investigate.

## Data Source

- 176 recorded cold boots (KylinBootLab Phase 1–6 `RunStore`)
- `systemd-analyze blame` results, median 1.427s for `org.kylin.kaiming.service`
- Phase 4 causal graph: slack=0, on the *effective* critical path (delayed after graphical)
- Phase 6 ABBA experiment `phase6-kaiming-stagger`
