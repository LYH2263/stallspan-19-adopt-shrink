import json

from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.database import get_db
from app.models.models import AllocationRun
from app.services import allocation_service as svc

router = APIRouter(prefix="/allocate", tags=["allocate"])


@router.get("/state")
def state(segment_id: int = 1, db: Session = Depends(get_db)):
    """现算结论（有让路草稿则含本轮临时优先）。纯读，不写运行行。"""
    return svc.get_state(db, segment_id)


@router.post("/yield/{vendor_id}")
def yield_for(vendor_id: int, segment_id: int = 1, db: Session = Depends(get_db)):
    """对某条放不下的摊让路：压邻摊本轮临时优先并重算。零写运行行；失败 409 且三态保持。"""
    return svc.yield_vendor(db, segment_id, vendor_id)


@router.post("/reset")
def reset(segment_id: int = 1, db: Session = Depends(get_db)):
    """清空本轮临时优先，回到绿仓基线。不写运行行。"""
    return svc.reset_draft(db, segment_id)


@router.post("/confirm")
def confirm(segment_id: int = 1, db: Session = Depends(get_db)):
    """正式确认：过时段窗 + 写闸后服务端按（含临时优先的）次序重算，幂等落恰好一条运行行。"""
    return svc.confirm(db, segment_id)


@router.get("/latest")
def latest(segment_id: int = 1, db: Session = Depends(get_db)):
    """最近一条正式运行；无则返回 null。纯读，绝不副作用式造行。"""
    run = db.scalars(
        select(AllocationRun).where(AllocationRun.segment_id == segment_id)
        .order_by(AllocationRun.id.desc())
    ).first()
    if run is None:
        return None
    return {"id": run.id, "created_at": run.created_at.isoformat(), **json.loads(run.result_json)}
