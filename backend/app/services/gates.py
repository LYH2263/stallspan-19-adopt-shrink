"""确认闸门：让路预览不落库，只有通过两道闸的正式确认才写运行行。

1. 可分配时段窗：今天必须落在 [集日 - days_before, 集日 + days_after]；
2. 同类写闸：同一街段同一写类型（allocate_run / yield_confirm）同时只允许一个写者，
   非阻塞抢锁，抢不到即 409，避免双击/并发产生半成功增行。

内存锁仅在单进程部署内互斥；本系统为单实例 uvicorn，够用且可测。
"""
from __future__ import annotations

import threading
from dataclasses import dataclass
from datetime import date, timedelta

from app.config import settings


class GateError(Exception):
    def __init__(self, status_code: int, code: str, detail: str):
        self.status_code = status_code
        self.code = code
        self.detail = detail
        super().__init__(detail)


_locks_guard = threading.Lock()
_write_locks: dict[tuple[int, str], threading.Lock] = {}
_held: set[tuple[int, str]] = set()


def _key(segment_id: int, kind: str) -> tuple[int, str]:
    return (segment_id, kind)


def check_day_window(market_day: date, today: date | None = None) -> None:
    today = today or date.today()
    lo = market_day - timedelta(days=settings.allocation_days_before)
    hi = market_day + timedelta(days=settings.allocation_days_after)
    if not (lo <= today <= hi):
        raise GateError(
            403,
            "outside_allocation_window",
            f"集日 {market_day.isoformat()} 的可分配时段窗为 {lo.isoformat()}～{hi.isoformat()}，"
            f"今天 {today.isoformat()} 已在窗外，确认被闸门拒绝（让路结果未落库）",
        )


@dataclass
class WriteGate:
    key: tuple[int, str]

    def __enter__(self) -> "WriteGate":
        with _locks_guard:
            lock = _write_locks.setdefault(self.key, threading.Lock())
        if not lock.acquire(blocking=False):
            seg_id, kind = self.key
            raise GateError(409, "write_gate_open", f"同类写闸已开（街段 {seg_id} / {kind}），请勿连点，稍后再试")
        _held.add(self.key)
        return self

    def __exit__(self, *exc) -> None:
        _held.discard(self.key)
        with _locks_guard:
            lock = _write_locks.get(self.key)
        if lock is not None and lock.locked():
            lock.release()


def acquire_write_gate(segment_id: int, kind: str) -> WriteGate:
    gate = WriteGate(_key(segment_id, kind))
    gate.__enter__()
    return gate


def _reset_for_tests() -> None:
    _held.clear()
