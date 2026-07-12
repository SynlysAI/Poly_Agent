<script setup>
import { computed, onMounted, reactive, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { ElMessage } from 'element-plus'
import {
  ChatLineRound,
  Collection,
  Connection,
  DataAnalysis,
  Refresh,
  Search,
} from '@element-plus/icons-vue'

import {
  getApiErrorMessage,
  getKnowledgeHealth,
  getKnowledgeSubgraph,
  generateKnowledgeSuggestions,
  listKnowledgeSystems,
  queryKnowledgeBase,
  streamKnowledgeQuery,
} from '../api/polyAgentApi'

const route = useRoute()
const router = useRouter()

const systems = ref([])
const health = ref(null)
const activeModule = ref(route.query.module === 'graph' ? 'graph' : 'rag')
const selectedSystemId = ref(typeof route.query.system === 'string' ? route.query.system : '')
const loadingSystems = ref(false)
const queryLoading = ref(false)
const graphLoading = ref(false)
const answer = ref(null)
const graph = ref(null)
const selectedNodeId = ref('')
const suggestedQuestions = ref([])
const suggestionsLoading = ref(false)
const queryTrace = ref([])

const queryForm = reactive({
  question: '',
  mode: 'hybrid',
  top_k: 5,
  include_graph_context: true,
})

const graphForm = reactive({
  query: '',
  limit: 30,
})

const selectedSystem = computed(() =>
  systems.value.find((item) => item.system_id === selectedSystemId.value) || null,
)
const hasSystems = computed(() => systems.value.length > 0)

const graphNodes = computed(() => graph.value?.nodes || [])
const graphEdges = computed(() => graph.value?.edges || [])
const graphStats = computed(() => graph.value?.stats || { entity_count: 0, relation_count: 0, document_count: 0 })
const graphSummaryStats = computed(() => graph.value?.stats || {
  entity_count: selectedSystem.value?.entity_count || 0,
  relation_count: selectedSystem.value?.relation_count || 0,
  document_count: selectedSystem.value?.indexed_document_count || selectedSystem.value?.document_count || 0,
})
const graphSummaryScope = computed(() => graph.value ? '当前子图' : '体系总量')
const selectedNode = computed(() => graphNodes.value.find((item) => item.id === selectedNodeId.value) || graphNodes.value[0] || null)
const selectedNodeEdges = computed(() =>
  graphEdges.value.filter((item) => item.source === selectedNode.value?.id || item.target === selectedNode.value?.id),
)
const answerBlocks = computed(() => parseMarkdownBlocks(answer.value?.answer || ''))
const systemMetricItems = computed(() => [
  { label: '文档', value: selectedSystem.value?.indexed_document_count || selectedSystem.value?.document_count || graphStats.value.document_count || 0 },
  { label: '实体', value: selectedSystem.value?.entity_count || graphStats.value.entity_count || 0 },
  { label: '关系', value: selectedSystem.value?.relation_count || graphStats.value.relation_count || 0 },
  { label: '索引状态', value: systemStatusLabel(selectedSystem.value?.status || health.value?.status) },
])
const currentStatus = computed(() => selectedSystem.value?.status || health.value?.status || 'unavailable')
const currentStatusMessage = computed(() =>
  normalizeKnowledgeMessage(selectedSystem.value?.health_message || health.value?.message || queryUnavailableMessage.value),
)
const canRunQuery = computed(() => hasCapability(selectedSystem.value, 'query') && selectedSystem.value?.status === 'ready')
const canStreamQuery = computed(() => canRunQuery.value && hasCapability(selectedSystem.value, 'streaming'))
const canLoadGraph = computed(() => hasCapability(selectedSystem.value, 'graph') && selectedSystem.value?.status === 'ready')
const canUseGraphContext = computed(() => canRunQuery.value && canLoadGraph.value)
const canLoadSuggestions = computed(() => hasCapability(selectedSystem.value, 'suggestions') && selectedSystem.value?.status === 'ready')
const queryUnavailableMessage = computed(() => {
  if (loadingSystems.value) return '正在检查知识库服务。'
  if (!health.value?.configured && !hasSystems.value) return '知识库服务未配置。'
  if (!hasSystems.value) return '未发现可用知识库体系。'
  if (!selectedSystem.value) return '请选择知识库体系。'
  if (selectedSystem.value.status === 'indexing') return '当前知识库体系正在索引，完成后可检索。'
  if (selectedSystem.value.status === 'empty') return '当前知识库体系尚未完成索引。'
  if (selectedSystem.value.status !== 'ready') return '当前知识库体系暂不可用。'
  if (!hasCapability(selectedSystem.value, 'query')) return '当前知识库体系未提供问答能力。'
  return '选择知识体系并输入问题后开始检索。'
})
const graphTypeCounts = computed(() => {
  const counts = {}
  graphNodes.value.forEach((node) => {
    counts[node.type] = (counts[node.type] || 0) + 1
  })
  return Object.entries(counts).map(([type, count]) => ({ type, count }))
})
const topCitations = computed(() => answer.value?.citations?.filter((item) => citationUrl(item)).slice(0, 8) || [])
const answerGraphContext = computed(() => answer.value?.graph_context || null)
const canOpenAnswerGraph = computed(() => (answerGraphContext.value?.nodes || []).length > 0)
const graphEmptyMessage = computed(() => {
  if (!canLoadGraph.value) return '该知识库体系未提供可用图谱。'
  if (!graph.value) return '尚未加载子图，输入关键词或使用默认关键词加载。'
  return '当前关键词未匹配到图谱节点。'
})
const graphLanes = computed(() => {
  const lanes = [
    { key: 'materials', label: 'Materials', types: ['Material', 'Polymer', 'Resin', 'Monomer', 'PhotoacidGenerator', 'Additive'], nodes: [] },
    { key: 'strategies', label: 'Strategies', types: ['Strategy', 'Method', 'ProcessCondition'], nodes: [] },
    { key: 'properties', label: 'Properties', types: ['Property', 'LithographyMetric', 'Application'], nodes: [] },
    { key: 'papers', label: 'Papers & Chunks', types: ['Paper', 'Dataset', 'Chunk'], nodes: [] },
  ]
  graphNodes.value.forEach((node) => {
    const lane = lanes.find((item) => item.types.includes(node.type)) || lanes[lanes.length - 1]
    lane.nodes.push(node)
  })
  return lanes
})
const selectedNodeSourceUrl = computed(() => selectedNode.value?.properties?.source_url || citationUrl(selectedNode.value?.properties || {}))

function parseMarkdownLinks(text) {
  const segments = []
  const pattern = /\[([^\]]+)\]\((https?:\/\/[^)]+)\)/g
  let lastIndex = 0
  let match = pattern.exec(text)
  while (match) {
    if (match.index > lastIndex) {
      segments.push({ type: 'text', text: text.slice(lastIndex, match.index) })
    }
    segments.push({ type: 'link', text: match[1], href: match[2] })
    lastIndex = pattern.lastIndex
    match = pattern.exec(text)
  }
  if (lastIndex < text.length) {
    segments.push({ type: 'text', text: text.slice(lastIndex) })
  }
  return segments.length ? segments : [{ type: 'text', text }]
}

