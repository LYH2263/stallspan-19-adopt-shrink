export class ApiError extends Error {
  status: number
  code?: string
  constructor(status: number, message: string, code?: string) {
    super(message)
    this.name = 'ApiError'
    this.status = status
    this.code = code
  }
}

export async function api<T = any>(path: string, init?: RequestInit): Promise<T> {
  const res = await fetch('/api' + path, {
    headers: { 'Content-Type': 'application/json', ...(init?.headers || {}) },
    ...init,
  })
  if (!res.ok) {
    // FastAPI 错误体：{"detail": "字符串"} 或 {"detail": {"code","message"}}
    let message = res.statusText
    let code: string | undefined
    try {
      const body = await res.json()
      const detail = body?.detail
      if (typeof detail === 'string') message = detail
      else if (detail && typeof detail === 'object') {
        message = detail.message || message
        code = detail.code
      }
    } catch {
      const text = await res.text().catch(() => '')
      if (text) message = text
    }
    throw new ApiError(res.status, message, code)
  }
  if (res.status === 204) return undefined as T
  return res.json()
}
