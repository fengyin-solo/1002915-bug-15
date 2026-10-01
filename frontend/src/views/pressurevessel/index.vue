<template>
  <section class="page" data-module="pressurevessel">
    <header class="page-head">
      <div>
        <h2>压力容器管理</h2>
        <p class="page-desc">维护压力容器，围绕容器编号、容器类别、设计压力、工作温度做登记、筛选与状态流转。审批按环节逐段推进：正常 → 超压运行 → 降压运行 → 检验中 → 已停用。</p>
      </div>
      <div class="page-actions">
        <button class="btn primary" type="button" @click="openCreate">登记压力容器</button>
        <button class="btn" type="button" @click="exportRows">导出压力容器清单</button>
      </div>
    </header>

    <div class="stat-row">
      <article v-for="item in stats" :key="item.label" class="stat-card">
        <span class="stat-label">{{ item.label }}</span>
        <strong class="stat-value">{{ item.value }}</strong>
      </article>
    </div>

    <form class="filter-bar" @submit.prevent="searchFirstPage">
      <label class="filter-item">
        <span>容器编号</span>
        <input v-model="filters.keyword" placeholder="按容器编号检索" />
      </label>
      <label class="filter-item">
        <span>容器类别</span>
        <input v-model="filters.category" placeholder="按容器类别检索" />
      </label>
      <label class="filter-item">
        <span>设计压力</span>
        <input v-model="filters.designPressure" placeholder="按设计压力检索" />
      </label>
      <button class="btn" type="submit">查询</button>
      <button class="btn ghost" type="button" @click="resetFilters">重置条件</button>
    </form>

    <div v-if="errorMessage" class="error-banner">
      <span>{{ errorMessage }}</span>
      <button class="btn" type="button" @click="reload">重试</button>
    </div>

    <table class="data-table">
      <thead>
        <tr>
          <th v-for="column in columns" :key="column">{{ column }}</th>
          <th>可执行动作</th>
        </tr>
      </thead>
      <tbody>
        <tr v-for="row in rows" :key="String(row.id)">
          <td v-for="column in columns" :key="column">{{ row[column] === '' || row[column] == null ? '—' : row[column] }}</td>
          <td class="row-actions">
            <button class="link" type="button" @click="openDetail(row)">详情</button>
            <button class="link" type="button" @click="openEdit(row)">编辑</button>
            <button
              v-for="action in actions"
              :key="action"
              class="link"
              :class="{ disabled: !canRun(action, row) }"
              type="button"
              @click="runAction(action, row)"
            >
              {{ action }}
            </button>
          </td>
        </tr>
        <tr v-if="!rows.length">
          <td :colspan="columns.length + 1" class="empty-state">
            {{ errorMessage ? '列表暂时加载失败，原有记录仍保留在本页，可点上方重试' : '暂无压力容器数据，可先登记压力容器' }}
          </td>
        </tr>
      </tbody>
    </table>

    <footer class="page-foot">
      <span>共 {{ total }} 条压力容器记录，第 {{ page }} / {{ totalPages }} 页</span>
      <span class="pager">
        <button class="btn" type="button" :disabled="page <= 1" @click="goPage(page - 1)">上一页</button>
        <button
          v-for="p in pageNumbers"
          :key="p"
          class="btn"
          :class="{ primary: p === page }"
          type="button"
          @click="goPage(p)"
        >
          {{ p }}
        </button>
        <button class="btn" type="button" :disabled="page >= totalPages" @click="goPage(page + 1)">下一页</button>
      </span>
    </footer>

    <div v-if="modalOpen" class="modal-mask" @click.self="closeModal">
      <div class="modal">
        <header class="modal-head">
          <strong>{{ modalTitle }}</strong>
          <button class="link" type="button" @click="closeModal">关闭</button>
        </header>
        <div v-if="modalMode === 'detail'" class="modal-body">
          <p v-for="field in formFields" :key="field.key" class="detail-line">
            <span class="detail-key">{{ field.key }}</span>
            <span>{{ detailData[field.key] === '' || detailData[field.key] == null ? '—' : detailData[field.key] }}</span>
          </p>
          <p class="detail-line">
            <span class="detail-key">当前审批环节</span>
            <span>{{ detailData['容器状态'] }}</span>
          </p>
        </div>
        <form v-else class="modal-body" @submit.prevent="submitForm">
          <label v-for="field in formFields" :key="field.key" class="form-item">
            <span>{{ field.key }}<em v-if="field.required">*</em></span>
            <input v-model="formData[field.key]" :placeholder="`请输入${field.key}`" />
          </label>
          <p v-if="formError" class="error-text">{{ formError }}</p>
          <footer class="modal-foot">
            <button class="btn" type="button" @click="closeModal">取消</button>
            <button class="btn primary" type="submit">保存</button>
          </footer>
        </form>
      </div>
    </div>
  </section>
