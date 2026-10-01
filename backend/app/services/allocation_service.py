"""分配编排：取数 → 纯引擎现算 → 草稿(临时优先)读写 → 确认落库 → 时段窗/写闸。

关键边界：
- 让路/重置只写 allocation_drafts，绝不写 allocation_runs；运行行仅 confirm 落一条。
- 主图(placements)、放不下(rejected)、临时优先(vendors[*].temp_priority) 永远来自同一次
  服务端实时重算，三处天然一套结论；草稿里的 result_json 仅审计，confirm 不读它。
- confirm 受集日可分配时段窗与 per-segment 写闸约束；拒绝时不增行、不清既有运行、不清草稿。
"""
from __future__ import annotations
import json
import threading
from datetime import datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.models import AllocationDraft, AllocationRun, MarketDay, Pillar, Segment, Vendor
from app.services.first_fit_engine import (
    YieldFailure,
    allocate_first_fit,
    effective_priority,
    plan_yield,
    result_to_dict,
    with_effective_priority,
)

# --------------------------------------------------------------------------- #
# 进程内 per-segment 写闸。compose 为单 uvicorn worker，足够；多 worker/多副本需换成
# Postgres 咨询锁 pg_try_advisory_xact_lock，只需替换本注册表里的获取方式。
# --------------------------------------------------------------------------- #
_locks_guard = threading.Lock()
_locks: dict[int, threading.Lock] = {}


def get_segment_lock(segment_id: int) -> threading.Lock:
    with _locks_guard:
        lock = _locks.get(segment_id)
        if lock is None:
            lock = threading.Lock()
            _locks[segment_id] = lock
        return lock


class AllocationError(Exception):
    def __init__(self, status_code: int, code: str, message: str):
        super().__init__(message)
        self.status_code = status_code
        self.code = code
        self.message = message


def _iso(value: datetime | None) -> str | None:
    return value.isoformat() if value is not None else None


def load_bundle(db: Session, segment_id: int):
    seg = db.get(Segment, segment_id)
    if seg is None:
        raise AllocationError(404, "segment_not_found", "街段不存在")
    day = db.get(MarketDay, seg.market_day_id)
    if day is None:
        raise AllocationError(404, "day_not_found", "集日不存在")
    pillars = [
        {"position_m": p.position_m, "thickness_m": p.thickness_m, "label": p.label}
        for p in db.scalars(select(Pillar).where(Pillar.segment_id == segment_id)
                           .order_by(Pillar.position_m)).all()
    ]
    vendors = [
        {"id": v.id, "name": v.name, "stall_width_m": v.stall_width_m, "priority": v.priority}
        for v in db.scalars(select(Vendor).where(Vendor.market_day_id == seg.market_day_id)).all()
    ]
    return seg, day, pillars, vendors


def _get_draft(db: Session, segment_id: int) -> AllocationDraft | None:
    return db.scalars(
        select(AllocationDraft).where(AllocationDraft.segment_id == segment_id)
    ).first()


def get_overrides(db: Session, segment_id: int) -> dict[int, float]:
    draft = _get_draft(db, segment_id)
    if draft is None:
        return {}
    raw = json.loads(draft.overrides_json or "{}")
    return {int(k): float(v) for k, v in raw.items()}


def _latest_run(db: Session, segment_id: int) -> AllocationRun | None:
    return db.scalars(
        select(AllocationRun).where(AllocationRun.segment_id == segment_id)
        .order_by(AllocationRun.id.desc())
    ).first()


def build_payload(seg: Segment, day: MarketDay, pillars: list[dict],
                  vendors: list[dict], overrides: dict[int, float]) -> dict:
    """同一构造器产出 state 与运行行 JSON，避免字段漂移；也是幂等比对的规范结论。"""
    result = allocate_first_fit(seg.width_m, with_effective_priority(vendors, overrides), pillars)
    result_dict = result_to_dict(result)
    eff_vendors = sorted(
        (
            {
                "id": v["id"],
                "name": v["name"],
                "stall_width_m": v["stall_width_m"],
                "priority": v["priority"],  # 登记优先，只读
                "temp_priority": effective_priority(v, overrides),
            }
            for v in vendors
        ),
        key=lambda v: (v["temp_priority"], v["id"]),
    )
    return {
        "segment": {
            "id": seg.id, "market_day_id": seg.market_day_id,
            "name": seg.name, "width_m": seg.width_m,
        },
        "pillars": pillars,
        "placements": result_dict["placements"],
        "rejected": result_dict["rejected"],
        "free_spans": result_dict["free_spans"],
        "vendors": eff_vendors,
        "window": {
            "alloc_open_at": _iso(day.alloc_open_at),
            "alloc_close_at": _iso(day.alloc_close_at),
        },
    }


