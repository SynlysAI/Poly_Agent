<script setup>
import { computed, onBeforeUnmount, onMounted, reactive, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { ElMessage, ElMessageBox } from 'element-plus'
import { Download, Refresh, Search, VideoPause, View } from '@element-plus/icons-vue'

import {
  cancelComputation,
  getApiErrorMessage,
  getArtifactDownloadUrl,
  getComputation,
  getIntegrationStatus,
  listComputationArtifacts,
  listComputations,
  previewArtifact,
  retryComputation,
} from '../api/polyAgentApi'

const route = useRoute()
const router = useRouter()
const tasks = ref([])
const total = ref(0)
const loading = ref(false)
const detailLoading = ref(false)
const detailVisible = ref(false)
const selectedRun = ref(null)
const artifacts = ref([])
const artifactPreview = ref(null)
const integrations = ref([])
const integrationLoading = ref(false)
const pollTimer = ref(null)

const filters = reactive({
  status: '',
  workflow_type: '',
  engine: '',
  keyword: '',
  page: 1,
  page_size: 20,
})

const statusOptions = [
  { label: '全部', value: '' },
  { label: 'Queued', value: 'queued' },
  { label: 'Running', value: 'running' },
  { label: 'Completed', value: 'completed' },
  { label: 'Failed', value: 'failed' },
  { label: 'Cancelled', value: 'cancelled' },
]

const workflowOptions = [
  { label: '全部', value: '' },
  { label: 'MOCK_XTB_ONLY', value: 'MOCK_XTB_ONLY' },
  { label: 'MOCK_LASER', value: 'MOCK_LASER' },
]

const statusSummary = computed(() => {
  const counts = { queued: 0, running: 0, completed: 0, failed: 0, cancelled: 0 }
  for (const item of tasks.value) {
    if (counts[item.status] !== undefined) counts[item.status] += 1
  }
  return counts
})

const hasActiveRuns = computed(() => tasks.value.some((item) => ['queued', 'running'].includes(item.status)))

function getStatusTag(status) {
  const map = { queued: 'info', running: 'warning', completed: 'success', failed: 'danger', cancelled: 'info' }
  return map[status] || 'info'
}

function formatDate(value) {
  if (!value) return '-'
  const date = new Date(value)
  if (Number.isNaN(date.getTime())) return value
  return date.toLocaleString()
}

function compactJson(value) {
  if (!value || Object.keys(value).length === 0) return '{}'
  return JSON.stringify(value, null, 2)
}

async function loadTasks() {
  loading.value = true
  try {
    const params = {
      page: filters.page,
      page_size: filters.page_size,
    }
    if (filters.status) params.status = filters.status
    if (filters.workflow_type) params.workflow_type = filters.workflow_type
    if (filters.engine) params.engine = filters.engine
    if (filters.keyword) params.keyword = filters.keyword
    const data = await listComputations(params)
    tasks.value = data.items || []
    total.value = data.total || 0
    syncPolling()
  } catch (error) {
    ElMessage.error(getApiErrorMessage(error))
  } finally {
    loading.value = false
  }
}

async function loadIntegrations() {
  integrationLoading.value = true
  try {
    const data = await getIntegrationStatus()
    integrations.value = data.items || []
  } catch (error) {
    ElMessage.error(getApiErrorMessage(error))
  } finally {
    integrationLoading.value = false
  }
}

async function openDetail(runId) {
  detailVisible.value = true
  artifactPreview.value = null
  await loadDetail(runId)
  router.replace({ path: '/computations/runs', query: { ...route.query, run_id: runId } })
}

async function loadDetail(runId) {
  detailLoading.value = true
  try {
    const [run, artifactData] = await Promise.all([
      getComputation(runId),
      listComputationArtifacts(runId).catch(() => ({ items: [] })),
    ])
    selectedRun.value = run
    artifacts.value = artifactData.items || []
  } catch (error) {
    ElMessage.error(getApiErrorMessage(error))
  } finally {
    detailLoading.value = false
  }
}

async function handlePreviewArtifact(artifactId) {
  try {
    artifactPreview.value = await previewArtifact(artifactId)
  } catch (error) {
    ElMessage.error(getApiErrorMessage(error))
  }
}

async function handleCancel(run) {
  try {
    await ElMessageBox.confirm(`确认取消任务 ${run.run_id}？`, '取消计算任务', { type: 'warning' })
    await cancelComputation(run.run_id)
    ElMessage.success('任务已取消')
    await loadTasks()
    if (selectedRun.value?.run_id === run.run_id) await loadDetail(run.run_id)
  } catch (error) {
    if (error === 'cancel') return
    ElMessage.error(getApiErrorMessage(error))
  }
}

async function handleRetry(run) {
  try {
    const data = await retryComputation(run.run_id)
    ElMessage.success(`已创建重试任务：${data.run_id}`)
    await loadTasks()
    await openDetail(data.run_id)
  } catch (error) {
    ElMessage.error(getApiErrorMessage(error))
  }
}

function handleSearch() {
  filters.page = 1
  loadTasks()
}

function handleReset() {
  filters.status = ''
  filters.workflow_type = ''
  filters.engine = ''
  filters.keyword = ''
  filters.page = 1
  loadTasks()
}

function syncPolling() {
  if (pollTimer.value || !hasActiveRuns.value) {
    if (!hasActiveRuns.value && pollTimer.value) {
      clearInterval(pollTimer.value)
      pollTimer.value = null
    }
    return
  }
  pollTimer.value = setInterval(async () => {
    await loadTasks()
    if (selectedRun.value && ['queued', 'running'].includes(selectedRun.value.status)) {
      await loadDetail(selectedRun.value.run_id)
    }
  }, 3000)
}

watch(detailVisible, (visible) => {
  if (!visible) {
    selectedRun.value = null
    artifactPreview.value = null
    const nextQuery = { ...route.query }
    delete nextQuery.run_id
    router.replace({ path: '/computations/runs', query: nextQuery })
  }
})

onMounted(async () => {
  await Promise.all([loadTasks(), loadIntegrations()])
  if (route.query.run_id) {
    await openDetail(String(route.query.run_id))
  }
})

onBeforeUnmount(() => {
  if (pollTimer.value) clearInterval(pollTimer.value)
})
</script>

<template>
  <div class="task-center">
    <section class="panel">
      <div class="panel-header task-header">
        <div>
          <h3 class="panel-title">计算任务中心</h3>
          <p class="panel-subtitle">任务生命周期、workflow timeline、artifact 和结果摘要统一追踪。</p>
        </div>
        <div class="header-actions">
          <el-button :icon="Refresh" :loading="loading" @click="loadTasks">刷新</el-button>
          <el-button type="primary" @click="$router.push('/computations/submit')">提交计算任务</el-button>
        </div>
      </div>
      <div class="panel-body">
        <div class="summary-row">
          <div class="summary-item">
            <span class="summary-label">Queued</span>
            <strong>{{ statusSummary.queued }}</strong>
          </div>
          <div class="summary-item">
            <span class="summary-label">Running</span>
            <strong>{{ statusSummary.running }}</strong>
          </div>
          <div class="summary-item">
            <span class="summary-label">Completed</span>
            <strong>{{ statusSummary.completed }}</strong>
          </div>
          <div class="summary-item">
            <span class="summary-label">Failed</span>
            <strong>{{ statusSummary.failed }}</strong>
          </div>
        </div>

        <div class="filter-bar">
          <el-select v-model="filters.status" placeholder="状态" clearable style="width:140px" @change="handleSearch">
            <el-option v-for="item in statusOptions" :key="item.value" :label="item.label" :value="item.value" />
          </el-select>
          <el-select v-model="filters.workflow_type" placeholder="Workflow" clearable style="width:170px" @change="handleSearch">
            <el-option v-for="item in workflowOptions" :key="item.value" :label="item.label" :value="item.value" />
          </el-select>
          <el-select v-model="filters.engine" placeholder="Engine" clearable style="width:130px" @change="handleSearch">
            <el-option label="全部" value="" />
            <el-option label="MOCK" value="MOCK" />
          </el-select>
          <el-input v-model="filters.keyword" placeholder="run id / 名称 / SMILES" clearable class="keyword-input" @keyup.enter="handleSearch">
            <template #prefix><el-icon><Search /></el-icon></template>
          </el-input>
          <el-button @click="handleSearch">查询</el-button>
          <el-button text @click="handleReset">重置</el-button>
        </div>

        <el-table :data="tasks" v-loading="loading" stripe style="width:100%">
          <el-table-column prop="run_id" label="Run ID" min-width="190" />
          <el-table-column label="Molecule" min-width="190">
            <template #default="{ row }">
              <div class="molecule-cell">
                <strong>{{ row.molecule?.name || '-' }}</strong>
                <span>{{ row.molecule?.smiles }}</span>
              </div>
            </template>
          </el-table-column>
          <el-table-column prop="workflow_type" label="Workflow" min-width="140" />
          <el-table-column prop="engine" label="Engine" min-width="90" />
          <el-table-column prop="status" label="状态" min-width="110">
            <template #default="{ row }">
              <el-tag :type="getStatusTag(row.status)" size="small">{{ row.status }}</el-tag>
            </template>
          </el-table-column>
          <el-table-column label="创建时间" min-width="170">
            <template #default="{ row }">{{ formatDate(row.created_at) }}</template>
          </el-table-column>
          <el-table-column label="操作" min-width="210" fixed="right">
            <template #default="{ row }">
              <el-button text type="primary" size="small" :icon="View" @click="openDetail(row.run_id)">查看</el-button>
              <el-button v-if="['queued', 'running'].includes(row.status)" text type="warning" size="small" :icon="VideoPause" @click="handleCancel(row)">取消</el-button>
              <el-button v-if="['failed', 'cancelled'].includes(row.status)" text type="primary" size="small" @click="handleRetry(row)">重试</el-button>
            </template>
          </el-table-column>
        </el-table>
      </div>
    </section>

    <section class="panel integration-panel">
      <div class="panel-header">
        <h3 class="panel-title">集成状态</h3>
        <el-button text :icon="Refresh" :loading="integrationLoading" @click="loadIntegrations">刷新</el-button>
      </div>
      <div class="panel-body integration-grid">
        <div v-for="item in integrations" :key="item.service" class="integration-item">
          <span>{{ item.service }}</span>
          <el-tag size="small" :type="item.status === 'up' || item.status === 'available' ? 'success' : 'info'">{{ item.status }}</el-tag>
        </div>
      </div>
    </section>

    <el-drawer v-model="detailVisible" title="计算任务详情" size="58%" class="run-drawer">
      <div v-loading="detailLoading" class="detail-body">
        <template v-if="selectedRun">
          <div class="detail-heading">
            <div>
              <h3>{{ selectedRun.run_id }}</h3>
              <p>{{ selectedRun.molecule?.name || '-' }} · {{ selectedRun.workflow_type }} · {{ selectedRun.engine }}</p>
            </div>
            <el-tag :type="getStatusTag(selectedRun.status)">{{ selectedRun.status }}</el-tag>
          </div>

          <el-descriptions :column="2" border size="small">
            <el-descriptions-item label="SMILES">{{ selectedRun.molecule?.smiles }}</el-descriptions-item>
            <el-descriptions-item label="Created">{{ formatDate(selectedRun.created_at) }}</el-descriptions-item>
            <el-descriptions-item label="Started">{{ formatDate(selectedRun.started_at) }}</el-descriptions-item>
            <el-descriptions-item label="Finished">{{ formatDate(selectedRun.finished_at) }}</el-descriptions-item>
            <el-descriptions-item label="Campaign">{{ selectedRun.campaign_id || '-' }}</el-descriptions-item>
            <el-descriptions-item label="Suggestion">{{ selectedRun.suggestion_id || '-' }}</el-descriptions-item>
          </el-descriptions>

          <h4 class="detail-section-title">Workflow timeline</h4>
          <el-timeline>
            <el-timeline-item
              v-for="step in selectedRun.steps"
              :key="step.step_key"
              :timestamp="formatDate(step.finished_at || step.started_at)"
              :type="step.status === 'completed' ? 'success' : step.status === 'running' ? 'warning' : 'info'"
            >
              <div class="timeline-step">
                <strong>{{ step.label || step.step_key }}</strong>
                <el-tag size="small" :type="getStatusTag(step.status)">{{ step.status }}</el-tag>
              </div>
              <p v-if="step.error" class="error-text">{{ step.error }}</p>
            </el-timeline-item>
            <el-timeline-item v-if="!selectedRun.steps?.length" type="info">等待 worker 接收任务</el-timeline-item>
          </el-timeline>

          <h4 class="detail-section-title">Result summary</h4>
          <pre class="json-block result-json">{{ compactJson(selectedRun.result_summary) }}</pre>

          <h4 class="detail-section-title">Artifacts</h4>
          <el-table :data="artifacts" size="small" border>
            <el-table-column prop="name" label="文件" min-width="150" />
            <el-table-column prop="artifact_type" label="类型" min-width="130" />
            <el-table-column prop="size_bytes" label="大小" width="100" />
            <el-table-column label="操作" width="170">
              <template #default="{ row }">
                <el-button text type="primary" size="small" @click="handlePreviewArtifact(row.artifact_id)">预览</el-button>
                <el-button text type="primary" size="small" :icon="Download" tag="a" :href="getArtifactDownloadUrl(row.artifact_id)" target="_blank">下载</el-button>
              </template>
            </el-table-column>
          </el-table>

          <div v-if="artifactPreview" class="artifact-preview">
            <h4 class="detail-section-title">Artifact preview · {{ artifactPreview.artifact.name }}</h4>
            <pre class="json-block result-json">{{ typeof artifactPreview.preview === 'string' ? artifactPreview.preview : compactJson(artifactPreview.preview) }}</pre>
          </div>
        </template>
      </div>
    </el-drawer>
  </div>
</template>

<style scoped>
.task-center {
  display: flex;
  flex-direction: column;
  gap: 16px;
}

.task-header,
.header-actions,
.filter-bar,
.summary-row {
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

.summary-label {
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
  width: 240px;
}

.molecule-cell {
  display: flex;
  flex-direction: column;
  gap: 2px;
  min-width: 0;
}

.molecule-cell span {
  color: var(--app-ink-muted);
  font-family: var(--app-mono-font);
  font-size: 12px;
  overflow: hidden;
  text-overflow: ellipsis;
}

.integration-grid {
  display: grid;
  grid-template-columns: repeat(3, minmax(0, 1fr));
  gap: 10px;
}

.integration-item {
  display: flex;
  align-items: center;
  justify-content: space-between;
  min-height: 40px;
  padding: 0 12px;
  border: 1px solid var(--app-border-soft);
  border-radius: var(--app-radius-sm);
  background: #ffffff;
  font-weight: 600;
}

.detail-body {
  min-height: 420px;
}

.detail-heading {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 16px;
  margin-bottom: 16px;
}

.detail-heading h3 {
  margin: 0;
  color: var(--app-ink);
  font-size: 18px;
}

.detail-heading p {
  margin: 6px 0 0;
  color: var(--app-ink-muted);
  font-size: 13px;
}

.detail-section-title {
  margin: 18px 0 10px;
  color: var(--app-sidebar-from);
  font-size: 14px;
}

.timeline-step {
  display: flex;
  align-items: center;
  gap: 8px;
}

.error-text {
  color: #b42318;
}

.result-json {
  max-height: 260px;
}

.artifact-preview {
  margin-top: 12px;
}

@media (max-width: 1000px) {
  .summary-row,
  .integration-grid {
    grid-template-columns: repeat(2, minmax(0, 1fr));
  }
}

@media (max-width: 640px) {
  .summary-row,
  .integration-grid {
    grid-template-columns: 1fr;
  }

  .keyword-input {
    width: 100%;
  }
}
</style>
