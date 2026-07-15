# Foundation Baseline Runbook

## 1. Install openKylin

Install the current official stable openKylin standard image on the dedicated SSD. During installation create the account `kbl`, use the default graphical desktop, and keep Secure Boot and storage settings unchanged after the first baseline. Set the hostname at the physical console:

```bash
sudo hostnamectl set-hostname kbl-target
sudo apt-get update
sudo apt-get install -y avahi-daemon build-essential curl openssh-server python3
sudo systemctl enable --now avahi-daemon ssh
```

Record the ISO hash on the Windows controller:

```powershell
$iso = Get-ChildItem "$HOME\Downloads" -File |
    Where-Object { $_.Name -match '^openKylin.*\.iso$' } |
    Sort-Object LastWriteTime -Descending |
    Select-Object -First 1
if ($null -eq $iso) { throw "No openKylin ISO found in Downloads" }
Get-FileHash -Algorithm SHA256 $iso.FullName
```

Record the installed platform facts on the target:

```bash
cat /etc/os-release
uname -a
systemd --version
```

Store that output in the experiment notebook associated with the first real run. Do not update packages during one A/B block.

## 2. Configure controller SSH authentication

On the Windows controller, create a default key only when one does not exist:

```powershell
if (-not (Test-Path "$HOME\.ssh\id_ed25519")) {
    ssh-keygen -t ed25519 -f "$HOME\.ssh\id_ed25519" -N ''
}
scp "$HOME\.ssh\id_ed25519.pub" kbl@kbl-target.local:/tmp/controller.pub
```

At the target console:

```bash
install -d -m 0700 "$HOME/.ssh"
touch "$HOME/.ssh/authorized_keys"
grep -qxF "$(cat /tmp/controller.pub)" "$HOME/.ssh/authorized_keys" || \
  cat /tmp/controller.pub >>"$HOME/.ssh/authorized_keys"
chmod 0600 "$HOME/.ssh/authorized_keys"
rm /tmp/controller.pub
```

Back on the controller:

```powershell
ssh -o BatchMode=yes kbl@kbl-target.local true
```

Expected: exit code 0 without a password prompt.

## 3. Build and install the target probe

Copy the Rust workspace from the controller:

```powershell
ssh kbl@kbl-target.local "mkdir -p ~/KylinBootLab/.cargo ~/KylinBootLab/target ~/KylinBootLab/scripts"
scp Cargo.toml Cargo.lock rust-toolchain.toml kbl@kbl-target.local:KylinBootLab/
scp .cargo/config.toml kbl@kbl-target.local:KylinBootLab/.cargo/
scp -r target/bootprobe kbl@kbl-target.local:KylinBootLab/target/
scp -r scripts/target kbl@kbl-target.local:KylinBootLab/scripts/
```

Build and install at the target console:

```bash
curl --proto '=https' --tlsv1.2 -sSf https://sh.rustup.rs | \
  sh -s -- -y --default-toolchain 1.85.1 --profile minimal
source "$HOME/.cargo/env"
cd "$HOME/KylinBootLab"
cargo test --workspace
cargo build --release -p kbl-bootprobe
chmod +x scripts/target/*.sh scripts/target/kbl-capture-run
sudo scripts/target/install_bootprobe.sh .cargo-target/release/kbl-bootprobe kbl
```

Log out and back in, then verify:

```bash
cd "$HOME/KylinBootLab"
bash -n scripts/target/install_bootprobe.sh
bash -n scripts/target/kbl-capture-run
bash -n scripts/target/verify_foundation.sh
scripts/target/verify_foundation.sh
```

Expected: the final command prints one UUID and all required capture exit codes are zero.

## 4. Controller smoke capture

Once Task 10 is complete, capture the command output directly into a PowerShell variable:

```powershell
$runId = (uv run kbl collect --target kbl@kbl-target.local --data-root var/runs --incoming-root var/incoming).Trim()
uv run kbl report $runId --data-root var/runs
Test-Path "var/runs/$runId/derived/metrics.json"
Test-Path "var/runs/$runId/reports/baseline.html"
```

Both `Test-Path` commands must print `True`.
