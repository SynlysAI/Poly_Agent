<script setup>
import { computed, onMounted, reactive, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { ElMessage } from 'element-plus'
import {
  Check, DataAnalysis, Edit, Files, Refresh, SetUp, View as ViewIcon, Warning,
} from '@element-plus/icons-vue'
import AttributionBanner from '../components/attribution/AttributionBanner.vue'
import AttributionBadges from '../components/attribution/AttributionBadges.vue'
import { authState } from '../auth/authState'
import {
  buildPolicyPayload,
  buildTestRunPayload,
  connectorStatus,
  formatQualitySummary,
  normalizePolicyForm,
} from '../utils/agentConnectors'

import {
  checkLlmModels,
  checkIntegrationConfig,
  createAgentExecRun,
  getAlgorithm,
  getAgentExecProviders,
  getAgentExecQuality,
  getAssistantQualityMetrics,
  getApiErrorMessage,
  getIntegrationStatus,
  getLlmConfigSchema,
  getLlmModels,
  listAgentToolRegistry,
  listAgentTools,
  listAlgorithms,
  listIntegrationConfigs,
  syncAgentTools,
  updateAgentExecPolicy,
  updateAgentToolPolicy,
  updateLlmRouting,
  upsertIntegrationConfig,
} from '../api/polyAgentApi'

const route = useRoute()
const router = useRouter()
const services = ref([])
const configs = ref([])
const llmCatalog = ref({ providers: [], routing: {} })
const llmConfigSchema = ref({ provider_fields: [], per_model_fields: [] })
const llmQualityMetrics = ref(null)
const loadingStatus = ref(false)
const loadingConfigs = ref(false)
const loadingLlm = ref(false)
const loadingLlmExtras = ref(false)
const saving = ref(false)
const savingLlmRouting = ref(false)
const actionLoading = ref('')
const configError = ref('')
const llmError = ref('')
const llmExtrasError = ref('')
const editVisible = ref(false)
const editingServiceKey = ref('')
const activeTab = ref(normalizeTab(route.query.tab))
const statusDetailVisible = ref(false)
const selectedServiceStatus = ref(null)
const serviceGroupFilter = ref('all')

// ── ResearchEngine 算法清单 ──
const algorithms = ref([])
const algoLoading = ref(false)
const agentToolItems = ref([])
const agentToolLoading = ref(false)
const agentToolSaving = ref('')
const syncingAgentTools = ref(false)
const agentToolFilter = ref('')
const algoDetailVisible = ref(false)
const algoDetail = ref(null)
const algoFilters = reactive({ type: '', material_scope: '', keyword: '' })
const configDetailVisible = ref(false)
const selectedConfig = ref(null)
const llmRouteForm = reactive({ qa: '', deep: '', report: '' })

function normalizeTab(value) {
  const tab = Array.isArray(value) ? value[0] : value
  return ['status', 'algorithms', 'agent-tools', 'agent-connectors', 'configs', 'llm-models'].includes(tab) ? tab : 'status'
}

const isAdmin = computed(() => authState.role === 'admin' || !authState.authEnabled)

const visibleAgentTools = computed(() => {
  const keyword = agentToolFilter.value.trim().toLowerCase()
  const items = agentToolItems.value || []
  if (!keyword) return items
  return items.filter((item) =>
    [item.name, item.tool_id, item.algorithm_id, item.description]
      .filter(Boolean)
      .some((value) => String(value).toLowerCase().includes(keyword)),
  )
})

function agentToolPhaseLabel(phase) {
  const map = { available: '可调用', disabled: '已禁用', unavailable: '不可用' }
  return map[phase] || phase
}

function agentToolPhaseTag(phase) {
  const map = { available: 'success', disabled: 'warning', unavailable: 'danger' }
  return map[phase] || 'info'
}

function agentToolHealthLabel(status) {
  const map = { healthy: '健康', unknown: '未知', unavailable: '不可用' }
  return map[status] || status
}

const algoTypeOptions = [
  { label: '全部类型', value: '' },
  { label: '检索器', value: 'retriever' },
  { label: '预测器', value: 'predictor' },
  { label: '模拟器', value: 'simulator' },
  { label: '优化器', value: 'optimizer' },
]

function algoTypeTag(type) {
  const map = { retriever: 'info', predictor: 'success', simulator: 'warning', optimizer: 'danger' }
  return map[type] || 'info'
}

function algoTypeLabel(type) {
  const map = { retriever: '检索器', predictor: '预测器', simulator: '模拟器', optimizer: '优化器' }
  return map[type] || type
}

function algoStatusTag(status) {
  const map = { active: 'success', pending_encapsulation: 'warning', in_development: 'info', frozen: 'info', decommissioned: 'danger' }
  return map[status] || 'info'
}

function algoStatusLabel(status) {
  const map = { active: '已接入', pending_encapsulation: '待封装', in_development: '开发中', frozen: '冻结', decommissioned: '下线' }
  return map[status] || status
}

function algoIntegrationKind(item) {
  if (item.capability_group === 'vertical_algorithm') return 'vertical'
  return item.integration_kind || 'builtin'
}

function algoIntegrationLabel(kind) {
  const map = { real: '真实能力', builtin: '内置能力', simulated: '模拟演示', pending: '待接入', vertical: '垂类算法' }
  return map[kind] || kind
}

function algoIntegrationTag(kind) {
  const map = { real: 'success', builtin: 'info', simulated: 'warning', pending: 'danger', vertical: 'success' }
  return map[kind] || 'info'
}

function materialScopeLabel(scopes) {
  const map = {
    fluoropolymer: '氟基',
    carbon_polymer: '碳基',
    silicon_polymer: '硅基',
    fluoro_carbon_copolymer: '氟碳共聚',
    universal: '通用',
  }
  return (scopes || []).map((scope) => map[scope] || scope)
}

function triggerModeLabel(modes) {
  const map = { human_workflow: '人工工作流', autoresearch: 'AutoResearch', system: '系统' }
  return (modes || []).map((mode) => map[mode] || mode)
}

const algorithmGroupDefs = [
  { key: 'real', label: '真实能力', hint: '已接入真实服务、SDK 或本地计算链路', tone: 'teal' },
  { key: 'builtin', label: '内置能力', hint: '平台内置能力或待封装能力', tone: 'blue' },
  { key: 'simulated', label: '模拟演示', hint: '仅用于演示、流程占位或 mock 输出', tone: 'amber' },
  { key: 'vertical', label: '垂类算法', hint: '材料性质等垂类模型服务与上传算法', tone: 'violet' },
]

const filteredAlgos = computed(() => {
  const kw = algoFilters.keyword.trim().toLowerCase()
  return algorithms.value.filter((item) => {
    const matchesType = !algoFilters.type || item.type === algoFilters.type
    const matchesMaterial = !algoFilters.material_scope || (item.material_scope || []).includes(algoFilters.material_scope)
    const haystack = `${item.name} ${item.algorithm_id} ${item.description || ''}`.toLowerCase()
    return matchesType && matchesMaterial && (!kw || haystack.includes(kw))
  })
})

const groupedAlgos = computed(() => {
  const groups = Object.fromEntries(algorithmGroupDefs.map((group) => [group.key, []]))
  filteredAlgos.value.forEach((item) => {
    const key = algoIntegrationKind(item)
    const target = groups[key] ? key : 'builtin'
    groups[target].push(item)
  })
  return algorithmGroupDefs.map((group) => ({ ...group, items: groups[group.key] || [] }))
})

const algorithmStats = computed(() =>
  algorithmGroupDefs.map((group) => {
    const count = filteredAlgos.value.filter((item) => {
      const key = algoIntegrationKind(item)
      return (key === group.key) || (!algorithmGroupDefs.some((def) => def.key === key) && group.key === 'builtin')
    }).length
    return { ...group, count }
  }),
)

async function loadAlgos() {
  algoLoading.value = true
  try {
    const data = await listAlgorithms({ page: 1, page_size: 100 })
    algorithms.value = data.items || []
  } catch (error) {
    ElMessage.error(getApiErrorMessage(error))
  } finally {
    algoLoading.value = false
  }
}

async function loadAgentToolItems() {
  agentToolLoading.value = true
  try {
    agentToolItems.value = isAdmin.value
      ? (await listAgentToolRegistry())?.items || []
      : (await listAgentTools())?.items || []
  } catch (error) {
    agentToolItems.value = []
    ElMessage.warning(`算法工具目录加载失败：${getApiErrorMessage(error)}`)
  } finally {
    agentToolLoading.value = false
  }
}

async function updatePolicy(row, fields) {
  const key = `${row.algorithm_id}:policy`
  agentToolSaving.value = key
  try {
    const updated = await updateAgentToolPolicy(row.algorithm_id, fields)
    const index = agentToolItems.value.findIndex((item) => item.algorithm_id === row.algorithm_id)
    if (index >= 0) agentToolItems.value.splice(index, 1, updated)
    ElMessage.success('工具策略已更新')
  } catch (error) {
    ElMessage.error(`策略更新失败：${getApiErrorMessage(error)}`)
  } finally {
    agentToolSaving.value = ''
  }
}

async function runAgentToolSync() {
  syncingAgentTools.value = true
  try {
    const data = await syncAgentTools()
    ElMessage.success(`一致性检查完成：可用 ${data.available}，不可用 ${data.unavailable}，禁用 ${data.disabled}`)
    await loadAgentToolItems()
  } catch (error) {
    ElMessage.error(`一致性检查失败：${getApiErrorMessage(error)}`)
  } finally {
    syncingAgentTools.value = false
  }
}

// ── Agent 连接器（受控外部 Agent 执行）──
const agentConnectors = ref([])
const agentConnectorLoading = ref(false)
const agentConnectorError = ref('')
const agentConnectorQuality = ref(null)
const agentConnectorSaving = ref('')
const agentConnectorPolicyForms = ref({})
const testRunVisible = ref(false)
const testRunCard = ref(null)
const testRunLoading = ref(false)
const testRunResult = ref(null)
const testRunForm = reactive({
  prompt: '',
  timeoutSeconds: 60,
  confirmed: false,
})

const connectorQualityText = computed(() => formatQualitySummary(agentConnectorQuality.value))

const agentConnectorAttributions = [
  {
    key: 'codex-cli',
    name: 'Codex CLI',
    organization: 'OpenAI',
    role: 'implementation_source',
    visibility: 'prominent',
    url: 'https://github.com/openai/codex',
  },
]

async function loadAgentConnectors() {
  if (!isAdmin.value) return
  agentConnectorLoading.value = true
  agentConnectorError.value = ''
  try {
    const [providers, quality] = await Promise.allSettled([
      getAgentExecProviders(),
      getAgentExecQuality(),
    ])
    if (providers.status === 'fulfilled') {
      agentConnectors.value = providers.value || []
      agentConnectorPolicyForms.value = Object.fromEntries(
        agentConnectors.value.map((card) => [card.provider_id, normalizePolicyForm(card)]),
      )
    } else {
      agentConnectors.value = []
      agentConnectorError.value = `连接器目录加载失败：${getApiErrorMessage(providers.reason)}`
    }
    agentConnectorQuality.value = quality.status === 'fulfilled' ? quality.value : null
  } finally {
    agentConnectorLoading.value = false
  }
}

async function saveConnectorPolicy(card) {
  const form = agentConnectorPolicyForms.value[card.provider_id]
  if (!form) return
  agentConnectorSaving.value = `${card.provider_id}:policy`
  try {
    const updated = await updateAgentExecPolicy(card.provider_id, buildPolicyPayload(form))
    const index = agentConnectors.value.findIndex((item) => item.provider_id === card.provider_id)
    if (index >= 0) agentConnectors.value.splice(index, 1, { ...card, policy: updated })
    agentConnectorPolicyForms.value = {
      ...agentConnectorPolicyForms.value,
      [card.provider_id]: normalizePolicyForm({ ...card, policy: updated }),
    }
    ElMessage.success('连接器策略已更新')
  } catch (error) {
    ElMessage.error(`策略更新失败：${getApiErrorMessage(error)}`)
  } finally {
    agentConnectorSaving.value = ''
  }
}

function openTestRun(card) {
  testRunCard.value = card
  testRunResult.value = null
  testRunForm.prompt = ''
  testRunForm.timeoutSeconds = 60
  testRunForm.confirmed = false
  testRunVisible.value = true
}

async function submitTestRun() {
  if (!testRunCard.value) return
  testRunLoading.value = true
  try {
    const payload = buildTestRunPayload({
      providerId: testRunCard.value.provider_id,
      prompt: testRunForm.prompt,
      timeoutSeconds: testRunForm.timeoutSeconds,
      confirmed: testRunForm.confirmed,
    })
    testRunResult.value = await createAgentExecRun(payload)
    ElMessage.success(`测试 run 已结束：${testRunResult.value.status}`)
  } catch (error) {
    ElMessage.error(`测试 run 失败：${getApiErrorMessage(error)}`)
  } finally {
    testRunLoading.value = false
  }
}

async function showAlgoDetail(algo) {
  try {
    algoDetail.value = await getAlgorithm(algo.algorithm_id)
    algoDetailVisible.value = true
  } catch (error) {
    ElMessage.error(getApiErrorMessage(error))
  }
}

const form = reactive({
  display_name: '',
  service_type: 'workflow',
  enabled: false,
  endpoint: '',
  config_summary: '{}',
  secret_refs: '{}',
})

const serviceTypeOptions = [
  'experiment',
  'provenance',
  'workflow',
  'worker',
  'artifact',
  'optimizer',
  'knowledge',
]

const currentConfig = computed(() => configs.value.find((item) => item.service_key === editingServiceKey.value))

const serviceCatalog = {
  mongodb: { name: 'MongoDB', group: '核心存储', hint: 'Poly Agent 主数据库连接状态' },
  'data-asset-mongodb': { name: '数据资产 MongoDB', group: '核心存储', hint: '只读材料数据资产库接入状态' },
  sqlite: { name: 'SQLite', group: '核心存储', hint: '开发/测试环境本地文档存储' },
  'computation-worker': { name: '计算 Worker', group: '运行组件', hint: '领取 queued run 并执行真实计算 workflow' },
  'artifact-store': { name: 'Artifact 存储', group: '核心存储', hint: '保存结构、日志、结果 JSON 和下载文件' },
  weknora: { name: 'WeKnora', group: '知识服务', hint: '知识库管理、检索问答和引用证据状态' },
  'knowledge-graph': { name: 'Knowledge Graph', group: '知识服务', hint: '基于 WeKnora 检索结果的子图能力状态' },
  rdkit: { name: 'RDKit', group: '计算工具链', hint: 'SMILES 解析和三维结构初猜' },
  openbabel: { name: 'OpenBabel', group: '计算工具链', hint: '结构格式转换和备用三维结构生成' },
  xtb: { name: 'xTB', group: '计算工具链', hint: '低成本粗优化和单点计算' },
  crest: { name: 'CREST', group: '计算工具链', hint: '构象搜索，给 xTB/ORCA 提供合理姿态' },
  orca: { name: 'ORCA', group: '计算工具链', hint: '高精度 DFT/激发态精加工' },
  'alchemist-backend': { name: 'Alchemist', group: '优化与实验', hint: '贝叶斯优化和实验设计后端' },
  speclabos: { name: 'SpecLabOS', group: '优化与实验', hint: '真实实验系统接口，需配置 endpoint' },
  docker: { name: 'Docker', group: '运行组件', hint: '可选容器运行能力' },
}

const serviceGroupMeta = {
  核心存储: { tone: 'blue', description: '数据库、数据资产与结果文件存储' },
  知识服务: { tone: 'teal', description: 'WeKnora 知识库检索与证据服务' },
  计算工具链: { tone: 'amber', description: '结构处理、构象搜索与量子化学计算' },
  优化与实验: { tone: 'coral', description: '主动学习、实验设计与外部实验系统' },
  运行组件: { tone: 'violet', description: '任务执行和可选运行环境' },
}

const serviceGroups = computed(() => {
  const groups = ['核心存储', '知识服务', '计算工具链', '优化与实验', '运行组件']
  return groups.map((group) => ({
    name: group,
    ...(serviceGroupMeta[group] || { tone: 'slate', description: '平台运行服务' }),
    items: services.value.filter((item) => (serviceCatalog[item.service]?.group || '运行组件') === group),
  })).filter((group) => group.items.length)
})

const visibleServiceGroups = computed(() => serviceGroupFilter.value === 'all'
  ? serviceGroups.value
  : serviceGroups.value.filter((group) => group.name === serviceGroupFilter.value))

const serviceStatusByKey = computed(() => Object.fromEntries(
  services.value.map((item) => [item.service, item]),
))

const CORE_SERVICE_IDS = ['sqlite', 'mongodb', 'artifact-store', 'weknora', 'computation-worker']
const ACTIVE_STORAGE_SERVICE_IDS = ['sqlite', 'mongodb']
const TOOLCHAIN_SERVICE_IDS = ['rdkit', 'openbabel', 'xtb', 'crest', 'orca']

function isReadyStatus(status) {
  return ['up', 'available', 'built_in'].includes(status)
}

const healthSummary = computed(() => {
  const items = services.value.filter((item) => CORE_SERVICE_IDS.includes(item.service))
  const storageItems = items.filter((item) => ACTIVE_STORAGE_SERVICE_IDS.includes(item.service))
  const otherItems = items.filter((item) => !ACTIVE_STORAGE_SERVICE_IDS.includes(item.service))
  const storageReady = storageItems.some((item) => isReadyStatus(item.status))
  const otherReady = otherItems.filter((item) => isReadyStatus(item.status)).length
  return { ready: otherReady + (storageReady ? 1 : 0), total: otherItems.length + 1 }
})

const serviceHealthStats = computed(() => {
  const issueStatuses = new Set(['degraded', 'down', 'failed'])
  const setupStatuses = new Set(['not_configured', 'disabled', 'not_available'])
  const toolchainItems = services.value.filter((item) => TOOLCHAIN_SERVICE_IDS.includes(item.service))
  const toolchainReady = toolchainItems.filter((item) => isReadyStatus(item.status)).length
  const issues = services.value.filter((item) => issueStatuses.has(item.status)).length
  const setupRequired = services.value.filter((item) => (
    setupStatuses.has(item.status) && !TOOLCHAIN_SERVICE_IDS.includes(item.service)
  )).length
  const coreReady = healthSummary.value.total > 0 && healthSummary.value.ready === healthSummary.value.total
  return [
    { label: '核心服务', value: `${healthSummary.value.ready}/${healthSummary.value.total}`, hint: '数据库 / 知识库 / worker', tone: coreReady ? 'success' : 'warning', icon: DataAnalysis },
    { label: '计算工具链', value: `${toolchainReady}/${toolchainItems.length}`, hint: 'RDKit / xTB / ORCA', tone: toolchainReady === toolchainItems.length ? 'success' : 'warning', icon: Files },
    { label: '异常服务', value: String(issues), hint: '需排查', tone: issues ? 'danger' : 'neutral', icon: Warning },
    { label: '待接入', value: String(setupRequired), hint: '外部 / 可选服务', tone: setupRequired ? 'warning' : 'neutral', icon: SetUp },
  ]
})

const llmModelOptions = computed(() => {
  const rows = []
  for (const provider of llmCatalog.value.providers || []) {
    for (const model of provider.models || []) {
      rows.push({
        key: `${provider.provider_id}::${model.model_id}`,
        providerId: provider.provider_id,
        providerName: provider.display_name || provider.provider_id,
        modelId: model.model_id,
        label: model.display_name || model.model_id,
        capabilities: model.capabilities || [],
        status: provider.status,
      })
    }
  }
  return rows
})

const llmProviderStats = computed(() => {
  const providers = llmCatalog.value.providers || []
  const available = providers.filter((item) => item.status === 'available').length
  const unprobed = providers.filter((item) => item.status === 'unknown').length
  const models = providers.reduce((sum, item) => sum + (item.models?.length || 0), 0)
  const reasoning = llmModelOptions.value.filter((item) => item.capabilities.includes('reasoning')).length
  return [
    { label: 'Provider', value: String(providers.length), hint: '已登记' },
    { label: '模型', value: String(models), hint: '可选择' },
    { label: '推理模型', value: String(reasoning), hint: 'deep 路由' },
    { label: '已探测可用', value: String(available), hint: `${unprobed} 未探测` },
  ]
})

function statusTag(status) {
  if (['up', 'available', 'built_in'].includes(status)) return 'success'
  if (['degraded', 'not_configured', 'disabled', 'not_available'].includes(status)) return 'warning'
  if (['down', 'failed'].includes(status)) return 'danger'
  return 'info'
}

function statusTone(status) {
  if (['up', 'available', 'built_in'].includes(status)) return 'success'
  if (['degraded', 'not_configured', 'disabled', 'not_available'].includes(status)) return 'warning'
  if (['down', 'failed'].includes(status)) return 'danger'
  return 'neutral'
}

function formatDate(value) {
  if (!value) return '-'
  const date = new Date(value)
  if (Number.isNaN(date.getTime())) return value
  return date.toLocaleString()
}

function formatDetails(details) {
  if (!details || Object.keys(details).length === 0) return '{}'
  return JSON.stringify(details, null, 2)
}

function serviceName(service) {
  return serviceCatalog[service]?.name || service
}

function serviceHint(service) {
  return serviceCatalog[service]?.hint || '外部集成服务'
}

function statusLabel(status) {
  const map = {
    up: '可用',
    available: '可用',
    degraded: '异常',
    down: '不可用',
    failed: '失败',
    not_available: '未安装',
    not_configured: '未配置',
    disabled: '已停用',
    built_in: '内置',
    unknown: '未知',
  }
  return map[status] || status
}

function llmStatusLabel(status) {
  if (status === 'unknown') return '未探测'
  return statusLabel(status)
}

function llmStatusNote(provider) {
  const map = {
    available: '远端模型列表已确认',
    unknown: '已登记，尚未执行连通性探测',
    not_configured: '缺少模型列表或本地服务配置',
    down: '探测失败',
    degraded: '部分能力异常',
  }
  return map[provider?.status] || statusLabel(provider?.status)
}

function llmCapabilityLabel(capability) {
  const map = {
    chat: '聊天',
    fast: '快速',
    reasoning: '推理',
    long_context: '长上下文',
    structured_json: 'JSON',
    tool_calling: '工具调用',
    local: '本地',
  }
  return map[capability] || capability
}

function llmCapabilityTag(capability) {
  if (capability === 'reasoning') return 'success'
  if (capability === 'fast') return 'primary'
  if (capability === 'long_context') return 'warning'
  return 'info'
}

function formatSchemaDefault(value) {
  if (value === null || value === undefined) return 'null'
  if (typeof value === 'string') return value
  return JSON.stringify(value)
}

function formatSchemaConstraints(constraints = {}) {
  const entries = Object.entries(constraints || {})
  if (!entries.length) return '-'
  return entries.map(([key, value]) => `${key}=${JSON.stringify(value)}`).join('；')
}

function qualityMetricType(metric) {
  const key = metric?.key || ''
  if (['tool_run_failure', 'tool_proposal_validation_failure', 'unsupported_model_fallback'].includes(key)) return 'danger'
  if (['route_resolved_rate', 'continuation_success'].includes(key)) return 'success'
  if (['confirmation_conversion', 'tool_capable_model_usage', 'tool_proposal_rate'].includes(key)) return 'primary'
  return 'info'
}

function servicePrimaryDetail(row) {
  const details = row.details || {}
  if (details.path) return details.path
  if (details.url) return details.url
  if (details.root) return details.root
  if (details.host && details.port) return `${details.host}:${details.port}`
  if (details.worker_id) return details.worker_id
  if (details.database) return details.database
  return '-'
}

function serviceReason(row) {
  const details = row.details || {}
  return details.reason || details.last_error_summary || details.stderr || ''
}

function serviceStatusNote(row) {
  return serviceReason(row) || (['up', 'available', 'built_in'].includes(row.status) ? '运行正常' : statusLabel(row.status))
}

function serviceVersion(row) {
  return row.details?.version || row.details?.message || '-'
}

function configRuntime(row) {
  return serviceStatusByKey.value[row.service_key] || null
}

function configDisplayStatus(row) {
  return configRuntime(row)?.status || row.last_status
}

function configStatusSource(row) {
  const runtime = configRuntime(row)
  if (runtime) return `实时检查 ${formatDate(runtime.checked_at)}`
  return `配置检查 ${formatDate(row.last_checked_at)}`
}

function configSummaryText(row) {
  const summary = compactConfigSummary(row)
  if (summary !== '-') return summary
  const runtime = configRuntime(row)
  if (runtime && ['up', 'available', 'built_in'].includes(runtime.status)) {
    return '运行状态来自环境变量或内置能力'
  }
  return '未保存手动配置'
}

function configSecondaryText(row) {
  const parts = [`手动配置：${row.enabled ? '已启用' : '未启用'}`]
  if (row.last_checked_at) {
    parts.push(`配置检查 ${statusLabel(row.last_status)}`)
  }
  return parts.join(' · ')
}

function showServiceDetail(row) {
  selectedServiceStatus.value = row
  statusDetailVisible.value = true
}

function formatConfigSummary(row) {
  const parts = []
  if (row.endpoint) parts.push(row.endpoint)
  if (row.config_summary && Object.keys(row.config_summary).length) parts.push(JSON.stringify(row.config_summary))
  if (row.secret_refs && Object.keys(row.secret_refs).length) parts.push(`secrets:${Object.keys(row.secret_refs).join(',')}`)
  return parts.join('\n') || '-'
}

function compactConfigSummary(row) {
  return formatConfigSummary(row).replace(/\s+/g, ' ')
}

function maskedSecretRefs(refs = {}) {
  return Object.fromEntries(Object.keys(refs || {}).map((key) => [key, 'configured reference']))
}

function routeKeyFromValue(value) {
  if (!value?.provider_id || !value?.model_id) return ''
  return `${value.provider_id}::${value.model_id}`
}

function routeValueFromKey(key) {
  const [providerId, ...modelParts] = String(key || '').split('::')
  const modelId = modelParts.join('::')
  if (!providerId || !modelId) return null
  return { provider_id: providerId, model_id: modelId }
}

function syncLlmRouteForm() {
  llmRouteForm.qa = routeKeyFromValue(llmCatalog.value.routing?.qa)
  llmRouteForm.deep = routeKeyFromValue(llmCatalog.value.routing?.deep)
  llmRouteForm.report = routeKeyFromValue(llmCatalog.value.routing?.report)
}

function parseJsonObject(value, label) {
  const text = String(value || '').trim()
  if (!text) return {}
  let parsed
  try {
    parsed = JSON.parse(text)
  } catch {
    throw new Error(`${label} 必须是 JSON object`)
  }
  if (!parsed || Array.isArray(parsed) || typeof parsed !== 'object') {
    throw new Error(`${label} 必须是 JSON object`)
  }
  return parsed
}

async function loadStatus() {
  loadingStatus.value = true
  try {
    const data = await getIntegrationStatus()
    services.value = data.items || []
  } catch (error) {
    ElMessage.error(getApiErrorMessage(error))
  } finally {
    loadingStatus.value = false
  }
}

async function loadConfigs({ quiet = false } = {}) {
  loadingConfigs.value = true
  configError.value = ''
  try {
    const data = await listIntegrationConfigs()
    configs.value = data.items || []
  } catch (error) {
    configError.value = getApiErrorMessage(error)
    if (!quiet) ElMessage.error(configError.value)
  } finally {
    loadingConfigs.value = false
  }
}

async function loadAll() {
  await Promise.all([loadStatus(), loadConfigs({ quiet: true })])
}

async function loadLlmModels({ quiet = false } = {}) {
  loadingLlm.value = true
  llmError.value = ''
  try {
    llmCatalog.value = await getLlmModels()
    syncLlmRouteForm()
  } catch (error) {
    llmError.value = getApiErrorMessage(error)
    if (!quiet) ElMessage.error(llmError.value)
  } finally {
    loadingLlm.value = false
  }
}

async function loadLlmExtras({ quiet = false } = {}) {
  loadingLlmExtras.value = true
  llmExtrasError.value = ''
  try {
    const requests = [getLlmConfigSchema()]
    if (isAdmin.value) requests.push(getAssistantQualityMetrics())
    const [schema, quality] = await Promise.all(requests)
    llmConfigSchema.value = schema || { provider_fields: [], per_model_fields: [] }
    llmQualityMetrics.value = quality || null
  } catch (error) {
    llmExtrasError.value = getApiErrorMessage(error)
    if (!quiet) ElMessage.error(llmExtrasError.value)
  } finally {
    loadingLlmExtras.value = false
  }
}

async function refreshLlmModels() {
  loadingLlm.value = true
  llmError.value = ''
  try {
    llmCatalog.value = await checkLlmModels()
    syncLlmRouteForm()
    ElMessage.success('LLM 模型状态已刷新')
    await loadLlmExtras({ quiet: true })
  } catch (error) {
    llmError.value = getApiErrorMessage(error)
    ElMessage.error(llmError.value)
  } finally {
    loadingLlm.value = false
  }
}

async function saveLlmRouting() {
  savingLlmRouting.value = true
  try {
    const payload = {
      qa: routeValueFromKey(llmRouteForm.qa),
      deep: routeValueFromKey(llmRouteForm.deep),
      report: routeValueFromKey(llmRouteForm.report),
    }
    await updateLlmRouting(payload)
    ElMessage.success('LLM 默认路由已保存')
    await loadLlmModels({ quiet: true })
  } catch (error) {
    ElMessage.error(getApiErrorMessage(error))
  } finally {
    savingLlmRouting.value = false
  }
}

function openEdit(row) {
  editingServiceKey.value = row.service_key
  form.display_name = row.display_name || ''
  form.service_type = row.service_type || 'workflow'
  form.enabled = Boolean(row.enabled)
  form.endpoint = row.endpoint || ''
  form.config_summary = JSON.stringify(row.config_summary || {}, null, 2)
  form.secret_refs = JSON.stringify(row.secret_refs || {}, null, 2)
  editVisible.value = true
}

function showConfigDetail(row) {
  selectedConfig.value = row
  configDetailVisible.value = true
}

async function saveConfig() {
  if (!editingServiceKey.value) return
  saving.value = true
  try {
    const configSummary = parseJsonObject(form.config_summary, 'Config summary')
    const secretRefs = parseJsonObject(form.secret_refs, 'Secret refs')
    await upsertIntegrationConfig(editingServiceKey.value, {
      display_name: form.display_name,
      service_type: form.service_type,
      enabled: form.enabled,
      endpoint: form.endpoint || null,
      config_summary: configSummary,
      secret_refs: secretRefs,
    })
    ElMessage.success('配置已保存')
    editVisible.value = false
    await Promise.all([loadConfigs(), loadStatus()])
  } catch (error) {
    ElMessage.error(getApiErrorMessage(error) || error.message)
  } finally {
    saving.value = false
  }
}

async function toggleEnabled(row, enabled) {
  actionLoading.value = `${row.service_key}:toggle`
  try {
    await upsertIntegrationConfig(row.service_key, {
      display_name: row.display_name,
      service_type: row.service_type,
      enabled,
      endpoint: row.endpoint,
      config_summary: row.config_summary || {},
      secret_refs: row.secret_refs || {},
    })
    await Promise.all([loadConfigs(), loadStatus()])
  } catch (error) {
    ElMessage.error(getApiErrorMessage(error))
    await loadConfigs({ quiet: true })
  } finally {
    actionLoading.value = ''
  }
}

async function handleCheck(row) {
  actionLoading.value = `${row.service_key}:check`
  try {
    const data = await checkIntegrationConfig(row.service_key)
    ElMessage.success(`${row.display_name}: ${data.status}`)
    await Promise.all([loadConfigs(), loadStatus()])
  } catch (error) {
    ElMessage.error(getApiErrorMessage(error))
  } finally {
    actionLoading.value = ''
  }
}

onMounted(() => {
  loadAll()
  loadAlgos()
  loadAgentToolItems()
  loadAgentConnectors()
  loadLlmModels({ quiet: true })
  loadLlmExtras({ quiet: true })
})

watch(
  () => route.query.tab,
  (tab) => {
    activeTab.value = normalizeTab(tab)
  },
)

watch(activeTab, (tab) => {
  const query = { ...route.query }
  if (tab === 'status') delete query.tab
  else query.tab = tab
  if (JSON.stringify(query) !== JSON.stringify(route.query)) router.replace({ query })
  if (tab === 'agent-connectors' && !agentConnectorLoading.value) loadAgentConnectors()
})
</script>

<template>
  <div class="tools-view">
    <header class="tools-page-header">
      <div>
        <h1>工具服务</h1>
        <p>真实计算工具链、Mongo/artifact、SpecLabOS 和优化服务状态。</p>
      </div>
      <div class="header-actions">
        <el-tag size="large" :type="healthSummary.total > 0 && healthSummary.ready === healthSummary.total ? 'success' : 'warning'">
          核心服务 {{ healthSummary.ready }}/{{ healthSummary.total }}
        </el-tag>
        <el-button :icon="Refresh" :loading="loadingStatus || loadingConfigs" @click="loadAll">刷新</el-button>
      </div>
    </header>

    <AttributionBanner module-id="computation" label="工具支持" compact />

    <section class="metric-grid" aria-label="工具服务关键指标">
      <article v-for="stat in serviceHealthStats" :key="stat.label" class="metric-panel" :class="`metric-panel--${stat.tone}`">
        <el-icon><component :is="stat.icon" /></el-icon>
        <div>
          <span>{{ stat.label }}</span>
          <strong>{{ stat.value }}</strong>
          <small>{{ stat.hint }}</small>
        </div>
      </article>
    </section>

    <el-tabs v-model="activeTab" class="tools-tabs">
      <el-tab-pane label="状态" name="status">
        <section class="tools-section" v-loading="loadingStatus">
          <div class="section-heading">
            <div>
              <h2>服务状态</h2>
              <p class="section-description">按服务类型分组查看位置、版本和异常原因。</p>
            </div>
            <span>{{ services.length }} 项服务</span>
          </div>
          <div class="tools-browser-layout">
            <nav class="tools-rail" aria-label="服务分类">
              <div class="tools-rail-label">服务分类</div>
              <button type="button" class="tools-filter" :class="{ active: serviceGroupFilter === 'all' }" @click="serviceGroupFilter = 'all'">
                <span>全部服务</span><strong>{{ services.length }}</strong>
              </button>
              <button
                v-for="group in serviceGroups"
                :key="group.name"
                type="button"
                class="tools-filter"
                :class="[`tone-${group.tone}`, { active: serviceGroupFilter === group.name }]"
                @click="serviceGroupFilter = group.name"
              >
                <span>{{ group.name }}</span><strong>{{ group.items.length }}</strong>
              </button>
            </nav>

            <div class="tools-group-stack">
              <section v-for="group in visibleServiceGroups" :key="group.name" class="tools-group" :class="`tone-${group.tone}`">
                <header class="tools-group-header">
                  <div class="tools-group-title">
                    <span class="tools-group-marker" aria-hidden="true"></span>
                    <div><h3>{{ group.name }}</h3><p>{{ group.description }}</p></div>
                  </div>
                  <span class="tools-group-count">{{ group.items.length }} 项</span>
                </header>
                <div class="service-list" role="list">
                  <article v-for="row in group.items" :key="row.service" class="service-list-row" role="listitem">
                    <div class="service-list-main">
                      <strong>{{ serviceName(row.service) }}</strong>
                      <small>{{ serviceHint(row.service) }}</small>
                    </div>
                    <div class="service-list-status">
                      <el-tag size="small" :type="statusTag(row.status)">{{ statusLabel(row.status) }}</el-tag>
                      <small>{{ serviceStatusNote(row) }}</small>
                    </div>
                    <div class="service-list-fact">
                      <strong>{{ servicePrimaryDetail(row) }}</strong>
                      <small>位置</small>
                    </div>
                    <div class="service-list-fact">
                      <strong>{{ serviceVersion(row) }}</strong>
                      <small>版本 / 信息</small>
                    </div>
                    <el-button text type="primary" size="small" :icon="ViewIcon" @click="showServiceDetail(row)">详情</el-button>
                  </article>
                </div>
              </section>
              <el-empty v-if="!visibleServiceGroups.length && !loadingStatus" description="暂无服务数据" />
            </div>
          </div>
        </section>
      </el-tab-pane>

      <el-tab-pane label="算法清单" name="algorithms">
        <section class="tools-section">
          <div class="section-heading">
            <div><h2>算法清单</h2><p class="section-description">按接入类型浏览算法、调用方式和适用材料范围。</p></div>
            <span>{{ filteredAlgos.length }} 项算法</span>
          </div>
          <div class="algo-filter-bar">
            <el-select v-model="algoFilters.type" placeholder="算法类型" clearable style="width:130px">
              <el-option v-for="item in algoTypeOptions" :key="item.value" :label="item.label" :value="item.value" />
            </el-select>
            <el-select v-model="algoFilters.material_scope" placeholder="材料体系" clearable style="width:130px">
              <el-option label="氟基" value="fluoropolymer" /><el-option label="碳基" value="carbon_polymer" /><el-option label="硅基" value="silicon_polymer" /><el-option label="通用" value="universal" />
            </el-select>
            <el-input v-model="algoFilters.keyword" placeholder="搜索算法" clearable style="width:220px" />
            <el-button text @click="algoFilters.type = ''; algoFilters.material_scope = ''; algoFilters.keyword = ''">重置</el-button>
            <el-button :icon="Refresh" :loading="algoLoading" @click="loadAlgos">刷新</el-button>
          </div>
          <div class="algo-summary-strip" aria-label="算法接入概览">
            <span v-for="stat in algorithmStats" :key="stat.key"><strong>{{ stat.count }}</strong>{{ stat.label }}</span>
          </div>
          <div v-if="filteredAlgos.length" v-loading="algoLoading" class="algo-group-stack">
            <section v-for="group in groupedAlgos.filter((item) => item.items.length)" :key="group.key" class="tools-group" :class="`tone-${group.tone}`">
              <header class="tools-group-header"><div class="tools-group-title"><span class="tools-group-marker" aria-hidden="true"></span><div><h3>{{ group.label }}</h3><p>{{ group.hint }}</p></div></div><span class="tools-group-count">{{ group.items.length }} 项</span></header>
              <div class="algo-list" role="list">
                <article v-for="row in group.items" :key="row.algorithm_id" class="algo-list-row" role="listitem">
                  <div class="algo-list-main"><strong>{{ row.name }}</strong><small>{{ row.algorithm_id }}</small><p>{{ row.description || '暂无描述' }}</p><div class="compact-tag-list"><el-tag size="small" :type="algoTypeTag(row.type)">{{ algoTypeLabel(row.type) }}</el-tag><el-tag v-for="item in materialScopeLabel(row.material_scope)" :key="item" size="small" effect="plain">{{ item }}</el-tag></div></div>
                  <div class="algo-list-status"><el-tag size="small" :type="algoIntegrationTag(algoIntegrationKind(row))" effect="plain">{{ algoIntegrationLabel(algoIntegrationKind(row)) }}</el-tag><el-tag size="small" :type="algoStatusTag(row.status)" effect="plain">{{ algoStatusLabel(row.status) }}</el-tag><small>{{ row.call_method || '未标注调用方式' }}</small></div>
                  <div class="algo-list-meta"><span>触发方式</span><div class="compact-tag-list"><el-tag v-for="item in triggerModeLabel(row.trigger_modes)" :key="item" size="small" effect="plain">{{ item }}</el-tag></div></div>
                  <el-button text type="primary" size="small" :icon="ViewIcon" @click="showAlgoDetail(row)">详情</el-button>
                </article>
              </div>
            </section>
          </div>
          <el-empty v-else-if="!algoLoading" description="暂无算法数据" />
        </section>
      </el-tab-pane>

      <el-tab-pane label="算法工具" name="agent-tools">
        <section class="tools-section">
          <div class="section-heading">
            <div>
              <h2>算法工具</h2>
              <p class="section-description">已部署垂类算法在对话 LUI 中的工具状态与调用策略。</p>
            </div>
            <span>{{ visibleAgentTools.length }} 项工具</span>
          </div>
          <div class="algo-filter-bar">
            <el-input v-model="agentToolFilter" placeholder="搜索算法工具" clearable style="width:240px" />
            <el-button :icon="Refresh" :loading="agentToolLoading" @click="loadAgentToolItems">刷新</el-button>
            <el-button v-if="isAdmin" :icon="Check" :loading="syncingAgentTools" @click="runAgentToolSync">
              一致性检查
            </el-button>
          </div>
          <div v-loading="agentToolLoading" class="agent-tool-panel">
            <el-table v-if="visibleAgentTools.length" :data="visibleAgentTools" class="agent-tool-table">
              <el-table-column label="工具" min-width="240">
                <template #default="{ row }">
                  <div class="agent-tool-main">
                    <strong>{{ row.name }}</strong>
                    <small>{{ row.tool_id }}</small>
                    <p>{{ row.description || '暂无描述' }}</p>
                    <AttributionBadges
                      v-if="row.framework_attributions?.length || row.method_attributions?.length || row.developer_attribution"
                      :attributions="[
                        ...(row.framework_attributions || []),
                        ...(row.method_attributions || []),
                        ...(row.developer_attribution ? [row.developer_attribution] : []),
                      ]"
                    />
                  </div>
                </template>
              </el-table-column>
              <el-table-column label="版本 / 健康" width="130">
                <template #default="{ row }">
                  <div class="agent-tool-main">
                    <strong>{{ row.version || '-' }}</strong>
                    <small>{{ agentToolHealthLabel(row.health_status) }}</small>
                  </div>
                </template>
              </el-table-column>
              <el-table-column label="可用状态" width="150">
                <template #default="{ row }">
                  <div class="agent-tool-main">
                    <el-tag size="small" :type="agentToolPhaseTag(row.phase)">{{ agentToolPhaseLabel(row.phase) }}</el-tag>
                    <small v-if="row.unavailable_reason" :title="row.unavailable_reason">{{ row.unavailable_reason }}</small>
                  </div>
                </template>
              </el-table-column>
              <template v-if="isAdmin">
                <el-table-column label="启用" width="86">
                  <template #default="{ row }">
                    <el-switch
                      :model-value="row.policy.enabled"
                      :disabled="row.phase === 'unavailable'"
                      :loading="agentToolSaving === `${row.algorithm_id}:policy`"
                      @change="(value) => updatePolicy(row, { enabled: value })"
                    />
                  </template>
                </el-table-column>
                <el-table-column label="允许角色" width="190">
                  <template #default="{ row }">
                    <el-select
                      :model-value="row.policy.allowed_roles"
                      multiple
                      size="small"
                      :disabled="row.phase === 'unavailable'"
                      @change="(value) => updatePolicy(row, { allowed_roles: value })"
                    >
                      <el-option label="管理员" value="admin" />
                      <el-option label="用户" value="user" />
                    </el-select>
                  </template>
                </el-table-column>
                <el-table-column label="确认执行" width="110">
                  <template #default="{ row }">
                    <el-switch
                      :model-value="row.policy.requires_confirmation"
                      :disabled="row.phase === 'unavailable'"
                      @change="(value) => updatePolicy(row, { requires_confirmation: value })"
                    />
                  </template>
                </el-table-column>
              </template>
              <el-table-column label="输入 / 输出" min-width="210">
                <template #default="{ row }">
                  <div class="agent-tool-main">
                    <small>输入：{{ Object.keys(row.input_schema?.fields || {}).join(', ') || '-' }}</small>
                    <small>输出：{{ Object.keys(row.output_schema?.fields || {}).join(', ') || '-' }}</small>
                  </div>
                </template>
              </el-table-column>
            </el-table>
            <el-empty v-if="!visibleAgentTools.length && !agentToolLoading" description="暂无算法工具" />
          </div>
        </section>
      </el-tab-pane>

      <el-tab-pane v-if="isAdmin" label="Agent 连接器" name="agent-connectors">
        <section class="tools-section">
          <div class="section-heading">
            <div>
              <h2>Agent 连接器</h2>
              <p class="section-description">受控外部 Agent 文件任务：默认关闭、仅显式输入输出、强制确认执行；执行判定以后端为准。</p>
            </div>
            <span>最近成功率 {{ connectorQualityText.successRate }} · 平均耗时 {{ connectorQualityText.duration }}</span>
          </div>
          <el-alert
            v-if="agentConnectorError"
            :title="agentConnectorError"
            type="warning"
            :closable="false"
            class="connector-alert"
          />
          <div v-loading="agentConnectorLoading" class="connector-list">
            <article v-for="card in agentConnectors" :key="card.provider_id" class="connector-card">
              <header class="connector-card-head">
                <div>
                  <strong>{{ card.display_name }}</strong>
                  <small>{{ card.provider_id }}</small>
                </div>
                <el-tag :type="connectorStatus(card).tag">{{ connectorStatus(card).label }}</el-tag>
              </header>
              <p v-if="connectorStatus(card).reason" class="connector-reason">
                {{ connectorStatus(card).reason }}
              </p>
              <dl class="connector-meta">
                <div>
                  <dt>支持任务</dt>
                  <dd>{{ (card.supported_task_types || []).join('、') || '-' }}</dd>
                </div>
                <div>
                  <dt>Sandbox</dt>
                  <dd>{{ card.sandbox_summary || '-' }}</dd>
                </div>
                <div>
                  <dt>配置来源</dt>
                  <dd>{{ card.config_source || '-' }}</dd>
                </div>
              </dl>
              <AttributionBanner
                label="执行能力来自"
                :attributions="agentConnectorAttributions"
                compact
                embedded
              />
              <div class="connector-policy">
                <h4>调用策略</h4>
                <el-form label-width="92px" label-position="left" class="connector-policy-form">
                  <el-form-item label="启用">
                    <el-switch v-model="agentConnectorPolicyForms[card.provider_id].enabled" />
                  </el-form-item>
                  <el-form-item label="允许角色">
                    <el-select v-model="agentConnectorPolicyForms[card.provider_id].allowed_roles" multiple>
                      <el-option label="管理员" value="admin" />
                      <el-option label="用户" value="user" />
                    </el-select>
                  </el-form-item>
                  <el-form-item label="任务类型">
                    <el-select
                      v-model="agentConnectorPolicyForms[card.provider_id].allowed_task_types"
                      multiple
                    >
                      <el-option
                        v-for="taskType in card.supported_task_types || []"
                        :key="taskType"
                        :label="taskType"
                        :value="taskType"
                      />
                    </el-select>
                  </el-form-item>
                  <el-form-item label="强制确认">
                    <el-switch v-model="agentConnectorPolicyForms[card.provider_id].requires_confirmation" />
                  </el-form-item>
                </el-form>
                <div class="connector-actions">
                  <el-button
                    size="small"
                    type="primary"
                    :loading="agentConnectorSaving === `${card.provider_id}:policy`"
                    @click="saveConnectorPolicy(card)"
                  >
                    保存策略
                  </el-button>
                  <el-button size="small" :disabled="connectorStatus(card).kind !== 'ready'" @click="openTestRun(card)">
                    受控测试
                  </el-button>
                </div>
              </div>
            </article>
            <el-empty
              v-if="!agentConnectors.length && !agentConnectorLoading"
              description="暂无已注册连接器"
            />
          </div>
        </section>
      </el-tab-pane>

      <el-tab-pane label="配置" name="configs">
        <section class="tools-section">
          <div class="section-heading"><div><h2>服务配置</h2><p class="section-description">管理手动接入配置；运行状态以状态页实时检查为准。</p></div><span>{{ configs.length }} 项配置</span></div>
          <el-alert v-if="configError" :title="configError" type="warning" :closable="false" class="config-alert" />
          <div v-else v-loading="loadingConfigs" class="config-list">
            <article v-for="row in configs" :key="row.service_key" class="config-list-row">
              <div class="config-list-main"><strong>{{ row.display_name || row.service_key }}</strong><small>{{ row.service_key }} · {{ row.service_type }}</small></div>
              <div class="config-list-status"><el-tag size="small" :type="statusTag(configDisplayStatus(row))">{{ statusLabel(configDisplayStatus(row)) }}</el-tag><small>{{ configStatusSource(row) }}</small></div>
              <div class="config-list-summary"><span>{{ configSummaryText(row) }}</span><small>{{ row.last_error_summary || configSecondaryText(row) }}</small></div>
              <div class="config-list-enabled"><span>手动启用</span><el-switch :model-value="row.enabled" :loading="actionLoading === `${row.service_key}:toggle`" @change="(value) => toggleEnabled(row, value)" /></div>
              <div class="config-actions"><el-button text type="primary" size="small" :icon="Edit" @click="openEdit(row)">编辑</el-button><el-button text type="primary" size="small" :icon="Check" :loading="actionLoading === `${row.service_key}:check`" @click="handleCheck(row)">检查配置</el-button><el-button text type="primary" size="small" :icon="ViewIcon" @click="showConfigDetail(row)">详情</el-button></div>
            </article>
          </div>
        </section>
      </el-tab-pane>

      <el-tab-pane label="LLM 模型" name="llm-models">
        <section class="tools-section">
            <AttributionBanner module-id="llm" label="模型服务来自" compact />
            <div class="llm-toolbar">
              <div>
                <h4>LLM 模型选择</h4>
                <p>维护问答、深度思考和报告生成的默认模型路由。</p>
              </div>
              <div class="llm-toolbar-actions">
                <el-button :icon="Refresh" :loading="loadingLlm" @click="loadLlmModels">刷新列表</el-button>
                <el-button type="primary" plain :icon="Check" :loading="loadingLlm" @click="refreshLlmModels">探测模型</el-button>
              </div>
            </div>
            <el-alert v-if="llmError" :title="llmError" type="warning" :closable="false" class="config-alert" />
            <el-alert v-if="llmExtrasError" :title="llmExtrasError" type="warning" :closable="false" class="config-alert" />
            <div v-loading="loadingLlm" class="llm-model-panel">
              <div class="llm-stat-grid">
                <article v-for="stat in llmProviderStats" :key="stat.label" class="llm-stat">
                  <span>{{ stat.label }}</span>
                  <strong>{{ stat.value }}</strong>
                  <small>{{ stat.hint }}</small>
                </article>
              </div>

              <section v-if="llmQualityMetrics" v-loading="loadingLlmExtras" class="llm-routing-card">
                <div class="llm-routing-head">
                  <div>
                    <strong>LUI 调用质量</strong>
                    <span>路由、工具提案、执行与续答的成功率和失败阶段。</span>
                  </div>
                </div>
                <div class="llm-quality-metrics">
                  <el-table :data="llmQualityMetrics.metrics || []" size="small" border>
                    <el-table-column prop="label" label="指标" min-width="190" />
                    <el-table-column label="当前值" min-width="110" align="right">
                      <template #default="{ row }">
                        <el-tag size="small" :type="qualityMetricType(row)">{{ row.display }}</el-tag>
                      </template>
                    </el-table-column>
                    <el-table-column prop="numerator" label="分子" width="80" align="right" />
                    <el-table-column prop="denominator" label="分母" width="80" align="right" />
                    <el-table-column prop="target" label="目标" min-width="150" />
                  </el-table>
                </div>
                <div v-if="llmQualityMetrics.context_token_distribution?.sections?.length" class="llm-context-distribution">
                  <div class="llm-routing-head">
                    <div>
                      <strong>上下文 token 分布</strong>
                      <span>总计 {{ llmQualityMetrics.context_token_distribution.total_tokens }} tokens。</span>
                    </div>
                  </div>
                  <el-table :data="llmQualityMetrics.context_token_distribution.sections" size="small" border>
                    <el-table-column prop="name" label="Section" min-width="150" />
                    <el-table-column prop="source" label="来源" min-width="170" />
                    <el-table-column prop="count" label="次数" width="80" align="right" />
                    <el-table-column prop="token_total" label="Token 合计" width="110" align="right" />
                    <el-table-column prop="token_avg" label="平均" width="90" align="right" />
                    <el-table-column prop="token_max" label="最大" width="90" align="right" />
                    <el-table-column prop="omitted_count" label="省略次数" width="100" align="right" />
                  </el-table>
                </div>
                <p v-if="llmQualityMetrics.event_replay_errors" class="llm-quality-note">
                  事件重放异常：{{ llmQualityMetrics.event_replay_errors }}。
                </p>
              </section>

              <section v-loading="loadingLlmExtras" class="llm-routing-card">
                <div class="llm-routing-head">
                  <div>
                    <strong>配置字段说明</strong>
                    <span>字段类型、默认值、约束与错误路径由 Pydantic schema 生成。</span>
                  </div>
                </div>
                <div class="llm-schema-section">
                  <h5>Provider 字段</h5>
                  <el-table :data="llmConfigSchema.provider_fields || []" size="small" border>
                    <el-table-column prop="field_name" label="字段" min-width="180">
                      <template #default="{ row }">
                        <code>{{ row.field_name }}</code>
                      </template>
                    </el-table-column>
                    <el-table-column prop="description" label="说明" min-width="220" />
                    <el-table-column prop="type" label="类型" min-width="150" />
                    <el-table-column label="默认值" min-width="120">
                      <template #default="{ row }">
                        <code>{{ formatSchemaDefault(row.default_value) }}</code>
                      </template>
                    </el-table-column>
                    <el-table-column label="约束" min-width="190">
                      <template #default="{ row }">
                        <span>{{ formatSchemaConstraints(row.constraints) }}</span>
                      </template>
                    </el-table-column>
                    <el-table-column label="错误路径" min-width="230">
                      <template #default="{ row }">
                        <code>{{ row.error_path }}</code>
                      </template>
                    </el-table-column>
                  </el-table>
                </div>
                <div class="llm-schema-section">
                  <h5>Per-model 字段</h5>
                  <el-table :data="llmConfigSchema.per_model_fields || []" size="small" border>
                    <el-table-column prop="field_name" label="字段" min-width="180">
                      <template #default="{ row }">
                        <code>{{ row.field_name }}</code>
                      </template>
                    </el-table-column>
                    <el-table-column prop="description" label="说明" min-width="220" />
                    <el-table-column prop="type" label="类型" min-width="150" />
                    <el-table-column label="默认值" min-width="120">
                      <template #default="{ row }">
                        <code>{{ formatSchemaDefault(row.default_value) }}</code>
                      </template>
                    </el-table-column>
                    <el-table-column label="约束" min-width="190">
                      <template #default="{ row }">
                        <span>{{ formatSchemaConstraints(row.constraints) }}</span>
                      </template>
                    </el-table-column>
                    <el-table-column label="错误路径" min-width="250">
                      <template #default="{ row }">
                        <code>{{ row.error_path }}</code>
                      </template>
                    </el-table-column>
                  </el-table>
                </div>
              </section>

              <section class="llm-routing-card">
                <div class="llm-routing-head">
                  <div>
                    <strong>默认路由</strong>
                    <span>用户仍可在对话页临时切换当前会话模型。</span>
                  </div>
                  <el-button type="primary" :loading="savingLlmRouting" @click="saveLlmRouting">保存路由</el-button>
                </div>
                <div class="llm-routing-grid">
                  <el-form-item label="科研问答">
                    <el-select v-model="llmRouteForm.qa" placeholder="选择模型" style="width:100%">
                      <el-option v-for="item in llmModelOptions" :key="`qa-${item.key}`" :label="`${item.label} · ${item.providerName}`" :value="item.key" />
                    </el-select>
                  </el-form-item>
                  <el-form-item label="深度思考">
                    <el-select v-model="llmRouteForm.deep" placeholder="选择模型" style="width:100%">
                      <el-option v-for="item in llmModelOptions" :key="`deep-${item.key}`" :label="`${item.label} · ${item.providerName}`" :value="item.key">
                        <span>{{ item.label }} · {{ item.providerName }}</span>
                      </el-option>
                    </el-select>
                  </el-form-item>
                  <el-form-item label="报告生成">
                    <el-select v-model="llmRouteForm.report" placeholder="选择模型" style="width:100%">
                      <el-option v-for="item in llmModelOptions" :key="`report-${item.key}`" :label="`${item.label} · ${item.providerName}`" :value="item.key" />
                    </el-select>
                  </el-form-item>
                </div>
              </section>

              <div class="llm-provider-grid">
                <article v-for="provider in llmCatalog.providers || []" :key="provider.provider_id" class="llm-provider-card">
                  <div class="llm-provider-head">
                    <div>
                      <strong>{{ provider.display_name }}</strong>
                      <span>{{ provider.provider_id }} · {{ provider.provider_type }}</span>
                    </div>
                    <el-tag size="small" :type="statusTag(provider.status)">{{ llmStatusLabel(provider.status) }}</el-tag>
                  </div>
                  <dl class="llm-provider-meta">
                    <div>
                      <dt>Endpoint</dt>
                      <dd>{{ provider.base_url_label || (provider.base_url_configured ? '已配置' : '未配置') }}</dd>
                    </div>
                    <div>
                      <dt>Secret</dt>
                      <dd>{{ provider.api_key_configured ? (provider.api_key_ref || '已配置') : '未配置' }}</dd>
                    </div>
                  </dl>
                  <p class="llm-provider-note">{{ llmStatusNote(provider) }}</p>
                  <div class="llm-model-list">
                    <div v-for="model in provider.models || []" :key="model.model_id" class="llm-model-row">
                      <span>{{ model.display_name || model.model_id }}</span>
                      <div>
                        <el-tag
                          v-for="cap in model.capabilities || []"
                          :key="`${model.model_id}-${cap}`"
                          size="small"
                          :type="llmCapabilityTag(cap)"
                          effect="plain"
                        >
                          {{ llmCapabilityLabel(cap) }}
                        </el-tag>
                      </div>
                    </div>
                  </div>
                </article>
              </div>
              <el-empty v-if="!(llmCatalog.providers || []).length && !loadingLlm" description="暂无 LLM provider 配置" :image-size="80" />
            </div>
        </section>
      </el-tab-pane>
    </el-tabs>

    <el-dialog v-model="editVisible" :title="currentConfig?.display_name || editingServiceKey" width="680px">
      <el-form label-position="top">
        <div class="form-grid">
          <el-form-item label="名称">
            <el-input v-model="form.display_name" />
          </el-form-item>
          <el-form-item label="类型">
            <el-select v-model="form.service_type">
              <el-option v-for="item in serviceTypeOptions" :key="item" :label="item" :value="item" />
            </el-select>
          </el-form-item>
        </div>
        <el-form-item label="启用">
          <el-switch v-model="form.enabled" />
        </el-form-item>
        <el-form-item label="Endpoint">
          <el-input v-model="form.endpoint" placeholder="https://service.example/api" />
        </el-form-item>
        <el-form-item label="Config summary">
          <el-input v-model="form.config_summary" type="textarea" :rows="6" spellcheck="false" />
        </el-form-item>
        <el-form-item label="Secret refs">
          <el-input v-model="form.secret_refs" type="textarea" :rows="4" spellcheck="false" />
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="editVisible = false">取消</el-button>
        <el-button type="primary" :loading="saving" @click="saveConfig">保存</el-button>
      </template>
    </el-dialog>

    <el-dialog
      v-model="testRunVisible"
      :title="`受控测试：${testRunCard?.display_name || ''}`"
      width="560px"
    >
      <el-alert
        type="info"
        :closable="false"
        class="connector-alert"
        title="测试仍走服务端 policy 校验；请确认连接器、任务类型、输入清单、输出 Schema、超时与输出限制。"
      />
      <el-form label-position="top">
        <el-form-item label="任务说明">
          <el-input
            v-model="testRunForm.prompt"
            type="textarea"
            :rows="4"
            placeholder="例如：总结当前输入文件的主要结论"
          />
        </el-form-item>
        <el-form-item label="超时（秒）">
          <el-input-number v-model="testRunForm.timeoutSeconds" :min="1" :max="3600" />
        </el-form-item>
        <el-form-item>
          <el-checkbox v-model="testRunForm.confirmed">
            我已确认本次外部 Agent 文件任务的输入、输出和限制
          </el-checkbox>
        </el-form-item>
      </el-form>
      <el-descriptions v-if="testRunResult" :column="1" border size="small" class="connector-result">
        <el-descriptions-item label="Run ID">{{ testRunResult.run_id }}</el-descriptions-item>
        <el-descriptions-item label="状态">{{ testRunResult.status }}</el-descriptions-item>
        <el-descriptions-item label="错误">{{ testRunResult.error_code || '-' }}</el-descriptions-item>
      </el-descriptions>
      <template #footer>
        <el-button @click="testRunVisible = false">关闭</el-button>
        <el-button type="primary" :loading="testRunLoading" @click="submitTestRun">执行测试</el-button>
      </template>
    </el-dialog>

    <el-drawer v-model="configDetailVisible" :title="selectedConfig?.display_name || '配置详情'" size="520px">
      <template v-if="selectedConfig">
        <el-descriptions :column="1" border size="small">
          <el-descriptions-item label="Service">{{ selectedConfig.service_key }}</el-descriptions-item>
          <el-descriptions-item label="类型">{{ selectedConfig.service_type }}</el-descriptions-item>
          <el-descriptions-item label="启用">{{ selectedConfig.enabled ? '是' : '否' }}</el-descriptions-item>
          <el-descriptions-item label="Endpoint">{{ selectedConfig.endpoint || '-' }}</el-descriptions-item>
          <el-descriptions-item label="最后状态">{{ selectedConfig.last_status || '-' }}</el-descriptions-item>
          <el-descriptions-item label="最后检查">{{ formatDate(selectedConfig.last_checked_at) }}</el-descriptions-item>
          <el-descriptions-item label="错误">{{ selectedConfig.last_error_summary || '-' }}</el-descriptions-item>
        </el-descriptions>
        <h4 class="drawer-section-title">Config summary</h4>
        <pre class="details-json drawer-json">{{ JSON.stringify(selectedConfig.config_summary || {}, null, 2) }}</pre>
        <h4 class="drawer-section-title">Secret refs</h4>
        <pre class="details-json drawer-json">{{ JSON.stringify(maskedSecretRefs(selectedConfig.secret_refs), null, 2) }}</pre>
      </template>
    </el-drawer>

    <el-drawer v-model="statusDetailVisible" :title="selectedServiceStatus ? serviceName(selectedServiceStatus.service) : '服务详情'" size="520px">
      <template v-if="selectedServiceStatus">
        <el-descriptions :column="1" border size="small">
          <el-descriptions-item label="Service">{{ selectedServiceStatus.service }}</el-descriptions-item>
          <el-descriptions-item label="状态">
            <el-tag size="small" :type="statusTag(selectedServiceStatus.status)">
              {{ statusLabel(selectedServiceStatus.status) }}
            </el-tag>
          </el-descriptions-item>
          <el-descriptions-item label="位置">{{ servicePrimaryDetail(selectedServiceStatus) }}</el-descriptions-item>
          <el-descriptions-item label="版本 / 信息">{{ serviceVersion(selectedServiceStatus) }}</el-descriptions-item>
          <el-descriptions-item label="原因">{{ serviceReason(selectedServiceStatus) || '-' }}</el-descriptions-item>
        </el-descriptions>
        <h4 class="drawer-section-title">原始检查结果</h4>
        <pre class="details-json drawer-json">{{ formatDetails(selectedServiceStatus.details) }}</pre>
      </template>
    </el-drawer>

    <!-- 算法详情 drawer -->
    <el-drawer v-model="algoDetailVisible" :title="algoDetail?.name || '算法详情'" size="520px">
      <template v-if="algoDetail">
        <el-descriptions :column="2" border size="small">
          <el-descriptions-item label="ID">{{ algoDetail.algorithm_id }}</el-descriptions-item>
          <el-descriptions-item label="类型"><el-tag size="small" :type="algoTypeTag(algoDetail.type)">{{ algoTypeLabel(algoDetail.type) }}</el-tag></el-descriptions-item>
          <el-descriptions-item label="状态"><el-tag size="small" :type="algoStatusTag(algoDetail.status)">{{ algoStatusLabel(algoDetail.status) }}</el-tag></el-descriptions-item>
          <el-descriptions-item label="版本">{{ algoDetail.version }}</el-descriptions-item>
          <el-descriptions-item label="调用方式">{{ algoDetail.call_method }}</el-descriptions-item>
          <el-descriptions-item label="运行依赖">{{ algoDetail.runtime_dependency || '无' }}</el-descriptions-item>
          <el-descriptions-item label="触发方式">{{ (algoDetail.trigger_modes || []).join(', ') }}</el-descriptions-item>
          <el-descriptions-item label="材料范围">{{ (algoDetail.material_scope || []).join(', ') }}</el-descriptions-item>
        </el-descriptions>
        <h4 style="margin:16px 0 8px">输入 Schema</h4>
        <pre class="details-json" style="max-height:200px">{{ JSON.stringify(algoDetail.input_schema, null, 2) }}</pre>
        <h4 style="margin:16px 0 8px">输出 Schema</h4>
        <pre class="details-json" style="max-height:200px">{{ JSON.stringify(algoDetail.output_schema, null, 2) }}</pre>
      </template>
    </el-drawer>
  </div>