function parseMarkdownBlocks(markdown) {
  const lines = markdown.split(/\r?\n/)
  const blocks = []
  let listItems = []
  const flushList = () => {
    if (listItems.length) {
      blocks.push({ type: 'list', items: listItems.map((item) => parseMarkdownLinks(item)) })
      listItems = []
    }
  }
  lines.forEach((line) => {
    const trimmed = line.trim()
    if (!trimmed) {
      flushList()
      return
    }
    if (trimmed.startsWith('### ')) {
      flushList()
      blocks.push({ type: 'heading', text: trimmed.slice(4) })
      return
    }
    if (trimmed.startsWith('- ')) {
      listItems.push(trimmed.slice(2))
      return
    }
    flushList()
    blocks.push({ type: 'paragraph', segments: parseMarkdownLinks(trimmed) })
  })
  flushList()
  return blocks
}

function citationUrl(item) {
  if (!item) return ''
  if (item.url) return item.url
  if (item.doi) return `https://doi.org/${item.doi}`
  return ''
}

function citationMeta(item) {
  const parts = [item?.journal, item?.year].filter(Boolean)
  return parts.join(' · ')
}

function nodeLabelById(nodeId) {
  return graphNodes.value.find((item) => item.id === nodeId)?.label || nodeId
}

function shortSource(hit) {
  const parts = [hit.journal || hit.source, hit.year].filter(Boolean)
  return parts.join(' · ') || hit.source_id
}

function sourceLevel(hit) {
  const sourceKind = hit?.metadata?.source_kind
  const labels = {
    authorized_upload: '授权全文',
    publisher_oa: '出版社 OA',
    openalex_oa: 'OpenAlex OA',
    unpaywall: 'Unpaywall OA',
    pmc: 'PMC',
    europe_pmc: 'Europe PMC',
  }
  return labels[sourceKind] || '可追溯来源'
}

function linkSegments(segments) {
  return segments || []
}

function normalizeKnowledgeMessage(message) {
  return String(message || '')
    .replace(/LightRAG\s*服务/gi, '知识库服务')
    .replace(/LightRAG/gi, '知识库服务')
    .replace(/Literature RAG\s*服务/gi, '知识库服务')
    .replace(/Literature RAG/gi, '知识库服务')
    .replace(/文献 RAG\s*服务/g, '知识库服务')
    .replace(/文献 RAG/g, '知识库服务')
    .replace(/知识库服务\s+/g, '知识库服务')
}

watch(activeModule, (module) => {
  updateRouteQuery({ module })
  if (module === 'graph') {
    ensureGraphLoaded()
  }
})

watch(
  () => route.query.module,
  (module) => {
    const nextModule = module === 'graph' ? 'graph' : 'rag'
    if (nextModule !== activeModule.value) {
      activeModule.value = nextModule
    }
  },
)

watch(
  () => route.query.system,
  (systemId) => {
    const nextSystemId = typeof systemId === 'string' ? systemId : ''
    if (nextSystemId && systems.value.some((item) => item.system_id === nextSystemId) && nextSystemId !== selectedSystemId.value) {
      selectedSystemId.value = nextSystemId
      resetWorkspace()
    }
  },
)

watch(
  canUseGraphContext,
  (enabled) => {
    queryForm.include_graph_context = Boolean(enabled)
  },
  { immediate: true },
)

watch(canLoadGraph, (enabled) => {
  if (enabled && activeModule.value === 'graph') {
    ensureGraphLoaded()
  }
})

function statusTagType(status) {
  if (status === 'ready') return 'success'
  if (['warning', 'indexing', 'empty'].includes(status)) return 'warning'
  return 'danger'
}

function systemStatusLabel(status) {
  const labels = {
    ready: '已连接',
    indexing: '索引中',
    empty: '未索引',
    warning: '需检查',
    unavailable: '不可用',
  }
  return labels[status] || '未知'
}

function hasCapability(system, capability) {
  return Array.isArray(system?.capabilities) && system.capabilities.includes(capability)
}

function updateRouteQuery(patch) {
  const nextQuery = { ...route.query, ...patch }
  Object.keys(nextQuery).forEach((key) => {
    if (!nextQuery[key]) delete nextQuery[key]
  })
  router.replace({ query: nextQuery })
}

