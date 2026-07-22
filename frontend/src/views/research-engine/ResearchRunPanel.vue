<script setup>
import { computed, onMounted, ref, watch } from 'vue'
import { useRoute } from 'vue-router'
import { ElMessage, ElMessageBox } from 'element-plus'
import { CircleCheck, CircleClose, Clock, Delete, Refresh, VideoPause, VideoPlay, CloseBold, SwitchButton } from '@element-plus/icons-vue'

import {
  advanceResearchRun,
  archiveResearchRun,
  createExecutionDecision,
  createResearchRun,
  failResearchRun,
  getActiveExecutionDecision,
  getApiErrorMessage,
  getResearchEngineReadiness,
  getResearchRun,
  listProblemSpecs,
  listResearchRuns,
  pauseResearchRun,
  resumeResearchRun,
  startResearchRun,
} from '../../api/polyAgentApi'
import GateReviewDialog from './GateReviewDialog.vue'
import { formatApiDateTime } from '../../utils/datetime'

const emit = defineEmits(['research-run-updated'])
const route = useRoute()

const loading = ref(false)
const actionLoading = ref('')
const runs = ref([])
const selectedRunId = ref('')
const currentRun = ref(null)
const gateDialogVisible = ref(false)
const gateStage = ref(null)
const readiness = ref(null)
const readinessLoading = ref(false)

// 新建 ResearchRun 表单
const newRunForm = ref({
  problem_spec_id: '',
  campaign_id: '',
  profile_id: 'fluoropolymer',
  max_iterations: 5,
  batch_size: 10,
  description: '',
})
const showCreateForm = ref(false)
const problemSpecs = ref([])

const stageLabels = {
  PROBLEM_SPEC: '问题定义',
  KNOWLEDGE_RETRIEVAL: '文献检索',
  STRUCTURE_FEATURE: '结构表示',
  COMPUTE_PREDICT: '计算预测',
  RECOMMENDATION_ASK: '候选推荐',
  HUMAN_REVIEW: '人工审核',
  EXPERIMENT_EXECUTION: '实验执行',
  RESULT_TELL: '结果回填',
  MODEL_UPDATE: '模型更新',
  ARCHIVE_LEARNING: '经验归档',
}

const stageDescriptions = {
  PROBLEM_SPEC: '解析研发任务定义，提取目标、约束与测量条件',
  KNOWLEDGE_RETRIEVAL: '从文献库和知识图谱中检索相关材料合成路线与性能数据',
  STRUCTURE_FEATURE: '将分子结构转换为数值描述符（指纹、图形特征等）',
  COMPUTE_PREDICT: '运行 DFT/xTB 计算或调用预测模型，生成候选分子的性质预测',
  RECOMMENDATION_ASK: '基于多目标贝叶斯优化推荐下一批实验候选',
  HUMAN_REVIEW: '人工审批阶段（Gate），审核推荐候选并决定是否进入实验执行',
  EXPERIMENT_EXECUTION: '将候选方案提交至湿实验平台执行合成与测试',
  RESULT_TELL: '将实验结果回填至 Campaign，更新候选评分',
  MODEL_UPDATE: '用新实验数据更新代理模型（GP/ML），提升后续推荐精度',
  ARCHIVE_LEARNING: '将本次研发过程归档，提取经验写入知识库供后续复用',
}

const completedStages = computed(() => {
  if (!currentRun.value?.stage_runs) return 0
  return currentRun.value.stage_runs.filter(s => s.status === 'completed').length
})
const totalStages = computed(() => currentRun.value?.stage_runs?.length || 10)
const completionPercent = computed(() => {
  if (!totalStages.value) return 0
  return Math.round((completedStages.value / totalStages.value) * 100)
})
const progressColor = computed(() => {
  if (currentRun.value?.status === 'completed') return '#16a34a'
  if (currentRun.value?.status === 'failed') return '#dc2626'
  return '#3b82f6'
})
const pendingApprovalStage = computed(() =>
  (currentRun.value?.stage_runs || []).find(stage => stage.status === 'blocked_approval') || null,
)
const readinessItems = computed(() => readiness.value?.items || [])
const readinessWarnings = computed(() => readinessItems.value.filter(item => item.status !== 'ready'))
const readinessAlertType = computed(() => {
  if (!readiness.value) return 'info'
  if (!readiness.value.can_start) return 'error'
  if (!readiness.value.ready) return 'warning'
  return 'success'
})
const readinessTitle = computed(() => {
  if (!readiness.value) return '启动前检查'
  if (!readiness.value.can_start) return '启动前检查未通过'
  if (!readiness.value.ready) return `启动前检查：${readinessWarnings.value.length} 项使用 fallback`
  return '启动前检查已通过'
})

