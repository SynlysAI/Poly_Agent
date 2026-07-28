<script setup>
import { computed, onMounted, onUnmounted, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import {
  Check, ArrowRight, DataAnalysis, MagicStick, Star, SetUp, Document, Download, CircleCheck, CircleClose, Clock, Collection,
} from '@element-plus/icons-vue'

import ProblemSpecPanel from './research-engine/ProblemSpecPanel.vue'
import AlgorithmRegistryPanel from './research-engine/AlgorithmRegistryPanel.vue'
import AlgorithmRunPanel from './research-engine/AlgorithmRunPanel.vue'
import AlgorithmRunDetail from './research-engine/AlgorithmRunDetail.vue'
import PipelineRunPanel from './research-engine/PipelineRunPanel.vue'
import ResearchRunPanel from './research-engine/ResearchRunPanel.vue'
import GateReviewDialog from './research-engine/GateReviewDialog.vue'
import ReportGenerateDrawer from './research-engine/ReportGenerateDrawer.vue'
import ReportJobPanel from './research-engine/ReportJobPanel.vue'
import AttributionBanner from '../components/attribution/AttributionBanner.vue'
import { formatApiDateTime } from '../utils/datetime'
import {
  createReport,
  createExecutionDecision,
  downloadReportArtifact,
  getActiveExecutionDecision,
  getAlgorithmRun,
  getApiErrorMessage,
  getManualWorkflow,
  getProblemSpec,
  getReportReadiness,
  getResearchEngineReadiness,
  getResearchRun,
  getResearchRunTraceability,
  instantiateResearchEngineExample,
  listReports,
  listResearchEngineExamples,
  retryReport,
} from '../api/polyAgentApi'
import { ElMessage } from 'element-plus'

const route = useRoute()
const router = useRouter()

// ── 工作流全局状态 ──
const currentStep = ref(1)
const problemSpec = ref(null)
const executionDecision = ref(null)
const executionMode = ref(null) // 'manual_workbench' | 'autoresearch'
const modeSelecting = ref(false)
const manualWorkflow = ref(null)
const workflowRun = ref(null)
const algorithmRun = ref(null)
const researchRun = ref(null)
const selectedAlgorithm = ref(null)
const pipelineSteps = ref([])  // 多算法流水线步骤列表
const examples = ref([])
const examplesVisible = ref(false)
const examplesLoading = ref(false)
const instantiatingExample = ref('')
const gateDialogVisible = ref(false)
const gateStage = ref(null)
const researchTraceability = ref(null)
const traceabilityLoading = ref(false)
const reportDrawerVisible = ref(false)
const reportJobs = ref([])
const reportJobsLoading = ref(false)
const reportSubmitting = ref(false)
const reportReadiness = ref(null)
const reportReadinessLoading = ref(false)
const readiness = ref(null)
const readinessLoading = ref(false)
const readinessError = ref('')
const advancedMode = ref(route.query.mode === 'manual_workbench' || Boolean(route.query.workflow_id))
let reportPollingTimer = null
const REPORT_TERMINAL_STATUSES = new Set(['completed', 'failed', 'cancelled'])

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

const pendingResearchApprovalStage = computed(() =>
  (researchRun.value?.stage_runs || []).find(stage => stage.status === 'blocked_approval') || null,
)

const reportSubject = computed(() => {
  if (researchRun.value?.run_id) {
    return {
      subject_type: 'research_run',
      subject_id: researchRun.value.run_id,
      status: researchRun.value.status,
    }
  }
  if (algorithmRun.value?.run_id) {
    return {
      subject_type: 'algorithm_run',
      subject_id: algorithmRun.value.run_id,
      status: algorithmRun.value.status,
    }
  }
  return null
})

const reportSubjectKey = computed(() =>
  reportSubject.value ? `${reportSubject.value.subject_type}:${reportSubject.value.subject_id}` : '',
)

const normalizedReportStatus = job => String(job?.status || '').trim().toLowerCase()
const hasActiveReportJobs = computed(() =>
  reportJobs.value.some(job => !REPORT_TERMINAL_STATUSES.has(normalizedReportStatus(job))),
)

const downloadableReportArtifacts = job =>
  (job?.artifact_refs || []).filter(item => ['pdf', 'markdown'].includes(item.artifact_type))

const latestCompletedReport = computed(() =>
  reportJobs.value.find(job => normalizedReportStatus(job) === 'completed' && downloadableReportArtifacts(job).length) || null,
)

const preferredReportArtifact = computed(() => {
  const artifacts = downloadableReportArtifacts(latestCompletedReport.value)
  return artifacts.find(item => item.artifact_type === 'pdf') || artifacts.find(item => item.artifact_type === 'markdown') || null
})

const hasDownloadableReport = computed(() => Boolean(latestCompletedReport.value && preferredReportArtifact.value))

const reportPrimaryButtonText = computed(() => {
  if (hasDownloadableReport.value) return '下载报告'
  if (hasActiveReportJobs.value) return '生成中'
  return '生成报告'
})

const reportReadinessWarnings = computed(() => reportReadiness.value?.warnings || [])
const isReportGenerationReady = computed(() =>
  Boolean(
    reportReadiness.value?.reports_enabled
      && reportReadiness.value?.output_root_ready
      && reportReadiness.value?.provider_ready
      && reportReadiness.value?.skill_pipeline_ready,
  ),
)
const TERMINAL_RUN_STATUSES = new Set(['completed', 'failed', 'cancelled'])
const isCurrentRunTerminal = computed(() => {
  const status = researchRun.value?.status || workflowRun.value?.status || algorithmRun.value?.status
  return TERMINAL_RUN_STATUSES.has(status)
})

const readinessItemsByService = computed(() => {
  const items = readiness.value?.items || []
  return Object.fromEntries(items.map(item => [item.service, item]))
})

const llmReadiness = computed(() => readinessItemsByService.value['research-llm'] || null)
const ragReadiness = computed(() => readinessItemsByService.value.weknora || null)
const autoResearchStageModes = computed(() => readiness.value?.stage_modes || [])

const researchStages = computed(() =>
  researchTraceability.value?.research_run?.stage_runs || researchRun.value?.stage_runs || [],
)

const visibleResearchStages = computed(() =>
  researchStages.value.filter(stage => {
    if (!stage) return false
    if (['pending', 'draft'].includes(stage.status)) return false
    return Boolean(
      stage.started_at
        || stage.finished_at
        || stage.status
        || stage.output_summary
        || stage.error
        || (stage.linked_algorithm_runs || []).length,
    )
  }),
)

const linkedResearchAlgorithmRuns = computed(() => researchTraceability.value?.linked_algorithm_runs || [])
const linkedResearchComputations = computed(() => researchTraceability.value?.linked_computations || [])
const linkedResearchObservations = computed(() => researchTraceability.value?.linked_observations || [])
const researchAuditEvents = computed(() => researchTraceability.value?.audit_events || [])
const hasResearchTraceContent = computed(() =>
  Boolean(
    visibleResearchStages.value.length
      || linkedResearchAlgorithmRuns.value.length
      || linkedResearchComputations.value.length
      || linkedResearchObservations.value.length
      || researchAuditEvents.value.length,
  ),
)

const mainActions = computed(() => [
  {
    key: 'problem',
    title: '定义研发任务',
    description: problemSpec.value ? problemSpec.value.name : '创建或选择研发任务',
    step: 1,
    tag: problemSpec.value ? '已选择' : '开始',
    type: problemSpec.value ? 'success' : 'primary',
    disabled: false,
  },
  {
    key: 'auto',
    title: '启动 AutoResearch',
    description: executionMode.value === 'autoresearch' ? '自动编排已选择' : '以自动编排推进研发任务',
    step: executionMode.value === 'autoresearch' ? 3 : 2,
    tag: executionMode.value === 'autoresearch' ? '已选择' : readinessLevelLabel(llmReadiness.value?.level),
    type: executionMode.value === 'autoresearch' ? 'success' : capabilityTagType(llmReadiness.value?.level),
    disabled: !problemSpec.value,
  },
  {
    key: 'runs',
    title: isCurrentRunTerminal.value ? '结果与报告' : '查看运行与审批',
    description: pendingResearchApprovalStage.value ? '有步骤等待审批' : (researchRun.value?.run_id || algorithmRun.value?.run_id || '查看当前运行状态'),
    step: isCurrentRunTerminal.value ? 5 : (researchRun.value || algorithmRun.value ? 4 : 3),
    tag: pendingResearchApprovalStage.value ? '待审批' : (isCurrentRunTerminal.value ? '可下载' : (researchRun.value || algorithmRun.value ? '可查看' : '待运行')),
    type: pendingResearchApprovalStage.value ? 'warning' : 'info',
    disabled: !(executionMode.value || researchRun.value || algorithmRun.value),
  },
])

const activeMainAction = computed(() => {
  if (currentStep.value === 1) return 'problem'
  if (currentStep.value === 2 || currentStep.value === 3) return 'auto'
  return 'runs'
})
const showInitialAttribution = computed(() => (
  currentStep.value === 1
  && !problemSpec.value
  && !executionMode.value
  && !manualWorkflow.value
  && !workflowRun.value
  && !algorithmRun.value
  && !researchRun.value
))

if (route.query.run_id) {
  algorithmRun.value = { run_id: String(route.query.run_id) }
  executionMode.value = 'manual_workbench'
  currentStep.value = 5
}
if (route.query.research_run_id) {
  currentStep.value = 3
  executionMode.value = 'autoresearch'
}
if (route.query.mode === 'manual_workbench') {
  currentStep.value = 3
  executionMode.value = 'manual_workbench'
}

// ── 步骤定义 ──
const steps = computed(() => [
  {
    key: 1,
    title: '研发任务定义',
    icon: DataAnalysis,
    description: '创建、选择并确认研发任务',
    status: stepStatus(1),
  },
  {
    key: 2,
    title: '执行路径选择',
    icon: MagicStick,
    description: '选择人工编排或自动编排',
    status: stepStatus(2),
    detail: executionMode.value
      ? (executionMode.value === 'manual_workbench' ? '人工算法工作台' : 'AutoResearch 自动编排')
      : null,
  },
  {
    key: 3,
    title: executionMode.value === 'autoresearch' ? 'AutoResearch 编排' : '人工任务流运行',
    icon: executionMode.value === 'autoresearch' ? Star : SetUp,
    description: executionMode.value === 'autoresearch'
      ? '创建并管理自动研发运行'
      : '选择算法、配置参数、运行任务流',
    status: stepStatus(3),
  },
  {
    key: 4,
    title: '当前运行状态',
    icon: Clock,
    description: '查看当前运行步骤与结果',
    status: stepStatus(4),
  },
  {
    key: 5,
    title: '结果与报告',
    icon: Document,
    description: '下载报告并查看关键记录',
    status: stepStatus(5),
  },
])

function stepStatus(stepKey) {
  if (stepKey < currentStep.value) return 'completed'
  if (stepKey === currentStep.value) return 'active'
  return 'pending'
}

const isStepDisabled = (stepKey) => {
  if (stepKey === 1) return false
  if (stepKey === 2) return !problemSpec.value
  if (stepKey === 3) return !executionDecision.value || !executionMode.value
  if (stepKey === 4) return !(algorithmRun.value || researchRun.value)
  if (stepKey === 5) return !isCurrentRunTerminal.value
  return true
}

// ── ProblemSpec 事件处理 ──
function handleSpecSelected(spec, options = {}) {
  problemSpec.value = spec
  if (spec && currentStep.value === 1 && options.source !== 'restore') {
    // 自动进入步骤 2
    currentStep.value = 2
  }
}

// ── 执行路径选择 ──
async function selectExecutionMode(mode) {
  if (!problemSpec.value) {
    ElMessage.warning('请先选择或创建研发任务')
    return
  }
  modeSelecting.value = true
  try {
    const decision = await ensureExecutionDecision(
      problemSpec.value.problem_spec_id,
      mode,
      `选择 ${mode === 'manual_workbench' ? '人工算法工作台' : 'AutoResearch 自动编排'} 执行路径`,
    )
    executionDecision.value = decision
    executionMode.value = mode
    currentStep.value = 3
  } catch (error) {
    ElMessage.error(getApiErrorMessage(error))
  } finally {
    modeSelecting.value = false
  }
}

async function ensureExecutionDecision(problemSpecId, mode, reason) {
  try {
    return await createExecutionDecision(problemSpecId, { mode, reason })
  } catch (error) {
    if (error.status !== 409) throw error
    const active = await getActiveExecutionDecision(problemSpecId)
    if (active?.mode === mode) return active
    throw error
  }
}

// ── 算法运行事件 ──
function handleRunCompleted(run) {
  algorithmRun.value = run
  currentStep.value = TERMINAL_RUN_STATUSES.has(run?.status) ? 5 : 4
}

function handleAlgorithmSelected(algo) {
  selectedAlgorithm.value = algo
  pipelineSteps.value = []  // 清除流水线，切换到单算法模式
}

function handlePipelineConfirmed(steps) {
  pipelineSteps.value = steps
  manualWorkflow.value = null
  workflowRun.value = null
  selectedAlgorithm.value = null  // 清除单算法选择
}

function handlePipelineRunCompleted(result) {
  workflowRun.value = result.workflowRun || null
  algorithmRun.value = result.stepResults?.[0] || result
  currentStep.value = TERMINAL_RUN_STATUSES.has(workflowRun.value?.status) ? 5 : 4
}

// ── ResearchRun 事件 ──
function handleResearchRunUpdated(run) {
  researchRun.value = run
  if (TERMINAL_RUN_STATUSES.has(run?.status)) {
    currentStep.value = 5
    loadResearchTraceability()
  } else if (route.query.action !== 'approve' && run?.status !== 'draft') {
    currentStep.value = 4
  }
}

function openGateReviewFromStatus() {
  if (!pendingResearchApprovalStage.value || !researchRun.value?.run_id) return
  gateStage.value = pendingResearchApprovalStage.value
  gateDialogVisible.value = true
}

function handleGateDecidedFromStatus(result) {
  gateDialogVisible.value = false
  gateStage.value = null
  if (result) {
    handleResearchRunUpdated(result)
  }
}

async function returnToResearchRunDetail() {
  if (!researchRun.value?.run_id) {
    currentStep.value = 3
    return
  }
  executionMode.value = 'autoresearch'
  currentStep.value = 3
  await router.replace({
    query: {
      ...route.query,
      mode: 'autoresearch',
      research_run_id: researchRun.value.run_id,
    },
  })
}

async function loadResearchTraceability() {
  if (!researchRun.value?.run_id) return
  traceabilityLoading.value = true
  try {
    researchTraceability.value = await getResearchRunTraceability(researchRun.value.run_id)
  } catch (error) {
    ElMessage.error(getApiErrorMessage(error))
  } finally {
    traceabilityLoading.value = false
  }
}

async function loadReportJobs(options = {}) {
  if (!reportSubject.value) {
    reportJobs.value = []
    return
  }
  if (reportJobsLoading.value && !options.force) return
  const showLoading = !options.silent
  if (showLoading) {
    reportJobsLoading.value = true
  }
  try {
    const data = await listReports({
      subject_type: reportSubject.value.subject_type,
      subject_id: reportSubject.value.subject_id,
      page: 1,
      page_size: 10,
    })
    reportJobs.value = data.items || []
  } catch (error) {
    if (!options.silent) {
      ElMessage.error(getApiErrorMessage(error))
    }
  } finally {
    if (showLoading) {
      reportJobsLoading.value = false
    }
  }
}

async function loadReportReadiness(options = {}) {
  reportReadinessLoading.value = true
  try {
    reportReadiness.value = await getReportReadiness()
  } catch (error) {
    if (!options.silent) {
      ElMessage.error(getApiErrorMessage(error))
    }
  } finally {
    reportReadinessLoading.value = false
  }
}

function openReportDrawer() {
  if (!reportSubject.value) {
    ElMessage.warning('暂无可生成报告的运行对象')
    return
  }
  if (!reportReadiness.value) {
    loadReportReadiness({ silent: true })
  }
  reportDrawerVisible.value = true
}

async function handleReportPrimaryAction() {
  if (!reportSubject.value) {
    ElMessage.warning('暂无可生成报告的运行对象')
    return
  }
  if (hasDownloadableReport.value) {
    await handleReportDownload(latestCompletedReport.value, preferredReportArtifact.value)
    return
  }
  if (hasActiveReportJobs.value) {
    await loadReportJobs()
    return
  }
  openReportDrawer()
}

async function handleReportSubmit(payload) {
  reportSubmitting.value = true
  try {
    await createReport(payload)
    reportDrawerVisible.value = false
    ElMessage.success('报告任务已创建')
    await loadReportJobs()
    syncReportPolling()
  } catch (error) {
    ElMessage.error(getApiErrorMessage(error))
  } finally {
    reportSubmitting.value = false
  }
}

async function handleReportRetry(job) {
  reportJobsLoading.value = true
  try {
    await retryReport(job.report_id)
    ElMessage.success('报告任务已重试')
    await loadReportJobs({ force: true })
    syncReportPolling()
  } catch (error) {
    ElMessage.error(getApiErrorMessage(error))
  } finally {
    reportJobsLoading.value = false
  }
}

async function handleReportDownload(job, artifact) {
  try {
    const data = await downloadReportArtifact(job.report_id, artifact.artifact_id, artifact.filename)
    saveBlob(data.blob, data.filename)
  } catch (error) {
    ElMessage.error(getApiErrorMessage(error))
  }
}

function saveBlob(blob, filename) {
  const url = URL.createObjectURL(blob)
  const link = document.createElement('a')
  link.href = url
  link.download = filename || 'report.dat'
  document.body.appendChild(link)
  link.click()
  document.body.removeChild(link)
  URL.revokeObjectURL(url)
}

function startReportPolling() {
  if (reportPollingTimer) return
  reportPollingTimer = window.setInterval(async () => {
    if (!reportSubject.value) {
      stopReportPolling()
      return
    }
    await loadReportJobs({ silent: true, force: true })
    if (!hasActiveReportJobs.value) {
      stopReportPolling()
    }
  }, 2500)
}

function stopReportPolling() {
  if (!reportPollingTimer) return
  window.clearInterval(reportPollingTimer)
  reportPollingTimer = null
}

function syncReportPolling() {
  if (reportSubject.value && hasActiveReportJobs.value) {
    startReportPolling()
  } else {
    stopReportPolling()
  }
}

function statusTag(status) {
  const map = { draft: 'info', running: 'warning', paused: 'info', blocked_approval: 'danger', completed: 'success', failed: 'danger', archived: 'info', pending: 'info' }
  return map[status] || 'info'
}

function capabilityTagType(level) {
  const map = {
    production_ready: 'success',
    configured_pending_verification: 'warning',
    demo_fallback: 'info',
    not_configured: 'danger',
    unavailable: 'danger',
  }
  return map[level] || 'info'
}

function readinessLevelLabel(level) {
  const map = {
    production_ready: '真实已接入',
    configured_pending_verification: '已配置待验证',
    demo_fallback: '演示路径',
    not_configured: '未配置',
    unavailable: '不可用',
  }
  return map[level] || '待检查'
}

function stageModeLabel(mode) {
  const map = {
    adapter: '真实接入',
    llm: 'AI 模型',
    demo_fallback: '演示路径',
    mock_fallback: '演示路径',
    not_configured: '未配置',
    human_approval: '人工审批',
    system: '系统处理',
    manual_or_adapter: '人工确认',
  }
  return map[mode] || mode || '-'
}

async function loadReadiness() {
  readinessLoading.value = true
  readinessError.value = ''
  try {
    readiness.value = await getResearchEngineReadiness()
  } catch (error) {
    readinessError.value = getApiErrorMessage(error)
  } finally {
    readinessLoading.value = false
  }
}

function handleMainAction(action) {
  if (action.disabled) return
  if (action.key === 'auto' && problemSpec.value && executionMode.value !== 'autoresearch') {
    selectExecutionMode('autoresearch')
    return
  }
  currentStep.value = action.step
}

function enableAdvancedMode(targetStep = currentStep.value) {
  advancedMode.value = true
  currentStep.value = targetStep
}

function formatDate(value) {
  return formatApiDateTime(value)
}

function shortJson(value) {
  if (!value || (typeof value === 'object' && Object.keys(value).length === 0)) return '-'
  return JSON.stringify(value, null, 2)
}

function workflowStepsFromWorkflow(workflow) {
  return (workflow?.steps || []).map((step, idx) => ({
    step_id: step.step_id || `step_${idx + 1}`,
    algorithm_id: step.algorithm_id,
    name: step.name || step.algorithm_name || step.algorithm_id,
    input_bindings: step.input_bindings || {},
    depends_on: step.depends_on || [],
  }))
}

async function restoreRouteState() {
  const algorithmRunId = route.query.run_id ? String(route.query.run_id) : ''
  const problemSpecId = route.query.problem_spec_id ? String(route.query.problem_spec_id) : ''
  const workflowId = route.query.workflow_id ? String(route.query.workflow_id) : ''
  const researchRunId = route.query.research_run_id ? String(route.query.research_run_id) : ''
  const mode = route.query.mode ? String(route.query.mode) : ''

  try {
    if (workflowId || mode === 'manual_workbench') {
      advancedMode.value = true
    }
    if (problemSpecId) {
      problemSpec.value = await getProblemSpec(problemSpecId)
      try {
        executionDecision.value = await getActiveExecutionDecision(problemSpecId)
      } catch {
        executionDecision.value = null
      }
      executionMode.value = mode || executionDecision.value?.mode || executionMode.value
      currentStep.value = workflowId || mode ? 3 : 1
    }

    if (workflowId) {
      const workflow = await getManualWorkflow(workflowId)
      manualWorkflow.value = workflow
      workflowRun.value = null
      if (!problemSpec.value && workflow.problem_spec_id) {
        problemSpec.value = await getProblemSpec(workflow.problem_spec_id)
      }
      executionDecision.value = executionDecision.value || {
        decision_id: workflow.execution_decision_id,
        mode: 'manual_workbench',
      }
      executionMode.value = 'manual_workbench'
      selectedAlgorithm.value = null
      pipelineSteps.value = workflowStepsFromWorkflow(workflow)
      currentStep.value = 3
    }

    if (algorithmRunId && !researchRunId) {
      const run = await getAlgorithmRun(algorithmRunId)
      algorithmRun.value = run
      researchRun.value = null
      workflowRun.value = null
      selectedAlgorithm.value = null
      pipelineSteps.value = []
      executionMode.value = run.trigger_source === 'autoresearch' ? 'autoresearch' : 'manual_workbench'
      if (!problemSpec.value && run.problem_spec_id) {
        problemSpec.value = await getProblemSpec(run.problem_spec_id)
      }
      executionDecision.value = executionDecision.value || {
        decision_id: run.workflow_run_id || run.research_run_id || '',
        mode: executionMode.value,
      }
      currentStep.value = TERMINAL_RUN_STATUSES.has(run.status) ? 5 : 4
    }

  if (researchRunId) {
      const run = await getResearchRun(researchRunId)
      researchRun.value = run
      algorithmRun.value = null
      executionMode.value = 'autoresearch'
      if (!problemSpec.value && run.problem_spec_id) {
        problemSpec.value = await getProblemSpec(run.problem_spec_id)
      }
      executionDecision.value = executionDecision.value || {
        decision_id: run.execution_decision_id || '',
        mode: 'autoresearch',
      }
      currentStep.value = run.status === 'completed' || run.status === 'failed' ? 5 : 4
      if (currentStep.value === 5) {
        await loadResearchTraceability()
      }
    }

    if (route.query.action === 'report' && reportSubject.value) {
      openReportDrawer()
    }
  } catch (error) {
    ElMessage.error(getApiErrorMessage(error))
  }
}

async function loadExamples() {
  examplesLoading.value = true
  try {
    const data = await listResearchEngineExamples()
    examples.value = data.items || []
  } catch (error) {
    ElMessage.error(getApiErrorMessage(error))
  } finally {
    examplesLoading.value = false
  }
}

async function openExamples() {
  examplesVisible.value = true
  if (!examples.value.length) {
    await loadExamples()
  }
}

async function instantiateExample(exampleId) {
  instantiatingExample.value = exampleId
  try {
    const data = await instantiateResearchEngineExample(exampleId)
    problemSpec.value = data.problem_spec
    executionDecision.value = data.execution_decision
    executionMode.value = data.execution_decision?.mode || (data.research_run ? 'autoresearch' : 'manual_workbench')
    manualWorkflow.value = data.manual_workflow || null
    workflowRun.value = data.workflow_run || null
    researchRun.value = data.research_run || null
    algorithmRun.value = null
    selectedAlgorithm.value = null
    pipelineSteps.value = data.manual_workflow
      ? workflowStepsFromWorkflow(data.manual_workflow)
      : []
    currentStep.value = 3
    examplesVisible.value = false
    ElMessage.success(data.message || '示例流程已创建')
    if (data.navigation?.path) {
      await router.push(data.navigation)
    }
  } catch (error) {
    ElMessage.error(getApiErrorMessage(error))
  } finally {
    instantiatingExample.value = ''
  }
}

// ── 导航到步骤 ──
function goToStep(stepKey) {
  if (isStepDisabled(stepKey)) return
  currentStep.value = stepKey
}

// ── 步骤图标组件映射 ──
function stepIconComponent(step) {
  if (step.status === 'completed') return CircleCheck
  if (step.status === 'active') return step.icon
  return step.icon
}

onMounted(async () => {
  loadReadiness()
  loadReportReadiness({ silent: true })
  loadExamples()
  await restoreRouteState()
  if (reportSubject.value) {
    await loadReportJobs({ silent: true })
    syncReportPolling()
  }
})

onUnmounted(() => {
  stopReportPolling()
})

watch(
  () => [route.query.run_id, route.query.problem_spec_id, route.query.workflow_id, route.query.research_run_id, route.query.mode],
  () => {
    restoreRouteState()
  },
)

watch(
  () => [currentStep.value, researchRun.value?.run_id],
  () => {
    if (currentStep.value === 5 && researchRun.value?.run_id) {
      loadResearchTraceability()
    }
  },
)

watch(
  () => reportSubjectKey.value,
  () => {
    if (reportSubject.value) {
      loadReportJobs()
      loadReportReadiness({ silent: true })
    } else {
      reportJobs.value = []
    }
  },
)

watch(
  () => [reportSubjectKey.value, hasActiveReportJobs.value],
  () => {
    syncReportPolling()
  },
)
</script>

<template>
  <div class="research-engine-workflow">
    <!-- 顶部概览条 -->
    <section class="workflow-topbar">
      <div class="topbar-left">
        <h3>ResearchEngine 研发引擎</h3>
        <span class="topbar-subtitle">材料研发任务编排与结果追溯</span>
      </div>
      <div class="topbar-right">
        <el-button :icon="Collection" @click="openExamples">示例流程</el-button>
        <span v-if="problemSpec" class="topbar-badge">
          <el-icon><Check /></el-icon>
          {{ problemSpec.name }}
        </span>
        <span v-if="executionMode" class="topbar-badge mode-badge">
          {{ executionMode === 'manual_workbench' ? '人工工作台' : 'AutoResearch' }}
        </span>
      </div>
    </section>

    <AttributionBanner v-if="showInitialAttribution" module-id="research_engine" label="参考框架" compact />

    <!-- 主体：左侧工作流树 + 右侧工作区 -->
    <div class="workflow-body">
      <!-- 左侧工作流树 -->
      <aside class="workflow-tree">
        <div class="tree-header">主流程</div>
        <div class="primary-action-list">
          <button
            v-for="action in mainActions"
            :key="action.key"
            type="button"
            class="primary-action-card"
            :class="{ 'is-active': activeMainAction === action.key, 'is-disabled': action.disabled }"
            :disabled="action.disabled"
            @click="handleMainAction(action)"
          >
            <span>
              <strong>{{ action.title }}</strong>
              <small>{{ action.description }}</small>
            </span>
            <el-tag size="small" :type="action.type" effect="plain">{{ action.tag }}</el-tag>
          </button>
        </div>

        <section v-if="advancedMode" class="capability-mini-panel" v-loading="readinessLoading">
          <div class="capability-mini-row">
            <span>AI 模型</span>
            <el-tag size="small" :type="capabilityTagType(llmReadiness?.level)" effect="plain">
              {{ readinessLevelLabel(llmReadiness?.level) }}
            </el-tag>
          </div>
          <p v-if="llmReadiness?.provider || llmReadiness?.model">
            {{ llmReadiness?.provider || '-' }} / {{ llmReadiness?.model || '-' }}
          </p>
          <p v-else>未配置时会明确标注演示路径。</p>
          <div class="capability-mini-row">
            <span>知识检索</span>
            <el-tag size="small" :type="capabilityTagType(ragReadiness?.level)" effect="plain">
              {{ readinessLevelLabel(ragReadiness?.level) }}
            </el-tag>
          </div>
          <p v-if="readinessError" class="capability-error">{{ readinessError }}</p>
        </section>

        <div class="advanced-toggle-row">
          <el-button text size="small" @click="advancedMode = !advancedMode">
            {{ advancedMode ? '收起高级工作区' : '更多 / 高级工作区' }}
          </el-button>
        </div>

        <div v-if="advancedMode" class="tree-steps advanced-steps">
          <div
            v-for="step in steps"
            :key="step.key"
            class="tree-step"
            :class="{
              'is-active': step.status === 'active',
              'is-completed': step.status === 'completed',
              'is-disabled': isStepDisabled(step.key) && step.status !== 'active',
            }"
            @click="goToStep(step.key)"
          >
            <!-- 连线 -->
            <div v-if="step.key > 1" class="step-connector" :class="{ 'connector-done': stepStatus(step.key - 1) === 'completed' }" />

            <div class="step-node">
              <div class="step-icon-wrapper">
                <el-icon :size="18">
                  <component :is="stepIconComponent(step)" />
                </el-icon>
              </div>
              <div class="step-text">
                <div class="step-title">{{ step.title }}</div>
                <div class="step-desc">{{ step.description }}</div>
                <div v-if="step.detail" class="step-detail">{{ step.detail }}</div>
              </div>
              <el-icon v-if="step.status === 'active'" class="step-arrow" :size="14">
                <ArrowRight />
              </el-icon>
            </div>
          </div>
        </div>

        <!-- 快速状态摘要 -->
        <div v-if="problemSpec || researchRun || algorithmRun" class="tree-status">
          <div class="status-title">当前状态</div>
          <div v-if="problemSpec" class="status-row">
            <el-tag size="small" type="success" effect="plain">研发任务</el-tag>
            <span>{{ problemSpec.status === 'frozen' ? '已冻结' : '草稿' }}</span>
          </div>
          <div v-if="executionDecision" class="status-row">
            <el-tag size="small" type="primary" effect="plain">执行路径</el-tag>
            <span>{{ executionMode === 'manual_workbench' ? '人工工作台' : 'AutoResearch' }}</span>
          </div>
          <div v-if="algorithmRun" class="status-row">
            <el-tag size="small" type="warning" effect="plain">算法运行</el-tag>
            <span>{{ algorithmRun.status || 'completed' }}</span>
          </div>
          <div v-if="researchRun" class="status-row">
            <el-tag size="small" :type="researchRun.status === 'completed' ? 'success' : researchRun.status === 'failed' ? 'danger' : 'warning'" effect="plain">
              自动运行
            </el-tag>
            <span>{{ researchRun.status }}</span>
          </div>
        </div>
      </aside>

      <!-- 右侧工作区 -->
      <main class="workflow-main">
        <!-- 步骤 1: 研发任务定义 -->
        <div v-if="currentStep === 1" class="step-panel">
          <div class="step-panel-header">
            <el-icon :size="20"><DataAnalysis /></el-icon>
            <h4>步骤 1：研发任务定义</h4>
          </div>
          <p class="step-panel-desc">创建、编辑或选择已有研发任务。确认后即可进入下一步选择执行路径。</p>
          <ProblemSpecPanel
            :current-problem-spec-id="problemSpec?.problem_spec_id || (route.query.problem_spec_id ? String(route.query.problem_spec_id) : '')"
            @spec-selected="handleSpecSelected"
          />
        </div>

        <!-- 步骤 2: 执行路径选择 -->
        <div v-if="currentStep === 2" class="step-panel">
          <div class="step-panel-header">
            <el-icon :size="20"><MagicStick /></el-icon>
            <h4>步骤 2：执行路径选择</h4>
          </div>
          <p class="step-panel-desc">
            默认使用 AutoResearch 自动编排；人工算法工作台、任务流和算法注册表保留在高级工作区。
          </p>

          <div v-if="!problemSpec" class="empty-hint">
            请先在步骤 1 中选择或创建研发任务
          </div>

          <div v-else class="mode-choice-grid">
            <div
              v-if="advancedMode"
              class="mode-choice-card"
              :class="{ 'is-selected': executionMode === 'manual_workbench' }"
              @click="selectExecutionMode('manual_workbench')"
            >
              <div class="mode-choice-icon manual-icon">
                <el-icon :size="24"><MagicStick /></el-icon>
              </div>
              <h5>人工算法工作台</h5>
              <p>从算法清单中选择节点，手动编排任务流并逐个运行。</p>
              <el-button
                size="small"
                type="primary"
                :loading="modeSelecting"
                :disabled="!problemSpec"
              >
                选择人工模式
              </el-button>
            </div>

            <div
              class="mode-choice-card"
              :class="{ 'is-selected': executionMode === 'autoresearch' }"
              @click="selectExecutionMode('autoresearch')"
            >
              <div class="mode-choice-icon auto-icon">
                <el-icon :size="24"><Star /></el-icon>
              </div>
              <h5>AutoResearch 自动编排</h5>
              <p>系统按阶段推进，关键节点等待人工审批；每个阶段会标明真实接入能力、AI 模型或演示路径。</p>
              <div v-if="advancedMode" class="mode-capability-line">
                <el-tag size="small" :type="capabilityTagType(llmReadiness?.level)" effect="plain">
                  AI：{{ readinessLevelLabel(llmReadiness?.level) }}
                </el-tag>
                <el-tag size="small" :type="capabilityTagType(ragReadiness?.level)" effect="plain">
                  RAG：{{ readinessLevelLabel(ragReadiness?.level) }}
                </el-tag>
              </div>
              <el-button
                size="small"
                type="success"
                :loading="modeSelecting"
                :disabled="!problemSpec"
              >
                选择自动模式
              </el-button>
            </div>
          </div>

          <div v-if="!advancedMode" class="advanced-inline-entry">
            <span>需要手工任务流、流水线或算法注册表？</span>
            <el-button text size="small" @click="enableAdvancedMode(2)">打开高级工作区</el-button>
          </div>

          <!-- 已选择执行路径后 -->
          <div v-if="executionDecision && executionMode" class="decision-confirmed">
            <el-alert
              :title="`已选择：${executionMode === 'manual_workbench' ? '人工算法工作台' : 'AutoResearch 自动编排'}`"
              type="success"
              :closable="false"
              show-icon
            >
              <template #default>
                <p style="margin:4px 0 0">编排记录 ID: {{ executionDecision.decision_id }}</p>
                <el-button style="margin-top:8px" type="primary" size="small" @click="currentStep = 3">
                  进入工作区 <el-icon style="margin-left:4px"><ArrowRight /></el-icon>
                </el-button>
              </template>
            </el-alert>
          </div>
        </div>

        <!-- 步骤 3: 分支工作区 -->
        <div v-if="currentStep === 3" class="step-panel">
          <!-- 人工任务流 -->
          <template v-if="executionMode === 'manual_workbench'">
            <div v-if="!advancedMode" class="empty-hint">
              人工任务流属于高级工作区。
              <el-button type="primary" size="small" @click="enableAdvancedMode(3)">打开高级工作区</el-button>
            </div>
            <template v-else>
            <div class="step-panel-header">
              <el-icon :size="20"><SetUp /></el-icon>
              <h4>步骤 3：人工任务流运行</h4>
            </div>
            <p class="step-panel-desc">
              从算法清单中选择多个算法串联成流水线，配置每个步骤的输入参数，一键运行。
              也可选择单个算法快速运行。
            </p>

            <!-- 算法选择区域：未选择算法且无流水线 -->
            <div v-if="!selectedAlgorithm && pipelineSteps.length === 0" class="algo-select-section">
              <h5>选择算法（支持多选串联）</h5>
              <AlgorithmRegistryPanel @run-created="handleAlgorithmSelected" @workflow-confirmed="handlePipelineConfirmed" />
            </div>

            <!-- 多算法流水线模式 -->
            <div v-else-if="pipelineSteps.length > 0">
              <div class="selected-algo-bar">
                <span>流水线模式：<strong>{{ pipelineSteps.map(s => s.name).join(' → ') }}</strong></span>
                <el-button size="small" @click="pipelineSteps = []">重新选择</el-button>
              </div>
              <PipelineRunPanel
                :pipeline-steps="pipelineSteps"
                :existing-workflow="manualWorkflow"
                :problem-spec-id="problemSpec?.problem_spec_id || ''"
                :campaign-id="problemSpec?.campaign_id || ''"
                @run-completed="handlePipelineRunCompleted"
              />
            </div>

            <!-- 已选择单算法，显示运行面板 -->
            <div v-else>
              <div class="selected-algo-bar">
                <span>已选择算法：<strong>{{ selectedAlgorithm.name }}</strong> ({{ selectedAlgorithm.algorithm_id }})</span>
                <el-button size="small" @click="selectedAlgorithm = null">重新选择</el-button>
              </div>
              <div class="two-col">
                <div class="col-left">
                  <AlgorithmRunPanel
                    :selected-algorithm="selectedAlgorithm"
                    :problem-spec-id="problemSpec?.problem_spec_id || ''"
                    :campaign-id="problemSpec?.campaign_id || ''"
                    @run-completed="handleRunCompleted"
                  />
                </div>
                <div class="col-right">
                  <AlgorithmRunDetail v-if="algorithmRun?.run_id" :run-id="algorithmRun.run_id" />
                  <div v-else class="empty-hint">运行任务流后将在此处显示算法运行详情</div>
                </div>
              </div>
            </div>
            </template>
          </template>

          <!-- AutoResearch -->
          <template v-else-if="executionMode === 'autoresearch'">
            <div class="step-panel-header">
              <el-icon :size="20"><Star /></el-icon>
              <h4>步骤 3：AutoResearch 编排</h4>
            </div>
            <p class="step-panel-desc">创建自动研发运行，启动后系统按阶段推进，关键节点会等待人工审批。</p>
            <section v-if="advancedMode" class="autoresearch-readiness-panel" v-loading="readinessLoading">
              <div class="readiness-header">
                <div>
                  <strong>AutoResearch 能力路径</strong>
                  <span>启动前确认真实接入、待验证和演示路径</span>
                </div>
                <el-button text size="small" @click="loadReadiness">刷新</el-button>
              </div>
              <div class="stage-mode-grid">
                <article v-for="stage in autoResearchStageModes" :key="stage.stage_key" class="stage-mode-item">
                  <div>
                    <strong>{{ stage.label }}</strong>
                    <span>{{ stage.capability_id }}</span>
                  </div>
                  <el-tag size="small" :type="capabilityTagType(stage.level)" effect="plain">
                    {{ stageModeLabel(stage.execution_mode) }}
                  </el-tag>
                </article>
              </div>
              <p v-if="llmReadiness?.demo_fallback || ragReadiness?.demo_fallback" class="readiness-note">
                当前包含演示路径，结果页会保留该标记，避免误认为真实科研结论。
              </p>
              <p v-if="readinessError" class="readiness-note readiness-error">{{ readinessError }}</p>
            </section>
            <ResearchRunPanel @research-run-updated="handleResearchRunUpdated" />
          </template>

          <!-- 未选择执行路径 -->
          <div v-else class="empty-hint">
            请先在步骤 2 中选择执行路径
          </div>
        </div>

        <!-- 步骤 4: 当前运行状态 -->
        <div v-if="currentStep === 4" class="step-panel">
          <div class="step-panel-header">
            <el-icon :size="20"><Clock /></el-icon>
            <h4>步骤 4：当前运行状态</h4>
          </div>
          <p class="step-panel-desc">查看当前正在执行或最近完成的运行结果。</p>

          <!-- 算法运行结果 -->
          <template v-if="algorithmRun">
            <AlgorithmRunDetail v-if="algorithmRun.run_id" :run-id="algorithmRun.run_id" />
            <div v-else class="empty-hint">暂无算法运行数据</div>
          </template>

          <!-- 自动研发运行结果 -->
          <template v-if="researchRun">
            <div class="run-summary-card">
              <div class="summary-header">
                <span>自动研发运行 · {{ researchRun.run_id }}</span>
                <el-tag
                  :type="researchRun.status === 'completed' ? 'success' : researchRun.status === 'failed' ? 'danger' : 'warning'"
                >
                  {{ researchRun.status }}
                </el-tag>
              </div>
              <el-descriptions :column="2" border size="small" style="margin-top:12px">
                <el-descriptions-item label="研发任务">{{ researchRun.problem_spec_id }}</el-descriptions-item>
                <el-descriptions-item label="Profile">{{ researchRun.profile_id }}</el-descriptions-item>
                <el-descriptions-item label="当前阶段">{{ researchRun.current_stage || '-' }}</el-descriptions-item>
                <el-descriptions-item label="阶段进度">
                  {{ researchRun.stage_runs?.filter(s => s.status === 'completed').length || 0 }}
                  /
                  {{ researchRun.stage_runs?.length || 0 }}
                </el-descriptions-item>
              </el-descriptions>
              <el-button
                v-if="isCurrentRunTerminal"
                style="margin-top:12px"
                type="primary"
                size="small"
                @click="currentStep = 5"
              >
                查看结果与报告 <el-icon style="margin-left:4px"><ArrowRight /></el-icon>
              </el-button>
              <el-button
                v-if="pendingResearchApprovalStage"
                style="margin-top:12px;margin-left:8px"
                type="warning"
                size="small"
                @click="openGateReviewFromStatus"
              >
                立即审批
              </el-button>
              <el-button
                style="margin-top:12px;margin-left:8px"
                size="small"
                @click="returnToResearchRunDetail"
              >
                返回编排详情
              </el-button>
            </div>
          </template>

          <div v-if="!algorithmRun && !researchRun" class="empty-hint">
            暂无运行数据。请先在步骤 3 中创建并执行任务流或自动研发运行。
          </div>
        </div>

        <!-- 步骤 5: 追溯/结果汇总 -->
        <div v-if="currentStep === 5" class="step-panel">
          <div class="step-panel-header step-panel-header-with-actions">
            <div class="step-panel-title">
              <el-icon :size="20"><Document /></el-icon>
              <h4>步骤 5：结果与报告</h4>
            </div>
            <el-button
              type="primary"
              :icon="hasDownloadableReport ? Download : Document"
              :disabled="!reportSubject"
              @click="handleReportPrimaryAction"
            >
              {{ reportPrimaryButtonText }}
            </el-button>
            <el-button
              v-if="reportSubject && hasDownloadableReport"
              :icon="Document"
              @click="openReportDrawer"
            >
              重新生成
            </el-button>
          </div>
          <p class="step-panel-desc">优先查看报告下载、关键结果和本次运行实际产生的追溯记录。</p>

          <el-alert
            v-if="reportSubject && reportReadiness && (!isReportGenerationReady || reportReadinessWarnings.length)"
            class="report-readiness-alert"
            :title="isReportGenerationReady ? '报告服务有提示信息' : '报告生成配置未完全就绪'"
            type="warning"
            :closable="false"
            show-icon
          >
            <template #default>
              <span>{{ reportReadinessWarnings[0] || '请检查报告 provider、输出目录或 Skill pipeline 配置。' }}</span>
            </template>
          </el-alert>

          <ReportJobPanel
            v-if="reportSubject"
            :jobs="reportJobs"
            :loading="reportJobsLoading"
            @refresh="loadReportJobs"
            @retry="handleReportRetry"
            @download="handleReportDownload"
          />

          <template v-if="algorithmRun?.run_id">
            <AlgorithmRunDetail :run-id="algorithmRun.run_id" :show-traceability="true" />
          </template>

          <template v-if="researchRun?.run_id">
            <div v-loading="traceabilityLoading" class="traceability-panel">
              <div class="trace-summary">
                <div>
                  <strong>{{ researchTraceability?.research_run?.run_id || researchRun.run_id }}</strong>
                  <span>Profile: {{ researchTraceability?.research_run?.profile_id || researchRun.profile_id }}</span>
                </div>
                <el-tag :type="statusTag(researchTraceability?.research_run?.status || researchRun.status)">
                  {{ researchTraceability?.research_run?.status || researchRun.status }}
                </el-tag>
              </div>

              <div v-if="!hasResearchTraceContent" class="empty-hint">暂无已产生的追溯记录</div>

              <section v-if="visibleResearchStages.length" class="trace-section">
                <h5>已执行阶段</h5>
                <div class="trace-stage-list">
                  <article
                    v-for="stage in visibleResearchStages"
                    :key="stage.stage_run_id"
                    class="trace-stage-item"
                  >
                    <div class="trace-stage-header">
                      <strong>{{ stageLabels[stage.stage_key] || stage.stage_key }}</strong>
                      <el-tag size="small" :type="statusTag(stage.status)">{{ stage.status }}</el-tag>
                    </div>
                    <div class="trace-stage-meta">
                      <span>{{ stage.stage_key }}</span>
                      <span>{{ formatDate(stage.started_at) }} - {{ formatDate(stage.finished_at) }}</span>
                    </div>
                    <div v-if="stage.linked_algorithm_runs?.length" class="trace-tags">
                      <el-tag v-for="id in stage.linked_algorithm_runs" :key="id" size="small" effect="plain">{{ id }}</el-tag>
                    </div>
                  </article>
                </div>
              </section>

              <section
                v-if="linkedResearchAlgorithmRuns.length || linkedResearchComputations.length || linkedResearchObservations.length"
                class="trace-section"
              >
                <h5>关联项</h5>
                <div class="trace-link-grid">
                  <div v-if="linkedResearchAlgorithmRuns.length">
                    <strong>算法运行</strong>
                    <el-tag v-for="run in linkedResearchAlgorithmRuns" :key="run.run_id" size="small" :type="statusTag(run.status)">
                      {{ run.algorithm_id }} · {{ run.run_id }}
                    </el-tag>
                  </div>
                  <div v-if="linkedResearchComputations.length">
                    <strong>计算任务</strong>
                    <el-tag v-for="run in linkedResearchComputations" :key="run.run_id" size="small" :type="statusTag(run.status)">
                      {{ run.workflow_type || run.engine || 'computation' }} · {{ run.run_id }}
                    </el-tag>
                  </div>
                  <div v-if="linkedResearchObservations.length">
                    <strong>观测记录</strong>
                    <el-tag v-for="(item, idx) in linkedResearchObservations" :key="idx" size="small" effect="plain">
                      {{ item.observation_id || item.id || `observation_${idx + 1}` }}
                    </el-tag>
                  </div>
                </div>
              </section>

              <el-collapse v-if="researchStages.length || researchAuditEvents.length" class="trace-detail-collapse">
                <el-collapse-item title="展开完整追溯明细" name="research-trace">
                  <section v-if="researchStages.length" class="trace-section">
                    <h5>阶段输入 / 输出 / 审批</h5>
                    <div class="trace-stage-list">
                      <article v-for="stage in researchStages" :key="`detail-${stage.stage_run_id}`" class="trace-stage-item">
                        <div class="trace-stage-header">
                          <strong>{{ stageLabels[stage.stage_key] || stage.stage_key }}</strong>
                          <el-tag size="small" :type="statusTag(stage.status)">{{ stage.status }}</el-tag>
                        </div>
                        <div class="trace-json">
                          <pre>input: {{ shortJson(stage.input_snapshot) }}</pre>
                          <pre>output: {{ shortJson(stage.output_summary) }}</pre>
                          <pre v-if="stage.decisions?.length">decisions: {{ shortJson(stage.decisions) }}</pre>
                          <pre v-if="stage.error">error: {{ shortJson(stage.error) }}</pre>
                        </div>
                      </article>
                    </div>
                  </section>

                  <section v-if="researchAuditEvents.length" class="trace-section">
                    <h5>审计事件</h5>
                    <el-timeline>
                      <el-timeline-item
                        v-for="event in researchAuditEvents"
                        :key="event.event_id"
                        :timestamp="formatDate(event.created_at)"
                        :type="event.event_type === 'failed' || event.event_type === 'rejected' ? 'danger' : event.event_type === 'completed' || event.event_type === 'approved' ? 'success' : 'primary'"
                      >
                        <div class="audit-item">
                          <strong>{{ event.event_type }}</strong>
                          <span>{{ event.entity_type }} · {{ event.entity_id }}</span>
                          <p v-if="event.reason">{{ event.reason }}</p>
                        </div>
                      </el-timeline-item>
                    </el-timeline>
                  </section>
                </el-collapse-item>
              </el-collapse>
            </div>
          </template>

          <div v-if="!algorithmRun && !researchRun" class="empty-hint">
            暂无追溯数据
          </div>
        </div>
      </main>

      <aside class="workflow-context" aria-label="研发任务上下文">
        <section class="context-card">
          <div class="context-card-header">
            <h4>当前上下文</h4>
            <el-tag v-if="currentStep" size="small" effect="plain">步骤 {{ currentStep }}</el-tag>
          </div>
          <div class="context-list">
            <div class="context-row">
              <span>研发任务</span>
              <strong>{{ problemSpec?.name || problemSpec?.problem_spec_id || '未选择' }}</strong>
            </div>
            <div class="context-row">
              <span>执行路径</span>
              <strong>{{ executionMode ? (executionMode === 'manual_workbench' ? '人工工作台' : 'AutoResearch') : '未选择' }}</strong>
            </div>
            <div class="context-row">
              <span>当前运行</span>
              <strong>{{ researchRun?.run_id || workflowRun?.run_id || algorithmRun?.run_id || '暂无' }}</strong>
            </div>
          </div>
        </section>

        <section class="context-card context-card-accent">
          <div class="context-card-header">
            <h4>下一步操作</h4>
          </div>
          <div class="context-actions">
            <el-button
              v-if="pendingResearchApprovalStage"
              type="warning"
              size="small"
              @click="openGateReviewFromStatus"
            >
              审批关键节点
            </el-button>
            <el-button
              v-if="reportSubject"
              type="primary"
              size="small"
              :icon="hasDownloadableReport ? Download : Document"
              :disabled="reportSubmitting"
              @click="handleReportPrimaryAction"
            >
              {{ reportPrimaryButtonText }}
            </el-button>
            <el-button
              v-if="reportSubject && hasDownloadableReport"
              size="small"
              @click="openReportDrawer"
            >
              重新生成
            </el-button>
            <el-button size="small" @click="openExamples">示例流程</el-button>
          </div>
          <p class="context-hint">
            右侧只保留审批、报告和追溯入口，主工作区专注当前步骤。
          </p>
        </section>

        <section class="context-card">
          <div class="context-card-header">
            <h4>追溯状态</h4>
            <el-tag
              v-if="researchRun?.status || algorithmRun?.status"
              size="small"
              :type="statusTag(researchRun?.status || algorithmRun?.status)"
            >
              {{ researchRun?.status || algorithmRun?.status }}
            </el-tag>
          </div>
          <div class="context-list">
            <div class="context-row">
              <span>报告任务</span>
              <strong>{{ reportJobs.length }}</strong>
            </div>
            <div class="context-row">
              <span>活跃报告</span>
              <strong>{{ hasActiveReportJobs ? '有' : '无' }}</strong>
            </div>
            <div class="context-row">
              <span>过程记录</span>
              <strong>{{ researchRun ? (researchTraceability ? '已加载' : '待加载') : (algorithmRun ? '已加载' : '待加载') }}</strong>
            </div>
          </div>
        </section>
      </aside>
    </div>

    <el-dialog v-model="examplesVisible" title="示例流程" width="640px">
      <div v-loading="examplesLoading" class="example-list">
        <article v-for="example in examples" :key="example.example_id" class="example-card">
          <div>
            <h4>{{ example.title }}</h4>
            <p>{{ example.description }}</p>
            <div class="example-tags">
              <el-tag v-for="tag in example.tags" :key="tag" size="small" effect="plain">{{ tag }}</el-tag>
            </div>
          </div>
          <el-button
            type="primary"
            :loading="instantiatingExample === example.example_id"
            @click="instantiateExample(example.example_id)"
          >
            创建示例
          </el-button>
        </article>
      </div>
    </el-dialog>

    <ReportGenerateDrawer
      v-model="reportDrawerVisible"
      :subject="reportSubject"
      :submitting="reportSubmitting"
      @submit="handleReportSubmit"
    />

    <GateReviewDialog
      :visible="gateDialogVisible"
      :research-run-id="researchRun?.run_id || ''"
      :stage-run="gateStage"
      @decided="handleGateDecidedFromStatus"
    />
  </div>
