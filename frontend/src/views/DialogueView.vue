<script setup>
import { computed, nextTick, onMounted, onUnmounted, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { ElMessage, ElMessageBox } from 'element-plus'
import {
  ArrowDown,
  ChatLineRound,
  Cpu,
  Delete,
  EditPen,
  Expand,
  Fold,
  FolderOpened,
  Plus,
  Promotion,
  Reading,
  RefreshRight,
  Search,
  Tools,
  Upload,
} from '@element-plus/icons-vue'

import {
  cancelAssistantToolCall,
  cancelAssistantRun,
  confirmAssistantToolCall,
  createAssistantChat,
  createAssistantRun,
  createAssistantToolCall,
  deleteAssistantChat,
  downloadArtifact,
  getApiErrorMessage,
  getAssistantChat,
  getAssistantToolCall,
  getActiveAssistantRun,
  getAssistantRun,
  getLlmModels,
  listAgentTools,
  listAssistantChats,
  listAssistantRuns,
  listKnowledgeSystems,
  streamAssistantRunEvents,
  updateAssistantChat,
  updateAssistantToolCallInput,
  uploadAssistantToolCallInput,
} from '../api/polyAgentApi'
import GlobeIcon from '../components/GlobeIcon.vue'
import LlmModelSelect from '../components/LlmModelSelect.vue'
import ToolMenuPicker from '../components/ToolMenuPicker.vue'
import {
  applyToolCallEvent,
  buildToolCallConfirmPayload,
  canEditToolCall,
  mergeToolCalls,
  normalizeToolCall,
  parseToolArguments,
  replaceToolCall,
  normalizeSchemaArguments,
  toolCallRunDetailRoute,
  toolPhaseLabel,
  toolPhaseTagType,
} from '../utils/assistantToolCalls.mjs'
import {
  assistantContextLabel,
  assistantContextTooltip,
} from '../utils/assistantContext.js'
import { replayAssistantEvents } from '../utils/assistantEvents.js'
import {
  capabilitySourceLabel,
  contextSectionRows,
  contextToolRows,
  formatContextWindow,
  formatUsage,
  modelMetaLabel,
  normalizeAssistantRoute,
  routeCapabilityLabels,
  routeReasonLabel,
  toolArgumentDiff,
  toolCapableModelOptions,
  toolProtocolLabel,
  toolTimelineRows,
} from '../utils/assistantUi.mjs'
import AlgorithmResultView from './vertical-prediction/AlgorithmResultView.vue'
import { downloadArtifactToBrowser } from '../utils/artifactDownload.mjs'
import {
  loadHistoryPanelPreference,
  loadKnowledgePreference,
  loadWebSearchPreference,
  saveHistoryPanelPreference,
  saveKnowledgePreference,
  saveWebSearchPreference,
} from '../utils/dialoguePreferences'
import { buildSelectableLlmModels, resolveDefaultModelSelection } from '../utils/llmModels'

const route = useRoute()
const router = useRouter()
const bodyRef = ref(null)
const inputText = ref('')
const runStates = ref(new Map())
const runSubscriptions = new Map()
const toolCallPollers = new Map()
const continuedToolCalls = new Set()
const confirmingCallId = ref('')
const modelLoading = ref(false)
const modelSelectionOrigin = ref('')
const initialUrlModel = ref(null)
const runContexts = ref(new Map())
const knowledgeLoading = ref(false)
const chatMode = ref(normalizeMode(route.query.mode))
const llmCatalog = ref({ providers: [], routing: {} })
const knowledgeSystems = ref([])
const agentTools = ref([])
const agentToolsLoading = ref(false)
const selectedModelKey = ref('')
const selectedKnowledgeBaseIds = ref(loadKnowledgePreference())
const selectedToolIds = ref([])
const useWebSearch = ref(loadWebSearchPreference())
const chatId = ref(normalizeQueryString(route.params.chatId))
const userMessageId = ref('')
const chatHistory = ref([])
const historyQuery = ref('')
const historyLoading = ref(false)
const historyArchived = ref(false)
const historyPanelVisible = ref(loadHistoryPanelPreference())
const activeRunStatuses = new Set(['queued', 'running'])
const currentRun = computed(() => runStates.value.get(chatId.value) || null)
const activeUserRun = computed(() => [...runStates.value.values()].find((run) => activeRunStatuses.has(run.status)) || null)
const currentRunActive = computed(() => activeRunStatuses.has(currentRun.value?.status))
const userHasActiveRun = computed(() => Boolean(activeUserRun.value))
const composerBusy = computed(() => userHasActiveRun.value)

function defaultMessages() {
  return [{
    role: 'assistant',
    content: '你好！我是 PolyAgent 产品内助手，可以帮你定位页面入口、确认 ResearchEngine 算法清单、提交计算任务和处理 AutoResearch 审批。',
    actions: [{ label: '进入 ResearchEngine', target: '/research-engine', type: 'route' }],
    references: [],
    suggested_questions: ['哪些算法是真实适配器？', '如何开始一个 ResearchEngine 示例？', '如何查看待审批任务？'],
  }]
}

const messages = ref(defaultMessages())

const chatModeOptions = [
  { label: '科研问答', value: 'qa' },
  { label: '深度思考', value: 'deep' },
]

const selectableModels = computed(() =>
  buildSelectableLlmModels(llmCatalog.value, {
    dedupeByModelId: true,
    preferredPurpose: routePurpose(),
  }),
)

const selectedModel = computed(() => selectableModels.value.find((item) => item.key === selectedModelKey.value) || null)
const selectedModelLacksToolCalling = computed(() =>
  Boolean(
    selectedToolIds.value.length
      && selectedModel.value
      && !selectedModel.value.capabilities.includes('tool_calling'),
  ))
const toolCapableModelChoices = computed(() =>
  toolCapableModelOptions(selectableModels.value),
)
const selectedKnowledgeBases = computed(() =>
  selectedKnowledgeBaseIds.value
    .map((systemId) => knowledgeSystems.value.find((item) => item.system_id === systemId))
    .filter(Boolean),
)
const hasKnowledgeBase = computed(() => Boolean(selectedKnowledgeBases.value.length))
const selectedToolSummary = computed(() =>
  (agentTools.value || []).filter((tool) => selectedToolIds.value.includes(tool.tool_id)),
)
const conversationStarted = computed(() => messages.value.some((item) => item.role === 'user'))

const currentSuggestions = computed(() => {
  const latestAssistant = [...messages.value].reverse().find((item) => item.role === 'assistant')
  return latestAssistant?.suggested_questions?.length
    ? latestAssistant.suggested_questions
    : ['哪些算法是真实适配器？', '如何上传垂类预测模型？', '如何查看待审批任务？']
})

const answerModeLabelMap = {
  llm_project_grounded: '项目事实+LLM',
  web_grounded: '网页证据+LLM',
  hybrid_grounded: '混合证据+LLM',
  fallback: '兜底回答',
}

const retrievalStatusLabelMap = {
  not_needed: '无需检索',
  skipped_disabled: '全局检索未启用',
  searched: '已检索证据',
  no_results: '无检索结果',
  failed: '检索失败',
}

function normalizeQueryString(value) {
  return Array.isArray(value) ? value[0] || '' : value || ''
}

function normalizeMode(value) {
  const mode = normalizeQueryString(value)
  return ['qa', 'deep', 'model'].includes(mode) ? mode : 'qa'
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

function cleanInitialQuery() {
  if (!route.query.prompt && !route.query.mode && !route.query.providerId && !route.query.modelId && !route.query.toolIds && !route.query.history) return
  const query = { ...route.query }
  delete query.prompt
  delete query.mode
  delete query.providerId
  delete query.modelId
  delete query.toolIds
  delete query.history
  router.replace({ path: route.path, query })
}

function routePurpose() {
  return chatMode.value === 'deep' ? 'deep' : 'qa'
}

function selectedModelKeyExists(key) {
  return Boolean(key) && selectableModels.value.some((item) => item.key === key)
}

function selectDefaultModelForMode(chatModel = null) {
  if (['user', 'url'].includes(modelSelectionOrigin.value) && selectedModelKeyExists(selectedModelKey.value)) return
  const selection = resolveDefaultModelSelection(selectableModels.value, {
    urlModel: initialUrlModel.value,
    chatModel,
    routing: llmCatalog.value.routing || {},
    purpose: routePurpose(),
  })
  selectedModelKey.value = selection.key
  modelSelectionOrigin.value = selection.origin
}

function handleModelManualChange() {
  if (selectedModelKey.value) modelSelectionOrigin.value = 'user'
}

function switchToToolCapableModel() {
  const target = toolCapableModelChoices.value[0]
  if (!target) return
  selectedModelKey.value = target.key
  modelSelectionOrigin.value = 'user'
}

async function loadLlmModels() {
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

async function loadKnowledgeBases() {
  knowledgeLoading.value = true
  try {
    const data = await listKnowledgeSystems()
    knowledgeSystems.value = data?.items || []
    if (selectedKnowledgeBaseIds.value.length) {
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

function chatOptionsPayload() {
  return {
    model: selectedModelContext() || {},
    mode: chatMode.value,
    knowledge_base_ids: selectedKnowledgeBaseIds.value,
    knowledge_base_names: selectedKnowledgeBases.value.map((item) => item.name),
    use_web_search: Boolean(useWebSearch.value),
    selected_tool_ids: selectedToolIds.value,
  }
}

async function loadChatHistory() {
  historyLoading.value = true
  try {
    const data = await listAssistantChats({ query: historyQuery.value || undefined, archived: historyArchived.value })
    chatHistory.value = data?.items || []
  } catch (error) {
    ElMessage.warning(`历史会话加载失败：${getApiErrorMessage(error)}`)
  } finally {
    historyLoading.value = false
  }
}

function toggleHistoryPanel() {
  historyPanelVisible.value = !historyPanelVisible.value
  saveHistoryPanelPreference(historyPanelVisible.value)
}

function restoreMessage(item) {
  return {
    ...item,
    actions: item.actions || [],
    references: item.references || [],
    suggested_questions: item.suggested_questions || [],
    reasoning_summary: item.reasoning_summary || [],
    tool_calls: (item.tool_calls || []).map((call) => normalizeToolCall({ ...call, schema_fields: normalizeSchemaArguments(call) })),
    web_search_requested: item.web_search_requested,
    llm_route: item.metadata?.llm_route || null,
    context_digest: item.metadata?.context_digest || null,
    run_id: item.metadata?.run_id || null,
    context_manifest: item.metadata?.context_manifest || null,
    tool_schema: item.metadata?.tool_schema || [],
    tool_catalog: item.metadata?.tool_catalog || [],
    streaming: false,
    error: false,
  }
}

function toolCallFields(call) {
  return call?.schema_fields?.length ? call.schema_fields : normalizeSchemaArguments(call)
}

function toolProposalModelLabel(call) {
  const route = normalizeAssistantRoute(call?.proposal_route)
  return route.model_id ? modelMetaLabel(route) : ''
}

function toolArgumentDiffResult(call) {
  return toolArgumentDiff(call)
}

function toolValueText(value) {
  try {
    return JSON.stringify(value)
  } catch {
    return String(value)
  }
}

function toolCallTimeline(call) {
  return toolTimelineRows(call)
}

function setToolArgument(call, field, value) {
  const next = { ...(call.arguments || {}) }
  if (field.type === 'number' || field.type === 'integer') {
    next[field.key] = value === '' ? '' : Number(value)
  } else if (field.type === 'boolean') {
    next[field.key] = Boolean(value)
  } else if (field.type === 'array' || field.type === 'object') {
    try { next[field.key] = JSON.parse(value || (field.type === 'array' ? '[]' : '{}')) } catch { next[field.key] = value }
  } else next[field.key] = value
  call.arguments = next
  call.arguments_text = JSON.stringify(next, null, 2)
  call.schema_fields = normalizeSchemaArguments(call)
}

function stopToolCallPolling(callId) {
  const timer = toolCallPollers.get(callId)
  if (timer) clearInterval(timer)
  toolCallPollers.delete(callId)
}

function startToolCallPolling(message, call) {
  if (!call?.call_id || !['queued', 'running'].includes(call.phase) || toolCallPollers.has(call.call_id)) return
  const poll = async () => {
    try {
      const updated = await getAssistantToolCall(call.call_id)
      replaceToolCall(message, { ...updated, schema_fields: normalizeSchemaArguments(updated) })
      if (['completed', 'failed', 'canceled'].includes(updated.phase)) {
        stopToolCallPolling(call.call_id)
        if (updated.phase === 'completed' && !continuedToolCalls.has(call.call_id)) {
          continuedToolCalls.add(call.call_id)
          await continueToolCall(updated.call_id)
        }
      }
    } catch { /* keep the last durable state and retry on the next tick */ }
  }
  poll()
  toolCallPollers.set(call.call_id, setInterval(poll, 2000))
}

function hasToolCallResultData(call) {
  if (call?.result_summary && Object.keys(call.result_summary).length) return true
  return Boolean(call?.artifact_refs?.length)
}

async function backfillCompletedToolCall(message, call) {
  if (!call?.call_id || hasToolCallResultData(call)) return
  try {
    const updated = await getAssistantToolCall(call.call_id)
    replaceToolCall(message, { ...updated, schema_fields: normalizeSchemaArguments(updated) })
  } catch {
    // 保留会话中的持久化状态，等待下一次完整加载或用户操作。
  }
}

async function loadChat(chatKey) {
  if (!chatKey) return
  try {
    const data = await getAssistantChat(chatKey)
    chatId.value = data.chat_id
    chatMode.value = normalizeMode(data.mode)
    selectedKnowledgeBaseIds.value = data.knowledge_base_ids || []
    selectedToolIds.value = data.selected_tool_ids || []
    useWebSearch.value = Boolean(data.use_web_search)
    messages.value = data.messages?.length ? data.messages.map(restoreMessage) : defaultMessages()
    for (const message of messages.value) {
      for (const call of message.tool_calls || []) {
        if (call.phase === 'completed') await backfillCompletedToolCall(message, call)
        startToolCallPolling(message, call)
      }
    }
    selectDefaultModelForMode(data.model || {})
    await loadChatRun(chatKey)
    await loadChatHistory()
    scrollToBottom()
  } catch (error) {
    ElMessage.warning(`会话恢复失败：${getApiErrorMessage(error)}`)
    await router.replace({ path: '/dialogue', query: route.query })
  }
}

async function ensureChat() {
  if (chatId.value) {
    await updateAssistantChat(chatId.value, chatOptionsPayload())
    return chatId.value
  }
  const data = await createAssistantChat(chatOptionsPayload())
  chatId.value = data.chat_id
  await router.replace({ path: `/dialogue/${encodeURIComponent(chatId.value)}`, query: route.query })
  await loadChatHistory()
  return chatId.value
}

async function createNewChat() {
  chatId.value = ''
  messages.value = defaultMessages()
  await router.push({ path: '/dialogue', query: { mode: chatMode.value } })
}

async function selectHistoryChat(item) {
  if (!item?.chat_id) return
  await router.push({ path: `/dialogue/${encodeURIComponent(item.chat_id)}` })
  await loadChat(item.chat_id)
}

async function renameHistoryChat(item) {
  try {
    const result = await ElMessageBox.prompt('输入新的会话名称', '重命名会话', {
      inputValue: item.title,
      confirmButtonText: '保存',
      cancelButtonText: '取消',
    })
    await updateAssistantChat(item.chat_id, { title: result.value })
    await loadChatHistory()
  } catch (error) {
    if (error !== 'cancel' && error !== 'close') ElMessage.error(`重命名失败：${getApiErrorMessage(error)}`)
  }
}

async function archiveHistoryChat(item) {
  try {
    await updateAssistantChat(item.chat_id, { archived: !item.archived })
    if (item.chat_id === chatId.value && !item.archived) await createNewChat()
    await loadChatHistory()
  } catch (error) {
    ElMessage.error(`归档操作失败：${getApiErrorMessage(error)}`)
  }
}

async function deleteHistoryChat(item) {
  try {
    await ElMessageBox.confirm('删除后将无法恢复该会话及其消息。', '删除会话', { type: 'warning' })
    await deleteAssistantChat(item.chat_id)
    if (item.chat_id === chatId.value) await createNewChat()
    await loadChatHistory()
  } catch (error) {
    if (error !== 'cancel' && error !== 'close') ElMessage.error(`删除失败：${getApiErrorMessage(error)}`)
  }
}

async function sendMessage() {
  await sendPrompt(inputText.value)
}

async function sendPrompt(prompt) {
  const text = String(prompt || '').trim()
  if (!text || userHasActiveRun.value) return
  try {
    await ensureChat()
  } catch (error) {
    ElMessage.error(`会话保存失败：${getApiErrorMessage(error)}`)
    return
  }
  const targetChatId = chatId.value
  const requestMessages = buildRequestMessages()
  try {
    const run = await createAssistantRun(targetChatId, {
      content: text,
      messages: requestMessages,
      context: buildAssistantContext({}),
    })
    userMessageId.value = run.user_message_id
    messages.value.push({
      role: 'user',
      content: text,
      message_id: run.user_message_id,
      tool_calls: [],
    })
    messages.value.push(runPlaceholder(run))
    inputText.value = ''
    registerRun(run)
    subscribeToRun(run)
    await loadChatHistory()
    scrollToBottom()
  } catch (error) {
    if (error.status === 409 && error.detail?.run_id) {
      ElMessage.warning('已有会话正在回答，请等待完成或先取消该回答')
      await refreshActiveRun()
    } else {
      ElMessage.error(`回答任务创建失败：${getApiErrorMessage(error)}`)
    }
  }
}

function runPlaceholder(run) {
  const replay = replayAssistantEvents(run.events || [])
  return {
    role: 'assistant', content: run.partial_content || '', reasoning_summary: [], actions: [], references: [],
    suggested_questions: [], answer_mode: '', answer_scope: '', retrieval_status: '',
    web_search_requested: Boolean(run.request_snapshot?.context?.use_web_search),
    stream_status: run.status === 'queued' ? '已进入回答队列' : '正在回答...',
    stream_stage: run.stage || run.status, streaming: activeRunStatuses.has(run.status), error: run.status === 'failed',
    llm_route: replay.route,
    context_digest: replay.context_digest,
    context_manifest: replay.context_manifest,
    tool_schema: replay.tool_schema,
    tool_catalog: replay.tool_catalog,
    tool_calls: [], pending_tool_call_ids: [], run_id: run.run_id,
  }
}

function registerRun(run) {
  if (!run?.chat_id) return
  const next = new Map(runStates.value)
  const previous = next.get(run.chat_id) || {}
  next.set(run.chat_id, { ...previous, ...run, lastSeq: run.lastSeq ?? run.event_seq ?? previous.lastSeq ?? 0 })
  runStates.value = next
  registerRunContext(run)
}

function runMessageIndex(runId) {
  return messages.value.findIndex((message) => message.run_id === runId || message.metadata?.run_id === runId)
}

function registerRunContext(run) {
  if (!run?.run_id) return
  const next = new Map(runContexts.value)
  const previous = next.get(run.run_id) || {}
  next.set(run.run_id, { ...previous, ...run })
  runContexts.value = next
}

function messageRunId(message) {
  return message?.run_id || message?.metadata?.run_id || ''
}

function messageRunContext(message) {
  const runId = messageRunId(message)
  return runId ? runContexts.value.get(runId) || null : null
}

function replayRunContext(run) {
  if (!run) return null
  return replayAssistantEvents(run.events || [])
}

function messageReplay(message) {
  const run = messageRunContext(message)
  if (run) {
    const replay = replayRunContext(run)
    if (replay?.route || replay?.context_manifest) return replay
  }
  return {
    route: message?.llm_route || null,
    context_digest: message?.context_digest || '',
    context_manifest: message?.context_manifest || null,
    context_manifests: {},
    tool_catalog: message?.tool_catalog || [],
    tool_schema: message?.tool_schema || [],
    usage: null,
  }
}

function messageRoute(message) {
  const normalized = normalizeAssistantRoute(messageReplay(message)?.route)
  return normalized.model_id ? normalized : normalizeAssistantRoute(message?.llm_route)
}

function messageUsage(message) {
  const run = messageRunContext(message)
  const runUsage = {
    prompt_tokens: run?.prompt_tokens,
    completion_tokens: run?.completion_tokens,
    total_tokens: run?.total_tokens,
  }
  return formatUsage(runUsage) || formatUsage(messageReplay(message)?.usage || {})
}

function messageContextManifest(message) {
  const replay = messageReplay(message)
  if (replay?.context_manifest) return replay.context_manifest
  const run = messageRunContext(message)
  const manifests = run?.request_manifests || {}
  return manifests.final_answer || manifests.tool_proposal || null
}

function messageContextSections(message) {
  return contextSectionRows(messageContextManifest(message))
}

function messageContextTools(message) {
  const replay = messageReplay(message)
  const schemaRows = Array.isArray(replay?.tool_schema) ? replay.tool_schema : []
  if (schemaRows.length) return schemaRows
  return contextToolRows(messageContextManifest(message))
}

function messageEvidenceReferences(message) {
  if (Array.isArray(message?.references) && message.references.length) return message.references
  return []
}

function hydrateMessagesWithRunContexts() {
  for (const message of messages.value) {
    if (message.role !== 'assistant') continue
    const replay = messageReplay(message)
    if (replay.route && !message.llm_route) message.llm_route = replay.route
    if (replay.context_digest && !message.context_digest) message.context_digest = replay.context_digest
    if (replay.context_manifest && !message.context_manifest) message.context_manifest = replay.context_manifest
    if (Array.isArray(replay.tool_schema) && !message.tool_schema?.length) message.tool_schema = replay.tool_schema
    if (Array.isArray(replay.tool_catalog) && !message.tool_catalog?.length) message.tool_catalog = replay.tool_catalog
  }
}

async function loadChatRun(chatKey) {
  try {
    const data = await listAssistantRuns(chatKey, { page_size: 200 })
    const runs = data?.items || []
    for (const item of runs) registerRunContext(item)
    const run = data?.active || runs.find((item) => activeRunStatuses.has(item.status)) || runs[0]
    if (!run) return
    registerRun(run)
    if (activeRunStatuses.has(run.status)) {
      if (runMessageIndex(run.run_id) < 0) messages.value.push(runPlaceholder(run))
      subscribeToRun(run)
    }
    hydrateMessagesWithRunContexts()
  } catch (error) {
    ElMessage.warning(`回答状态恢复失败：${getApiErrorMessage(error)}`)
  }
}

async function refreshActiveRun() {
  try {
    const run = await getActiveAssistantRun()
    if (!run) return
    registerRun(run)
    subscribeToRun(run)
  } catch {
    // The chat-level restore path will retry when the user opens the conversation.
  }
}

function applyRunEvent(run, event) {
  const current = runStates.value.get(run.chat_id) || run
  current.lastSeq = Math.max(current.lastSeq || 0, event.seq || 0)
  if (event?.seq && !(current.events || []).some((item) => Number(item?.seq) === Number(event.seq) && item?.type === event.type)) {
    current.events = [...(current.events || []), event]
  }
  if (event.type === 'run_status') {
    current.status = event.status || current.status
    current.stage = event.stage || current.stage
    current.error = event.error || current.error
  }
  if (event.type === 'reset') {
    current.status = 'queued'
    current.stage = 'queued'
    current.partial_content = ''
  }
  const next = new Map(runStates.value)
  next.set(run.chat_id, current)
  runStates.value = next
  registerRunContext(current)
  if (chatId.value !== run.chat_id) return
  const index = runMessageIndex(run.run_id)
  if (index >= 0 && event.type === 'reset') {
    Object.assign(messages.value[index], {
      content: '', streaming: true, error: false, stream_stage: 'queued',
      stream_status: event.message || '正在重新生成回答',
    })
  }
  if (index >= 0 && !['run_status', 'heartbeat'].includes(event.type)) applyAssistantStreamEvent(index, event)
  if (index >= 0 && event.type === 'run_status') {
    const target = messages.value[index]
    target.streaming = activeRunStatuses.has(event.status)
    target.stream_stage = event.stage || event.status
    target.stream_status = event.status === 'canceled' ? '回答已取消' : ''
    if (event.status === 'failed') {
      target.error = true
      target.content = target.content || `对话出错：${event.error?.message || '回答失败'}`
    }
  }
}

async function subscribeToRun(run) {
  if (!run?.run_id || runSubscriptions.has(run.run_id) || !activeRunStatuses.has(run.status)) return
  const controller = new AbortController()
  runSubscriptions.set(run.run_id, controller)
  let retries = 0
  try {
    while (!controller.signal.aborted) {
      const current = runStates.value.get(run.chat_id) || run
      if (!activeRunStatuses.has(current.status)) break
      try {
        await streamAssistantRunEvents(run.run_id, current.lastSeq || 0, (event) => applyRunEvent(run, event), controller.signal)
        retries = 0
      } catch (error) {
        if (controller.signal.aborted) break
        retries += 1
        await new Promise((resolve) => setTimeout(resolve, Math.min(1000 * (2 ** (retries - 1)), 8000)))
        const restored = await getAssistantRun(run.run_id)
        registerRun({ ...restored, lastSeq: current.lastSeq || 0 })
      }
    }
  } finally {
    runSubscriptions.delete(run.run_id)
    const latest = await getAssistantRun(run.run_id).catch(() => null)
    if (latest) registerRun(latest)
    if (latest?.status === 'completed' && chatId.value === run.chat_id) await loadChat(run.chat_id)
  }
}

async function cancelCurrentRun() {
  if (!currentRunActive.value) return
  try {
    const run = await cancelAssistantRun(currentRun.value.run_id)
    registerRun(run)
    applyRunEvent(run, { type: 'run_status', status: run.status, stage: run.stage, seq: run.event_seq })
  } catch (error) {
    ElMessage.error(`取消失败：${getApiErrorMessage(error)}`)
  }
}

function buildAssistantContext(extra = {}) {
  return {
    current_route: router.currentRoute.value.fullPath,
    page: 'dialogue',
    mode: chatMode.value,
    use_web_search: Boolean(useWebSearch.value),
    use_knowledge_base: hasKnowledgeBase.value,
    knowledge_base_ids: selectedKnowledgeBases.value.map((item) => item.system_id),
    knowledge_base_names: selectedKnowledgeBases.value.map((item) => item.name),
    knowledge_base_id: selectedKnowledgeBases.value[0]?.system_id || '',
    knowledge_base_name: selectedKnowledgeBases.value[0]?.name || '',
    model: selectedModelContext(),
    chat_id: chatId.value,
    message_id: userMessageId.value,
    selected_tool_ids: selectedToolIds.value,
    ...extra,
  }
}

async function continueToolCall(callId) {
  if (composerBusy.value) return
  const targetChatId = chatId.value
  try {
    const run = await createAssistantRun(targetChatId, {
      content: '',
      user_message_id: userMessageId.value,
      messages: buildRequestMessages(),
      context: buildAssistantContext({ tool_call_ids: [callId] }),
    })
    messages.value.push(runPlaceholder(run))
    registerRun(run)
    subscribeToRun(run)
    scrollToBottom()
  } catch (error) {
    ElMessage.error(`继续生成失败：${getApiErrorMessage(error)}`)
  }
}

function buildRequestMessages() {
  return messages.value
    .filter((message) => {
      const content = String(message.content || '').trim()
      if (!content) return false
      if (!['assistant', 'user'].includes(message.role)) return false
      if (message.streaming) return false
      if (isAssistantErrorMessage(message)) return false
      return true
    })
    .map((message) => ({ role: message.role, content: message.content }))
}

function isAssistantErrorMessage(message) {
  if (message.role !== 'assistant') return false
  if (message.error || message.stream_stage === 'error') return true
  return /^对话出错[:：]/.test(String(message.content || '').trim())
}

function selectedModelContext() {
  if (selectedModel.value) {
    return { providerId: selectedModel.value.providerId, modelId: selectedModel.value.modelId }
  }
  const key = String(selectedModelKey.value || '')
  const separatorIndex = key.indexOf('::')
  if (separatorIndex <= 0) return null
  const providerId = key.slice(0, separatorIndex)
  const modelId = key.slice(separatorIndex + 2)
  return providerId && modelId ? { providerId, modelId } : null
}

function applyAssistantStreamEvent(index, event) {
  const target = messages.value[index]
  if (!target || !event) return ''
  if (event.type === 'tool_call' || event.type === 'tool_input_required') {
    applyToolCallEvent(findToolCallMessage(event.call_id) || messages.value[index - 1], event)
    return ''
  }
  if (event.type === 'route.resolved' || event.type === 'route.fallback') {
    target.llm_route = event.route || target.llm_route
    if (event.type === 'route.fallback' && event.reason) {
      target.llm_route = { ...(target.llm_route || {}), fallback_reason: event.reason }
    }
    return ''
  }
  if (event.type === 'context.assembled' || event.type === 'request.header') {
    target.context_digest = event.manifest?.context?.digest || target.context_digest
    target.context_manifest = event.manifest || target.context_manifest
    return ''
  }
  if (event.type === 'tool.catalog.resolved') {
    target.tool_catalog = event.tools || target.tool_catalog || []
    return ''
  }
  if (event.type === 'tool.schema.rendered') {
    target.tool_schema = event.tools || target.tool_schema || []
    return ''
  }
  if (event.type === 'llm.usage.recorded') {
    target.usage = event.usage || target.usage
    return ''
  }
  if (event.type === 'status') {
    target.stream_status = event.message || ''
    target.stream_stage = event.stage || ''
    return ''
  }
  if (event.type === 'evidence') {
    target.retrieval_status = event.status || target.retrieval_status
    target.stream_status = event.message || target.stream_status
    if (Array.isArray(event.references) && event.references.length) {
      target.references = mergeAssistantReferences(target.references, event.references)
    }
    return ''
  }
  if (event.type === 'reasoning_summary_delta') {
    const item = String(event.item || '').trim()
    if (item && !target.reasoning_summary.includes(item)) target.reasoning_summary.push(item)
    return ''
  }
  if (event.type === 'answer_delta') {
    target.content += event.delta || ''
    return ''
  }
  if (event.type === 'final') {
    const data = event.data || {}
    Object.assign(target, {
      content: data.content || target.content || '抱歉，未能获得有效回复。',
      reasoning_summary: data.reasoning_summary || target.reasoning_summary || [],
      actions: data.actions || [],
      references: data.references || target.references || [],
      suggested_questions: data.suggested_questions || [],
      answer_mode: data.answer_mode || '',
      answer_scope: data.answer_scope || '',
      retrieval_status: data.retrieval_status || target.retrieval_status || '',
      llm_route: data.grounding_facts?.llm_route || target.llm_route || null,
      context_digest: data.grounding_facts?.context?.digest || target.context_digest || null,
      stream_status: '',
      stream_stage: '',
      streaming: false,
      error: false,
    })
    const calls = Array.isArray(data.tool_calls) ? data.tool_calls : []
    if (calls.length) {
      target.pending_tool_call_ids = calls.map((call) => call.call_id)
      const userMessage = messages.value[index - 1]
      if (userMessage) {
        userMessage.tool_calls = mergeToolCalls(userMessage.tool_calls, calls)
      }
    }
    return ''
  }
  if (event.type === 'error') {
    const message = event.message || '流式对话失败'
    target.content = target.content || `对话出错：${message}`
    target.stream_status = ''
    target.stream_stage = 'error'
    target.streaming = false
    target.error = true
    return message
  }
  return ''
}

function findToolCallMessage(callId) {
  if (!callId) return null
  for (const message of messages.value) {
    if ((message.tool_calls || []).some((call) => call.call_id === callId)) return message
  }
  return null
}

async function updateToolCallArguments(message, call) {
  const result = parseToolArguments(call.arguments_text)
  if (!result.ok) {
    ElMessage.error(result.error)
    return
  }
  try {
    const updated = await updateAssistantToolCallInput(call.call_id, { arguments: result.arguments })
    replaceToolCall(message, { ...updated, schema_fields: normalizeSchemaArguments(updated) })
    ElMessage.success('参数已更新')
  } catch (error) {
    ElMessage.error(`参数更新失败：${getApiErrorMessage(error)}`)
  }
}

async function uploadToolCallAsset(message, call, assetKey, event) {
  const file = event.target.files?.[0]
  if (!file) return
  const formData = new FormData()
  formData.append(assetKey, file)
  try {
    const updated = await uploadAssistantToolCallInput(call.call_id, formData)
    replaceToolCall(message, { ...updated, schema_fields: normalizeSchemaArguments(updated) })
    ElMessage.success('附件已上传')
  } catch (error) {
    ElMessage.error(`附件上传失败：${getApiErrorMessage(error)}`)
  }
  event.target.value = ''
}

async function confirmToolCall(message, call) {
  if (confirmingCallId.value === call.call_id) return
  const payload = buildToolCallConfirmPayload(call)
  if (!payload.ok) {
    ElMessage.error(payload.error)
    return
  }
  confirmingCallId.value = call.call_id
  try {
    const updated = await confirmAssistantToolCall(call.call_id, payload.payload)
    replaceToolCall(message, { ...updated, schema_fields: normalizeSchemaArguments(updated) })
    if (['queued', 'running'].includes(updated.phase)) {
      startToolCallPolling(message, updated)
      ElMessage.info(updated.phase === 'queued' ? '算法已提交，正在排队' : '算法运行中')
    } else if (updated.phase === 'completed') {
      ElMessage.success('算法运行完成')
    }
  } catch (error) {
    const detail = error?.detail
    const missingFields = Array.isArray(detail?.missing_fields) ? detail.missing_fields : []
    const missingAssets = Array.isArray(detail?.missing_assets) ? detail.missing_assets : []
    if (detail?.code === 'TOOL_INPUT_REQUIRED' || missingFields.length || missingAssets.length) {
      replaceToolCall(message, {
        ...call,
        phase: 'awaiting_input',
        missing_fields: missingFields,
        required_assets: missingAssets.map((key) => ({ key, required: true, accept: '' })),
      })
      const hint = [...missingFields, ...missingAssets.map((key) => `附件：${key}`)].join('、')
      ElMessage.warning(`请先补充参数后再次确认：${hint || '存在必填输入'}`)
    } else {
      ElMessage.error(`确认执行失败：${getApiErrorMessage(error)}`)
    }
  } finally {
    confirmingCallId.value = ''
  }
}

async function cancelToolCall(message, call) {
  try {
    const updated = await cancelAssistantToolCall(call.call_id)
    replaceToolCall(message, updated)
    ElMessage.info('算法调用已取消')
  } catch (error) {
    ElMessage.error(`取消失败：${getApiErrorMessage(error)}`)
  }
}

async function retryToolCall(message, call) {
  try {
    const created = await createAssistantToolCall({
      tool_id: call.tool_id,
      chat_id: chatId.value,
      message_id: message.message_id,
      arguments: call.arguments || {},
      input_asset_refs: call.input_asset_refs || {},
    })
    replaceToolCall(message, created)
    ElMessage.success('已重新发起算法调用')
  } catch (error) {
    ElMessage.error(`重新发起失败：${getApiErrorMessage(error)}`)
  }
}

async function downloadToolArtifact(ref) {
  const artifactId = ref?.artifact_id || ref?.id
  if (!artifactId) return
  try {
    await downloadArtifactToBrowser({
      artifactId,
      fallbackName: ref?.name || 'artifact.dat',
      download: downloadArtifact,
    })
  } catch (error) {
    ElMessage.error(`下载失败：${getApiErrorMessage(error)}`)
  }
}

function visibleToolArtifactRefs(call) {
  return (call?.artifact_refs || []).filter((ref) => ref?.name !== '运行结果')
}

function currentModeLabel() {
  return chatModeOptions.find((item) => item.value === chatMode.value)?.label || '科研问答'
}

function webSearchRequestLabel(message) {
  if (message.web_search_requested === true) return '联网开启'
  if (message.web_search_requested === false) return '联网关闭'
  return ''
}

function assistantModelLabel(message) {
  const routeInfo = messageRoute(message)
  if (!routeInfo.model_id) return ''
  const label = modelMetaLabel(routeInfo)
  return routeInfo.capabilities.includes('tool_calling') ? `${label} · 工具` : label
}

function assistantModelDetailRows(message) {
  const routeInfo = messageRoute(message)
  if (!routeInfo.model_id) return []
  const rows = [
    { label: 'Provider', value: routeInfo.provider_id || routeInfo.provider_type || '未记录' },
    { label: '模型', value: routeInfo.model_id },
    { label: '路由原因', value: routeReasonLabel(routeInfo.route_reason) || '未记录' },
    { label: '能力', value: routeCapabilityLabels(routeInfo).join('、') || '未记录' },
    { label: '能力来源', value: capabilitySourceLabel(routeInfo.capability_source) || '未记录' },
    { label: '工具协议', value: toolProtocolLabel(routeInfo.tool_protocol) || '未记录' },
    { label: '上下文窗口', value: formatContextWindow(routeInfo.context_window) || '未记录' },
  ]
  if (routeInfo.max_output_tokens) rows.push({ label: '最大输出', value: routeInfo.max_output_tokens })
  if (routeInfo.fallback_reason) rows.push({ label: '兜底原因', value: routeInfo.fallback_reason })
  return rows
}

function assistantUsageLabel(message) {
  return messageUsage(message)
}

function webSearchRequestTagType(message) {
  return message.web_search_requested ? 'primary' : 'info'
}

function retrievalStatusTagType(status) {
  if (status === 'searched') return 'success'
  if (status === 'failed') return 'danger'
  if (status === 'skipped_disabled') return 'warning'
  return 'info'
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

function mergeAssistantReferences(current = [], incoming = []) {
  const merged = []
  const seen = new Set()
  for (const item of [...current, ...incoming]) {
    const key = `${item.type || ''}|${item.target || ''}|${item.label || ''}`
    if (!item.label || seen.has(key)) continue
    seen.add(key)
    merged.push(item)
  }
  return merged
}

function scrollToBottom() {
  nextTick(() => {
    if (bodyRef.value) bodyRef.value.scrollTop = bodyRef.value.scrollHeight
  })
}

function openAssistantAction(action) {
  if (action?.target) router.push(action.target)
}

function openAssistantReference(ref) {
  if (!ref?.target) return
  if (ref.type === 'web' || /^https?:\/\//i.test(ref.target)) {
    window.open(ref.target, '_blank', 'noopener,noreferrer')
    return
  }
  if (ref.type === 'route' || ref.target.startsWith('/')) {
    router.push(ref.target)
    return
  }
  ElMessage.info(`来源：${ref.target}`)
}

function handleComposerKeydown(event) {
  if (event.key === 'Enter' && !event.shiftKey) {
    event.preventDefault()
    sendMessage()
  }
}

function markdownBlocks(text) {
  const lines = String(text || '').split('\n')
  const blocks = []
  let paragraph = []
  let list = []
  let listOrdered = false
  let code = []
  let table = []
  let inCode = false
  const flushParagraph = () => {
    if (paragraph.length) {
      blocks.push({ type: 'paragraph', text: paragraph.join(' ') })
      paragraph = []
    }
  }
  const flushList = () => {
    if (list.length) {
      blocks.push({ type: 'list', items: list, ordered: listOrdered })
      list = []
      listOrdered = false
    }
  }
  const flushTable = () => {
    if (table.length) {
      blocks.push({ type: 'table', rows: table })
      table = []
    }
  }
  const flushTextBlocks = () => {
    flushParagraph()
    flushList()
    flushTable()
  }
  for (const line of lines) {
    if (line.trim().startsWith('```')) {
      if (inCode) {
        blocks.push({ type: 'code', text: code.join('\n') })
        code = []
        inCode = false
      } else {
        flushTextBlocks()
        inCode = true
      }
      continue
    }
    if (inCode) {
      code.push(line)
      continue
    }
    if (!line.trim()) {
      flushTextBlocks()
      continue
    }
    const tableRow = parseMarkdownTableRow(line)
    if (tableRow) {
      flushParagraph()
      flushList()
      if (!isMarkdownTableDivider(tableRow)) table.push(tableRow)
      continue
    }
    flushTable()
    const heading = line.match(/^(#{1,3})\s+(.+)$/)
    if (heading) {
      flushParagraph()
      flushList()
      blocks.push({ type: 'heading', level: heading[1].length, text: heading[2] })
      continue
    }
    const listItem = line.match(/^\s*[-*•]\s+(.+)$/)
    if (listItem) {
      flushParagraph()
      if (list.length && listOrdered) flushList()
      listOrdered = false
      list.push(listItem[1])
      continue
    }
    const orderedListItem = line.match(/^\s*\d+[.)]\s+(.+)$/)
    if (orderedListItem) {
      flushParagraph()
      if (list.length && !listOrdered) flushList()
      listOrdered = true
      list.push(orderedListItem[1])
      continue
    }
    paragraph.push(line.trim())
  }
  flushParagraph()
  flushList()
  flushTable()
  if (code.length) blocks.push({ type: 'code', text: code.join('\n') })
  return blocks
}

function parseMarkdownTableRow(line) {
  const trimmed = String(line || '').trim()
  if (!trimmed.includes('|')) return null
  const cells = trimmed
    .replace(/^\|/, '')
    .replace(/\|$/, '')
    .split('|')
    .map((cell) => cell.trim())
  return cells.length >= 2 ? cells : null
}

function isMarkdownTableDivider(cells) {
  return cells.every((cell) => /^:?-{3,}:?$/.test(cell))
}

function inlineSegments(text) {
  const parts = String(text || '').split(/(\*\*[^*]+\*\*)/g)
  return parts.filter(Boolean).map((part) => {
    if (part.startsWith('**') && part.endsWith('**')) return { strong: true, text: part.slice(2, -2) }
    return { strong: false, text: part }
  })
}

onMounted(() => {
  const initialPrompt = normalizeQueryString(route.query.prompt).trim()
  const initialProviderId = normalizeQueryString(route.query.providerId).trim()
  const initialModelId = normalizeQueryString(route.query.modelId).trim()
  const initialToolIds = String(route.query.toolIds || '')
    .split(',')
    .map((item) => item.trim())
    .filter(Boolean)
  selectedToolIds.value = initialToolIds
  chatMode.value = normalizeMode(route.query.mode)
  initialUrlModel.value = initialProviderId && initialModelId
    ? { providerId: initialProviderId, modelId: initialModelId }
    : null
  if (route.query.history === 'open') {
    historyPanelVisible.value = true
  }
  cleanInitialQuery()
  Promise.all([
    loadLlmModels(),
    loadKnowledgeBases(),
    loadAgentTools(),
  ]).then(async () => {
    await refreshActiveRun()
    if (chatId.value) await loadChat(chatId.value)
    await loadChatHistory()
    if (initialPrompt) await sendPrompt(initialPrompt)
  })
})

watch(
  [chatMode, selectedModelKey, selectedKnowledgeBaseIds, useWebSearch],
  async () => {
    if (!chatId.value || currentRunActive.value) return
    try {
      await updateAssistantChat(chatId.value, chatOptionsPayload())
      await loadChatHistory()
    } catch {
      // The next message save retries the session options if this background update fails.
    }
  },
  { deep: true },
)

onUnmounted(() => {
  for (const controller of runSubscriptions.values()) controller.abort()
  runSubscriptions.clear()
  for (const callId of toolCallPollers.keys()) stopToolCallPolling(callId)
  continuedToolCalls.clear()
})

watch(
  () => route.params.chatId,
  async (value) => {
    const nextChatId = normalizeQueryString(value)
    if (nextChatId && nextChatId !== chatId.value) await loadChat(nextChatId)
    if (!nextChatId && chatId.value) {
      chatId.value = ''
      messages.value = defaultMessages()
    }
  },
)
</script>

<template>
  <div class="dialogue-page" :class="{ 'history-docked': !historyPanelVisible }">
    <aside class="dialogue-history" :class="{ docked: !historyPanelVisible }" aria-label="历史会话">
      <template v-if="historyPanelVisible">
        <div class="history-header">
          <strong>历史会话</strong>
          <div class="history-header-actions">
            <el-tooltip content="收起历史会话" placement="right">
              <el-button circle text :icon="Fold" aria-label="收起历史会话" :aria-expanded="true" @click="toggleHistoryPanel" />
            </el-tooltip>
            <el-tooltip content="新建会话" placement="right">
              <el-button circle text :icon="Plus" aria-label="新建会话" @click="createNewChat" />
            </el-tooltip>
          </div>
        </div>
        <el-input
          v-model="historyQuery"
          size="small"
          clearable
          placeholder="搜索会话"
          :prefix-icon="Search"
          @keyup.enter="loadChatHistory"
          @clear="loadChatHistory"
        />
        <div class="history-tabs">
          <button type="button" :class="{ active: !historyArchived }" @click="historyArchived = false; loadChatHistory()">最近</button>
          <button type="button" :class="{ active: historyArchived }" @click="historyArchived = true; loadChatHistory()">归档</button>
        </div>
        <div v-loading="historyLoading" class="history-list">
          <div v-if="!historyLoading && !chatHistory.length" class="history-empty">暂无会话</div>
          <div
            v-for="item in chatHistory"
            :key="item.chat_id"
            class="history-item"
            :class="{ active: item.chat_id === chatId }"
          >
            <button type="button" class="history-item-main" @click="selectHistoryChat(item)">
              <span class="history-item-title">{{ item.title }}</span>
              <small>{{ item.messages?.length || 0 }} 条消息</small>
            </button>
            <el-dropdown trigger="click" @command="(command) => command === 'rename' ? renameHistoryChat(item) : command === 'archive' ? archiveHistoryChat(item) : deleteHistoryChat(item)">
              <el-button text circle :icon="FolderOpened" aria-label="会话操作" />
              <template #dropdown>
                <el-dropdown-menu>
                  <el-dropdown-item command="rename"><el-icon><EditPen /></el-icon>重命名</el-dropdown-item>
                  <el-dropdown-item command="archive"><el-icon><FolderOpened /></el-icon>{{ item.archived ? '取消归档' : '归档' }}</el-dropdown-item>
                  <el-dropdown-item command="delete" divided><el-icon><Delete /></el-icon>删除</el-dropdown-item>
                </el-dropdown-menu>
              </template>
            </el-dropdown>
          </div>
        </div>
      </template>
      <el-tooltip v-else content="展开历史会话" placement="right">
        <button type="button" class="history-dock" aria-label="展开历史会话" :aria-expanded="false" @click="toggleHistoryPanel">
          <el-icon><Expand /></el-icon>
        </button>
      </el-tooltip>
    </aside>
    <header class="dialogue-header" :class="{ 'dialogue-header-centered': !conversationStarted }">
      <div>
        <p class="dialogue-kicker">Poly Agent 问答</p>
        <h1>科研任务交互问答</h1>
      </div>
    </header>

    <main ref="bodyRef" class="dialogue-body" aria-live="polite">
      <div class="message-stack">
        <div
          v-for="(msg, idx) in messages"
          :key="idx"
          class="chat-message"
          :class="msg.role === 'user' ? 'chat-message-user' : 'chat-message-assistant'"
        >
          <div class="chat-bubble">
            <div class="chat-bubble-text">
              <div v-if="msg.answer_mode || msg.retrieval_status || msg.stream_status || webSearchRequestLabel(msg) || assistantModelLabel(msg) || assistantUsageLabel(msg) || assistantContextLabel(msg)" class="chat-meta">
                <el-tag v-if="webSearchRequestLabel(msg)" size="small" effect="plain" :type="webSearchRequestTagType(msg)">
                  {{ webSearchRequestLabel(msg) }}
                </el-tag>
                <el-popover
                  v-if="assistantModelLabel(msg)"
                  trigger="click"
                  placement="top"
                  :width="380"
                  popper-class="assistant-model-detail-popper"
                >
                  <template #reference>
                    <el-tag size="small" effect="plain" type="success" class="model-meta-trigger">
                      {{ assistantModelLabel(msg) }}
                    </el-tag>
                  </template>
                  <div class="model-detail-panel">
                    <strong>本轮模型路由</strong>
                    <dl>
                      <template v-for="row in assistantModelDetailRows(msg)" :key="row.label">
                        <dt>{{ row.label }}</dt>
                        <dd>{{ row.value }}</dd>
                      </template>
                    </dl>
                  </div>
                </el-popover>
                <el-tag v-if="assistantUsageLabel(msg)" size="small" effect="plain" type="info">
                  {{ assistantUsageLabel(msg) }}
                </el-tag>
                <el-tooltip
                  v-if="assistantContextLabel(msg)"
                  :content="assistantContextTooltip(msg)"
                  placement="top"
                >
                  <el-tag size="small" effect="plain" type="success">
                    {{ assistantContextLabel(msg) }}
                  </el-tag>
                </el-tooltip>
                <el-tag v-if="msg.answer_mode" size="small" effect="plain" type="info">
                  {{ answerModeLabelMap[msg.answer_mode] || msg.answer_mode }}
                </el-tag>
                <el-tag v-if="msg.retrieval_status" size="small" effect="plain" :type="retrievalStatusTagType(msg.retrieval_status)">
                  {{ retrievalStatusLabelMap[msg.retrieval_status] || msg.retrieval_status }}
                </el-tag>
                <el-tag v-if="msg.stream_status" size="small" effect="plain" type="warning">
                  {{ msg.stream_status }}
                </el-tag>
              </div>
              <details v-if="messageContextSections(msg).length || messageContextTools(msg).length || assistantModelDetailRows(msg).length" class="assistant-context-panel">
                <summary>本轮上下文</summary>
                <div class="assistant-context-panel-body">
                  <section v-if="assistantModelDetailRows(msg).length" class="context-panel-section">
                    <h4>模型路由</h4>
                    <dl>
                      <template v-for="row in assistantModelDetailRows(msg)" :key="`context-${row.label}`">
                        <dt>{{ row.label }}</dt>
                        <dd>{{ row.value }}</dd>
                      </template>
                    </dl>
                  </section>
                  <section v-if="messageContextSections(msg).length" class="context-panel-section">
                    <h4>上下文 section</h4>
                    <div v-for="section in messageContextSections(msg)" :key="section.name" class="context-section-row">
                      <div>
                        <strong>{{ section.name }}</strong>
                        <small>{{ section.source }}</small>
                      </div>
                      <span :class="{ omitted: !section.included }">
                        {{ section.included ? `${section.token_estimate} tokens` : section.omitted_reason || '已省略' }}
                      </span>
                    </div>
                  </section>
                  <section v-if="messageContextTools(msg).length" class="context-panel-section">
                    <h4>工具 schema</h4>
                    <div v-for="tool in messageContextTools(msg)" :key="tool.tool_id || tool.function_name" class="context-tool-row">
                      <div>
                        <strong>{{ tool.tool_id || tool.function_name }}</strong>
                        <small>{{ tool.function_name }} · v{{ tool.version || '未知' }}</small>
                      </div>
                      <code>{{ tool.schema_digest ? tool.schema_digest.slice(-8) : '未记录' }}</code>
                    </div>
                  </section>
                  <section v-if="messageEvidenceReferences(msg).length" class="context-panel-section">
                    <h4>证据引用</h4>
                    <button
                      v-for="ref in messageEvidenceReferences(msg)"
                      :key="`${ref.label}-${ref.target}`"
                      type="button"
                      class="context-evidence-link"
                      @click="openAssistantReference(ref)"
                    >
                      {{ ref.label }}
                    </button>
                  </section>
                </div>
              </details>
              <details v-if="msg.reasoning_summary?.length" class="reasoning-summary">
                <summary>推理摘要</summary>
                <ol>
                  <li v-for="(item, itemIdx) in msg.reasoning_summary" :key="`${idx}-reasoning-${itemIdx}`">
                    {{ item }}
                  </li>
                </ol>
              </details>
              <template v-for="(block, blockIdx) in markdownBlocks(msg.content)" :key="blockIdx">
                <h2 v-if="block.type === 'heading'" class="markdown-heading">
                  <template v-for="(seg, segIdx) in inlineSegments(block.text)" :key="segIdx">
                    <strong v-if="seg.strong">{{ seg.text }}</strong>
                    <span v-else>{{ seg.text }}</span>
                  </template>
                </h2>
                <component :is="block.ordered ? 'ol' : 'ul'" v-else-if="block.type === 'list'" class="markdown-list">
                  <li v-for="(item, itemIdx) in block.items" :key="itemIdx">
                    <template v-for="(seg, segIdx) in inlineSegments(item)" :key="segIdx">
                      <strong v-if="seg.strong">{{ seg.text }}</strong>
                      <span v-else>{{ seg.text }}</span>
                    </template>
                  </li>
                </component>
                <div v-else-if="block.type === 'table'" class="markdown-table-wrap">
                  <table class="markdown-table">
                    <tbody>
                      <tr v-for="(row, rowIdx) in block.rows" :key="rowIdx">
                        <template v-if="rowIdx === 0">
                          <th v-for="(cell, cellIdx) in row" :key="cellIdx" scope="col">
                            <template v-for="(seg, segIdx) in inlineSegments(cell)" :key="segIdx">
                              <strong v-if="seg.strong">{{ seg.text }}</strong>
                              <span v-else>{{ seg.text }}</span>
                            </template>
                          </th>
                        </template>
                        <template v-else>
                          <td v-for="(cell, cellIdx) in row" :key="cellIdx">
                            <template v-for="(seg, segIdx) in inlineSegments(cell)" :key="segIdx">
                              <strong v-if="seg.strong">{{ seg.text }}</strong>
                              <span v-else>{{ seg.text }}</span>
                            </template>
                          </td>
                        </template>
                      </tr>
                    </tbody>
                  </table>
                </div>
                <pre v-else-if="block.type === 'code'" class="markdown-code"><code>{{ block.text }}</code></pre>
                <p v-else class="markdown-paragraph">
                  <template v-for="(seg, segIdx) in inlineSegments(block.text)" :key="segIdx">
                    <strong v-if="seg.strong">{{ seg.text }}</strong>
                    <span v-else>{{ seg.text }}</span>
                  </template>
                </p>
              </template>
            </div>
            <div v-if="msg.actions?.length" class="chat-actions">
              <el-button
                v-for="action in msg.actions"
                :key="`${idx}-${action.label}-${action.target}`"
                size="small"
                type="primary"
                plain
                @click="openAssistantAction(action)"
              >
                {{ action.label }}
              </el-button>
            </div>
            <div v-if="msg.references?.length" class="chat-references">
              <button
                v-for="ref in msg.references"
                :key="`${idx}-${ref.label}`"
                type="button"
                class="chat-reference"
                :title="ref.target"
                @click="openAssistantReference(ref)"
              >
                {{ ref.label }}
              </button>
            </div>
            <div v-if="msg.tool_calls?.length" class="tool-call-list">
              <div
                v-for="call in msg.tool_calls"
                :key="call.call_id"
                class="tool-call-card"
                :class="`tool-call-${call.phase}`"
              >
                <div class="tool-call-head">
                  <el-icon><Cpu /></el-icon>
                  <strong>{{ call.tool_name || call.tool_id }}</strong>
                  <el-tag size="small" effect="plain" :type="toolPhaseTagType(call.phase)">
                    {{ toolPhaseLabel(call.phase) }}
                  </el-tag>
                  <small v-if="call.algorithm_version">v{{ call.algorithm_version }}</small>
                  <small v-if="call.function_name">{{ call.function_name }}</small>
                  <small v-if="toolProposalModelLabel(call)">提议：{{ toolProposalModelLabel(call) }}</small>
                </div>
                <details class="tool-call-details tool-call-audit">
                  <summary>调用详情</summary>
                  <div class="tool-call-meta-grid">
                    <span><em>提议模型</em>{{ toolProposalModelLabel(call) || '未记录' }}</span>
                    <span><em>Provider call id</em>{{ call.provider_tool_call_id || '未记录' }}</span>
                    <span><em>Function name</em>{{ call.function_name || '未记录' }}</span>
                    <span><em>Schema digest</em>{{ call.schema_digest || '未记录' }}</span>
                    <span><em>Finish reason</em>{{ call.finish_reason || '未记录' }}</span>
                    <span><em>Proposal usage</em>{{ formatUsage(call.proposal_usage || {}) || '未记录' }}</span>
                  </div>
                  <div v-if="toolArgumentDiffResult(call).ok && toolArgumentDiffResult(call).changes.length" class="tool-arg-diff">
                    <strong>模型提议值与用户确认值差异</strong>
                    <div v-for="change in toolArgumentDiffResult(call).changes" :key="change.key" class="tool-arg-diff-row">
                      <code>{{ change.key }}</code>
                      <span class="tool-arg-diff-proposed">{{ toolValueText(change.proposed) }}</span>
                      <span>→</span>
                      <span class="tool-arg-diff-confirmed">{{ toolValueText(change.confirmed) }}</span>
                    </div>
                  </div>
                  <div v-if="toolCallTimeline(call).length" class="tool-event-timeline">
                    <strong>事件 timeline</strong>
                    <el-timeline>
                      <el-timeline-item
                        v-for="row in toolCallTimeline(call)"
                        :key="`${row.at}-${row.label}-${row.type}`"
                        :timestamp="row.at"
                        :type="row.type === 'tool.failed' ? 'danger' : row.type === 'tool.result' ? 'success' : 'primary'"
                      >
                        <div class="tool-event-timeline-row">
                          <strong>{{ row.label }}</strong>
                          <small v-if="row.detail">{{ row.detail }}</small>
                        </div>
                      </el-timeline-item>
                    </el-timeline>
                  </div>
                </details>
                <details v-if="call.raw_arguments" class="tool-call-details tool-proposal-details">
                  <summary>模型原始提案</summary>
                  <pre class="tool-proposal-raw">{{ call.raw_arguments_text || call.raw_arguments }}</pre>
                  <p v-if="call.arguments_parse_error" class="tool-proposal-error">
                    参数解析失败：{{ call.arguments_parse_error }}
                  </p>
                </details>
                <details v-if="canEditToolCall(call)" class="tool-call-details" open>
                  <summary>参数</summary>
                  <div v-if="toolCallFields(call).length" class="tool-schema-form">
                    <div v-for="field in toolCallFields(call)" :key="field.key" class="tool-schema-field">
                      <label :for="`tool-${call.call_id}-${field.key}`">
                        {{ field.key }} <span v-if="field.required" class="required-mark">*</span>
                      </label>
                      <el-select
                        v-if="field.options?.length"
                        :id="`tool-${call.call_id}-${field.key}`"
                        :model-value="call.arguments?.[field.key]"
                        @update:model-value="setToolArgument(call, field, $event)"
                      >
                        <el-option v-for="option in field.options" :key="String(option)" :label="String(option)" :value="option" />
                      </el-select>
                      <el-switch
                        v-else-if="field.type === 'boolean'"
                        :id="`tool-${call.call_id}-${field.key}`"
                        :model-value="Boolean(call.arguments?.[field.key])"
                        @update:model-value="setToolArgument(call, field, $event)"
                      />
                      <el-input-number
                        v-else-if="field.type === 'number' || field.type === 'integer'"
                        :id="`tool-${call.call_id}-${field.key}`"
                        :model-value="call.arguments?.[field.key] === '' ? undefined : call.arguments?.[field.key]"
                        :step="field.type === 'integer' ? 1 : 0.1"
                        controls-position="right"
                        @update:model-value="setToolArgument(call, field, $event)"
                      />
                      <el-input
                        v-else-if="field.type === 'array' || field.type === 'object'"
                        :id="`tool-${call.call_id}-${field.key}`"
                        :model-value="JSON.stringify(call.arguments?.[field.key] ?? (field.type === 'array' ? [] : {}))"
                        type="textarea"
                        :rows="2"
                        @update:model-value="setToolArgument(call, field, $event)"
                      />
                      <el-input
                        v-else
                        :id="`tool-${call.call_id}-${field.key}`"
                        :model-value="call.arguments?.[field.key] ?? ''"
                        @update:model-value="setToolArgument(call, field, $event)"
                      />
                      <small>{{ field.description }}</small>
                    </div>
                  </div>
                  <el-input
                    v-else
                    v-model="call.arguments_text"
                    type="textarea"
                    :rows="3"
                    class="tool-args-editor"
                    resize="none"
                  />
                  <div v-if="call.missing_fields?.length" class="tool-missing-fields">待补充：{{ call.missing_fields.join('、') }}</div>
                  <div class="tool-call-actions">
                    <el-button size="small" @click="updateToolCallArguments(msg, call)">更新参数</el-button>
                    <el-button
                      v-if="call.phase === 'awaiting_confirmation'"
                      size="small"
                      type="primary"
                      :loading="confirmingCallId === call.call_id"
                      @click="confirmToolCall(msg, call)"
                    >
                      确认执行
                    </el-button>
                    <el-button
                      v-if="['awaiting_input', 'awaiting_confirmation'].includes(call.phase)"
                      size="small"
                      @click="cancelToolCall(msg, call)"
                    >
                      取消
                    </el-button>
                  </div>
                </details>
                <div v-if="call.required_assets?.length" class="tool-assets">
                  <label v-for="asset in call.required_assets" :key="asset.key" class="tool-asset-upload">
                    <el-icon><Upload /></el-icon>
                    <span>{{ asset.key }}{{ asset.required ? '（必填）' : '' }}</span>
                    <input
                      type="file"
                      :accept="asset.accept || ''"
                      @change="uploadToolCallAsset(msg, call, asset.key, $event)"
                    />
                  </label>
                </div>
                <div v-if="call.phase === 'completed'" class="tool-call-result">
                  <AlgorithmResultView
                    :output-summary="call.result_summary || {}"
                    :input-snapshot="call.arguments || {}"
                    :artifact-refs="call.artifact_refs || []"
                    :output-schema="call.output_schema || null"
                    :attributions="call.attributions || []"
                    :status="call.phase"
                    :algorithm-id="call.algorithm_id"
                    :run-id="call.run_id || ''"
                    :show-input="true"
                  />
                  <div v-if="visibleToolArtifactRefs(call).length" class="tool-artifacts">
                    <template v-for="(ref, refIndex) in visibleToolArtifactRefs(call)" :key="ref.artifact_id || refIndex">
                      <el-button
                        v-if="ref.artifact_id || ref.id"
                        size="small"
                        text
                        type="primary"
                        @click="downloadToolArtifact(ref)"
                      >
                        下载 {{ ref.name || ref.artifact_id }}
                      </el-button>
                      <el-button
                        v-else
                        size="small"
                        text
                        type="primary"
                        :disabled="!call.run_id"
                        @click="router.push(toolCallRunDetailRoute(call))"
                      >
                        查看运行结果
                      </el-button>
                    </template>
                  </div>
                </div>
                <div v-if="call.phase === 'failed'" class="tool-call-error">
                  <p>{{ call.error?.message || '算法运行失败' }}</p>
                  <el-button size="small" type="primary" plain @click="retryToolCall(msg, call)">
                    重新发起
                  </el-button>
                </div>
                <div v-if="['queued', 'running'].includes(call.phase)" class="tool-call-progress">
                  <el-progress :indeterminate="true" :percentage="50" :show-text="false" />
                  <span>{{ call.phase === 'queued' ? '任务已进入任务中心队列' : '算法正在执行，结果会自动回填到对话' }}</span>
                </div>
                <div v-if="call.run_id" class="tool-call-links">
                  <el-button size="small" text type="primary" @click="router.push(toolCallRunDetailRoute(call))">查看运行详情</el-button>
                </div>
              </div>
            </div>
          </div>
        </div>
      </div>
    </main>

    <footer class="dialogue-composer">
      <div class="suggestion-row" aria-label="推荐问题">
        <button v-for="question in currentSuggestions" :key="question" type="button" :disabled="composerBusy" @click="sendPrompt(question)">
          {{ question }}
        </button>
      </div>
      <div class="composer-box">
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
        <div class="composer-input-row">
          <el-icon class="composer-mark"><ChatLineRound /></el-icon>
          <el-input
            v-model="inputText"
            type="textarea"
            :rows="2"
            placeholder="继续研究..."
            resize="none"
            :disabled="composerBusy"
            @keydown="handleComposerKeydown"
          />
        </div>
        <div class="composer-toolbar">
          <div class="composer-toolbar-left">
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
            <el-popover
              placement="top-start"
              trigger="click"
              width="300"
              popper-class="dialogue-kb-popper"
            >
              <template #reference>
                <button
                  type="button"
                  class="icon-tool-btn"
                  :class="{ active: hasKnowledgeBase }"
                  :disabled="knowledgeLoading || !knowledgeSystems.length"
                  aria-label="选择知识库"
                >
                  <el-icon><Reading /></el-icon>
                  <span v-if="hasKnowledgeBase" class="tool-count">{{ selectedKnowledgeBases.length }}</span>
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
          <div class="composer-toolbar-right">
            <LlmModelSelect
              v-model="selectedModelKey"
              class="composer-model-select"
              :models="selectableModels"
              :loading="modelLoading"
              @change="handleModelManualChange"
            />
            <div
              v-if="selectedModelLacksToolCalling"
              class="composer-model-warning"
              role="status"
            >
              <span>当前模型不支持工具调用</span>
              <el-button
                v-if="toolCapableModelChoices.length"
                size="small"
                text
                type="primary"
                @click="switchToToolCapableModel"
              >
                切换到工具模型
              </el-button>
            </div>
            <el-button
              v-if="currentRunActive"
              type="danger"
              plain
              @click="cancelCurrentRun"
            >
              取消回答
            </el-button>
            <el-button
              type="primary"
              circle
              :icon="Promotion"
              :disabled="!inputText.trim() || composerBusy"
              :loading="composerBusy"
              aria-label="发送"
              @click="sendMessage"
            />
          </div>
        </div>
      </div>
    </footer>
  </div>
</template>

<style scoped>
.dialogue-page {
  position: relative;
  height: calc(100vh - 90px);
  min-height: 620px;
  display: grid;
  grid-template-columns: 248px minmax(0, 1fr);
  grid-template-rows: auto minmax(0, 1fr) auto;
  gap: 12px;
  max-width: 1440px;
  margin: 0 auto;
}

.dialogue-page.history-docked {
  grid-template-columns: minmax(0, 1fr);
}

.dialogue-history {
  grid-row: 1 / -1;
  min-height: 0;
  display: flex;
  flex-direction: column;
  gap: 10px;
  padding: 14px;
  border: 1px solid var(--app-border);
  border-radius: var(--app-radius-lg);
  background: rgba(255, 255, 255, 0.82);
}

.dialogue-history.docked {
  position: absolute;
  top: 0;
  left: 0;
  z-index: 2;
  width: 36px;
  height: 36px;
  min-height: 36px;
  padding: 0;
  gap: 0;
  overflow: hidden;
  border-radius: var(--app-radius-sm);
  background: #ffffff;
}

.history-header,
.history-item,
.history-tabs {
  display: flex;
  align-items: center;
}

.history-header {
  justify-content: space-between;
  color: var(--app-ink);
}

.history-header-actions {
  display: flex;
  align-items: center;
}

.history-dock {
  width: 34px;
  height: 34px;
  display: grid;
  place-items: center;
  padding: 0;
  border: 0;
  background: transparent;
  color: var(--app-ink-muted);
  cursor: pointer;
  font: inherit;
}

.history-dock:hover,
.history-dock:focus-visible {
  background: #f5f8fc;
  color: var(--app-primary-active);
}

.history-tabs {
  gap: 4px;
  border-bottom: 1px solid var(--app-border-soft);
}

.history-tabs button {
  flex: 1;
  padding: 6px 4px;
  border: 0;
  border-bottom: 2px solid transparent;
  background: transparent;
  color: var(--app-ink-muted);
  cursor: pointer;
  font-size: 12px;
}

.history-tabs button.active {
  border-bottom-color: var(--app-primary-active);
  color: var(--app-primary-active);
  font-weight: 650;
}

.history-list {
  min-height: 0;
  overflow-y: auto;
}

.history-item {
  gap: 4px;
  padding: 4px;
  border-radius: var(--app-radius-sm);
}

.history-item.active,
.history-item:hover {
  background: #f0f7ff;
}

.history-item-main {
  min-width: 0;
  flex: 1;
  display: grid;
  gap: 3px;
  padding: 7px 6px;
  border: 0;
  background: transparent;
  text-align: left;
  cursor: pointer;
}

.history-item-title,
.history-item-main small {
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.history-item-title {
  color: var(--app-ink);
  font-size: 13px;
}

.history-item-main small,
.history-empty {
  color: var(--app-ink-muted);
  font-size: 11px;
}

.history-empty {
  padding: 24px 8px;
  text-align: center;
}

.dialogue-header,
.dialogue-body,
.dialogue-composer {
  grid-column: 2;
}

.history-docked .dialogue-header,
.history-docked .dialogue-body,
.history-docked .dialogue-composer {
  grid-column: 1;
}

.history-docked .dialogue-header {
  padding-left: 48px;
}

.history-docked .dialogue-header-centered {
  padding-right: 48px;
}

.dialogue-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 16px;
  min-height: 48px;
}

.dialogue-header-centered {
  justify-content: center;
  text-align: center;
}

.dialogue-header > div:first-child {
  min-width: 0;
}

.dialogue-kicker {
  margin: 0 0 3px;
  color: var(--app-primary-active);
  font-size: 12px;
  font-weight: 700;
}

h1 {
  margin: 0;
  color: var(--app-ink);
  font-size: 20px;
  line-height: 1.3;
  letter-spacing: 0;
}

.dialogue-body {
  min-height: 0;
  overflow-y: auto;
  border: 1px solid var(--app-border);
  border-radius: var(--app-radius-lg);
  background: rgba(255, 255, 255, 0.78);
  box-shadow: var(--app-card-shadow);
}

.message-stack {
  width: min(980px, 100%);
  min-height: 100%;
  margin: 0 auto;
  padding: 28px 18px 36px;
  display: flex;
  flex-direction: column;
  gap: 16px;
}

.chat-message {
  display: flex;
}

.chat-message-user {
  justify-content: flex-end;
}

.chat-message-assistant {
  justify-content: flex-start;
}

.chat-bubble {
  max-width: min(760px, 82%);
  border: 1px solid var(--app-border-soft);
  border-radius: var(--app-radius-md);
  padding: 13px 15px;
  background: #ffffff;
  color: var(--app-ink-body);
  box-shadow: 0 6px 16px rgba(22, 59, 110, 0.04);
}

.chat-message-user .chat-bubble {
  max-width: min(620px, 72%);
  background: var(--app-primary);
  color: #ffffff;
  border-color: var(--app-primary);
}

.chat-meta {
  display: flex;
  flex-wrap: wrap;
  gap: 6px;
  margin-bottom: 8px;
}

.model-meta-trigger {
  cursor: pointer;
}

.model-detail-panel {
  display: grid;
  gap: 10px;
  min-width: 0;
}

.model-detail-panel > strong {
  color: var(--app-ink);
  font-size: 13px;
}

.model-detail-panel dl {
  display: grid;
  grid-template-columns: 92px minmax(0, 1fr);
  gap: 6px 12px;
  margin: 0;
  font-size: 12px;
}

.model-detail-panel dt {
  color: var(--app-ink-muted);
}

.model-detail-panel dd {
  min-width: 0;
  margin: 0;
  color: var(--app-ink-body);
  overflow-wrap: anywhere;
}

.assistant-context-panel {
  margin-top: 10px;
  border: 1px solid var(--app-border-soft);
  border-radius: var(--app-radius-sm);
  background: #f8fbff;
}

.assistant-context-panel summary {
  padding: 8px 10px;
  color: var(--app-ink);
  cursor: pointer;
  font-size: 13px;
  font-weight: 650;
}

.assistant-context-panel-body {
  display: grid;
  gap: 10px;
  padding: 2px 10px 10px;
}

.context-panel-section {
  display: grid;
  gap: 6px;
}

.context-panel-section h4 {
  margin: 0;
  color: var(--app-ink-muted);
  font-size: 11px;
  letter-spacing: 0.04em;
}

.context-panel-section dl {
  display: grid;
  grid-template-columns: 86px minmax(0, 1fr);
  gap: 5px 10px;
  margin: 0;
  font-size: 12px;
}

.context-panel-section dt {
  color: var(--app-ink-muted);
}

.context-panel-section dd {
  margin: 0;
  color: var(--app-ink-body);
  overflow-wrap: anywhere;
}

.context-section-row,
.context-tool-row {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 8px;
  padding: 6px 8px;
  border: 1px solid var(--app-border-soft);
  border-radius: var(--app-radius-sm);
  background: #ffffff;
}

.context-section-row > div,
.context-tool-row > div {
  min-width: 0;
  display: grid;
  gap: 2px;
}

.context-section-row strong,
.context-tool-row strong,
.context-section-row small,
.context-tool-row small {
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.context-section-row strong,
.context-tool-row strong {
  color: var(--app-ink);
  font-size: 12px;
}

.context-section-row small,
.context-tool-row small {
  color: var(--app-ink-muted);
  font-size: 11px;
}

.context-section-row > span {
  flex: 0 0 auto;
  color: #15803d;
  font-size: 11px;
}

.context-section-row > span.omitted {
  color: #b45309;
}

.context-tool-row code {
  flex: 0 0 auto;
  max-width: 120px;
  overflow: hidden;
  text-overflow: ellipsis;
  color: var(--app-primary-active);
  font-size: 11px;
  white-space: nowrap;
}

.context-evidence-link {
  justify-self: start;
  max-width: 100%;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  padding: 4px 8px;
  border: 1px solid #bfdbfe;
  border-radius: var(--app-radius-pill);
  background: #eff6ff;
  color: var(--app-primary-active);
  cursor: pointer;
  font-size: 12px;
}

.reasoning-summary {
  margin: 0 0 10px;
  border: 1px solid var(--app-border-soft);
  border-radius: var(--app-radius-sm);
  background: #f8fbff;
}

.reasoning-summary summary {
  padding: 8px 10px;
  color: var(--app-ink);
  font-size: 13px;
  font-weight: 650;
  cursor: pointer;
}

.reasoning-summary ol {
  margin: 0;
  padding: 0 12px 10px 28px;
  color: var(--app-ink-body);
  font-size: 13px;
  line-height: 1.7;
}

.markdown-heading,
.markdown-paragraph {
  margin: 0 0 8px;
}

.markdown-heading {
  color: inherit;
  font-size: 15px;
  line-height: 1.55;
}

.markdown-paragraph,
.markdown-list {
  font-size: 14px;
  line-height: 1.75;
}

.markdown-list {
  margin: 0 0 8px;
  padding-left: 18px;
}

.markdown-code {
  max-width: 100%;
  overflow: auto;
  margin: 8px 0;
  padding: 10px;
  border-radius: var(--app-radius-sm);
  background: #0e1b2d;
  color: #b9d4ff;
  font-size: 12px;
}

.markdown-table-wrap {
  max-width: 100%;
  overflow-x: auto;
  margin: 8px 0 10px;
  border: 1px solid var(--app-border-soft);
  border-radius: var(--app-radius-sm);
}

.markdown-table {
  width: 100%;
  min-width: 520px;
  border-collapse: collapse;
  font-size: 13px;
  line-height: 1.6;
}

.markdown-table th,
.markdown-table td {
  padding: 8px 10px;
  border-bottom: 1px solid var(--app-border-soft);
  text-align: left;
  vertical-align: top;
}

.markdown-table th {
  color: var(--app-ink);
  background: #f8fbff;
  font-weight: 700;
}

.markdown-table tr:last-child td {
  border-bottom: 0;
}

.chat-actions,
.chat-references,
.suggestion-row {
  display: flex;
  gap: 8px;
  flex-wrap: wrap;
}

.chat-actions,
.chat-references {
  margin-top: 10px;
}

.chat-reference,
.suggestion-row button {
  max-width: 100%;
  border: 1px solid #bfdbfe;
  border-radius: var(--app-radius-pill);
  background: #eff6ff;
  color: var(--app-primary-active);
  font: inherit;
  cursor: pointer;
}

.chat-reference {
  padding: 4px 9px;
  font-size: 12px;
}

.dialogue-composer {
  position: sticky;
  bottom: 0;
  display: grid;
  gap: 10px;
  width: min(980px, 100%);
  justify-self: center;
}

.suggestion-row {
  justify-content: center;
}

.suggestion-row button {
  padding: 7px 11px;
  font-size: 13px;
  background: rgba(255, 255, 255, 0.92);
}

.suggestion-row button:disabled {
  cursor: not-allowed;
  opacity: 0.65;
}

.composer-box {
  display: grid;
  grid-template-columns: minmax(0, 1fr);
  gap: 8px;
  padding: 12px;
  border: 1px solid #c7dcfb;
  border-radius: var(--app-radius-lg);
  background: rgba(255, 255, 255, 0.96);
  box-shadow: 0 12px 28px rgba(22, 59, 110, 0.08);
}

.composer-input-row {
  display: grid;
  grid-template-columns: 24px minmax(0, 1fr);
  gap: 10px;
  align-items: start;
}

.composer-mark {
  align-self: start;
  margin-top: 8px;
  color: var(--app-primary-active);
  font-size: 19px;
}

.composer-box :deep(.el-textarea__inner) {
  min-height: 52px !important;
  border: 0;
  box-shadow: none;
  font-size: 14px;
  line-height: 1.65;
}

.composer-toolbar {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 8px;
  padding-top: 8px;
  border-top: 1px solid var(--app-border-soft);
}

.composer-toolbar-left,
.composer-toolbar-right {
  min-width: 0;
  display: flex;
  align-items: center;
  gap: 8px;
  flex-wrap: wrap;
}

.composer-toolbar-right {
  justify-content: flex-end;
  margin-left: auto;
}

.mode-trigger {
  height: 28px;
  display: inline-flex;
  align-items: center;
  justify-content: center;
  gap: 4px;
  padding: 0 10px;
  border: 1px solid var(--app-border-soft);
  border-radius: var(--app-radius-sm);
  background: #ffffff;
  color: var(--app-ink-body);
  font: inherit;
  font-size: 13px;
  font-weight: 650;
  cursor: pointer;
}

.mode-trigger:hover {
  background: #f8fbff;
  border-color: #bfdbfe;
  color: var(--app-primary-active);
}

.mode-trigger .el-icon {
  font-size: 12px;
}

.icon-tool-btn {
  position: relative;
  width: 28px;
  height: 28px;
  min-width: 28px;
  display: inline-grid;
  place-items: center;
  padding: 0;
  border: 0;
  border-radius: var(--app-radius-sm);
  background: transparent;
  color: var(--app-ink-muted);
  cursor: pointer;
  transition: background 0.15s ease, color 0.15s ease;
}

.icon-tool-btn:hover:not(:disabled) {
  background: #eef4ff;
  color: var(--app-ink);
}

.icon-tool-btn.active {
  background: var(--app-primary-light);
  color: var(--app-primary-active);
  box-shadow: inset 0 0 0 1px rgba(37, 99, 235, 0.2);
}

.icon-tool-btn.active:hover:not(:disabled) {
  background: #dbeafe;
  color: var(--app-primary);
}

.icon-tool-btn:disabled {
  cursor: not-allowed;
  opacity: 0.45;
}

.tool-count {
  position: absolute;
  top: -5px;
  right: -5px;
  min-width: 15px;
  height: 15px;
  padding: 0 3px;
  border: 2px solid #ffffff;
  border-radius: 999px;
  background: var(--app-primary);
  color: #ffffff;
  font-size: 9px;
  line-height: 11px;
  box-sizing: border-box;
}

.selected-tags-inline {
  display: flex;
  align-items: center;
  gap: 6px;
  flex-wrap: wrap;
  padding: 0 0 8px;
  border-bottom: 1px solid var(--app-border-soft);
}

.mention-chip {
  max-width: 100%;
  height: 26px;
  display: inline-flex;
  align-items: center;
  gap: 5px;
  padding: 0 7px;
  border: 1px solid var(--app-border-soft);
  border-radius: var(--app-radius-sm);
  background: #f8fbff;
  color: var(--app-ink-body);
  font-size: 12px;
  font-weight: 650;
}

.mention-chip--kb .el-icon {
  color: var(--app-primary-active);
}

.mention-chip--tool .el-icon {
  color: #16a34a;
}

.mention-chip-name {
  min-width: 0;
  max-width: 180px;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.mention-chip button {
  width: 16px;
  height: 16px;
  display: inline-grid;
  place-items: center;
  padding: 0;
  border: 0;
  border-radius: 999px;
  background: transparent;
  color: #94a3b8;
  cursor: pointer;
  line-height: 1;
}

.mention-chip button:hover {
  background: #e2e8f0;
  color: var(--app-ink);
}

.composer-model-select {
  flex: 0 1 280px;
}

.composer-model-warning {
  flex: 0 0 auto;
  display: inline-flex;
  align-items: center;
  gap: 4px;
  border: 1px solid #fde68a;
  border-radius: 999px;
  padding: 3px 8px;
  color: #92400e;
  background: #fffbeb;
  font-size: 11px;
  line-height: 1.4;
}

.kb-picker {
  display: grid;
  gap: 6px;
}

.kb-picker-item {
  width: 100%;
  min-width: 0;
  display: grid;
  grid-template-columns: 18px minmax(0, 1fr);
  align-items: center;
  gap: 8px;
  padding: 8px;
  border: 0;
  border-radius: var(--app-radius-sm);
  background: transparent;
  color: var(--app-ink-body);
  text-align: left;
  cursor: pointer;
}

.kb-picker-item:hover,
.kb-picker-item.selected {
  background: #f0f7ff;
  color: var(--app-primary-active);
}

.kb-picker-item .el-icon {
  color: var(--app-primary-active);
}

.kb-picker-item span {
  min-width: 0;
  display: grid;
  gap: 2px;
}

.kb-picker-item strong,
.kb-picker-item small {
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.kb-picker-item strong {
  font-size: 13px;
}

.kb-picker-item small,
.kb-picker-empty {
  color: var(--app-ink-muted);
  font-size: 12px;
}

.kb-picker-clear {
  justify-self: start;
  padding: 5px 7px;
  border: 0;
  border-radius: var(--app-radius-sm);
  background: transparent;
  color: var(--app-primary-active);
  cursor: pointer;
  font-size: 12px;
}

.tool-call-list {
  display: grid;
  gap: 8px;
  margin-top: 10px;
}

.tool-call-card {
  display: grid;
  gap: 8px;
  padding: 10px;
  border: 1px solid var(--app-border);
  border-radius: var(--app-radius-md);
  background: #fbfdff;
  color: var(--app-ink-body);
}

.tool-call-card.tool-call-completed {
  border-color: #bbf7d0;
  background: #f0fdf4;
}

.tool-call-card.tool-call-failed {
  border-color: #fecaca;
  background: #fef2f2;
}

.tool-call-card.tool-call-running {
  border-color: #fde68a;
  background: #fffbeb;
}

.tool-call-card.tool-call-queued {
  border-color: #bfdbfe;
  background: #eff6ff;
}

.tool-call-head {
  min-width: 0;
  display: flex;
  align-items: center;
  gap: 8px;
}

.tool-call-head .el-icon {
  color: var(--app-primary-active);
}

.tool-call-head strong {
  min-width: 0;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  color: var(--app-ink);
  font-size: 13px;
}

.tool-call-head small {
  color: var(--app-ink-muted);
  font-size: 11px;
}

.tool-call-details summary {
  color: var(--app-ink-muted);
  cursor: pointer;
  font-size: 12px;
}

.tool-call-audit {
  padding: 8px;
  border: 1px solid var(--app-border-soft);
  border-radius: var(--app-radius-sm);
  background: #ffffff;
}

.tool-call-meta-grid {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 6px 12px;
  margin-top: 8px;
}

.tool-call-meta-grid span {
  min-width: 0;
  display: grid;
  gap: 2px;
  color: var(--app-ink-body);
  font-size: 12px;
  overflow-wrap: anywhere;
}

.tool-call-meta-grid em {
  color: var(--app-ink-muted);
  font-size: 11px;
  font-style: normal;
}

.tool-arg-diff {
  display: grid;
  gap: 6px;
  margin-top: 8px;
}

.tool-arg-diff > strong,
.tool-event-timeline > strong {
  color: var(--app-ink);
  font-size: 12px;
}

.tool-arg-diff-row {
  display: grid;
  grid-template-columns: minmax(80px, auto) minmax(0, 1fr) auto minmax(0, 1fr);
  align-items: center;
  gap: 6px;
  font-size: 12px;
}

.tool-arg-diff-row code {
  color: var(--app-primary-active);
}

.tool-arg-diff-proposed,
.tool-arg-diff-confirmed {
  min-width: 0;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.tool-arg-diff-proposed {
  color: #b45309;
}

.tool-arg-diff-confirmed {
  color: #15803d;
}

.tool-event-timeline {
  display: grid;
  gap: 6px;
  margin-top: 8px;
}

.tool-event-timeline :deep(.el-timeline) {
  padding-left: 2px;
}

.tool-event-timeline-row {
  min-width: 0;
  display: grid;
  gap: 2px;
}

.tool-event-timeline-row strong {
  color: var(--app-ink);
  font-size: 12px;
}

.tool-event-timeline-row small {
  color: var(--app-ink-muted);
  font-size: 11px;
  overflow-wrap: anywhere;
}

.tool-schema-form {
  display: grid;
  gap: 8px;
  margin-top: 8px;
}

.tool-schema-field {
  display: grid;
  gap: 4px;
}

.tool-schema-field label {
  color: var(--app-ink-body);
  font-size: 12px;
  font-weight: 650;
}

.tool-schema-field small,
.tool-missing-fields,
.tool-call-progress span {
  color: var(--app-ink-muted);
  font-size: 11px;
}

.required-mark {
  color: #dc2626;
}

.tool-call-progress {
  display: grid;
  gap: 5px;
}

.tool-call-links {
  display: flex;
  justify-content: flex-end;
}

.tool-args-editor :deep(textarea) {
  font-family: ui-monospace, SFMono-Regular, Menlo, Consolas, monospace;
  font-size: 12px;
}

.tool-proposal-details {
  margin-top: 8px;
}

.tool-proposal-raw,
.tool-proposal-error {
  margin: 8px 0 0;
  padding: 8px;
  border-radius: var(--app-radius-sm);
  background: #f1f5f9;
  color: var(--app-ink-body);
  font-size: 12px;
  white-space: pre-wrap;
  word-break: break-word;
}

.tool-proposal-error {
  color: #b91c1c;
}

.tool-call-actions {
  display: flex;
  flex-wrap: wrap;
  gap: 6px;
}

.tool-assets {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
}

.tool-asset-upload {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  padding: 5px 9px;
  border: 1px dashed #cbd5e1;
  border-radius: var(--app-radius-sm);
  color: var(--app-ink-body);
  cursor: pointer;
  font-size: 12px;
}

.tool-asset-upload input {
  display: none;
}

.tool-call-result {
  color: var(--app-ink-body);
}

.tool-call-result pre,
.tool-call-error p {
  margin: 0;
  padding: 8px;
  border-radius: var(--app-radius-sm);
  background: #f1f5f9;
  color: var(--app-ink-body);
  font-size: 12px;
  white-space: pre-wrap;
  word-break: break-word;
}

.tool-artifacts {
  display: flex;
  flex-wrap: wrap;
  gap: 4px;
}

.tool-call-error p {
  background: #fef2f2;
  color: #b91c1c;
}

@media (max-width: 900px) {
  .dialogue-page {
    height: calc(100vh - 78px);
    min-height: 560px;
    grid-template-columns: minmax(0, 1fr);
    grid-template-rows: auto auto minmax(0, 1fr) auto;
  }

  .dialogue-page.history-docked {
    grid-template-columns: minmax(0, 1fr);
  }

  .dialogue-history {
    grid-row: auto;
    max-height: 180px;
  }

  .dialogue-history.docked {
    width: 36px;
    height: 36px;
    min-height: 36px;
  }

  .history-empty {
    padding: 6px 8px;
  }

  .dialogue-header,
  .dialogue-body,
  .dialogue-composer {
    grid-column: 1;
  }

  .dialogue-header {
    align-items: stretch;
    flex-direction: column;
  }

  .chat-bubble,
  .chat-message-user .chat-bubble {
    max-width: 92%;
  }

  .composer-toolbar {
    align-items: stretch;
    flex-direction: column;
  }

  .composer-toolbar-left,
  .composer-toolbar-right {
    justify-content: stretch;
  }

  .composer-model-select {
    width: 100%;
  }
}

@media (max-width: 560px) {
  .message-stack {
    padding: 18px 10px 24px;
  }

  .composer-mark {
    display: none;
  }

  .composer-input-row {
    grid-template-columns: minmax(0, 1fr);
  }

  .mode-trigger {
    flex: 0 0 auto;
  }

  .tool-call-meta-grid {
    grid-template-columns: minmax(0, 1fr);
  }

  .tool-arg-diff-row {
    grid-template-columns: minmax(0, 1fr);
    align-items: stretch;
  }
}
</style>
