import json
import threading
from dataclasses import dataclass, field
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.database import get_db
from app.models.models import AllocationRun, MarketDay, Pillar, Segment, Vendor
from app.services.first_fit_engine import allocate_first_fit, result_to_dict
from app.services.gates import GateError, WriteGate, check_day_window
from app.services.yield_service import attempt_yield

router = APIRouter(prefix="/allocate", tags=["allocate"])


class YieldRequest(BaseModel):
    vendor_id: int
    span_lo: float
    span_hi: float


@dataclass
class YieldPreview:
    """让路成功后的临时结论。纯内存、零落库，正式确认才写运行行。"""
    segment_id: int
    target_vendor_id: int
    priority_override: dict[int, float]
    suppressed: list[dict]
    result: dict
    # 快照：确认时严格按让路时的输入与刚压低的临时优先重算，不读取期间可能变化的登记值
    segment_meta: dict
    width_m: float
    vendors: list[dict]
    pillars: list[dict]
    created_at: datetime = field(default_factory=datetime.utcnow)


_previews_lock = threading.Lock()
_previews: dict[int, YieldPreview] = {}


def _load_pillars(db: Session, segment_id: int) -> list[dict]:
    return [{"position_m": p.position_m, "thickness_m": p.thickness_m}
            for p in db.scalars(select(Pillar).where(Pillar.segment_id == segment_id)).all()]


def _load_vendors(db: Session, market_day_id: int) -> list[dict]:
    return [{"id": v.id, "name": v.name, "stall_width_m": v.stall_width_m, "priority": v.priority}
            for v in db.scalars(select(Vendor).where(Vendor.market_day_id == market_day_id)).all()]


def _build_result(width_m: float, segment_meta: dict, pillars: list[dict], vendors: list[dict],
                  override: dict[int, float] | None = None) -> dict:
    """主图 / 放不下 / 临时优先三处共用的唯一结论出口。"""
    r = allocate_first_fit(width_m, vendors, pillars, priority_override=override or None)
    result = result_to_dict(r, priority_override=override or None)
    result["segment"] = segment_meta
    result["pillars"] = pillars
    return result


def _preview_payload(pv: YieldPreview) -> dict:
    return {
        "id": None,  # 预览未落库，没有运行行 id
        **pv.result,
        "yield_preview": {
            "target_vendor_id": pv.target_vendor_id,
            "suppressed": pv.suppressed,
            "created_at": pv.created_at.isoformat(),
        },
    }


@router.post("/run")
def run_allocate(segment_id: int = 1, db: Session = Depends(get_db)):
    seg = db.get(Segment, segment_id)
    if not seg:
        raise HTTPException(404, "街段不存在")
    market_day = db.get(MarketDay, seg.market_day_id)
    # 正式重算同样过闸：窗外不许写；写闸期间拒绝双击
    try:
        check_day_window(market_day.day)
        with WriteGate((segment_id, "allocation_write")):
            pillars = _load_pillars(db, segment_id)
            vendors = _load_vendors(db, seg.market_day_id)
            segment_meta = {"id": seg.id, "name": seg.name, "width_m": seg.width_m}
            result = _build_result(seg.width_m, segment_meta, pillars, vendors)
            run = AllocationRun(segment_id=segment_id, created_at=datetime.utcnow(),
                                result_json=json.dumps(result, ensure_ascii=False))
            db.add(run)
            db.commit()
            db.refresh(run)
    except GateError as e:
        raise HTTPException(e.status_code, {"code": e.code, "detail": e.detail})
    # 正式重算意味着放弃此前未落库的让路预览
    with _previews_lock:
        _previews.pop(segment_id, None)
    return {"id": run.id, **result}


