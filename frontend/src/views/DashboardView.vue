<script setup>
import { computed, nextTick, onMounted, reactive, ref, watch } from 'vue'
import { useRouter } from 'vue-router'
import { ElMessage } from 'element-plus'
import {
  Aim, ArrowDown, ChatLineRound, Check, Expand, FolderOpened, Histogram, MagicStick, Promotion, Reading, SetUp, Tools,
} from '@element-plus/icons-vue'

import {
  createAssistantChat,
  getApiErrorMessage,
  getAssistantCommandCatalog,
  getIntegrationStatus,
  getLlmModels,
  listAgentTools,
  listKnowledgeSystems,
  listAlgorithmRuns,
  listCampaigns,
  listComputations,
  listResearchRuns,
  updateAssistantChat,
} from '../api/polyAgentApi'
import CommandPalette from '../components/assistant/CommandPalette.vue'
import GlobeIcon from '../components/GlobeIcon.vue'
import LlmModelSelect from '../components/LlmModelSelect.vue'
import ToolMenuPicker from '../components/ToolMenuPicker.vue'
import {
  loadKnowledgePreference,
  loadWebSearchPreference,
  saveKnowledgePreference,
  saveWebSearchPreference,
} from '../utils/dialoguePreferences'
import {
  isResearchEngineContainerCampaign,
  mapAlgorithmRunToGlobalTask,
  mapCampaignToGlobalTask,
  mapComputationRunToGlobalTask,
  mapResearchRunToGlobalTask,
} from '../tasks/taskModules'
import { buildSelectableLlmModels } from '../utils/llmModels'
import { createCommandCatalogCache } from '../utils/commandCatalog'
import {
  buildCommandDialogueRoute,
  filterCommandPalette,
  getSlashContext,
  movePaletteHighlight,
  paletteKeyAction,
  resolveCaretPosition,
  resolveCommandSubmission,
} from '../utils/slashCommands'

const router = useRouter()
const loading = ref(false)
const activeView = ref('chat')
const computationRows = ref([])
const campaignRows = ref([])
const algorithmRuns = ref([])
const researchRuns = ref([])
const integrationItems = ref([])
const computationsTotal = ref(0)
const campaignsTotal = ref(0)
const algorithmRunsTotal = ref(0)
const researchRunsTotal = ref(0)
const chatMode = ref('qa')
const chatInput = ref('')
const homeComposerRef = ref(null)
const homeComposerCaretPosition = ref(0)
const homeComposerComposing = ref(false)
const commandPaletteActive = ref(false)
const commandPaletteDismissed = ref(false)
const commandPaletteHighlightedIndex = ref(0)
const commandPaletteQuery = ref('')
const commandChatId = ref('')
const commandChatCreatingPromise = ref(null)
const commandCatalogLoadPromise = ref(null)
const modelLoading = ref(false)
const knowledgeLoading = ref(false)
const llmCatalog = ref({ providers: [], routing: {} })
const knowledgeSystems = ref([])
const agentTools = ref([])
const agentToolsLoading = ref(false)
const selectedModelKey = ref('')
const selectedKnowledgeBaseIds = ref(loadKnowledgePreference())
const selectedToolIds = ref([])
const useWebSearch = ref(loadWebSearchPreference())
const commandCatalogCache = createCommandCatalogCache(async (targetChatId) =>
  getAssistantCommandCatalog(targetChatId))
const commandCatalogState = reactive({
  loading: false,
  error: '',
  items: [],
  sessionState: null,
  catalogVersion: '',
})

const dashboardViewOptions = [
  { label: '问答', value: 'chat' },
  { label: '看板', value: 'board' },
]

const chatModeOptions = [
  { label: '科研问答', value: 'qa' },
  { label: '深度思考', value: 'deep' },
]

const homeGreetings = {
  default: {
    title: '今天想推进哪条高分子研发路线？',
    subtitle: '描述材料体系、目标性质或实验约束，Poly Agent 会帮你定位模型、计算和优化入口。',
    placeholder: '例如：帮我为含氟聚合物设计 Tg 预测和后续验证流程...',
    suggestions: ['如何为 Tg 预测模型准备输入？', '哪些垂类模型可直接调用？', '帮我规划一个 AI4S 材料发现任务'],
  },
  morning: {
    title: '上午好，先看模型还是实验闭环？',
    subtitle: '从性质预测、计算验证到贝叶斯优化，把 AI4S 研发动作拆成可追踪任务。',
    placeholder: '输入你的聚合物结构、物性目标或实验设计问题...',
    suggestions: ['上传的预测模型现在怎么运行？', '如何把预测结果接到 AutoResearch？', '查看最近失败的计算任务'],
  },
  noon: {
    title: '中午好，要先梳理材料数据还是任务队列？',
    subtitle: '把上午积累的结构、配方和计算结果整理成下一步可执行动作。',
    placeholder: '例如：根据现有候选材料，安排下午的预测和验证任务...',
    suggestions: ['帮我整理下一步实验建议', '查看最近失败的计算任务', '哪些算法是真实适配器？'],
  },
  afternoon: {
    title: '下午好，继续推进材料研发任务吗？',
    subtitle: '围绕性质预测、计算验证和优化建议，快速进入问答、任务提交或研发编排。',
    placeholder: '例如：为一批候选聚合物安排预测、xTB 计算和优化建议...',
    suggestions: ['如何开始一个 ResearchEngine 示例？', '计算智能和垂类预测怎么衔接？', '如何查看待审批任务？'],
  },
  evening: {
    title: '晚上好，要复盘今天的材料数据吗？',
    subtitle: '可以从知识库、垂类模型和计算结果出发，形成明天的实验或算法调用建议。',
    placeholder: '输入数据来源、目标性质或需要比较的材料系列...',
    suggestions: ['查询知识库里的高分子体系', '帮我整理下一步实验建议', '查看今天的任务进展'],
  },
  night: {
    title: '需要把材料问题拆成可执行任务吗？',
    subtitle: '围绕高分子结构、配方、工艺和目标性能，快速进入问答、任务提交或研发编排。',
    placeholder: '例如：为一批候选聚合物安排预测、xTB 计算和优化建议...',
    suggestions: ['如何开始一个 ResearchEngine 示例？', '计算智能和垂类预测怎么衔接？', '如何查看待审批任务？'],
  },
}

