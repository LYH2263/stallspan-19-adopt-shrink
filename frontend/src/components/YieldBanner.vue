<script setup lang="ts">
import { computed } from 'vue'
import { allocStore } from '../lib/allocStore'

const s = allocStore.state
const preview = computed(() => s.alloc?.yield_preview || null)
</script>

<template>
  <div v-if="preview" class="card ss-yield-banner">
    <div class="ss-yield-head">
      <span class="badge badge-warn">让路试运行 · 未落库</span>
      <span class="muted">主图 / 放不下 / 临时优先为同一套试运行结论，确认后才写正式运行行</span>
    </div>
    <table>
      <thead>
        <tr><th>本轮被压低的邻摊</th><th>登记优先</th><th>临时优先（本轮）</th></tr>
      </thead>
      <tbody>
        <tr v-for="z in preview.suppressed" :key="z.vendor_id">
          <td>{{ z.vendor_name }}</td>
          <td>{{ z.registered_priority }}</td>
          <td><strong class="ss-temp">{{ z.temp_priority }}</strong> <span class="muted">仅本轮，不写回登记</span></td>
        </tr>
      </tbody>
    </table>
    <p v-if="s.actionError" class="ss-action-error">
      <span class="badge badge-bad">{{ s.actionError.code === 'outside_allocation_window' ? '时段窗拒绝' : (s.actionError.code === 'write_gate_open' ? '写闸已开' : '确认被拒') }}</span>
      {{ s.actionError.detail }}（试运行结论与让路前运行行均保留，未写库）
    </p>
    <div class="ss-yield-actions">
      <button class="btn" :disabled="s.acting" @click="allocStore.confirm()">正式确认落库</button>
      <button class="btn ss-btn-ghost" :disabled="s.acting" @click="allocStore.cancelYield()">放弃让路</button>
      <span v-if="s.acting" class="muted">处理中…</span>
    </div>
  </div>
</template>