</template>

<style scoped>
.research-engine-workflow {
  display: flex;
  flex-direction: column;
  height: calc(100vh - 120px);
  min-height: 600px;
  gap: 0;
}

/* ── 顶部概览条 ── */
.workflow-topbar {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 14px 20px;
  background: #fff;
  border: 1px solid var(--app-border-soft);
  border-radius: var(--app-radius-md) var(--app-radius-md) 0 0;
  border-bottom: none;
}

.topbar-left {
  display: flex;
  align-items: baseline;
  gap: 12px;
}

.topbar-left h3 {
  margin: 0;
  font-size: 17px;
  color: var(--app-ink);
}

.topbar-subtitle {
  font-size: 13px;
  color: var(--app-ink-muted);
}

.topbar-right {
  display: flex;
  align-items: center;
  flex-wrap: wrap;
  justify-content: flex-end;
  gap: 8px;
}

.topbar-badge {
  display: inline-flex;
  align-items: center;
  gap: 4px;
  font-size: 12px;
  padding: 4px 10px;
  border-radius: var(--app-radius-sm);
  background: #f0fdf4;
  color: #15803d;
  border: 1px solid #bbf7d0;
}

.mode-badge {
  background: #eff6ff;
  color: #1d4ed8;
  border-color: #bfdbfe;
}