function getTimeGreeting(date = new Date()) {
  const hour = date.getHours()
  if (hour >= 5 && hour < 12) return homeGreetings.morning
  if (hour >= 12 && hour < 14) return homeGreetings.noon
  if (hour >= 14 && hour < 18) return homeGreetings.afternoon
  if (hour >= 18 && hour < 24) return homeGreetings.evening
  if (hour >= 0 && hour < 5) return homeGreetings.night
  return homeGreetings.default
}

const homeGreeting = ref(getTimeGreeting())

const currentSuggestions = computed(() => homeGreeting.value.suggestions)

const selectableModels = computed(() =>
  buildSelectableLlmModels(llmCatalog.value, {
    dedupeByModelId: true,
    preferredPurpose: routePurpose(),
  }),
)

const selectedModel = computed(() => selectableModels.value.find((item) => item.key === selectedModelKey.value) || null)
const selectedKnowledgeBases = computed(() =>
  selectedKnowledgeBaseIds.value
    .map((systemId) => knowledgeSystems.value.find((item) => item.system_id === systemId))
    .filter(Boolean),
)

const selectedToolSummary = computed(() =>
  (agentTools.value || []).filter((tool) => selectedToolIds.value.includes(tool.tool_id)),
)
const commandCatalogItems = computed(() => commandCatalogState.items || [])
const commandPaletteGroups = computed(() =>
  filterCommandPalette(commandCatalogItems.value, commandPaletteQuery.value))
const commandPaletteOptions = computed(() =>
  commandPaletteGroups.value.flatMap((group) => group.items))
const commandPaletteVisible = computed(() => commandPaletteActive.value && (
  commandCatalogState.loading
  || Boolean(commandCatalogState.error)
  || commandPaletteGroups.value.length > 0
))

const stats = computed(() => {
  const visibleCampaignRows = campaignRows.value.filter((item) => !isResearchEngineContainerCampaign(item))
  const allItems = [
    ...computationRows.value.map(mapComputationRunToGlobalTask),
    ...visibleCampaignRows.map(mapCampaignToGlobalTask),
    ...algorithmRuns.value.map(mapAlgorithmRunToGlobalTask),
    ...researchRuns.value.map(mapResearchRunToGlobalTask),
  ]
  const totalCount = computationsTotal.value + campaignsTotal.value + algorithmRunsTotal.value + researchRunsTotal.value
  const runningCount = allItems.filter((item) => item.status === 'running').length
  const completedCount = allItems.filter((item) => item.status === 'completed').length
  const blockedCount = allItems.filter((item) => item.status === 'blocked_approval').length
  const integrationsUp = integrationItems.value.filter((item) => item.status === 'up' || item.status === 'available').length

  return [
    { title: '总任务数', value: String(totalCount), color: '#3b82f6' },
    { title: '已完成', value: String(completedCount), color: '#16a34a' },
    { title: '运行中', value: String(runningCount), color: '#d97706' },
    { title: '待审批', value: String(blockedCount), color: '#ef4444' },
    { title: '模型服务', value: String(integrationsUp), color: '#7c3aed' },
  ]
})

const recentTasks = computed(() =>
  [
    ...computationRows.value.map(mapComputationRunToGlobalTask),
    ...campaignRows.value.filter((item) => !isResearchEngineContainerCampaign(item)).map(mapCampaignToGlobalTask),
    ...algorithmRuns.value.map(mapAlgorithmRunToGlobalTask),
    ...researchRuns.value.map(mapResearchRunToGlobalTask),
  ]
    .sort((a, b) => new Date(b.updated_at || b.created_at || 0).getTime() - new Date(a.updated_at || a.created_at || 0).getTime())
    .slice(0, 10),
)

const attentionTasks = computed(() =>
  recentTasks.value
    .filter((item) => ['blocked_approval', 'failed', 'running', 'queued'].includes(item.status))
    .slice(0, 6),
)

const serviceHealthCards = computed(() =>
  integrationItems.value.slice(0, 6).map((item) => ({
    service: item.service,
    status: item.status,
    message: item.details?.message || item.details?.reason || item.details?.version || item.status,
  })),
)

const moduleCards = computed(() => [
  {
    id: 'research-engine',
    icon: MagicStick,
    title: '研发引擎',
    description: '材料研发的算法编排平台，支持人工调用和自动编排两种模式。',
    highlights: ['定义研发任务与优化目标', '浏览材料算法', 'AutoResearch 自动推进'],
    route: '/research-engine',
    color: '#2563eb',
  },
  {
    id: 'task-submit',
    icon: Aim,
    title: '任务提交',
    description: '统一的工具调用入口，涵盖计算任务、湿实验优化和垂类模型。',
    highlights: ['提交计算任务', '启动贝叶斯优化', '上传预测模型'],
    route: '/tasks/submit',
    color: '#16a34a',
  },
  {
    id: 'task-center',
    icon: Histogram,
    title: '任务中心',
    description: '全局任务管理器，追踪所有模块的任务状态和进度。',
    highlights: ['筛选任务', '查看结果', '追踪进度'],
    route: '/tasks/center',
    color: '#d97706',
  },
  {
    id: 'tools',
    icon: SetUp,
    title: '工具服务',
    description: '查看计算工具链和后端服务的运行状态与集成配置。',
    highlights: ['工具链状态', '算法清单', '集成配置'],
    route: '/tools',
    color: '#0f766e',
  },
  {
    id: 'database',
    icon: FolderOpened,
    title: '数据管理',
    description: '统一查看材料数据资产、计算结果和 Mongo 结构化索引。',
    highlights: ['数据分级', '计算数据', '物性覆盖'],
    route: '/database/data-catalog',
    color: '#dc2626',
  },
])

