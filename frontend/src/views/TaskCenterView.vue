<script setup>
import { computed, onMounted, reactive, ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { ElMessage } from 'element-plus'
import { Connection, Cpu, DataAnalysis, Document, Finished, Refresh, Search, View } from '@element-plus/icons-vue'

import { getApiErrorMessage, listGlobalTasks } from '../api/polyAgentApi'
import {
  TASK_MODULES,
  getTaskModule,
} from '../tasks/taskModules'

const router = useRouter()
const route = useRoute()
const loading = ref(false)
const taskRows = ref([])
const total = ref(0)
const summary = ref({ total: 0, running: 0, completed: 0, pending: 0 })
const selectedTask = ref(null)
const taskDrawerVisible = ref(false)

const filters = reactive({
  module_id: route.query.module_id ? String(route.query.module_id) : '',
  status: route.query.status ? String(route.query.status) : '',
  keyword: route.query.keyword ? String(route.query.keyword) : '',
  page: route.query.page ? Number(route.query.page) || 1 : 1,
  page_size: route.query.page_size ? Number(route.query.page_size) || 20 : 20,
})

const moduleOptions = computed(() => [
  { label: '全部模块', value: '' },
  ...TASK_MODULES.map((item) => ({ label: item.name, value: item.id })),
])

const statusOptions = [
  { label: '全部状态', value: '' },
  { label: 'Queued', value: 'queued' },
  { label: 'Running', value: 'running' },
  { label: 'Completed', value: 'completed' },
  { label: 'Failed', value: 'failed' },
  { label: 'Cancelled', value: 'cancelled' },
  { label: 'Draft', value: 'draft' },
  { label: 'Paused', value: 'paused' },
  { label: 'Archived', value: 'archived' },
  { label: 'Blocked Approval', value: 'blocked_approval' },
]

const unavailableModules = computed(() => TASK_MODULES.filter((item) => !item.routes?.center && item.status === 'coming'))

function getStatusTag(status) {
  const map = { queued: 'info', running: 'warning', completed: 'success', failed: 'danger', cancelled: 'info', draft: 'info', paused: 'info', archived: 'info', blocked_approval: 'danger' }
  return map[status] || 'info'
}

function formatDate(value) {
  if (!value) return '-'
  const date = new Date(value)
  if (Number.isNaN(date.getTime())) return value
  return date.toLocaleString()
}

async function loadTasks() {
  loading.value = true
  try {
    const data = await listGlobalTasks({
      module_id: filters.module_id || undefined,
      status: filters.status || undefined,
      keyword: filters.keyword.trim() || undefined,
      page: filters.page,
      page_size: filters.page_size,
    })
    taskRows.value = data.items || []
    total.value = data.total || 0
    summary.value = data.summary || { total: total.value, running: 0, completed: 0, pending: 0 }
  } catch (error) {
    ElMessage.error(getApiErrorMessage(error))
  } finally {
    loading.value = false
  }
}

function handleSearch() {
  filters.page = 1
  syncFiltersToRoute()
  loadTasks()
}

function handleReset() {
  filters.module_id = ''
  filters.status = ''
  filters.keyword = ''
  filters.page = 1
  syncFiltersToRoute()
  loadTasks()
}

function syncFiltersToRoute() {
  router.replace({
    path: route.path,
    query: {
      ...(filters.module_id ? { module_id: filters.module_id } : {}),
      ...(filters.status ? { status: filters.status } : {}),
      ...(filters.keyword.trim() ? { keyword: filters.keyword.trim() } : {}),
      ...(filters.page > 1 ? { page: filters.page } : {}),
      ...(filters.page_size !== 20 ? { page_size: filters.page_size } : {}),
    },
  })
}

function handlePageChange(page) {
  filters.page = page
  syncFiltersToRoute()
  loadTasks()
}

function handleSizeChange(pageSize) {
  filters.page_size = pageSize
  filters.page = 1
  syncFiltersToRoute()
  loadTasks()
}

function navigateTask(row) {
  if (row.route) {
    router.push(row.route)
    return
  }
  ElMessage.info('该任务类型暂未接入详情页')
}

function openTask(row) {
  selectedTask.value = row
  taskDrawerVisible.value = true
}

function actionLabel(row) {
  return row.module_id === 'research-engine' && row.status === 'blocked_approval' ? '审批' : '查看'
}

function actionIcon(row) {
  return row.module_id === 'research-engine' && row.status === 'blocked_approval' ? Finished : View
}

function primaryActionText(row) {
  return row?.module_id === 'research-engine' && row?.status === 'blocked_approval' ? '进入审批' : '进入详情'
}

function openModule(moduleId) {
  const module = getTaskModule(moduleId)
  if (module?.routes?.submit) {
    router.push(module.routes.submit)
    return
  }
  ElMessage.info(`${module?.name || '该模块'} 正在接入中`)
}

function openKnowledgeBase() {
  router.push('/knowledge')
}

function openAlgorithmCenter() {
  router.push({ path: '/vertical-prediction', query: { tab: 'center' } })
}

function openResearchEngine() {
  router.push('/research-engine')
}

function taskSourceRoute(row) {
  if (row?.route?.path) return row.route
  return null
}

function openTaskSource(row) {
  const target = taskSourceRoute(row)
  if (!target) return
  router.push(target)
}

function taskAlgorithmResultTarget(row) {
  const algorithmId = row?.raw?.algorithm_id
  const runId = row?.raw?.run_id || row?.task_id
  if (!algorithmId || !runId) return null
  return { algorithmId, runId }
}

function openTaskAlgorithmResult(row) {
  const target = taskAlgorithmResultTarget(row)
  if (!target) return
  router.push({ path: '/vertical-prediction', query: { tab: 'detail', algorithm_id: target.algorithmId, run_id: target.runId } })
}

function openTaskReport(row) {
  const routeQuery = row?.route?.query || {}
  if (routeQuery.run_id) {
    router.push({ path: '/research-engine', query: { run_id: routeQuery.run_id, action: 'report' } })
    return
  }
  if (routeQuery.research_run_id) {
    router.push({ path: '/research-engine', query: { research_run_id: routeQuery.research_run_id, action: 'report' } })
  }
}

onMounted(() => {
  loadTasks()
})
</script>

<template>
  <div class="global-task-center">
    <section class="panel">
      <div class="panel-header task-header">
        <div>
          <h3 class="panel-title">任务中心</h3>
          <p class="panel-subtitle">全局任务管理器用于统一追踪计算任务、湿实验优化任务和预测模型任务，并支持跨模块回访。</p>
        </div>
        <div class="header-actions">
          <el-button :icon="Connection" @click="openKnowledgeBase">知识库</el-button>
          <el-button :icon="DataAnalysis" @click="openAlgorithmCenter">算法结果</el-button>
          <el-button :icon="Document" @click="openResearchEngine">报告</el-button>
          <el-button :icon="Refresh" :loading="loading" @click="loadTasks">刷新</el-button>
          <el-button :icon="Cpu" @click="$router.push('/computations/runs')">计算任务中心</el-button>
          <el-button type="primary" @click="$router.push('/tasks/submit')">提交任务</el-button>
        </div>
      </div>

      <div class="panel-body">
        <div class="summary-row">
          <div class="summary-item">
            <span>当前筛选</span>
            <strong>{{ summary.total }}</strong>
          </div>
          <div class="summary-item">
            <span>等待中</span>
            <strong>{{ summary.pending }}</strong>
          </div>
          <div class="summary-item">
            <span>运行中</span>
            <strong>{{ summary.running }}</strong>
          </div>
          <div class="summary-item">
            <span>已完成</span>
            <strong>{{ summary.completed }}</strong>
          </div>
        </div>

        <div class="filter-bar">
          <el-select v-model="filters.module_id" placeholder="任务模块" clearable style="width:170px" @change="handleSearch">
            <el-option v-for="item in moduleOptions" :key="item.value" :label="item.label" :value="item.value" />
          </el-select>
          <el-select v-model="filters.status" placeholder="状态" clearable style="width:150px" @change="handleSearch">
            <el-option v-for="item in statusOptions" :key="item.value" :label="item.label" :value="item.value" />
          </el-select>
          <el-input v-model="filters.keyword" class="keyword-input" clearable placeholder="搜索任务编号、标题、模块" @keyup.enter="handleSearch">
            <template #prefix><el-icon><Search /></el-icon></template>
          </el-input>
          <el-button @click="handleSearch">查询</el-button>
          <el-button text @click="handleReset">重置</el-button>
        </div>

        <el-table :data="taskRows" v-loading="loading" stripe style="width:100%">
          <el-table-column prop="task_id" label="任务编号" min-width="190" />
          <el-table-column prop="task_type" label="任务类型" min-width="120" />
          <el-table-column prop="module_name" label="模块" min-width="120" />
          <el-table-column label="任务标题" min-width="220">
            <template #default="{ row }">
              <div class="task-title-cell">
                <strong>{{ row.title }}</strong>
                <span>{{ row.summary }}</span>
              </div>
            </template>
          </el-table-column>
          <el-table-column prop="status" label="状态" min-width="110">
            <template #default="{ row }">
              <el-tag :type="getStatusTag(row.status)" size="small">{{ row.status_text }}</el-tag>
            </template>
          </el-table-column>
          <el-table-column label="创建时间" min-width="170">
            <template #default="{ row }">{{ formatDate(row.created_at) }}</template>
          </el-table-column>
          <el-table-column label="操作" width="120" fixed="right">
            <template #default="{ row }">
              <el-button
                text
                :type="row.module_id === 'research-engine' && row.status === 'blocked_approval' ? 'warning' : 'primary'"
                size="small"
                :icon="actionIcon(row)"
                @click="openTask(row)"
              >
                {{ actionLabel(row) }}
              </el-button>
            </template>
          </el-table-column>
        </el-table>

        <div class="pagination-row">
          <el-pagination
            v-model:current-page="filters.page"
            v-model:page-size="filters.page_size"
            :page-sizes="[10, 20, 50, 100]"
            :total="total"
            layout="total, sizes, prev, pager, next"
            @current-change="handlePageChange"
            @size-change="handleSizeChange"
          />
        </div>
      </div>
    </section>

    <section class="panel">
      <div class="panel-header">
        <h3 class="panel-title">未接入任务类型</h3>
      </div>
      <div class="panel-body unavailable-grid">
        <button v-for="module in unavailableModules" :key="module.id" type="button" class="unavailable-item" @click="openModule(module.id)">
          <span>
            <strong>{{ module.name }}</strong>
            <small>{{ module.category }} · {{ module.statusText }}</small>
          </span>
          <el-tag size="small" type="info">占位</el-tag>
        </button>
      </div>
    </section>

    <el-drawer
      v-model="taskDrawerVisible"
      :title="selectedTask?.title || '任务详情'"
      size="460px"
      class="task-detail-drawer"
    >
      <template v-if="selectedTask">
        <div class="task-detail-summary">
          <el-tag :type="getStatusTag(selectedTask.status)" effect="plain">{{ selectedTask.status_text }}</el-tag>
          <span>{{ selectedTask.module_name }}</span>
        </div>
        <el-descriptions :column="1" border size="small">
          <el-descriptions-item label="任务编号">{{ selectedTask.task_id }}</el-descriptions-item>
          <el-descriptions-item label="任务类型">{{ selectedTask.task_type }}</el-descriptions-item>
          <el-descriptions-item label="摘要">{{ selectedTask.summary || '-' }}</el-descriptions-item>
          <el-descriptions-item label="创建时间">{{ formatDate(selectedTask.created_at) }}</el-descriptions-item>
          <el-descriptions-item label="更新时间">{{ formatDate(selectedTask.updated_at) }}</el-descriptions-item>
        </el-descriptions>
        <div class="task-detail-shortcuts">
          <el-button :icon="DataAnalysis" :disabled="!taskAlgorithmResultTarget(selectedTask)" @click="openTaskAlgorithmResult(selectedTask)">算法结果</el-button>
          <el-button :icon="Document" :disabled="!taskSourceRoute(selectedTask)" @click="openTaskSource(selectedTask)">来源页</el-button>
          <el-button :icon="Document" :disabled="!selectedTask?.route?.query?.run_id && !selectedTask?.route?.query?.research_run_id" @click="openTaskReport(selectedTask)">报告</el-button>
        </div>
        <div class="task-detail-actions">
          <el-button @click="taskDrawerVisible = false">关闭</el-button>
          <el-button type="primary" :icon="actionIcon(selectedTask)" @click="navigateTask(selectedTask)">
            {{ primaryActionText(selectedTask) }}
          </el-button>
        </div>
      </template>
    </el-drawer>
  </div>
</template>

<style scoped>
.global-task-center {
  display: flex;
  flex-direction: column;
  gap: 16px;
}

.task-header,
.header-actions,
.filter-bar {
  display: flex;
  align-items: center;
}

.task-header {
  gap: 16px;
}

.header-actions {
  gap: 10px;
  flex-wrap: wrap;
}

.panel-subtitle {
  margin: 6px 0 0;
  color: var(--app-ink-muted);
  font-size: 13px;
}

.summary-row {
  display: grid;
  grid-template-columns: repeat(4, minmax(0, 1fr));
  gap: 10px;
  margin-bottom: 14px;
}

.summary-item {
  min-height: 56px;
  padding: 10px 12px;
  border: 1px solid var(--app-border-soft);
  border-radius: var(--app-radius-sm);
  background: #f8fbff;
}

.summary-item span {
  display: block;
  color: var(--app-ink-muted);
  font-size: 12px;
}

.summary-item strong {
  color: var(--app-sidebar-from);
  font-size: 22px;
}

.filter-bar {
  gap: 10px;
  margin-bottom: 14px;
  flex-wrap: wrap;
}

.keyword-input {
  width: 280px;
}

.task-title-cell {
  display: flex;
  flex-direction: column;
  gap: 2px;
}

.task-title-cell span {
  color: var(--app-ink-muted);
  font-family: var(--app-mono-font);
  font-size: 12px;
  overflow: hidden;
  text-overflow: ellipsis;
}

.pagination-row {
  display: flex;
  justify-content: flex-end;
  margin-top: 14px;
}

.task-detail-summary,
.task-detail-actions {
  display: flex;
  align-items: center;
}

.task-detail-summary {
  gap: 8px;
  margin-bottom: 14px;
  color: var(--app-ink-muted);
  font-size: 13px;
}

.task-detail-actions {
  justify-content: flex-end;
  gap: 10px;
  margin-top: 16px;
}

.task-detail-shortcuts {
  display: flex;
  align-items: center;
  gap: 8px;
  flex-wrap: wrap;
  margin-top: 14px;
}

.unavailable-grid {
  display: grid;
  grid-template-columns: repeat(3, minmax(0, 1fr));
  gap: 10px;
}

.unavailable-item {
  min-height: 58px;
  padding: 10px 12px;
  border: 1px solid var(--app-border-soft);
  border-radius: var(--app-radius-sm);
  background: #ffffff;
  color: var(--app-ink);
  cursor: pointer;
  display: flex;
  align-items: center;
  justify-content: space-between;
  text-align: left;
}

.unavailable-item strong {
  display: block;
  font-size: 13px;
}

.unavailable-item small {
  display: block;
  margin-top: 2px;
  color: var(--app-ink-muted);
  font-size: 12px;
}

@media (max-width: 1000px) {
  .summary-row,
  .unavailable-grid {
    grid-template-columns: repeat(2, minmax(0, 1fr));
  }
}

@media (max-width: 640px) {
  .summary-row,
  .unavailable-grid {
    grid-template-columns: 1fr;
  }

  .keyword-input {
    width: 100%;
  }
}
</style>
