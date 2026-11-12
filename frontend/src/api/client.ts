/** 统一请求封装：拼后端地址、携带身份头、抛网络错误、给页脚留一句可读的说明。 */
import { useSessionStore } from '@/stores/session'

const API_BASE = import.meta.env.VITE_API_BASE ?? ''

function identityHeaders(): Record<string, string> {
  // 中文身份头按 RFC 做编码，后端用 unquote 还原。
  const session = useSessionStore()
  return {
    'X-Operator': encodeURIComponent(session.operator),
    'X-Operator-Role': session.role,
  }
}

export function request(path: string, init?: RequestInit): Promise<Response> {
  const url = path.startsWith('http') ? path : `${API_BASE}${path}`
  return fetch(url, {
    headers: { 'Content-Type': 'application/json', ...identityHeaders(), ...(init?.headers ?? {}) },
    ...init,
  }).catch((error: unknown) => {
    const detail = error instanceof Error ? error.message : '请求未送达'
    throw new Error(`接口请求失败：${detail}`)
  })
}

export async function fetchJson<T>(path: string): Promise<T> {
  const response = await request(path)
  if (!response.ok) {
    throw new Error(`接口返回 ${response.status}，数据未更新`)
  }
  return (await response.json()) as T
}

/**
 * 竞态守卫：快速连续修改检索条件时，只有最后一次请求允许落地结果。
 * 每次调用产生新的请求序号，过期响应被直接丢弃，不能覆盖新条件下的界面。
 */
export class LatestOnlyRunner {
  private seq = 0

  async run<T>(task: () => Promise<T>): Promise<{ ok: true; value: T } | { ok: false; stale: true }> {
    const current = ++this.seq
    const value = await task()
    if (current !== this.seq) {
      return { ok: false, stale: true }
    }
    return { ok: true, value }
  }

  /** 作废所有在途请求（例如关闭选择器时），避免旧结果回写到已销毁的界面。 */
  invalidate(): void {
    this.seq += 1
  }
}