function getStatusTag(status) {
  const map = { queued: 'info', running: 'warning', completed: 'success', failed: 'danger', cancelled: 'info', draft: 'info', paused: 'info', archived: 'info', blocked_approval: 'danger' }
  return map[status] || 'info'
}

function formatDate(value) {
  if (!value) return '-'
  const date = new Date(value)
  return Number.isNaN(date.getTime()) ? value : date.toLocaleString()
}

function goToTask(task) {
  if (task.route) router.push(task.route)
}

function routePurpose() {
  return chatMode.value === 'deep' ? 'deep' : 'qa'
}

watch(useWebSearch, (value) => {
  saveWebSearchPreference(value)
})

watch(
  selectedKnowledgeBaseIds,
  (value) => {
    saveKnowledgePreference(value)
  },
  { flush: 'sync' },
)

function selectDefaultModelForMode() {
  if (chatMode.value === 'model') return
  const purpose = routePurpose()
  const route = llmCatalog.value.routing?.[purpose]
  const key = route?.provider_id && route?.model_id ? `${route.provider_id}::${route.model_id}` : ''
  if (key && selectableModels.value.some((item) => item.key === key)) {
    selectedModelKey.value = key
    return
  }
  selectedModelKey.value = selectableModels.value[0]?.key || ''
}

/**
 * 构造首页预备会话的选项快照。
 *
 * Returns:
 *   与后端 AssistantChatCreate 契约一致的会话选项。
 */
function homeCommandChatPayload() {
  return {
    title: '首页命令会话',
    model: selectedModel.value
      ? { providerId: selectedModel.value.providerId, modelId: selectedModel.value.modelId }
      : {},
    mode: chatMode.value,
    knowledge_base_ids: selectedKnowledgeBaseIds.value,
    knowledge_base_names: selectedKnowledgeBases.value.map((item) => item.name),
    use_web_search: Boolean(useWebSearch.value),
    selected_tool_ids: selectedToolIds.value,
  }
}

/**
 * 创建或复用首页 Slash Command 预备会话。
 *
 * Returns:
 *   可加载命令目录的会话 ID；创建失败时返回空字符串。
 */
async function ensureHomeCommandChat() {
  if (commandChatId.value) return commandChatId.value
  if (!commandChatCreatingPromise.value) {
    commandChatCreatingPromise.value = createAssistantChat(homeCommandChatPayload())
      .then((data) => {
        commandChatId.value = data?.chat_id || ''
        return commandChatId.value
      })
      .finally(() => {
        commandChatCreatingPromise.value = null
      })
  }
  try {
    return await commandChatCreatingPromise.value
  } catch {
    return ''
  }
}

/**
 * 加载首页命令目录，并把错误保留在面板状态中供重试。
 *
 * Returns:
 *   成功时返回目录数据；失败时返回 null。
 */
async function loadHomeCommandCatalog() {
  if (commandCatalogLoadPromise.value) return commandCatalogLoadPromise.value
  const request = (async () => {
    commandCatalogState.loading = true
    commandCatalogState.error = ''
    try {
      const targetChatId = await ensureHomeCommandChat()
      if (!targetChatId) throw new Error('命令会话创建失败')
      const data = await commandCatalogCache.load(targetChatId)
      Object.assign(commandCatalogState, {
        loading: commandCatalogCache.state.loading,
        error: commandCatalogCache.state.error,
        items: data.items,
        sessionState: data.sessionState,
        catalogVersion: data.catalogVersion,
      })
      return data
    } catch (error) {
      commandCatalogState.loading = false
      commandCatalogState.error = getApiErrorMessage(error)
      return null
    }
  })()
  commandCatalogLoadPromise.value = request
  try {
    return await request
  } finally {
    if (commandCatalogLoadPromise.value === request) commandCatalogLoadPromise.value = null
  }
}

/**
 * 请求首页命令目录刷新，不阻塞首页输入。
 */
function requestHomeCommandCatalog() {
  void loadHomeCommandCatalog()
}

/**
 * 根据首页输入光标刷新 Slash Command 面板状态。
 *
 * Args:
 *   caretPosition: 首页 textarea 的当前光标位置。
 */
function refreshHomeCommandPalette(caretPosition = homeComposerCaretPosition.value) {
  const context = getSlashContext(chatInput.value, caretPosition)
  if (context.active && commandPaletteDismissed.value && context.query.length > 1) {
    commandPaletteActive.value = false
    return
  }
  commandPaletteDismissed.value = false
  commandPaletteActive.value = context.active
  commandPaletteQuery.value = context.query
  if (!context.active) {
    commandPaletteHighlightedIndex.value = 0
    return
  }
  if (!commandCatalogItems.value.length
    && !commandCatalogState.loading
    && !commandCatalogState.error) {
    requestHomeCommandCatalog()
  }
  const optionCount = commandPaletteOptions.value.length
  if (commandPaletteHighlightedIndex.value >= optionCount) commandPaletteHighlightedIndex.value = 0
}

/**
 * 同步首页输入光标并刷新命令面板。
 *
 * Args:
 *   event: 输入事件或 Element Plus 输入值。
 */
