<script setup>
import { computed, onBeforeUnmount, onMounted, reactive, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { ElMessage, ElMessageBox } from 'element-plus'
import { Download, Histogram, Refresh, Search, VideoPause, View } from '@element-plus/icons-vue'

import {
  cancelComputation,
  createObservationFromComputation,
  downloadArtifact,
  getApiErrorMessage,
  getComputation,
  getArtifactSpectrum,
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
const artifactSpectrum = ref(null)
const integrations = ref([])
const integrationLoading = ref(false)
const pollTimer = ref(null)
const observationSubmitting = ref(false)
const downloadingArtifactId = ref('')
const spectrumLoadingArtifactId = ref('')

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
  { label: 'LOCAL_STRUCTURE', value: 'LOCAL_STRUCTURE' },
  { label: 'LOCAL_XTB', value: 'LOCAL_XTB' },
  { label: 'ORCA 精加工', value: 'ORCA_COMPUTE_ENGINE_LASER' },
]

const engineOptions = [
  { label: '全部', value: '' },
  { label: 'LOCAL', value: 'LOCAL' },
  { label: 'RDKit', value: 'RDKit' },
  { label: 'OPENBABEL', value: 'OPENBABEL' },
  { label: 'XTB', value: 'XTB' },
  { label: 'ORCA', value: 'ORCA' },
]

const statusSummary = computed(() => {
  const counts = { queued: 0, running: 0, completed: 0, failed: 0, cancelled: 0 }
  for (const item of tasks.value) {
    if (counts[item.status] !== undefined) counts[item.status] += 1
  }
  return counts
})

const hasActiveRuns = computed(() => tasks.value.some((item) => ['queued', 'running'].includes(item.status)))
const selectedSpectrumPoints = computed(() => {
  const payload = artifactSpectrum.value?.spectrum
  const points = payload?.spectrum?.points || payload?.points || []
  return points
    .map((point) => ({ x: Number(point.x), y: Number(point.y) }))
    .filter((point) => Number.isFinite(point.x) && Number.isFinite(point.y))
})

const selectedSpectrumPolyline = computed(() => {
  const points = selectedSpectrumPoints.value
  if (!points.length) return ''
  const minX = Math.min(...points.map((point) => point.x))
  const maxX = Math.max(...points.map((point) => point.x))
  const minY = Math.min(...points.map((point) => point.y))
  const maxY = Math.max(...points.map((point) => point.y))
  const xRange = maxX - minX || 1
  const yRange = maxY - minY || 1
  return points
    .map((point) => {
      const x = 44 + ((point.x - minX) / xRange) * 432
      const y = 188 - ((point.y - minY) / yRange) * 152
      return `${x.toFixed(2)},${y.toFixed(2)}`
    })
    .join(' ')
})

const selectedSpectrumSummary = computed(() => {
  const payload = artifactSpectrum.value?.spectrum
  return payload?.summary || payload?.spectra || {}
})

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

function shortChecksum(value) {
  if (!value) return '-'
  return String(value).slice(0, 12)
}

function artifactSourceStep(row) {
  return row.metadata?.source_step || row.step_key || '-'
}

function artifactParserLabel(row) {
  if (!row.parser_name) return '-'
  return row.parser_version ? `${row.parser_name}@${row.parser_version}` : row.parser_name
}

function canRenderSpectrum(row) {
  return ['spectrum_json', 'result_json'].includes(row.artifact_type)
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
  artifactSpectrum.value = null
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

async function handleViewSpectrum(row) {
  spectrumLoadingArtifactId.value = row.artifact_id
  try {
    artifactSpectrum.value = await getArtifactSpectrum(row.artifact_id)
  } catch (error) {
    ElMessage.error(getApiErrorMessage(error))
  } finally {
    spectrumLoadingArtifactId.value = ''
  }
}

async function handleDownloadArtifact(row) {
  downloadingArtifactId.value = row.artifact_id
  try {
    const data = await downloadArtifact(row.artifact_id)
    const blob = data.blob instanceof Blob ? data.blob : new Blob([data.blob], { type: data.contentType })
    const url = window.URL.createObjectURL(blob)
    const link = document.createElement('a')
    link.href = url
    link.download = data.filename || row.name || `${row.artifact_id}.dat`
    document.body.appendChild(link)
    link.click()
    link.remove()
    window.URL.revokeObjectURL(url)
  } catch (error) {
    ElMessage.error(`下载失败：${getApiErrorMessage(error)}`)
  } finally {
    downloadingArtifactId.value = ''
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

async function handleCreateObservationFromRun() {
  if (!selectedRun.value?.run_id) return
  observationSubmitting.value = true
  try {
    await createObservationFromComputation(selectedRun.value.run_id)
    ElMessage.success('Observation 已生成')
    await loadDetail(selectedRun.value.run_id)
  } catch (error) {
    ElMessage.error(getApiErrorMessage(error))
  } finally {
    observationSubmitting.value = false
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
    artifactSpectrum.value = null
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
          <el-button :icon="Histogram" @click="$router.push({ path: '/tasks/center', query: { module_id: 'computation' } })">全局任务中心</el-button>
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
            <el-option v-for="item in engineOptions" :key="item.value" :label="item.label" :value="item.value" />
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
          <el-tag size="small" :type="['up', 'available', 'built_in'].includes(item.status) ? 'success' : 'info'">{{ item.status }}</el-tag>
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
          <div v-if="selectedRun.status === 'completed' && selectedRun.campaign_id && selectedRun.suggestion_id" class="detail-actions">
            <el-button type="primary" :loading="observationSubmitting" @click="handleCreateObservationFromRun">从计算结果生成 observation</el-button>
            <el-button @click="$router.push(`/optimization/campaigns/${selectedRun.campaign_id}`)">查看 Campaign</el-button>
          </div>

          <el-descriptions :column="2" border size="small">
            <el-descriptions-item label="SMILES">{{ selectedRun.molecule?.smiles }}</el-descriptions-item>
            <el-descriptions-item label="Created">{{ formatDate(selectedRun.created_at) }}</el-descriptions-item>
            <el-descriptions-item label="Started">{{ formatDate(selectedRun.started_at) }}</el-descriptions-item>
            <el-descriptions-item label="Finished">{{ formatDate(selectedRun.finished_at) }}</el-descriptions-item>
            <el-descriptions-item label="Campaign">{{ selectedRun.campaign_id || '-' }}</el-descriptions-item>
            <el-descriptions-item label="Suggestion">{{ selectedRun.suggestion_id || '-' }}</el-descriptions-item>
          </el-descriptions>

          <el-alert
            v-if="selectedRun.error"
            class="run-error-alert"
            type="error"
            :closable="false"
            :title="selectedRun.error.error_code || 'WORKFLOW_ERROR'"
            :description="selectedRun.error.message"
            show-icon
          />

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
            <el-table-column label="Checksum" min-width="120">
              <template #default="{ row }"><span class="mono-text">{{ shortChecksum(row.checksum_sha256) }}</span></template>
            </el-table-column>
            <el-table-column label="Parser" min-width="130">
              <template #default="{ row }">{{ artifactParserLabel(row) }}</template>
            </el-table-column>
            <el-table-column label="Source step" min-width="150">
              <template #default="{ row }">{{ artifactSourceStep(row) }}</template>
            </el-table-column>
            <el-table-column prop="size_bytes" label="大小" width="100" />
            <el-table-column label="操作" width="220">
              <template #default="{ row }">
                <el-button
                  v-if="canRenderSpectrum(row)"
                  text
                  type="primary"
                  size="small"
                  :loading="spectrumLoadingArtifactId === row.artifact_id"
                  @click="handleViewSpectrum(row)"
                >
                  图谱
                </el-button>
                <el-button text type="primary" size="small" @click="handlePreviewArtifact(row.artifact_id)">预览</el-button>
                <el-button text type="primary" size="small" :icon="Download" :loading="downloadingArtifactId === row.artifact_id" @click="handleDownloadArtifact(row)">下载</el-button>
              </template>
            </el-table-column>
          </el-table>

          <div v-if="artifactSpectrum" class="spectrum-preview">
            <div class="spectrum-header">
              <div>
                <h4 class="detail-section-title">Spectrum · {{ artifactSpectrum.artifact.name }}</h4>
                <p class="spectrum-meta">
                  {{ artifactSpectrum.spectrum.schema_version || 'spectrum' }}
                  · {{ artifactSpectrum.artifact.parser_name || '-' }}@{{ artifactSpectrum.artifact.parser_version || '-' }}
                </p>
              </div>
              <div class="spectrum-summary">
                <span v-if="selectedSpectrumSummary.absorption_peak_nm">Peak {{ selectedSpectrumSummary.absorption_peak_nm }} nm</span>
                <span>{{ selectedSpectrumPoints.length }} points</span>
              </div>
            </div>
            <svg class="spectrum-chart" viewBox="0 0 520 220" role="img" aria-label="Spectrum preview">
              <line x1="44" y1="188" x2="486" y2="188" class="chart-axis" />
              <line x1="44" y1="28" x2="44" y2="188" class="chart-axis" />
              <polyline v-if="selectedSpectrumPolyline" :points="selectedSpectrumPolyline" class="chart-line" />
            </svg>
          </div>

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

.detail-actions {
  display: flex;
  gap: 10px;
  margin-bottom: 14px;
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

.run-error-alert {
  margin-top: 14px;
}

.timeline-step {
  display: flex;
  align-items: center;
  gap: 8px;
}

.error-text {
  color: #b42318;
}

.mono-text {
  font-family: var(--app-mono-font);
  font-size: 12px;
}

.result-json {
  max-height: 260px;
}

.artifact-preview {
  margin-top: 12px;
}

.spectrum-preview {
  margin-top: 14px;
  padding: 12px;
  border: 1px solid var(--app-border-soft);
  border-radius: var(--app-radius-sm);
  background: #ffffff;
}

.spectrum-header {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 12px;
}

.spectrum-header .detail-section-title {
  margin-top: 0;
}

.spectrum-meta,
.spectrum-summary {
  color: var(--app-ink-muted);
  font-size: 12px;
}

.spectrum-summary {
  display: flex;
  flex-direction: column;
  align-items: flex-end;
  gap: 4px;
  white-space: nowrap;
}

.spectrum-chart {
  width: 100%;
  height: 220px;
  margin-top: 8px;
}

.chart-axis {
  stroke: #c9d6e6;
  stroke-width: 1;
}

.chart-line {
  fill: none;
  stroke: var(--app-primary);
  stroke-width: 2.5;
  stroke-linecap: round;
  stroke-linejoin: round;
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
