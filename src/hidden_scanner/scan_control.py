"""Provides adaptive rate-limiting and boundary control for hidden scanners."""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(slots=True)
class AdaptiveScanController:
    """Controls adaptive scanner bounds and early-stop conditions."""

    hard_max: int
    initial_floor: int
    tail_window: int
    learned_high: int = 0
    inactive_streak_limit: int = 60
    start_id: int = 0
    current_max: int = field(init=False)
    cursor: int = field(init=False)
    highest_new_id: int = field(init=False, default=-1)
    last_processed_id: int = field(init=False, default=-1)
    inactive_streak: int = field(init=False, default=0)
    stop_reason: str = field(init=False, default="")

    def __post_init__(self) -> None:
        """Executes __post_init__ logic."""
        self.hard_max = max(0, int(self.hard_max))
        self.initial_floor = max(0, int(self.initial_floor))
        self.tail_window = max(1, int(self.tail_window))
        self.learned_high = max(0, int(self.learned_high))
        self.inactive_streak_limit = max(8, int(self.inactive_streak_limit))
        self.start_id = max(0, int(self.start_id))

        initial_max = max(self.initial_floor, self.learned_high + self.tail_window)
        self.current_max = min(self.hard_max, initial_max)
        self.cursor = self.start_id

    def next_batch(self, batch_size: int) -> list[int]:
        """Executes next_batch logic."""
        if self.should_stop or self.cursor > self.current_max:
            return []
        size = max(1, int(batch_size))
        start = self.cursor
        end = min(self.current_max, start + size - 1)
        self.cursor = end + 1
        return list(range(start, end + 1))

    def mark(self, item_id: int, is_new_discovery: bool) -> bool:
        """Executes mark logic."""
        self.last_processed_id = max(self.last_processed_id, item_id)

        if is_new_discovery:
            self.inactive_streak = 0
            if item_id > self.highest_new_id:
                self.highest_new_id = item_id
            # Extend the active scan edge when we find newer IDs.
            target_max = min(self.hard_max, self.highest_new_id + self.tail_window)
            if target_max > self.current_max:
                self.current_max = target_max
        else:
            self.inactive_streak += 1

        if (
            item_id >= self.initial_floor
            and self.inactive_streak >= self.inactive_streak_limit
            and (self.highest_new_id < 0 or item_id >= self.highest_new_id)
        ):
            self.stop_reason = (
                f"inactive-streak={self.inactive_streak} floor={self.initial_floor} "
                f"highest_new={self.highest_new_id}"
            )
            return True
        return False

    @property
    def should_stop(self) -> bool:
        """Executes should_stop logic."""
        return bool(self.stop_reason)
