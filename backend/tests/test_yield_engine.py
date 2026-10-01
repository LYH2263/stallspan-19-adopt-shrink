"""让路(yield)纯引擎测试：绿仓黄金基线、临时优先、失败分类、回流反例、确定性。"""
from app.services.first_fit_engine import (
    allocate_first_fit,
    apply_yield_overrides,
    effective_priority,
    free_spans_from_pillars,
    plan_yield,
    with_effective_priority,
)

# 绿仓：30m 东街段，两柱 @10/@20 厚 0.5 -> 柱间 9.75 / 9.5 / 9.75
GREEN_PILLARS = [
    {"position_m": 10.0, "thickness_m": 0.5},
    {"position_m": 20.0, "thickness_m": 0.5},
]
GREEN_VENDORS = [
    {"id": 1, "name": "阿强烧烤", "stall_width_m": 4.0, "priority": 1},
    {"id": 2, "name": "林记糖水", "stall_width_m": 3.0, "priority": 1},
    {"id": 3, "name": "老周水果", "stall_width_m": 5.0, "priority": 2},
    {"id": 4, "name": "小美饰品", "stall_width_m": 2.5, "priority": 2},
    {"id": 5, "name": "大碗面", "stall_width_m": 6.0, "priority": 1},
    {"id": 6, "name": "手作皮具", "stall_width_m": 3.5, "priority": 3},
    {"id": 7, "name": "巨型舞台车", "stall_width_m": 12.0, "priority": 9},
    {"id": 8, "name": "流浪咖啡车", "stall_width_m": 9.0, "priority": 8},
]
W = 30.0


def _ids(rows):
    return [r.vendor_id for r in rows]


def test_green_baseline_pinned():
    """未让路即绿仓：落点、拒绝、空档与登记/临时一致全部钉死。"""
    spans = free_spans_from_pillars(W, GREEN_PILLARS)
    assert spans == [(0.0, 9.75), (10.25, 19.75), (20.25, 30.0)]

    r = allocate_first_fit(W, with_effective_priority(GREEN_VENDORS, {}), GREEN_PILLARS)
    assert [(p.vendor_id, p.start_m, p.end_m) for p in r.placements] == [
        (1, 0.0, 4.0),
        (2, 4.0, 7.0),
        (5, 10.25, 16.25),
        (3, 20.25, 25.25),
        (4, 7.0, 9.5),
        (6, 16.25, 19.75),
    ]
    assert _ids(r.rejected) == [8, 7]
    assert r.free_spans == [(9.5, 9.75), (25.25, 30.0)]
    # 无覆盖时全员有效优先 == 登记优先
    assert all(effective_priority(v, {}) == float(v["priority"]) for v in GREEN_VENDORS)


def test_partition_invariant():
    """每个摊主恰好属于 placements 或 rejected 之一。"""
    r = allocate_first_fit(W, with_effective_priority(GREEN_VENDORS, {}), GREEN_PILLARS)
    placed, rejected = set(_ids(r.placements)), set(_ids(r.rejected))
    assert not (placed & rejected)
    assert placed | rejected == {v["id"] for v in GREEN_VENDORS}


def test_yield_for_coffee_cart():
    plan = plan_yield(W, GREEN_VENDORS, GREEN_PILLARS, {}, 8)
    assert plan.noop is False
    # 目标第三柱间，唯一受害者老周(5m)，被压宽 5
    assert plan.target_span_index == 2
    assert plan.victim_ids == [3]
    assert plan.pushed_width == 5.0
    # 老周临时优先压到队尾（登记 9 的舞台车之后），登记优先不在覆盖中被改写
    assert plan.new_overrides == {3: 10.0}
    assert 8 in _ids(plan.result.placements)
    assert _ids(plan.result.rejected) == [7, 3]
    placed = {p.vendor_id for p in plan.result.placements}
    rejected = {x.vendor_id for x in plan.result.rejected}
    assert not (placed & rejected)
    coffee = next(p for p in plan.result.placements if p.vendor_id == 8)
    assert (coffee.start_m, coffee.end_m) == (20.25, 29.25)
    # 覆盖里只有受害者，X 自身与其他摊主不变
    assert 8 not in plan.new_overrides


def test_repeat_yield_is_noop():
    plan = plan_yield(W, GREEN_VENDORS, GREEN_PILLARS, {}, 8)
    again = plan_yield(W, GREEN_VENDORS, GREEN_PILLARS, plan.new_overrides, 8)
    assert again.noop is True
    assert again.new_overrides == plan.new_overrides
    assert again.victim_ids == []
    # no-op 结论与成功结论一致
    assert _ids(again.result.placements) == _ids(plan.result.placements)


def test_yield_too_wide_failure_is_classified():
    f = plan_yield(W, GREEN_VENDORS, GREEN_PILLARS, {}, 7)
    assert f.code == "vendor_too_wide"
    assert "空档不够" not in f.message
    assert "比任意柱间都宽" in f.message


def test_apply_yield_overrides_pushes_behind_everyone():
    ov = apply_yield_overrides({}, GREEN_VENDORS, [3])
    assert ov == {3: 10.0}
    # 链式第二批：从新的全员最大值继续递增
    ov2 = apply_yield_overrides(ov, GREEN_VENDORS, [4])
    assert ov2 == {3: 10.0, 4: 11.0}


def test_iterative_guided_yield_cross_span_reflow_counterexample():
    """赤字压够但 X 仍不入位的跨柱间接力回流反例：必须靠重算引导继续压回流者。

    3 个等长 10m 柱间；基线 v3、X 被拒。只压 n 会让 v2 回流占住目标柱间，X 仍放不下；
    迭代引导必须继续压 v2（再由 v3 回流后压 v3），最终 X 入第三柱间，受害者 {v2,v3}。
    """
    pillars = [
        {"position_m": 10.1, "thickness_m": 0.2},
        {"position_m": 20.3, "thickness_m": 0.2},
    ]
    vendors = [
        {"id": 1, "name": "A", "stall_width_m": 10.0, "priority": 1},
        {"id": 2, "name": "n", "stall_width_m": 9.0, "priority": 2},
        {"id": 3, "name": "v2", "stall_width_m": 7.0, "priority": 3},
        {"id": 4, "name": "v3", "stall_width_m": 4.0, "priority": 4},
        {"id": 5, "name": "X", "stall_width_m": 10.0, "priority": 5},
    ]
    base = allocate_first_fit(30.4, with_effective_priority(vendors, {}), pillars)
    assert _ids(base.rejected) == [4, 5]
    plan = plan_yield(30.4, vendors, pillars, {}, 5)
    assert plan.noop is False
    assert 5 in _ids(plan.result.placements)
    # 仅压 1 人在本反例中必然失败；引导算法应找到 2 人计划
    assert len(plan.victim_ids) == 2
    assert set(plan.victim_ids) == {3, 4}


def test_determinism():
    signatures = set()
    for _ in range(60):
        p = plan_yield(W, GREEN_VENDORS, GREEN_PILLARS, {}, 8)
        signatures.add((tuple(p.victim_ids), tuple(
            (x.vendor_id, x.start_m) for x in p.result.placements)))
    assert len(signatures) == 1


def test_floating_tolerance():
    # 与最长柱间 9.75 仅差极小量：视为放得下（基线即入位），无需让路
    vendors = [{"id": 1, "name": "tight", "stall_width_m": 9.75 + 1e-10, "priority": 1}]
    r = allocate_first_fit(W, with_effective_priority(vendors, {}), GREEN_PILLARS)
    assert _ids(r.placements) == [1]
