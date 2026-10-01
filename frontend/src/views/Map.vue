<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { api } from '../api'
import { allocStore } from '../lib/allocStore'
import { tempPriorityFor } from '../lib/spans'
import YieldBanner from '../components/YieldBanner.vue'

const s = allocStore.state
const vendors = ref<any[]>([])
onMounted(async () => {
  vendors.value = await api('/vendors')
  await allocStore.refresh()
})

async function rerun() {
  await allocStore.rerun()
  vendors.value = await api('/vendors')
}

const colors = ['#e8a87c','#85dcb8','#e27d60','#c38d9e','#41b3a3','#f4a261','#e76f51']
const cells = computed(() => {
  if (!s.alloc) return []
  const width = s.alloc.segment.width_m
  const out: any[] = []
  for (const p of s.alloc.pillars || []) {
    out.push({ type: 'pillar', start: p.position_m - p.thickness_m/2, w: p.thickness_m, label: p.label || '挡柱' })
  }
  for (const [i, p] of (s.alloc.placements || []).entries()) {
    out.push({ type: 'stall', start: p.start_m, w: p.width_m, label: p.vendor_name, color: colors[i % colors.length] })
  }
  return out.sort((a,b) => a.start - b.start).map(c => ({ ...c, pct: Math.max((c.w / width) * 100, 2) }))
})
const isPreview = computed(() => !!s.alloc?.yield_preview)
</script>
<template>
  <div class="ss-street-wrap">
    <h1>街段分配带</h1>
    <p class="sub">
      沿街一维开间 · 挡柱为竖直阻断 · 底部为摊主排队 ·
      主图与「放不下」「临时优先」始终同读一套结论
    </p>
    <div class="ss-map-actions">
      <button class="btn" :disabled="s.acting" @click="rerun">重新分配</button>
      <span v-if="isPreview" class="badge badge-warn">当前为让路试运行（未落库）</span>
    </div>
    <YieldBanner />
    <p v-if="s.actionError" class="ss-action-error">{{ s.actionError.detail }}</p>
    <p v-if="s.loading && !s.alloc" class="muted">载入中…</p>

    <template v-if="s.alloc">
      <div class="ss-band-ruler">
        <span>0 m</span>
        <span>{{ s.alloc.segment.name }} · {{ s.alloc.segment.width_m }} m</span>
        <span>{{ s.alloc.segment.width_m }} m</span>
      </div>
      <div class="ss-street-band">
        <div class="ss-street-inner">
          <div
            v-for="(c,i) in cells" :key="i"
            class="ss-band-cell"
            :class="{ 'ss-pillar': c.type === 'pillar' }"
            :style="{ width: c.pct + '%', background: c.type === 'pillar' ? undefined : c.color, flex: '0 0 ' + c.pct + '%' }"
          >{{ c.label }}</div>
        </div>
      </div>
      <div class="ss-vendor-queue">
        <div v-for="v in vendors" :key="v.id" class="ss-vendor-chip">
          <strong>{{ v.name }}</strong>
          <span>
            需 {{ v.stall_width_m }} m · 优先 {{ v.priority }}
            <template v-if="tempPriorityFor(s.alloc, v.id) !== null">
              → 本轮临时 <b class="ss-temp">{{ tempPriorityFor(s.alloc, v.id) }}</b>
            </template>
          </span>
        </div>
      </div>
      <div class="card">
        <table>
          <thead><tr><th>摊主</th><th>起点</th><th>终点</th><th>宽度</th></tr></thead>
          <tbody>
            <tr v-for="p in s.alloc.placements" :key="p.vendor_id">
              <td>{{ p.vendor_name }}</td><td>{{ p.start_m }}</td><td>{{ p.end_m }}</td><td>{{ p.width_m }}</td>
            </tr>
          </tbody>
        </table>
      </div>
    </template>
  </div>
</template>
