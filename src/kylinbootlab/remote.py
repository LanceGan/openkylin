import subprocess
from collections.abc import Sequence
from pathlib import Path
from typing import Protocol
from uuid import UUID

from kylinbootlab.store import RunStore


class RemoteCollectionError(RuntimeError):
    """Raised when SSH collection fails — partial diagnostic data may be saved."""


class Runner(Protocol):
    """Injection point for test doubles — must match subprocess.run semantics."""

    def run(self, args: Sequence[str]) -> subprocess.CompletedProcess[str]: ...


class SubprocessRunner:
    """Real subprocess runner with a per-call timeout (default 60 s)."""

    def __init__(self, timeout: int = 60) -> None:
        self.timeout = timeout

    def run(self, args: Sequence[str]) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            list(args),
            check=False,
            capture_output=True,
            text=True,
            timeout=self.timeout,
        )


# Shared SSH hardening — applied to both ssh and scp commands.
_SSH_OPTIONS = [
    "-o", "BatchMode=yes",
    "-o", "ConnectTimeout=15",
    "-o", "ServerAliveInterval=15",
    "-o", "ServerAliveCountMax=3",
]

# Remote paths — override via *probe_cmd* / *remote_dir* parameters.
_DEFAULT_PROBE_BIN = "/usr/local/bin/kbl-bootprobe"
_DEFAULT_REMOTE_DIR = "/var/lib/kylinbootlab/runs"


def ssh_snapshot_command(
    target: str,
    run_id: UUID,
    *,
    probe_cmd: str = _DEFAULT_PROBE_BIN,
    remote_dir: str = _DEFAULT_REMOTE_DIR,
) -> list[str]:
    """Build the ssh command that triggers a snapshot on the target.

    Runs ``<probe_cmd> snapshot --run-id <uuid> --output <remote_dir>/<uuid>``.
    Uses BatchMode=yes so ssh never prompts interactively.
    On openKylin SP2 (ostree) the probe binary is called directly without sudo.
    """
    run_output = f"{remote_dir.rstrip('/')}/{run_id}"
    return [
        "ssh",
        *_SSH_OPTIONS,
        target,
        probe_cmd,
        "snapshot",
        "--run-id", str(run_id),
        "--output", run_output,
    ]


def scp_command(
    target: str,
    run_id: UUID,
    incoming_root: Path,
    *,
    remote_dir: str = _DEFAULT_REMOTE_DIR,
) -> list[str]:
    """Build the scp command that copies the snapshot bundle back to the controller.

    The source path is ``<remote_dir>/<run_id>`` on the target;
    the destination is the untrusted incoming staging area on the controller.
    """
    run_output = f"{remote_dir.rstrip('/')}/{run_id}"
    return [
        "scp",
        *_SSH_OPTIONS,
        "-r",
        f"{target}:{run_output}",
        str(incoming_root),
    ]


def collect_target_run(
    *,
    target: str,
    run_id: UUID,
    incoming_root: Path,
    store: RunStore,
    runner: Runner,
    probe_cmd: str = _DEFAULT_PROBE_BIN,
    remote_dir: str = _DEFAULT_REMOTE_DIR,
) -> Path:
    """Run snapshot on the target, copy the bundle back, and import into *store*.

    1. Trigger the snapshot via ssh.
    2. Copy the bundle via scp into *incoming_root*.
    3. Ingest the bundle into the immutable RunStore.

    If the snapshot fails, the bundle is still imported for diagnostics,
    then ``RemoteCollectionError`` is raised.  If the scp fails, no run
    is created.
    """
    if target.startswith("-"):
        raise RemoteCollectionError(
            f"target must not start with '-', got: {target!r}"
        )

    incoming_root.mkdir(parents=True, exist_ok=True)
    bundle = incoming_root / str(run_id)
    if bundle.exists():
        raise RemoteCollectionError(f"incoming bundle already exists: {bundle}")

    try:
        snapshot = runner.run(ssh_snapshot_command(
            target, run_id, probe_cmd=probe_cmd, remote_dir=remote_dir,
        ))
        copied = runner.run(scp_command(
            target, run_id, incoming_root, remote_dir=remote_dir,
        ))
    except subprocess.TimeoutExpired as exc:
        raise RemoteCollectionError(
            f"remote command timed out after {exc.timeout}s: {exc.cmd}"
        ) from exc
    if copied.returncode != 0:
        detail = copied.stderr.strip()
        if snapshot.returncode != 0:
            detail = (
                f"scp failed (snapshot exited {snapshot.returncode}): "
                f"{detail}\nsnapshot stderr: {snapshot.stderr.strip()}"
            )
        raise RemoteCollectionError(f"scp failed: {detail}")

    run_path = store.ingest(bundle)
    if snapshot.returncode != 0:
        raise RemoteCollectionError(
            f"target snapshot failed but diagnostic bundle was imported at {run_path}: "
            f"{snapshot.stderr.strip()}"
        )
    return run_path
