#!/usr/bin/env bash
set -euo pipefail

run_id="$(cat /proc/sys/kernel/random/uuid)"
sudo /usr/local/sbin/kbl-capture-run "$run_id"
manifest="/var/lib/kylinbootlab/runs/${run_id}/probe-manifest.json"

python3 - "$manifest" "$run_id" <<'PY'
import json
import pathlib
import sys

manifest_path = pathlib.Path(sys.argv[1])
expected_run_id = sys.argv[2]
manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
assert manifest["schema_version"] == 1
assert manifest["run_id"] == expected_run_id
artifacts = {item["name"]: item for item in manifest["artifacts"]}
assert artifacts["systemd-time"]["exit_code"] == 0
assert artifacts["systemd-blame"]["exit_code"] == 0
for artifact in artifacts.values():
    assert (manifest_path.parent / artifact["relative_path"]).is_file()
print(expected_run_id)
PY