function selectInitialSystem(systemData) {
  const items = systemData.items || []
  const routeSystemId = typeof route.query.system === 'string' ? route.query.system : ''
  const defaultSystemId = systemData.default_system_id || ''
  const candidates = [
    routeSystemId,
    defaultSystemId,
    items.find((item) => item.status === 'ready')?.system_id,
    items[0]?.system_id,
  ].filter(Boolean)
  const nextSystemId = candidates.find((systemId) => items.some((item) => item.system_id === systemId)) || ''
  selectedSystemId.value = nextSystemId
  updateRouteQuery({ system: nextSystemId || undefined })
}

function handleSystemChange() {
  resetWorkspace()
  updateRouteQuery({ system: selectedSystemId.value || undefined })
  if (activeModule.value === 'graph') {
    ensureGraphLoaded()
  }
}

function nodeTypeTag(type) {
  const map = {
    Material: 'success',
    Polymer: 'primary',
    Monomer: 'warning',
    Property: 'danger',
    Method: 'info',
    Strategy: 'warning',
    PerformanceMetric: 'danger',
    Paper: 'info',
    Dataset: 'success',
    Application: 'warning',
  }
  return map[type] || 'info'
}

async function loadBootstrap() {
  loadingSystems.value = true
  try {
    const [systemData, healthData] = await Promise.all([
      listKnowledgeSystems(),
      getKnowledgeHealth().catch(() => null),
    ])
    systems.value = systemData.items || []
    health.value = healthData
    selectInitialSystem(systemData)
    if (activeModule.value === 'graph') {
      await ensureGraphLoaded()
    }
  } catch (error) {
    ElMessage.error(normalizeKnowledgeMessage(getApiErrorMessage(error)))
  } finally {
    loadingSystems.value = false
  }
}

function defaultGraphQuery() {
  const tags = selectedSystem.value?.tags || []
  const krfTag = tags.find((tag) => /krf/i.test(tag))
  return krfTag || tags[0] || selectedSystem.value?.material_family || selectedSystem.value?.name || ''
}

async function ensureGraphLoaded() {
  if (!canLoadGraph.value || graph.value || graphLoading.value) return
  if (!graphForm.query.trim()) {
    graphForm.query = defaultGraphQuery()
  }
  if (graphForm.query.trim()) {
    await loadGraph({ silent: true })
  }
}

async function runQuery() {
  if (!canRunQuery.value || !selectedSystemId.value || !queryForm.question.trim()) return
  queryLoading.value = true
  answer.value = { answer: '', hits: [], citations: [], configured: true, message: canStreamQuery.value ? '知识库流式检索' : '知识库检索' }
  graph.value = null
  queryTrace.value = []
  const payload = {
    system_id: selectedSystemId.value,
    question: queryForm.question,
    mode: queryForm.mode,
    top_k: queryForm.top_k,
    include_graph_context: canUseGraphContext.value && queryForm.include_graph_context,
  }
  try {
    if (canStreamQuery.value) {
      await streamKnowledgeQuery(payload, (event) => {
        if (event.label) {
          queryTrace.value.push({ event: event.event, label: event.label, elapsed_ms: event.elapsed_ms })
        }
        if (event.event === 'evidence') {
          answer.value.hits = event.hits || []
          answer.value.citations = event.citations || []
          answer.value.graph_context = event.graph_context || null
          graph.value = event.graph_context || null
          selectedNodeId.value = graph.value?.nodes?.[0]?.id || ''
        }
        if (event.event === 'answer_delta') {
          answer.value.answer += event.content || ''
        }
        if (event.event === 'failed') {
          throw new Error(normalizeKnowledgeMessage(event.message || '知识库检索失败'))
        }
      })
    } else {
      const data = await queryKnowledgeBase(payload)
      answer.value = {
        ...data,
        hits: data?.hits || [],
        citations: data?.citations || [],
        answer: data?.answer || '',
        configured: data?.configured ?? true,
        message: normalizeKnowledgeMessage(data?.message || '知识库检索完成'),
      }
      graph.value = data?.graph_context || null
      selectedNodeId.value = graph.value?.nodes?.[0]?.id || ''
    }
  } catch (error) {
    answer.value = null
    ElMessage.error(normalizeKnowledgeMessage(getApiErrorMessage(error)))
  } finally {
    queryLoading.value = false
  }
}

async function loadGraph({ silent = false } = {}) {
  if (!canLoadGraph.value) {
    if (!silent) ElMessage.warning('当前知识库体系未提供可用图谱能力')
    return
  }
  if (!selectedSystemId.value || !graphForm.query.trim()) {
    if (!silent) ElMessage.warning('请输入实体或关键词后加载真实子图')
    return
  }
  graphLoading.value = true
  try {
    graph.value = await getKnowledgeSubgraph(selectedSystemId.value, { query: graphForm.query, limit: graphForm.limit })
    selectedNodeId.value = graph.value.nodes?.[0]?.id || ''
  } catch (error) {
    ElMessage.error(normalizeKnowledgeMessage(getApiErrorMessage(error)))
  } finally {
    graphLoading.value = false
  }
}

function resetWorkspace() {
  answer.value = null
  graph.value = null
  selectedNodeId.value = ''
  queryTrace.value = []
  suggestedQuestions.value = []
}

function openAnswerGraphContext() {
  if (!canOpenAnswerGraph.value) return
  graph.value = answerGraphContext.value
  selectedNodeId.value = graph.value.nodes?.[0]?.id || ''
  graphForm.query = queryForm.question
  activeModule.value = 'graph'
}

