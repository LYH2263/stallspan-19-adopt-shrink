from datetime import date

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, func, select
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.database import Base, get_db
from app.main import app
from app.api import allocate as alloc_api
from app.models.models import AllocationRun, MarketDay, Pillar, Segment, Vendor
from app.services import gates

PILLARS = [
    {"position_m": 10.0, "thickness_m": 0.5},
    {"position_m": 20.0, "thickness_m": 0.5},
]
MID = {"span_lo": 10.25, "span_hi": 19.75}


@pytest.fixture()
def client():
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    TestSession = sessionmaker(bind=engine, autoflush=False)

    def _override_get_db():
        db = TestSession()
        try:
            yield db
        finally:
            db.close()

    app.dependency_overrides[get_db] = _override_get_db
    gates._reset_for_tests()
    with alloc_api._previews_lock:
        alloc_api._previews.clear()

    # 街段1（窗内）：让路成功场景
    with TestSession() as db:
        d1 = MarketDay(name="今日集", day=date.today())
        db.add(d1); db.flush()
        s1 = Segment(market_day_id=d1.id, name="成功段", width_m=30.0)
        db.add(s1); db.flush()
        for p in PILLARS:
            db.add(Pillar(segment_id=s1.id, **p))
        for name, w, pri in [
            ("A", 4.0, 1), ("B", 4.0, 1), ("N", 5.5, 1), ("M", 4.0, 1),
            ("C", 9.75, 2), ("T", 6.0, 3),
        ]:
            db.add(Vendor(market_day_id=d1.id, name=name, stall_width_m=w, priority=pri))

        # 街段2（窗外）：同样可让路，确认必须被闸门拒绝
        d2 = MarketDay(name="远古集", day=date(2000, 1, 1))
        db.add(d2); db.flush()
        s2 = Segment(market_day_id=d2.id, name="窗外段", width_m=30.0)
        db.add(s2); db.flush()
        for p in PILLARS:
            db.add(Pillar(segment_id=s2.id, **p))
        for name, w, pri in [
            ("A", 4.0, 1), ("B", 4.0, 1), ("N", 5.5, 1), ("M", 4.0, 1),
            ("C", 9.75, 2), ("T", 6.0, 3),
        ]:
            db.add(Vendor(market_day_id=d2.id, name=name, stall_width_m=w, priority=pri))

        # 街段3（窗内）：无邻失败 + 有邻但空档不够
        d3 = MarketDay(name="失败集", day=date.today())
        db.add(d3); db.flush()
        s3 = Segment(market_day_id=d3.id, name="失败段", width_m=30.0)
        db.add(s3); db.flush()
        for p in PILLARS:
            db.add(Pillar(segment_id=s3.id, **p))
        for name, w, pri in [
            ("A", 9.75, 1), ("X", 3.0, 1), ("Big", 9.9, 1),
            ("B", 6.5, 1), ("C", 9.75, 2), ("U", 9.9, 3),
        ]:
            db.add(Vendor(market_day_id=d3.id, name=name, stall_width_m=w, priority=pri))
        db.commit()

    # 不进入 lifespan，避免全局 Postgres engine 的建表/播种
    c = TestClient(app)
    c.headers_ = {}  # noqa
    yield c, TestSession

    app.dependency_overrides.clear()
    gates._reset_for_tests()
    with alloc_api._previews_lock:
        alloc_api._previews.clear()


def _run_count(Session, segment_id: int) -> int:
    with Session() as db:
        return db.scalar(select(func.count()).select_from(AllocationRun).where(AllocationRun.segment_id == segment_id))


def _priority_snapshot(Session, market_day_id: int) -> dict:
    with Session() as db:
        return {v.name: v.priority for v in db.scalars(
            select(Vendor).where(Vendor.market_day_id == market_day_id)).all()}


# ---------- 让路成功：零写运行行、双击不增行、确认落一行、登记优先不动 ----------

