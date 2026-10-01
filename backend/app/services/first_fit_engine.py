"""1D First-Fit stall placement along a street segment; stalls cannot cross pillars.

另含「让路(yield)」纯函数：在不改摊位宽度、不写登记优先的前提下，把目标柱间内挡住某被拒摊位的
邻摊的本轮临时优先压到队尾，并以"用新临时优先实际重算后该摊位是否入位"作为成功唯一判据。
"""
from __future__ import annotations
from dataclasses import asdict, dataclass

EPS_FIT = 1e-9
EPS_SPAN = 1e-6

@dataclass
class Placement:
    vendor_id: int
    vendor_name: str
    start_m: float
    end_m: float
    width_m: float

@dataclass
class Rejected:
    vendor_id: int
    vendor_name: str
    width_m: float
    reason: str

@dataclass
class AllocResult:
    placements: list[Placement]
    rejected: list[Rejected]
    free_spans: list[tuple[float, float]]

def free_spans_from_pillars(width_m: float, pillars: list[dict]) -> list[tuple[float, float]]:
    """pillars: position_m, thickness_m — treated as blocked intervals."""
    blocked = []
    for p in pillars:
        half = p.get("thickness_m", 0.4) / 2.0
        lo = max(0.0, p["position_m"] - half)
        hi = min(width_m, p["position_m"] + half)
        if hi > lo:
            blocked.append((lo, hi))
    blocked.sort()
    merged = []
    for lo, hi in blocked:
        if not merged or lo > merged[-1][1]:
            merged.append([lo, hi])
        else:
            merged[-1][1] = max(merged[-1][1], hi)
    spans = []
    cursor = 0.0
    for lo, hi in merged:
        if lo > cursor:
            spans.append((cursor, lo))
        cursor = hi
    if cursor < width_m:
        spans.append((cursor, width_m))
    return [(round(a, 3), round(b, 3)) for a, b in spans if b - a > EPS_SPAN]

def allocate_first_fit(width_m: float, vendors: list[dict], pillars: list[dict]) -> AllocResult:
    """vendors sorted by priority ascending then id; each needs stall_width_m contiguous in one free span (no pillar cross)."""
    spans = free_spans_from_pillars(width_m, pillars)
    # mutable remaining capacity per span
    remain = [[a, b] for a, b in spans]
    ordered = sorted(vendors, key=lambda v: (v.get("priority", 1), v["id"]))
    placements: list[Placement] = []
    rejected: list[Rejected] = []
    for v in ordered:
        need = float(v["stall_width_m"])
        placed = False
        for span in remain:
            avail = span[1] - span[0]
            if avail + EPS_FIT >= need:
                start = span[0]
                end = start + need
                placements.append(Placement(v["id"], v["name"], round(start, 3), round(end, 3), need))
                span[0] = end
                placed = True
                break
        if not placed:
            rejected.append(Rejected(v["id"], v["name"], need, "无连续空档可放下且不跨越挡柱"))
    free = [(round(a, 3), round(b, 3)) for a, b in remain if b - a > EPS_SPAN]
    return AllocResult(placements, rejected, free)

def result_to_dict(r: AllocResult) -> dict:
    return {
        "placements": [asdict(p) for p in r.placements],
        "rejected": [asdict(x) for x in r.rejected],
        "free_spans": [{"start_m": a, "end_m": b} for a, b in r.free_spans],
    }


# --------------------------------------------------------------------------- #
# 让路（yield）：临时优先 + 重算验收                                            #
# --------------------------------------------------------------------------- #
def effective_priority(vendor: dict, overrides: dict[int, float]) -> float:
    """本轮有效优先：有临时覆盖用覆盖，否则用登记 priority。临时优先绝不写回登记值。"""
    return float(overrides[vendor["id"]]) if vendor["id"] in overrides else float(vendor.get("priority", 1))

def with_effective_priority(vendors: list[dict], overrides: dict[int, float]) -> list[dict]:
    """返回把 priority 字段替换为有效优先(float)的副本列表，供 allocate_first_fit 排序。"""
    out = []
    for v in vendors:
        out.append({**v, "priority": effective_priority(v, overrides)})
    return out

def placement_span_index(placement: Placement, spans: list[tuple[float, float]]) -> int | None:
    """first-fit 从每个柱间左端连续打包，落点必恰好归属一个柱间。"""
    for j, (a, b) in enumerate(spans):
        if a - EPS_SPAN <= placement.start_m and placement.end_m <= b + EPS_SPAN:
            return j
    return None

