<template>
  <section class="page" data-module="datastore">
    <header class="page-head">
      <div>
        <h2>数据集管理管理</h2>
        <p class="page-desc">维护数据集定义的输入、执行约束与结果记录，为数据集管理提供可验证的数据工程流程。</p>
      </div>
      <div class="page-actions">
        <button class="btn primary" type="button" @click="openCreate">登记数据集定义</button>
        <button class="btn" type="button" @click="exportRows">导出数据集管理清单</button>
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
          <th>来源连接</th>
          <th>可执行动作</th>
        </tr>
      </thead>
      <tbody>
        <tr v-for="row in rows" :key="String(row.id)">
          <td v-for="column in columns" :key="column">{{ row[column] ?? '—' }}</td>
          <td>
            <template v-if="row.来源连接ID">
              <a class="link" href="javascript:void(0)" @click="inspectBinding(row)">
                {{ row.来源配置编号 }}（{{ row.来源负责人 }}）
              </a>
              <span v-if="bindingWarnings[row.id as number]" class="tag tag-off">连接已断开，绑定身份保留</span>
            </template>
            <template v-else>
              <span class="muted-text">仅名称：{{ row.来源表名 ?? '—' }}</span>
              <button class="link" type="button" @click="openBind(Number(row.id))">选择候选</button>
              <button class="link" type="button" @click="resolveLegacyName(row)">按名称解析</button>
            </template>
          </td>
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
          <td :colspan="columns.length + 2" class="empty-state">暂无数据集管理数据，可先登记数据集定义</td>
        </tr>
      </tbody>
    </table>

    <footer class="page-foot">
      <span>共 {{ total }} 条数据集管理记录</span>
      <span v-if="errorMessage" class="error-text">{{ errorMessage }}</span>
    </footer>

    <div v-if="pickerOpen" class="modal-mask" @click.self="closePicker">
      <div class="modal-panel">
        <ConnectionPicker
          :datastore-id="activeDatastoreId"
          :embedded="false"
          :confirm-candidates="confirmCandidates"
          @bound="onBound"
          @conflict="onConflict"
          @error="onPickerError"
          @cancel="closePicker"
        />
      </div>
    </div>

    <div v-if="bindingDetail" class="modal-mask" @click.self="bindingDetail = null">
      <div class="modal-panel detail-panel">
        <h3>来源绑定详情</h3>
        <dl class="detail-list">
          <template v-for="(value, key) in bindingDetail" :key="String(key)">
            <dt>{{ String(key) }}</dt>
            <dd>{{ value ?? '—' }}</dd>
          </template>
        </dl>
        <button class="btn" type="button" @click="bindingDetail = null">关闭</button>
      </div>
    </div>
  </section>
</template>

<script setup lang="ts">
import { onBeforeUnmount, onMounted, reactive, ref } from 'vue'

import { LatestOnlyRunner, request } from '@/api/client'
import {
  CandidateConflictError,
  ForbiddenError,
  bindDatastore,
  getBinding,
  type BindingStatus,
  type ConnectionCandidate,
} from '@/api/connections'
import ConnectionPicker from '@/components/ConnectionPicker.vue'

type Row = Record<string, string | number | null>

const ENDPOINT = '/api/datastore'
const columns = ["数据集编号", "数据集名称", "来源表名", "字段列表", "更新策略", "数据采样比例", "生命周期天数", "缓存开关"]
const actions = ["提交审核", "生效发布", "废弃下线"]
const stats = [{"label": "数据集定义总数", "value": 0}, {"label": "已生效数据集", "value": 0}, {"label": "待审核数据集", "value": 0}]

const rows = ref<Row[]>([])
const total = ref(0)
const errorMessage = ref('')

// 条件栏中文字段映射为后端检索参数，不再把列名直接拼进查询串。
const filterFields = [
  { key: 'dataset_no', label: '数据集编号' },
  { key: 'dataset_name', label: '数据集名称' },
  { key: 'source_table', label: '来源表名' },
] as const
type FilterKey = (typeof filterFields)[number]['key']
const filters = reactive<Record<FilterKey, string>>({
  dataset_no: '',
  dataset_name: '',
  source_table: '',
})
const listRunner = new LatestOnlyRunner()

const pickerOpen = ref(false)
const activeDatastoreId = ref(0)
const confirmCandidates = ref<ConnectionCandidate[]>([])
const bindingWarnings = ref<Record<number, boolean>>({})
const bindingDetail = ref<Record<string, unknown> | null>(null)

function resetFilters() {
  for (const field of filterFields) filters[field.key] = ''
  void reload()
}

function exportRows() {
  window.open(`${ENDPOINT}/export`, '_blank')
}

