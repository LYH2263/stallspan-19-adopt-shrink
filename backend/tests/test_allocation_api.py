from datetime import datetime

import pytest
from fastapi.testclient import TestClient

from app.models.models import AllocationDraft, AllocationRun, MarketDay, Vendor
from app.services import allocation_service as svc


def _ids(rows, key="vendor_id"):
    return [r[key] for r in rows]


def _run_count(db) -> int:
    return db.query(AllocationRun).count()


# ----------------------------- GET /state ---------------------------------- #
def test_state_is_green_baseline_and_writes_nothing(client, db):
    before = _run_count(db)
    res = client.get("/api/allocate/state?segment_id=1")
    assert res.status_code == 200
    data = res.json()
    assert _ids(data["placements"]) == [1, 2, 5, 3, 4, 6]
    assert _ids(data["rejected"]) == [8, 7]
    # 全员临时优先 == 登记优先
    for v in data["vendors"]:
        assert v["temp_priority"] == float(v["priority"])
    assert data["latest_run_id"] is None
    assert _run_count(db) == before  # 纯读，零运行行


def test_state_404_for_missing_segment(client):
    res = client.get("/api/allocate/state?segment_id=999")
    assert res.status_code == 404


# ----------------------------- 让路成功 ------------------------------------- #
def test_yield_success_three_views_align_no_run_row(client, db):
    res = client.post("/api/allocate/yield/8?segment_id=1")
    assert res.status_code == 200, res.text
    data = res.json()
    # 主图与放不下来自同一结论：8 入主图，3 转入放不下，二者不重叠
    assert 8 in _ids(data["placements"])
    assert 8 not in _ids(data["rejected"])
    assert 3 in _ids(data["rejected"])
    assert 7 in _ids(data["rejected"])
    # 临时优先视图同一套：老周登记 2，本轮被压到 10；咖啡车自身优先不变
    vendors = {v["id"]: v for v in data["vendors"]}
    assert vendors[3]["priority"] == 2 and vendors[3]["temp_priority"] == 10.0
    assert vendors[8]["temp_priority"] == 8.0
    # 让路零写运行行，只写草稿
    assert _run_count(db) == 0
    assert db.query(AllocationDraft).count() == 1
    # 登记优先绝未被写回
    db.expire_all()
    assert db.get(Vendor, 3).priority == 2


def test_repeat_yield_is_noop_and_adds_no_row(client, db):
    client.post("/api/allocate/yield/8?segment_id=1")
    draft = db.query(AllocationDraft).one()
    overrides_after_first = draft.overrides_json
    runs_after_first = _run_count(db)

    res2 = client.post("/api/allocate/yield/8?segment_id=1")
    assert res2.status_code == 200
    db.expire_all()
    draft2 = db.query(AllocationDraft).one()
    assert draft2.overrides_json == overrides_after_first  # 无二次写入
    assert _run_count(db) == runs_after_first


def test_yield_too_wide_is_409_and_state_untouched(client, db):
    before_state = client.get("/api/allocate/state?segment_id=1").json()
    res = client.post("/api/allocate/yield/7?segment_id=1")
    assert res.status_code == 409
    detail = res.json()["detail"]
    assert detail["code"] == "vendor_too_wide"
    assert "空档不够" not in detail["message"]
    # 图、放不下、登记、草稿、运行行全部保持改前
    after = client.get("/api/allocate/state?segment_id=1").json()
    assert _ids(after["placements"]) == _ids(before_state["placements"])
    assert _ids(after["rejected"]) == _ids(before_state["rejected"])
    assert db.query(AllocationDraft).count() == 0
    assert _run_count(db) == 0


def test_reset_returns_to_green(client, db):
    client.post("/api/allocate/yield/8?segment_id=1")
    assert db.query(AllocationDraft).count() == 1
    res = client.post("/api/allocate/reset?segment_id=1")
    assert res.status_code == 200
    data = res.json()
    assert _ids(data["rejected"]) == [8, 7]
    assert db.query(AllocationDraft).count() == 0
    assert _run_count(db) == 0


