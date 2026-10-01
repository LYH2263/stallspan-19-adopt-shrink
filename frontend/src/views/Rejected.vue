<script setup lang="ts">
import { computed, onMounted, reactive, ref } from 'vue'
import { allocStore } from '../lib/allocStore'
import { spansFromPillars } from '../lib/spans'
import YieldBanner from '../components/YieldBanner.vue'

const s = allocStore.state
onMounted(() => allocStore.refresh())

// 每条放不下的摊可选的目标柱间（净长放得下它的才列出）；这是柱间，不是剩余空档
const spansFor = (widthM: number) =>
  spansFromPillars(s.alloc.segment.width_m, s.alloc.pillars || []).filter((sp) => sp.end_m - sp.start_m + 1e-9 >= widthM)

const chosen = reactive<Record<number, string>>({})
function keyOf(lo: number, hi: number) { return `${lo}|${hi}` }
function chosenSpan(vendorId: number, widthM: number) {
  const opts = spansFor(widthM)
  const cur = chosen[vendorId]
  if (cur && opts.some((o) => keyOf(o.start_m, o.end_m) === cur)) return cur
  const k = opts.length ? keyOf(opts[0].start_m, opts[0].end_m) : ''
  chosen[vendorId] = k
  return k
}

const rowError = ref<Record<number, { code: string; detail: string }>>({})
const busyId = ref<number | null>(null)

async function doYield(vendorId: number, widthM: number) {
  const k = chosenSpan(vendorId, widthM)
  if (!k) { rowError.value[vendorId] = { code: 'no_span', detail: '没有任何柱间的净长放得下该摊（非邻摊让路可解）' }; return }
  const [lo, hi] = k.split('|').map(Number)
  busyId.value = vendorId
  delete rowError.value[vendorId]
  s.actionError = null
  const err = await allocStore.yieldWay({ vendor_id: vendorId, span_lo: lo, span_hi: hi })
  if (err) rowError.value[vendorId] = { code: err.code, detail: err.detail }
  else delete rowError.value[vendorId]
  busyId.value = null
}

const rows = computed(() => s.alloc?.rejected || [])
const isPreview = computed(() => !!s.alloc?.yield_preview)
const fmt = (sp: { start_m: number; end_m: number }) => `${sp.start_m}–${sp.end_m} m`
</script>

<template>
  <h1>放不下</h1>
  <p class="sub">
    无法在连续空档内安置且不跨越挡柱的摊位 ·
    可请求同一柱间内登记优先更低的邻摊本轮临时让路
  </p>

  <YieldBanner />
  <p v-if="s.actionError && !isPreview" class="ss-action-error">{{ s.actionError.detail }}</p>

  <div class="card">
    <table>
      <thead>
        <tr><th>摊主</th><th>需求宽度</th><th>原因</th><th>目标柱间</th><th>让路</th></tr>
      </thead>
      <tbody>
        <tr v-for="r in rows" :key="r.vendor_id">
          <td>{{ r.vendor_name }}</td>
          <td>{{ r.width_m }}</td>
          <td>{{ r.reason }}</td>
          <td>
            <select v-if="spansFor(r.width_m).length" v-model="chosen[r.vendor_id]">
              <option v-for="sp in spansFor(r.width_m)" :key="keyOf(sp.start_m, sp.end_m)" :value="keyOf(sp.start_m, sp.end_m)">
                {{ fmt(sp) }}
              </option>
            </select>
            <span v-else class="muted">无柱间放得下</span>
          </td>
          <td>
            <button class="btn ss-btn-sm" :disabled="busyId === r.vendor_id || s.acting"
                    @click="doYield(r.vendor_id, r.width_m)">
              {{ busyId === r.vendor_id ? '试算中…' : '请求让路' }}
            </button>
          </td>
        </tr>
      </tbody>
    </table>
    <p v-if="!rows.length" class="muted">全部放下</p>
  </div>

  <div v-for="(e, vid) in rowError" :key="vid" class="card ss-yield-fail">
    <p>
      <span class="badge" :class="e.code === 'no_neighbor' ? 'badge-bad' : 'badge-warn'">
        {{ e.code === 'no_neighbor' ? '无邻可压' : (e.code === 'insufficient_space' ? '空档仍不够' : '让路失败') }}
      </span>
      <strong>摊主 #{{ vid }}</strong>：{{ e.detail }}
    </p>
    <p class="muted">登记优先、主图、放不下均保持让路前结论，未写任何运行行。</p>
  </div>
</template>