.example-list {
  display: flex;
  flex-direction: column;
  gap: 12px;
  min-height: 120px;
}

.example-card {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 16px;
  padding: 14px;
  border: 1px solid var(--app-border-soft);
  border-radius: var(--app-radius-md);
  background: #fff;
}

.example-card h4 {
  margin: 0 0 6px;
  font-size: 15px;
  color: var(--app-ink);
}

.example-card p {
  margin: 0 0 10px;
  color: var(--app-ink-body);
  font-size: 13px;
  line-height: 1.5;
}

.example-tags {
  display: flex;
  flex-wrap: wrap;
  gap: 6px;
}

/* ── 主体三栏布局 ── */
.workflow-body {
  display: grid;
  grid-template-columns: 280px minmax(0, 1fr) 300px;
  flex: 1;
  min-height: 0;
  border: 1px solid var(--app-border-soft);
  border-top: none;
  border-radius: 0 0 var(--app-radius-md) var(--app-radius-md);
  background: #fff;
  overflow: hidden;
}

/* ── 左侧工作流树 ── */
.workflow-tree {
  width: 280px;
  border-right: 1px solid var(--app-border-soft);
  background: #fafbfc;
  display: flex;
  flex-direction: column;
  overflow-y: auto;
}

.tree-header {
  padding: 14px 18px 10px;
  font-weight: 700;
  font-size: 13px;
  color: var(--app-ink-muted);
  text-transform: uppercase;
  letter-spacing: 0.5px;
}

