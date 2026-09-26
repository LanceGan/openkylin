#!/usr/bin/env bash
set -euo pipefail

if [[ $EUID -ne 0 || $# -ne 2 ]]; then
  printf 'usage: sudo install_bootprobe.sh BINARY TARGET_USER\n' >&2
  exit 64
fi

readonly binary="$1"
readonly target_user="$2"
readonly script_dir="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"

if [[ ! -x "$binary" ]]; then
  printf 'probe binary is not executable: %s\n' "$binary" >&2
  exit 66
fi
if ! id "$target_user" >/dev/null 2>&1; then
  printf 'target user does not exist: %s\n' "$target_user" >&2
  exit 67
fi

getent group kbl >/dev/null 2>&1 || groupadd --system kbl
usermod --append --groups kbl "$target_user"
install -o root -g root -m 0755 "$binary" /usr/local/bin/kbl-bootprobe
install -o root -g root -m 0755 "$script_dir/kbl-capture-run" /usr/local/sbin/kbl-capture-run
install -d -o root -g kbl -m 2750 /var/lib/kylinbootlab
install -d -o root -g kbl -m 2750 /var/lib/kylinbootlab/runs

sudoers_temp="$(mktemp)"
trap 'rm -f "$sudoers_temp"' EXIT
printf '%s ALL=(root) NOPASSWD: /usr/local/sbin/kbl-capture-run *\n' "$target_user" \
  >"$sudoers_temp"
chmod 0440 "$sudoers_temp"
visudo -cf "$sudoers_temp"
install -o root -g root -m 0440 "$sudoers_temp" /etc/sudoers.d/kylinbootlab

printf 'installed kbl-bootprobe for %s; log out and back in to refresh group membership\n' \
  "$target_user"