</template>

<style scoped>
.tools-view {
  display: flex;
  flex-direction: column;
  gap: 16px;
  min-height: calc(100vh - 96px);
}

.tools-page-header,
.section-heading,
.tools-group-title,
.service-list-row,
.algo-list-row,
.config-list-row {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 16px;
}

.tools-page-header h1,
.tools-section h2,
.tools-group-header h3 {
  margin: 0;
  color: var(--app-ink);
  letter-spacing: 0;
}

.tools-page-header h1 {
  font-size: 24px;
  line-height: 1.2;
}

.tools-page-header p,
.section-description,
.tools-group-header p {
  margin: 6px 0 0;
  color: var(--app-ink-muted);
  font-size: 13px;
}

.header-actions {
  display: flex;
  align-items: center;
  justify-content: flex-end;
  flex-wrap: wrap;
  gap: 8px;
}

.metric-grid {
  display: grid;
  grid-template-columns: repeat(4, minmax(0, 1fr));
  gap: 12px;
}

.metric-panel {
  position: relative;
  display: flex;
  align-items: center;
  gap: 12px;
  min-height: 86px;
  overflow: hidden;
  padding: 14px;
  border: 1px solid var(--app-card-border);
  border-radius: var(--app-radius-sm);
  background: rgba(255, 255, 255, 0.96);
  box-shadow: var(--app-card-shadow);
}

