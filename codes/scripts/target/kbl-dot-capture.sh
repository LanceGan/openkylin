#!/usr/bin/env bash
# Capture systemd dependency DOT graph for Phase 4 causal analysis.
# Run on target:  bash kbl-dot-capture.sh > dot-output.txt
set -euo pipefail
systemd-analyze --no-pager dot --order 2>/dev/null || {
    echo "ERROR: systemd-analyze dot failed" >&2
    exit 1
}
