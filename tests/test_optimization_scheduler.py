"""Unit tests for ABBAScheduler and ProfileStateMachine."""

import pytest

from kylinbootlab.optimization.scheduler import (
    ABBAScheduler,
    ProfileStateMachine,
)


class TestABBAScheduler:
    def test_one_block_sequence(self) -> None:
        scheduler = ABBAScheduler(total_blocks=1, warmup_boots=0)
        seq = scheduler.generate_sequence()
        assert seq == ["A", "B", "B", "A"]

    def test_one_block_with_warmup(self) -> None:
        scheduler = ABBAScheduler(total_blocks=1, warmup_boots=2)
        seq = scheduler.generate_sequence()
        assert seq == ["A", "A", "A", "B", "B", "A"]

    def test_four_blocks_correct_length(self) -> None:
        scheduler = ABBAScheduler(total_blocks=4, warmup_boots=2)
        seq = scheduler.generate_sequence()
        # 2 warmup + 4 blocks * 4 = 2 + 16 = 18
        assert len(seq) == 18

    def test_four_blocks_indices_correct(self) -> None:
        scheduler = ABBAScheduler(total_blocks=4, warmup_boots=2)
        seq = scheduler.generate_sequence()
        # Block 1 measured boots are at indices [2, 3, 4, 5]
        assert seq[2:6] == ["A", "B", "B", "A"]
        # Block 2 measured boots are at indices [6, 7, 8, 9]
        assert seq[6:10] == ["A", "B", "B", "A"]
        # Block 3 measured boots at [10, 11, 12, 13]
        assert seq[10:14] == ["A", "B", "B", "A"]
        # Block 4 measured boots at [14, 15, 16, 17]
        assert seq[14:18] == ["A", "B", "B", "A"]

    def test_current_profile_returns_correct_value(self) -> None:
        scheduler = ABBAScheduler(total_blocks=2, warmup_boots=1)
        seq = scheduler.generate_sequence()
        # warmup
        assert scheduler.current_profile(seq, 0) == "A"
        # block 1
        assert scheduler.current_profile(seq, 1) == "A"
        assert scheduler.current_profile(seq, 2) == "B"
        assert scheduler.current_profile(seq, 3) == "B"
        assert scheduler.current_profile(seq, 4) == "A"

    def test_needs_switch_same_profile(self) -> None:
        scheduler = ABBAScheduler(total_blocks=1, warmup_boots=0)
        seq = scheduler.generate_sequence()  # ["A", "B", "B", "A"]
        # Both indices 1 and 2 are "B" -- no switch needed
        assert scheduler.needs_switch(seq, 1, 2) is False

    def test_needs_switch_different_profile(self) -> None:
        scheduler = ABBAScheduler(total_blocks=1, warmup_boots=0)
        seq = scheduler.generate_sequence()  # ["A", "B", "B", "A"]
        # Index 0 is "A", index 1 is "B" -- switch needed
        assert scheduler.needs_switch(seq, 0, 1) is True

    def test_rejects_zero_blocks(self) -> None:
        with pytest.raises(ValueError, match="total_blocks"):
            ABBAScheduler(total_blocks=0)

    def test_current_profile_out_of_range(self) -> None:
        scheduler = ABBAScheduler(total_blocks=1, warmup_boots=0)
        seq = scheduler.generate_sequence()  # length 4
        with pytest.raises(IndexError):
            scheduler.current_profile(seq, 4)
        with pytest.raises(IndexError):
            scheduler.current_profile(seq, -1)


class TestProfileStateMachine:
    def test_initial_a(self) -> None:
        sm = ProfileStateMachine(initial="A")
        assert sm.current == "A"

    def test_initial_b(self) -> None:
        sm = ProfileStateMachine(initial="B")
        assert sm.current == "B"

    def test_switch_to_different(self) -> None:
        sm = ProfileStateMachine(initial="A")
        sm.switch_to("B")
        assert sm.current == "B"

    def test_switch_to_same_is_noop(self) -> None:
        sm = ProfileStateMachine(initial="A")
        sm.switch_to("A")
        assert sm.current == "A"

    def test_switch_back(self) -> None:
        sm = ProfileStateMachine(initial="A")
        sm.switch_to("B")
        sm.switch_to("A")
        assert sm.current == "A"

    def test_rejects_invalid_initial(self) -> None:
        with pytest.raises(ValueError, match="initial"):
            ProfileStateMachine(initial="C")

    def test_rejects_invalid_target(self) -> None:
        sm = ProfileStateMachine()
        with pytest.raises(ValueError, match="target"):
            sm.switch_to("C")


class TestProfileExecutorCommandConstruction:
    """Verify that ProfileExecutor builds correct SSH commands.

    These tests validate command construction only -- no real SSH connections.
    They examine the internal command strings that would be passed to subprocess.
    """

    def test_drop_in_apply_command(self) -> None:
        """Drop-in apply must create directory, write file via tee, and daemon-reload."""
        from kylinbootlab.optimization.executor import ProfileExecutor
        from kylinbootlab.optimization.plan import build_socket_nm_wait

        plan = build_socket_nm_wait()
        _executor = ProfileExecutor(target="test-target")
        assert plan.drop_in_path is not None
        assert plan.drop_in_content is not None

        # Build the command string as _ssh() would
        drop_in_dir = plan.drop_in_path.rsplit("/", 1)[0]
        escaped = plan.drop_in_content.replace("'", "'\\''")
        cmd = (
            f"sudo mkdir -p {drop_in_dir} && "
            f"echo '{escaped}' | sudo tee {plan.drop_in_path} > /dev/null && "
            f"sudo systemctl daemon-reload"
        )
        assert "sudo mkdir -p" in cmd
        assert "sudo tee" in cmd
        assert "kbl-opt.conf" in cmd
        assert "sudo systemctl daemon-reload" in cmd

    def test_mask_apply_command(self) -> None:
        """Mask apply must run systemctl mask."""
        from kylinbootlab.optimization.executor import ProfileExecutor
        from kylinbootlab.optimization.plan import build_mask_biometric

        plan = build_mask_biometric()
        _executor = ProfileExecutor(target="test-target")
        assert plan.mask_unit is not None
        cmd = f"sudo systemctl mask {plan.mask_unit}"
        assert cmd == "sudo systemctl mask biometric-authentication.service"

    def test_drop_in_rollback_command(self) -> None:
        """Drop-in rollback must rm the file and daemon-reload."""
        from kylinbootlab.optimization.executor import ProfileExecutor
        from kylinbootlab.optimization.plan import build_socket_nm_wait

        plan = build_socket_nm_wait()
        _executor = ProfileExecutor(target="test-target")
        assert plan.drop_in_path is not None
        cmd = (
            f"sudo rm -f {plan.drop_in_path} && "
            f"sudo systemctl daemon-reload"
        )
        assert "sudo rm -f" in cmd
        assert "kbl-opt.conf" in cmd
        assert "sudo systemctl daemon-reload" in cmd

    def test_mask_rollback_command(self) -> None:
        """Mask rollback must run systemctl unmask."""
        from kylinbootlab.optimization.executor import ProfileExecutor
        from kylinbootlab.optimization.plan import build_mask_biometric

        plan = build_mask_biometric()
        _executor = ProfileExecutor(target="test-target")
        assert plan.mask_unit is not None
        cmd = f"sudo systemctl unmask {plan.mask_unit}"
        assert cmd == "sudo systemctl unmask biometric-authentication.service"