function syncHomeComposerCaret(event) {
  const nativeSelectionStart = homeComposerRef.value?.textarea?.selectionStart
  homeComposerCaretPosition.value = resolveCaretPosition(
    event,
    chatInput.value.length,
    typeof nativeSelectionStart === 'number' ? nativeSelectionStart : null,
  )
  refreshHomeCommandPalette()
}

/**
 * 生成首页命令选项被选中后的命令行。
 *
 * Args:
 *   option: 命令面板返回的选项。
 *
 * Returns:
 *   可继续补充参数的 slash 命令行。
 */
function homeCommandLineForOption(option) {
  if (option.usage.includes('<')) return `/${option.commandName} `
  if (option.key === option.commandName) {
    return option.inputMode === 'none' ? `/${option.commandName}` : `/${option.commandName} `
  }
  return option.usage
}

/**
 * 选中首页命令选项并保持输入框焦点。
 *
 * Args:
 *   option: 命令面板中的当前选项。
 */
function selectHomeCommandOption(option) {
  const line = homeCommandLineForOption(option)
  chatInput.value = line
  homeComposerCaretPosition.value = line.length
  commandPaletteQuery.value = getSlashContext(line, line.length).query
  commandPaletteHighlightedIndex.value = 0
  commandPaletteActive.value = false
  commandPaletteDismissed.value = true
  nextTick(() => homeComposerRef.value?.focus?.())
}

/**
 * 从首页工具栏打开 Slash Command 面板。
 */
function openHomeCommandPalette() {
  if (!chatInput.value.trim()) {
    chatInput.value = '/'
    homeComposerCaretPosition.value = 1
  }
  commandPaletteDismissed.value = false
  refreshHomeCommandPalette()
  nextTick(() => homeComposerRef.value?.focus?.())
}

function openDialogue(prompt) {
  const text = String(prompt || chatInput.value).trim()
  if (chatMode.value === 'model') {
    router.push({ path: '/tools', query: { tab: 'llm-models' } })
    return
  }
  if (!text) return
  if (resolveCommandSubmission(text, commandCatalogItems.value).isCommand) {
    void ensureHomeCommandChat().then(async (targetChatId) => {
      if (targetChatId) {
        await updateAssistantChat(targetChatId, homeCommandChatPayload()).catch(() => null)
      }
      router.push(buildCommandDialogueRoute(text, targetChatId))
    })
    return
  }
  const query = {
    prompt: text,
    mode: chatMode.value,
    providerId: selectedModel.value?.providerId || undefined,
    modelId: selectedModel.value?.modelId || undefined,
  }
  if (selectedToolIds.value.length) {
    query.toolIds = selectedToolIds.value.join(',')
  }
  router.push({
    path: '/dialogue',
    query,
  })
}

function handleChatKeydown(event) {
  if (commandPaletteVisible.value) {
    const action = paletteKeyAction({
      key: event.key,
      keyCode: event.keyCode,
      isComposing: homeComposerComposing.value || event.isComposing,
    })
    if (action.action === 'close') {
      event.preventDefault()
      commandPaletteActive.value = false
      commandPaletteDismissed.value = true
      return
    }
    if (action.action === 'move') {
      event.preventDefault()
      commandPaletteHighlightedIndex.value = movePaletteHighlight(
        commandPaletteHighlightedIndex.value,
        action.direction,
        commandPaletteOptions.value.length,
      )
      return
    }
    if (action.action === 'select') {
      event.preventDefault()
      const option = commandPaletteOptions.value[commandPaletteHighlightedIndex.value]
      if (option) selectHomeCommandOption(option)
      return
    }
  }
  if (event.key === 'Enter' && !event.shiftKey) {
    event.preventDefault()
    openDialogue()
  }
}

/**
 * 标记首页输入法组合开始，避免 Enter 误选命令。
 */
function handleHomeCompositionStart() {
  homeComposerComposing.value = true
}

/**
 * 标记首页输入法组合结束并刷新命令过滤词。
 */
function handleHomeCompositionEnd(event) {
  homeComposerComposing.value = false
  syncHomeComposerCaret(event)
}

async function loadDashboardData() {
  loading.value = true
  try {
    const [computations, campaigns, algoRuns, researchRunsData, status] = await Promise.all([
      listComputations({ page: 1, page_size: 5 }).catch(() => ({ items: [], total: 0 })),
      listCampaigns({ page: 1, page_size: 5 }).catch(() => ({ items: [], total: 0 })),
      listAlgorithmRuns({ page: 1, page_size: 5 }).catch(() => ({ items: [], total: 0 })),
      listResearchRuns({ page: 1, page_size: 5 }).catch(() => ({ items: [], total: 0 })),
      getIntegrationStatus().catch(() => ({ items: [] })),
    ])
    computationRows.value = computations.items || []
    campaignRows.value = campaigns.items || []
    algorithmRuns.value = algoRuns.items || []
    researchRuns.value = researchRunsData.items || []
    integrationItems.value = status.items || []
    computationsTotal.value = computations.total || 0
    campaignsTotal.value = campaigns.total || 0
    algorithmRunsTotal.value = algoRuns.total || 0
    researchRunsTotal.value = researchRunsData.total || 0
  } catch (error) {
    ElMessage.error(getApiErrorMessage(error))
  } finally {
    loading.value = false
  }
}

async function loadLlmCatalog() {
  modelLoading.value = true
  try {
    llmCatalog.value = await getLlmModels()
    selectDefaultModelForMode()
  } catch (error) {
    ElMessage.warning(`模型列表加载失败：${getApiErrorMessage(error)}`)
  } finally {
    modelLoading.value = false
  }
}

function currentModeLabel() {
  return chatModeOptions.find((item) => item.value === chatMode.value)?.label || '科研问答'
}

function selectChatMode(mode) {
  chatMode.value = mode
  selectDefaultModelForMode()
}

