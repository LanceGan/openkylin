"""Run one fault corpus case: inject → boot → analyze → verify → cleanup."""
import subprocess
import sys
import json
from pathlib import Path
from uuid import UUID

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from kylinbootlab.systemd import parse_systemd_blame
from kylinbootlab.capture import load_command_capture
from kylinbootlab.store import RunStore
from kylinbootlab.readiness import parse_events
from kylinbootlab.analysis.builder import CausalGraphBuilder
from kylinbootlab.analysis.bottleneck import rank_bottlenecks
from kylinbootlab.analysis.critical_path import critical_path

TARGET = "kbl@192.168.19.128"
VMX = r"F:\VMware\Vitural machine\openkylin\openkylin.vmx"
VMRUN = r"F:\VMware\VMware Workstation\vmrun.exe"
DATA_ROOT = Path("var/runs")


def fetch_dot() -> str:
    r = subprocess.run(
        ["ssh", "-o", "BatchMode=yes", TARGET, "/usr/local/bin/kbl-dot-capture"],
        capture_output=True, text=True, timeout=15,
    )
    assert r.returncode == 0 and "digraph" in r.stdout, f"DOT failed: {r.stderr[:200]}"
    return r.stdout


def analyze(run_id: UUID):
    store = RunStore(Path(DATA_ROOT))
    manifest = store.load_manifest(run_id)
    dot_text = fetch_dot()

    blame_cap = load_command_capture(store.run_path(run_id), manifest, "systemd-blame")
    blame_units = parse_systemd_blame(blame_cap.stdout)

    try:
        r_cap = load_command_capture(store.run_path(run_id), manifest, "readiness-events")
        events = parse_events(r_cap.stdout)
    except Exception:
        events = []

    graph = CausalGraphBuilder().build(dot_text, blame_units, events)
    sink = "usable" if any(n.layer == "readiness" for n in graph.nodes.values()) else "graphical.target"
    cp = critical_path(graph, sink)
    bottlenecks = rank_bottlenecks(graph, sink=sink, top_k=5)

    print(f"  Nodes: {len(graph.nodes)}  Edges: {len(graph.edges)}  Sink: {sink}")
    print(f"  CP: {len(cp)} nodes")
    for b in bottlenecks:
        print(f"  {b.rank}. {b.node}: score={b.score:.3f} blame={b.blame_ns/1e9:.3f}s on_cp={b.on_critical_path} sl={b.slack_ns/1e9:.3f}s")
    return {b.node: b.rank for b in bottlenecks}

def inject(case_id: int):
    """Execute inject commands via SSH."""
    cmd_map = {
        1: [ # Fake dep on NM
            'echo "[Unit]\nDescription=kbl-fault\n" | sudo tee /etc/systemd/system/foo-slow.service',
            'sudo mkdir -p /etc/systemd/system/NetworkManager.service.d',
            'echo "[Unit]\nAfter=foo-slow.service" | sudo tee /etc/systemd/system/NetworkManager.service.d/kbl-fault.conf',
            'sudo systemctl daemon-reload'
        ],
        2: [ # dbus delay
            'sudo mkdir -p /etc/systemd/system/dbus.service.d',
            'echo "[Service]\nExecStartPre=/bin/sleep 3" | sudo tee /etc/systemd/system/dbus.service.d/kbl-fault.conf',
            'sudo systemctl daemon-reload'
        ],
        3: [ # bluetooth delay (no-op, large slack)
            'sudo mkdir -p /etc/systemd/system/ukui-bluetooth.service.d',
            'echo "[Service]\nExecStartPre=/bin/sleep 5" | sudo tee /etc/systemd/system/ukui-bluetooth.service.d/kbl-fault.conf',
            'sudo systemctl daemon-reload'
        ],
        4: [ # lightdm delay
            'sudo mkdir -p /etc/systemd/system/lightdm.service.d',
            'echo "[Service]\nExecStartPre=/bin/sleep 2" | sudo tee /etc/systemd/system/lightdm.service.d/kbl-fault.conf',
            'sudo systemctl daemon-reload'
        ],
        5: [ # dbus 2s + lightdm 2s (combined)
            'sudo mkdir -p /etc/systemd/system/dbus.service.d',
            'echo "[Service]\nExecStartPre=/bin/sleep 2" | sudo tee /etc/systemd/system/dbus.service.d/kbl-fault.conf',
            'sudo mkdir -p /etc/systemd/system/lightdm.service.d',
            'echo "[Service]\nExecStartPre=/bin/sleep 2" | sudo tee /etc/systemd/system/lightdm.service.d/kbl-fault.conf',
            'sudo systemctl daemon-reload'
        ],
    }
    cmds = cmd_map[case_id]
    for cmd in cmds:
        r = subprocess.run(
            ["ssh", "-o", "BatchMode=yes", TARGET, f"echo '12345678' | sudo -S bash -c '{cmd}'"],
            capture_output=True, text=True, timeout=15,
        )
        if r.returncode != 0:
            print(f"  WARNING: inject cmd failed: {cmd[:60]} -> {r.stderr[:100]}")
    print(f"  Injected case {case_id}")

