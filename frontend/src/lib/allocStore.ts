import { reactive } from 'vue'
import { api } from '../api'

/**
 * 主图、放不下、临时优先三处共用同一套结论：
 * 任何页面只读本 store 的 alloc，所有写操作都经这里刷新 /latest，
 * 杜绝三处各自请求、结论对不齐。
 */
export interface YieldError {
  code: string
  detail: string
  suppressed?: Array<{ vendor_id: number; vendor_name: string; registered_priority: number; temp_priority: number }>
}

const SEGMENT_ID = 1

class AllocStore {
  state = reactive({
    alloc: null as any,
    loading: false,
    error: '' as string,
    acting: false,
    actionError: null as YieldError | null,
  })

  async refresh() {
    this.state.loading = true
    this.state.error = ''
    try {
      this.state.alloc = await api(`/allocate/latest?segment_id=${SEGMENT_ID}`)
    } catch (e: any) {
      this.state.error = parseDetail(e)?.detail || String(e?.message ?? e)
    } finally {
      this.state.loading = false
    }
  }

  async yieldWay(req: { vendor_id: number; span_lo: number; span_hi: number }): Promise<YieldError | null> {
    this.state.acting = true
    this.state.actionError = null
    try {
      // 成功即同一份结论：直接用响应替换，并再拉 /latest 校准三处
      this.state.alloc = await api(`/allocate/yield?segment_id=${SEGMENT_ID}`, {
        method: 'POST',
        body: JSON.stringify(req),
      })
      await this.refresh()
      return null
    } catch (e: any) {
      const err = parseDetail(e) || { code: 'unknown', detail: String(e?.message ?? e) }
      this.state.actionError = err
      return err
    } finally {
      this.state.acting = false
    }
  }

  async confirm(): Promise<YieldError | null> {
    this.state.acting = true
    this.state.actionError = null
    try {
      this.state.alloc = await api(`/allocate/confirm?segment_id=${SEGMENT_ID}`, { method: 'POST' })
      await this.refresh()
      return null
    } catch (e: any) {
      // 闸门拒绝（窗外 403 / 写闸 409）：后端保留预览与旧运行，刷新拉回同一结论
      const err = parseDetail(e) || { code: 'unknown', detail: String(e?.message ?? e) }
      this.state.actionError = err
      await this.refresh()
      return err
    } finally {
      this.state.acting = false
    }
  }

  async cancelYield() {
    this.state.acting = true
    try {
      await api(`/allocate/yield/cancel?segment_id=${SEGMENT_ID}`, { method: 'POST' })
      await this.refresh()
    } finally {
      this.state.acting = false
    }
  }

  async rerun(): Promise<YieldError | null> {
    this.state.acting = true
    this.state.actionError = null
    try {
      this.state.alloc = await api(`/allocate/run?segment_id=${SEGMENT_ID}`, { method: 'POST' })
      await this.refresh()
      return null
    } catch (e: any) {
      const err = parseDetail(e) || { code: 'unknown', detail: String(e?.message ?? e) }
      this.state.actionError = err
      await this.refresh()
      return err
    } finally {
      this.state.acting = false
    }
  }
}

function parseDetail(e: any): YieldError | null {
  const raw = e?.message
  if (typeof raw !== 'string') return null
  try {
    const obj = JSON.parse(raw)
    if (obj && obj.detail && obj.detail.code) return obj.detail as YieldError
    if (obj && obj.code) return obj as YieldError
  } catch { /* 非 JSON 的纯文本错误 */ }
  return null
}

export const allocStore = new AllocStore()