const profileOptions = [
  { label: '氟基高分子', value: 'fluoropolymer' },
  { label: '碳基高分子', value: 'carbon_polymer' },
  { label: '硅基高分子', value: 'silicon_polymer' },
]

function statusTag(status) {
  const map = { draft: 'info', running: 'warning', paused: 'info', blocked_approval: 'danger', completed: 'success', failed: 'danger', archived: 'info' }
  return map[status] || 'info'
}

function statusLabel(status) {
  const map = { draft: '草稿', running: '运行中', paused: '已暂停', blocked_approval: '等待审批', completed: '已完成', failed: '已失败', archived: '已归档' }
  return map[status] || status
}

function stageStatusTag(status) {
  const map = { pending: 'info', running: 'warning', blocked_approval: 'danger', completed: 'success', failed: 'danger' }
  return map[status] || 'info'
}

function stageStatusLabel(status) {
  const map = { pending: '待执行', running: '执行中', blocked_approval: '等待审批', completed: '已完成', failed: '已失败' }
  return map[status] || status
}

function readinessTag(status) {
  const map = { ready: 'success', warning: 'warning', unavailable: 'danger' }
  return map[status] || 'info'
}

function readinessLabel(status) {
  const map = { ready: '可用', warning: 'Fallback', unavailable: '不可用' }
  return map[status] || status
}

function formatDate(value) {
  return formatApiDateTime(value)
}

const canStart = computed(() => currentRun.value?.status === 'draft')
const canPause = computed(() => ['running', 'blocked_approval'].includes(currentRun.value?.status))
const canResume = computed(() => currentRun.value?.status === 'paused')
const canAdvance = computed(() => currentRun.value?.status === 'running')
const canFail = computed(() => !['completed', 'failed', 'archived'].includes(currentRun.value?.status))

async function loadRuns() {
  loading.value = true
  try {
    const data = await listResearchRuns({ page: 1, page_size: 50 })
    runs.value = data.items || []
  } catch (error) {
    ElMessage.error(getApiErrorMessage(error))
  } finally {
    loading.value = false
  }
}

async function openRouteRunIfNeeded() {
  const routeRunId = route.query.research_run_id ? String(route.query.research_run_id) : ''
  if (!routeRunId) return
  selectedRunId.value = routeRunId
  showCreateForm.value = false
  await loadRunDetail(routeRunId)
  if (route.query.action === 'approve' && pendingApprovalStage.value) {
    openGateReview(pendingApprovalStage.value)
  }
}

async function loadProblemSpecs() {
  try {
    const data = await listProblemSpecs({ page: 1, page_size: 50 })
    problemSpecs.value = data.items || []
  } catch {
    problemSpecs.value = []
  }
}

async function loadReadiness() {
  readinessLoading.value = true
  try {
    readiness.value = await getResearchEngineReadiness()
    return true
  } catch (error) {
    readiness.value = null
    ElMessage.error(getApiErrorMessage(error))
    return false
  } finally {
    readinessLoading.value = false
  }
}

async function ensureReadiness() {
  const checked = await loadReadiness()
  if (!checked) return false
  if (readiness.value && !readiness.value.can_start) {
    ElMessage.error('启动前检查未通过')
    return false
  }
  return true
}

async function selectRun(runId) {
  selectedRunId.value = runId
  showCreateForm.value = false
  if (runId === '__new__') {
    currentRun.value = null
    showCreateForm.value = true
    await Promise.all([loadProblemSpecs(), loadReadiness()])
    return
  }
  await loadRunDetail(runId)
}

async function loadRunDetail(runId) {
  loading.value = true
  try {
    currentRun.value = await getResearchRun(runId)
    emit('research-run-updated', currentRun.value)
  } catch (error) {
    ElMessage.error(getApiErrorMessage(error))
  } finally {
    loading.value = false
  }
}

