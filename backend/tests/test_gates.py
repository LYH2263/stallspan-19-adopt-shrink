from datetime import date, timedelta

import pytest

from app.services import gates
from app.services.gates import GateError, WriteGate, check_day_window


def test_day_inside_window_passes():
    today = date(2026, 10, 1)
    check_day_window(date(2026, 9, 20), today=today)  # ±30 天，11 天差，通过
    check_day_window(date(2026, 10, 1), today=today)


def test_day_outside_window_far_past_rejected():
    today = date(2026, 10, 1)
    with pytest.raises(GateError) as ei:
        check_day_window(date(2020, 1, 1), today=today)
    assert ei.value.status_code == 403
    assert ei.value.code == "outside_allocation_window"


def test_day_boundary_of_window():
    today = date(2026, 10, 1)
    check_day_window(today + timedelta(days=30), today=today)   # 含端点
    with pytest.raises(GateError):
        check_day_window(today + timedelta(days=31), today=today)


def test_write_gate_blocks_second_holder_and_releases():
    gates._reset_for_tests()
    g = gates.acquire_write_gate(77, "allocation_write")
    try:
        with pytest.raises(GateError) as ei:
            with WriteGate((77, "allocation_write")):
                pass
        assert ei.value.status_code == 409
        assert ei.value.code == "write_gate_open"
    finally:
        g.__exit__(None, None, None)
    # 释放后可再拿
    with WriteGate((77, "allocation_write")):
        pass


def test_distinct_segments_do_not_block_each_other():
    gates._reset_for_tests()
    with WriteGate((1, "allocation_write")):
        with WriteGate((2, "allocation_write")):
            pass
