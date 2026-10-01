<script setup lang="ts">
import { onMounted } from 'vue'
import { allocStore, ensureState, yieldFor, clearError } from '../store/allocation'

onMounted(() => { ensureState() })
</script>
<template>
  <h1>放不下</h1>
  <p class="sub">无法在连续空档内安置且不跨越挡柱的摊位 · 可让路压低邻摊本轮临时优先后重算</p>
  <div class="card">
    <table>
      <thead><tr><th>摊主</th><th>需求宽度</th><th>原因</th><th>操作</th></tr></thead>
      <tbody>
        <tr v-for="r in (allocStore.state?.rejected || [])" :key="r.vendor_id">
          <td>{{ r.vendor_name }}</td>
          <td>{{ r.width_m }}</td>
          <td>{{ r.reason }}</td>
          <td>
            <button
              class="btn"
              :disabled="allocStore.yieldingId !== null"
              @click="yieldFor(r.vendor_id)"
            >{{ allocStore.yieldingId === r.vendor_id ? '让路中…' : '让路' }}</button>
            <div
              v-if="allocStore.error?.vendorId === r.vendor_id"
              class="ss-inline-err"
            >
              {{ allocStore.error.message }}
              <a href="#" @click.prevent="clearError">×</a>
            </div>
          </td>
        </tr>
      </tbody>
    </table>
    <p v-if="!(allocStore.state?.rejected || []).length" class="muted">全部放下</p>
  </div>
</template>
