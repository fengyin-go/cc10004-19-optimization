/** 连接候选接口封装：候选检索、来源绑定、绑定状态回显。 */
import { request } from '@/api/client'

export interface ConnectionCandidate {
  id: number
  配置编号: string
  连接类型: string
  接入地址: string
  负责人: string
  status: string
  bindable: boolean
}

export interface CandidatePage {
  items: ConnectionCandidate[]
  total: number
  page: number
  size: number
}

export interface CandidateFilters {
  config_no?: string
  conn_type?: string
  address?: string
  owner?: string
}

export class ForbiddenError extends Error {
  constructor(detail: string) {
    super(detail)
    this.name = 'ForbiddenError'
  }
}

export class CandidateConflictError extends Error {
  candidates: ConnectionCandidate[]

  constructor(message: string, candidates: ConnectionCandidate[]) {
    super(message)
    this.name = 'CandidateConflictError'
    this.candidates = candidates
  }
}

export class DisconnectedError extends Error {
  candidate: ConnectionCandidate | null

  constructor(message: string, candidate: ConnectionCandidate | null) {
    super(message)
    this.name = 'DisconnectedError'
    this.candidate = candidate
  }
}

function buildQuery(filters: CandidateFilters, page: number, size: number): string {
  const params = new URLSearchParams()
  for (const [key, value] of Object.entries(filters)) {
    if (value && value.trim()) {
      params.set(key, value.trim())
    }
  }
  params.set('page', String(page))
  params.set('size', String(size))
  return params.toString()
}

export async function searchCandidates(
  filters: CandidateFilters,
  page: number,
  size: number,
): Promise<CandidatePage> {
  const response = await request(`/api/connections/candidates?${buildQuery(filters, page, size)}`)
  if (response.status === 403) {
    // 越权响应不携带 total/items，原样抛出固定话术，不暴露匹配数量。
    const body = await response.json().catch(() => ({ detail: '无权检索连接候选' }))
    throw new ForbiddenError(typeof body.detail === 'string' ? body.detail : '无权检索连接候选')
  }
  if (!response.ok) {
    throw new Error('连接候选读取失败，请稍后重试')
  }
  return (await response.json()) as CandidatePage
}

export async function bindDatastore(
  datastoreId: number,
  payload: { source_id?: number; source_name?: string; confirmed?: boolean },
): Promise<{ ok: boolean; message: string; entry: Record<string, unknown> | null }> {
  const response = await request(`/api/connections/datastore/${datastoreId}/bind`, {
    method: 'POST',
    body: JSON.stringify(payload),
  })
  if (response.status === 409) {
    const body = await response.json()
    const detail = body.detail ?? {}
    throw new CandidateConflictError(
      detail.message ?? '来源名称匹配到多个连接，请确认',
      (detail.candidates ?? []) as ConnectionCandidate[],
    )
  }
  if (response.status === 403) {
    const body = await response.json().catch(() => ({ detail: '无权绑定该连接' }))
    throw new ForbiddenError(typeof body.detail === 'string' ? body.detail : '无权绑定该连接')
  }
  if (!response.ok) {
    const body = await response.json().catch(() => ({ detail: '来源绑定失败' }))
    throw new Error(typeof body.detail === 'string' ? body.detail : '来源绑定失败')
  }
  return (await response.json()) as {
    ok: boolean
    message: string
    entry: Record<string, unknown> | null
  }
}

export interface BindingStatus {
  bound: boolean
  legacy_name?: string
  live_status?: string | null
  still_bindable?: boolean
  snapshot?: Record<string, unknown>
  message?: string
}

export async function getBinding(datastoreId: number): Promise<BindingStatus> {
  const response = await request(`/api/connections/datastore/${datastoreId}/binding`)
  if (!response.ok) {
    throw new Error('绑定状态读取失败')
  }
  return (await response.json()) as BindingStatus
}