async function handleCreate() {
  if (!newRunForm.value.problem_spec_id) {
    ElMessage.warning('请选择 ProblemSpec')
    return
  }
  if (!(await ensureReadiness())) return
  actionLoading.value = 'create'
  try {
    const decision = await ensureExecutionDecision(
      newRunForm.value.problem_spec_id,
      'autoresearch',
      '启动 AutoResearch 自动编排',
    )
    const data = await createResearchRun({
      ...newRunForm.value,
      execution_decision_id: decision.decision_id,
    })
    ElMessage.success('ResearchRun 创建成功')
    showCreateForm.value = false
    selectedRunId.value = data.run_id
    currentRun.value = data
    emit('research-run-updated', data)
    await loadRuns()
  } catch (error) {
    ElMessage.error(getApiErrorMessage(error))
  } finally {
    actionLoading.value = ''
  }
}

async function ensureExecutionDecision(problemSpecId, mode, reason) {
  try {
    return await createExecutionDecision(problemSpecId, { mode, reason })
  } catch (error) {
    if (error.status !== 409) {
      throw error
    }
    const active = await getActiveExecutionDecision(problemSpecId)
    if (active?.mode === mode) {
      return active
    }
    throw error
  }
}

async function handleStart() {
  try {
    if (!(await ensureReadiness())) return
    const { value } = await ElMessageBox.prompt('请输入启动原因', '启动 ResearchRun', {
      confirmButtonText: '启动',
      cancelButtonText: '取消',
      inputType: 'textarea',
      inputValidator: (v) => Boolean(v?.trim()) || '原因不能为空',
    })
    actionLoading.value = 'start'
    const data = await startResearchRun(currentRun.value.run_id, { target_status: 'running', reason: value.trim() })
    currentRun.value = data
    emit('research-run-updated', data)
    ElMessage.success('ResearchRun 已启动')
  } catch (error) {
    if (error === 'cancel' || error === 'close') return
    ElMessage.error(getApiErrorMessage(error))
  } finally {
    actionLoading.value = ''
  }
}

async function handlePause() {
  try {
    const { value } = await ElMessageBox.prompt('请输入暂停原因', '暂停 ResearchRun', {
      confirmButtonText: '暂停',
      cancelButtonText: '取消',
      inputType: 'textarea',
      inputValidator: (v) => Boolean(v?.trim()) || '原因不能为空',
    })
    actionLoading.value = 'pause'
    const data = await pauseResearchRun(currentRun.value.run_id, { target_status: 'paused', reason: value.trim() })
    currentRun.value = data
    emit('research-run-updated', data)
    ElMessage.success('ResearchRun 已暂停')
  } catch (error) {
    if (error === 'cancel' || error === 'close') return
    ElMessage.error(getApiErrorMessage(error))
  } finally {
    actionLoading.value = ''
  }
}

async function handleResume() {
  try {
    const { value } = await ElMessageBox.prompt('请输入恢复原因', '恢复 ResearchRun', {
      confirmButtonText: '恢复',
      cancelButtonText: '取消',
      inputType: 'textarea',
      inputValidator: (v) => Boolean(v?.trim()) || '原因不能为空',
    })
    actionLoading.value = 'resume'
    const data = await resumeResearchRun(currentRun.value.run_id, { target_status: 'running', reason: value.trim() })
    currentRun.value = data
    emit('research-run-updated', data)
    ElMessage.success('ResearchRun 已恢复')
  } catch (error) {
    if (error === 'cancel' || error === 'close') return
    ElMessage.error(getApiErrorMessage(error))
  } finally {
    actionLoading.value = ''
  }
}

async function handleAdvance() {
  try {
    const { value } = await ElMessageBox.prompt('请输入推进原因', '继续推进 ResearchRun', {
      confirmButtonText: '推进',
      cancelButtonText: '取消',
      inputType: 'textarea',
      inputValidator: (v) => Boolean(v?.trim()) || '原因不能为空',
    })
    actionLoading.value = 'advance'
    const data = await advanceResearchRun(currentRun.value.run_id, { target_status: 'running', reason: value.trim() })
    currentRun.value = data
    emit('research-run-updated', data)
    ElMessage.success('ResearchRun 已推进')
  } catch (error) {
    if (error === 'cancel' || error === 'close') return
    ElMessage.error(getApiErrorMessage(error))
  } finally {
    actionLoading.value = ''
  }
}

