from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.orm import Session
from app.database import get_db
from app.models.models import MarketDay
router = APIRouter(prefix="/days", tags=["days"])

@router.get("")
def list_days(db: Session = Depends(get_db)):
    return [
        {
            "id": r.id,
            "name": r.name,
            "day": r.day.isoformat(),
            "alloc_open_at": r.alloc_open_at.isoformat() if r.alloc_open_at else None,
            "alloc_close_at": r.alloc_close_at.isoformat() if r.alloc_close_at else None,
        }
        for r in db.scalars(select(MarketDay).order_by(MarketDay.id)).all()
    ]