def get_state(db: Session, segment_id: int) -> dict:
    """纯读：无草稿即绿仓基线，不落任何写。"""
    seg, day, pillars, vendors = load_bundle(db, segment_id)
    overrides = get_overrides(db, segment_id)
    payload = build_payload(seg, day, pillars, vendors, overrides)
    run = _latest_run(db, segment_id)
    payload["latest_run_id"] = run.id if run else None
    return payload


def yield_vendor(db: Session, segment_id: int, vendor_id: int) -> dict:
    with get_segment_lock(segment_id):
        seg, day, pillars, vendors = load_bundle(db, segment_id)
        if not any(v["id"] == vendor_id for v in vendors):
            raise AllocationError(404, "vendor_not_found", "摊主不存在")
        overrides = get_overrides(db, segment_id)
        plan = plan_yield(seg.width_m, vendors, pillars, overrides, vendor_id)
        if isinstance(plan, YieldFailure):
            # 不写草稿、不写运行行、不改登记优先；session 无任何待提交变更。
            raise AllocationError(409, plan.code, plan.message)
        if not plan.noop:
            if not any(p.vendor_id == vendor_id for p in plan.result.placements):
                # 防御性不变量：非 no-op 计划必须已让 X 入位，否则按无邻失败处理，绝不半成功。
                raise AllocationError(
                    409, "no_neighbor",
                    "目标柱间内没有可压低的邻摊，让路无法腾出空档")
            payload = build_payload(seg, day, pillars, vendors, plan.new_overrides)
            draft = _get_draft(db, segment_id)
            if draft is None:
                draft = AllocationDraft(segment_id=segment_id)
                db.add(draft)
            draft.overrides_json = json.dumps(
                {str(k): v for k, v in plan.new_overrides.items()}, ensure_ascii=False)
            draft.result_json = json.dumps(payload, ensure_ascii=False)
            draft.updated_at = datetime.utcnow()
            db.commit()
        return get_state(db, segment_id)


def reset_draft(db: Session, segment_id: int) -> dict:
    with get_segment_lock(segment_id):
        seg, day, pillars, vendors = load_bundle(db, segment_id)
        draft = _get_draft(db, segment_id)
        if draft is not None:
            db.delete(draft)
            db.commit()
        return get_state(db, segment_id)


def _in_window(day: MarketDay, now: datetime) -> AllocationError | None:
    if day.alloc_open_at is None or day.alloc_close_at is None:
        return AllocationError(409, "window_unset", "集日未配置可分配时段窗")
    # naive UTC，端点含等号
    if now < day.alloc_open_at or now > day.alloc_close_at:
        return AllocationError(409, "outside_window", "集日已在可分配时段窗外")
    return None


def confirm(db: Session, segment_id: int, now: datetime | None = None) -> dict:
    lock = get_segment_lock(segment_id)
    if not lock.acquire(blocking=False):
        raise AllocationError(409, "lock_open", "同类写闸已开")
    try:
        seg, day, pillars, vendors = load_bundle(db, segment_id)
        err = _in_window(day, now or datetime.utcnow())
        if err is not None:
            raise err
        overrides = get_overrides(db, segment_id)
        payload = build_payload(seg, day, pillars, vendors, overrides)

        latest = _latest_run(db, segment_id)
        if latest is not None:
            try:
                stored = json.loads(latest.result_json or "{}")
            except json.JSONDecodeError:
                stored = None
            if stored == payload:
                out = dict(payload)
                out["latest_run_id"] = latest.id
                out["run_id"] = latest.id
                out["idempotent"] = True
                return out

        run = AllocationRun(segment_id=segment_id, created_at=datetime.utcnow(),
                            result_json=json.dumps(payload, ensure_ascii=False))
        db.add(run)
        db.commit()
        db.refresh(run)
        out = dict(payload)
        out["latest_run_id"] = run.id
        out["run_id"] = run.id
        out["idempotent"] = False
        return out
    finally:
        lock.release()
