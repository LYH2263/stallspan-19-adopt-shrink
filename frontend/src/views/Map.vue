<script setup lang="ts">
import { computed, onMounted } from 'vue'
import {
  allocStore, ensureState, confirmAllocation, resetYields, clearError,
} from '../store/allocation'

onMounted(() => { ensureState() })

const colors = ['#e8a87c','#85dcb8','#e27d60','#c38d9e','#41b3a3','#f4a261','#e76f51']
const data = computed(() => allocStore.state)

const cells = computed(() => {
  if (!data.value) return []
  const width = data.value.segment.width_m
  const out: any[] = []
  for (const p of data.value.pillars || []) {
    out.push({ type: 'pillar', start: p.position_m - p.thickness_m/2, w: p.thickness_m, label: p.label || '挡柱' })
  }
  for (const [i, p] of (data.value.placements || []).entries()) {
    out.push({ type: 'stall', start: p.start_m, w: p.width_m, label: p.vendor_name, color: colors[i % colors.length] })
  }
  return out.sort((a,b) => a.start - b.start).map(c => ({ ...c, pct: Math.max((c.w / width) * 100, 2) }))
})
</script>
<template>
  <div class="ss-street-wrap">
    <h1>街段分配带</h1>
    <p class="sub">沿街一维开间 · 挡柱为竖直阻断 · 底部为本轮临时优先排队</p>
    <div class="ss-actions">
      <button class="btn" :disabled="allocStore.confirming" @click="confirmAllocation">
        {{ allocStore.confirming ? '确认中…' : '确认落库' }}
      </button>
      <button class="btn" :disabled="allocStore.confirming" @click="resetYields">重置让路</button>
      <span v-if="allocStore.state?.latest_run_id" class="muted">
        已确认运行 #{{ allocStore.state.latest_run_id }}
      </span>
    </div>
    <div v-if="allocStore.error && !allocStore.error.vendorId" class="ss-inline-err">
      {{ allocStore.error.message }}
      <a href="#" @click.prevent="clearError">×</a>
    </div>
    <div class="ss-band-ruler" v-if="data">
      <span>0 m</span>
      <span>{{ data.segment.name }} · {{ data.segment.width_m }} m</span>
      <span>{{ data.segment.width_m }} m</span>
    </div>
    <div class="ss-street-band" v-if="data">
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
      <div v-for="v in (data?.vendors || [])" :key="v.id" class="ss-vendor-chip">
        <strong>{{ v.name }}</strong>
        <span>
          需 {{ v.stall_width_m }} m · 登记 {{ v.priority }}
          <template v-if="v.temp_priority !== v.priority">
            · <em class="ss-temp-pri">临时 {{ v.temp_priority }}</em>
          </template>
        </span>
      </div>
    </div>
    <div class="card" v-if="data">
      <table>
        <thead><tr><th>摊主</th><th>起点</th><th>终点</th><th>宽度</th></tr></thead>
        <tbody>
          <tr v-for="p in data.placements" :key="p.vendor_id">
            <td>{{ p.vendor_name }}</td><td>{{ p.start_m }}</td><td>{{ p.end_m }}</td><td>{{ p.width_m }}</td>
          </tr>
        </tbody>
      </table>
    </div>
  </div>
</template>