function isKnowledgeBaseSelected(systemId) {
  return selectedKnowledgeBaseIds.value.includes(systemId)
}

function toggleKnowledgeBase(systemId) {
  if (!systemId) return
  selectedKnowledgeBaseIds.value = isKnowledgeBaseSelected(systemId)
    ? selectedKnowledgeBaseIds.value.filter((item) => item !== systemId)
    : [...selectedKnowledgeBaseIds.value, systemId]
}

function removeKnowledgeBase(systemId) {
  selectedKnowledgeBaseIds.value = selectedKnowledgeBaseIds.value.filter((item) => item !== systemId)
}

function clearKnowledgeBases() {
  selectedKnowledgeBaseIds.value = []
}

async function loadKnowledgeBases() {
  knowledgeLoading.value = true
  try {
    const data = await listKnowledgeSystems()
    knowledgeSystems.value = data?.items || []
    if (
      selectedKnowledgeBaseIds.value.length
    ) {
      const validIds = new Set(knowledgeSystems.value.map((item) => item.system_id))
      selectedKnowledgeBaseIds.value = selectedKnowledgeBaseIds.value.filter((systemId) => validIds.has(systemId))
    }
  } catch (error) {
    knowledgeSystems.value = []
    ElMessage.warning(`知识库列表加载失败：${getApiErrorMessage(error)}`)
  } finally {
    knowledgeLoading.value = false
  }
}

async function loadAgentTools() {
  agentToolsLoading.value = true
  try {
    const data = await listAgentTools()
    agentTools.value = data?.items || []
    if (selectedToolIds.value.length) {
      const validIds = new Set(agentTools.value.map((tool) => tool.tool_id))
      selectedToolIds.value = selectedToolIds.value.filter((toolId) => validIds.has(toolId))
    }
  } catch (error) {
    agentTools.value = []
    ElMessage.warning(`算法工具加载失败：${getApiErrorMessage(error)}`)
  } finally {
    agentToolsLoading.value = false
  }
}

function removeAgentTool(toolId) {
  selectedToolIds.value = selectedToolIds.value.filter((item) => item !== toolId)
}

function openHistory() {
  router.push({ path: '/dialogue', query: { history: 'open' } })
}

function preloadDialogueRoute() {
  const preload = () => {
    import('../views/DialogueView.vue').catch(() => {
      // 预加载失败不影响正常点击跳转，路由仍会在需要时再次加载。
    })
  }
  window.setTimeout(preload, 300)
}

onMounted(() => {
  loadDashboardData()
  loadLlmCatalog()
  loadKnowledgeBases()
  loadAgentTools()
  preloadDialogueRoute()
})
</script>

