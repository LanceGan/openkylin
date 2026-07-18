#!/usr/bin/env bash
set -euo pipefail

# prepare_recovery.sh — set up ostree recovery baseline for KylinBootLab
#
# Pins the current deployment as the recovery baseline.  After running
# this script, ``ostree admin status`` will show one deployment with
# ``Pinned: yes`` — the recovery target used by Phase 2 RecoveryManager.

if [[ $EUID -ne 0 ]]; then
  printf 'usage: sudo prepare_recovery.sh\n' >&2
  exit 64
fi

echo "=== Current ostree status ==="
ostree admin status

readonly current="$(ostree admin status | grep '^\*' | head -1 | awk '{print $2}')"
if [[ -z "$current" ]]; then
  printf 'error: could not determine current deployment\n' >&2
  exit 1
fi

echo ""
echo "Pinning deployment ${current} as recovery baseline ..."
ostree admin pin 0

echo ""
echo "=== Updated ostree status ==="
ostree admin status

echo ""
echo "Recovery baseline set. Verify with: ostree admin status"
echo "The pinned deployment will be used by Phase 2 RecoveryManager."
