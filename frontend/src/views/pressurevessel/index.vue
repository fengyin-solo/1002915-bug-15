<template>
  <section class="page" data-module="pressurevessel">
    <header class="page-head">
      <div>
        <h2>压力容器管理</h2>
        <p class="page-desc">维护压力容器，围绕容器编号、容器类别、设计压力、工作温度做登记、筛选与状态流转。</p>
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

    <form class="filter-bar" @submit.prevent="applyFilters">
      <label class="filter-item">
        <span>容器编号</span>
        <input v-model="filters.keyword" placeholder="按容器编号检索" />
      </label>
      <label class="filter-item">
        <span>容器状态</span>
        <select v-model="filters.status">
          <option value="">全部状态</option>
          <option v-for="status in statuses" :key="status" :value="status">{{ status }}</option>
        </select>
      </label>
      <button class="btn" type="submit">查询</button>
      <button class="btn ghost" type="button" @click="resetFilters">重置条件</button>
    </form>

    <p v-if="errorMessage" class="error-banner">{{ errorMessage }}</p>

    <table class="data-table">
      <thead>
        <tr>
          <th v-for="column in columns" :key="column">{{ column }}</th>
          <th>可执行动作</th>
        </tr>
      </thead>
      <tbody>
        <tr v-for="row in rows" :key="String(row.id)">
          <td v-for="column in columns" :key="column">{{ row[column] ?? '—' }}</td>
          <td class="row-actions">
            <button class="link" type="button" @click="openDetail(row)">详情</button>
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
          <td :colspan="columns.length + 1" class="empty-state">暂无压力容器数据，可先登记压力容器</td>
        </tr>
      </tbody>
    </table>

    <footer class="page-foot">
      <span>共 {{ total }} 条压力容器记录</span>
      <div class="pager">
        <button class="btn" type="button" :disabled="page <= 1" @click="goToPage(page - 1)">上一页</button>
        <span>第 {{ page }} / {{ pageCount }} 页</span>
        <button class="btn" type="button" :disabled="page >= pageCount" @click="goToPage(page + 1)">下一页</button>
      </div>
    </footer>

    <div v-if="dialogVisible" class="modal-mask" @click.self="closeDialog">
      <div class="modal">
        <h3>{{ dialogMode === 'create' ? '登记压力容器' : `压力容器详情 #${editingId}` }}</h3>
        <form @submit.prevent="saveForm">
          <label v-for="field in entryFields" :key="field" class="form-item">
            <span>{{ field }}<em v-if="requiredFields.includes(field)">*</em></span>
            <input v-model="form[field]" :placeholder="`请输入${field}`" />
          </label>
          <p v-if="dialogError" class="error-text">{{ dialogError }}</p>
          <div class="modal-actions">
            <button class="btn primary" type="submit">保存</button>
            <button class="btn ghost" type="button" @click="closeDialog">取消</button>
          </div>
        </form>
      </div>
    </div>
  </section>
</template>

<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'

import { request } from '@/api/client'

type Row = Record<string, string | number | null>

const ENDPOINT = '/api/pressurevessel'
const columns = ["容器编号", "容器类别", "设计压力", "工作温度", "介质名称", "容积", "安全附件", "容器状态"]
const actions = ["降压运行", "安排检验", "办理停用"]
const statuses = ["正常", "超压运行", "检验中", "已停用"]
const stats = [{"label": "正常容器", "value": 0}, {"label": "超压容器", "value": 0}, {"label": "检验容器", "value": 0}]
const entryFields = ["容器编号", "容器类别", "设计压力", "工作温度", "介质名称", "容积", "安全附件", "容器状态"]
const requiredFields = ["容器编号", "容器类别", "设计压力"]
const PAGE_KEY = 'pressurevessel.page'
const size = 20

const rows = ref<Row[]>([])
const total = ref(0)
// 重新进入页面时停在刚才那一页
const savedPage = Number(sessionStorage.getItem(PAGE_KEY))
const page = ref(Number.isInteger(savedPage) && savedPage > 0 ? savedPage : 1)
const errorMessage = ref('')
const filters = ref({ keyword: '', status: '' })
const pageCount = computed(() => Math.max(1, Math.ceil(total.value / size)))

const dialogVisible = ref(false)
const dialogMode = ref<'create' | 'edit'>('create')
const editingId = ref<number | null>(null)
const form = ref<Record<string, string>>({})
const dialogError = ref('')

