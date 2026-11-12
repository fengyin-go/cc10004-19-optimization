<template>
  <div class="picker" :class="{ 'picker--modal': !embedded }">
    <div class="picker-head">
      <strong>选择连接候选</strong>
      <button v-if="!embedded" class="link" type="button" @click="emitCancel">关闭</button>
    </div>

    <form class="picker-filters" @submit.prevent="searchFromFirstPage">
      <label class="filter-item">
        <span>配置编号</span>
        <input v-model.trim="filters.config_no" placeholder="按配置编号检索" />
      </label>
      <label class="filter-item">
        <span>连接类型</span>
        <input v-model.trim="filters.conn_type" placeholder="按连接类型检索" />
      </label>
      <label class="filter-item">
        <span>接入地址</span>
        <input v-model.trim="filters.address" placeholder="按接入地址检索" />
      </label>
      <label class="filter-item">
        <span>负责人</span>
        <input v-model.trim="filters.owner" placeholder="按负责人定位" />
      </label>
      <button class="btn primary" type="submit">搜索候选</button>
      <button class="btn ghost" type="button" @click="resetFilters">重置</button>
    </form>

    <p v-if="loading" class="picker-hint">候选检索中…</p>
    <p v-else-if="forbidden" class="error-text">{{ forbidden }}</p>
    <p v-else-if="errorMessage" class="error-text">{{ errorMessage }}</p>

    <table v-if="!forbidden" class="data-table picker-table">
      <thead>
        <tr>
          <th>配置编号</th>
          <th>连接类型</th>
          <th>接入地址</th>
          <th>负责人</th>
          <th>状态</th>
          <th>操作</th>
        </tr>
      </thead>
      <tbody>
        <tr v-for="candidate in candidates" :key="candidate.id">
          <td>{{ candidate.配置编号 }}</td>
          <td>{{ candidate.连接类型 }}</td>
          <td>{{ candidate.接入地址 }}</td>
          <td>{{ candidate.负责人 }}</td>
          <td>
            {{ candidate.status }}
            <span v-if="!candidate.bindable" class="tag tag-off">不可绑定</span>
          </td>
          <td>
            <button
              class="link"
              type="button"
              :disabled="!candidate.bindable"
              @click="choose(candidate)"
            >
              选择
            </button>
          </td>
        </tr>
        <tr v-if="!loading && !candidates.length">
          <td colspan="6" class="empty-state">当前条件下没有可用候选，可调整关键词后重新检索</td>
        </tr>
      </tbody>
    </table>

    <footer v-if="!forbidden" class="picker-foot">
      <span>共 {{ total }} 条候选</span>
      <div class="pager">
        <button class="btn" type="button" :disabled="page <= 1 || loading" @click="goPage(page - 1)">
          上一页
        </button>
        <span>第 {{ page }} 页</span>
        <button
          class="btn"
          type="button"
          :disabled="page * size >= total || loading"
          @click="goPage(page + 1)"
        >
          下一页
        </button>
      </div>
    </footer>
  </div>
</template>

<script setup lang="ts">
import { onBeforeUnmount, reactive, ref } from 'vue'

import { LatestOnlyRunner } from '@/api/client'
import {
  CandidateConflictError,
  DisconnectedError,
  ForbiddenError,
  bindDatastore,
  searchCandidates,
  type CandidateFilters,
  type ConnectionCandidate,
} from '@/api/connections'

const props = withDefaults(
  defineProps<{
    /** 数据集 id：传入后“选择”会直接发起绑定；不传则只把候选抛给父组件。 */
    datastoreId?: number
    /** 内嵌在表单里为 true，独立弹窗为 false。 */
    embedded?: boolean
    /** 每页条数，默认 5，保证同址多负责人、同人多地址都能分开看到。 */
    pageSize?: number
    /** 409 重名冲突时由后端带回的候选，进入确认视图。 */
    confirmCandidates?: ConnectionCandidate[]
  }>(),
  { datastoreId: 0, embedded: true, pageSize: 5, confirmCandidates: () => [] },
)

const emit = defineEmits<{
  (e: 'select', candidate: ConnectionCandidate): void
  (e: 'bound', entry: Record<string, unknown>): void
  (e: 'cancel'): void
  (e: 'conflict', error: CandidateConflictError): void
  (e: 'error', message: string): void
}>()

const runner = new LatestOnlyRunner()
const filters = reactive<CandidateFilters>({
  config_no: '',
  conn_type: '',
  address: '',
  owner: '',
})
const candidates = ref<ConnectionCandidate[]>([])
const total = ref(0)
const page = ref(1)
// 确认模式下候选一次性全部展示，避免重名列表被分页截断。
const size = props.confirmCandidates.length
  ? Math.max(props.pageSize, props.confirmCandidates.length)
  : props.pageSize
