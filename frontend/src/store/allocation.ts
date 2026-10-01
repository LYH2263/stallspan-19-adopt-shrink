import { reactive } from 'vue'
import { api, ApiError } from '../api'

export interface Placement {
  vendor_id: number
  vendor_name: string
  start_m: number
  end_m: number
  width_m: number
}
export interface RejectedRow {
  vendor_id: number
  vendor_name: string
  width_m: number
  reason: string
}
export interface VendorPriority {
  id: number
  name: string
  stall_width_m: number
  priority: number        // 登记优先（只读）
  temp_priority: number   // 本轮临时优先
}
export interface AllocState {
  segment: { id: number; market_day_id: number; name: string; width_m: number }
  pillars: { id?: number; segment_id?: number; position_m: number; thickness_m: number; label: string }[]
  placements: Placement[]
  rejected: RejectedRow[]
  free_spans: { start_m: number; end_m: number }[]
  vendors: VendorPriority[]
  window: { alloc_open_at: string | null; alloc_close_at: string | null }
  latest_run_id: number | null
}

interface StoreError {
  vendorId?: number
  code?: string
  message: string
}

export const allocStore = reactive({
  state: null as AllocState | null,
  loading: false,
  confirming: false,
  yieldingId: null as number | null,
  error: null as StoreError | null,
})

let inflight: Promise<void> | null = null

export function ensureState(force = false): Promise<void> {
  if (!force && allocStore.state) return Promise.resolve()
  if (!force && inflight) return inflight
  allocStore.loading = true
  inflight = api<AllocState>('/allocate/state?segment_id=1')
    .then((data) => {
      allocStore.state = data
      allocStore.error = null
    })
    .catch((e: unknown) => {
      allocStore.error = { message: e instanceof Error ? e.message : String(e) }
    })
    .finally(() => {
      allocStore.loading = false
      inflight = null
    })
  return inflight
}

export function refreshState(): Promise<void> {
  return ensureState(true)
}

export function clearError() {
  allocStore.error = null
}

function setError(e: unknown, vendorId?: number) {
  if (e instanceof ApiError) {
    allocStore.error = { vendorId, code: e.code, message: e.message }
  } else {
    allocStore.error = { vendorId, message: e instanceof Error ? e.message : String(e) }
  }
}

export async function yieldFor(vendorId: number) {
  if (allocStore.yieldingId !== null) return
  allocStore.error = null
  allocStore.yieldingId = vendorId
  try {
    allocStore.state = await api<AllocState>(`/allocate/yield/${vendorId}?segment_id=1`, { method: 'POST' })
  } catch (e) {
    setError(e, vendorId)
  } finally {
    allocStore.yieldingId = null
  }
}

export async function confirmAllocation() {
  if (allocStore.confirming) return
  allocStore.error = null
  allocStore.confirming = true
  try {
    allocStore.state = await api<AllocState>('/allocate/confirm?segment_id=1', { method: 'POST' })
  } catch (e) {
    setError(e)
  } finally {
    allocStore.confirming = false
  }
}

export async function resetYields() {
  allocStore.error = null
  try {
    allocStore.state = await api<AllocState>('/allocate/reset?segment_id=1', { method: 'POST' })
  } catch (e) {
    setError(e)
  }
}
