"""让路（yield）：放不下的摊主要求同一柱间内、登记优先严格更低的邻摊在本轮临时让路。

约束：
- 只在本轮临时优先上压低邻摊（数值抬到请求摊之后），绝不改写摊主登记优先；
- 无邻可压 -> no_neighbor（不得写成空档不够）；有邻但压完仍放不下 -> insufficient_space；
- 任何失败都返回 None，调用方必须保持改前结论，不得半成功。
"""
from __future__ import annotations

from dataclasses import dataclass, field

from app.services.first_fit_engine import (
    AllocResult,
    allocate_first_fit,
    free_spans_from_pillars,
)

# 让路后邻摊临时优先 = 请求摊登记优先 + 该步长：恰好排在请求摊之后一档
YIELD_STEP = 0.5
EPS = 1e-9


@dataclass
class YieldOutcome:
    status: str  # success | no_neighbor | insufficient_space | not_rejected | span_not_found
    message: str
    result: AllocResult | None = None
    priority_override: dict[int, float] = field(default_factory=dict)
    target_vendor_id: int | None = None
    suppressed: list[dict] = field(default_factory=list)  # 被临时压低的邻摊登记信息


def spans_for_vendor(width_m: float, pillars: list[dict], need: float) -> list[tuple[float, float]]:
    """该摊理论上可进的柱间（净长够即可，不管当前被占）。"""
    return [(a, b) for a, b in free_spans_from_pillars(width_m, pillars) if b - a + EPS >= need]


def _placement_span_index(p: object, spans: list[tuple[float, float]]) -> int:
    for i, (lo, hi) in enumerate(spans):
        if p.start_m + EPS >= lo and p.end_m <= hi + EPS:
            return i
    return -1


def attempt_yield(
    width_m: float,
    vendors: list[dict],
    pillars: list[dict],
    target_vendor_id: int,
    span_lo: float,
    span_hi: float,
) -> YieldOutcome:
    by_id = {v["id"]: v for v in vendors}
    target = by_id.get(target_vendor_id)
    if target is None:
        return YieldOutcome("not_rejected", "摊主不存在")

    spans = free_spans_from_pillars(width_m, pillars)
    target_span = next(((a, b) for a, b in spans if abs(a - span_lo) < 1e-6 and abs(b - span_hi) < 1e-6), None)
    if target_span is None:
        return YieldOutcome("span_not_found", "目标柱间不存在或已变化，请重新选择")

    baseline = allocate_first_fit(width_m, vendors, pillars)
    if not any(x.vendor_id == target_vendor_id for x in baseline.rejected):
        return YieldOutcome("not_rejected", "该摊当前已在主图中，无需让路", target_vendor_id=target_vendor_id)

    lo, hi = target_span
    # 同一目标柱间内、登记优先严格低于请求摊（数值更小=排更前）的已进图邻摊
    neighbors = [
        p for p in baseline.placements
        if p.start_m + EPS >= lo and p.end_m <= hi + EPS
        and by_id[p.vendor_id]["priority"] < target["priority"]
    ]
    if not neighbors:
        return YieldOutcome(
            "no_neighbor",
            f"目标柱间 {lo:g}–{hi:g} m 内没有登记优先低于 {target['name']}（优先 {target['priority']}）的邻摊可压",
            target_vendor_id=target_vendor_id,
        )

    # 临时优先只在本轮生效：把这些邻摊统一压到请求摊之后，绝不写回登记值
    temp_priority = float(target["priority"]) + YIELD_STEP
    override = {p.vendor_id: temp_priority for p in neighbors}
    suppressed = [
        {
            "vendor_id": p.vendor_id,
            "vendor_name": p.vendor_name,
            "registered_priority": by_id[p.vendor_id]["priority"],
            "temp_priority": temp_priority,
        }
        for p in neighbors
    ]

    rerun = allocate_first_fit(width_m, vendors, pillars, priority_override=override)
    if not any(p.vendor_id == target_vendor_id for p in rerun.placements):
        return YieldOutcome(
            "insufficient_space",
            f"已压低 {len(neighbors)} 个邻摊临时让路，但柱间 {lo:g}–{hi:g} m 净空仍放不下 {target['stall_width_m']} m",
            target_vendor_id=target_vendor_id,
            suppressed=suppressed,
        )

    return YieldOutcome(
        "success",
        f"让路成功：{len(neighbors)} 个邻摊本轮临时排后，{target['name']} 改入主图（待正式确认落库）",
        result=rerun,
        priority_override=override,
        target_vendor_id=target_vendor_id,
        suppressed=suppressed,
    )
