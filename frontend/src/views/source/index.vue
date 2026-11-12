<template>
  <section class="page" data-module="source">
    <header class="page-head">
      <div>
        <h2>数据源接入管理</h2>
        <p class="page-desc">维护数据源接入配置的输入、执行约束与结果记录，为数据接入提供可验证的数据工程流程。</p>
      </div>
      <div class="page-actions">
        <button class="btn primary" type="button" @click="openCreate">登记接入配置</button>
        <button class="btn" type="button" @click="exportRows">导出数据源接入清单</button>
      </div>
    </header>

    <div class="stat-row">
      <article v-for="item in stats" :key="item.label" class="stat-card">
        <span class="stat-label">{{ item.label }}</span>
        <strong class="stat-value">{{ item.value }}</strong>
      </article>
    </div>

    <form class="filter-bar" @submit.prevent="searchFromFirstPage">
      <label v-for="field in filterFields" :key="field.key" class="filter-item">
        <span>{{ field.label }}</span>
        <input v-model.trim="filters[field.key]" :placeholder="`按${field.label}检索`" />
      </label>
      <button class="btn" type="submit">查询</button>
      <button class="btn ghost" type="button" @click="resetFilters">重置条件</button>
    </form>

    <table class="data-table">
      <thead>
        <tr>
          <th v-for="column in columns" :key="column">{{ column }}</th>
          <th>状态</th>
          <th>可执行动作</th>
        </tr>
      </thead>
      <tbody>
        <tr v-for="row in rows" :key="String(row.id)">
          <td v-for="column in columns" :key="column">{{ row[column] ?? '—' }}</td>
          <td>{{ row.status ?? '—' }}</td>
          <td class="row-actions">
            <button
              v-for="action in actions"
              :key="action"
              class="link"
              type="button"
              @click="runAction(action, row)"
            >
              {{ action }}
            </button>
          </td>
        </tr>
        <tr v-if="!rows.length">
          <td :colspan="columns.length + 2" class="empty-state">暂无数据源接入数据，可先登记接入配置</td>
        </tr>
      </tbody>
    </table>

    <footer class="page-foot">
      <span>共 {{ total }} 条数据源接入记录</span>
      <div class="pager">
        <button class="btn" type="button" :disabled="page <= 1 || loading" @click="goPage(page - 1)">
          上一页
        </button>
        <span>第 {{ page }} 页 / 每页 {{ size }} 条</span>
        <button
          class="btn"
          type="button"
          :disabled="page * size >= total || loading"
          @click="goPage(page + 1)"
        >
          下一页
        </button>
      </div>
      <span v-if="errorMessage" class="error-text">{{ errorMessage }}</span>
    </footer>
  </section>
</template>

<script setup lang="ts">
import { onBeforeUnmount, onMounted, reactive, ref } from 'vue'

import { LatestOnlyRunner, request } from '@/api/client'

type Row = Record<string, string | number | null>

const ENDPOINT = '/api/source'
const columns = ["配置编号", "连接类型", "接入地址", "认证凭证", "连接池大小", "超时秒数", "重试上限", "负责人"]
const actions = ["提交校验", "建立连接", "断开连接"]
const stats = [{"label": "接入配置总数", "value": 0}, {"label": "已连接接入", "value": 0}, {"label": "待校验接入", "value": 0}]

// 条件栏字段与后端检索参数一一对应，不再把中文列名直接拼进查询串。
const filterFields = [
  { key: 'config_no', label: '配置编号' },
  { key: 'conn_type', label: '连接类型' },
  { key: 'address', label: '接入地址' },
  { key: 'owner', label: '负责人' },
] as const

type FilterKey = (typeof filterFields)[number]['key']

const rows = ref<Row[]>([])
const total = ref(0)
const page = ref(1)
const size = 20
const loading = ref(false)
const errorMessage = ref('')
const filters = reactive<Record<FilterKey, string>>({
  config_no: '',
  conn_type: '',
  address: '',
  owner: '',
})
const runner = new LatestOnlyRunner()

function buildQuery(targetPage: number): string {
  const params = new URLSearchParams()
  for (const field of filterFields) {
    const value = filters[field.key]
    if (value) params.set(field.key, value)
  }
  params.set('page', String(targetPage))
  params.set('size', String(size))
  return params.toString()
}

async function load(targetPage: number) {
  loading.value = true
  errorMessage.value = ''
  const result = await runner.run(() => request(`${ENDPOINT}?${buildQuery(targetPage)}`))
  // 快速改关键词产生的晚到响应直接丢弃，不能覆盖新条件下的列表。
  if (!result.ok) {
    loading.value = false
    return
  }
  try {
    const response = result.value
    if (!response.ok) {
      throw new Error('接入配置列表读取失败')
    }
    const payload = await response.json()
    rows.value = payload.items ?? []
    total.value = payload.total ?? rows.value.length
    page.value = targetPage
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : '数据源接入列表读取失败'
  } finally {
    loading.value = false
  }
}

function searchFromFirstPage() {
  void load(1)
}

function goPage(target: number) {
  if (target < 1 || (target - 1) * size >= total.value) return
  void load(target)
}

function resetFilters() {
  for (const field of filterFields) filters[field.key] = ''
  void load(1)
}

function exportRows() {
  window.open(`${ENDPOINT}/export`, '_blank')
}

function openCreate() {
  errorMessage.value = '接入配置登记入口尚未接入审批流'
}

async function runAction(action: string, row: Row) {
  errorMessage.value = ''
  try {
    const response = await request(`${ENDPOINT}/${row.id}/actions`, {
      method: 'POST',
      body: JSON.stringify({ values: { action } }),
    })
    if (!response.ok) {
      throw new Error('数据源接入动作未生效，请稍后重试')
    }
    await load(page.value)
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : '数据源接入操作失败'
  }
}

onMounted(() => void load(1))
onBeforeUnmount(() => runner.invalidate())
</script>

<style scoped>
.pager {
  display: flex;
  gap: 8px;
  align-items: center;
  font-size: 12px;
  color: var(--muted);
}
</style>