# ----------------------------- 闸门 / 确认 ---------------------------------- #
def test_confirm_outside_window_rejected_and_preserves_everything(client, db):
    # 先让路造草稿、再确认造一条正式运行
    client.post("/api/allocate/yield/8?segment_id=1")
    ok = client.post("/api/allocate/confirm?segment_id=1")
    assert ok.status_code == 200
    runs_before = _run_count(db)
    draft_overrides = db.query(AllocationDraft).one().overrides_json

    # 把窗移到过去
    day = db.get(MarketDay, 1)
    day.alloc_open_at = datetime(2000, 1, 1)
    day.alloc_close_at = datetime(2001, 1, 1)
    db.commit()

    res = client.post("/api/allocate/confirm?segment_id=1")
    assert res.status_code == 409
    detail = res.json()["detail"]
    assert detail["code"] == "outside_window"
    # 不增运行行、不清既有运行、不清草稿
    assert _run_count(db) == runs_before
    assert db.query(AllocationDraft).one().overrides_json == draft_overrides


def test_confirm_window_unset_is_409(client, db):
    day = db.get(MarketDay, 1)
    day.alloc_open_at = None
    day.alloc_close_at = None
    db.commit()
    res = client.post("/api/allocate/confirm?segment_id=1")
    assert res.status_code == 409
    assert res.json()["detail"]["code"] == "window_unset"
    assert _run_count(db) == 0


def test_confirm_lock_open_is_409_without_extra_row(client, db):
    lock = svc.get_segment_lock(1)
    assert lock.acquire(blocking=False)
    try:
        res = client.post("/api/allocate/confirm?segment_id=1")
        assert res.status_code == 409
        assert res.json()["detail"]["code"] == "lock_open"
        assert _run_count(db) == 0
    finally:
        lock.release()


def test_confirm_uses_temp_priority_and_is_idempotent(client, db):
    # 让路后确认：落恰好一行，且按压低后的次序（老周最后处理 -> rejected 尾）
    client.post("/api/allocate/yield/8?segment_id=1")
    res = client.post("/api/allocate/confirm?segment_id=1")
    assert res.status_code == 200
    body = res.json()
    assert body["idempotent"] is False
    assert _run_count(db) == 1
    assert 8 in _ids(body["placements"])
    assert _ids(body["rejected"]) == [7, 3]

    # 再确认：结论相同 -> 幂等，不增行
    res2 = client.post("/api/allocate/confirm?segment_id=1")
    assert res2.status_code == 200
    assert res2.json()["idempotent"] is True
    assert _run_count(db) == 1

    # 重置让路后结论变化 -> 新落一行
    client.post("/api/allocate/reset?segment_id=1")
    res3 = client.post("/api/allocate/confirm?segment_id=1")
    assert res3.json()["idempotent"] is False
    assert _run_count(db) == 2
    assert _ids(res3.json()["rejected"]) == [8, 7]


def test_service_now_injection_window_bounds(db):
    # 直接对 service 注入 now，验证边界含等号与窗外拒绝，且不增行
    svc.confirm(db, 1, now=datetime(2020, 1, 1))  # 恰好开窗时刻 -> 允许
    assert _run_count(db) == 1
    with pytest.raises(svc.AllocationError) as ei:
        svc.confirm(db, 1, now=datetime(2100, 1, 2))
    assert ei.value.code == "outside_window"
    assert _run_count(db) == 1  # 拒绝不增行


# ----------------------------- latest -------------------------------------- #
def test_latest_null_when_no_run_and_no_side_effect(client, db):
    res = client.get("/api/allocate/latest?segment_id=1")
    assert res.status_code == 200
    assert res.json() is None
    assert _run_count(db) == 0  # 旧实现会顺手造一行，这里必须纯读


def test_latest_returns_confirmed_run(client):
    body = client.post("/api/allocate/confirm?segment_id=1").json()
    res = client.get("/api/allocate/latest?segment_id=1")
    assert res.status_code == 200
    latest = res.json()
    assert latest["id"] == body["run_id"]
    assert _ids(latest["rejected"]) == [8, 7]


def test_vendor_not_found_404(client):
    res = client.post("/api/allocate/yield/999?segment_id=1")
    assert res.status_code == 404
