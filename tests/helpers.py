import hashlib
import json
from datetime import UTC, datetime
from pathlib import Path
from typing import TypedDict
from uuid import UUID

from kylinbootlab.contracts import ArtifactRecord, HostInfo, ProbeManifest

RUN_ID = UUID("11111111-1111-4111-8111-111111111111")
BOOT_ID = UUID("22222222-2222-4222-8222-222222222222")


class CaptureFixture(TypedDict):
    command: list[str]
    exit_code: int
    stdout: str
    stderr: str


CAPTURES: dict[str, CaptureFixture] = {
    "systemd-time": {
        "command": ["systemd-analyze", "--no-pager", "time"],
        "exit_code": 0,
        "stdout": (
            "Startup finished in 1.000s (kernel) + 2.000s (userspace) = 3.000s\n"
            "graphical.target reached after 1.500s in userspace.\n"
        ),
        "stderr": "",
    },
    "systemd-blame": {
        "command": ["systemd-analyze", "--no-pager", "blame"],
        "exit_code": 0,
        "stdout": "900ms NetworkManager.service\n250ms dbus.service\n",
        "stderr": "",
    },
}


def create_probe_bundle(root: Path, run_id: UUID = RUN_ID) -> Path:
    bundle = root / "bundle"
    captures = bundle / "captures"
    captures.mkdir(parents=True)
    artifacts: list[ArtifactRecord] = []

    for name, document in CAPTURES.items():
        encoded = (json.dumps(document, indent=2, sort_keys=True) + "\n").encode()
        relative_path = f"captures/{name}.json"
        (bundle / relative_path).write_bytes(encoded)
        artifacts.append(
            ArtifactRecord(
                name=name,
                relative_path=relative_path,
                sha256=hashlib.sha256(encoded).hexdigest(),
                size_bytes=len(encoded),
                command=document["command"],
                exit_code=document["exit_code"],
                required=True,
            )
        )

    manifest = ProbeManifest(
        schema_version=1,
        run_id=run_id,
        boot_id=BOOT_ID,
        captured_at_utc=datetime(2026, 7, 15, 3, 0, tzinfo=UTC),
        boottime_ns=3_100_000_000,
        host=HostInfo(
            hostname="kbl-target",
            kernel_release="6.6.0-openkylin",
            os_id="openkylin",
            os_version_id="2.0",
            architecture="x86_64",
        ),
        artifacts=artifacts,
    )
    (bundle / "probe-manifest.json").write_text(
        manifest.model_dump_json(indent=2) + "\n",
        encoding="utf-8",
        newline="\n",
    )
    return bundle