.tree-steps {
  display: flex;
  flex-direction: column;
  padding: 0 12px;
}

.primary-action-list {
  display: flex;
  flex-direction: column;
  gap: 8px;
  padding: 0 12px 12px;
}

.primary-action-card {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 10px;
  width: 100%;
  padding: 10px 12px;
  border: 1px solid var(--app-border-soft);
  border-radius: var(--app-radius-md);
  background: #fff;
  color: var(--app-ink);
  text-align: left;
  cursor: pointer;
}

.primary-action-card.is-active {
  border-color: #bfdbfe;
  background: #eff6ff;
}

.primary-action-card.is-disabled {
  cursor: not-allowed;
  opacity: 0.58;
}

.primary-action-card span {
  min-width: 0;
  display: flex;
  flex-direction: column;
  gap: 3px;
}

.primary-action-card strong {
  font-size: 13px;
  font-weight: 700;
}

.primary-action-card small {
  overflow: hidden;
  color: var(--app-ink-muted);
  font-size: 12px;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.capability-mini-panel {
  margin: 0 12px 10px;
  padding: 10px 12px;
  border: 1px solid var(--app-border-soft);
  border-radius: var(--app-radius-md);
  background: #fff;
}

.capability-mini-row {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 8px;
  margin-bottom: 6px;
  font-size: 12px;
  color: var(--app-ink-body);
}

.capability-mini-panel p {
  margin: 0 0 8px;
  color: var(--app-ink-muted);
  font-size: 12px;
  line-height: 1.45;
}

.capability-error {
  color: #dc2626 !important;
}

.advanced-toggle-row {
  padding: 0 12px 10px;
}

.advanced-steps {
  padding-top: 4px;
  border-top: 1px solid var(--app-border-soft);
}

.tree-step {
  position: relative;
  cursor: pointer;
  user-select: none;
}

.tree-step.is-disabled {
  cursor: not-allowed;
  opacity: 0.45;
}

.step-connector {
  width: 2px;
  height: 18px;
  background: #e5e7eb;
  margin-left: 22px;
}

.connector-done {
  background: #16a34a;
}

.step-node {
  display: flex;
  align-items: flex-start;
  gap: 10px;
  padding: 10px 12px;
  border-radius: var(--app-radius-md);
  transition: background 0.15s;
}

.tree-step.is-active .step-node {
  background: #eff6ff;
  border: 1px solid #bfdbfe;
}

.tree-step.is-completed .step-node {
  background: transparent;
}

.tree-step:not(.is-disabled):hover .step-node {
  background: #f8fbff;
}

.step-icon-wrapper {
  width: 32px;
  height: 32px;
  border-radius: 50%;
  display: flex;
  align-items: center;
  justify-content: center;
  flex-shrink: 0;
  background: #e5e7eb;
  color: #6b7280;
}

.tree-step.is-active .step-icon-wrapper {
  background: #3b82f6;
  color: #fff;
}

.tree-step.is-completed .step-icon-wrapper {
  background: #16a34a;
  color: #fff;
}

.step-text {
  flex: 1;
  min-width: 0;
}

.step-title {
  font-weight: 600;
  font-size: 13px;
  color: var(--app-ink);
  line-height: 1.3;
}

.tree-step.is-active .step-title {
  color: #1d4ed8;
}

.step-desc {
  font-size: 11px;
  color: var(--app-ink-muted);
  margin-top: 2px;
  line-height: 1.4;
}

.step-detail {
  font-size: 11px;
  color: #3b82f6;
  font-weight: 500;
  margin-top: 2px;
}

.step-arrow {
  color: #3b82f6;
  align-self: center;
  animation: pulse-right 1.5s ease-in-out infinite;
}

@keyframes pulse-right {
  0%, 100% { transform: translateX(0); opacity: 0.6; }
  50% { transform: translateX(4px); opacity: 1; }
}

/* ── 状态摘要 ── */
.tree-status {
  margin-top: auto;
  padding: 14px 18px;
  border-top: 1px solid var(--app-border-soft);
}

.status-title {
  font-weight: 600;
  font-size: 12px;
  color: var(--app-ink-muted);
  margin-bottom: 8px;
  text-transform: uppercase;
  letter-spacing: 0.5px;
}

.status-row {
  display: flex;
  align-items: center;
  gap: 8px;
  margin-bottom: 6px;
  font-size: 12px;
  color: var(--app-ink-body);
}

/* ── 右侧工作区 ── */
.workflow-main {
  min-width: 0;
  overflow-y: auto;
  padding: 20px 24px;
}

.step-panel {
  max-width: none;
}

.workflow-context {
  min-width: 0;
  border-left: 1px solid var(--app-border-soft);
  background: #fbfdff;
  overflow-y: auto;
  padding: 14px;
  display: flex;
  flex-direction: column;
  gap: 12px;
}

.context-card {
  border: 1px solid var(--app-border-soft);
  border-radius: var(--app-radius-md);
  background: #ffffff;
  padding: 12px;
}

.context-card-accent {
  background: #f8fbff;
  border-color: #bfdbfe;
}

.context-card-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 8px;
  margin-bottom: 10px;
}