async function handleFail() {
  try {
    const { value } = await ElMessageBox.prompt('请输入失败原因', '标记 ResearchRun 失败', {
      confirmButtonText: '标记失败',
      cancelButtonText: '取消',
      inputType: 'textarea',
      inputValidator: (v) => Boolean(v?.trim()) || '原因不能为空',
    })
    actionLoading.value = 'fail'
    const data = await failResearchRun(currentRun.value.run_id, { target_status: 'failed', reason: value.trim() })
    currentRun.value = data
    emit('research-run-updated', data)
    ElMessage.success('ResearchRun 已标记为失败')
  } catch (error) {
    if (error === 'cancel' || error === 'close') return
    ElMessage.error(getApiErrorMessage(error))
  } finally {
    actionLoading.value = ''
  }
}

async function handleArchiveRun(run) {
  try {
    await ElMessageBox.confirm(`确定要归档 ResearchRun「${run.run_id}」吗？归档后默认历史列表将不再显示，但追溯记录会保留。`, '归档确认', {
      confirmButtonText: '归档',
      cancelButtonText: '取消',
      type: 'warning',
    })
    await archiveResearchRun(run.run_id, { reason: '用户从 AutoResearch 历史列表归档' })
    ElMessage.success('ResearchRun 已归档')
    if (selectedRunId.value === run.run_id) {
      selectedRunId.value = ''
      currentRun.value = null
      emit('research-run-updated', null)
    }
    await loadRuns()
  } catch (error) {
    if (error === 'cancel' || error === 'close') return
    ElMessage.error(getApiErrorMessage(error))
  }
}

function openGateReview(stage) {
  gateStage.value = stage
  gateDialogVisible.value = true
}

function handleGateDecided(result) {
  gateDialogVisible.value = false
  if (result) {
    currentRun.value = result
    emit('research-run-updated', result)
  }
}

watch(
  () => [route.query.research_run_id, route.query.action],
  () => {
    openRouteRunIfNeeded()
  },
)

onMounted(async () => {
  await Promise.all([loadRuns(), loadReadiness()])
  await openRouteRunIfNeeded()
})
</script>