const loading = ref(false)
const errorMessage = ref('')
const forbidden = ref('')

async function loadCandidates(targetPage: number) {
  loading.value = true
  errorMessage.value = ''
  forbidden.value = ''
  const result = await runner.run(() => searchCandidates({ ...filters }, targetPage, size))
  // 晚到响应：条件已被更新，直接丢弃，绝不能覆盖新条件下的界面。
  if (!result.ok) {
    loading.value = false
    return
  }
  try {
    const payload = await result.value
    candidates.value = payload.items
    total.value = payload.total
    page.value = targetPage
  } catch (error) {
    if (error instanceof ForbiddenError) {
      // 越权：清空候选与计数，不展示 total，避免侧面暴露匹配数量。
      candidates.value = []
      total.value = 0
      forbidden.value = error.message
    } else {
      errorMessage.value = error instanceof Error ? error.message : '连接候选读取失败'
    }
  } finally {
    loading.value = false
  }
}

function searchFromFirstPage() {
  void loadCandidates(1)
}

function goPage(target: number) {
  if (target < 1 || (target - 1) * size >= total.value) return
  void loadCandidates(target)
}

function resetFilters() {
  filters.config_no = ''
  filters.conn_type = ''
  filters.address = ''
  filters.owner = ''
  void loadCandidates(1)
}

async function choose(candidate: ConnectionCandidate) {
  // 选择前再次确认候选仍可绑定：失效时保留当前检索输入，提示用户重新选择，
  // 而不是悄悄切到别的连接。
  if (!candidate.bindable) {
    errorMessage.value = '该连接已断开或失效，请保留当前关键词重新选择其他候选'
    return
  }
  if (!props.datastoreId) {
    emit('select', candidate)
    return
  }
  try {
    const result = await bindDatastore(props.datastoreId, { source_id: candidate.id })
    if (result.ok) {
      emit('bound', result.entry ?? {})
      return
    }
    // 选择瞬间候选已失效（如连接刚断开）：就地标记并保留检索输入，
    // 让用户在原条件下重新选择，而不是悄悄切到别的连接。
    if (result.message.includes('断开')) {
      markStale(candidate.id)
    }
    errorMessage.value = `${result.message}；检索条件已保留，可重新选择`
  } catch (error) {
    if (error instanceof ForbiddenError) {
      forbidden.value = error.message
      return
    }
    if (error instanceof DisconnectedError) {
      // 候选在选择瞬间失效：标记该候选并保留输入，不替换成别的连接。
      markStale(candidate.id)
      errorMessage.value = `${error.message}；已保留检索条件，请重新选择`
      return
    }
    if (error instanceof CandidateConflictError) {
      emit('conflict', error)
      return
    }
    errorMessage.value = error instanceof Error ? error.message : '来源绑定失败'
    emit('error', errorMessage.value)
  }
}

function markStale(id: number) {
  candidates.value = candidates.value.map((item) =>
    item.id === id ? { ...item, bindable: false, status: '已断开' } : item,
  )
}

function emitCancel() {
  runner.invalidate()
  emit('cancel')
}

onBeforeUnmount(() => runner.invalidate())

// 409 确认视图：直接展示后端带回的候选，不再发检索请求；否则进入正常检索。
if (props.confirmCandidates.length) {
  candidates.value = props.confirmCandidates
  total.value = props.confirmCandidates.length
} else {
  void loadCandidates(1)
}

// 暴露给父组件在绑定成功后刷新候选实时状态。
defineExpose({ reload: () => loadCandidates(page.value) })
</script>

<style scoped>
.picker {
  border: 1px solid var(--border);
  border-radius: 8px;
  background: #fff;
  padding: 12px;
}
.picker--modal {
  box-shadow: 0 12px 32px rgba(15, 23, 42, 0.18);
}
.picker-head {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-bottom: 8px;
}
.picker-filters {
  display: flex;
  flex-wrap: wrap;
  gap: 10px;
  align-items: flex-end;
  margin-bottom: 10px;
}
.picker-table {
  margin-top: 4px;
}
.picker-foot {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-top: 8px;
  font-size: 12px;
  color: var(--muted);
}
.pager {
  display: flex;
  gap: 8px;
  align-items: center;
}
.picker-hint {
  font-size: 12px;
  color: var(--muted);
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
.link:disabled {
  color: #94a3b8;
  cursor: not-allowed;
}
</style>
