// Static evidence imports — all JSON bundled at build time.
// Updated 2026-07-25 with cross-distro phase results.

import calibrationReport from "../../../docs/evidence/calibration-report.json";
import phase5MaskBiometric from "../../../docs/evidence/phase5-mask-biometric-verdict.json";
import phase5SocketNmWait from "../../../docs/evidence/phase5-socket-nm-wait-verdict.json";
import phase6InitramfsTrim from "../../../docs/evidence/phase6/initramfs-trim-verdict.json";

// Cross-distro ABBA results (inline — avoids Vite import issues with new JSON files)
const ubuntuStrongswan = {
  plan_id: "mask-strongswan (Ubuntu 22.04)",
  verdict: "REJECTED",
  statistics: {
    a_median_ns: 42411000000, b_median_ns: 42378000000,
    median_improvement_ns: 33000000, median_improvement_pct: 0.65,
    ci_lower_95_ns: -217500000, ci_upper_95_ns: 65500000,
    p95_a_ns: 42411000000, p95_b_ns: 42411000000,
    paired_diffs_ns: []
  },
  functional_passed: true, failed_gates: [], recommendation: ""
};

const fedoraStrongswan = {
  plan_id: "mask-strongswan (Fedora 41)",
  verdict: "REJECTED",
  statistics: {
    a_median_ns: 9654000000, b_median_ns: 9045000000,
    median_improvement_ns: 609000000, median_improvement_pct: 6.88,
    ci_lower_95_ns: -8429000000, ci_upper_95_ns: 2931500000,
    p95_a_ns: 9654000000, p95_b_ns: 9654000000,
    paired_diffs_ns: []
  },
  functional_passed: true, failed_gates: [], recommendation: ""
};

const fedoraDracutTrim = {
  plan_id: "dracut initramfs trim (Fedora 41)",
  verdict: "REJECTED",
  statistics: {
    a_median_ns: 9654000000, b_median_ns: 7560500000,
    median_improvement_ns: 2093500000, median_improvement_pct: 18.99,
    ci_lower_95_ns: -8179500000, ci_upper_95_ns: -37500000,
    p95_a_ns: 9654000000, p95_b_ns: 9654000000,
    paired_diffs_ns: []
  },
  functional_passed: true, failed_gates: [], recommendation: ""
};

// Readiness fixture
const readinessFixture = [
  { schema_version: 1, monotonic_ns: 3000000000, kind: "observer_started", detail: "mode=benchmark dm=lightdm.service", source: "probe" },
  { schema_version: 1, monotonic_ns: 6613388000, kind: "greeter_started", detail: "lightdm start begin", source: "journald" },
  { schema_version: 1, monotonic_ns: 7000000000, kind: "unit_active", detail: "dbus.service", source: "systemd" },
  { schema_version: 1, monotonic_ns: 7100000000, kind: "unit_active", detail: "NetworkManager.service", source: "systemd" },
  { schema_version: 1, monotonic_ns: 7200000000, kind: "unit_active", detail: "lightdm.service", source: "systemd" },
  { schema_version: 1, monotonic_ns: 8500000000, kind: "greeter_ready", detail: "ukui-greeter first output", source: "journald" },
  { schema_version: 1, monotonic_ns: 9000000000, kind: "login_injected", detail: "password+enter via uinput", source: "probe" },
  { schema_version: 1, monotonic_ns: 11500000000, kind: "session_opened", detail: "session opened for user kbl", source: "journald" },
  { schema_version: 1, monotonic_ns: 16000000000, kind: "desktop_process_up", detail: "ukui-panel", source: "probe" },
  { schema_version: 1, monotonic_ns: 16500000000, kind: "atspi_desktop_ready", detail: "3 desktop children", source: "atspi" },
  { schema_version: 1, monotonic_ns: 16600000000, kind: "sentinel_launched", detail: "mate-terminal", source: "probe" },
  { schema_version: 1, monotonic_ns: 18100000000, kind: "sentinel_window_shown", detail: "mate-terminal window", source: "atspi" },
  { schema_version: 1, monotonic_ns: 18100000000, kind: "usable", detail: "all three conditions met", source: "probe" },
];

const abbaResults = [
  { ...phase5MaskBiometric, phase: "Phase 5 (openKylin)" },
  { ...phase5SocketNmWait, phase: "Phase 5 (openKylin)" },
  { ...phase6InitramfsTrim, phase: "Phase 6 (openKylin)" },
  { ...ubuntuStrongswan, phase: "Phase 10 (Ubuntu 22.04)", plan_id: "mask-strongswan", distribution: "Ubuntu 22.04 LTS" },
  { ...fedoraStrongswan, phase: "Phase 10 (Fedora 41)", plan_id: "mask-strongswan", distribution: "Fedora 41" },
  { ...fedoraDracutTrim, phase: "Phase 10 (Fedora 41)", plan_id: "dracut initramfs trim", distribution: "Fedora 41" },
];

export const evidence = {
  calibration: calibrationReport,
  abbaResults,
  readinessEvents: readinessFixture,
  // Cross-distro baseline summary
  crossDistro: {
    openKylin: { os_total_s: 28.306, kernel_s: 4.726, userspace_s: 23.580, max_bottleneck: "kaiming.service (20.2s)", dm: "LightDM", nodes: 343, edges: 1714 },
    ubuntu: { os_total_s: 42.411, kernel_s: 2.468, userspace_s: 39.943, max_bottleneck: "plymouth-quit-wait (19.8s)", dm: "GDM", nodes: 330, edges: 1600 },
    fedora: { os_total_s: 9.654, kernel_s: 1.206, initrd_s: 1.397, userspace_s: 7.051, max_bottleneck: "plymouth-quit-wait (3.1s)", dm: "GDM", nodes: 290, edges: 1200 },
  },
  agentSkills: [
    { name: "Trace Analyst", description: "Locates anomalous paths and cross-boot volatility in systemd causal graphs." },
    { name: "Source Investigator", description: "Inspects systemd unit files and openKylin package data for actionable changes." },
    { name: "Experiment Designer", description: "Forms hypotheses and designs minimal A/B experiments with falsification conditions." },
    { name: "Safety Critic", description: "Reviews optimization plans for functional regression and portability risks." },
  ],
  benchmarkCases: [
    { id: "B1", name: "dbus exclusive delay", status: "pass" },
    { id: "B2", name: "bluetooth large slack", status: "pass" },
    { id: "B3", name: "kaiming stagger positive", status: "pass" },
    { id: "B4", name: "socket-nm-wait regression", status: "pass" },
    { id: "B5", name: "dbus+lightdm combined", status: "fail" },
  ],
  bottlenecks: [
    { node: "org.kylin.kaiming.service", blame_ns: 20244000000, slack_ns: 0, on_critical_path: true },
    { node: "biometric-authentication.service", blame_ns: 704000000, slack_ns: 0, on_critical_path: false },
    { node: "NetworkManager-wait-online.service", blame_ns: 738000000, slack_ns: 0, on_critical_path: false },
    { node: "NetworkManager.service", blame_ns: 559000000, slack_ns: 0, on_critical_path: true },
    { node: "accounts-daemon.service", blame_ns: 606000000, slack_ns: 0, on_critical_path: false },
    { node: "kysdk-conf2.service", blame_ns: 477000000, slack_ns: 0, on_critical_path: false },
    { node: "lightdm.service", blame_ns: 273000000, slack_ns: 0, on_critical_path: true },
  ],
};
