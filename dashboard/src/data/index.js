// Static evidence imports — all JSON bundled at build time.

import calibrationReport from "../../../docs/evidence/calibration-report.json";
import phase5MaskBiometric from "../../../docs/evidence/phase5-mask-biometric-verdict.json";
import phase5SocketNmWait from "../../../docs/evidence/phase5-socket-nm-wait-verdict.json";
import phase6InitramfsTrim from "../../../docs/evidence/phase6/initramfs-trim-verdict.json";

// Readiness fixture (inline — avoids Vite ?raw import issues)
const readinessFixture = [
  { schema_version: 1, monotonic_ns: 3000000000, kind: "observer_started", detail: "mode=benchmark", source: "probe" },
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
  { ...phase5MaskBiometric, phase: "Phase 5" },
  { ...phase5SocketNmWait, phase: "Phase 5" },
  { ...phase6InitramfsTrim, phase: "Phase 6" },
];

export const evidence = {
  calibration: calibrationReport,
  abbaResults,
  readinessEvents: readinessFixture,
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
    { node: "org.kylin.kaiming.service", blame_ns: 3225000000, slack_ns: 0, on_critical_path: false },
    { node: "biometric-authentication.service", blame_ns: 706000000, slack_ns: 200000000, on_critical_path: false },
    { node: "NetworkManager-wait-online.service", blame_ns: 703000000, slack_ns: 0, on_critical_path: true },
    { node: "NetworkManager.service", blame_ns: 546000000, slack_ns: 0, on_critical_path: true },
    { node: "accounts-daemon.service", blame_ns: 516000000, slack_ns: 300000000, on_critical_path: false },
    { node: "dbus.service", blame_ns: 101000000, slack_ns: 0, on_critical_path: true },
    { node: "lightdm.service", blame_ns: 273000000, slack_ns: 0, on_critical_path: true },
  ],
};
