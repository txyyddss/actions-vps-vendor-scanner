from __future__ import annotations

from src.misc.stock_state import count_stock_states


def test_count_stock_states_handles_mixed_formats() -> None:
    counts = count_stock_states(
        [
            {"in_stock": 1},
            {"in_stock": "0"},
            {"stock_status": "out_of_stock"},
            {"stock_status": "in_stock"},
            {"in_stock": "invalid"},
        ]
    )

    assert counts == {"in_stock": 2, "out_of_stock": 2, "unknown": 1}
