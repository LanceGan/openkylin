#!/usr/bin/env bash
set -euo pipefail

# install_observer.sh — one-sudo installer for the Phase 3 readiness observer.
# Installs the probe binary, the root observer unit, the session usable-probe
# autostart entry, the root-only observe.toml, and the shared state dir.

if [[ $EUID -ne 0 || $# -ne 3 ]]; then
  printf 'usage: sudo install_observer.sh BINARY TARGET_USER PASSWORD\n' >&2
  printf '  PASSWORD: TARGET_USER login password, lowercase letters+digits only\n' >&2
  exit 64
fi

readonly binary="$1"
readonly target_user="$2"
readonly password="$3"
readonly script_dir="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"

if [[ ! -x "$binary" ]]; then
  printf 'probe binary is not executable: %s\n' "$binary" >&2
  exit 66
fi
if ! id "$target_user" >/dev/null 2>&1; then
  printf 'target user does not exist: %s\n' "$target_user" >&2
  exit 67
fi
if [[ ! "$password" =~ ^[a-z0-9]+$ ]]; then
  printf 'password must be lowercase letters and digits only (spec constraint)\n' >&2
  exit 65
fi

getent group kbl >/dev/null 2>&1 || groupadd --system kbl
usermod --append --groups kbl "$target_user"
install -o root -g root -m 0755 "$binary" /usr/local/bin/kbl-bootprobe

# Shared state dir: root observer writes the stream, the kbl session probe
# writes its result file, the controller toggles the enabled marker over
# plain SSH — hence group-writable with setgid (no runtime sudo anywhere).
install -d -o root -g kbl -m 2750 /var/lib/kylinbootlab
install -d -o root -g kbl -m 2775 /var/lib/kylinbootlab/observe

install -d -o root -g root -m 0755 /etc/kylinbootlab
config_temp="$(mktemp)"
trap 'rm -f "$config_temp"' EXIT
cat >"$config_temp" <<EOF
# KylinBootLab Phase 3 observer configuration (root 0600 — contains the
# login password).  Omitted fields use built-in defaults.
mode = "benchmark"
target_user = "${target_user}"
password = "${password}"
# Refine after the first real login (see runbook section 4):
# desktop_processes = ["ukui-panel", "ukui-settings-daemon"]
# sentinel_command = ["mate-terminal"]
# greeter_ready_pattern = "ukui-greeter"
# session_opened_pattern = "session opened for user"
EOF
install -o root -g root -m 0600 "$config_temp" /etc/kylinbootlab/observe.toml

install -o root -g root -m 0644 "$script_dir/kbl-observe.service" \
  /etc/systemd/system/kbl-observe.service
systemctl daemon-reload
systemctl enable kbl-observe.service

readonly autostart_dir="/home/${target_user}/.config/autostart"
install -d -o "$target_user" -g "$target_user" "$autostart_dir"
install -o "$target_user" -g "$target_user" -m 0644 \
  "$script_dir/kbl-usable-probe.desktop" "$autostart_dir/kbl-usable-probe.desktop"

touch /var/lib/kylinbootlab/observe/enabled
chgrp kbl /var/lib/kylinbootlab/observe/enabled
chmod 0664 /var/lib/kylinbootlab/observe/enabled

printf 'observer installed and enabled (marker present -> observes next boot)\n'
printf 'next steps:\n'
printf '  1. verify unit: systemctl cat kbl-observe.service\n'
printf '  2. reboot, then inspect /var/lib/kylinbootlab/observe/current.jsonl\n'
printf '  3. refine desktop_processes/patterns in /etc/kylinbootlab/observe.toml\n'
printf 'NOTE: the password was passed on the command line; clear your shell history\n'