<template>
  <div class="research-run-panel">
    <!-- 选择/新建 -->
    <div class="run-selector">
      <el-select
        v-model="selectedRunId"
        placeholder="选择已有 ResearchRun 或新建"
        style="width: 400px"
        @change="selectRun"
      >
        <el-option label="+ 新建 ResearchRun" value="__new__" />
        <el-option
          v-for="run in runs"
          :key="run.run_id"
          :label="`ResearchRun - ${run.profile_id}`"
          :value="run.run_id"
        >
          <span class="option-row">
            <span class="option-main">
              <span>ResearchRun · {{ run.profile_id }} · {{ statusLabel(run.status) }}</span>
              <el-tag size="small" :type="statusTag(run.status)" style="margin-left:8px">{{ statusLabel(run.status) }}</el-tag>
            </span>
            <el-button
              text
              type="danger"
              size="small"
              :icon="Delete"
              aria-label="归档 ResearchRun"
              @click.stop="handleArchiveRun(run)"
            />
          </span>
        </el-option>
      </el-select>
      <el-button :icon="Refresh" :loading="loading" @click="loadRuns">刷新</el-button>
    </div>

    <!-- 创建表单 -->
    <div v-if="showCreateForm" class="create-form">
      <h4>新建 AutoResearch ResearchRun</h4>

      <el-alert
        v-if="readiness"
        class="readiness-alert"
        :title="readinessTitle"
        :type="readinessAlertType"
        :closable="false"
        show-icon
      >
        <template #default>
          <div class="readiness-grid">
            <div v-for="item in readinessItems" :key="item.service" class="readiness-item">
              <span class="readiness-name">{{ item.label }}</span>
              <el-tag size="small" :type="readinessTag(item.status)">{{ readinessLabel(item.status) }}</el-tag>
              <span class="readiness-message">{{ item.message }}</span>
            </div>
          </div>
          <el-button text size="small" :loading="readinessLoading" @click="loadReadiness">刷新检查</el-button>
        </template>
      </el-alert>

      <!-- Auto Research 简介提示 -->
      <el-alert
        title="Auto Research 自动编排说明"
        type="info"
        :closable="true"
        show-icon
        style="margin-bottom:14px"
      >
        <template #default>
          <p style="margin:0;line-height:1.7">
            Auto Research 将自动按 <strong>十阶段</strong> 推进研发流程（文献检索 → 结构表示 → 计算预测 → 候选推荐 → 实验执行 → 结果回填 → 模型更新 → 经验归档）。
            <br/>
            在 <strong>3 个 Gate 阶段</strong>（问题定义、候选推荐、实验执行）会暂停等待您的审批——届时阶段时间线中会显示橙色<strong>"审批"按钮</strong>。
          </p>
        </template>
      </el-alert>

      <el-form label-position="top">
        <el-form-item label="ProblemSpec" required>
          <el-select v-model="newRunForm.problem_spec_id" placeholder="选择研发任务定义" style="width:100%">
            <el-option
              v-for="spec in problemSpecs"
              :key="spec.problem_spec_id"
              :label="spec.name"
              :value="spec.problem_spec_id"
            />
          </el-select>
        </el-form-item>
        <div class="form-row">
          <el-form-item label="材料 Profile" style="flex:1">
            <el-select v-model="newRunForm.profile_id">
              <el-option v-for="item in profileOptions" :key="item.value" :label="item.label" :value="item.value" />
            </el-select>
          </el-form-item>
          <el-form-item label="最大迭代次数" style="flex:1">
            <el-input-number v-model="newRunForm.max_iterations" :min="1" :max="100" />
          </el-form-item>
          <el-form-item label="批次大小" style="flex:1">
            <el-input-number v-model="newRunForm.batch_size" :min="1" :max="100" />
          </el-form-item>
        </div>
        <el-form-item label="描述">
          <el-input v-model="newRunForm.description" type="textarea" :rows="2" placeholder="简要描述本次 AutoResearch 运行" />
        </el-form-item>
        <el-button type="primary" :loading="actionLoading === 'create'" @click="handleCreate">创建草稿</el-button>
      </el-form>
    </div>

    <!-- ResearchRun 详情 -->
    <div v-if="currentRun" class="run-detail" v-loading="loading">
      <el-alert
        v-if="canStart && readiness"
        class="readiness-alert"
        :title="readinessTitle"
        :type="readinessAlertType"
        :closable="false"
        show-icon
      >
        <template #default>
          <div class="readiness-grid compact">
            <div v-for="item in readinessItems" :key="item.service" class="readiness-item">
              <span class="readiness-name">{{ item.label }}</span>
              <el-tag size="small" :type="readinessTag(item.status)">{{ readinessLabel(item.status) }}</el-tag>
            </div>
          </div>
        </template>
      </el-alert>

      <el-alert
        v-if="pendingApprovalStage"
        class="approval-alert"
        type="warning"
        :closable="false"
        show-icon
      >
        <template #title>
          待审批：{{ stageLabels[pendingApprovalStage.stage_key] || pendingApprovalStage.stage_key }}
        </template>
        <template #default>
          <div class="approval-alert-body">
            <span>当前 ResearchRun 已停在 blocked_approval，需要处理 Gate 审批后才能继续推进。</span>
            <el-button type="warning" size="small" @click="openGateReview(pendingApprovalStage)">立即审批</el-button>
          </div>
        </template>
      </el-alert>

      <!-- 基本信息 -->
      <div class="detail-top">
        <div>
          <h4>{{ currentRun.run_id }}</h4>
          <span class="run-meta">Profile: {{ currentRun.profile_id }} · Batch: {{ currentRun.batch_size }}</span>
        </div>
        <div class="detail-actions">
          <el-tag size="large" :type="statusTag(currentRun.status)">{{ statusLabel(currentRun.status) }}</el-tag>
          <el-button v-if="canStart" type="primary" :icon="VideoPlay" :loading="actionLoading === 'start'" @click="handleStart">启动</el-button>
          <el-button v-if="canPause" :icon="VideoPause" :loading="actionLoading === 'pause'" @click="handlePause">暂停</el-button>
          <el-button v-if="canResume" type="primary" :icon="VideoPlay" :loading="actionLoading === 'resume'" @click="handleResume">恢复</el-button>
          <el-button v-if="canAdvance" :icon="SwitchButton" :loading="actionLoading === 'advance'" @click="handleAdvance">推进</el-button>
          <el-button v-if="canFail" type="danger" :icon="CloseBold" :loading="actionLoading === 'fail'" @click="handleFail">标记失败</el-button>
        </div>
      </div>

      <el-descriptions :column="3" border size="small" style="margin:14px 0">
        <el-descriptions-item label="ProblemSpec">{{ currentRun.problem_spec_id }}</el-descriptions-item>
        <el-descriptions-item label="ExecutionDecision">{{ currentRun.execution_decision_id || '-' }}</el-descriptions-item>
        <el-descriptions-item label="Campaign">{{ currentRun.campaign_id || '-' }}</el-descriptions-item>
        <el-descriptions-item label="当前阶段">{{ stageLabels[currentRun.current_stage] || currentRun.current_stage || '-' }}</el-descriptions-item>
        <el-descriptions-item label="创建者">{{ currentRun.created_by }}</el-descriptions-item>
        <el-descriptions-item label="创建时间">{{ formatDate(currentRun.created_at) }}</el-descriptions-item>
        <el-descriptions-item label="更新时间">{{ formatDate(currentRun.updated_at) }}</el-descriptions-item>
      </el-descriptions>

      <!-- Stage 时间线 -->
      <section class="stage-section">
        <h4>阶段推进进度</h4>
        <!-- 进度条 -->
        <div v-if="currentRun.stage_runs?.length" class="research-progress">
          <el-progress :percentage="completionPercent" :color="progressColor" :stroke-width="8" :striped="currentRun.status === 'running'" :striped-flow="currentRun.status === 'running'" />
          <span class="progress-label">{{ completedStages }}/{{ totalStages }} 阶段完成</span>
        </div>
        <div v-if="currentRun.stage_runs?.length" class="stage-timeline">
          <div
            v-for="(stage, idx) in currentRun.stage_runs"
            :key="stage.stage_run_id"
            class="stage-item"
          >
            <div class="stage-marker">
              <el-icon v-if="stage.status === 'completed'" class="stage-icon-done"><CircleCheck /></el-icon>
              <el-icon v-else-if="stage.status === 'failed'" class="stage-icon-fail"><CircleClose /></el-icon>
              <el-icon v-else-if="stage.status === 'blocked_approval'" class="stage-icon-pending"><Clock /></el-icon>
              <span v-else class="stage-dot" :class="`dot-${stage.status}`" />
              <div v-if="idx < currentRun.stage_runs.length - 1" class="stage-line" :class="stage.status === 'completed' ? 'line-done' : ''" />
            </div>
            <div class="stage-info">
              <div class="stage-info-header">
                <strong :title="stageDescriptions[stage.stage_key] || ''">{{ stageLabels[stage.stage_key] || stage.stage_key }}</strong>
                <el-tag size="small" :type="stageStatusTag(stage.status)">{{ stageStatusLabel(stage.status) }}</el-tag>
              </div>
              <p class="stage-desc-hint">{{ stageDescriptions[stage.stage_key] || '该阶段的具体任务描述待补充' }}</p>
              <div v-if="stage.status === 'blocked_approval'" style="margin-top:4px">
                <el-tooltip content="该阶段需要人工审批。点击「审批」按钮，选择批准或拒绝并填写原因。" placement="top">
                  <el-button type="warning" size="small" @click="openGateReview(stage)">审批</el-button>
                </el-tooltip>
              </div>
              <div v-if="stage.decisions?.length" class="stage-decisions">
                <div v-for="d in stage.decisions" :key="`${d.stage_key}-${d.decided_at}`" class="decision-item">
                  <el-tag size="small" :type="d.decision === 'approved' ? 'success' : 'danger'">
                    {{ d.decision === 'approved' ? '已批准' : '已拒绝' }}
                  </el-tag>
                  <span>{{ d.reason }} · {{ formatDate(d.decided_at) }}</span>
                </div>
              </div>
            </div>
          </div>
        </div>
        <div v-else class="empty-hint">
          <template v-if="currentRun.status === 'draft'">
            尚未开始任何阶段。点击「<strong>启动</strong>」按钮开始 AutoResearch 十阶段自动推进流程。
          </template>
          <template v-else>
            暂无阶段运行记录
          </template>
        </div>
      </section>

      <!-- 关联 AlgorithmRun -->
      <section v-if="currentRun.linked_algorithm_runs?.length" class="linked-section">
        <h4>关联算法运行 ({{ currentRun.linked_algorithm_runs.length }})</h4>
        <div class="linked-list">
          <el-tag v-for="id in currentRun.linked_algorithm_runs" :key="id" size="small" style="margin:2px">{{ id }}</el-tag>
        </div>
      </section>
    </div>

    <!-- Gate 审批 Dialog -->
    <GateReviewDialog
      :visible="gateDialogVisible"
      :research-run-id="currentRun?.run_id || ''"
      :stage-run="gateStage"
      @decided="handleGateDecided"
    />
  </div>