.metric-panel::before {
  content: "";
  position: absolute;
  inset: 0 auto 0 0;
  width: 3px;
  background: var(--app-primary);
}

.metric-panel--success::before { background: #22c55e; }
.metric-panel--warning::before { background: #f59e0b; }
.metric-panel--danger::before { background: #ef4444; }
.metric-panel .el-icon { width: 34px; height: 34px; border-radius: var(--app-radius-sm); color: var(--app-primary); background: var(--app-primary-light); }
.metric-panel span, .metric-panel small { display: block; color: var(--app-ink-muted); font-size: 12px; }
.metric-panel strong { display: block; margin: 3px 0; color: var(--app-ink); font-size: 22px; line-height: 1.1; }

.tools-tabs :deep(.el-tabs__header) { margin: 0 0 16px; }
.tools-tabs :deep(.el-tabs__nav-wrap::after) { background: var(--app-border-soft); }
.tools-tabs :deep(.el-tabs__item) { color: var(--app-ink-body); font-size: 14px; }
.tools-tabs :deep(.el-tabs__item.is-active) { color: var(--app-primary); font-weight: 600; }
.tools-tabs :deep(.el-tabs__active-bar) { height: 2px; }

.tools-section {
  min-width: 0;
  padding: 16px;
  border: 1px solid var(--app-card-border);
  border-radius: var(--app-radius-sm);
  background: rgba(255, 255, 255, 0.96);
  box-shadow: var(--app-card-shadow);
}

.tools-section h2 { font-size: 20px; }
.section-heading { align-items: center; margin-bottom: 14px; }
.section-heading > span { color: var(--app-ink-muted); font-size: 14px; white-space: nowrap; }

.tools-browser-layout { display: grid; grid-template-columns: 188px minmax(0, 1fr); gap: 18px; align-items: start; }
.tools-rail { position: sticky; top: 12px; display: flex; flex-direction: column; gap: 4px; padding-right: 14px; border-right: 1px solid var(--app-border-soft); }
.tools-rail-label { margin: 2px 10px 8px; color: var(--app-ink-subtle); font-size: 14px; font-weight: 700; letter-spacing: 0.08em; }
.tools-filter { display: flex; align-items: center; justify-content: space-between; width: 100%; min-height: 48px; padding: 10px 14px; border: 1px solid transparent; border-radius: var(--app-radius-sm); background: transparent; color: var(--app-ink-body); text-align: left; font-size: 15px; cursor: pointer; }
.tools-filter strong { min-width: 26px; color: var(--app-ink-subtle); font-size: 14px; font-weight: 600; text-align: right; }
.tools-filter:hover, .tools-filter.active { border-color: var(--app-border-soft); background: #f5f8fd; color: var(--app-sidebar-from); font-weight: 600; }
.tools-filter.active strong { color: var(--app-primary); }
.tools-filter.tone-blue.active { border-left: 3px solid #2563eb; }
.tools-filter.tone-teal.active { border-left: 3px solid #0f766e; }
.tools-filter.tone-amber.active { border-left: 3px solid #d97706; }
.tools-filter.tone-coral.active { border-left: 3px solid #be5a35; }
.tools-filter.tone-violet.active { border-left: 3px solid #7c3aed; }
.tools-group-stack, .algo-group-stack { display: flex; flex-direction: column; gap: 18px; min-width: 0; }
.tools-group { overflow: hidden; border: 1px solid var(--app-border-soft); border-left: 3px solid var(--app-border); border-radius: var(--app-radius-sm); background: #fff; }
.tools-group.tone-blue { border-left-color: #2563eb; }
.tools-group.tone-teal { border-left-color: #0f766e; }
.tools-group.tone-amber { border-left-color: #d97706; }
.tools-group.tone-coral { border-left-color: #be5a35; }
.tools-group.tone-violet { border-left-color: #7c3aed; }
.tools-group-header { display: flex; align-items: center; justify-content: space-between; gap: 12px; padding: 13px 15px 11px; border-bottom: 1px solid var(--app-border-soft); background: #fbfcfe; }
.tools-group-title { align-items: center; gap: 10px; min-width: 0; }
.tools-group-title > div { min-width: 0; }
.tools-group-title h3 { font-size: 18px; }
.tools-group-title p { margin-top: 3px; }
.tools-group-marker { width: 8px; height: 8px; flex: 0 0 auto; border-radius: 50%; background: var(--app-border); }
.tone-blue .tools-group-marker { background: #2563eb; }
.tone-teal .tools-group-marker { background: #0f766e; }
.tone-amber .tools-group-marker { background: #d97706; }
.tone-coral .tools-group-marker { background: #be5a35; }
.tone-violet .tools-group-marker { background: #7c3aed; }
.tools-group-count { color: var(--app-ink-muted); font-size: 14px; white-space: nowrap; }

.service-list, .algo-list, .config-list { display: flex; flex-direction: column; }
.service-list-row, .algo-list-row, .config-list-row { align-items: center; min-width: 0; padding: 14px 16px; border-bottom: 1px solid #eef2f7; background: #fff; }
.service-list-row:last-child, .algo-list-row:last-child, .config-list-row:last-child { border-bottom: 0; }
.service-list-row:hover, .algo-list-row:hover, .config-list-row:hover { background: #f7faff; }
.service-list-main, .algo-list-main, .config-list-main, .config-list-summary { min-width: 0; }
.service-list-main { flex: 1.8 1 240px; }
.service-list-status { flex: 0 0 130px; min-width: 0; }
.service-list-fact { flex: 0.9 1 150px; min-width: 0; }
.service-list-main strong, .algo-list-main > strong, .config-list-main strong { display: block; overflow: hidden; color: var(--app-ink); font-size: 16px; font-weight: 700; text-overflow: ellipsis; white-space: nowrap; }
.service-list-main small, .algo-list-main small, .config-list-main small, .service-list-status small, .service-list-fact small, .config-list-status small, .config-list-summary small, .config-list-enabled span { display: block; margin-top: 4px; color: var(--app-ink-muted); font-size: 12px; line-height: 1.45; }
.service-list-status small, .config-list-summary small { overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.service-list-fact strong { display: block; overflow: hidden; color: var(--app-sidebar-from); font-size: 14px; text-overflow: ellipsis; white-space: nowrap; }
.service-list-row > .el-button, .algo-list-row > .el-button { flex: 0 0 auto; }

.algo-filter-bar { display: flex; align-items: center; gap: 10px; flex-wrap: wrap; margin-bottom: 12px; }
.algo-summary-strip { display: flex; align-items: center; gap: 8px; flex-wrap: wrap; margin-bottom: 14px; }
.algo-summary-strip span { min-height: 30px; display: inline-flex; align-items: center; gap: 5px; padding: 5px 10px; border: 1px solid var(--app-border-soft); border-radius: var(--app-radius-sm); background: #fff; color: var(--app-ink-muted); font-size: 12px; }
.algo-summary-strip strong { color: var(--app-ink); font-size: 14px; }
.algo-list-row { align-items: center; }
.algo-list-main { flex: 1.8 1 280px; }
.algo-list-main p { display: -webkit-box; overflow: hidden; margin: 4px 0 7px; color: var(--app-ink-muted); font-size: 12px; line-height: 1.45; -webkit-box-orient: vertical; -webkit-line-clamp: 2; }
.algo-list-status { flex: 0 0 150px; min-width: 0; display: flex; flex-direction: column; align-items: flex-start; gap: 4px; }
.algo-list-meta { flex: 1 1 190px; min-width: 0; }
.algo-list-meta > span { display: block; margin-bottom: 5px; color: var(--app-ink-muted); font-size: 12px; }
.compact-tag-list { display: flex; align-items: center; flex-wrap: wrap; gap: 5px; }

.config-list-row { gap: 14px; }
.config-list-main { flex: 1.2 1 200px; }
.config-list-status { flex: 0 0 150px; min-width: 0; }
.config-list-summary { flex: 2 1 260px; }
.config-list-summary span { display: block; overflow: hidden; color: var(--app-ink-body); font-size: 13px; text-overflow: ellipsis; white-space: nowrap; }
.config-list-enabled { flex: 0 0 60px; text-align: center; }
.config-list-enabled span { margin-top: 0; margin-bottom: 4px; }
.config-actions { display: flex; align-items: center; gap: 4px; flex: 0 0 auto; flex-wrap: nowrap; white-space: nowrap; }
.config-actions :deep(.el-button) { margin-left: 0; }

.algo-filter-bar {
  display: flex;
  align-items: center;
  gap: 10px;
  flex-wrap: wrap;
}

.algo-table-panel,
.service-group-collapse {
  margin-top: 12px;
}

.algo-summary-strip {
  display: flex;
  align-items: center;
  gap: 8px;
  flex-wrap: wrap;
  margin-bottom: 10px;
}

.algo-summary-strip span {
  min-height: 30px;
  display: inline-flex;
  align-items: center;
  gap: 5px;
  padding: 5px 10px;
  border: 1px solid var(--app-border-soft);
  border-radius: var(--app-radius-sm);
  background: #ffffff;
  color: var(--app-ink-muted);
  font-size: 12px;
}

.algo-summary-strip strong {
  color: var(--app-ink);
  font-size: 14px;
}

.algo-table,
.service-status-table {
  border: 1px solid var(--app-border-soft);
  border-radius: var(--app-radius-sm);
}

.agent-tool-panel {
  min-width: 0;
  margin-top: 12px;
  overflow-x: auto;
}

.agent-tool-table {
  border: 1px solid var(--app-border-soft);
  border-radius: var(--app-radius-sm);
}

.agent-tool-main {
  min-width: 0;
  display: grid;
  gap: 3px;
}

.agent-tool-main strong {
  color: var(--app-ink);
  font-size: 13px;
}

.agent-tool-main small,
.agent-tool-main p {
  overflow: hidden;
  color: var(--app-ink-muted);
  font-size: 12px;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.agent-tool-main p {
  margin: 0;
}

.algo-table :deep(.el-table__cell),
.service-status-table :deep(.el-table__cell) {
  vertical-align: top;
}

.algo-name-cell,
.service-name-cell {
  min-width: 0;
  display: grid;
  gap: 3px;
}

.algo-name-cell strong,
.service-name-cell strong {
  overflow: hidden;
  color: var(--app-ink);
  font-size: 13px;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.algo-name-cell small,
.service-name-cell small,
.algo-name-cell span {
  min-width: 0;
  overflow: hidden;
  color: var(--app-ink-muted);
  font-size: 12px;
  line-height: 1.45;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.algo-status-cell,
.compact-tag-list {
  display: flex;
  align-items: center;
  gap: 5px;
  flex-wrap: wrap;
}

.service-group-collapse :deep(.el-collapse-item__header) {
  min-height: 44px;
  padding: 0 4px;
}

.service-group-collapse :deep(.el-collapse-item__content) {
  padding-bottom: 14px;
}

.tools-header {
  display: flex;
  align-items: center;
  gap: 16px;
}

.tools-header > div {
  flex: 1;
}

.panel-subtitle {
  margin: 6px 0 0;
  color: var(--app-ink-muted);
  font-size: 13px;
}

.config-alert {
  margin-bottom: 12px;
}

.connector-alert {
  margin-bottom: 12px;
}

.connector-list {
  display: grid;
  gap: 14px;
}

.connector-card {
  padding: 16px;
  border: 1px solid #dbeafe;
  border-radius: 12px;
  background: #fff;
}

.connector-card-head {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 12px;
}

.connector-card-head strong {
  display: block;
  color: var(--app-ink);
  font-size: 15px;
}

.connector-card-head small {
  display: block;
  margin-top: 2px;
  color: var(--app-ink-muted);
  font-size: 12px;
}

.connector-reason {
  margin: 8px 0 0;
  color: #b45309;
  font-size: 13px;
}

.connector-meta {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(220px, 1fr));
  gap: 10px;
  margin: 12px 0;
}

.connector-meta dt {
  color: var(--app-ink-muted);
  font-size: 12px;
}

.connector-meta dd {
  margin: 2px 0 0;
  color: var(--app-ink);
  font-size: 13px;
  line-height: 1.5;
}

.connector-policy {
  margin-top: 12px;
  padding-top: 12px;
  border-top: 1px dashed #e2e8f0;
}

.connector-policy h4 {
  margin: 0 0 8px;
  color: var(--app-ink);
  font-size: 13px;
}

.connector-policy-form {
  max-width: 460px;
}

.connector-actions {
  display: flex;
  gap: 8px;
}

.connector-result {
  margin-top: 12px;
}

.config-summary-line {
  display: block;
  max-width: 100%;
  overflow: hidden;
  color: var(--app-ink-body);
  text-overflow: ellipsis;
  white-space: nowrap;
}

.llm-toolbar,
.llm-routing-head,
.llm-provider-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 14px;
}

.llm-toolbar h4 {
  margin: 0;
  color: var(--app-ink);
  font-size: 15px;
}

.llm-toolbar p,
.llm-routing-head span,
.llm-provider-head span {
  margin: 4px 0 0;
  color: var(--app-ink-muted);
  font-size: 12px;
}

.llm-toolbar-actions {
  display: flex;
  gap: 8px;
  flex-wrap: wrap;
  justify-content: flex-end;
}

.llm-model-panel {
  min-height: 280px;
  display: grid;
  gap: 14px;
  margin-top: 12px;
}

.llm-stat-grid {
  display: grid;
  grid-template-columns: repeat(4, minmax(0, 1fr));
  gap: 10px;
}

.llm-stat,
.llm-routing-card,
.llm-provider-card {
  border: 1px solid var(--app-border-soft);
  border-radius: var(--app-radius-md);
  background: #fff;
}

.llm-stat {
  display: grid;
  gap: 3px;
  padding: 12px;
}

.llm-stat span,
.llm-stat small {
  color: var(--app-ink-muted);
  font-size: 12px;
}

.llm-stat strong {
  color: var(--app-ink);
  font-size: 22px;
}

.llm-routing-card,
.llm-provider-card {
  padding: 14px;
}

.llm-routing-grid {
  display: grid;
  grid-template-columns: repeat(3, minmax(0, 1fr));
  gap: 12px;
  margin-top: 14px;
}

.llm-provider-grid {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 12px;
}

.llm-provider-meta {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 10px;
  margin: 12px 0;
}

.llm-provider-meta dt {
  color: var(--app-ink-muted);
  font-size: 12px;
}

.llm-provider-meta dd {
  min-width: 0;
  margin: 3px 0 0;
  overflow-wrap: anywhere;
  color: var(--app-ink-body);
  font-size: 13px;
}

.llm-provider-note {
  margin: -2px 0 12px;
  color: var(--app-ink-muted);
  font-size: 12px;
}

.llm-quality-metrics,
.llm-context-distribution,
.llm-schema-section {
  min-width: 0;
  overflow-x: auto;
}

.llm-quality-metrics + .llm-context-distribution,
.llm-schema-section + .llm-schema-section {
  margin-top: 18px;
}

.llm-quality-note {
  margin: 12px 0 0;
  color: var(--app-ink-muted);
  font-size: 13px;
}

.llm-schema-section h5 {
  margin: 0 0 8px;
  color: var(--app-ink);
  font-size: 13px;
}

.llm-schema-section code,
.llm-quality-metrics code,
.llm-context-distribution code {
  font-family: var(--app-font-mono, ui-monospace, SFMono-Regular, Menlo, monospace);
  font-size: 12px;
  overflow-wrap: anywhere;
}

.llm-model-list {
  display: grid;
  gap: 8px;
}

.llm-model-row {
  min-width: 0;
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 10px;
  padding-top: 8px;
  border-top: 1px solid var(--app-border-soft);
}

.llm-model-row span {
  min-width: 0;
  overflow: hidden;
  color: var(--app-ink);
  font-size: 13px;
  font-weight: 600;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.llm-model-row div {
  display: flex;
  gap: 5px;
  flex-wrap: wrap;
  justify-content: flex-end;
}

.algo-board {
  min-height: 240px;
  display: grid;
  grid-template-columns: repeat(4, minmax(0, 1fr));
  gap: 12px;
  margin-top: 12px;
}

.algo-group {
  min-width: 0;
  border: 1px solid var(--app-border-soft);
  border-radius: var(--app-radius-md);
  background: #ffffff;
  overflow: hidden;
}

.algo-group--real {
  border-color: #bbdfc8;
}

.algo-group--builtin {
  border-color: #cbd8e8;
}

.algo-group--simulated {
  border-color: #ead1a0;
}

.algo-group--vertical {
  border-color: #bed7ff;
}

.algo-group-header {
  min-height: 70px;
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 10px;
  padding: 12px;
  border-bottom: 1px solid var(--app-border-soft);
  background: #f8fafc;
}

.algo-group--real .algo-group-header {
  background: #f0f8f2;
}

.algo-group--simulated .algo-group-header {
  background: #fff8e8;
}

.algo-group--vertical .algo-group-header {
  background: #f0f6ff;
}

.algo-group-header strong {
  display: block;
  color: var(--app-ink);
  font-size: 14px;
}

.algo-group-header span {
  display: block;
  margin-top: 4px;
  color: var(--app-ink-muted);
  font-size: 12px;
  line-height: 1.45;
}

.algo-group-header em {
  min-width: 26px;
  height: 24px;
  display: inline-flex;
  align-items: center;
  justify-content: center;
  border-radius: 999px;
  background: #ffffff;
  color: var(--app-ink);
  font-size: 12px;
  font-style: normal;
  font-weight: 800;
}

.algo-group-body {
  min-height: 160px;
  max-height: 620px;
  overflow: auto;
  display: flex;
  flex-direction: column;
  gap: 10px;
  padding: 10px;
}

.algo-card {
  min-width: 0;
  padding: 10px;
  border: 1px solid var(--app-border-soft);
  border-radius: var(--app-radius-sm);
  background: #ffffff;
}

.algo-card-top,
.algo-tags,
.algo-meta-row,
.algo-meta-row div {
  display: flex;
  align-items: center;
}

.algo-card-top {
  justify-content: space-between;
  gap: 8px;
}

.algo-title-block {
  min-width: 0;
}

.algo-title-block strong,
.algo-title-block small {
  display: block;
  max-width: 100%;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.algo-title-block strong {
  color: var(--app-ink);
  font-size: 13px;
}

.algo-title-block small,
.algo-meta-row > span {
  color: var(--app-ink-muted);
  font-size: 11px;
}

.algo-card p {
  min-height: 38px;
  display: -webkit-box;
  overflow: hidden;
  margin: 8px 0;
  color: var(--app-ink-body);
  font-size: 12px;
  line-height: 1.55;
  -webkit-box-orient: vertical;
  -webkit-line-clamp: 2;
}

.algo-tags {
  flex-wrap: wrap;
  gap: 6px;
  margin-bottom: 8px;
}

.algo-meta-row {
  align-items: flex-start;
  justify-content: space-between;
  gap: 8px;
  margin-top: 6px;
}

.algo-meta-row > span {
  flex: 0 0 34px;
  padding-top: 3px;
}

.algo-meta-row div {
  min-width: 0;
  flex: 1;
  justify-content: flex-end;
  flex-wrap: wrap;
  gap: 4px;
}

.algo-group-empty {
  min-height: 84px;
  display: flex;
  align-items: center;
  justify-content: center;
  border: 1px dashed var(--app-border-soft);
  border-radius: var(--app-radius-sm);
  color: var(--app-ink-muted);
  font-size: 12px;
}

.service-status-panel {
  min-height: 180px;
}

.service-health-strip {
  display: grid;
  grid-template-columns: repeat(4, minmax(0, 1fr));
  gap: 12px;
  margin-bottom: 18px;
}

.service-health-stat {
  min-width: 0;
  position: relative;
  overflow: hidden;
  padding: 12px 14px;
  border: 1px solid var(--app-border-soft);
  border-radius: var(--app-radius-md);
  background: linear-gradient(180deg, #ffffff 0%, #f8fbff 100%);
}

.service-health-stat::before {
  content: "";
  position: absolute;
  inset: 0 auto 0 0;
  width: 3px;
  background: #94a3b8;
}

.service-health-stat--success::before {
  background: #22c55e;
}

.service-health-stat--warning::before {
  background: #f59e0b;
}

.service-health-stat--danger::before {
  background: #ef4444;
}

.service-health-stat span,
.service-health-stat small {
  display: block;
  color: var(--app-ink-muted);
  font-size: 12px;
}

.service-health-stat strong {
  display: block;
  margin: 4px 0 2px;
  color: var(--app-ink);
  font-size: 22px;
  line-height: 1.1;
}

.service-group-title {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 10px;
  width: 100%;
  margin: 0;
  padding-right: 12px;
}

.service-group-title h4 {
  margin: 0;
  color: var(--app-ink);
  font-size: 14px;
}

.service-group-title span {
  color: var(--app-ink-muted);
  font-size: 12px;
}

.service-card-grid {
  display: grid;
  grid-template-columns: repeat(3, minmax(0, 1fr));
  gap: 12px;
}

.service-card {
  position: relative;
  overflow: hidden;
  min-height: 190px;
  padding: 16px 14px 14px;
  border: 1px solid var(--app-border-soft);
  border-radius: var(--app-radius-md);
  background: linear-gradient(180deg, #ffffff 0%, #fbfdff 100%);
  transition: border-color 0.18s ease, box-shadow 0.18s ease, transform 0.18s ease;
}

.service-card::before {
  content: "";
  position: absolute;
  inset: 0 0 auto;
  height: 3px;
  background: #94a3b8;
}

.service-card--success::before {
  background: #22c55e;
}

.service-card--warning::before {
  background: #f59e0b;
}

.service-card--danger::before {
  background: #ef4444;
}

.service-card:hover {
  border-color: #bfdbfe;
  box-shadow: 0 12px 26px rgba(22, 59, 110, 0.08);
  transform: translateY(-1px);
}

.service-card-header {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 12px;
}

.service-card-header > div:first-child {
  min-width: 0;
}

.service-card-header strong {
  display: block;
  overflow: hidden;
  color: var(--app-ink);
  font-size: 15px;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.service-card-header span {
  display: block;
  margin-top: 4px;
  color: var(--app-ink-muted);
  font-size: 12px;
  line-height: 1.5;
}

.service-status-line {
  flex: 0 0 auto;
  display: inline-flex;
  align-items: center;
  gap: 6px;
}

.service-status-dot {
  width: 8px;
  height: 8px;
  border-radius: 50%;
  background: #94a3b8;
  box-shadow: 0 0 0 4px rgba(148, 163, 184, 0.14);
}

.service-card--success .service-status-dot {
  background: #22c55e;
  box-shadow: 0 0 0 4px rgba(34, 197, 94, 0.14);
}

.service-card--warning .service-status-dot {
  background: #f59e0b;
  box-shadow: 0 0 0 4px rgba(245, 158, 11, 0.14);
}

.service-card--danger .service-status-dot {
  background: #ef4444;
  box-shadow: 0 0 0 4px rgba(239, 68, 68, 0.14);
}

.service-facts {
  margin: 14px 0 10px;
  display: grid;
  gap: 8px;
}

.service-facts div {
  min-width: 0;
}

.service-facts dt {
  color: var(--app-ink-muted);
  font-size: 12px;
}

.service-facts dd {
  margin: 2px 0 0;
  color: var(--app-ink-body);
  font-size: 12px;
  overflow-wrap: anywhere;
}

.service-fact-value {
  display: -webkit-box;
  overflow: hidden;
  -webkit-box-orient: vertical;
  -webkit-line-clamp: 2;
}

.service-fact-value--version,
.service-fact-value--reason {
  -webkit-line-clamp: 3;
}

.service-reason dd {
  color: #b45309;
}

.config-table {
  border-radius: var(--app-radius-sm);
}

.config-table :deep(.el-table-fixed-column--right) {
  background: #ffffff;
  box-shadow: -8px 0 18px rgba(22, 59, 110, 0.06);
}

.config-table :deep(.el-table__body tr.el-table__row--striped td.el-table-fixed-column--right) {
  background: #f7f9fd;
}

.config-actions {
  display: flex;
  align-items: center;
  gap: 6px;
  flex-wrap: nowrap;
  white-space: nowrap;
}

.config-actions :deep(.el-button) {
  margin-left: 0;
}

summary {
  cursor: pointer;
  color: var(--app-primary-active);
  font-size: 12px;
}

.details-json {
  margin: 0;
  max-height: 120px;
  overflow: auto;
  color: var(--app-ink-body);
  font-family: var(--app-mono-font);
  font-size: 12px;
  line-height: 1.45;
  white-space: pre-wrap;
  word-break: break-word;
}

.drawer-section-title {
  margin: 16px 0 8px;
  color: var(--app-ink);
  font-size: 14px;
}

.drawer-json {
  max-height: 240px;
  padding: 10px;
  border: 1px solid var(--app-border-soft);
  border-radius: var(--app-radius-sm);
  background: #f8fafc;
}

.form-grid {
  display: grid;
  grid-template-columns: minmax(0, 1fr) 180px;
  gap: 12px;
}

@media (max-width: 720px) {
  .tools-header {
    align-items: flex-start;
    flex-direction: column;
  }

  .service-health-strip {
    grid-template-columns: 1fr;
  }

  .form-grid {
    grid-template-columns: 1fr;
  }

  .service-card-grid {
    grid-template-columns: 1fr;
  }

  .algo-board {
    grid-template-columns: 1fr;
  }

  .llm-toolbar,
  .llm-routing-head,
  .llm-provider-head {
    align-items: stretch;
    flex-direction: column;
  }

  .llm-stat-grid,
  .llm-routing-grid,
  .llm-provider-grid,
  .llm-provider-meta {
    grid-template-columns: 1fr;
  }
}

@media (min-width: 721px) and (max-width: 1180px) {
  .service-health-strip {
    grid-template-columns: repeat(2, minmax(0, 1fr));
  }

  .service-card-grid {
    grid-template-columns: repeat(2, minmax(0, 1fr));
  }

  .algo-board {
    grid-template-columns: repeat(2, minmax(0, 1fr));
  }

  .llm-stat-grid,
  .llm-provider-grid {
    grid-template-columns: repeat(2, minmax(0, 1fr));
  }

  .llm-routing-grid {
    grid-template-columns: 1fr;
  }
}

@media (max-width: 1180px) {
  .service-list-row { flex-wrap: wrap; }
  .service-list-main { flex-basis: calc(100% - 58px); }
  .service-list-status, .service-list-fact { flex: 1 1 145px; }
  .algo-list-row, .config-list-row { flex-wrap: wrap; }
  .algo-list-main { flex-basis: calc(100% - 58px); }
  .algo-list-status, .algo-list-meta { flex: 1 1 180px; }
  .config-list-main { flex-basis: calc(100% - 58px); }
  .config-list-status, .config-list-summary, .config-list-enabled { flex: 1 1 160px; }
}

@media (max-width: 760px) {
  .tools-page-header, .section-heading { align-items: flex-start; flex-direction: column; }
  .header-actions { justify-content: flex-start; }
  .metric-grid { grid-template-columns: 1fr; }
  .tools-browser-layout { grid-template-columns: 1fr; }
  .tools-rail { position: static; display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); padding: 0 0 10px; border-right: 0; border-bottom: 1px solid var(--app-border-soft); }
  .tools-rail-label { grid-column: 1 / -1; margin: 0 0 2px; }
  .tools-group-title h3 { font-size: 16px; }
  .service-list-row, .algo-list-row, .config-list-row { align-items: flex-start; padding: 13px 12px; }
  .service-list-main, .algo-list-main, .config-list-main { flex-basis: 100%; }
  .service-list-status, .service-list-fact, .algo-list-status, .algo-list-meta, .config-list-status, .config-list-summary, .config-list-enabled { flex: 1 1 calc(50% - 8px); }
  .config-actions { width: 100%; justify-content: flex-start; }
  .algo-filter-bar .el-input { width: 100% !important; }
}
</style>