.context-card-header h4 {
  margin: 0;
  color: var(--app-ink);
  font-size: 14px;
}

.context-list,
.context-actions {
  display: flex;
  flex-direction: column;
  gap: 8px;
}

.context-row {
  display: flex;
  flex-direction: column;
  gap: 2px;
}

.context-row span,
.context-hint {
  color: var(--app-ink-muted);
  font-size: 12px;
}

.context-row strong {
  overflow: hidden;
  color: var(--app-ink);
  font-size: 13px;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.context-actions .el-button {
  width: 100%;
}

.context-hint {
  margin: 10px 0 0;
  line-height: 1.5;
}

.step-panel-header {
  display: flex;
  align-items: center;
  gap: 10px;
  margin-bottom: 4px;
}

.step-panel-header-with-actions {
  justify-content: space-between;
  gap: 16px;
}

.step-panel-title {
  display: flex;
  align-items: center;
  gap: 10px;
  min-width: 0;
}

.step-panel-header h4 {
  margin: 0;
  font-size: 17px;
  color: var(--app-ink);
}

.step-panel-desc {
  margin: 6px 0 16px;
  font-size: 13px;
  color: var(--app-ink-muted);
  line-height: 1.6;
}

.report-readiness-alert {
  margin-bottom: 12px;
}

/* ── 执行路径选择卡片 ── */
.mode-choice-grid {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 16px;
  margin-top: 8px;
}

.mode-choice-card {
  padding: 20px;
  border: 2px solid var(--app-border-soft);
  border-radius: var(--app-radius-lg);
  cursor: pointer;
  transition: all 0.2s;
  background: #fff;
}

.mode-choice-card:hover {
  border-color: #93c5fd;
  box-shadow: 0 2px 8px rgba(59, 130, 246, 0.08);
}

.mode-choice-card.is-selected {
  border-color: #3b82f6;
  background: #f8fbff;
}

.mode-choice-icon {
  width: 44px;
  height: 44px;
  border-radius: var(--app-radius-sm);
  display: flex;
  align-items: center;
  justify-content: center;
  margin-bottom: 12px;
}

.manual-icon {
  background: #eff6ff;
  color: #3b82f6;
}

.auto-icon {
  background: #dcfce7;
  color: #15803d;
}

.mode-choice-card h5 {
  margin: 0 0 6px;
  font-size: 15px;
  color: var(--app-ink);
}

.mode-choice-card p {
  margin: 0 0 14px;
  font-size: 13px;
  color: var(--app-ink-body);
  line-height: 1.6;
}

.mode-capability-line,
.advanced-inline-entry {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 8px;
}

.mode-capability-line {
  margin-bottom: 14px;
}

.advanced-inline-entry {
  margin-top: 12px;
  color: var(--app-ink-muted);
  font-size: 13px;
}

.autoresearch-readiness-panel {
  margin-bottom: 14px;
  padding: 12px;
  border: 1px solid var(--app-border-soft);
  border-radius: var(--app-radius-md);
  background: #fbfdff;
}

.readiness-header {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 12px;
  margin-bottom: 10px;
}

.readiness-header div {
  display: flex;
  flex-direction: column;
  gap: 3px;
}

.readiness-header strong {
  color: var(--app-ink);
  font-size: 14px;
}

.readiness-header span,
.readiness-note {
  color: var(--app-ink-muted);
  font-size: 12px;
}

.stage-mode-grid {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 8px;
}

.stage-mode-item {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 8px;
  padding: 8px 10px;
  border: 1px solid var(--app-border-soft);
  border-radius: var(--app-radius-sm);
  background: #fff;
}

.stage-mode-item div {
  min-width: 0;
  display: flex;
  flex-direction: column;
  gap: 2px;
}

.stage-mode-item strong {
  color: var(--app-ink);
  font-size: 12px;
}

.stage-mode-item span {
  overflow: hidden;
  color: var(--app-ink-muted);
  font-size: 11px;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.readiness-note {
  margin: 10px 0 0;
}

.readiness-error {
  color: #dc2626;
}

/* ── 确认提示 ── */
.decision-confirmed {
  margin-top: 16px;
}

/* ── 两栏布局 ── */
.two-col {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 16px;
}

/* ── 通用 ── */
.empty-hint {
  color: var(--app-ink-muted);
  font-size: 14px;
  text-align: center;
  padding: 40px 0;
}

.run-summary-card {
  padding: 16px;
  border: 1px solid var(--app-border-soft);
  border-radius: var(--app-radius-md);
  background: #f8fbff;
}

.summary-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  font-weight: 600;
  font-size: 14px;
}

.traceability-panel {
  display: flex;
  flex-direction: column;
  gap: 16px;
}

.trace-summary {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
  padding: 14px;
  border: 1px solid var(--app-border-soft);
  border-radius: var(--app-radius-md);
  background: #f8fbff;
}

.trace-summary div {
  display: flex;
  flex-direction: column;
  gap: 4px;
  min-width: 0;
}

.trace-summary span,
.trace-stage-meta,
.audit-item span,
.audit-item p,
.trace-link-grid p {
  color: var(--app-ink-muted);
  font-size: 12px;
}

.trace-section h5 {
  margin: 0 0 10px;
  font-size: 14px;
  color: var(--app-ink);
}

.trace-stage-list {
  display: flex;
  flex-direction: column;
  gap: 10px;
}

.trace-stage-item {
  padding: 12px;
  border: 1px solid var(--app-border-soft);
  border-radius: var(--app-radius-md);
  background: #fff;
}

.trace-stage-header,
.trace-stage-meta {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
}

.trace-stage-meta {
  margin-top: 4px;
}

.trace-tags,
.trace-link-grid > div {
  display: flex;
  flex-wrap: wrap;
  gap: 6px;
}

.trace-tags {
  margin-top: 8px;
}

.trace-json {
  margin-top: 8px;
  font-size: 12px;
  color: var(--app-ink-body);
}

.trace-json pre {
  overflow-x: auto;
  margin: 8px 0 0;
  padding: 8px;
  border-radius: var(--app-radius-sm);
  background: #f8fafc;
  white-space: pre-wrap;
  word-break: break-word;
}

.trace-link-grid {
  display: grid;
  grid-template-columns: repeat(3, minmax(0, 1fr));
  gap: 12px;
}

.trace-link-grid > div {
  align-content: flex-start;
  padding: 12px;
  border: 1px solid var(--app-border-soft);
  border-radius: var(--app-radius-md);
  background: #fff;
}

.audit-item {
  display: flex;
  flex-direction: column;
  gap: 3px;
}

.trace-detail-collapse {
  margin-top: 4px;
}

/* ── 算法选择区域 ── */
.algo-select-section h5 {
  margin: 0 0 12px;
  font-size: 14px;
  color: var(--app-ink);
}

.selected-algo-bar {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 10px 14px;
  margin-bottom: 14px;
  background: #eff6ff;
  border: 1px solid #bfdbfe;
  border-radius: var(--app-radius-md);
  font-size: 13px;
  color: var(--app-ink);
}

/* ── 响应式 ── */
@media (max-width: 1180px) {
  .workflow-body {
    grid-template-columns: 240px minmax(0, 1fr);
  }

  .workflow-tree {
    width: 240px;
  }

  .workflow-context {
    grid-column: 1 / -1;
    border-top: 1px solid var(--app-border-soft);
    border-left: none;
    display: grid;
    grid-template-columns: repeat(3, minmax(0, 1fr));
  }
}

@media (max-width: 960px) {
  .workflow-body {
    grid-template-columns: 1fr;
  }

  .workflow-tree {
    width: 100%;
    max-height: 200px;
    border-right: none;
    border-bottom: 1px solid var(--app-border-soft);
  }

  .workflow-context {
    grid-template-columns: 1fr;
  }

  .two-col {
    grid-template-columns: 1fr;
  }

  .mode-choice-grid {
    grid-template-columns: 1fr;
  }

  .stage-mode-grid {
    grid-template-columns: 1fr;
  }

  .trace-link-grid {
    grid-template-columns: 1fr;
  }

  .workflow-topbar {
    flex-direction: column;
    align-items: flex-start;
    gap: 8px;
  }
}
</style>