def test_yield_writes_no_run_row_and_double_click_keeps_count(client):
    c, Session = client
    baseline = c.get("/api/allocate/latest?segment_id=1").json()
    assert baseline["id"] == 1
    assert {r["vendor_name"] for r in baseline["rejected"]} == {"T"}

    r1 = c.post("/api/allocate/yield?segment_id=1", json={"vendor_id": 6, **MID})
    assert r1.status_code == 200
    body1 = r1.json()
    assert body1["id"] is None  # 预览没有运行行 id
    assert _run_count(Session, 1) == 1  # 让路零写运行行

    # 连点第二次让路：运行条数相对让路前不动，禁止半成功增行
    r2 = c.post("/api/allocate/yield?segment_id=1", json={"vendor_id": 6, **MID})
    assert r2.status_code == 200
    assert _run_count(Session, 1) == 1

    # 三处同一套结论：/yield 响应与随后 /latest（主图、放不下、临时优先共用）完全一致
    latest = c.get("/api/allocate/latest?segment_id=1").json()
    assert latest["id"] is None
    assert latest["placements"] == body1["placements"]
    assert latest["rejected"] == body1["rejected"]
    assert latest["priority_override"] == {"3": 3.5, "4": 3.5}

    names_placed = {p["vendor_name"] for p in body1["placements"]}
    names_rejected = {r["vendor_name"] for r in body1["rejected"]}
    assert "T" in names_placed and "T" not in names_rejected       # 图上已进
    assert {"N", "M"} <= names_rejected                             # 放不下挂让路摊
    # 登记优先未被临时值写回
    assert _priority_snapshot(Session, 1) == {
        "A": 1, "B": 1, "N": 1, "M": 1, "C": 2, "T": 3}


def test_confirm_persists_one_row_with_temp_priority_and_clears_preview(client):
    c, Session = client
    c.get("/api/allocate/latest?segment_id=1")
    preview = c.post("/api/allocate/yield?segment_id=1", json={"vendor_id": 6, **MID}).json()

    r = c.post("/api/allocate/confirm?segment_id=1")
    assert r.status_code == 200
    confirmed = r.json()
    assert confirmed["id"] == 2
    assert _run_count(Session, 1) == 2  # 只落一行
    # 确认结论与预览（刚压低后的临时优先）一致，不沿用让路前次序
    assert confirmed["placements"] == preview["placements"]
    assert confirmed["rejected"] == preview["rejected"]

    latest = c.get("/api/allocate/latest?segment_id=1").json()
    assert latest["id"] == 2
    assert "yield_preview" not in latest
    assert latest["priority_override"] == {"3": 3.5, "4": 3.5}
    # 再确认即无预览
    again = c.post("/api/allocate/confirm?segment_id=1")
    assert again.status_code == 400
    assert again.json()["detail"]["code"] == "no_preview"
    assert _run_count(Session, 1) == 2


# ---------- 失败：无邻可压 ≠ 空档不够；登记优先/预览/运行行不动 ----------

def test_no_neighbor_failure_is_distinct_from_space(client):
    c, Session = client
    before = _priority_snapshot(Session, 3)
    r = c.post("/api/allocate/yield?segment_id=3", json={"vendor_id": 15, **MID})  # Big pri1
    assert r.status_code == 409
    err = r.json()["detail"]
    assert err["code"] == "no_neighbor"
    assert "空档" not in err["detail"] and "净空" not in err["detail"]
    assert _run_count(Session, 3) == 0          # 失败不写运行行
    assert _priority_snapshot(Session, 3) == before  # 不偷改邻摊登记优先


def test_insufficient_space_failure(client):
    c, Session = client
    before = _priority_snapshot(Session, 3)
    r = c.post("/api/allocate/yield?segment_id=3", json={"vendor_id": 18, **MID})  # U pri3
    assert r.status_code == 409
    err = r.json()["detail"]
    assert err["code"] == "insufficient_space"
    assert "净空仍放不下" in err["detail"]
    assert {s["vendor_id"] for s in err["suppressed"]} == {14, 16}
    assert _run_count(Session, 3) == 0
    assert _priority_snapshot(Session, 3) == before


