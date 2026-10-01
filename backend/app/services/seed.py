from datetime import date
from sqlalchemy import func, select
from sqlalchemy.orm import Session
from app.models.models import MarketDay, Pillar, Segment, Vendor

def seed_if_empty(db: Session) -> None:
    if (db.scalar(select(func.count()).select_from(MarketDay)) or 0) > 0:
        return
    day = MarketDay(name="周末夜市", day=date(2026, 9, 20))
    db.add(day); db.flush()
    seg = Segment(market_day_id=day.id, name="东街段", width_m=30.0)
    db.add(seg); db.flush()
    db.add(Pillar(segment_id=seg.id, position_m=8.0, thickness_m=0.5, label="灯柱A"))
    db.add(Pillar(segment_id=seg.id, position_m=18.0, thickness_m=0.5, label="灯柱B"))
    # 三柱间净长：[0,7.75]=7.75  [8.25,17.75]=9.5  [18.25,30]=11.75
    # p1 摊按序恰好钉满三柱间；后四摊基线放不下，分别覆盖让路的三种结局与“无柱间可容”：
    #  流动花车 p3 选中柱间让路 → 成功（临时压低陈氏卤味/麦叔煎饼，不写回登记）
    #  大鼓车   p1 只放得下被同优先长龙凉菜车占满的柱间 → 无邻可压（不是空档不够）
    #  加长布匹 p5 压完邻摊后，p3 花车仍先进中跨占 6m，剩 3.5m → 有邻但空档不够
    #  巨型舞台车 12m 超过所有柱间净长 → 无柱间放得下，不允许让路
    vendors = [
        ("阿强烧烤", 4.0, 1), ("林记糖水", 3.75, 1),
        ("陈氏卤味", 5.5, 1), ("麦叔煎饼", 4.0, 1),
        ("长龙凉菜车", 11.75, 1), ("大鼓车", 9.7, 1),
        ("流动花车", 6.0, 3), ("加长布匹摊", 7.5, 5), ("巨型舞台车", 12.0, 9),
    ]
    for name, wdt, pri in vendors:
        db.add(Vendor(market_day_id=day.id, name=name, stall_width_m=wdt, priority=pri))
    db.commit()
