<script setup>
import { computed, onMounted, ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { ElMessage, ElMessageBox } from 'element-plus'
import { CircleClose, CloseBold, Connection, MagicStick, Refresh, Star, SwitchButton, Upload, VideoPause } from '@element-plus/icons-vue'

import {
  archiveCampaign,
  completeCampaign,
  createObservationFromComputation,
  failCampaign,
  generateSuggestion,
  getApiErrorMessage,
  getCampaign,
  getCampaignHistory,
  importCampaignCandidatesCsv,
  pauseCampaign,
  rejectSuggestion,
  resumeCampaign,
  submitSuggestionComputation,
} from '../api/polyAgentApi'

const route = useRoute()
const router = useRouter()
const loading = ref(false)
const actionLoading = ref('')
const detail = ref(null)
const history = ref([])
const csvDialogVisible = ref(false)
const csvText = ref('candidate_key,smiles\nCAND-001,CCO\n')
const lastImportReport = ref(null)

const campaignId = computed(() => String(route.params.campaignId || ''))
const campaign = computed(() => detail.value?.campaign || null)
const candidates = computed(() => detail.value?.candidates || [])
const suggestions = computed(() => detail.value?.suggestions || [])
const observations = computed(() => detail.value?.observations || [])
const canImport = computed(() => ['draft', 'running'].includes(campaign.value?.status))
const canGenerate = computed(() => campaign.value?.status === 'running')
const canSubmitSuggestion = computed(() => campaign.value?.status === 'running')

const computationPresetOptions = [
  { value: 'local_xtb', label: 'xTB / CREST 粗优化' },
  { value: 'orca', label: 'ORCA 精加工' },
]
const computationPreset = computed(() => {
  const raw = campaign.value?.planner_config?.computation_preset || 'local_xtb'
  return typeof raw === 'string' ? raw : raw?.preset_key
})
const computationPresetLabel = computed(() => (
  computationPresetOptions.find((item) => item.value === computationPreset.value)?.label || computationPreset.value || 'xTB / CREST 粗优化'
))

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

const statusActionOptions = computed(() => {
  const status = campaign.value?.status
  if (status === 'running') {
    return [
      { label: 'Pause', action: 'pause', icon: VideoPause },
      { label: 'Complete', action: 'complete', icon: SwitchButton },
      { label: 'Fail', action: 'fail', icon: CloseBold },
      { label: 'Archive', action: 'archive', icon: CloseBold },
    ]
  }
  if (status === 'paused') {
    return [
      { label: 'Resume', action: 'resume', icon: SwitchButton },
      { label: 'Complete', action: 'complete', icon: SwitchButton },
      { label: 'Fail', action: 'fail', icon: CloseBold },
      { label: 'Archive', action: 'archive', icon: CloseBold },
    ]
  }
  if (status === 'draft') {
    return [
      { label: 'Archive', action: 'archive', icon: CloseBold },
      { label: 'Fail', action: 'fail', icon: CloseBold },
    ]
  }
  if (['completed', 'failed'].includes(status)) {
    return [{ label: 'Archive', action: 'archive', icon: CloseBold }]
  }
  return []
})

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

async function handleStatusAction(action) {
  const actionMap = {
    pause: pauseCampaign,
    resume: resumeCampaign,
    archive: archiveCampaign,
    complete: completeCampaign,
    fail: failCampaign,
  }
  try {
    const { value } = await ElMessageBox.prompt('请输入状态变更原因', `Campaign ${action}`, {
      confirmButtonText: action,
      cancelButtonText: '取消',
      inputType: 'textarea',
    })
    actionLoading.value = `campaign-${action}`
    await actionMap[action](campaignId.value, { reason: value?.trim() || null })
    ElMessage.success(`Campaign 已${action}`)
    await loadDetail()
  } catch (error) {
    if (error === 'cancel' || error === 'close') return
    ElMessage.error(getApiErrorMessage(error))
  } finally {
    actionLoading.value = ''
  }
}

async function handleImportCsv() {
  actionLoading.value = 'import-csv'
  try {
    const data = await importCampaignCandidatesCsv(campaignId.value, csvText.value)
    lastImportReport.value = data
    csvDialogVisible.value = false
    ElMessage.success(`导入 ${data.imported_count} 个，更新 ${data.updated_count || 0} 个`)
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

async function handleRejectSuggestion(suggestion) {
  try {
    const { value } = await ElMessageBox.prompt('请输入拒绝原因', 'Reject suggestion', {
      confirmButtonText: 'Reject',
      cancelButtonText: '取消',
      inputType: 'textarea',
      inputValidator: (value) => Boolean(value?.trim()) || '原因不能为空',
    })
    actionLoading.value = `reject-${suggestion.suggestion_id}`
    await rejectSuggestion(suggestion.suggestion_id, { reason: value.trim() })
    ElMessage.success('Suggestion 已拒绝')
    await loadDetail()
  } catch (error) {
    if (error === 'cancel' || error === 'close') return
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

function suggestionReason(suggestion) {
  return suggestion.planner_payload?.rejection?.reason || suggestion.planner_payload?.failure?.reason || '-'
}

onMounted(loadDetail)
</script>

<template>
  <div class="campaign-detail" v-loading="loading">
    <section class="panel">
      <div class="panel-header detail-header">
        <div>
          <h3 class="panel-title">{{ campaign?.name || 'Campaign 详情' }}</h3>
          <p class="panel-subtitle">{{ campaignId }}</p>
        </div>
        <div class="header-actions">
          <el-button :icon="Refresh" :loading="loading" @click="loadDetail">刷新</el-button>
          <el-button :icon="Upload" :disabled="!canImport" :loading="actionLoading === 'import-csv'" @click="csvDialogVisible = true">导入 CSV</el-button>
          <el-button type="primary" :icon="MagicStick" :disabled="!canGenerate" :loading="actionLoading === 'suggest'" @click="handleGenerateSuggestion">生成推荐</el-button>
          <el-dropdown v-if="statusActionOptions.length" trigger="click">
            <el-button>状态</el-button>
            <template #dropdown>
              <el-dropdown-menu>
                <el-dropdown-item
                  v-for="item in statusActionOptions"
                  :key="item.action"
                  :icon="item.icon"
                  :disabled="actionLoading === `campaign-${item.action}`"
                  @click="handleStatusAction(item.action)"
                >
                  {{ item.label }}
                </el-dropdown-item>
              </el-dropdown-menu>
            </template>
          </el-dropdown>
        </div>
      </div>
      <div class="panel-body" v-if="campaign">
        <el-descriptions :column="3" border size="small">
          <el-descriptions-item label="状态"><el-tag size="small" :type="statusTag(campaign.status)">{{ campaign.status }}</el-tag></el-descriptions-item>
          <el-descriptions-item label="Planner">{{ campaign.planner_type }}</el-descriptions-item>
          <el-descriptions-item label="Preset">{{ computationPresetLabel }}</el-descriptions-item>
          <el-descriptions-item label="候选数">{{ campaign.search_space?.candidate_count || 0 }}</el-descriptions-item>
          <el-descriptions-item label="目标">{{ campaign.objectives?.map((item) => item.name).join(', ') }}</el-descriptions-item>
          <el-descriptions-item label="创建">{{ formatDate(campaign.created_at) }}</el-descriptions-item>
          <el-descriptions-item label="更新">{{ formatDate(campaign.updated_at) }}</el-descriptions-item>
        </el-descriptions>
      </div>
    </section>

    <section v-if="lastImportReport" class="panel">
      <div class="panel-header">
        <h3 class="panel-title">最近导入报告</h3>
      </div>
      <div class="panel-body import-report">
        <el-statistic title="新增" :value="lastImportReport.imported_count || 0" />
        <el-statistic title="更新" :value="lastImportReport.updated_count || 0" />
        <el-statistic title="失败行" :value="lastImportReport.failed_rows?.length || 0" />
        <el-statistic title="重复行" :value="lastImportReport.duplicate_rows?.length || 0" />
        <el-table v-if="lastImportReport.failed_rows?.length || lastImportReport.duplicate_rows?.length" :data="[...(lastImportReport.failed_rows || []), ...(lastImportReport.duplicate_rows || [])]" border size="small" class="report-table">
          <el-table-column prop="row_number" label="行号" width="80" />
          <el-table-column prop="candidate_key" label="Candidate" min-width="140" />
          <el-table-column prop="smiles" label="SMILES" min-width="180" />
          <el-table-column prop="reason" label="原因" min-width="220" />
        </el-table>
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
          <el-table-column label="Reason" min-width="180">
            <template #default="{ row }">{{ suggestionReason(row) }}</template>
          </el-table-column>
          <el-table-column label="操作" min-width="260">
            <template #default="{ row }">
              <el-button v-if="row.status === 'suggested' && !row.submitted_run_id" text type="primary" size="small" :icon="Connection" :disabled="!canSubmitSuggestion" :loading="actionLoading === row.suggestion_id" @click="handleSubmitSuggestion(row)">提交 {{ computationPresetLabel }}</el-button>
              <el-button v-if="row.submitted_run_id" text type="primary" size="small" @click="router.push({ path: '/computations/runs', query: { run_id: row.submitted_run_id } })">查看计算</el-button>
              <el-button v-if="['suggested', 'submitted'].includes(row.status)" text type="danger" size="small" :icon="CircleClose" :loading="actionLoading === `reject-${row.suggestion_id}`" @click="handleRejectSuggestion(row)">Reject</el-button>
              <el-button v-if="row.submitted_run_id && row.status === 'submitted'" text type="primary" size="small" :loading="actionLoading === `obs-${row.suggestion_id}`" @click="handleCreateObservation(row)">生成 observation</el-button>
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

    <!-- ResearchEngine 入口 -->
    <section class="panel">
      <div class="panel-header">
        <h3 class="panel-title">ResearchEngine 研发引擎</h3>
      </div>
      <div class="panel-body">
        <div class="re-entry-grid">
          <div class="re-entry-card">
            <div class="re-entry-top">
              <el-icon :size="20"><Star /></el-icon>
              <span>研发任务定义</span>
            </div>
            <p>为此 Campaign 创建或关联 ProblemSpec，定义材料体系、变量、目标与约束。</p>
            <el-button type="primary" size="small" @click="router.push({ path: '/research-engine', query: { problem_spec_id: campaignId } })">进入 ProblemSpec</el-button>
          </div>
          <div class="re-entry-card">
            <div class="re-entry-top">
              <el-icon :size="20"><MagicStick /></el-icon>
              <span>人工算法工具</span>
            </div>
            <p>浏览算法能力清单，手动触发文献检索、结构表示、性质预测和计算任务。</p>
            <el-button type="primary" size="small" @click="router.push('/research-engine')">进入算法工作台</el-button>
          </div>
          <div class="re-entry-card">
            <div class="re-entry-top">
              <el-icon :size="20"><Connection /></el-icon>
              <span>AutoResearch 编排</span>
            </div>
            <p>基于 ProblemSpec 启动自动研发流程，审批阶段门禁，查看推进进度。</p>
            <el-button type="primary" size="small" @click="router.push({ path: '/research-engine', query: { campaign_id: campaignId } })">进入 AutoResearch</el-button>
          </div>
        </div>
      </div>
    </section>

    <el-dialog v-model="csvDialogVisible" title="导入 CSV 候选" width="620px">
      <el-input
        v-model="csvText"
        type="textarea"
        :rows="10"
        spellcheck="false"
        placeholder="candidate_key,smiles"
      />
      <template #footer>
        <el-button @click="csvDialogVisible = false">取消</el-button>
        <el-button type="primary" :loading="actionLoading === 'import-csv'" @click="handleImportCsv">导入</el-button>
      </template>
    </el-dialog>
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

.import-report {
  display: grid;
  grid-template-columns: repeat(4, minmax(0, 1fr));
  gap: 16px;
}

.report-table {
  grid-column: 1 / -1;
}

.history-line {
  display: flex;
  align-items: center;
  gap: 10px;
}

.re-entry-grid {
  display: grid;
  grid-template-columns: repeat(3, minmax(0, 1fr));
  gap: 12px;
}

.re-entry-card {
  min-height: 160px;
  padding: 14px;
  border: 1px solid var(--app-border-soft);
  border-radius: var(--app-radius-md);
  background: #f8fbff;
  display: flex;
  flex-direction: column;
}

.re-entry-top {
  display: flex;
  align-items: center;
  gap: 8px;
  margin-bottom: 8px;
  font-weight: 600;
  font-size: 14px;
  color: var(--app-ink);
}

.re-entry-card p {
  flex: 1;
  margin: 0 0 12px;
  color: var(--app-ink-body);
  font-size: 13px;
  line-height: 1.5;
}

@media (max-width: 900px) {
  .re-entry-grid {
    grid-template-columns: 1fr;
  }
  .detail-grid,
  .import-report {
    grid-template-columns: 1fr;
  }
}
</style>
