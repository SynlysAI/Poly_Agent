<script setup>
import { computed, onMounted, reactive, ref, watch } from 'vue'
import { ElMessage } from 'element-plus'
import { Refresh, View } from '@element-plus/icons-vue'

import { getApiErrorMessage, listAlgorithmRuns } from '../../api/polyAgentApi'
import { apiDateTimeMs, formatApiDateTime } from '../../utils/datetime'
import AlgorithmResultView from './AlgorithmResultView.vue'

const props = defineProps({
  refreshKey: { type: Number, default: 0 },
  algorithmId: { type: String, default: '' },
})

const loading = ref(false)
const runs = ref([])
const detail = ref(null)
const detailVisible = ref(false)
const filters = reactive({ algorithm_id: '', version_id: '', status: '', date_range: null })
const lockedAlgorithmId = computed(() => String(props.algorithmId || '').trim())

const filteredRuns = computed(() => runs.value.filter((run) => {
  if (filters.version_id && !String(run.algorithm_version_id || '').includes(filters.version_id.trim())) return false
  if (filters.date_range?.length === 2) {
    const created = apiDateTimeMs(run.created_at)
    const endExclusive = new Date(filters.date_range[1])
    endExclusive.setDate(endExclusive.getDate() + 1)
    if (Number.isNaN(created) || created < filters.date_range[0].getTime() || created >= endExclusive.getTime()) return false
  }
  return true
}))

watch(() => props.refreshKey, loadRuns)
watch(lockedAlgorithmId, (value) => {
  filters.algorithm_id = value
  loadRuns()
})

async function loadRuns() {
  loading.value = true
  try {
    const params = { page: 1, page_size: 100 }
    const algorithmId = lockedAlgorithmId.value || filters.algorithm_id.trim()
    if (algorithmId) params.algorithm_id = algorithmId
    if (filters.status) params.status = filters.status
    const data = await listAlgorithmRuns(params)
    runs.value = (data.items || []).filter((item) => item.algorithm_version_id)
  } catch (error) {
    ElMessage.error(getApiErrorMessage(error))
  } finally {
    loading.value = false
  }
}

function resetFilters() {
  filters.algorithm_id = lockedAlgorithmId.value
  filters.version_id = ''
  filters.status = ''
  filters.date_range = null
  loadRuns()
}

function openDetail(run) {
  detail.value = run
  detailVisible.value = true
}

function formatDate(value) {
  return formatApiDateTime(value)
}

function duration(run) {
  if (!run.started_at || !run.finished_at) return '-'
  const started = apiDateTimeMs(run.started_at)
  const finished = apiDateTimeMs(run.finished_at)
  if (Number.isNaN(started) || Number.isNaN(finished)) return '-'
  return `${Math.max(0, finished - started)} ms`
}

function shortDigest(value) {
  if (!value) return '-'
  return value.length > 34 ? `${value.slice(0, 30)}...` : value
}

function runtimeBackend(run) {
  return run.runtime_snapshot?.backend || run.runtime_snapshot?.deployment?.backend || '-'
}

onMounted(() => {
  filters.algorithm_id = lockedAlgorithmId.value
  loadRuns()
})
</script>

<template>
  <div class="history-panel">
    <div class="history-toolbar">
      <el-input v-model="filters.algorithm_id" :clearable="!lockedAlgorithmId" :disabled="Boolean(lockedAlgorithmId)" placeholder="算法 ID" style="width: 220px" @keyup.enter="loadRuns" />
      <el-input v-model="filters.version_id" clearable placeholder="版本 ID 包含" style="width: 220px" />
      <el-select v-model="filters.status" clearable placeholder="运行状态" style="width: 140px">
        <el-option label="已完成" value="completed" /><el-option label="失败" value="failed" /><el-option label="运行中" value="running" />
      </el-select>
      <el-date-picker v-model="filters.date_range" type="daterange" range-separator="至" start-placeholder="开始日期" end-placeholder="结束日期" />
      <el-button type="primary" @click="loadRuns">筛选</el-button>
      <el-button @click="resetFilters">重置</el-button>
      <el-button :icon="Refresh" :loading="loading" aria-label="刷新运行记录" @click="loadRuns" />
    </div>

    <el-table v-loading="loading" :data="filteredRuns" border empty-text="暂无上传算法运行记录">
      <el-table-column prop="run_id" label="Run ID" min-width="190" />
      <el-table-column prop="algorithm_id" label="算法" min-width="180" />
      <el-table-column label="版本" min-width="210"><template #default="{ row }"><code>{{ row.algorithm_version_id }}</code></template></el-table-column>
      <el-table-column prop="status" label="状态" width="90"><template #default="{ row }"><el-tag :type="row.status === 'completed' ? 'success' : row.status === 'failed' ? 'danger' : 'warning'">{{ row.status }}</el-tag></template></el-table-column>
      <el-table-column label="耗时" width="100"><template #default="{ row }">{{ duration(row) }}</template></el-table-column>
      <el-table-column label="创建时间" width="170"><template #default="{ row }">{{ formatDate(row.created_at) }}</template></el-table-column>
      <el-table-column width="72" fixed="right"><template #default="{ row }"><el-button text :icon="View" aria-label="查看运行详情" @click="openDetail(row)" /></template></el-table-column>
    </el-table>

    <el-drawer v-model="detailVisible" title="预测运行详情" size="min(680px, 94vw)">
      <template v-if="detail">
        <el-descriptions :column="1" border size="small">
          <el-descriptions-item label="Run ID">{{ detail.run_id }}</el-descriptions-item>
          <el-descriptions-item label="算法 / 版本">{{ detail.algorithm_id }} / {{ detail.algorithm_version_id }}</el-descriptions-item>
          <el-descriptions-item label="Package SHA">{{ detail.package_sha256 || '-' }}</el-descriptions-item>
          <el-descriptions-item label="Runtime">{{ runtimeBackend(detail) }}</el-descriptions-item>
          <el-descriptions-item label="Runtime Digest">{{ shortDigest(detail.runtime_digest || detail.image_digest) }}</el-descriptions-item>
          <el-descriptions-item label="Environment Digest">{{ shortDigest(detail.environment_digest) }}</el-descriptions-item>
          <el-descriptions-item label="状态 / 耗时">{{ detail.status }} / {{ duration(detail) }}</el-descriptions-item>
          <el-descriptions-item v-if="detail.runtime_snapshot?.logs?.stderr" label="Runtime stderr">
            <pre class="runtime-log">{{ detail.runtime_snapshot.logs.stderr }}</pre>
          </el-descriptions-item>
        </el-descriptions>
        <AlgorithmResultView
          class="detail-result-view"
          :output-summary="detail.output_summary"
          :input-snapshot="detail.input_snapshot"
          :artifact-refs="detail.artifact_refs"
          :status="detail.status"
          :error="detail.error"
        />
      </template>
    </el-drawer>
  </div>
</template>

<style scoped>
.history-panel { display: grid; gap: 14px; }
.history-toolbar { display: flex; gap: 8px; flex-wrap: wrap; align-items: center; }
code { font-family: var(--app-mono-font); font-size: 12px; }
.runtime-log { margin: 0; white-space: pre-wrap; word-break: break-word; font-family: var(--app-mono-font); font-size: 12px; }
.detail-result-view { margin-top: 16px; }
@media (max-width: 720px) { .history-toolbar { align-items: stretch; flex-direction: column; } .history-toolbar > * { width: 100% !important; } }
</style>