async function refreshAll() {
  resetWorkspace()
  await loadBootstrap()
}

async function loadSuggestedQuestions() {
  if (!canLoadSuggestions.value || !selectedSystemId.value) return
  suggestionsLoading.value = true
  try {
    const data = await generateKnowledgeSuggestions(selectedSystemId.value)
    suggestedQuestions.value = data.questions || []
  } catch (error) {
    suggestedQuestions.value = []
    ElMessage.error(normalizeKnowledgeMessage(getApiErrorMessage(error)))
  } finally {
    suggestionsLoading.value = false
  }
}

function selectNode(nodeId) {
  selectedNodeId.value = nodeId
}

onMounted(loadBootstrap)
</script>

<template>
  <div class="knowledge-page">
    <section class="panel knowledge-shell" v-loading="loadingSystems">
      <div class="panel-header knowledge-header">
        <div>
          <h3 class="panel-title">知识库工作台</h3>
          <p class="panel-subtitle">在同一工作区完成知识检索、证据核查和图谱关系浏览。</p>
        </div>
        <div class="header-actions">
          <el-select
            v-model="selectedSystemId"
            class="system-select"
            :disabled="!hasSystems"
            placeholder="暂无可用知识库体系"
            @change="handleSystemChange"
          >
            <el-option
              v-for="system in systems"
              :key="system.system_id"
              :label="system.name"
              :value="system.system_id"
            >
              <div class="system-option">
                <div>
                  <strong>{{ system.name }}</strong>
                  <small>{{ system.provider || 'unknown' }}:{{ system.corpus_id || system.system_id }} · {{ system.indexed_document_count || system.document_count || 0 }} docs</small>
                </div>
                <el-tag size="small" :type="statusTagType(system.status)" effect="plain">{{ systemStatusLabel(system.status) }}</el-tag>
              </div>
            </el-option>
          </el-select>
          <el-tag v-if="health || selectedSystem" :type="statusTagType(currentStatus)" effect="plain">
            {{ systemStatusLabel(currentStatus) }}
          </el-tag>
          <span class="status-message">{{ currentStatusMessage }}</span>
          <el-button :icon="Refresh" @click="refreshAll">刷新</el-button>
        </div>
      </div>

      <div class="panel-body knowledge-body">
        <div class="system-overview">
          <div v-if="selectedSystem" class="system-meta">
            <el-icon><Collection /></el-icon>
            <div>
              <strong>{{ selectedSystem.name }}</strong>
              <small>{{ selectedSystem.description || selectedSystem.data_source_id || selectedSystem.system_id }}</small>
            </div>
          </div>
          <div v-else class="system-meta">
            <el-icon><Collection /></el-icon>
            <div>
              <strong>未发现知识库体系</strong>
              <small>{{ currentStatusMessage }}</small>
            </div>
          </div>
          <div v-if="selectedSystem" class="system-metrics">
            <div v-for="item in systemMetricItems" :key="item.label" class="system-metric">
              <span>{{ item.label }}</span>
              <strong>{{ item.value }}</strong>
            </div>
          </div>
        </div>

        <el-tabs v-model="activeModule" class="knowledge-tabs">
          <el-tab-pane name="rag">
            <template #label>
              <span class="tab-label"><el-icon><ChatLineRound /></el-icon>知识增强检索问答</span>
            </template>
          </el-tab-pane>
          <el-tab-pane name="graph">
            <template #label>
              <span class="tab-label"><el-icon><Connection /></el-icon>知识图谱</span>
            </template>
          </el-tab-pane>
        </el-tabs>

        <div v-if="activeModule === 'rag'" class="rag-layout">
          <section class="query-pane">
            <div class="pane-heading">
              <span>Query</span>
              <strong>检索配置</strong>
            </div>
            <el-form label-position="top">
              <el-form-item label="问题">
                <el-input v-model="queryForm.question" type="textarea" :rows="7" maxlength="2000" show-word-limit :disabled="!canRunQuery" />
              </el-form-item>
              <div class="control-grid">
                <el-form-item label="模式">
                  <el-segmented
                    v-model="queryForm.mode"
                    class="knowledge-mode-segmented"
                    block
                    :disabled="!canRunQuery"
                    :options="[
                      { label: 'Hybrid', value: 'hybrid' },
                      { label: 'Local', value: 'local' },
                      { label: 'Global', value: 'global' },
                      { label: 'Naive', value: 'naive' },
                      { label: 'Mix', value: 'mix' },
                    ]"
                  />
                  <small class="control-help">
                    naive 纯向量；local 局部实体；global 全局主题；hybrid 局部+全局；mix 图谱+向量。
                  </small>
                </el-form-item>
                <el-form-item label="Top K">
                  <el-input-number v-model="queryForm.top_k" :min="1" :max="20" :disabled="!canRunQuery" />
                  <small class="control-help">重排后最多送入回答阶段的证据条数，不等于最终引用数。</small>
                </el-form-item>
              </div>
              <el-checkbox v-model="queryForm.include_graph_context" :disabled="!canUseGraphContext">返回图谱上下文</el-checkbox>
              <div class="query-actions">
                <el-button type="primary" :loading="queryLoading" :icon="Search" :disabled="!canRunQuery || !queryForm.question.trim()" @click="runQuery">检索问答</el-button>
              </div>
            </el-form>
            <div class="query-hints">
              <span>AI 建议问题</span>
              <el-button size="small" :loading="suggestionsLoading" :disabled="!canLoadSuggestions" @click="loadSuggestedQuestions">生成建议</el-button>
              <button v-for="question in suggestedQuestions" :key="question" type="button" @click="queryForm.question = question">{{ question }}</button>
            </div>
          </section>

          <section class="answer-pane" v-loading="queryLoading">
            <div v-if="queryTrace.length" class="query-trace" aria-live="polite">
              <span v-for="item in queryTrace" :key="`${item.event}-${item.elapsed_ms}`">
                {{ item.label }} · {{ item.elapsed_ms }} ms
              </span>
            </div>
            <div v-if="answer" class="answer-content">
              <div class="answer-topline">
                <el-tag :type="answer.configured ? 'success' : 'warning'" effect="plain">
                  {{ answer.configured ? '可用' : '降级' }}
                </el-tag>
                <span>{{ answer.message }}</span>
              </div>
              <div class="answer-grid">
                <article class="semantic-answer">
                  <div class="section-title-row answer-title-row">
                    <h4>综合回答</h4>
                    <div class="answer-title-actions">
                      <el-button
                        v-if="canOpenAnswerGraph"
                        size="small"
                        :icon="Connection"
                        @click="openAnswerGraphContext"
                      >
                        查看图谱上下文
                      </el-button>
                      <span>{{ queryForm.mode }} · Top {{ queryForm.top_k }}</span>
                    </div>
                  </div>
                  <template v-for="(block, index) in answerBlocks" :key="`${block.type}-${index}`">
                    <h4 v-if="block.type === 'heading'">{{ block.text }}</h4>
                    <p v-else-if="block.type === 'paragraph'" class="answer-text">
                      <template v-for="(segment, segIndex) in linkSegments(block.segments)" :key="segIndex">
                        <a v-if="segment.type === 'link'" :href="segment.href" target="_blank" rel="noreferrer">{{ segment.text }}</a>
                        <span v-else>{{ segment.text }}</span>
                      </template>
                    </p>
                    <ul v-else-if="block.type === 'list'" class="answer-list">
                      <li v-for="(item, itemIndex) in block.items" :key="itemIndex">
                        <template v-for="(segment, segIndex) in item" :key="segIndex">
                          <a v-if="segment.type === 'link'" :href="segment.href" target="_blank" rel="noreferrer">{{ segment.text }}</a>
                          <span v-else>{{ segment.text }}</span>
                        </template>
                      </li>
                    </ul>
                  </template>
                </article>

                <aside class="citation-panel">
                  <div class="pane-heading compact">
                    <span>References</span>
                    <strong>引用来源</strong>
                  </div>
                  <a
                    v-for="citation in topCitations"
                    :key="citation.source_id"
                    class="citation-card"
                    :href="citationUrl(citation)"
                    target="_blank"
                    rel="noreferrer"
                  >
                    <strong>{{ citation.title }}</strong>
                    <small>{{ citationMeta(citation) || citation.doi }}</small>
                    <span class="source-link-label">打开原文/PDF</span>
                  </a>
                  <span v-if="!topCitations.length" class="muted-text">本次回答没有可用论文链接。</span>
                </aside>
              </div>

              <div class="section-title-row">
                <h4>命中证据</h4>
                <span>{{ answer.hits.length }} sources</span>
              </div>
              <div class="hit-list">
                <article v-for="hit in answer.hits" :key="hit.source_id" class="hit-item">
                  <div class="hit-title">
                    <strong>{{ hit.title }}</strong>
                    <el-tag size="small" effect="plain">{{ hit.score.toFixed ? hit.score.toFixed(2) : hit.score }}</el-tag>
                  </div>
                  <p>{{ hit.snippet }}</p>
                  <div class="hit-footer">
                    <small>{{ shortSource(hit) }} · {{ sourceLevel(hit) }}</small>
                    <a v-if="citationUrl(hit)" :href="citationUrl(hit)" target="_blank" rel="noreferrer">打开原文/PDF</a>
                  </div>
                </article>
              </div>
            </div>
            <div v-else class="empty-state">
              <el-icon><DataAnalysis /></el-icon>
              <span>{{ queryUnavailableMessage }}</span>
            </div>
          </section>
        </div>

        <div v-else class="graph-layout">
          <section class="graph-toolbar">
            <div class="pane-heading compact">
              <span>Graph</span>
              <strong>子图检索</strong>
            </div>
            <div class="graph-controls">
              <el-input v-model="graphForm.query" placeholder="检索实体、论文、性质或方法" clearable :disabled="!canLoadGraph" @keyup.enter="loadGraph">
                <template #prefix><el-icon><Search /></el-icon></template>
              </el-input>
              <el-input-number v-model="graphForm.limit" :min="1" :max="100" :disabled="!canLoadGraph" />
              <el-button type="primary" :loading="graphLoading" :disabled="!canLoadGraph || !graphForm.query.trim()" @click="loadGraph">加载子图</el-button>
            </div>
          </section>

          <section class="graph-summary">
            <div>
              <span>Entities · {{ graphSummaryScope }}</span>
              <strong>{{ graphSummaryStats.entity_count }}</strong>
            </div>
            <div>
              <span>Relations · {{ graphSummaryScope }}</span>
              <strong>{{ graphSummaryStats.relation_count }}</strong>
            </div>
            <div>
              <span>Documents · {{ graphSummaryScope }}</span>
              <strong>{{ graphSummaryStats.document_count }}</strong>
            </div>
            <div class="type-legend">
              <el-tag v-for="item in graphTypeCounts" :key="item.type" size="small" effect="plain" :type="nodeTypeTag(item.type)">
                {{ item.type }} {{ item.count }}
              </el-tag>
            </div>
          </section>

          <section class="graph-workspace" v-loading="graphLoading">
            <div class="graph-board">
              <div v-for="lane in graphLanes" :key="lane.key" class="graph-lane">
                <div class="graph-lane-header">
                  <span>{{ lane.label }}</span>
                  <strong>{{ lane.nodes.length }}</strong>
                </div>
                <div class="graph-lane-body">
                  <button
                    v-for="node in lane.nodes"
                    :key="node.id"
                    type="button"
                    class="graph-node"
                    :class="{ active: node.id === selectedNode?.id }"
                    @click="selectNode(node.id)"
                  >
                    <span>{{ node.label }}</span>
                    <small>{{ node.type }}</small>
                  </button>
                  <span v-if="!lane.nodes.length" class="lane-empty">无节点</span>
                </div>
              </div>
              <div v-if="!graphNodes.length" class="empty-state">
                <el-icon><Connection /></el-icon>
                <span>{{ graphEmptyMessage }}</span>
              </div>
            </div>

            <aside class="node-detail">
              <div class="node-detail-header">
                <h4>{{ selectedNode?.label || '节点详情' }}</h4>
                <el-tag v-if="selectedNode" :type="nodeTypeTag(selectedNode.type)" effect="plain">{{ selectedNode.type }}</el-tag>
              </div>
              <a
                v-if="selectedNodeSourceUrl"
                class="node-source-link"
                :href="selectedNodeSourceUrl"
                target="_blank"
                rel="noreferrer"
              >
                打开原文/PDF
              </a>
              <el-descriptions v-if="selectedNode" :column="1" size="small" border>
                <el-descriptions-item label="ID">{{ selectedNode.id }}</el-descriptions-item>
                <el-descriptions-item label="Score">{{ selectedNode.score }}</el-descriptions-item>
              </el-descriptions>
              <pre v-if="selectedNode" class="property-json">{{ JSON.stringify(selectedNode.properties, null, 2) }}</pre>

              <div class="edge-list">
                <h4>关联关系</h4>
                <div v-for="edge in selectedNodeEdges" :key="edge.id" class="edge-item">
                  <el-tag size="small" effect="plain">{{ edge.type }}</el-tag>
                  <span>{{ nodeLabelById(edge.source) }} -> {{ nodeLabelById(edge.target) }}</span>
                </div>
                <span v-if="!selectedNodeEdges.length" class="muted-text">暂无关联关系。</span>
              </div>
            </aside>
          </section>
        </div>
      </div>
    </section>
  </div>
