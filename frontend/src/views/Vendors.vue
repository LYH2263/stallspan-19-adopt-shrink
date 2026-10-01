<script setup lang="ts">
import { onMounted, ref } from 'vue'
import { api } from '../api'
import { allocStore } from '../lib/allocStore'
import { tempPriorityFor } from '../lib/spans'
import YieldBanner from '../components/YieldBanner.vue'

const rows = ref<any[]>([])
const s = allocStore.state
onMounted(async () => {
  rows.value = await api('/vendors')
  await allocStore.refresh()
})
</script>
<template>
  <h1>摊主队列</h1>
  <p class="sub">底部排队条 · 宽度与登记优先 · 让路只在本轮临时压低，绝不写回登记</p>
  <YieldBanner />
  <div class="ss-vendor-queue" style="border-top:none; background:transparent; margin:0; padding:0.5rem 0 1rem">
    <div v-for="r in rows" :key="r.id" class="ss-vendor-chip">
      <strong>{{ r.name }}</strong>
      <span>
        需 {{ r.stall_width_m }} m · 优先 {{ r.priority }}
        <template v-if="s.alloc && tempPriorityFor(s.alloc, r.id) !== null">
          → 临时 <b class="ss-temp">{{ tempPriorityFor(s.alloc, r.id) }}</b>
        </template>
      </span>
    </div>
  </div>
  <div class="card">
    <table>
      <thead><tr><th>摊主</th><th>宽度(m)</th><th>登记优先</th><th>本轮临时优先</th></tr></thead>
      <tbody>
        <tr v-for="r in rows" :key="r.id">
          <td>{{ r.name }}</td><td>{{ r.stall_width_m }}</td><td>{{ r.priority }}</td>
          <td>
            <template v-if="s.alloc && tempPriorityFor(s.alloc, r.id) !== null">
              <b class="ss-temp">{{ tempPriorityFor(s.alloc, r.id) }}</b>
              <span class="muted">（不写回登记）</span>
            </template>
            <span v-else class="muted">—</span>
          </td>
        </tr>
      </tbody>
    </table>
  </div>
</template>