@router.get("/latest")
def latest(segment_id: int = 1, db: Session = Depends(get_db)):
    seg = db.get(Segment, segment_id)
    if not seg:
        raise HTTPException(404, "街段不存在")
    # 让路预览优先：主图、放不下、临时优先都读这同一份结论
    with _previews_lock:
        pv = _previews.get(segment_id)
    if pv is not None:
        return _preview_payload(pv)
    run = db.scalars(select(AllocationRun).where(AllocationRun.segment_id == segment_id)
                     .order_by(AllocationRun.id.desc())).first()
    if not run:
        return run_allocate(segment_id=segment_id, db=db)
    data = json.loads(run.result_json)
    return {"id": run.id, **data}


@router.post("/yield")
def yield_way(req: YieldRequest, segment_id: int = 1, db: Session = Depends(get_db)):
    """对某条放不下的摊请求让路：纯内存试算，零写运行行、零写登记优先。"""
    seg = db.get(Segment, segment_id)
    if not seg:
        raise HTTPException(404, "街段不存在")
    pillars = _load_pillars(db, segment_id)
    vendors = _load_vendors(db, seg.market_day_id)

    outcome = attempt_yield(
        seg.width_m, vendors, pillars,
        target_vendor_id=req.vendor_id,
        span_lo=req.span_lo, span_hi=req.span_hi,
    )
    if outcome.status != "success":
        # 失败：不碰既有预览、不碰登记优先、不写运行行；无邻与空档不够严格区分
        raise HTTPException(409, {"code": outcome.status, "detail": outcome.message,
                                  "suppressed": outcome.suppressed})

    segment_meta = {"id": seg.id, "name": seg.name, "width_m": seg.width_m}
    result = _build_result(seg.width_m, segment_meta, pillars, vendors, override=outcome.priority_override)
    pv = YieldPreview(
        segment_id=segment_id,
        target_vendor_id=req.vendor_id,
        priority_override=dict(outcome.priority_override),
        suppressed=outcome.suppressed,
        result=result,
        segment_meta=segment_meta,
        width_m=seg.width_m,
        vendors=vendors,
        pillars=pillars,
    )
    with _previews_lock:
        _previews[segment_id] = pv
    return _preview_payload(pv)


@router.post("/confirm")
def confirm_yield(segment_id: int = 1, db: Session = Depends(get_db)):
    """正式确认让路结论：过时段窗 + 同类写闸后，按快照与临时优先重算并只落一行。"""
    seg = db.get(Segment, segment_id)
    if not seg:
        raise HTTPException(404, "街段不存在")
    # 原子摘除预览：连点确认时第二次必为 no_preview，杜绝错开毫秒的双击各写一行
    with _previews_lock:
        pv = _previews.pop(segment_id, None)
    if pv is None:
        raise HTTPException(400, {"code": "no_preview", "detail": "没有待确认的让路预览"})

    def restore_preview() -> None:
        # 闸门拒绝：预览必须原样保留，让路前已成功的运行行也不动
        with _previews_lock:
            _previews.setdefault(segment_id, pv)

    market_day = db.get(MarketDay, seg.market_day_id)
    try:
        # 窗外或写闸已开：拒绝确认。先时段窗、后写闸，顺序固定。
        check_day_window(market_day.day)
        with WriteGate((segment_id, "allocation_write")):
            # 严格按刚压低后的临时优先与让路时快照重算，不沿用让路前次序
            result = _build_result(pv.width_m, pv.segment_meta, pv.pillars, pv.vendors,
                                   override=pv.priority_override)
            run = AllocationRun(segment_id=segment_id, created_at=datetime.utcnow(),
                                result_json=json.dumps(result, ensure_ascii=False))
            db.add(run)
            db.commit()
            db.refresh(run)
    except GateError as e:
        db.rollback()
        restore_preview()
        raise HTTPException(e.status_code, {"code": e.code, "detail": e.detail})

    return {"id": run.id, **result}


@router.post("/yield/cancel")
def cancel_yield(segment_id: int = 1):
    with _previews_lock:
        pv = _previews.pop(segment_id, None)
    return {"cancelled": pv is not None}