</template>

<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'

import { request } from '@/api/client'

type Row = Record<string, string | number | null>
type ModalMode = 'create' | 'edit' | 'detail'

const ENDPOINT = '/api/pressurevessel'
const PAGE_SIZE = 20
const STORAGE_KEY = 'pressurevessel:list-state'
const columns = ["容器编号", "容器类别", "设计压力", "工作温度", "介质名称", "容积", "安全附件", "容器状态"]
const statuses = ["正常", "超压运行", "降压运行", "检验中", "已停用"]
// 动作逐段推进：键为动作，值为动作执行前必须停留的环节
const actionPrerequisite: Record<string, string> = {
  "超压运行": "正常",
  "降压运行": "超压运行",
  "安排检验": "降压运行",
  "办理停用": "检验中",
}
const actions = Object.keys(actionPrerequisite)
const stats = [{ "label": "正常容器", "value": 0 }, { "label": "超压容器", "value": 0 }, { "label": "检验容器", "value": 0 }]
const formFields = columns
  .filter((key) => key !== '容器状态')
  .map((key) => ({ key, required: ["容器编号", "容器类别", "设计压力"].includes(key) }))

const rows = ref<Row[]>([])
const total = ref(0)
const page = ref(1)
const errorMessage = ref('')
const filters = ref<Record<string, string>>({ keyword: '', category: '', designPressure: '' })

const totalPages = computed(() => Math.max(1, Math.ceil(total.value / PAGE_SIZE)))
const pageNumbers = computed(() => {
  const last = totalPages.value
  const start = Math.max(1, Math.min(page.value - 2, last - 4))
  return Array.from({ length: Math.min(5, last) }, (_, index) => start + index).filter((p) => p <= last)
})

const modalOpen = ref(false)
const modalMode = ref<ModalMode>('create')
const formData = ref<Record<string, string>>({})
const detailData = ref<Row>({})
const formError = ref('')
const editingId = ref<number | null>(null)

const modalTitle = computed(() => {
  if (modalMode.value === 'create') return '登记压力容器'
  if (modalMode.value === 'edit') return `编辑压力容器 #${editingId.value}`
  return `压力容器详情 #${editingId.value}`
})

function canRun(action: string, row: Row): boolean {
  return String(row.status ?? row['容器状态'] ?? '') === actionPrerequisite[action]
}

function persistState() {
  // 翻页/筛选状态记在本地，重新进入或刷新后仍停在刚才那一页
  sessionStorage.setItem(STORAGE_KEY, JSON.stringify({ page: page.value, filters: filters.value }))
}

function restoreState() {
  const raw = sessionStorage.getItem(STORAGE_KEY)
  if (raw) {
    try {
      const saved = JSON.parse(raw) as { page?: number; filters?: Record<string, string> }
      page.value = Number(saved.page) > 0 ? Number(saved.page) : 1
      filters.value = { keyword: '', category: '', designPressure: '', ...(saved.filters ?? {}) }
    } catch {
      // 本地状态损坏时退回默认首页，不影响列表读取
    }
  }
}

function buildQuery(): string {
  const params = new URLSearchParams()
  if (filters.value.keyword.trim()) params.set('keyword', filters.value.keyword.trim())
  if (filters.value.category.trim()) params.set('category', filters.value.category.trim())
  if (filters.value.designPressure.trim()) params.set('设计压力', filters.value.designPressure.trim())
  params.set('page', String(page.value))
  params.set('size', String(PAGE_SIZE))
  return params.toString()
}

async function readError(response: Response, fallback: string): Promise<string> {
  // 后端给的原因原样带出来：ActionResult.message 优先，其次是 HTTPException 的 detail
  try {
    const payload = await response.json()
    const detail = payload?.message ?? payload?.detail
    if (typeof detail === 'string' && detail.trim()) return detail
    if (Array.isArray(detail) && detail.length) return JSON.stringify(detail)
  } catch {
    // 响应不是 JSON 时继续用兜底文案
  }
  return `${fallback}（HTTP ${response.status}）`
}

async function reload() {
  persistState()
  try {
    const response = await request(`${ENDPOINT}?${buildQuery()}`)
    if (!response.ok) {
      errorMessage.value = await readError(response, '压力容器列表读取失败')
      return
    }
    const payload = await response.json()
    rows.value = payload.items ?? []
    total.value = payload.total ?? rows.value.length
    if (page.value > totalPages.value) {
      page.value = totalPages.value
      await reload()
      return
    }
    errorMessage.value = ''
  } catch (error) {
    // 请求未送达时保留原有记录，不清空、不留白
    errorMessage.value = error instanceof Error ? error.message : '压力容器列表读取失败'
  }
}

function searchFirstPage() {
  page.value = 1
  void reload()
}

