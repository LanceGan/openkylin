import shutil
import subprocess
from collections.abc import Sequence
from pathlib import Path

import pytest

from kylinbootlab.remote import (
    RemoteCollectionError,
    collect_target_run,
    scp_command,
    ssh_snapshot_command,
)
from kylinbootlab.store import RunStore
from tests.helpers import RUN_ID, create_probe_bundle


class FakeRunner:
    def __init__(
        self,
        bundle: Path,
        *,
        snapshot_returncode: int = 0,
        scp_returncode: int = 0,
    ) -> None:
        self.bundle = bundle
        self.snapshot_returncode = snapshot_returncode
        self.scp_returncode = scp_returncode
        self.calls: list[list[str]] = []

    def run(self, args: Sequence[str]) -> subprocess.CompletedProcess[str]:
        command = list(args)
        self.calls.append(command)
        if command[0] == "scp":
            if self.scp_returncode == 0:
                incoming_root = Path(command[-1])
                shutil.copytree(self.bundle, incoming_root / str(RUN_ID))
            return subprocess.CompletedProcess(
                command,
                self.scp_returncode,
                stdout="",
                stderr="copy failed" if self.scp_returncode else "",
            )
        return subprocess.CompletedProcess(
            command,
            self.snapshot_returncode,
            stdout="",
            stderr="capture failed" if self.snapshot_returncode else "",
        )


def test_transport_commands_are_noninteractive_and_fixed_path() -> None:
    assert ssh_snapshot_command("kbl@kbl-target.local", RUN_ID) == [
        "ssh",
        "-o",
        "BatchMode=yes",
        "-o",
        "ConnectTimeout=15",
        "-o",
        "ServerAliveInterval=15",
        "-o",
        "ServerAliveCountMax=3",
        "kbl@kbl-target.local",
        "sudo",
        "/usr/local/sbin/kbl-capture-run",
        str(RUN_ID),
    ]
    assert scp_command("kbl@kbl-target.local", RUN_ID, Path("incoming")) == [
        "scp",
        "-o",
        "BatchMode=yes",
        "-o",
        "ConnectTimeout=15",
        "-o",
        "ServerAliveInterval=15",
        "-o",
        "ServerAliveCountMax=3",
        "-r",
        f"kbl@kbl-target.local:/var/lib/kylinbootlab/runs/{RUN_ID}",
        "incoming",
    ]


def test_collect_transports_then_imports_bundle(tmp_path: Path) -> None:
    bundle = create_probe_bundle(tmp_path / "remote", run_id=RUN_ID)
    runner = FakeRunner(bundle)
    store = RunStore(tmp_path / "runs")

    run_path = collect_target_run(
        target="kbl@kbl-target.local",
        run_id=RUN_ID,
        incoming_root=tmp_path / "incoming",
        store=store,
        runner=runner,
    )

    assert run_path == store.run_path(RUN_ID)
    assert [call[0] for call in runner.calls] == ["ssh", "scp"]


def test_snapshot_failure_imports_diagnostics_then_raises(tmp_path: Path) -> None:
    bundle = create_probe_bundle(tmp_path / "remote", run_id=RUN_ID)
    runner = FakeRunner(bundle, snapshot_returncode=1)
    store = RunStore(tmp_path / "runs")

    with pytest.raises(RemoteCollectionError, match="diagnostic bundle was imported"):
        collect_target_run(
            target="kbl@kbl-target.local",
            run_id=RUN_ID,
            incoming_root=tmp_path / "incoming",
            store=store,
            runner=runner,
        )

    assert store.run_path(RUN_ID).is_dir()


def test_scp_failure_does_not_create_a_stored_run(tmp_path: Path) -> None:
    bundle = create_probe_bundle(tmp_path / "remote", run_id=RUN_ID)
    runner = FakeRunner(bundle, scp_returncode=1)
    store = RunStore(tmp_path / "runs")

    with pytest.raises(RemoteCollectionError, match="scp failed"):
        collect_target_run(
            target="kbl@kbl-target.local",
            run_id=RUN_ID,
            incoming_root=tmp_path / "incoming",
            store=store,
            runner=runner,
        )

    assert not store.run_path(RUN_ID).exists()