</template>

<style scoped>
.knowledge-page {
  display: flex;
  flex-direction: column;
  gap: 16px;
}

.knowledge-shell {
  overflow: hidden;
}

.knowledge-header {
  gap: 12px;
}

.panel-subtitle {
  margin: 6px 0 0;
  color: var(--app-ink-muted);
  font-size: 13px;
}

.header-actions,
.system-overview,
.system-meta,
.system-metrics,
.tab-label,
.query-actions,
.answer-topline,
.hit-title,
.graph-controls,
.graph-toolbar,
.node-detail-header,
.edge-item {
  display: flex;
  align-items: center;
}

.header-actions {
  flex-wrap: wrap;
  justify-content: flex-end;
  gap: 10px;
}

.system-select {
  width: 320px;
}

.system-option {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
  min-width: 0;
}

.system-option div {
  min-width: 0;
}

.system-option strong,
.system-option small {
  display: block;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.system-option small,
.status-message {
  color: var(--app-ink-muted);
  font-size: 12px;
}

.status-message {
  max-width: 260px;
  overflow-wrap: anywhere;
}

.knowledge-body {
  display: flex;
  flex-direction: column;
  gap: 14px;
}

.system-overview {
  min-height: 76px;
  justify-content: space-between;
  gap: 16px;
  padding: 14px;
  border: 1px solid var(--app-border-soft);
  border-radius: var(--app-radius-sm);
  background: #f8fbff;
}

.system-meta,
.tab-label {
  gap: 8px;
  font-weight: 700;
  color: var(--app-ink);
}

.system-meta small {
  display: block;
  margin-top: 2px;
  color: var(--app-ink-muted);
  font-size: 12px;
  font-weight: 400;
}

.system-metrics {
  display: grid;
  grid-template-columns: repeat(4, minmax(86px, 1fr));
  gap: 8px;
  min-width: 440px;
}

.system-metric {
  min-width: 0;
  padding: 10px 12px;
  border: 1px solid var(--app-border-soft);
  border-radius: var(--app-radius-sm);
  background: #ffffff;
}

.system-metric span {
  display: block;
  color: var(--app-ink-muted);
  font-size: 12px;
}

.system-metric strong {
  display: block;
  margin-top: 2px;
  color: var(--app-ink);
  font-size: 15px;
  overflow-wrap: anywhere;
}

.knowledge-tabs {
  margin-bottom: -4px;
}

.rag-layout {
  display: grid;
  grid-template-columns: 340px minmax(0, 1fr);
  gap: 16px;
}

.query-pane,
.answer-pane,
.node-detail {
  border: 1px solid var(--app-border-soft);
  border-radius: var(--app-radius-sm);
  background: #ffffff;
}

.query-pane,
.answer-pane {
  min-height: 480px;
  padding: 16px;
}

.query-pane {
  position: sticky;
  top: 74px;
}

.pane-heading {
  display: flex;
  flex-direction: column;
  gap: 2px;
  margin-bottom: 14px;
}

.pane-heading span {
  color: var(--app-ink-subtle);
  font-size: 11px;
  font-weight: 700;
  letter-spacing: 0.08em;
  text-transform: uppercase;
}

.pane-heading strong {
  color: var(--app-ink);
  font-size: 15px;
}

.pane-heading.compact {
  margin-bottom: 10px;
}

.control-grid {
  display: grid;
  grid-template-columns: minmax(0, 1fr);
  gap: 12px;
}

.control-grid :deep(.el-form-item) {
  min-width: 0;
}

.knowledge-mode-segmented {
  width: 100%;
}

.knowledge-mode-segmented :deep(.el-segmented__group) {
  width: 100%;
}

.knowledge-mode-segmented :deep(.el-segmented__item) {
  flex: 1 1 0;
  min-width: 0;
}

.knowledge-mode-segmented :deep(.el-segmented__item-label) {
  overflow: visible;
  text-overflow: clip;
  white-space: nowrap;
}

.query-actions {
  justify-content: flex-end;
  margin-top: 16px;
}

.query-hints {
  display: flex;
  flex-direction: column;
  gap: 8px;
  margin-top: 18px;
  padding-top: 14px;
  border-top: 1px solid var(--app-border-soft);
}

.query-hints span {
  color: var(--app-ink-muted);
  font-size: 12px;
  font-weight: 700;
}

.query-hints button {
  min-height: 34px;
  border: 1px solid var(--app-border-soft);
  border-radius: var(--app-radius-sm);
  background: #f8fafc;
  color: var(--app-ink-body);
  cursor: pointer;
  text-align: left;
  font-size: 12px;
}

.query-hints button:hover {
  border-color: var(--app-primary);
  color: var(--app-primary-active);
}

.query-hints button:disabled {
  cursor: not-allowed;
  opacity: 0.6;
}

.answer-content {
  display: flex;
  flex-direction: column;
  gap: 16px;
}

.section-title-row,
.hit-footer,
.graph-summary,
.type-legend,
.node-detail h4 {
  display: flex;
  align-items: center;
}

.answer-content h4,
.node-detail h4 {
  margin: 0;
  color: var(--app-ink);
  font-size: 14px;
}

.section-title-row {
  justify-content: space-between;
  gap: 12px;
}

.section-title-row span {
  color: var(--app-ink-muted);
  font-size: 12px;
}

.answer-topline {
  gap: 8px;
  color: var(--app-ink-muted);
  font-size: 13px;
}

.answer-grid {
  display: grid;
  grid-template-columns: minmax(0, 1fr) 280px;
  gap: 14px;
  align-items: start;
}

.semantic-answer {
  display: flex;
  flex-direction: column;
  gap: 10px;
  min-height: 260px;
  padding: 16px;
  border: 1px solid #dce5f5;
  border-radius: var(--app-radius-sm);
  background: #fbfdff;
}

.answer-title-row {
  padding-bottom: 10px;
  border-bottom: 1px solid var(--app-border-soft);
}

.answer-title-actions {
  display: flex;
  align-items: center;
  justify-content: flex-end;
  gap: 8px;
  min-width: 0;
}

.semantic-answer h4 {
  padding-top: 4px;
  color: #0b2d63;
  font-size: 15px;
}

.answer-text {
  margin: 0;
  color: var(--app-ink-body);
  line-height: 1.75;
}

.semantic-answer a,
.citation-card,
.hit-footer a {
  color: var(--app-primary-active);
  text-decoration: none;
}

.semantic-answer a:hover,
.citation-card:hover,
.hit-footer a:hover {
  text-decoration: underline;
}

.answer-list {
  margin: 0;
  padding-left: 18px;
  color: var(--app-ink-body);
  line-height: 1.7;
}

.citation-panel {
  display: flex;
  flex-direction: column;
  gap: 8px;
  min-width: 0;
  padding: 14px;
  border: 1px solid var(--app-border-soft);
  border-radius: var(--app-radius-sm);
  background: #ffffff;
}

.citation-card {
  display: flex;
  flex-direction: column;
  gap: 4px;
  padding: 10px;
  border: 1px solid var(--app-border-soft);
  border-radius: var(--app-radius-sm);
  background: #f8fafc;
}

.citation-card strong {
  display: -webkit-box;
  overflow: hidden;
  color: var(--app-ink);
  font-size: 12px;
  line-height: 1.45;
  -webkit-box-orient: vertical;
  -webkit-line-clamp: 3;
}

.citation-card small,
.muted-text,
.source-link-label {
  color: var(--app-ink-muted);
  font-size: 12px;
}

.source-link-label {
  color: var(--app-primary-active);
  font-weight: 700;
}

.hit-list,
.edge-list {
  display: flex;
  flex-direction: column;
  gap: 10px;
}

.hit-item {
  padding: 12px;
  border: 1px solid var(--app-border-soft);
  border-radius: var(--app-radius-sm);
  background: #fbfdff;
}

.hit-title {
  justify-content: space-between;
  gap: 8px;
}

.hit-item p {
  margin: 8px 0;
  color: var(--app-ink-body);
  font-size: 13px;
  line-height: 1.6;
}

.hit-item small {
  color: var(--app-ink-muted);
}

.hit-footer {
  justify-content: space-between;
  gap: 10px;
}

.empty-state {
  min-height: 220px;
  display: flex;
  align-items: center;
  justify-content: center;
  gap: 8px;
  color: var(--app-ink-muted);
}

.graph-layout {
  display: flex;
  flex-direction: column;
  gap: 12px;
}

.graph-toolbar {
  justify-content: space-between;
  gap: 12px;
  padding: 12px;
  border: 1px solid var(--app-border-soft);
  border-radius: var(--app-radius-sm);
  background: #ffffff;
}

.graph-toolbar .pane-heading {
  margin-bottom: 0;
  min-width: 120px;
}

.graph-controls {
  flex: 1;
  gap: 10px;
}

.graph-summary {
  justify-content: space-between;
  gap: 12px;
  padding: 12px;
  border: 1px solid var(--app-border-soft);
  border-radius: var(--app-radius-sm);
  background: #ffffff;
}

.graph-summary > div:not(.type-legend) {
  display: flex;
  flex-direction: column;
  min-width: 86px;
}

.graph-summary span {
  color: var(--app-ink-muted);
  font-size: 12px;
}

.graph-summary strong {
  color: var(--app-ink);
  font-size: 20px;
}

.type-legend {
  flex: 1;
  flex-wrap: wrap;
  justify-content: flex-end;
  gap: 6px;
}

.graph-workspace {
  display: grid;
  grid-template-columns: minmax(0, 1fr) 320px;
  gap: 16px;
}

.graph-board {
  min-height: 560px;
  display: grid;
  grid-template-columns: repeat(4, 1fr);
  gap: 10px;
  padding: 10px;
  border: 1px solid var(--app-border-soft);
  border-radius: var(--app-radius-sm);
  background: #f8fafc;
}

.graph-lane {
  min-width: 0;
  display: flex;
  flex-direction: column;
  border: 1px solid #e1e8f2;
  border-radius: var(--app-radius-sm);
  background: #ffffff;
}

.graph-lane-header {
  min-height: 38px;
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 8px;
  padding: 10px 12px;
  border-bottom: 1px solid var(--app-border-soft);
  color: var(--app-ink-subtle);
  font-size: 11px;
  font-weight: 800;
  letter-spacing: 0.06em;
  text-transform: uppercase;
}

.graph-lane-header strong {
  color: var(--app-ink-muted);
  font-size: 12px;
}

.graph-lane-body {
  min-height: 0;
  max-height: 508px;
  overflow: auto;
  display: flex;
  flex-direction: column;
  gap: 8px;
  padding: 10px;
}

.graph-node {
  width: 100%;
  min-height: 48px;
  border: 1px solid #d4dfec;
  border-radius: var(--app-radius-sm);
  background: #ffffff;
  color: var(--app-ink);
  cursor: pointer;
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  gap: 2px;
  padding: 8px;
  text-align: center;
  box-shadow: 0 8px 16px rgba(15, 23, 42, 0.06);
}

.graph-node.active {
  border-color: var(--app-primary);
  box-shadow: 0 0 0 3px rgba(59, 130, 246, 0.14);
}

.graph-node span {
  max-width: 100%;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  font-size: 12px;
  font-weight: 700;
}

.graph-node small {
  color: var(--app-ink-muted);
  font-size: 11px;
}

.graph-node:hover {
  border-color: var(--app-primary);
}

.lane-empty {
  min-height: 48px;
  display: flex;
  align-items: center;
  justify-content: center;
  border: 1px dashed var(--app-border-soft);
  border-radius: var(--app-radius-sm);
  color: var(--app-ink-muted);
  font-size: 12px;
}

.node-source-link {
  min-height: 34px;
  display: inline-flex;
  align-items: center;
  justify-content: center;
  border: 1px solid #b7d2ff;
  border-radius: var(--app-radius-sm);
  background: #eef5ff;
  color: var(--app-primary-active);
  font-size: 13px;
  font-weight: 700;
  text-decoration: none;
}

.node-source-link:hover {
  border-color: var(--app-primary);
  text-decoration: underline;
}

.node-detail {
  min-height: 560px;
  padding: 14px;
  display: flex;
  flex-direction: column;
  gap: 12px;
}

.node-detail-header {
  justify-content: space-between;
  gap: 8px;
}

.property-json {
  min-height: 120px;
  max-height: 220px;
  overflow: auto;
  margin: 0;
  padding: 10px;
  border-radius: var(--app-radius-sm);
  background: #0f172a;
  color: #dbeafe;
  font-family: var(--app-mono-font);
  font-size: 12px;
}

.edge-item {
  gap: 8px;
  min-height: 34px;
  padding: 6px 8px;
  border: 1px solid var(--app-border-soft);
  border-radius: var(--app-radius-sm);
  color: var(--app-ink-body);
  font-size: 12px;
  min-width: 0;
}

.edge-item span {
  min-width: 0;
  overflow-wrap: anywhere;
}

.control-help {
  display: block;
  margin-top: 6px;
  color: var(--app-ink-muted);
  font-size: 12px;
  line-height: 1.45;
}

.query-trace {
  display: flex;
  flex-wrap: wrap;
  gap: 6px;
  padding: 10px 14px;
  border-bottom: 1px solid var(--app-border-soft);
  background: #f8fafc;
}

.query-trace span {
  color: var(--app-ink-muted);
  font-size: 12px;
}

@media (max-width: 1100px) {
  .rag-layout,
  .graph-workspace {
    grid-template-columns: 1fr;
  }

  .query-pane,
  .answer-pane,
  .node-detail {
    min-height: auto;
  }

  .query-pane {
    position: static;
  }

  .answer-grid {
    grid-template-columns: 1fr;
  }
}

@media (max-width: 700px) {
  .knowledge-header,
  .system-overview,
  .graph-toolbar,
  .graph-controls,
  .graph-summary {
    align-items: stretch;
    flex-direction: column;
  }

  .header-actions {
    justify-content: stretch;
  }

  .system-select {
    width: 100%;
  }

  .system-metrics {
    grid-template-columns: repeat(2, minmax(0, 1fr));
    min-width: 0;
  }

  .control-grid {
    grid-template-columns: 1fr;
  }

  .graph-board {
    grid-template-columns: repeat(2, minmax(0, 1fr));
    min-height: 520px;
  }

  .type-legend {
    justify-content: flex-start;
  }
}

@media (max-width: 420px) {
  .system-metrics {
    grid-template-columns: 1fr;
  }

  .query-pane,
  .answer-pane,
  .citation-panel,
  .node-detail {
    padding: 12px;
  }

  .graph-board {
    grid-template-columns: 1fr;
  }
}
</style>
