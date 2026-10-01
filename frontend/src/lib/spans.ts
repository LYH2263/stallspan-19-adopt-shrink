/** 与后端 free_spans_from_pillars 同构：按挡柱算出全部柱间（不是分配后剩余空档）。 */
export interface Pillar { position_m: number; thickness_m: number }

export function spansFromPillars(widthM: number, pillars: Pillar[]): Array<{ start_m: number; end_m: number }> {
  const blocked = pillars
    .map((p) => {
      const half = (p.thickness_m ?? 0.4) / 2
      return [Math.max(0, p.position_m - half), Math.min(widthM, p.position_m + half)] as [number, number]
    })
    .filter(([lo, hi]) => hi > lo)
    .sort((a, b) => a[0] - b[0])
  const merged: Array<[number, number]> = []
  for (const [lo, hi] of blocked) {
    if (!merged.length || lo > merged[merged.length - 1][1]) merged.push([lo, hi])
    else merged[merged.length - 1][1] = Math.max(merged[merged.length - 1][1], hi)
  }
  const out: Array<{ start_m: number; end_m: number }> = []
  let cursor = 0
  for (const [lo, hi] of merged) {
    if (lo > cursor) out.push({ start_m: r3(cursor), end_m: r3(lo) })
    cursor = hi
  }
  if (cursor < widthM) out.push({ start_m: r3(cursor), end_m: r3(widthM) })
  return out.filter((s) => s.end_m - s.start_m > 1e-6)
}

function r3(x: number) { return Math.round(x * 1000) / 1000 }

export function tempPriorityFor(data: any, vendorId: number): number | null {
  const ov = data?.priority_override
  if (!ov) return null
  const v = ov[String(vendorId)]
  return v === undefined ? null : v
}