function openCreate() {
  errorMessage.value = '数据集定义登记入口尚未接入审批流'
}

function openBind(datastoreId: number) {
  activeDatastoreId.value = datastoreId
  confirmCandidates.value = []
  pickerOpen.value = true
  errorMessage.value = ''
}

function closePicker() {
  pickerOpen.value = false
  confirmCandidates.value = []
}

async function onBound() {
  closePicker()
  await reload()
}

function onConflict(error: CandidateConflictError) {
  // 重名冲突：让用户在同一选择器里确认具体候选，而不是静默挑一条连接。
  confirmCandidates.value = error.candidates
  errorMessage.value = error.message
}

function onPickerError(message: string) {
  errorMessage.value = message
}

async function inspectBinding(row: Row) {
  try {
    const status: BindingStatus = await getBinding(Number(row.id))
    const view: Record<string, unknown> = {
      是否仍可新建绑定: status.still_bindable ? '是' : '否（已绑定记录不受影响）',
      连接实时状态: status.live_status ?? '未知',
      ...(status.snapshot ?? {}),
    }
    bindingDetail.value = view
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : '绑定状态读取失败'
  }
}

/** 历史只有名称的记录：先按名称尝试解析，冲突时弹出候选确认。 */
async function resolveLegacyName(row: Row) {
  const name = String(row.来源表名 ?? '')
  if (!name) return
  try {
    const result = await bindDatastore(Number(row.id), { source_name: name })
    if (result.ok) await reload()
  } catch (error) {
    if (error instanceof CandidateConflictError) {
      activeDatastoreId.value = Number(row.id)
      confirmCandidates.value = error.candidates
      pickerOpen.value = true
      errorMessage.value = error.message
      return
    }
    if (error instanceof ForbiddenError) {
      errorMessage.value = error.message
      return
    }
    errorMessage.value = error instanceof Error ? error.message : '来源解析失败'
  }
}

async function runAction(action: string, row: Row) {
  errorMessage.value = ''
  try {
    const response = await request(`${ENDPOINT}/${row.id}/actions`, {
      method: 'POST',
      body: JSON.stringify({ values: { action } }),
    })
    if (!response.ok) {
      throw new Error('数据集管理动作未生效，请稍后重试')
    }
    await reload()
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : '数据集管理操作失败'
  }
}

async function refreshBindingWarnings() {
  const warnings: Record<number, boolean> = {}
  for (const row of rows.value) {
    if (!row.来源连接ID) continue
    try {
      const status = await getBinding(Number(row.id))
      if (status.bound && status.still_bindable === false) {
        warnings[Number(row.id)] = true
      }
    } catch {
      // 状态回显失败不阻塞列表，只跳过标记。
    }
  }
  bindingWarnings.value = warnings
}

function searchFromFirstPage() {
  void reload()
}

async function reload() {
  errorMessage.value = ''
  const params = new URLSearchParams()
  for (const field of filterFields) {
    if (filters[field.key]) params.set(field.key, filters[field.key])
  }
  const result = await listRunner.run(() => request(`${ENDPOINT}?${params.toString()}`))
  // 快速修改关键词产生的晚到响应直接丢弃，不覆盖新条件下的列表。
  if (!result.ok) return
  try {
    const response = result.value
    if (!response.ok) {
      throw new Error('数据集定义列表读取失败')
    }
    const payload = await response.json()
    rows.value = payload.items ?? []
    total.value = payload.total ?? rows.value.length
    await refreshBindingWarnings()
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : '数据集管理列表读取失败'
  }
}

onMounted(() => {
  void reload()
})

onBeforeUnmount(() => listRunner.invalidate())
</script>

<style scoped>
.modal-mask {
  position: fixed;
  inset: 0;
  background: rgba(15, 23, 42, 0.45);
  display: flex;
  align-items: center;
  justify-content: center;
  z-index: 20;
}
.modal-panel {
  width: min(960px, 92vw);
  max-height: 86vh;
  overflow: auto;
  background: #fff;
  border-radius: 10px;
  padding: 16px;
}
.detail-panel {
  width: min(560px, 92vw);
}
.detail-list {
  display: grid;
  grid-template-columns: 140px 1fr;
  gap: 6px 12px;
  font-size: 13px;
}
.detail-list dt {
  color: var(--muted);
}
.detail-list dd {
  margin: 0;
}
.tag {
  margin-left: 6px;
  padding: 1px 6px;
  border-radius: 10px;
  font-size: 11px;
}
.tag-off {
  background: #fef3f2;
  color: #b42318;
}
.muted-text {
  color: var(--muted);
  font-size: 12px;
  margin-right: 8px;
}
</style>
