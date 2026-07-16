<script setup>
import { computed, nextTick, onMounted, ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { ElMessage } from 'element-plus'
import { ChatLineRound, Loading, Promotion, Setting } from '@element-plus/icons-vue'

import { getApiErrorMessage, getLlmModels, streamAssistantChat } from '../api/polyAgentApi'
import LlmModelSelect from '../components/LlmModelSelect.vue'
import { buildSelectableLlmModels } from '../utils/llmModels'

const route = useRoute()
const router = useRouter()
const bodyRef = ref(null)
const inputText = ref('')
const sending = ref(false)
const modelLoading = ref(false)
const chatMode = ref(normalizeMode(route.query.mode))
const llmCatalog = ref({ providers: [], routing: {} })
const selectedModelKey = ref('')

const messages = ref([
  {
    role: 'assistant',
    content: '你好！我是 PolyAgent 产品内助手，可以帮你定位页面入口、确认 ResearchEngine 算法清单、提交计算任务和处理 AutoResearch 审批。',
    actions: [{ label: '进入 ResearchEngine', target: '/research-engine', type: 'route' }],
    references: [],
    suggested_questions: ['哪些算法是真实适配器？', '如何开始一个 ResearchEngine 示例？', '如何查看待审批任务？'],
  },
])

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
  skipped_disabled: '检索已关闭',
  searched: '已联网检索',
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

function cleanInitialQuery() {
  if (!route.query.prompt && !route.query.mode && !route.query.providerId && !route.query.modelId) return
  const query = { ...route.query }
  delete query.prompt
  delete query.mode
  delete query.providerId
  delete query.modelId
  router.replace({ path: route.path, query })
}

function routePurpose() {
  return chatMode.value === 'deep' ? 'deep' : 'qa'
}

function selectDefaultModelForMode(preferred = {}) {
  const preferredKey = preferred.providerId && preferred.modelId ? `${preferred.providerId}::${preferred.modelId}` : ''
  if (preferredKey && selectableModels.value.some((item) => item.key === preferredKey)) {
    selectedModelKey.value = preferredKey
    return
  }
  const purpose = routePurpose()
  const route = llmCatalog.value.routing?.[purpose]
  const key = route?.provider_id && route?.model_id ? `${route.provider_id}::${route.model_id}` : ''
  if (key && selectableModels.value.some((item) => item.key === key)) {
    selectedModelKey.value = key
    return
  }
  selectedModelKey.value = selectableModels.value[0]?.key || ''
}

async function loadLlmModels(preferred = {}) {
  modelLoading.value = true
  try {
    llmCatalog.value = await getLlmModels()
    selectDefaultModelForMode(preferred)
  } catch (error) {
    ElMessage.warning(`模型列表加载失败：${getApiErrorMessage(error)}`)
  } finally {
    modelLoading.value = false
  }
}

async function sendMessage() {
  await sendPrompt(inputText.value)
}

async function sendPrompt(prompt) {
  const text = String(prompt || '').trim()
  if (!text || sending.value) return
  messages.value.push({ role: 'user', content: text })
  const requestMessages = messages.value.map((message) => ({ role: message.role, content: message.content }))
  const assistantMessage = {
    role: 'assistant',
    content: '',
    reasoning_summary: [],
    actions: [],
    references: [],
    suggested_questions: [],
    answer_mode: '',
    answer_scope: '',
    retrieval_status: '',
    stream_status: '准备回答...',
    stream_stage: 'queued',
    streaming: true,
  }
  messages.value.push(assistantMessage)
  const assistantIndex = messages.value.length - 1
  inputText.value = ''
  sending.value = true
  scrollToBottom()
  let streamErrorMessage = ''
  try {
    await streamAssistantChat(
      {
        messages: requestMessages,
        context: {
          current_route: router.currentRoute.value.fullPath,
          page: 'dialogue',
          mode: chatMode.value,
          model: selectedModel.value
            ? { providerId: selectedModel.value.providerId, modelId: selectedModel.value.modelId }
            : null,
        },
      },
      (event) => {
        const errorMessage = applyAssistantStreamEvent(assistantIndex, event)
        if (errorMessage) streamErrorMessage = errorMessage
        scrollToBottom()
      },
    )
    if (streamErrorMessage) ElMessage.error(`对话失败：${streamErrorMessage}`)
  } catch (error) {
    const message = getApiErrorMessage(error)
    Object.assign(messages.value[assistantIndex], {
      content: `对话出错：${message}`,
      stream_status: '',
      streaming: false,
    })
    ElMessage.error(`对话失败：${message}`)
  } finally {
    if (messages.value[assistantIndex]) {
      messages.value[assistantIndex].streaming = false
      messages.value[assistantIndex].stream_status = ''
    }
    sending.value = false
    scrollToBottom()
  }
}

function applyAssistantStreamEvent(index, event) {
  const target = messages.value[index]
  if (!target || !event) return ''
  if (event.type === 'status') {
    target.stream_status = event.message || ''
    target.stream_stage = event.stage || ''
    return ''
  }
  if (event.type === 'evidence') {
    target.retrieval_status = event.status || target.retrieval_status
    target.stream_status = event.message || target.stream_status
    if (Array.isArray(event.references) && event.references.length) target.references = event.references
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
      stream_status: '',
      stream_stage: '',
      streaming: false,
    })
    return ''
  }
  if (event.type === 'error') {
    const message = event.message || '流式对话失败'
    target.content = target.content || `对话出错：${message}`
    target.stream_status = ''
    target.streaming = false
    return message
  }
  return ''
}