<template>
  <div class="dashboard-view">
    <header class="dashboard-switchbar">
      <el-segmented v-model="activeView" :options="dashboardViewOptions" />
    </header>

    <section v-if="activeView === 'chat'" class="lui-hero">
      <div class="home-history docked" aria-label="历史会话">
        <el-tooltip content="展开历史会话" placement="right">
          <button type="button" class="home-history-icon-btn home-history-dock" aria-label="展开历史会话" @click="openHistory">
            <el-icon><Expand /></el-icon>
          </button>
        </el-tooltip>
      </div>

      <div class="hero-copy">
        <p class="hero-kicker">Poly Agent 工作台</p>
        <h1>{{ homeGreeting.title }}</h1>
        <p>{{ homeGreeting.subtitle }}</p>
      </div>

      <div class="lui-composer" @mouseenter="preloadDialogueRoute" @focusin="preloadDialogueRoute">
        <div v-if="selectedKnowledgeBases.length || selectedToolSummary.length" class="selected-tags-inline">
          <span v-for="system in selectedKnowledgeBases" :key="system.system_id" class="mention-chip mention-chip--kb">
            <el-icon><Reading /></el-icon>
            <span class="mention-chip-name" :title="system.name">{{ system.name }}</span>
            <button type="button" aria-label="移除知识库" @click="removeKnowledgeBase(system.system_id)">×</button>
          </span>
          <span v-for="tool in selectedToolSummary" :key="tool.tool_id" class="mention-chip mention-chip--tool">
            <el-icon><Tools /></el-icon>
            <span class="mention-chip-name" :title="tool.name">{{ tool.name }}</span>
            <button type="button" aria-label="移除工具" @click="removeAgentTool(tool.tool_id)">×</button>
          </span>
        </div>
        <div class="composer-input">
          <el-icon class="composer-mark"><ChatLineRound /></el-icon>
          <el-input
            v-model="chatInput"
            ref="homeComposerRef"
            type="textarea"
            :rows="5"
            :placeholder="homeGreeting.placeholder"
            resize="none"
            @input="syncHomeComposerCaret"
            @compositionstart="handleHomeCompositionStart"
            @compositionend="handleHomeCompositionEnd"
            @keydown="handleChatKeydown"
          />
          <CommandPalette
            :visible="commandPaletteVisible"
            :groups="commandPaletteGroups"
            :highlighted-index="commandPaletteHighlightedIndex"
            :loading="commandCatalogState.loading"
            :error="commandCatalogState.error"
            @highlight="commandPaletteHighlightedIndex = $event"
            @close="commandPaletteActive = false"
            @retry="requestHomeCommandCatalog"
            @select="selectHomeCommandOption"
          />
        </div>
        <div class="composer-toolbar">
          <div class="composer-left-tools">
            <el-dropdown trigger="click" @command="selectChatMode">
              <button type="button" class="mode-trigger">
                <span>{{ currentModeLabel() }}</span>
                <el-icon><ArrowDown /></el-icon>
              </button>
              <template #dropdown>
                <el-dropdown-menu>
                  <el-dropdown-item
                    v-for="item in chatModeOptions"
                    :key="item.value"
                    :command="item.value"
                    :class="{ selected: item.value === chatMode }"
                  >
                    {{ item.label }}
                  </el-dropdown-item>
                </el-dropdown-menu>
              </template>
            </el-dropdown>
            <el-tooltip :content="useWebSearch ? '关闭联网搜索' : '开启联网搜索'" placement="top">
              <button
                type="button"
                class="icon-tool-btn"
                :class="{ active: useWebSearch }"
                :aria-pressed="useWebSearch"
                aria-label="联网搜索"
                @click="useWebSearch = !useWebSearch"
              >
                <el-icon><GlobeIcon /></el-icon>
              </button>
            </el-tooltip>
            <el-tooltip content="输入 / 打开命令面板" placement="top">
              <button
                type="button"
                class="icon-tool-btn command-trigger"
                :class="{ active: commandPaletteVisible }"
                :aria-pressed="commandPaletteVisible"
                aria-label="打开命令面板"
                @click="openHomeCommandPalette"
              >
                /
              </button>
            </el-tooltip>
            <el-popover
              placement="top-start"
              trigger="click"
              width="300"
              popper-class="dashboard-kb-popper"
            >
              <template #reference>
                <button
                  type="button"
                  class="icon-tool-btn"
                  :class="{ active: Boolean(selectedKnowledgeBases.length) }"
                  :disabled="knowledgeLoading || !knowledgeSystems.length"
                  aria-label="选择知识库"
                >
                  <el-icon><Reading /></el-icon>
                  <span v-if="selectedKnowledgeBases.length" class="tool-count">{{ selectedKnowledgeBases.length }}</span>
                </button>
              </template>
              <div class="kb-picker">
                <button
                  v-for="system in knowledgeSystems"
                  :key="system.system_id"
                  type="button"
                  class="kb-picker-item"
                  :class="{ selected: isKnowledgeBaseSelected(system.system_id) }"
                  :aria-pressed="isKnowledgeBaseSelected(system.system_id)"
                  @click="toggleKnowledgeBase(system.system_id)"
                >
                  <el-icon><Reading /></el-icon>
                  <span>
                    <strong>{{ system.name }}</strong>
                    <small>{{ system.document_count || 0 }} 文档 · {{ system.status || 'unknown' }}</small>
                  </span>
                </button>
                <button v-if="selectedKnowledgeBases.length" type="button" class="kb-picker-clear" @click="clearKnowledgeBases">
                  清除全部
                </button>
                <p v-if="!knowledgeSystems.length" class="kb-picker-empty">暂无可用知识库</p>
              </div>
            </el-popover>
            <ToolMenuPicker
              v-model="selectedToolIds"
              :tools="agentTools"
              :loading="agentToolsLoading"
              aria-label="选择工具"
            />
          </div>
          <div class="composer-actions">
            <LlmModelSelect
              v-model="selectedModelKey"
              class="dashboard-model-select"
              :models="selectableModels"
              :loading="modelLoading"
            />
            <el-button
              type="primary"
              circle
              :icon="Promotion"
              :disabled="!chatInput.trim()"
              aria-label="发送"
              @click="openDialogue()"
            />
          </div>
        </div>
      </div>

      <div class="suggestion-row" aria-label="推荐问题">
        <button v-for="question in currentSuggestions" :key="question" type="button" @click="openDialogue(question)">
          {{ question }}
        </button>
      </div>
    </section>

    <template v-else>
      <section class="dashboard-section">
        <div class="stat-grid" v-loading="loading">
          <div v-for="stat in stats" :key="stat.title" class="stat-card">
            <div class="stat-title">{{ stat.title }}</div>
            <div class="stat-value" :style="{ color: stat.color }">{{ stat.value }}</div>
          </div>
        </div>
      </section>

      <section class="dashboard-section">
        <div class="section-heading">
          <h2>关键入口</h2>
          <p>保留常用路径，状态信息集中在看板中浏览。</p>
        </div>
        <div class="module-card-grid">
          <button v-for="card in moduleCards" :key="card.id" type="button" class="module-card" :style="{ '--card-accent': card.color }" @click="router.push(card.route)">
            <div class="module-card-header">
              <div class="module-card-icon">
                <el-icon :size="22"><component :is="card.icon" /></el-icon>
              </div>
              <div class="module-card-title-group">
                <strong>{{ card.title }}</strong>
                <span>{{ card.description }}</span>
              </div>
            </div>
            <div class="module-card-body">
              <span v-for="highlight in card.highlights" :key="highlight"><el-icon><Check /></el-icon>{{ highlight }}</span>
            </div>
          </button>
        </div>
      </section>

      <section class="dashboard-section command-grid">
        <div class="panel command-panel command-panel-primary">
          <div class="command-panel-header">
            <div>
              <h2>待处理任务</h2>
              <p>审批、失败和运行中的任务优先显示在这里。</p>
            </div>
            <el-button text type="primary" @click="router.push('/tasks/center')">全部任务</el-button>
          </div>
          <div v-if="attentionTasks.length" class="attention-list">
            <button v-for="task in attentionTasks" :key="task.task_id" type="button" class="attention-item" @click="goToTask(task)">
              <span>
                <strong>{{ task.title }}</strong>
                <small>{{ task.module_name }} · {{ task.task_id }}</small>
              </span>
              <el-tag :type="getStatusTag(task.status)" size="small">{{ task.status_text || task.status }}</el-tag>
            </button>
          </div>
          <el-empty v-else description="暂无需要处理的任务" :image-size="80" />
        </div>

        <div class="panel command-panel">
          <div class="command-panel-header">
            <div>
              <h2>服务健康</h2>
              <p>计算 worker、工具链和知识服务的最近状态。</p>
            </div>
            <el-button text type="primary" @click="router.push('/tools')">工具服务</el-button>
          </div>
          <div v-if="serviceHealthCards.length" class="service-health-list">
            <div v-for="item in serviceHealthCards" :key="item.service" class="service-health-item">
              <span>
                <strong>{{ item.service }}</strong>
                <small>{{ item.message }}</small>
              </span>
              <el-tag size="small" :type="['up', 'available', 'built_in'].includes(item.status) ? 'success' : item.status === 'disabled' ? 'info' : 'warning'">
                {{ item.status }}
              </el-tag>
            </div>
          </div>
          <el-empty v-else description="暂无服务状态" :image-size="80" />
        </div>
      </section>

    </template>
  </div>