function resetFilters() {
  filters.value = { keyword: '', category: '', designPressure: '' }
  page.value = 1
  void reload()
}

function goPage(target: number) {
  if (target < 1 || target > totalPages.value || target === page.value) return
  page.value = target
  void reload()
}

function exportRows() {
  window.open(`${ENDPOINT}/export`, '_blank')
}

function emptyForm(): Record<string, string> {
  return Object.fromEntries(formFields.map((field) => [field.key, '']))
}

function openCreate() {
  modalMode.value = 'create'
  editingId.value = null
  formData.value = emptyForm()
  formError.value = ''
  modalOpen.value = true
}

function openEdit(row: Row) {
  modalMode.value = 'edit'
  editingId.value = Number(row.id)
  formData.value = Object.fromEntries(formFields.map((field) => [field.key, String(row[field.key] ?? '')]))
  formError.value = ''
  modalOpen.value = true
}

async function openDetail(row: Row) {
  modalMode.value = 'detail'
  editingId.value = Number(row.id)
  detailData.value = { ...row }
  formError.value = ''
  modalOpen.value = true
  try {
    // 详情以单条接口为准，和列表页读到的应是同一份落库内容
    const response = await request(`${ENDPOINT}/${row.id}`)
    if (!response.ok) {
      formError.value = await readError(response, '压力容器详情读取失败')
      return
    }
    detailData.value = (await response.json()) as Row
  } catch (error) {
    formError.value = error instanceof Error ? error.message : '压力容器详情读取失败'
  }
}

function closeModal() {
  modalOpen.value = false
}

async function submitForm() {
  formError.value = ''
  const method = modalMode.value === 'create' ? 'POST' : 'PUT'
  const path = modalMode.value === 'create' ? ENDPOINT : `${ENDPOINT}/${editingId.value}`
  try {
    const response = await request(path, {
      method,
      body: JSON.stringify({ values: formData.value }),
    })
    const payload = await response.json()
    if (!response.ok || payload?.ok === false) {
      formError.value = payload?.message ?? `保存失败（HTTP ${response.status}）`
      return
    }
    modalOpen.value = false
    await reload()
  } catch (error) {
    formError.value = error instanceof Error ? error.message : '压力容器保存失败'
  }
}

async function runAction(action: string, row: Row) {
  if (!canRun(action, row)) {
    // 跳着点当场退回，并说明卡在哪一步
    const current = String(row.status ?? row['容器状态'] ?? '未知')
    errorMessage.value = `「${action}」被退回：当前停在「${current}」环节，必须先到「${actionPrerequisite[action]}」才能执行，审批需按 ${statuses.join(' → ')} 逐段推进`
    return
  }
  errorMessage.value = ''
  try {
    const response = await request(`${ENDPOINT}/${row.id}/actions`, {
      method: 'POST',
      body: JSON.stringify({ values: { action } }),
    })
    const payload = await response.json().catch(() => null)
    if (!response.ok || payload?.ok === false) {
      errorMessage.value = payload?.message ?? `动作未生效（HTTP ${response.status}）`
      return
    }
    await reload()
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : '压力容器操作失败'
  }
}

onMounted(() => {
  restoreState()
  void reload()
})
</script>

<style scoped>
.error-banner {
  display: flex;
  justify-content: space-between;
  align-items: center;
  gap: 12px;
  background: #fef3f2;
  border: 1px solid #fda29b;
  color: #b42318;
  border-radius: 6px;
  padding: 8px 12px;
  margin-bottom: 12px;
  font-size: 13px;
}
.pager { display: inline-flex; gap: 6px; }
.pager .btn { padding: 2px 10px; }
.link.disabled { color: #98a2b3; cursor: not-allowed; }
.modal-mask {
  position: fixed;
  inset: 0;
  background: rgba(16, 24, 40, 0.45);
  display: flex;
  align-items: center;
  justify-content: center;
  z-index: 20;
}
.modal {
  width: 520px;
  max-height: 80vh;
  overflow: auto;
  background: #fff;
  border-radius: 10px;
  padding: 16px 20px;
}
.modal-head { display: flex; justify-content: space-between; align-items: center; margin-bottom: 12px; }
.modal-body { display: flex; flex-direction: column; gap: 10px; }
.form-item span { display: block; font-size: 12px; color: var(--muted); margin-bottom: 4px; }
.form-item em { color: #b42318; font-style: normal; margin-left: 2px; }
.form-item input { width: 100%; padding: 6px 8px; border: 1px solid var(--border); border-radius: 6px; }
.modal-foot { display: flex; justify-content: flex-end; gap: 8px; margin-top: 8px; }
.detail-line { display: flex; justify-content: space-between; gap: 16px; margin: 0; font-size: 13px; border-bottom: 1px dashed var(--border); padding-bottom: 6px; }
.detail-key { color: var(--muted); }
</style>