function scrollToBottom() {
  nextTick(() => {
    if (bodyRef.value) bodyRef.value.scrollTop = bodyRef.value.scrollHeight
  })
}

function openAssistantAction(action) {
  if (action?.target) router.push(action.target)
}

function openModelManagement() {
  router.push({ path: '/tools', query: { tab: 'llm-models' } })
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
  chatMode.value = normalizeMode(route.query.mode)
  cleanInitialQuery()
  loadLlmModels({ providerId: initialProviderId, modelId: initialModelId }).finally(() => {
    if (initialPrompt) sendPrompt(initialPrompt)
  })
})
</script>

<template>
  <div class="dialogue-page">
    <header class="dialogue-header">
      <div>
        <p class="dialogue-kicker">Poly Agent 问答</p>
        <h1>科研任务交互问答</h1>
      </div>
      <div class="dialogue-controls">
        <LlmModelSelect
          v-model="selectedModelKey"
          :models="selectableModels"
          :loading="modelLoading"
        />
        <el-segmented v-model="chatMode" :options="chatModeOptions" @change="() => selectDefaultModelForMode()" />
        <el-button text type="primary" :icon="Setting" @click="openModelManagement">模型管理</el-button>
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
              <div v-if="msg.answer_mode || msg.retrieval_status || msg.stream_status" class="chat-meta">
                <el-tag v-if="msg.answer_mode" size="small" effect="plain" type="info">
                  {{ answerModeLabelMap[msg.answer_mode] || msg.answer_mode }}
                </el-tag>
                <el-tag v-if="msg.retrieval_status" size="small" effect="plain" type="success">
                  {{ retrievalStatusLabelMap[msg.retrieval_status] || msg.retrieval_status }}
                </el-tag>
                <el-tag v-if="msg.stream_status" size="small" effect="plain" type="warning">
                  {{ msg.stream_status }}
                </el-tag>
              </div>
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
          </div>
        </div>
      </div>
    </main>

    <footer class="dialogue-composer">
      <div class="suggestion-row" aria-label="推荐问题">
        <button v-for="question in currentSuggestions" :key="question" type="button" :disabled="sending" @click="sendPrompt(question)">
          {{ question }}
        </button>
      </div>
      <div class="composer-box">
        <el-icon class="composer-mark"><ChatLineRound /></el-icon>
        <el-input
          v-model="inputText"
          type="textarea"
          :rows="2"
          placeholder="继续研究..."
          resize="none"
          :disabled="sending"
          @keydown="handleComposerKeydown"
        />
        <el-button
          type="primary"
          circle
          :icon="Promotion"
          :disabled="!inputText.trim() || sending"
          :loading="sending"
          aria-label="发送"
          @click="sendMessage"
        />
      </div>
    </footer>
  </div>
</template>

<style scoped>
.dialogue-page {
  height: calc(100vh - 90px);
  min-height: 620px;
  display: grid;
  grid-template-rows: auto minmax(0, 1fr) auto;
  gap: 12px;
  max-width: 1440px;
  margin: 0 auto;
}

.dialogue-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 16px;
  min-height: 48px;
}

.dialogue-controls {
  display: flex;
  align-items: center;
  gap: 10px;
  flex-wrap: wrap;
  justify-content: flex-end;
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
  grid-template-columns: 24px minmax(0, 1fr) 42px;
  align-items: end;
  gap: 10px;
  padding: 12px;
  border: 1px solid #c7dcfb;
  border-radius: var(--app-radius-lg);
  background: rgba(255, 255, 255, 0.96);
  box-shadow: 0 12px 28px rgba(22, 59, 110, 0.08);
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

@media (max-width: 900px) {
  .dialogue-page {
    height: calc(100vh - 78px);
    min-height: 560px;
  }

  .dialogue-header {
    align-items: stretch;
    flex-direction: column;
  }

  .chat-bubble,
  .chat-message-user .chat-bubble {
    max-width: 92%;
  }
}

@media (max-width: 560px) {
  .message-stack {
    padding: 18px 10px 24px;
  }

  .composer-box {
    grid-template-columns: minmax(0, 1fr) 40px;
  }

  .composer-mark {
    display: none;
  }
}
</style>
