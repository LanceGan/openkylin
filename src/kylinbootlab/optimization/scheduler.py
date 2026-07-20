"""ABBA randomized-block scheduler and profile state machine.

The ABBA pattern eliminates linear time trends by pairing baseline (A) and
optimized (B) boots within each block in A-B-B-A order.  The state machine
tracks which profile is currently applied on the target so that we only
execute a switch when the profile actually changes.
"""

from __future__ import annotations


class ABBAScheduler:
    """Generate ABBA experiment sequences and query boot indices.

    Each block contributes 4 boots in A-B-B-A order.  With ``total_blocks=4``
    the total measured boots = 16; plus ``warmup_boots=2`` warmup boots
    (discarded from statistics) the full experiment has 18 boots per candidate.
    """

    def __init__(self, total_blocks: int = 4, warmup_boots: int = 2) -> None:
        if total_blocks < 1:
            raise ValueError("total_blocks must be >= 1")
        if warmup_boots < 0:
            raise ValueError("warmup_boots must be >= 0")
        self.total_blocks = total_blocks
        self.warmup_boots = warmup_boots

    def generate_sequence(self) -> list[str]:
        """Generate the full A/B sequence including warmup boots.

        Warmup boots are always indexed first and use profile "A" (baseline).
        Then each block contributes ["A", "B", "B", "A"].

        Returns a list of ``self.warmup_boots + self.total_blocks * 4``
        elements, each either ``"A"`` or ``"B"``.
        """
        sequence: list[str] = []
        # Warmup boots
        for _ in range(self.warmup_boots):
            sequence.append("A")
        # ABBA blocks
        for _ in range(self.total_blocks):
            sequence.extend(["A", "B", "B", "A"])
        return sequence

    def current_profile(self, sequence: list[str], boot_index: int) -> str:
        """Return the profile ("A" or "B") at the given 0-based boot index."""
        if boot_index < 0 or boot_index >= len(sequence):
            raise IndexError(
                f"boot_index {boot_index} out of range [0, {len(sequence)})"
            )
        return sequence[boot_index]

    def needs_switch(
        self, sequence: list[str], from_idx: int, to_idx: int
    ) -> bool:
        """Return True if the profile at ``from_idx`` differs from ``to_idx``."""
        return sequence[from_idx] != sequence[to_idx]


class ProfileStateMachine:
    """Tracks the currently-applied profile on the target machine.

    ``switch_to`` is idempotent: calling it with the current profile is a no-op.
    """

    def __init__(self, initial: str = "A") -> None:
        if initial not in ("A", "B"):
            raise ValueError("initial profile must be 'A' or 'B'")
        self._current = initial

    @property
    def current(self) -> str:
        """The currently active profile ("A" or "B")."""
        return self._current

    def switch_to(self, target: str) -> None:
        """Transition to *target* profile.  No-op if already there."""
        if target not in ("A", "B"):
            raise ValueError("target profile must be 'A' or 'B'")
        self._current = target
