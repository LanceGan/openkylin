import subprocess
from collections.abc import Sequence
from pathlib import Path
from typing import Protocol
from uuid import UUID

from kylinbootlab.store import RunStore


class RemoteCollectionError(RuntimeError):
    pass


class Runner(Protocol):
    def run(self, args: Sequence[str]) -> subprocess.CompletedProcess[str]: ...


class SubprocessRunner:
    def run(self, args: Sequence[str]) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            list(args),
            check=False,
            capture_output=True,
            text=True,
        )


def ssh_snapshot_command(target: str, run_id: UUID) -> list[str]:
    return [
        "ssh",
        "-o",
        "BatchMode=yes",
        "-o",
        "ConnectTimeout=15",
        target,
        "sudo",
        "/usr/local/sbin/kbl-capture-run",
        str(run_id),
    ]


def scp_command(target: str, run_id: UUID, incoming_root: Path) -> list[str]:
    return [
        "scp",
        "-o",
        "BatchMode=yes",
        "-o",
        "ConnectTimeout=15",
        "-r",
        f"{target}:/var/lib/kylinbootlab/runs/{run_id}",
        str(incoming_root),
    ]


def collect_target_run(
    *,
    target: str,
    run_id: UUID,
    incoming_root: Path,
    store: RunStore,
    runner: Runner,
) -> Path:
    incoming_root.mkdir(parents=True, exist_ok=True)
    bundle = incoming_root / str(run_id)
    if bundle.exists():
        raise RemoteCollectionError(f"incoming bundle already exists: {bundle}")

    snapshot = runner.run(ssh_snapshot_command(target, run_id))
    copied = runner.run(scp_command(target, run_id, incoming_root))
    if copied.returncode != 0:
        detail = copied.stderr.strip()
        if snapshot.returncode != 0:
            detail = f"scp failed (snapshot exited {snapshot.returncode}): {detail}\nsnapshot stderr: {snapshot.stderr.strip()}"
        raise RemoteCollectionError(f"scp failed: {detail}")

    run_path = store.ingest(bundle)
    if snapshot.returncode != 0:
        raise RemoteCollectionError(
            f"target snapshot failed but diagnostic bundle was imported at {run_path}: "
            f"{snapshot.stderr.strip()}"
        )
    return run_path
