"""Minimal debug: executor apply/verify with explicit SSH output."""
import subprocess
import sys

sys.path.insert(0, "src")

TARGET = "kbl@192.168.19.128"
PASSWORD = "12345678"

def debug_ssh(cmd):
    """Run SSH command with explicit error capture."""
    if "sudo " in cmd:
        cmd = cmd.replace("sudo ", f"echo '{PASSWORD}' | sudo -S ", 1)
    r = subprocess.run(["ssh", "-o", "BatchMode=yes", TARGET, cmd],
                       capture_output=True, text=True, timeout=30)
    print(f"  CMD: {cmd[:80]}...")
    print(f"  RC={r.returncode} STDOUT={r.stdout.strip()[:100]}")
    print(f"  STDERR={r.stderr.strip()[:100]}")
    return r

# Check current state
print("=== Current biometric state ===")
r = debug_ssh("systemctl is-active biometric-authentication.service 2>&1")
print()

# Try mask
print("=== Mask ===")
r = debug_ssh("sudo systemctl mask biometric-authentication.service 2>&1")
print()

# Verify (our executor's exact command)
print("=== Verify (executor's command) ===")
vcmd = "test -L /etc/systemd/system/biometric-authentication.service && readlink /etc/systemd/system/biometric-authentication.service | grep -q /dev/null"
r = debug_ssh(vcmd)
print(f"  Final: mask_applied={r.returncode == 0}")
print()

# What does readlink actually see?
print("=== Direct readlink ===")
r = debug_ssh("readlink /etc/systemd/system/biometric-authentication.service 2>&1")
print()

# Is there even a base unit file?
print("=== Unit files ===")
r = debug_ssh("ls /etc/systemd/system/biometric* /usr/lib/systemd/system/biometric* 2>&1")
print()

# unmask
print("=== Cleanup: unmask ===")
r = debug_ssh("sudo systemctl unmask biometric-authentication.service 2>&1")
print("done")
