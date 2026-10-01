"""1D First-Fit stall placement along a street segment; stalls cannot cross pillars."""
from __future__ import annotations
from dataclasses import asdict, dataclass

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
    return [(round(a, 3), round(b, 3)) for a, b in spans if b - a > 1e-6]

def allocate_first_fit(
    width_m: float,
    vendors: list[dict],
    pillars: list[dict],
    priority_override: dict[int, float] | None = None,
) -> AllocResult:
    """vendors sorted by effective priority ascending then id; each needs stall_width_m contiguous in one free span (no pillar cross).

    priority_override 仅本轮排序用的临时优先，绝不写回摊主登记值；
    不传或为空时与原实现完全一致。
    """
    override = priority_override or {}
    spans = free_spans_from_pillars(width_m, pillars)
    # mutable remaining capacity per span
    remain = [[a, b] for a, b in spans]
    def eff(v: dict) -> float:
        return override.get(v["id"], v.get("priority", 1))
    ordered = sorted(vendors, key=lambda v: (eff(v), v["id"]))
    placements: list[Placement] = []
    rejected: list[Rejected] = []
    for v in ordered:
        need = float(v["stall_width_m"])
        placed = False
        for span in remain:
            avail = span[1] - span[0]
            if avail + 1e-9 >= need:
                start = span[0]
                end = start + need
                placements.append(Placement(v["id"], v["name"], round(start, 3), round(end, 3), need))
                span[0] = end
                placed = True
                break
        if not placed:
            rejected.append(Rejected(v["id"], v["name"], need, "无连续空档可放下且不跨越挡柱"))
    free = [(round(a, 3), round(b, 3)) for a, b in remain if b - a > 1e-6]
    return AllocResult(placements, rejected, free)

def result_to_dict(r: AllocResult, priority_override: dict[int, float] | None = None) -> dict:
    out = {
        "placements": [asdict(p) for p in r.placements],
        "rejected": [asdict(x) for x in r.rejected],
        "free_spans": [{"start_m": a, "end_m": b} for a, b in r.free_spans],
    }
    # 仅在确有临时压低时下发覆盖表；未让路与绿仓响应形状一致
    if priority_override:
        out["priority_override"] = {str(k): v for k, v in sorted(priority_override.items())}
    return out
