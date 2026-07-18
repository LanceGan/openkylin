from __future__ import annotations

import subprocess
from collections.abc import Sequence
from pathlib import Path
from typing import Any

import pytest

from kylinbootlab.experiments.aliveness import wait_for_ssh


def test_wait_for_ssh_returns_false_when_ssh_never_answers(tmp_path: Path) -> None:
    """wait_for_ssh returns False when every attempt fails."""
    result = wait_for_ssh("192.0.2.1", timeout=0.5, interval=0.1)
    assert result is False


def test_wait_for_ssh_returns_true_on_first_success(monkeypatch: pytest.MonkeyPatch) -> None:
    """wait_for_ssh returns True as soon as one call succeeds."""
    call_count = 0

    def fake_run(
        args: Sequence[str],
        **_kwargs: Any,
    ) -> subprocess.CompletedProcess[str]:
        nonlocal call_count
        call_count += 1
        if call_count >= 2:
            return subprocess.CompletedProcess(args, 0, stdout="", stderr="")
        raise OSError("connection refused")

    monkeypatch.setattr("kylinbootlab.experiments.aliveness.subprocess.run", fake_run)

    result = wait_for_ssh("target.local", timeout=10, interval=0.05)
    assert result is True
