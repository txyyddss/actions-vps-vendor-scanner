from src.hidden_scanner.scan_control import AdaptiveScanController


def test_adaptive_scan_stops_after_inactive_streak() -> None:
    control = AdaptiveScanController(
        hard_max=500,
        initial_floor=10,
        tail_window=20,
        learned_high=0,
        inactive_streak_limit=6,
    )

    while True:
        batch = control.next_batch(4)
        if not batch:
            break
        for item_id in batch:
            should_stop = control.mark(item_id=item_id, is_new_discovery=False)
            if should_stop:
                break
        if control.should_stop:
            break

    assert control.should_stop is True
    assert control.last_processed_id < 500
    assert "inactive-streak" in control.stop_reason


def test_adaptive_scan_extends_when_new_ids_found() -> None:
    control = AdaptiveScanController(
        hard_max=120,
        initial_floor=20,
        tail_window=10,
        learned_high=0,
        inactive_streak_limit=20,
    )
    # Initial upper edge should be initial_floor because learned_high is zero.
    assert control.current_max == 20

    # Discovering a new id near the edge should extend scan upper bound.
    control.mark(item_id=19, is_new_discovery=True)
    assert control.current_max == 29
