<script setup>
import { computed, onMounted, reactive, ref } from 'vue'
import { useRouter } from 'vue-router'
import { ElMessage } from 'element-plus'
import { Refresh, Search, View } from '@element-plus/icons-vue'

import { getApiErrorMessage, listAlgorithmRuns, listCampaigns, listComputations, listResearchRuns } from '../api/polyAgentApi'
import {
  TASK_MODULES,
  getTaskModule,
  isResearchEngineContainerCampaign,
  mapAlgorithmRunToGlobalTask,
  mapCampaignToGlobalTask,
  mapComputationRunToGlobalTask,
  mapResearchRunToGlobalTask,
} from '../tasks/taskModules'

const router = useRouter()
const loading = ref(false)
const computationRows = ref([])
const campaignRows = ref([])
const algorithmRuns = ref([])
const researchRuns = ref([])
const total = ref(0)

const filters = reactive({
  module_id: '',
  status: '',
  keyword: '',
  page: 1,
  page_size: 20,
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

const taskRows = computed(() => {
  const rows = [
    ...computationRows.value.map(mapComputationRunToGlobalTask),
    ...campaignRows.value.filter((item) => !isResearchEngineContainerCampaign(item)).map(mapCampaignToGlobalTask),
    ...algorithmRuns.value.map(mapAlgorithmRunToGlobalTask),
    ...researchRuns.value.map(mapResearchRunToGlobalTask),
  ].sort((a, b) => new Date(b.updated_at || b.created_at || 0).getTime() - new Date(a.updated_at || a.created_at || 0).getTime())
  const normalizedKeyword = filters.keyword.trim().toLowerCase()
  return rows.filter((row) => {
    const matchesModule = !filters.module_id || row.module_id === filters.module_id
    const matchesStatus = !filters.status || row.status === filters.status
    const haystack = `${row.task_id} ${row.task_type} ${row.module_name} ${row.title} ${row.summary}`.toLowerCase()
    const matchesKeyword = !normalizedKeyword || haystack.includes(normalizedKeyword)
    return matchesModule && matchesStatus && matchesKeyword
  })
})

const unavailableModules = computed(() => TASK_MODULES.filter((item) => !item.routes?.center && item.status === 'coming'))

const summary = computed(() => {
  const counts = { total: taskRows.value.length, running: 0, completed: 0, pending: 0 }
  for (const item of taskRows.value) {
    if (item.status === 'running') counts.running += 1
    if (item.status === 'completed') counts.completed += 1
    if (item.status === 'queued') counts.pending += 1
  }
  return counts
})

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
    const [computations, campaigns, algoRuns, researchRunsData] = await Promise.all([
      listComputations({ page: filters.page, page_size: filters.page_size }),
      listCampaigns({ page: filters.page, page_size: filters.page_size }),
      listAlgorithmRuns({ page: filters.page, page_size: filters.page_size }).catch(() => ({ items: [], total: 0 })),
      listResearchRuns({ page: filters.page, page_size: filters.page_size }).catch(() => ({ items: [], total: 0 })),
    ])
    computationRows.value = computations.items || []
    campaignRows.value = campaigns.items || []
    algorithmRuns.value = algoRuns.items || []
    researchRuns.value = researchRunsData.items || []
    total.value = (computations.total || 0) + (campaigns.total || 0) + (algoRuns.total || 0) + (researchRunsData.total || 0)
  } catch (error) {
    ElMessage.error(getApiErrorMessage(error))
  } finally {
    loading.value = false
  }
}

function handleSearch() {
  filters.page = 1
  loadTasks()
}

function handleReset() {
  filters.module_id = ''
  filters.status = ''
  filters.keyword = ''
  filters.page = 1
  loadTasks()
}

function openTask(row) {
  if (row.route) {
    router.push(row.route)
    return
  }
  ElMessage.info('该任务类型暂未接入详情页')
}

function openModule(moduleId) {
  const module = getTaskModule(moduleId)
  if (module?.routes?.submit) {
    router.push(module.routes.submit)
    return
  }
  ElMessage.info(`${module?.name || '该模块'} 正在接入中`)
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
          <p class="panel-subtitle">这里是全局任务管理器。计算任务、湿实验优化和预测模型任务统一从这里回访。</p>
        </div>
        <div class="header-actions">
          <el-button :icon="Refresh" :loading="loading" @click="loadTasks">刷新</el-button>
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
          <el-table-column label="操作" width="110" fixed="right">
            <template #default="{ row }">
              <el-button text type="primary" size="small" :icon="View" @click="openTask(row)">查看</el-button>
            </template>
          </el-table-column>
        </el-table>
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
