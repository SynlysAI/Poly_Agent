<script setup>
import { computed, onMounted, ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { ElMessage } from 'element-plus'
import { Connection, MagicStick, Refresh, Upload } from '@element-plus/icons-vue'

import {
  createObservationFromComputation,
  generateSuggestion,
  getApiErrorMessage,
  getCampaign,
  getCampaignHistory,
  importChemosDemoCandidates,
  submitSuggestionComputation,
} from '../api/polyAgentApi'

const route = useRoute()
const router = useRouter()
const loading = ref(false)
const actionLoading = ref('')
const detail = ref(null)
const history = ref([])

const campaignId = computed(() => String(route.params.campaignId || ''))
const campaign = computed(() => detail.value?.campaign || null)
const candidates = computed(() => detail.value?.candidates || [])
const suggestions = computed(() => detail.value?.suggestions || [])
const observations = computed(() => detail.value?.observations || [])

function formatDate(value) {
  if (!value) return '-'
  const date = new Date(value)
  if (Number.isNaN(date.getTime())) return value
  return date.toLocaleString()
}

function statusTag(status) {
  const map = { draft: 'info', running: 'warning', paused: 'info', completed: 'success', failed: 'danger', archived: 'info', suggested: 'info', submitted: 'warning', evaluated: 'success', rejected: 'danger' }
  return map[status] || 'info'
}

function compactJson(value) {
  if (!value || Object.keys(value).length === 0) return '{}'
  return JSON.stringify(value, null, 2)
}

async function loadDetail() {
  loading.value = true
  try {
    const [detailData, historyData] = await Promise.all([
      getCampaign(campaignId.value),
      getCampaignHistory(campaignId.value),
    ])
    detail.value = detailData
    history.value = historyData.items || []
  } catch (error) {
    ElMessage.error(getApiErrorMessage(error))
  } finally {
    loading.value = false
  }
}

async function handleImportChemos() {
  actionLoading.value = 'import'
  try {
    const data = await importChemosDemoCandidates(campaignId.value)
    ElMessage.success(`已导入 ${data.imported_count} 个候选`)
    await loadDetail()
  } catch (error) {
    ElMessage.error(getApiErrorMessage(error))
  } finally {
    actionLoading.value = ''
  }
}

async function handleGenerateSuggestion() {
  actionLoading.value = 'suggest'
  try {
    const data = await generateSuggestion(campaignId.value, { batch_size: 1 })
    ElMessage.success(`已生成 ${data.items?.length || 0} 个 suggestion`)
    await loadDetail()
  } catch (error) {
    ElMessage.error(getApiErrorMessage(error))
  } finally {
    actionLoading.value = ''
  }
}

async function handleSubmitSuggestion(suggestion) {
  actionLoading.value = suggestion.suggestion_id
  try {
    const data = await submitSuggestionComputation(suggestion.suggestion_id)
    ElMessage.success(`计算任务已提交：${data.run_id}`)
    await loadDetail()
  } catch (error) {
    ElMessage.error(getApiErrorMessage(error))
  } finally {
    actionLoading.value = ''
  }
}

async function handleCreateObservation(suggestion) {
  if (!suggestion.submitted_run_id) return
  actionLoading.value = `obs-${suggestion.suggestion_id}`
  try {
    await createObservationFromComputation(suggestion.submitted_run_id)
    ElMessage.success('Observation 已生成')
    await loadDetail()
  } catch (error) {
    ElMessage.error(getApiErrorMessage(error))
  } finally {
    actionLoading.value = ''
  }
}

onMounted(loadDetail)
</script>

<template>
  <div class="campaign-detail" v-loading="loading">
    <section class="panel">
      <div class="panel-header detail-header">
        <div>
          <h3 class="panel-title">{{ campaign?.name || 'Campaign Detail' }}</h3>
          <p class="panel-subtitle">{{ campaignId }}</p>
        </div>
        <div class="header-actions">
          <el-button :icon="Refresh" :loading="loading" @click="loadDetail">刷新</el-button>
          <el-button :icon="Upload" :loading="actionLoading === 'import'" @click="handleImportChemos">导入 ChemOS</el-button>
          <el-button type="primary" :icon="MagicStick" :loading="actionLoading === 'suggest'" @click="handleGenerateSuggestion">生成推荐</el-button>
        </div>
      </div>
      <div class="panel-body" v-if="campaign">
        <el-descriptions :column="3" border size="small">
          <el-descriptions-item label="状态"><el-tag size="small" :type="statusTag(campaign.status)">{{ campaign.status }}</el-tag></el-descriptions-item>
          <el-descriptions-item label="Planner">{{ campaign.planner_type }}</el-descriptions-item>
          <el-descriptions-item label="候选数">{{ campaign.search_space?.candidate_count || 0 }}</el-descriptions-item>
          <el-descriptions-item label="目标">{{ campaign.objectives?.map((item) => item.name).join(', ') }}</el-descriptions-item>
          <el-descriptions-item label="创建">{{ formatDate(campaign.created_at) }}</el-descriptions-item>
          <el-descriptions-item label="更新">{{ formatDate(campaign.updated_at) }}</el-descriptions-item>
        </el-descriptions>
      </div>
    </section>

    <section class="panel">
      <div class="panel-header">
        <h3 class="panel-title">Suggestions</h3>
      </div>
      <div class="panel-body">
        <el-table :data="suggestions" border size="small">
          <el-table-column prop="iteration_index" label="#" width="70" />
          <el-table-column prop="candidate_key" label="Candidate" min-width="150" />
          <el-table-column prop="smiles" label="SMILES" min-width="220" />
          <el-table-column prop="status" label="状态" width="110">
            <template #default="{ row }"><el-tag size="small" :type="statusTag(row.status)">{{ row.status }}</el-tag></template>
          </el-table-column>
          <el-table-column prop="submitted_run_id" label="Run" min-width="210" />
          <el-table-column label="操作" min-width="260">
            <template #default="{ row }">
              <el-button v-if="!row.submitted_run_id" text type="primary" size="small" :icon="Connection" :loading="actionLoading === row.suggestion_id" @click="handleSubmitSuggestion(row)">提交计算</el-button>
              <el-button v-else text type="primary" size="small" @click="router.push({ path: '/computations/runs', query: { run_id: row.submitted_run_id } })">查看计算</el-button>
              <el-button v-if="row.submitted_run_id && row.status !== 'evaluated'" text type="primary" size="small" :loading="actionLoading === `obs-${row.suggestion_id}`" @click="handleCreateObservation(row)">生成 observation</el-button>
            </template>
          </el-table-column>
        </el-table>
      </div>
    </section>

    <div class="detail-grid">
      <section class="panel">
        <div class="panel-header">
          <h3 class="panel-title">Candidates</h3>
        </div>
        <div class="panel-body">
          <el-table :data="candidates" border size="small" height="320">
            <el-table-column prop="candidate_key" label="Key" min-width="140" />
            <el-table-column prop="smiles" label="SMILES" min-width="220" />
            <el-table-column label="Descriptor" min-width="150">
              <template #default="{ row }">{{ row.descriptors?.status || '-' }}</template>
            </el-table-column>
          </el-table>
        </div>
      </section>

      <section class="panel">
        <div class="panel-header">
          <h3 class="panel-title">Observations</h3>
        </div>
        <div class="panel-body">
          <el-table :data="observations" border size="small" height="320">
            <el-table-column prop="candidate_id" label="Candidate ID" min-width="170" />
            <el-table-column prop="source_run_id" label="Run" min-width="170" />
            <el-table-column label="Values" min-width="180">
              <template #default="{ row }"><pre class="inline-json">{{ compactJson(row.values) }}</pre></template>
            </el-table-column>
          </el-table>
        </div>
      </section>
    </div>

    <section class="panel">
      <div class="panel-header">
        <h3 class="panel-title">History</h3>
      </div>
      <div class="panel-body">
        <el-timeline>
          <el-timeline-item v-for="item in history" :key="`${item.event_type}-${item.occurred_at}-${item.suggestion_id || item.candidate_id}`" :timestamp="formatDate(item.occurred_at)">
            <div class="history-line">
              <strong>{{ item.event_type }}</strong>
              <span>{{ item.summary?.candidate_key || item.candidate_id || '-' }}</span>
              <el-button v-if="item.source_run_id" text size="small" @click="router.push({ path: '/computations/runs', query: { run_id: item.source_run_id } })">{{ item.source_run_id }}</el-button>
            </div>
          </el-timeline-item>
        </el-timeline>
      </div>
    </section>
  </div>
</template>

<style scoped>
.campaign-detail {
  display: flex;
  flex-direction: column;
  gap: 16px;
}

.detail-header,
.header-actions {
  display: flex;
  align-items: center;
}

.detail-header {
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

.detail-grid {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 16px;
}

.inline-json {
  margin: 0;
  font-family: var(--app-mono-font);
  font-size: 12px;
  white-space: pre-wrap;
}

.history-line {
  display: flex;
  align-items: center;
  gap: 10px;
}
</style>
