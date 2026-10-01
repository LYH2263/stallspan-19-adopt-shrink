from app.services.first_fit_engine import allocate_first_fit, result_to_dict
from app.services.yield_service import attempt_yield

PILLARS = [
    {"position_m": 10.0, "thickness_m": 0.5},
    {"position_m": 20.0, "thickness_m": 0.5},
]
# 三跨净长：[0,9.75]=9.75  [10.25,19.75]=9.5  [20.25,30]=9.75
MID = (10.25, 19.75)


def success_case_vendors():
    # A/B 占跨1 剩1.75；N/M 占满中跨；C 占满跨3；T(pri3,w6) 基线放不下
    return [
        {"id": 1, "name": "A", "stall_width_m": 4.0, "priority": 1},
        {"id": 2, "name": "B", "stall_width_m": 4.0, "priority": 1},
        {"id": 3, "name": "N", "stall_width_m": 5.5, "priority": 1},
        {"id": 4, "name": "M", "stall_width_m": 4.0, "priority": 1},
        {"id": 5, "name": "C", "stall_width_m": 9.75, "priority": 2},
        {"id": 6, "name": "T", "stall_width_m": 6.0, "priority": 3},
    ]


def test_override_changes_order_and_gets_target_placed():
    vendors = success_case_vendors()
    baseline = allocate_first_fit(30.0, vendors, PILLARS)
    assert {p.vendor_id for p in baseline.placements} == {1, 2, 3, 4, 5}
    assert [r.vendor_id for r in baseline.rejected] == [6]

    out = attempt_yield(30.0, vendors, PILLARS, 6, MID[0], MID[1])
    assert out.status == "success"
    placed = {p.vendor_id for p in out.result.placements}
    rejected = {r.vendor_id for r in out.result.rejected}
    # T 改入主图；让路的 N/M 挂到放不下
    assert 6 in placed
    assert 6 not in rejected
    assert {3, 4} <= rejected
    # 临时优先：邻摊统一压到请求摊之后一档
    assert out.priority_override == {3: 3.5, 4: 3.5}


def test_temp_priority_never_writes_back_to_registered():
    vendors = success_case_vendors()
    snapshot = {v["id"]: v["priority"] for v in vendors}
    attempt_yield(30.0, vendors, PILLARS, 6, MID[0], MID[1])
    assert {v["id"]: v["priority"] for v in vendors} == snapshot
    assert all(isinstance(v["priority"], int) for v in vendors)


def test_no_lower_priority_neighbor_is_no_neighbor_not_space():
    # A 占满跨1 把 X 挤进中跨；Big 登记优先也是 1，没有比它更低的邻摊
    vendors = [
        {"id": 1, "name": "A", "stall_width_m": 9.75, "priority": 1},
        {"id": 2, "name": "X", "stall_width_m": 3.0, "priority": 1},
        {"id": 9, "name": "Big", "stall_width_m": 9.9, "priority": 1},
    ]
    baseline = allocate_first_fit(30.0, vendors, PILLARS)
    assert [r.vendor_id for r in baseline.rejected] == [9]

    out = attempt_yield(30.0, vendors, PILLARS, 9, MID[0], MID[1])
    assert out.status == "no_neighbor"
    assert out.result is None
    assert out.priority_override == {}
    # 无邻失败不得写成空档不够
    assert "空档" not in out.message and "净空" not in out.message
    assert "没有登记优先低于" in out.message


def test_neighbors_but_still_too_wide_is_insufficient_space():
    vendors = [
        {"id": 1, "name": "A", "stall_width_m": 9.75, "priority": 1},
        {"id": 2, "name": "X", "stall_width_m": 3.0, "priority": 1},
        {"id": 3, "name": "B", "stall_width_m": 6.5, "priority": 1},
        {"id": 4, "name": "C", "stall_width_m": 9.75, "priority": 2},
        {"id": 5, "name": "U", "stall_width_m": 9.9, "priority": 3},
    ]
    out = attempt_yield(30.0, vendors, PILLARS, 5, MID[0], MID[1])
    assert out.status == "insufficient_space"
    assert out.result is None
    assert {s["vendor_id"] for s in out.suppressed} == {2, 3}
    assert "净空仍放不下" in out.message


def test_yield_for_already_placed_is_rejected():
    vendors = success_case_vendors()
    out = attempt_yield(30.0, vendors, PILLARS, 1, MID[0], MID[1])
    assert out.status == "not_rejected"


def test_baseline_shape_unchanged_without_override():
    # 未让路：响应形状与绿仓一致，无临时优先覆盖表，placement 无额外字段
    vendors = success_case_vendors()
    r = allocate_first_fit(30.0, vendors, PILLARS)
    d = result_to_dict(r)
    assert "priority_override" not in d
    assert set(d["placements"][0].keys()) == {"vendor_id", "vendor_name", "start_m", "end_m", "width_m"}
    # 显式空覆盖也不下发
    assert "priority_override" not in result_to_dict(r, priority_override={})