def cleanup(case_id: int):
    cleanup_map = {
        1: "sudo rm -f /etc/systemd/system/foo-slow.service /etc/systemd/system/NetworkManager.service.d/kbl-fault.conf",
        2: "sudo rm -f /etc/systemd/system/dbus.service.d/kbl-fault.conf",
        3: "sudo rm -f /etc/systemd/system/ukui-bluetooth.service.d/kbl-fault.conf",
        4: "sudo rm -f /etc/systemd/system/lightdm.service.d/kbl-fault.conf",
        5: "sudo rm -f /etc/systemd/system/dbus.service.d/kbl-fault.conf /etc/systemd/system/lightdm.service.d/kbl-fault.conf",
    }
    cmd = f"{cleanup_map[case_id]} && sudo systemctl daemon-reload"
    subprocess.run(
        ["ssh", "-o", "BatchMode=yes", TARGET, f"echo '12345678' | sudo -S bash -c '{cmd}'"],
        capture_output=True, text=True, timeout=15,
    )
    print(f"  Cleaned up case {case_id}")


if __name__ == "__main__":
    case_id = int(sys.argv[1]) if len(sys.argv) > 1 else 1
    run_id = UUID(sys.argv[2]) if len(sys.argv) > 2 else UUID(f"00000000-0000-4000-a000-{case_id:012d}")
    print(f"\n=== FAULT CORPUS CASE {case_id} ===\n")

    inject(case_id)
    # Cold reboot
    subprocess.run([VMRUN, "-T", "ws", "reset", VMX, "hard"], capture_output=True, timeout=30)

    # Wait for observer done
    import time
    for i in range(1, 48):
        r2 = subprocess.run(["ssh", "-o", "BatchMode=yes", "-o", "ConnectTimeout=5", TARGET,
            "cat /var/lib/kylinbootlab/observe/done 2>/dev/null"], capture_output=True, text=True, timeout=10)
        if r2.stdout.strip():
            break
        time.sleep(10)
    print(f"  Observer done after {i*10}s")

    # Collect snapshot
    subprocess.run(["ssh", "-o", "BatchMode=yes", TARGET,
        f"/usr/local/bin/kbl-bootprobe snapshot --run-id {run_id} --output /var/lib/kylinbootlab/runs/{run_id}"],
        capture_output=True, text=True, timeout=30)
    subprocess.run(["scp", "-r", "-o", "BatchMode=yes", f"{TARGET}:/var/lib/kylinbootlab/runs/{run_id}",
        str(Path("var/incoming") / str(run_id))], capture_output=True, timeout=60)

    # Ingest
    from importlib import import_module
    ingest_module = import_module("kylinbootlab.cli")
    # Use direct store ingest
    store = RunStore(Path(DATA_ROOT))
    store.ingest(Path("var/incoming") / str(run_id))
    print(f"  Ingested run {run_id}")

    # Analyze
    ranking = analyze(run_id)
    cleanup(case_id)
    print(f"\n  Ranking: {json.dumps(ranking, indent=2)}")
