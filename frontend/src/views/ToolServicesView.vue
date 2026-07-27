<script setup>
import { computed, onMounted, reactive, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { ElMessage } from 'element-plus'
import { Check, Edit, Refresh, View as ViewIcon } from '@element-plus/icons-vue'

import {
  checkLlmModels,
  checkIntegrationConfig,
  getAlgorithm,
  getApiErrorMessage,
  getIntegrationStatus,
  getLlmModels,
  listAlgorithms,
  listIntegrationConfigs,
  updateLlmRouting,
  upsertIntegrationConfig,
} from '../api/polyAgentApi'

const route = useRoute()
const router = useRouter()
const services = ref([])
const configs = ref([])
const llmCatalog = ref({ providers: [], routing: {} })
const loadingStatus = ref(false)
const loadingConfigs = ref(false)
const loadingLlm = ref(false)
const saving = ref(false)
const savingLlmRouting = ref(false)
const actionLoading = ref('')
const configError = ref('')
const llmError = ref('')
const editVisible = ref(false)
const editingServiceKey = ref('')
const activeTab = ref(normalizeTab(route.query.tab))
const statusDetailVisible = ref(false)
const selectedServiceStatus = ref(null)

// ── ResearchEngine 算法清单 ──
const algorithms = ref([])
const algoLoading = ref(false)
const algoDetailVisible = ref(false)
const algoDetail = ref(null)
const algoFilters = reactive({ type: '', material_scope: '', keyword: '' })
const configDetailVisible = ref(false)
const selectedConfig = ref(null)
const llmRouteForm = reactive({ qa: '', deep: '', report: '' })

function normalizeTab(value) {
  const tab = Array.isArray(value) ? value[0] : value
  return ['status', 'algorithms', 'configs', 'llm-models'].includes(tab) ? tab : 'status'
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
  { key: 'real', label: '真实能力', hint: '已接入真实服务、SDK 或本地计算链路' },
  { key: 'builtin', label: '内置能力', hint: '平台内置能力或待封装能力' },
  { key: 'simulated', label: '模拟演示', hint: '仅用于演示、流程占位或 mock 输出' },
  { key: 'vertical', label: '垂类算法', hint: '材料性质等垂类模型服务与上传算法' },
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
]

const currentConfig = computed(() => configs.value.find((item) => item.service_key === editingServiceKey.value))

const serviceCatalog = {
  mongodb: { name: 'MongoDB', group: '核心存储', hint: 'Poly Agent 主数据库连接状态' },
  'data-asset-mongodb': { name: '数据资产 MongoDB', group: '核心存储', hint: '只读材料数据资产库接入状态' },
  'computation-worker': { name: '计算 Worker', group: '运行组件', hint: '领取 queued run 并执行真实计算 workflow' },
  'artifact-store': { name: 'Artifact 存储', group: '核心存储', hint: '保存结构、日志、结果 JSON 和下载文件' },
  'literature-rag': { name: 'Literature RAG', group: '知识服务', hint: '知识增强检索服务和 corpus 状态' },
  'knowledge-graph': { name: 'Knowledge Graph', group: '知识服务', hint: '知识图谱子图检索能力状态' },
  rdkit: { name: 'RDKit', group: '计算工具链', hint: 'SMILES 解析和三维结构初猜' },
  openbabel: { name: 'OpenBabel', group: '计算工具链', hint: '结构格式转换和备用三维结构生成' },
  xtb: { name: 'xTB', group: '计算工具链', hint: '低成本粗优化和单点计算' },
  crest: { name: 'CREST', group: '计算工具链', hint: '构象搜索，给 xTB/ORCA 提供合理姿态' },
  orca: { name: 'ORCA', group: '计算工具链', hint: '高精度 DFT/激发态精加工' },
  'alchemist-backend': { name: 'Alchemist', group: '优化与实验', hint: '贝叶斯优化和实验设计后端' },
  speclabos: { name: 'SpecLabOS', group: '优化与实验', hint: '真实实验系统接口，需配置 endpoint' },
  docker: { name: 'Docker', group: '运行组件', hint: '可选容器运行能力' },
}

const serviceGroups = computed(() => {
  const groups = ['核心存储', '知识服务', '计算工具链', '优化与实验', '运行组件']
  return groups.map((group) => ({
    name: group,
    items: services.value.filter((item) => (serviceCatalog[item.service]?.group || '运行组件') === group),
  })).filter((group) => group.items.length)
})

const activeServiceGroups = ref([])

watch(serviceGroups, (groups) => {
  activeServiceGroups.value = groups.map((group) => group.name)
}, { immediate: true })

const healthSummary = computed(() => {
  const required = ['mongodb', 'artifact-store', 'literature-rag', 'rdkit', 'openbabel', 'xtb']
  const items = services.value.filter((item) => required.includes(item.service))
  const ready = items.filter((item) => ['up', 'available', 'built_in'].includes(item.status)).length
  return { ready, total: items.length }
})

const serviceHealthStats = computed(() => {
  const readyStatuses = new Set(['up', 'available', 'built_in'])
  const issueStatuses = new Set(['degraded', 'down', 'failed'])
  const setupStatuses = new Set(['not_configured', 'disabled', 'not_available'])
  const ready = services.value.filter((item) => readyStatuses.has(item.status)).length
  const issues = services.value.filter((item) => issueStatuses.has(item.status)).length
  const setupRequired = services.value.filter((item) => setupStatuses.has(item.status)).length
  const coreReady = healthSummary.value.total > 0 && healthSummary.value.ready === healthSummary.value.total
  return [
    { label: '核心服务', value: `${healthSummary.value.ready}/${healthSummary.value.total}`, hint: '关键链路', tone: coreReady ? 'success' : 'warning' },
    { label: '可用服务', value: String(ready), hint: '在线 / 内置', tone: 'success' },
    { label: '异常服务', value: String(issues), hint: '需排查', tone: issues ? 'danger' : 'neutral' },
    { label: '待配置', value: String(setupRequired), hint: '未安装 / 未配置', tone: setupRequired ? 'warning' : 'neutral' },
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
  const available = providers.filter((item) => ['available', 'unknown'].includes(item.status)).length
  const models = providers.reduce((sum, item) => sum + (item.models?.length || 0), 0)
  const reasoning = llmModelOptions.value.filter((item) => item.capabilities.includes('reasoning')).length
  return [
    { label: 'Provider', value: String(providers.length), hint: '已登记' },
    { label: '模型', value: String(models), hint: '可选择' },
    { label: '推理模型', value: String(reasoning), hint: 'deep 路由' },
    { label: '可用/未知', value: String(available), hint: '未失败' },
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

function serviceVersion(row) {
  return row.details?.version || row.details?.message || '-'
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

async function refreshLlmModels() {
  loadingLlm.value = true
  llmError.value = ''
  try {
    llmCatalog.value = await checkLlmModels()
    syncLlmRouteForm()
    ElMessage.success('LLM 模型状态已刷新')
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
    await loadConfigs()
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
  loadLlmModels({ quiet: true })
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
})
</script>

<template>
  <div class="tools-view">
    <section class="panel">
      <div class="panel-header tools-header">
        <div>
          <h3 class="panel-title">工具服务</h3>
          <p class="panel-subtitle">真实计算工具链、Mongo/artifact、SpecLabOS 和优化服务状态。</p>
        </div>
        <el-tag size="large" :type="healthSummary.total > 0 && healthSummary.ready === healthSummary.total ? 'success' : 'warning'">
          核心服务 {{ healthSummary.ready }}/{{ healthSummary.total }}
        </el-tag>
        <el-button :icon="Refresh" :loading="loadingStatus || loadingConfigs" @click="loadAll">刷新</el-button>
      </div>
    </section>

    <section class="panel">
      <div class="panel-body">
        <el-tabs v-model="activeTab">
          <el-tab-pane label="状态" name="status">
            <div v-loading="loadingStatus" class="service-status-panel">
              <div class="service-health-strip" aria-label="服务健康概览">
                <article v-for="stat in serviceHealthStats" :key="stat.label" class="service-health-stat" :class="`service-health-stat--${stat.tone}`">
                  <span>{{ stat.label }}</span>
                  <strong>{{ stat.value }}</strong>
                  <small>{{ stat.hint }}</small>
                </article>
              </div>
              <el-collapse v-model="activeServiceGroups" class="service-group-collapse">
                <el-collapse-item v-for="group in serviceGroups" :key="group.name" :name="group.name">
                  <template #title>
                    <div class="service-group-title">
                      <h4>{{ group.name }}</h4>
                      <span>{{ group.items.length }} 项</span>
                    </div>
                  </template>
                  <el-table :data="group.items" stripe class="service-status-table">
                    <el-table-column label="服务" min-width="210">
                      <template #default="{ row }">
                        <div class="service-name-cell">
                          <strong>{{ serviceName(row.service) }}</strong>
                          <small>{{ serviceHint(row.service) }}</small>
                        </div>
                      </template>
                    </el-table-column>
                    <el-table-column label="状态" width="110">
                      <template #default="{ row }">
                        <el-tag size="small" :type="statusTag(row.status)">{{ statusLabel(row.status) }}</el-tag>
                      </template>
                    </el-table-column>
                    <el-table-column label="位置" min-width="220" show-overflow-tooltip>
                      <template #default="{ row }">{{ servicePrimaryDetail(row) }}</template>
                    </el-table-column>
                    <el-table-column label="版本 / 信息" min-width="180" show-overflow-tooltip>
                      <template #default="{ row }">{{ serviceVersion(row) }}</template>
                    </el-table-column>
                    <el-table-column label="原因" min-width="180" show-overflow-tooltip>
                      <template #default="{ row }">{{ serviceReason(row) || '-' }}</template>
                    </el-table-column>
                    <el-table-column label="操作" width="96" align="right">
                      <template #default="{ row }">
                        <el-button text type="primary" size="small" :icon="ViewIcon" @click="showServiceDetail(row)">详情</el-button>
                      </template>
                    </el-table-column>
                  </el-table>
                </el-collapse-item>
              </el-collapse>
            </div>
          </el-tab-pane>

          <el-tab-pane label="算法清单" name="algorithms">
            <div class="algo-filter-bar">
              <el-select v-model="algoFilters.type" placeholder="算法类型" clearable style="width:130px">
                <el-option v-for="item in algoTypeOptions" :key="item.value" :label="item.label" :value="item.value" />
              </el-select>
              <el-select v-model="algoFilters.material_scope" placeholder="材料体系" clearable style="width:130px">
                <el-option label="氟基" value="fluoropolymer" />
                <el-option label="碳基" value="carbon_polymer" />
                <el-option label="硅基" value="silicon_polymer" />
                <el-option label="通用" value="universal" />
              </el-select>
              <el-input v-model="algoFilters.keyword" placeholder="搜索算法" clearable style="width:200px" />
              <el-button text @click="algoFilters.type = ''; algoFilters.material_scope = ''; algoFilters.keyword = ''">重置</el-button>
              <el-button :icon="Refresh" :loading="algoLoading" @click="loadAlgos">刷新</el-button>
            </div>
            <div v-if="filteredAlgos.length" v-loading="algoLoading" class="algo-table-panel">
              <div class="algo-summary-strip" aria-label="算法接入概览">
                <span v-for="stat in algorithmStats" :key="stat.key">
                  <strong>{{ stat.count }}</strong>
                  {{ stat.label }}
                </span>
              </div>
              <el-table :data="filteredAlgos" stripe class="algo-table">
                <el-table-column label="算法 / ID" min-width="260">
                  <template #default="{ row }">
                    <div class="algo-name-cell">
                      <strong :title="row.name">{{ row.name }}</strong>
                      <small :title="row.algorithm_id">{{ row.algorithm_id }}</small>
                      <span :title="row.description">{{ row.description || '暂无描述' }}</span>
                    </div>
                  </template>
                </el-table-column>
                <el-table-column label="类型" width="110">
                  <template #default="{ row }">
                    <el-tag size="small" :type="algoTypeTag(row.type)">{{ algoTypeLabel(row.type) }}</el-tag>
                  </template>
                </el-table-column>
                <el-table-column label="接入状态" width="140">
                  <template #default="{ row }">
                    <div class="algo-status-cell">
                      <el-tag size="small" :type="algoIntegrationTag(algoIntegrationKind(row))" effect="plain">
                        {{ algoIntegrationLabel(algoIntegrationKind(row)) }}
                      </el-tag>
                      <el-tag size="small" :type="algoStatusTag(row.status)" effect="plain">{{ algoStatusLabel(row.status) }}</el-tag>
                    </div>
                  </template>
                </el-table-column>
                <el-table-column label="调用方式" min-width="150" show-overflow-tooltip>
                  <template #default="{ row }">{{ row.call_method }}</template>
                </el-table-column>
                <el-table-column label="材料范围" min-width="180">
                  <template #default="{ row }">
                    <div class="compact-tag-list">
                      <el-tag v-for="item in materialScopeLabel(row.material_scope)" :key="item" size="small" effect="plain">
                        {{ item }}
                      </el-tag>
                    </div>
                  </template>
                </el-table-column>
                <el-table-column label="触发方式" min-width="180">
                  <template #default="{ row }">
                    <div class="compact-tag-list">
                      <el-tag v-for="item in triggerModeLabel(row.trigger_modes)" :key="item" size="small" effect="plain">
                        {{ item }}
                      </el-tag>
                    </div>
                  </template>
                </el-table-column>
                <el-table-column label="操作" width="96" align="right">
                  <template #default="{ row }">
                    <el-button text type="primary" size="small" :icon="ViewIcon" @click="showAlgoDetail(row)">详情</el-button>
                  </template>
                </el-table-column>
              </el-table>
            </div>
            <div v-else-if="!algoLoading" class="empty-inline" style="min-height:100px;justify-content:center">
              暂无算法数据
            </div>
          </el-tab-pane>
          <el-tab-pane label="配置" name="configs">
            <el-alert v-if="configError" :title="configError" type="warning" :closable="false" class="config-alert" />
            <el-table v-else :data="configs" v-loading="loadingConfigs" stripe class="config-table">
              <el-table-column prop="service_key" label="Service" min-width="150" />
              <el-table-column prop="display_name" label="名称" min-width="180" />
              <el-table-column prop="service_type" label="类型" width="130" />
              <el-table-column label="启用" width="96">
                <template #default="{ row }">
                  <el-switch
                    :model-value="row.enabled"
                    :loading="actionLoading === `${row.service_key}:toggle`"
                    @change="(value) => toggleEnabled(row, value)"
                  />
                </template>
              </el-table-column>
              <el-table-column label="状态" width="130">
                <template #default="{ row }">
                  <el-tag size="small" :type="statusTag(row.last_status)">{{ statusLabel(row.last_status) }}</el-tag>
                </template>
              </el-table-column>
              <el-table-column label="配置摘要" min-width="220" show-overflow-tooltip>
                <template #default="{ row }">
                  <span class="config-summary-line">{{ compactConfigSummary(row) }}</span>
                </template>
              </el-table-column>
              <el-table-column label="最后检查" width="180">
                <template #default="{ row }">
                  <span>{{ formatDate(row.last_checked_at) }}</span>
                </template>
              </el-table-column>
              <el-table-column prop="last_error_summary" label="错误" min-width="180" show-overflow-tooltip />
              <el-table-column label="操作" width="230" fixed="right">
                <template #default="{ row }">
                  <div class="config-actions">
                    <el-button text type="primary" size="small" :icon="Edit" @click="openEdit(row)">编辑</el-button>
                    <el-button
                      text
                      type="primary"
                      size="small"
                      :icon="Check"
                      :loading="actionLoading === `${row.service_key}:check`"
                      @click="handleCheck(row)"
                    >
                      检查
                    </el-button>
                    <el-button text type="primary" size="small" :icon="ViewIcon" @click="showConfigDetail(row)">详情</el-button>
                  </div>
                </template>
              </el-table-column>
            </el-table>
          </el-tab-pane>
          <el-tab-pane label="LLM 模型" name="llm-models">
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
            <div v-loading="loadingLlm" class="llm-model-panel">
              <div class="llm-stat-grid">
                <article v-for="stat in llmProviderStats" :key="stat.label" class="llm-stat">
                  <span>{{ stat.label }}</span>
                  <strong>{{ stat.value }}</strong>
                  <small>{{ stat.hint }}</small>
                </article>
              </div>

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
                    <el-tag size="small" :type="statusTag(provider.status)">{{ statusLabel(provider.status) }}</el-tag>
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
          </el-tab-pane>
        </el-tabs>
      </div>
    </section>

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
}

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
</style>
