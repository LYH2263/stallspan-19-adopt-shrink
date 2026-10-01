<script setup lang="ts">
import { onMounted, ref } from 'vue'
import { api } from '../api'
const rows = ref<any[]>([])
function fmt(s: string | null): string {
  return s ? s.replace('T', ' ').slice(0, 19) : '—'
}
onMounted(async () => { rows.value = await api('/days') })
</script>
<template>
  <h1>集日</h1>
  <p class="sub">开市日程 · 仅在可分配时段窗内允许确认落库</p>
  <div class="card">
    <table>
      <thead><tr><th>名称</th><th>日期</th><th>可分配开始</th><th>可分配结束</th></tr></thead>
      <tbody>
        <tr v-for="r in rows" :key="r.id ?? JSON.stringify(r)">
          <td>{{ r.name }}</td>
          <td>{{ r.day }}</td>
          <td>{{ fmt(r.alloc_open_at) }}</td>
          <td>{{ fmt(r.alloc_close_at) }}</td>
        </tr>
      </tbody>
    </table>
  </div>
</template>