</template>

<style scoped>
.dashboard-view { max-width: 1440px; margin: 0 auto; display: grid; gap: 16px; }
.dashboard-switchbar { display: flex; align-items: center; justify-content: flex-start; min-height: 32px; }
.lui-hero { position: relative; min-height: calc(100vh - 188px); display: grid; align-content: center; justify-items: center; gap: 16px; padding: 34px 16px 28px; }
.home-history { position: absolute; top: 0; left: 0; z-index: 2; border: 1px solid var(--app-border); border-radius: var(--app-radius-sm); background: #ffffff; }
.home-history.docked { width: 36px; height: 36px; padding: 0; }
.home-history-icon-btn { display: grid; place-items: center; padding: 0; border: 0; border-radius: var(--app-radius-sm); background: transparent; color: var(--app-ink-muted); cursor: pointer; font: inherit; }
.home-history-icon-btn:hover, .home-history-icon-btn:focus-visible { background: #f5f8fc; color: var(--app-primary-active); }
.home-history-dock { width: 34px; height: 34px; }
.hero-copy { max-width: 760px; text-align: center; }
.hero-kicker { margin: 0 0 8px; color: var(--app-primary-active); font-size: 13px; font-weight: 700; }
h1, h2 { margin: 0; color: var(--app-ink); letter-spacing: 0; }
h1 { font-size: 38px; line-height: 1.18; }
h2 { font-size: 16px; line-height: 1.35; }
.hero-copy p:last-child, .section-heading p, .command-panel-header p { margin: 8px 0 0; color: var(--app-ink-muted); font-size: 14px; line-height: 1.65; }
.lui-composer { width: min(820px, 100%); border: 1px solid #bcd5fb; border-radius: var(--app-radius-lg); background: rgba(255, 255, 255, 0.96); box-shadow: 0 18px 44px rgba(22, 59, 110, 0.09); padding: 14px; }
.selected-tags-inline { display: flex; align-items: center; gap: 6px; flex-wrap: wrap; padding: 0 0 8px; border-bottom: 1px solid var(--app-border-soft); }
.mention-chip { max-width: 100%; height: 26px; display: inline-flex; align-items: center; gap: 5px; padding: 0 7px; border: 1px solid var(--app-border-soft); border-radius: var(--app-radius-sm); background: #f8fbff; color: var(--app-ink-body); font-size: 12px; font-weight: 650; }
.mention-chip--kb .el-icon { color: var(--app-primary-active); }
.mention-chip--tool .el-icon { color: #16a34a; }
.mention-chip-name { min-width: 0; max-width: 180px; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.mention-chip button { width: 16px; height: 16px; display: inline-grid; place-items: center; padding: 0; border: 0; border-radius: 999px; background: transparent; color: #94a3b8; cursor: pointer; line-height: 1; }
.mention-chip button:hover { background: #e2e8f0; color: var(--app-ink); }
.composer-input { position: relative; display: grid; grid-template-columns: 26px minmax(0, 1fr); gap: 8px; align-items: start; }
.composer-mark { margin-top: 8px; color: var(--app-primary-active); font-size: 20px; }
.composer-input :deep(.el-textarea__inner) { min-height: 116px !important; border: 0; box-shadow: none; font-size: 15px; line-height: 1.7; }
.composer-toolbar { display: flex; justify-content: space-between; align-items: center; gap: 8px; padding-top: 10px; border-top: 1px solid var(--app-border-soft); }
.composer-left-tools, .composer-actions { min-width: 0; display: flex; align-items: center; gap: 8px; }
.composer-actions { justify-content: flex-end; }
.mode-trigger { height: 28px; display: inline-flex; align-items: center; justify-content: center; gap: 4px; padding: 0 10px; border: 1px solid var(--app-border-soft); border-radius: var(--app-radius-sm); background: #fff; color: var(--app-ink-body); font: inherit; font-size: 13px; font-weight: 650; cursor: pointer; }
.mode-trigger:hover { background: #f8fbff; border-color: #bfdbfe; color: var(--app-primary-active); }
.mode-trigger .el-icon { font-size: 12px; }
.icon-tool-btn { position: relative; width: 28px; height: 28px; min-width: 28px; display: inline-grid; place-items: center; padding: 0; border: 0; border-radius: var(--app-radius-sm); background: transparent; color: var(--app-ink-muted); cursor: pointer; transition: background 0.15s ease, color 0.15s ease; }
.icon-tool-btn:hover:not(:disabled) { background: #eef4ff; color: var(--app-ink); }
.icon-tool-btn.active { background: var(--app-primary-light); color: var(--app-primary-active); box-shadow: inset 0 0 0 1px rgba(37, 99, 235, 0.2); }
.icon-tool-btn.active:hover:not(:disabled) { background: #dbeafe; color: var(--app-primary); }
.icon-tool-btn:disabled { cursor: not-allowed; opacity: 0.45; }
.tool-count { position: absolute; top: -5px; right: -5px; min-width: 15px; height: 15px; padding: 0 3px; border: 2px solid #fff; border-radius: 999px; background: var(--app-primary); color: #fff; font-size: 9px; line-height: 11px; box-sizing: border-box; }
.dashboard-model-select { flex: 0 1 280px; }
.kb-picker { display: grid; gap: 6px; }
.kb-picker-item { width: 100%; min-width: 0; display: grid; grid-template-columns: 18px minmax(0, 1fr); align-items: center; gap: 8px; padding: 8px; border: 0; border-radius: var(--app-radius-sm); background: transparent; color: var(--app-ink-body); text-align: left; cursor: pointer; }
.kb-picker-item:hover, .kb-picker-item.selected { background: #f0f7ff; color: var(--app-primary-active); }
.kb-picker-item .el-icon { color: var(--app-primary-active); }
.kb-picker-item span { min-width: 0; display: grid; gap: 2px; }
.kb-picker-item strong, .kb-picker-item small { overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.kb-picker-item strong { font-size: 13px; }
.kb-picker-item small, .kb-picker-empty { color: var(--app-ink-muted); font-size: 12px; }
.kb-picker-clear { justify-self: start; padding: 5px 7px; border: 0; border-radius: var(--app-radius-sm); background: transparent; color: var(--app-primary-active); cursor: pointer; font-size: 12px; }
.suggestion-row { width: min(820px, 100%); display: flex; justify-content: center; gap: 8px; flex-wrap: wrap; }
.suggestion-row button { max-width: 100%; border: 1px solid var(--app-border-soft); border-radius: var(--app-radius-pill); background: rgba(255, 255, 255, 0.86); color: var(--app-ink-body); padding: 8px 12px; font: inherit; font-size: 13px; cursor: pointer; }
.suggestion-row button:hover { border-color: #bfdbfe; color: var(--app-primary-active); }
.dashboard-section { display: grid; gap: 14px; }
.section-heading { display: flex; align-items: flex-end; justify-content: space-between; gap: 12px; }
.stat-grid { display: grid; grid-template-columns: repeat(5, minmax(0, 1fr)); gap: 12px; }
.module-card-grid { display: grid; grid-template-columns: repeat(5, minmax(0, 1fr)); gap: 12px; }
.module-card { min-width: 0; display: grid; gap: 12px; padding: 14px; border: 1px solid var(--app-border); border-radius: var(--app-radius-md); background: #fff; color: inherit; text-align: left; cursor: pointer; transition: border-color 0.18s ease, box-shadow 0.18s ease, transform 0.18s ease; }
.module-card:hover { border-color: #bfdbfe; box-shadow: 0 10px 22px rgba(37, 99, 235, 0.08); transform: translateY(-1px); }
.module-card:focus-visible { outline: 3px solid var(--app-primary-light); outline-offset: 2px; }
.module-card-header { display: grid; grid-template-columns: 42px minmax(0, 1fr); gap: 10px; align-items: start; }
.module-card-icon { width: 42px; height: 42px; display: grid; place-items: center; border-radius: var(--app-radius-sm); background: color-mix(in srgb, var(--card-accent) 12%, white); color: var(--card-accent); }
.module-card-title-group { min-width: 0; display: grid; gap: 4px; }
.module-card-title-group strong { color: var(--app-ink); font-size: 15px; }
.module-card-title-group span { display: -webkit-box; overflow: hidden; color: var(--app-ink-muted); font-size: 12px; line-height: 1.55; -webkit-line-clamp: 2; -webkit-box-orient: vertical; }
.module-card-body { display: grid; gap: 5px; }
.module-card-body span { display: inline-flex; align-items: center; gap: 5px; color: var(--app-ink-body); font-size: 12px; }
.module-card-body .el-icon { color: var(--card-accent); }
.command-grid { grid-template-columns: minmax(0, 1.1fr) minmax(320px, 0.9fr); align-items: start; }
.command-panel { padding: 16px; min-height: 320px; }
.command-panel-header { display: flex; justify-content: space-between; gap: 12px; margin-bottom: 14px; }
.attention-list, .service-health-list { display: grid; gap: 10px; }
.attention-item, .service-health-item { width: 100%; display: grid; grid-template-columns: minmax(0, 1fr) auto; align-items: center; gap: 12px; padding: 12px; border: 1px solid var(--app-border-soft); border-radius: var(--app-radius-sm); background: #fff; text-align: left; }
.attention-item { cursor: pointer; }
.attention-item:hover { border-color: #bfdbfe; background: #f8fbff; }
.attention-item span, .service-health-item span { min-width: 0; display: grid; gap: 3px; }
.attention-item strong, .service-health-item strong { overflow: hidden; color: var(--app-ink); font-size: 13px; text-overflow: ellipsis; white-space: nowrap; }
.attention-item small, .service-health-item small { overflow: hidden; color: var(--app-ink-muted); font-size: 12px; text-overflow: ellipsis; white-space: nowrap; }
@media (max-width: 1280px) {
  .stat-grid { grid-template-columns: repeat(3, minmax(0, 1fr)); }
  .module-card-grid { grid-template-columns: repeat(3, minmax(0, 1fr)); }
}
@media (max-width: 900px) {
  .dashboard-switchbar { justify-content: center; }
  .lui-hero { min-height: auto; padding: 24px 0 18px; }
  h1 { font-size: 30px; }
  .composer-toolbar, .section-heading, .command-panel-header { align-items: stretch; flex-direction: column; }
  .composer-left-tools, .composer-actions { justify-content: space-between; }
  .dashboard-model-select { width: 100%; }
  .stat-grid, .module-card-grid, .command-grid { grid-template-columns: 1fr; }
}
@media (max-width: 560px) {
  h1 { font-size: 25px; }
  .lui-composer { padding: 10px; }
  .composer-input { grid-template-columns: 1fr; }
  .composer-mark { display: none; }
  .stat-grid { grid-template-columns: 1fr; }
}
</style>