</template>

<style scoped>
.research-run-panel {
  display: flex;
  flex-direction: column;
  gap: 16px;
}

.option-row {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 8px;
  width: 100%;
}

.option-main {
  min-width: 0;
  display: flex;
  align-items: center;
}

.run-selector {
  display: flex;
  align-items: center;
  gap: 12px;
}

.create-form {
  padding: 14px;
  border: 1px solid var(--app-border-soft);
  border-radius: var(--app-radius-md);
  background: #f8fbff;
}

.create-form h4 {
  margin: 0 0 12px;
}

.readiness-alert {
  margin-bottom: 14px;
}

.readiness-grid {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 8px 12px;
  margin: 4px 0 6px;
}

.readiness-grid.compact {
  grid-template-columns: repeat(4, minmax(0, 1fr));
}

.readiness-item {
  display: flex;
  align-items: center;
  gap: 8px;
  min-width: 0;
}

.readiness-name {
  font-weight: 600;
  color: var(--app-ink);
  white-space: nowrap;
}

.readiness-message {
  min-width: 0;
  color: var(--app-ink-muted);
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.form-row {
  display: flex;
  gap: 16px;
}

.detail-top {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 16px;
}

.approval-alert {
  margin-bottom: 14px;
}

.approval-alert-body {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
  flex-wrap: wrap;
}

.detail-top h4 {
  margin: 0;
  font-family: var(--app-mono-font);
  font-size: 15px;
}

.run-meta {
  display: block;
  margin-top: 4px;
  color: var(--app-ink-muted);
  font-size: 12px;
}

.detail-actions {
  display: flex;
  align-items: center;
  gap: 8px;
  flex-wrap: wrap;
}

.stage-section h4,
.linked-section h4 {
  margin: 0 0 10px;
  font-size: 14px;
}

.research-progress {
  display: flex;
  align-items: center;
  gap: 12px;
  margin-bottom: 14px;
}
.research-progress .el-progress {
  flex: 1;
}
.progress-label {
  font-size: 13px;
  color: var(--app-ink-muted);
  white-space: nowrap;
}

.stage-timeline {
  display: flex;
  flex-direction: column;
  gap: 0;
}

.stage-item {
  display: flex;
  gap: 14px;
  min-height: 50px;
}

.stage-marker {
  width: 32px;
  display: flex;
  flex-direction: column;
  align-items: center;
  position: relative;
}

.stage-marker .el-icon {
  font-size: 20px;
}

.stage-icon-done {
  color: #16a34a;
}

.stage-icon-fail {
  color: #dc2626;
}

.stage-icon-pending {
  color: #d97706;
}

.stage-dot {
  width: 12px;
  height: 12px;
  border-radius: 50%;
}

.dot-pending { background: #d1d5db; }
.dot-running { background: #3b82f6; }
.dot-blocked_approval { background: #d97706; }
.dot-completed { background: #16a34a; }
.dot-failed { background: #dc2626; }

.stage-line {
  flex: 1;
  width: 2px;
  background: #e5e7eb;
  min-height: 20px;
}

.line-done {
  background: #16a34a;
}

.stage-info {
  flex: 1;
  padding-bottom: 14px;
  display: flex;
  flex-direction: column;
  gap: 4px;
}

.stage-info-header {
  display: flex;
  align-items: center;
  gap: 8px;
}

.stage-info strong {
  font-size: 14px;
}

.stage-desc-hint {
  margin: 0;
  font-size: 12px;
  color: var(--app-ink-muted);
  line-height: 1.5;
}

.stage-decisions {
  margin-top: 4px;
  display: flex;
  flex-direction: column;
  gap: 4px;
}

.decision-item {
  display: flex;
  align-items: center;
  gap: 8px;
  font-size: 12px;
  color: var(--app-ink-muted);
}

.linked-list {
  display: flex;
  flex-wrap: wrap;
  gap: 4px;
}

.empty-hint {
  color: var(--app-ink-muted);
  font-size: 13px;
  text-align: center;
  padding: 16px 0;
}

@media (max-width: 760px) {
  .readiness-grid,
  .readiness-grid.compact {
    grid-template-columns: 1fr;
  }

  .readiness-message {
    white-space: normal;
  }
}
</style>
