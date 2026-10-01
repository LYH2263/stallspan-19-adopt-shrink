from datetime import date, datetime
from sqlalchemy import func, select
from sqlalchemy.orm import Session
from app.models.models import MarketDay, Pillar, Segment, Vendor
from app.services.schema_bootstrap import DEFAULT_CLOSE, DEFAULT_OPEN

# (name, stall_width_m, priority)
GREEN_VENDORS = [
    ("阿强烧烤", 4.0, 1), ("林记糖水", 3.0, 1), ("老周水果", 5.0, 2),
    ("小美饰品", 2.5, 2), ("大碗面", 6.0, 1), ("手作皮具", 3.5, 3),
    ("巨型舞台车", 12.0, 9), ("流浪咖啡车", 9.0, 8),
]


def ensure_seed(db: Session) -> None:
    """幂等播种：空库建绿仓全套；旧库补齐可分配时段窗与缺失摊主（按名去重）。"""
    count = db.scalar(select(func.count()).select_from(MarketDay)) or 0
    if count == 0:
        day = MarketDay(name="周末夜市", day=date(2026, 9, 20),
                        alloc_open_at=DEFAULT_OPEN, alloc_close_at=DEFAULT_CLOSE)
        db.add(day); db.flush()
        seg = Segment(market_day_id=day.id, name="东街段", width_m=30.0)
        db.add(seg); db.flush()
        db.add(Pillar(segment_id=seg.id, position_m=10.0, thickness_m=0.5, label="灯柱A"))
        db.add(Pillar(segment_id=seg.id, position_m=20.0, thickness_m=0.5, label="灯柱B"))
        for name, wdt, pri in GREEN_VENDORS:
            db.add(Vendor(market_day_id=day.id, name=name, stall_width_m=wdt, priority=pri))
        db.commit()
        return

    # 旧库：回填窗口。
    days = db.scalars(select(MarketDay)).all()
    changed = False
    for day in days:
        if day.alloc_open_at is None:
            day.alloc_open_at = DEFAULT_OPEN; changed = True
        if day.alloc_close_at is None:
            day.alloc_close_at = DEFAULT_CLOSE; changed = True
    # 旧库：按名补齐缺失摊主（绿仓新增的流浪咖啡车等）。
    existing_names = {
        row[0]
        for row in db.execute(select(Vendor.name)).all()
    }
    for day in days:
        for name, wdt, pri in GREEN_VENDORS:
            if name not in existing_names:
                db.add(Vendor(market_day_id=day.id, name=name, stall_width_m=wdt, priority=pri))
                existing_names.add(name)
                changed = True
    if changed:
        db.commit()


def seed_if_empty(db: Session) -> None:
    ensure_seed(db)
