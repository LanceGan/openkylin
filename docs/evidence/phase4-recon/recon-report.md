# Phase 4 Reconnaissance Report

**Date:** 2026-07-19
**Target:** openKylin 2.0 SP2 (systemd 255)

---

## 1. Critical Path (systemd-analyze critical-chain)

**graphical.target reached: 3.129s** (userspace)

```
The time when unit became active or started is printed after the "@" character.
The time the unit took to start is printed after the "+" character.

graphical.target @3.129s
鈹斺攢multi-user.target @3.129s
  鈹斺攢strongswan-starter.service @2.986s
    鈹斺攢network-online.target @2.977s
      鈹斺攢NetworkManager-wait-online.service @2.274s +703ms
        鈹斺攢NetworkManager.service @1.725s +546ms
          鈹斺攢dbus.service @1.464s +101ms
            鈹斺攢basic.target @1.444s
              鈹斺攢sockets.target @1.444s
                鈹斺攢uuidd.socket @1.444s
                  鈹斺攢sysinit.target @1.436s
                    鈹斺攢systemd-resolved.service @1.383s +52ms
                      鈹斺攢systemd-tmpfiles-setup.service @1.338s +34ms
                        鈹斺攢local-fs.target @1.329s
                          鈹斺攢run-user-1000.mount @3.138s
                            鈹斺攢swap.target @601ms
                              鈹斺攢dev-disk-by\x2duuid-268e8788\x2d6158\x2d413a\x2d904d\x2dbcc8163add5c.swap @580ms +20ms
                                鈹斺攢dev-disk-by\x2duuid-268e8788\x2d6158\x2d413a\x2d904d\x2dbcc8163add5c.device @574ms

```

## 2. Service Blame (Top 10)

| Rank | Service | Duration | On Critical Path? |
|------|---------|----------|-------------------|
| 3 | org.kylin.kaiming.service | 3.225s | ⚠️  After graphical.target |
| 4 | biometric-authentication.service | 706ms | ❌ |
| 5 | NetworkManager-wait-online.service | 703ms | ✅ |
| 6 | NetworkManager.service | 546ms | ✅ |
| 7 | accounts-daemon.service | 516ms | ❌ |
| 8 | udisks2.service | 408ms | ❌ |
| 9 | dev-sda5.device | 335ms | ❌ |
| 10 | loadcpufreq.service | 327ms | ❌ |
| 11 | kysdk-conf2.service | 318ms | ❌ |
| 12 | lightdm.service | 273ms | ❌ |

## 3. Dependency Graph

- **Total edges:** 1651 (all After= ordering)

- **Unique units:** 333

- **Edge file:** `docs/evidence/phase4-recon/full-order.dot` (1651 lines)

- **SVG plot:** `docs/evidence/phase4-recon/boot-plot.svg` (205 KB)


### Top Bottleneck Candidates (by After-in-degree)

| Unit | Services waiting after it |
|------|--------------------------|
| system.slice | 196 |
| systemd-journald.socket | 187 |
| sysinit.target | 114 |
| basic.target | 88 |
| -.mount | 77 |
| var.mount | 28 |
| dbus.socket | 23 |
| systemd-remount-fs.service | 20 |
| local-fs.target | 18 |
| var-lib.mount | 18 |

## 4. Key Insight: kylin-kaiming Service

**3.225s** — but ordered _after_ graphical.target.  Not on the systemd critical path, yet the single longest service.  Adds desktop-usable latency because the desktop session waits for `WantedBy=graphical.target` services.

- Unit file: `After=graphical.target` (deliberate late start)

- Type: dbus-activated daemon (`/opt/kaiming-tools/bin/kaiming-system-dbus`)

- Restart: always (why 3.2s restart? investigate dbus activation race)

## 5. Key Insight: NetworkManager-wait-online.service

**703ms** on critical path.  Blocks `network-online.target` which gates `strongswan-starter.service` → `multi-user.target`.  On a VM with one NIC, this wait is unnecessary — the network is available much earlier.

## 6. Key Insight: biometric-authentication.service

**706ms** — likely a no-op on a VM with no biometric hardware.  If on the login critical path, a candidate for masking.


## 7. Phase 4 Design Implications

- DOT output is the right input format: 1651 edges, parsable, captures all ordering

- `systemd-analyze critical-chain` provides the gold-standard timing trace

- `systemd-analyze blame` provides per-unit self-time (excl. dependencies)

- `systemd-analyze plot` SVG is available for human visualization

- **Missing for causal engine:** Runtime blocking (CPU/IO contention), journal merge points, P-idle vs P-busy annotation

- **Readiness events (Phase 3) bridge the gap:** the observer's `unit_active`/`greeter_*`/`session_opened` events align systemd time with user-perceived time

- **Graphical target reached (3.1s) vs desktop usable (78s):** the 75s gap is dominated by GUI services, PAM, autostart — systemd analysis alone is insufficient beyond 3.1s