# ---------- 闸门：窗外确认拒绝、预览保留、旧运行不丢；写闸 409 ----------

def test_outside_window_confirm_rejected_but_preview_and_runs_survive(client):
    c, Session = client
    # 窗外段预置一条让路前已成功的运行行
    with Session() as db:
        seg = db.scalar(select(Segment).where(Segment.name == "窗外段"))
        db.add(AllocationRun(segment_id=seg.id, result_json='{"placements": [], "rejected": []}'))
        db.commit()
    seg2 = 2
    assert _run_count(Session, seg2) == 1

    # 窗外允许试算让路（预览不落库）
    r = c.post(f"/api/allocate/yield?segment_id={seg2}", json={"vendor_id": 12, **MID})
    assert r.status_code == 200
    assert r.json()["id"] is None
    assert _run_count(Session, seg2) == 1

    # 确认被时段窗拒绝
    cf = c.post(f"/api/allocate/confirm?segment_id={seg2}")
    assert cf.status_code == 403
    assert cf.json()["detail"]["code"] == "outside_allocation_window"
    assert _run_count(Session, seg2) == 1  # 闸门拒绝不增行、不清旧运行

    # 预览仍在，主图/放不下继续展示让路结论
    latest = c.get(f"/api/allocate/latest?segment_id={seg2}").json()
    assert latest["id"] is None
    assert "T" in {p["vendor_name"] for p in latest["placements"]}

    # 窗外正式重算也被闸
    run = c.post(f"/api/allocate/run?segment_id={seg2}")
    assert run.status_code == 403
    assert _run_count(Session, seg2) == 1

    # 取消预览后，让路前那条旧运行原样还在
    c.post(f"/api/allocate/yield/cancel?segment_id={seg2}")
    latest2 = c.get(f"/api/allocate/latest?segment_id={seg2}").json()
    assert latest2["id"] == 1
    assert latest2["placements"] == []


def test_write_gate_conflict_then_release_allows_confirm(client):
    c, Session = client
    c.get("/api/allocate/latest?segment_id=1")  # 建让路前已成功的基线运行行
    c.post("/api/allocate/yield?segment_id=1", json={"vendor_id": 6, **MID})
    g = gates.acquire_write_gate(1, "allocation_write")
    try:
        r = c.post("/api/allocate/confirm?segment_id=1")
        assert r.status_code == 409
        assert r.json()["detail"]["code"] == "write_gate_open"
    finally:
        g.__exit__(None, None, None)
    # 写闸拒绝同样不毁预览
    latest = c.get("/api/allocate/latest?segment_id=1").json()
    assert latest["id"] is None
    # 释放后确认成功
    ok = c.post("/api/allocate/confirm?segment_id=1")
    assert ok.status_code == 200
    assert _run_count(Session, 1) == 2


def test_cancel_yield_returns_to_last_run(client):
    c, Session = client
    c.get("/api/allocate/latest?segment_id=1")
    c.post("/api/allocate/yield?segment_id=1", json={"vendor_id": 6, **MID})
    r = c.post("/api/allocate/yield/cancel?segment_id=1")
    assert r.json()["cancelled"] is True
    latest = c.get("/api/allocate/latest?segment_id=1").json()
    assert latest["id"] == 1
    assert "priority_override" not in latest
    assert {"T"} == {x["vendor_name"] for x in latest["rejected"]}


def test_run_recomputes_and_discards_preview(client):
    c, Session = client
    c.get("/api/allocate/latest?segment_id=1")
    c.post("/api/allocate/yield?segment_id=1", json={"vendor_id": 6, **MID})
    r = c.post("/api/allocate/run?segment_id=1")
    assert r.status_code == 200
    assert "priority_override" not in r.json()
    assert {"T"} == {x["vendor_name"] for x in r.json()["rejected"]}
    latest = c.get("/api/allocate/latest?segment_id=1").json()
    assert latest["id"] == r.json()["id"]
    assert "yield_preview" not in latest