function persistPage() {
  sessionStorage.setItem(PAGE_KEY, String(page.value))
}

async function readError(response: Response, fallback: string): Promise<string> {
  // 接口报错的原因原样带出来，不自己另编一套说辞
  try {
    const body = await response.json()
    if (typeof body?.detail === 'string') return body.detail
    if (Array.isArray(body?.detail)) {
      return body.detail.map((item: { msg?: string }) => item?.msg ?? JSON.stringify(item)).join('；')
    }
    if (typeof body?.message === 'string') return body.message
  } catch {
    // 响应体不是 JSON，退回状态码说明
  }
  return `${fallback}（接口返回 ${response.status}）`
}

function resetFilters() {
  filters.value = { keyword: '', status: '' }
  applyFilters()
}

function applyFilters() {
  page.value = 1
  persistPage()
  void reload()
}

function goToPage(target: number) {
  if (target < 1 || target > pageCount.value) return
  page.value = target
  persistPage()
  void reload()
}

function exportRows() {
  window.open(`${ENDPOINT}/export`, '_blank')
}

function openCreate() {
  dialogMode.value = 'create'
  editingId.value = null
  form.value = Object.fromEntries(entryFields.map((field) => [field, '']))
  dialogError.value = ''
  dialogVisible.value = true
}

async function openDetail(row: Row) {
  errorMessage.value = ''
  try {
    const response = await request(`${ENDPOINT}/${row.id}`)
    if (!response.ok) {
      throw new Error(await readError(response, '压力容器详情读取失败'))
    }
    const detail = await response.json()
    dialogMode.value = 'edit'
    editingId.value = Number(row.id)
    form.value = Object.fromEntries(
      entryFields.map((field) => [field, detail[field] == null ? '' : String(detail[field])]),
    )
    dialogError.value = ''
    dialogVisible.value = true
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : '压力容器详情读取失败'
  }
}

async function saveForm() {
  dialogError.value = ''
  const values = Object.fromEntries(entryFields.map((field) => [field, form.value[field] ?? '']))
  const isCreate = dialogMode.value === 'create'
  const url = isCreate ? ENDPOINT : `${ENDPOINT}/${editingId.value}`
  try {
    const response = await request(url, {
      method: isCreate ? 'POST' : 'PUT',
      body: JSON.stringify({ values }),
    })
    if (!response.ok) {
      throw new Error(await readError(response, '压力容器保存失败'))
    }
    const result = await response.json()
    if (!result?.ok) {
      throw new Error(result?.message ?? '压力容器保存失败')
    }
    dialogVisible.value = false
    await reload()
  } catch (error) {
    dialogError.value = error instanceof Error ? error.message : '压力容器保存失败'
  }
}

function closeDialog() {
  dialogVisible.value = false
}

async function runAction(action: string, row: Row) {
  errorMessage.value = ''
  try {
    const response = await request(`${ENDPOINT}/${row.id}/actions`, {
      method: 'POST',
      body: JSON.stringify({ values: { action } }),
    })
    if (!response.ok) {
      throw new Error(await readError(response, `压力容器${action}未生效`))
    }
    const result = await response.json()
    if (!result?.ok) {
      // 审批被退回：把卡在哪一步的原因原样亮出来
      throw new Error(result?.message ?? `压力容器${action}未生效`)
    }
    await reload()
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : '压力容器操作失败'
  }
}

async function reload() {
  errorMessage.value = ''
  const query = new URLSearchParams()
  if (filters.value.keyword.trim()) query.set('keyword', filters.value.keyword.trim())
  if (filters.value.status) query.set('status', filters.value.status)
  query.set('page', String(page.value))
  query.set('size', String(size))
  try {
    const response = await request(`${ENDPOINT}?${query.toString()}`)
    if (!response.ok) {
      throw new Error(await readError(response, '压力容器列表读取失败'))
    }
    const payload = await response.json()
    const items: Row[] = payload.items ?? []
    // 当前页空了但总量还在：回退一页再拉，避免对着空白页
    if (!items.length && (payload.total ?? 0) > 0 && page.value > 1) {
      page.value -= 1
      persistPage()
      return reload()
    }
    rows.value = items
    total.value = payload.total ?? items.length
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : '压力容器列表读取失败'
  }
}

onMounted(reload)
</script>
