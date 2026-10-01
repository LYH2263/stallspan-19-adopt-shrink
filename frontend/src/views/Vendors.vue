<script setup lang="ts">
import { onMounted } from 'vue'
import { allocStore, ensureState } from '../store/allocation'

onMounted(() => { ensureState() })
</script>
<template>
  <h1>摊主队列</h1>
  <p class="sub">登记优先只读 · 本轮临时优先仅来自让路，绝不写回登记值</p>
  <div class="ss-vendor-queue" style="border-top:none; background:transparent; margin:0; padding:0.5rem 0 1rem">
    <div v-for="r in (allocStore.state?.vendors || [])" :key="r.id" class="ss-vendor-chip">
      <strong>{{ r.name }}</strong>
      <span>
        需 {{ r.stall_width_m }} m · 登记 {{ r.priority }}
        <template v-if="r.temp_priority !== r.priority">
          · <em class="ss-temp-pri">临时 {{ r.temp_priority }}</em>
        </template>
      </span>
    </div>
  </div>
  <div class="card">
    <table>
      <thead><tr><th>摊主</th><th>宽度(m)</th><th>登记优先</th><th>本轮临时优先</th></tr></thead>
      <tbody>
        <tr v-for="r in (allocStore.state?.vendors || [])" :key="r.id">
          <td>{{ r.name }}</td>
          <td>{{ r.stall_width_m }}</td>
          <td>{{ r.priority }}</td>
          <td :class="{ 'ss-temp-cell': r.temp_priority !== r.priority }">{{ r.temp_priority }}</td>
        </tr>
      </tbody>
    </table>
  </div>
</template>