def apply_yield_overrides(overrides: dict[int, float], vendors: list[dict],
                          victim_ids: list[int]) -> dict[int, float]:
    """把受害者本轮临时优先压到队尾：当前全员最大有效优先 M 之上依次 M+1, M+2, …。

    受害者按当前 (有效优先, id) 升序赋值，保留他们彼此原序；X 与其他摊主的覆盖原样保留。
    队尾追加保证所有受害者严格排在 X 之后，且跨批次单调、确定。
    """
    if not victim_ids:
        return dict(overrides)
    eff = {v["id"]: effective_priority(v, overrides) for v in vendors}
    watermark = max(eff.values())
    ordered_victims = sorted(victim_ids, key=lambda vid: (eff[vid], vid))
    new_overrides = dict(overrides)
    for step, vid in enumerate(ordered_victims, start=1):
        new_overrides[vid] = watermark + step
    return new_overrides

@dataclass
class YieldPlan:
    noop: bool
    target_span_index: int | None
    victim_ids: list[int]
    pushed_width: float
    new_overrides: dict[int, float]
    result: AllocResult

@dataclass
class YieldFailure:
    code: str       # "vendor_too_wide" | "no_neighbor"
    message: str

def plan_yield(width_m: float, vendors: list[dict], pillars: list[dict],
               overrides: dict[int, float], x_id: int) -> YieldPlan | YieldFailure:
    """为被拒摊位 x_id 规划让路。纯函数，不触碰登记优先。

    成功判据：用新临时优先实际重算后 x_id 进入 placements。仅压够赤字不保证入位——更后柱间的
    摊主会按 first-fit 左倾回流吞掉新释放的空档，且这种接力回流可能跨多个柱间。因此对每个可容纳
    X 的目标柱间采用"重算引导的迭代贪心"：每轮只选【当前临时结论中】仍占住该目标柱间、且有效
    次序仍在 X 之前的最右邻摊，压一个再重算；回流者若在新结论里落入目标柱间，下一轮自然成为新
    候选。被压者排到 X 之后后不会再回到 X 之前，故每轮目标柱间的 X 前占户严格减少，迭代有界。
    在所有目标柱间的成功计划中按 (受害人数, 被压总宽, 柱间从左到右) 取最优，全确定。
    """
    x = next((v for v in vendors if v["id"] == x_id), None)
    if x is None:
        raise ValueError(f"vendor {x_id} 不存在")
    spans = free_spans_from_pillars(width_m, pillars)
    base = allocate_first_fit(width_m, with_effective_priority(vendors, overrides), pillars)

    if any(p.vendor_id == x_id for p in base.placements):
        # 已在主图：连点两次让路等情形 -> no-op，不产生任何状态变化。
        return YieldPlan(True, None, [], 0.0, dict(overrides), base)

    xw = float(x["stall_width_m"])
    max_span = max((b - a for a, b in spans), default=0.0)
    if xw > max_span + EPS_FIT:
        return YieldFailure("vendor_too_wide", "该摊位比任意柱间都宽，结构上无法安置，让路无效")

    width_by_id = {v["id"]: float(v["stall_width_m"]) for v in vendors}
    candidates = []
    for j, (a, b) in enumerate(spans):
        if (b - a) + EPS_FIT < xw:
            continue
        trial_overrides = dict(overrides)
        victims: list[int] = []
        trial: AllocResult | None = None
        for _ in range(len(vendors) + 1):
            eff_vendors = with_effective_priority(vendors, trial_overrides)
            trial = allocate_first_fit(width_m, eff_vendors, pillars)
            if any(p.vendor_id == x_id for p in trial.placements):
                break  # 该目标柱间引导成功
            x_eff = next(v["priority"] for v in eff_vendors if v["id"] == x_id)
            before = {v["id"] for v in eff_vendors if (v["priority"], v["id"]) < (x_eff, x_id)}
            neighbors = [p for p in trial.placements
                         if placement_span_index(p, spans) == j and p.vendor_id in before]
            neighbors.sort(key=lambda p: (-p.end_m, -p.vendor_id))
            if not neighbors or neighbors[0].vendor_id in victims:
                trial = None  # 无可压邻摊或陷入重复（防御）：此目标柱间无解
                break
            pick = neighbors[0].vendor_id
            victims.append(pick)
            trial_overrides = apply_yield_overrides(trial_overrides, vendors, [pick])
        if trial is not None and any(p.vendor_id == x_id for p in trial.placements):
            pushed = sum(width_by_id[vid] for vid in victims)
            candidates.append((len(victims), round(pushed, 3), j, victims, trial_overrides, trial))

    if not candidates:
        return YieldFailure("no_neighbor", "目标柱间内没有可压低的邻摊，让路无法腾出空档")

    k, pushed, j, victims, new_overrides, trial = min(
        candidates, key=lambda c: (c[0], c[1], c[2]))
    return YieldPlan(False, j, victims, pushed, new_overrides, trial)
