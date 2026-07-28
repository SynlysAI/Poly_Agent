<script setup>
import { computed, onMounted, reactive, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { ElMessage } from 'element-plus'
import {
  Close,
  ChatLineRound,
  Collection,
  Connection,
  DataAnalysis,
  Expand,
  Fold,
  Loading,
  Refresh,
  Search,
  Setting,
} from '@element-plus/icons-vue'
import VChart from 'vue-echarts'
import { use } from 'echarts/core'
import { GraphChart } from 'echarts/charts'
import { LegendComponent, TooltipComponent } from 'echarts/components'
import { CanvasRenderer } from 'echarts/renderers'

import {
  getApiErrorMessage,
  getKnowledgeHealth,
  getKnowledgeSubgraph,
  generateKnowledgeSuggestions,
  listKnowledgeSystems,
  queryKnowledgeBase,
  streamKnowledgeQuery,
} from '../api/polyAgentApi'
import { promptToGraphQuery } from '../utils/knowledgeGraphKeywords.mjs'

use([
  GraphChart,
  LegendComponent,
  TooltipComponent,
  CanvasRenderer,
])

const route = useRoute()
const router = useRouter()

const systems = ref([])
const health = ref(null)
const selectedSystemId = ref(typeof route.query.system === 'string' ? route.query.system : '')
const loadingSystems = ref(false)
const queryLoading = ref(false)
const graphLoading = ref(false)
const answer = ref(null)
const graph = ref(null)
const queryError = ref('')
const graphError = ref('')
const searchBatchId = ref(0)
const activeTab = ref(normalizeKnowledgeTab(route.query.tab, route.query.module))
const graphViewMode = ref('relationship')
const selectedNodeId = ref('')
const suggestedQuestions = ref([])
const suggestionsLoading = ref(false)
const topBarCollapsed = ref(false)
const queryTrace = ref([])
const queryPaneCollapsed = ref(true)
const citationPanelCollapsed = ref(true)
const nodeDetailCollapsed = ref(false)
const nodeDetailDrawerVisible = ref(false)

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
const graphStats = computed(() => graph.value?.stats || {})
const graphSummaryStats = computed(() => graph.value?.stats || {
  entity_count: firstDefinedNumber(selectedSystem.value?.entity_count),
  relation_count: firstDefinedNumber(selectedSystem.value?.relation_count),
  document_count: firstDefinedNumber(selectedSystem.value?.indexed_document_count, selectedSystem.value?.document_count),
})
const graphSummaryScope = computed(() => graph.value ? '当前子图' : '体系总量')
const selectedNode = computed(() => graphNodes.value.find((item) => item.id === selectedNodeId.value) || graphNodes.value[0] || null)
const selectedNodeEdges = computed(() =>
  graphEdges.value.filter((item) => item.source === selectedNode.value?.id || item.target === selectedNode.value?.id),
)
const graphNodeDegreeMap = computed(() => {
  const degreeMap = {}
  graphEdges.value.forEach((edge) => {
    degreeMap[edge.source] = (degreeMap[edge.source] || 0) + 1
    degreeMap[edge.target] = (degreeMap[edge.target] || 0) + 1
  })
  return degreeMap
})
const answerBlocks = computed(() => parseMarkdownBlocks(answer.value?.answer || ''))
const graphSourceLabel = computed(() => sourceStatusLabel(graph.value || selectedSystem.value || health.value))
const graphEnhancementStatus = computed(() => {
  if (!graph.value) return ''
  if (graph.value.graph_backend === 'weknora-wiki-graph') {
    const returned = graph.value.provenance?.wiki_returned
    const total = graph.value.provenance?.wiki_total
    if (returned && total) return `WeKnora Wiki 页面链接图谱：已显示 ${returned}/${total} 个页面节点`
    return 'WeKnora Wiki 页面链接图谱'
  }
  if (graph.value.graph_backend === 'weknora-neo4j') {
    return '已根据 WeKnora 命中证据反查 Neo4j 实体邻域'
  }
  if (graph.value.graph_backend === 'search-synthesis') {
    return '基于 WeKnora 命中证据生成检索子图'
  }
  return graph.value.message || ''
})
const graphSummaryItems = computed(() => [
  { label: graph.value?.graph_backend === 'weknora-wiki-graph' ? '当前页面' : '实体', value: graphSummaryStats.value.entity_count, scope: graphSummaryScope.value },
  { label: graph.value?.graph_backend === 'weknora-wiki-graph' ? '链接' : '关系', value: graphSummaryStats.value.relation_count, scope: graphSummaryScope.value },
  { label: graph.value?.graph_backend === 'weknora-wiki-graph' ? '页面总量' : '文档', value: graphSummaryStats.value.document_count, scope: graphSummaryScope.value },
].filter((item) => hasDisplayValue(item.value)))
const systemMetricItems = computed(() => {
  const isWikiGraph = graph.value?.graph_backend === 'weknora-wiki-graph'
  const documentCount = firstDefinedNumber(
    graphStats.value.document_count,
    selectedSystem.value?.indexed_document_count,
    selectedSystem.value?.document_count,
  )
  const entityCount = firstDefinedNumber(graphStats.value.entity_count, selectedSystem.value?.entity_count)
  const relationCount = firstDefinedNumber(graphStats.value.relation_count, selectedSystem.value?.relation_count)
  const sourceLabel = graphSourceLabel.value || sourceStatusLabel(selectedSystem.value || health.value)
  return [
    { label: isWikiGraph ? '页面' : '文档', value: documentCount },
    { label: isWikiGraph ? '当前节点' : '实体', value: entityCount },
    { label: isWikiGraph ? '链接' : '关系', value: relationCount },
    { label: '图谱来源', value: sourceLabel },
  ].filter((item) => hasDisplayValue(item.value))
})
const selectedSystemSubtitle = computed(() => systemSubtitle(selectedSystem.value))
const currentStatus = computed(() => selectedSystem.value?.status || health.value?.status || 'unavailable')
const currentStatusLabel = computed(() => sourceStatusLabel(selectedSystem.value || health.value) || systemStatusLabel(currentStatus.value))
const currentStatusMessage = computed(() =>
  normalizeKnowledgeMessage(selectedSystem.value?.health_message || health.value?.message || queryUnavailableMessage.value),
)
const canRunQuery = computed(() => hasCapability(selectedSystem.value, 'query') && selectedSystem.value?.status === 'ready')
const canStreamQuery = computed(() => canRunQuery.value && hasCapability(selectedSystem.value, 'streaming'))
const canLoadGraph = computed(() => hasCapability(selectedSystem.value, 'graph') && selectedSystem.value?.status === 'ready')
const canUseGraphSearchControls = computed(() => canLoadGraph.value && !queryLoading.value && !graphLoading.value)
const canUseGraphContext = computed(() => canRunQuery.value && canLoadGraph.value)
const canLoadSuggestions = computed(() => hasCapability(selectedSystem.value, 'suggestions') && selectedSystem.value?.status === 'ready')
const hasJointResults = computed(() => Boolean(
  answer.value
  || graph.value
  || queryError.value
  || graphError.value
  || queryLoading.value
  || graphLoading.value
  || queryTrace.value.length,
))
const showQueryLanding = computed(() => !hasJointResults.value)
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
const graphCategories = computed(() => graphTypeCounts.value.map((item) => ({
  name: nodeTypeLabel(item.type),
  itemStyle: { color: graphTypeColor(item.type) },
})))
const graphForceOptions = computed(() => {
  if (graph.value?.graph_backend === 'weknora-wiki-graph') {
    return {
      repulsion: 1080,
      edgeLength: [180, 320],
      gravity: 0.015,
      friction: 0.16,
    }
  }
  return {
    repulsion: 320,
    edgeLength: [100, 180],
    gravity: 0.06,
    friction: 0.2,
  }
})
const knowledgeGraphOption = computed(() => ({
  color: graphCategories.value.map((item) => item.itemStyle.color),
  legend: {
    type: 'scroll',
    orient: 'vertical',
    right: 10,
    top: 16,
    bottom: 16,
    textStyle: { color: '#64748b', fontSize: 11 },
    data: graphCategories.value.map((item) => item.name),
  },
  tooltip: {
    trigger: 'item',
    confine: true,
    formatter: graphTooltipFormatter,
  },
  series: [{
    type: 'graph',
    layout: 'force',
    categories: graphCategories.value,
    data: graphNodes.value.map((node) => {
      const degree = graphNodeDegreeMap.value[node.id] || 0
      const isSelected = node.id === selectedNode.value?.id
      return {
        id: node.id,
        name: node.label || node.id,
        value: Number(node.score || degree || 1),
        category: nodeTypeLabel(node.type),
        symbolSize: graphSymbolSize(node, degree),
        draggable: true,
        raw: node,
        label: {
          show: isSelected || shouldShowGraphNodeLabel(degree),
          position: 'right',
          color: '#0f172a',
          fontSize: 11,
          width: 136,
          overflow: 'truncate',
        },
        itemStyle: {
          color: graphTypeColor(node.type),
          borderColor: isSelected ? '#0f172a' : '#ffffff',
          borderWidth: isSelected ? 3 : 1,
        },
      }
    }),
    links: graphEdges.value.map((edge, index) => ({
      id: edge.id || `${edge.source}-${edge.target}-${edge.type}-${index}`,
      source: edge.source,
      target: edge.target,
      name: edge.type,
      raw: edge,
      lineStyle: {
        color: '#94a3b8',
        opacity: 0.7,
        width: edge.source === selectedNode.value?.id || edge.target === selectedNode.value?.id ? 2.2 : 1,
        curveness: 0.08,
      },
      label: {
        show: edge.source === selectedNode.value?.id || edge.target === selectedNode.value?.id,
        formatter: edge.type,
        color: '#475569',
        fontSize: 10,
      },
    })),
    roam: true,
    edgeSymbol: ['none', 'arrow'],
    edgeSymbolSize: 7,
    focusNodeAdjacency: true,
    force: graphForceOptions.value,
    emphasis: {
      focus: 'adjacency',
      lineStyle: { width: 2.5 },
      label: { show: true },
    },
    labelLayout: {
      hideOverlap: true,
    },
    animationDurationUpdate: 350,
  }],
}))
const topCitations = computed(() => answer.value?.citations?.filter((item) => citationUrl(item)).slice(0, 8) || [])
const answerGraphContext = computed(() => answer.value?.graph_context || null)
const canOpenAnswerGraph = computed(() => (answerGraphContext.value?.nodes || []).length > 0)
const graphEmptyMessage = computed(() => {
  if (isProductionNeo4j(selectedSystem.value) && !hasNeo4jGraphData(selectedSystem.value)) return 'Neo4j 已连接，但 KrF 图谱尚未完成 worker 索引。'
  if (!canLoadGraph.value) return '该知识库体系未提供可用图谱。'
  if (graphError.value) return graphError.value
  if (!graph.value) return '提交问题后将自动拆解关键词并加载对应知识图谱。'
  return '当前关键词未匹配到图谱节点。'
})
const graphLanes = computed(() => {
  if (graph.value?.graph_backend === 'weknora-wiki-graph') {
    const lanes = [
      { key: 'summary', label: '摘要', types: ['Summary'], nodes: [] },
      { key: 'entities', label: '实体', types: ['Entity'], nodes: [] },
      { key: 'concepts', label: '概念', types: ['Concept'], nodes: [] },
      { key: 'synthesis', label: '综合', types: ['Synthesis'], nodes: [] },
      { key: 'comparison', label: '对比', types: ['Comparison', 'Index', 'WikiPage'], nodes: [] },
    ]
    graphNodes.value.forEach((node) => {
      const lane = lanes.find((item) => item.types.includes(node.type)) || lanes[lanes.length - 1]
      lane.nodes.push(node)
    })
    return lanes
  }
  const lanes = [
    { key: 'materials', label: '材料', types: ['Material', 'Polymer', 'Resin', 'Monomer', 'PhotoacidGenerator', 'Additive'], nodes: [] },
    { key: 'strategies', label: '策略方法', types: ['Strategy', 'Method', 'ProcessCondition'], nodes: [] },
    { key: 'properties', label: '性质指标', types: ['Property', 'LithographyMetric', 'PerformanceMetric', 'Application'], nodes: [] },
    { key: 'entities', label: '实体', types: ['Entity'], nodes: [] },
    { key: 'papers', label: '论文片段', types: ['Paper', 'Dataset', 'Chunk'], nodes: [] },
  ]
  const fallbackLane = lanes.find((item) => item.key === 'entities') || lanes[lanes.length - 1]
  graphNodes.value.forEach((node) => {
    const lane = lanes.find((item) => item.types.includes(node.type)) || fallbackLane
    lane.nodes.push(node)
  })
  return lanes
})
const selectedNodeSourceUrl = computed(() => selectedNode.value?.properties?.source_url || citationUrl(selectedNode.value?.properties || {}))
const selectedNodeSnippet = computed(() => textProperty(selectedNode.value?.properties, ['snippet', 'content', 'text', 'abstract']))
const selectedNodeAttributes = computed(() => arrayProperty(selectedNode.value?.properties?.attributes))
const selectedNodeChunks = computed(() => arrayProperty(selectedNode.value?.properties?.chunks))
const selectedNodeDetailRows = computed(() => buildNodeDetailRows(selectedNode.value))
const selectedNodePropertyJson = computed(() => {
  const properties = selectedNode.value?.properties || {}
  if (!Object.keys(properties).length) return ''
  return JSON.stringify(properties, null, 2)
})

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

function hasDisplayValue(value) {
  if (value === null || value === undefined) return false
  if (Array.isArray(value)) return value.length > 0
  return String(value).trim() !== ''
}

function firstDefinedNumber(...values) {
  for (const value of values) {
    if (value === null || value === undefined || value === '') continue
    const numberValue = Number(value)
    if (!Number.isNaN(numberValue)) return numberValue
  }
  return null
}

function joinDisplayParts(parts) {
  return parts.filter(hasDisplayValue).join(' · ')
}

function systemSubtitle(system) {
  if (!system) return ''
  return joinDisplayParts([
    system.description,
    system.data_source_id,
    sourceStatusLabel(system),
    system.system_id,
  ])
}

function systemOptionMeta(system) {
  const documentCount = firstDefinedNumber(system?.indexed_document_count, system?.document_count)
  const identityParts = [system?.provider, system?.corpus_id || system?.system_id].filter(hasDisplayValue)
  return joinDisplayParts([
    identityParts.length ? identityParts.join(':') : '',
    hasDisplayValue(documentCount) ? `${documentCount} docs` : '',
    sourceStatusLabel(system) || system?.graph_backend,
  ])
}

function textProperty(properties, keys) {
  if (!properties) return ''
  for (const key of keys) {
    if (hasDisplayValue(properties[key])) return String(properties[key])
  }
  return ''
}

function arrayProperty(value) {
  if (!Array.isArray(value)) return []
  return value.map((item) => String(item).trim()).filter(Boolean)
}

function formatScore(score) {
  if (!hasDisplayValue(score)) return ''
  const numberValue = Number(score)
  if (Number.isNaN(numberValue)) return String(score)
  return numberValue.toFixed(2)
}

function hitFooterText(hit) {
  return joinDisplayParts([shortSource(hit), sourceLevel(hit)])
}

function evidenceItemKey(item) {
  const metadata = item?.metadata || {}
  return [
    metadata.chunk_id,
    metadata.parent_chunk_id,
    item?.chunk_id,
    item?.source_id,
    item?.title,
    item?.snippet,
  ].map((part) => String(part || '').trim()).filter(Boolean).join('|')
}

function evidenceRenderKey(hit, index) {
  return evidenceItemKey(hit) || `hit-${index}`
}

function mergeEvidenceItem(existing, incoming) {
  return {
    ...existing,
    ...incoming,
    metadata: {
      ...(existing?.metadata || {}),
      ...(incoming?.metadata || {}),
    },
  }
}

function mergeEvidenceItems(currentItems = [], incomingItems = []) {
  const merged = []
  const itemByKey = new Map()
  const append = (item) => {
    if (!item) return
    const key = evidenceItemKey(item)
    if (!key) {
      merged.push(item)
      return
    }
    const existing = itemByKey.get(key)
    if (existing) {
      Object.assign(existing, mergeEvidenceItem(existing, item))
      return
    }
    const nextItem = { ...item, metadata: { ...(item.metadata || {}) } }
    itemByKey.set(key, nextItem)
    merged.push(nextItem)
  }
  currentItems.forEach(append)
  incomingItems.forEach(append)
  return merged.slice(0, queryForm.top_k)
}

function appendQueryTrace(event) {
  if (!event?.label) return
  const traceKey = `${event.event || 'progress'}:${event.label}`
  const hasSameStage = queryTrace.value.some((item) => item.traceKey === traceKey)
  if (hasSameStage) return
  queryTrace.value.push({
    id: `${Date.now()}-${queryTrace.value.length}`,
    traceKey,
    event: event.event,
    label: event.label,
    elapsed_ms: event.elapsed_ms,
  })
}

function buildNodeDetailRows(node) {
  if (!node) return []
  const properties = node.properties || {}
  const scoreValue = node.type === 'Entity' && properties.graph_backend === 'weknora-neo4j'
    ? ''
    : formatScore(node.score)
  const propertyRows = [
    { label: 'Knowledge ID', value: properties.knowledge_id },
    { label: 'Slug', value: properties.slug },
    { label: 'Page Type', value: properties.page_type },
    { label: 'Link Count', value: properties.link_count },
    { label: '文件', value: properties.knowledge_filename || properties.filename || properties.file_name },
    { label: 'Chunk ID', value: properties.chunk_id || properties.parent_chunk_id },
    { label: 'Chunk Index', value: properties.chunk_index },
    { label: 'DOI', value: properties.doi },
    { label: '来源', value: properties.source },
    { label: '年份', value: properties.year },
  ]
  return [
    { label: 'ID', value: node.id },
    { label: 'Score', value: scoreValue },
    ...propertyRows,
  ].filter((item) => hasDisplayValue(item.value))
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
  if (!sourceKind) return ''
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
    .replace(/WeKnora\s*服务/gi, '知识库服务')
    .replace(/WeKnora/gi, '知识库服务')
    .replace(/LightRAG\s*服务/gi, '知识库服务')
    .replace(/LightRAG/gi, '知识库服务')
    .replace(/知识库服务\s+/g, '知识库服务')
}

function normalizeKnowledgeTab(tab, module) {
  const normalizedTab = Array.isArray(tab) ? tab[0] : tab
  if (normalizedTab === 'graph') return 'graph'
  if (normalizedTab === 'literature') return 'literature'
  return module === 'graph' ? 'graph' : 'literature'
}

function setGraphQueryFromQuestion(question) {
  graphForm.query = promptToGraphQuery(question, { maxKeywords: 10 })
}

function useQuestionForGraphSearch() {
  if (queryLoading.value || graphLoading.value || !queryForm.question.trim()) return
  setGraphQueryFromQuestion(queryForm.question)
  activeTab.value = 'graph'
}

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
  () => [route.query.tab, route.query.module],
  ([tab, module]) => {
    const nextTab = normalizeKnowledgeTab(tab, module)
    if (nextTab !== activeTab.value) activeTab.value = nextTab
  },
)

watch(activeTab, (tab) => {
  updateRouteQuery({ tab: tab === 'graph' ? 'graph' : 'literature' })
})

watch(
  canUseGraphContext,
  (enabled) => {
    queryForm.include_graph_context = Boolean(enabled)
  },
  { immediate: true },
)

watch(canLoadGraph, (enabled) => {
  if (enabled && hasJointResults.value && !graph.value && !graphLoading.value && queryForm.question.trim()) {
    setGraphQueryFromQuestion(queryForm.question)
    void runGraphQueryForBatch(searchBatchId.value, graphForm.query || queryForm.question)
  }
})

function statusTagType(status) {
  if (status === 'ready') return 'success'
  if (['warning', 'indexing', 'empty'].includes(status)) return 'warning'
  return 'danger'
}

function systemStatusLabel(status, system = null) {
  const sourceLabel = sourceStatusLabel(system)
  if (sourceLabel) return sourceLabel
  const labels = {
    ready: '已连接',
    indexing: '索引中',
    empty: '未索引',
    warning: '需检查',
    unavailable: '不可用',
  }
  return labels[status] || '未知'
}

function sourceStatusLabel(source) {
  if (!source) return ''
  if (source.graph_backend === 'weknora-wiki-graph') {
    return 'WeKnora / Wiki 图谱'
  }
  if (source.graph_backend === 'weknora-neo4j') {
    return 'WeKnora / Neo4j 图谱增强'
  }
  if (source.graph_backend === 'search-synthesis') {
    return 'WeKnora / 检索子图'
  }
  if (source.provider === 'weknora' || source.backend === 'weknora') {
    return 'WeKnora / 知识库检索'
  }
  if (source.is_demo || source.backend === 'memory' || source.graph_backend === 'memory') {
    return 'Demo / Memory 数据，非 Neo4j'
  }
  if (isProductionNeo4j(source)) {
    return hasNeo4jGraphData(source) ? 'Neo4j / 真实 PDF 索引' : 'Neo4j 已连接，等待 worker 索引'
  }
  return ''
}

function isProductionNeo4j(source) {
  return source?.backend === 'production' && source?.graph_backend === 'neo4j'
}

function hasNeo4jGraphData(source) {
  return Number(source?.graph_node_count || 0) > 0 && Number(source?.graph_relationship_count || 0) > 0
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
  if (canLoadSuggestions.value) {
    loadSuggestedQuestions()
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
    Summary: 'success',
    Entity: 'primary',
    Concept: 'success',
    Synthesis: 'warning',
    Comparison: 'danger',
    Index: 'info',
    WikiPage: 'info',
    Paper: 'info',
    Chunk: 'info',
    Dataset: 'success',
    Application: 'warning',
  }
  return map[type] || 'info'
}

function nodeTypeLabel(type) {
  const map = {
    Summary: '摘要',
    Entity: '实体',
    Concept: '概念',
    Synthesis: '综合',
    Comparison: '对比',
    Index: '索引',
    WikiPage: 'Wiki 页面',
    Material: '材料',
    Polymer: '聚合物',
    Resin: '树脂',
    Monomer: '单体',
    PhotoacidGenerator: '光酸产生剂',
    Additive: '添加剂',
    Strategy: '策略',
    Method: '方法',
    ProcessCondition: '工艺条件',
    Property: '性质',
    LithographyMetric: '光刻指标',
    PerformanceMetric: '性能指标',
    Application: '应用',
    Paper: '论文',
    Dataset: '数据集',
    Chunk: '片段',
  }
  return map[type] || type || '未知'
}

function graphSymbolSize(node, degree) {
  if (graph.value?.graph_backend === 'weknora-wiki-graph') {
    const linkCount = Number(node?.properties?.link_count || node?.score || degree || 1)
    return Math.max(20, Math.min(42, 20 + Math.sqrt(linkCount) * 2.2))
  }
  return Math.max(24, Math.min(56, 28 + degree * 3.2))
}

function shouldShowGraphNodeLabel(degree) {
  if (graph.value?.graph_backend === 'weknora-wiki-graph') {
    return degree >= 4
  }
  return degree > 1
}

function graphNodeTitle(node) {
  return `${node?.label || ''} · ${nodeTypeLabel(node?.type)}`
}

function graphTypeColor(type) {
  const map = {
    Material: '#2f855a',
    Polymer: '#2563eb',
    Resin: '#0891b2',
    Monomer: '#d97706',
    PhotoacidGenerator: '#9333ea',
    Additive: '#7c3aed',
    Property: '#dc2626',
    LithographyMetric: '#b7791f',
    PerformanceMetric: '#e11d48',
    Method: '#1d4ed8',
    Strategy: '#0f766e',
    ProcessCondition: '#ca8a04',
    Summary: '#2563eb',
    Concept: '#10b981',
    Synthesis: '#f97316',
    Comparison: '#ef4444',
    Index: '#64748b',
    WikiPage: '#64748b',
    Paper: '#64748b',
    Dataset: '#16a34a',
    Chunk: '#475569',
    Entity: '#7c3aed',
    Application: '#ea580c',
  }
  return map[type] || '#64748b'
}

function escapeHtml(value) {
  return String(value ?? '')
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;')
    .replace(/'/g, '&#039;')
}

function graphTooltipFormatter(params) {
  if (params.dataType === 'edge') {
    const edge = params.data?.raw || params.data || {}
    return [
      `<strong>${escapeHtml(edge.type || params.name || '关系')}</strong>`,
      `${escapeHtml(nodeLabelById(edge.source))} -&gt; ${escapeHtml(nodeLabelById(edge.target))}`,
    ].join('<br/>')
  }
  const node = params.data?.raw || params.data || {}
  return [
    `<strong>${escapeHtml(node.label || params.name || node.id)}</strong>`,
    `类型：${escapeHtml(nodeTypeLabel(node.type))}`,
    `ID：${escapeHtml(node.id || '')}`,
  ].join('<br/>')
}

function handleGraphChartClick(params) {
  if (params.dataType !== 'node') return
  const nodeId = params.data?.id || params.data?.raw?.id
  if (nodeId) selectNode(nodeId)
}

function shouldUseNodeDetailDrawer() {
  return typeof window !== 'undefined' && window.matchMedia('(max-width: 1100px)').matches
}

function openNodeDetailPanel() {
  if (shouldUseNodeDetailDrawer()) {
    nodeDetailDrawerVisible.value = true
  } else {
    nodeDetailCollapsed.value = false
  }
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
    if (canLoadSuggestions.value) {
      void loadSuggestedQuestions()
    }
  } catch (error) {
    ElMessage.error(normalizeKnowledgeMessage(getApiErrorMessage(error)))
  } finally {
    loadingSystems.value = false
  }
}

async function runQuery() {
  if (!canRunQuery.value || !selectedSystemId.value || !queryForm.question.trim()) return
  const batchId = searchBatchId.value + 1
  const question = queryForm.question.trim()
  searchBatchId.value = batchId
  queryLoading.value = true
  graphLoading.value = canLoadGraph.value
  queryError.value = ''
  graphError.value = ''
  answer.value = { answer: '', hits: [], citations: [], configured: true, message: canStreamQuery.value ? '知识库流式检索' : '知识库检索' }
  graph.value = null
  setGraphQueryFromQuestion(question)
  selectedNodeId.value = ''
  queryTrace.value = []
  const payload = {
    system_id: selectedSystemId.value,
    question,
    mode: queryForm.mode,
    top_k: queryForm.top_k,
    include_graph_context: canUseGraphContext.value && queryForm.include_graph_context,
  }
  const literatureTask = runLiteratureQueryForBatch(batchId, payload)
  const graphTask = runGraphQueryForBatch(batchId, graphForm.query || question)
  await Promise.allSettled([literatureTask, graphTask])
}

async function runLiteratureQueryForBatch(batchId, payload) {
  try {
    if (canStreamQuery.value) {
      await streamKnowledgeQuery(payload, (event) => {
        if (batchId !== searchBatchId.value) return
        appendQueryTrace(event)
        if (event.event === 'evidence') {
          answer.value.hits = mergeEvidenceItems(answer.value.hits || [], event.hits || [])
          answer.value.citations = mergeEvidenceItems(answer.value.citations || [], event.citations || [])
          answer.value.graph_context = event.graph_context || answer.value.graph_context || null
          if (!graph.value && graphError.value && (event.graph_context?.nodes || []).length) {
            graph.value = event.graph_context
            selectedNodeId.value = event.graph_context.nodes?.[0]?.id || ''
            graphError.value = ''
          }
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
      if (batchId !== searchBatchId.value) return
      answer.value = {
        ...data,
        hits: data?.hits || [],
        citations: data?.citations || [],
        answer: data?.answer || '',
        configured: data?.configured ?? true,
        message: normalizeKnowledgeMessage(data?.message || '知识库检索完成'),
      }
      if (!graph.value && graphError.value && (data?.graph_context?.nodes || []).length) {
        graph.value = data.graph_context
        selectedNodeId.value = data.graph_context.nodes?.[0]?.id || ''
        graphError.value = ''
      }
    }
  } catch (error) {
    if (batchId !== searchBatchId.value) return
    answer.value = null
    queryError.value = normalizeKnowledgeMessage(getApiErrorMessage(error))
    ElMessage.error(queryError.value)
  } finally {
    if (batchId === searchBatchId.value) {
      queryLoading.value = false
    }
  }
}

async function runGraphQueryForBatch(batchId, question) {
  if (!canLoadGraph.value) {
    graphLoading.value = false
    graphError.value = '当前知识库体系未提供可用图谱能力。'
    return
  }
  if (!selectedSystemId.value || !question.trim()) {
    graphLoading.value = false
    graphError.value = '请输入问题后加载对应知识图谱。'
    return
  }
  graphLoading.value = true
  try {
    const data = await getKnowledgeSubgraph(selectedSystemId.value, { query: question, limit: graphForm.limit })
    if (batchId !== searchBatchId.value) return
    graph.value = data
    selectedNodeId.value = data?.nodes?.[0]?.id || ''
  } catch (error) {
    if (batchId !== searchBatchId.value) return
    const fallbackGraph = answerGraphContext.value
    if ((fallbackGraph?.nodes || []).length) {
      graph.value = fallbackGraph
      selectedNodeId.value = fallbackGraph.nodes?.[0]?.id || ''
      graphError.value = ''
      return
    }
    graph.value = null
    graphError.value = normalizeKnowledgeMessage(getApiErrorMessage(error))
    ElMessage.error(graphError.value)
  } finally {
    if (batchId === searchBatchId.value) {
      graphLoading.value = false
    }
  }
}

async function loadGraph({ silent = false } = {}) {
  if (queryLoading.value || graphLoading.value) {
    if (!silent) ElMessage.warning('联合检索正在进行，请稍后再检索图谱')
    return
  }
  if (!canLoadGraph.value) {
    if (!silent) ElMessage.warning('当前知识库体系未提供可用图谱能力')
    return
  }
  if (!selectedSystemId.value || !graphForm.query.trim()) {
    if (!silent) ElMessage.warning('请输入实体或关键词后加载真实子图')
    return
  }
  graphLoading.value = true
  graphError.value = ''
  try {
    graph.value = await getKnowledgeSubgraph(selectedSystemId.value, { query: graphForm.query, limit: graphForm.limit })
    selectedNodeId.value = graph.value.nodes?.[0]?.id || ''
  } catch (error) {
    graphError.value = normalizeKnowledgeMessage(getApiErrorMessage(error))
    ElMessage.error(graphError.value)
  } finally {
    graphLoading.value = false
  }
}

function resetWorkspace() {
  searchBatchId.value += 1
  answer.value = null
  graph.value = null
  queryError.value = ''
  graphError.value = ''
  queryLoading.value = false
  graphLoading.value = false
  selectedNodeId.value = ''
  queryTrace.value = []
  suggestedQuestions.value = []
}

function openAnswerGraphContext() {
  if (!canOpenAnswerGraph.value) return
  graph.value = answerGraphContext.value
  selectedNodeId.value = graph.value.nodes?.[0]?.id || ''
  setGraphQueryFromQuestion(queryForm.question)
  activeTab.value = 'graph'
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
  if (nodeDetailCollapsed.value || shouldUseNodeDetailDrawer()) {
    openNodeDetailPanel()
  }
}

onMounted(loadBootstrap)
</script>

<template>
  <div class="knowledge-page">
    <section class="panel knowledge-shell" v-loading="loadingSystems">
      <div v-if="topBarCollapsed" class="knowledge-dock">
        <div class="dock-summary">
          <span>知识库工作台</span>
          <strong>{{ selectedSystem?.name || '未选择知识库' }}</strong>
          <el-tag v-if="health || selectedSystem" size="small" :type="statusTagType(currentStatus)" effect="plain">
            {{ currentStatusLabel }}
          </el-tag>
        </div>
        <div class="dock-actions">
          <span class="dock-status">{{ currentStatusMessage }}</span>
          <el-button size="small" :icon="Expand" @click="topBarCollapsed = false">展开</el-button>
        </div>
      </div>

      <div v-else class="panel-header knowledge-header" :class="{ 'landing-header': showQueryLanding }">
        <div>
          <h3 class="panel-title">知识增强</h3>
          <p v-if="!showQueryLanding" class="panel-subtitle">知识检索、证据核查与图谱关系</p>
        </div>
        <div class="header-actions">
          <el-select
            v-model="selectedSystemId"
            class="system-select"
            popper-class="knowledge-system-select-popper"
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
              <div class="system-option-meta">
                <strong>{{ system.name }}</strong>
                <small v-if="systemOptionMeta(system)">{{ systemOptionMeta(system) }}</small>
              </div>
              <el-tag size="small" :type="statusTagType(system.status)" effect="plain">{{ systemStatusLabel(system.status, system) }}</el-tag>
            </div>
            </el-option>
          </el-select>
          <el-tag v-if="health || selectedSystem" :type="statusTagType(currentStatus)" effect="plain">
            {{ currentStatusLabel }}
          </el-tag>
          <span v-if="!showQueryLanding" class="status-message">{{ currentStatusMessage }}</span>
          <el-button :icon="Refresh" circle aria-label="刷新知识库" @click="refreshAll" />
          <el-button v-if="!showQueryLanding" :icon="Fold" @click="topBarCollapsed = true">隐藏</el-button>
        </div>
      </div>

      <div class="panel-body knowledge-body">
        <div v-if="!showQueryLanding" class="system-overview">
          <div v-if="selectedSystem" class="system-meta">
            <el-icon><Collection /></el-icon>
            <div>
              <strong>{{ selectedSystem.name }}</strong>
              <small v-if="selectedSystemSubtitle">{{ selectedSystemSubtitle }}</small>
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

        <section v-if="showQueryLanding && activeTab === 'literature'" class="knowledge-query-entry">
          <div class="entry-heading">
            <el-icon><ChatLineRound /></el-icon>
            <h2>知识检索</h2>
          </div>
          <div class="entry-composer">
            <el-input
              v-model="queryForm.question"
              type="textarea"
              :rows="4"
              maxlength="2000"
              resize="none"
              placeholder="输入需要检索的问题"
              :disabled="!canRunQuery"
              @keydown.ctrl.enter.prevent="runQuery"
            />
            <el-button
              class="entry-submit"
              type="primary"
              :icon="Search"
              :loading="queryLoading"
              :disabled="!canRunQuery || !queryForm.question.trim()"
              @click="runQuery"
            >
              检索
            </el-button>
          </div>
          <div class="entry-suggestions">
            <div class="entry-suggestion-head">
              <span>建议问题</span>
              <el-button text size="small" :loading="suggestionsLoading" :disabled="!canLoadSuggestions" @click="loadSuggestedQuestions">换一组</el-button>
            </div>
            <div class="entry-suggestion-list">
              <button v-for="question in suggestedQuestions" :key="question" type="button" @click="queryForm.question = question">{{ question }}</button>
              <span v-if="!suggestedQuestions.length" class="muted-text">当前暂无建议问题</span>
            </div>
          </div>
          <el-collapse class="entry-advanced">
            <el-collapse-item name="advanced">
              <template #title>
                <span class="entry-advanced-title"><el-icon><Setting /></el-icon>高级设置</span>
              </template>
              <div class="entry-advanced-grid">
                <label>
                  <span>证据条数</span>
                  <el-input-number v-model="queryForm.top_k" :min="1" :max="20" :disabled="!canRunQuery" />
                </label>
                <label>
                  <span>图谱节点上限</span>
                  <el-input-number v-model="graphForm.limit" :min="1" :max="100" :disabled="!canUseGraphSearchControls" />
                </label>
                <el-checkbox v-model="queryForm.include_graph_context" :disabled="!canUseGraphContext">回答携带图谱上下文</el-checkbox>
              </div>
            </el-collapse-item>
          </el-collapse>
          <span v-if="!canRunQuery" class="entry-status">{{ queryUnavailableMessage }}</span>
        </section>

        <div v-else class="knowledge-results-shell">
          <section v-if="!showQueryLanding || activeTab === 'graph'" class="result-search-bar">
            <el-input
              v-model="queryForm.question"
              type="textarea"
              :rows="2"
              maxlength="2000"
              resize="none"
              placeholder="输入需要检索的问题"
              :disabled="!canRunQuery"
              @keydown.ctrl.enter.prevent="runQuery"
            />
            <div class="result-search-actions">
              <el-button text size="small" :icon="Setting" @click="queryPaneCollapsed = !queryPaneCollapsed">
                {{ queryPaneCollapsed ? '展开配置' : '收起配置' }}
              </el-button>
              <el-button type="primary" :loading="queryLoading || graphLoading" :icon="Search" :disabled="!canRunQuery || !queryForm.question.trim()" @click="runQuery">联合检索</el-button>
            </div>
          </section>

          <section v-if="!showQueryLanding && !queryPaneCollapsed" class="query-pane inline-query-pane">
            <div class="pane-toolbar">
              <div class="pane-heading">
                <span>Query</span>
                <strong>检索配置</strong>
              </div>
              <el-button text size="small" :icon="Fold" @click="queryPaneCollapsed = true">收起</el-button>
            </div>
            <el-form label-position="top">
              <div class="control-grid inline-control-grid">
                <el-form-item label="证据条数">
                  <el-input-number v-model="queryForm.top_k" :min="1" :max="20" :disabled="!canRunQuery" />
                  <small class="control-help">控制 PolyAgent 展示和传入回答上下文的 WeKnora 命中证据数量。</small>
                </el-form-item>
                <el-form-item label="图谱节点上限">
                  <el-input-number v-model="graphForm.limit" :min="1" :max="100" :disabled="!canUseGraphSearchControls" />
                  <small class="control-help">控制 Wiki 图谱或降级检索图谱返回的节点数量。</small>
                </el-form-item>
                <el-form-item label="回答上下文">
                  <el-checkbox v-model="queryForm.include_graph_context" :disabled="!canUseGraphContext">返回图谱上下文</el-checkbox>
                  <small class="control-help">开启后，联合检索会把图谱上下文随回答结果一起返回。</small>
                </el-form-item>
              </div>
            </el-form>
          </section>

          <el-tabs v-model="activeTab" class="knowledge-workspace-tabs">
            <el-tab-pane label="文献检索" name="literature">
              <div class="rag-layout literature-results-layout" :class="{ 'citations-collapsed': citationPanelCollapsed }">

          <section class="answer-pane" :class="{ 'answer-pane--streaming': queryLoading }">
            <div v-if="queryTrace.length" class="query-trace" aria-live="polite">
              <span v-for="item in queryTrace" :key="item.id">
                {{ item.label }}<template v-if="item.elapsed_ms !== undefined"> · {{ item.elapsed_ms }} ms</template>
              </span>
            </div>
            <div v-if="answer" class="answer-content">
              <div class="answer-topline">
                <el-tag :type="answer.configured ? 'success' : 'warning'" effect="plain">
                  {{ answer.configured ? '可用' : '降级' }}
                </el-tag>
                <span>{{ answer.message }}</span>
                <span v-if="queryLoading" class="streaming-status">正在接收 WeKnora 流式结果</span>
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
                      <span>证据 {{ queryForm.top_k }} 条</span>
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
                  <div
                    v-if="queryLoading"
                    class="answer-generation-indicator"
                    :class="{ 'answer-generation-indicator--centered': !answer.answer }"
                    aria-live="polite"
                  >
                    <el-icon class="answer-loading-icon"><Loading /></el-icon>
                    <span>{{ answer.answer ? '综合回答持续生成中' : '综合回答正在生成，命中证据可先查看' }}</span>
                  </div>
                </article>

                <aside v-if="!citationPanelCollapsed" class="citation-panel">
                  <div class="pane-toolbar compact">
                    <div class="pane-heading compact">
                      <span>References</span>
                      <strong>引用来源</strong>
                    </div>
                    <el-button text size="small" :icon="Fold" @click="citationPanelCollapsed = true">收起</el-button>
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
                <button
                  v-else
                  type="button"
                  class="side-restore-button citation-restore-button"
                  aria-label="展开引用来源"
                  @click="citationPanelCollapsed = false"
                >
                  <el-icon><Expand /></el-icon>
                  <span>引用</span>
                </button>
              </div>
              <div class="section-title-row">
                <h4>命中证据</h4>
                <span>{{ answer.hits.length }} sources</span>
              </div>
              <div class="hit-list">
                <article v-for="(hit, index) in answer.hits" :key="evidenceRenderKey(hit, index)" class="hit-item">
                  <div class="hit-title">
                    <strong>{{ hit.title || hit.source_id || '命中证据' }}</strong>
                    <el-tag v-if="formatScore(hit.score)" size="small" effect="plain">{{ formatScore(hit.score) }}</el-tag>
                  </div>
                  <p v-if="hit.snippet">{{ hit.snippet }}</p>
                  <div class="hit-footer">
                    <small v-if="hitFooterText(hit)">{{ hitFooterText(hit) }}</small>
                    <a v-if="citationUrl(hit)" :href="citationUrl(hit)" target="_blank" rel="noreferrer">打开原文/PDF</a>
                  </div>
                </article>
                <div v-if="queryLoading && !answer.hits.length" class="inline-loading-state">
                  WeKnora 正在返回命中证据
                </div>
              </div>
            </div>
            <div v-else class="empty-state">
              <el-icon><DataAnalysis /></el-icon>
              <span>{{ queryError || queryUnavailableMessage }}</span>
            </div>
          </section>

              </div>
            </el-tab-pane>

            <el-tab-pane label="知识图谱" name="graph">
          <div class="graph-layout graph-tab-panel">
          <section class="graph-toolbar">
            <div class="pane-heading compact">
              <span>图谱</span>
              <strong>子图检索</strong>
            </div>
            <div class="graph-controls">
              <el-input v-model="graphForm.query" placeholder="检索 Wiki 页面、实体或概念" clearable :disabled="!canUseGraphSearchControls" @keyup.enter="loadGraph">
                <template #prefix><el-icon><Search /></el-icon></template>
              </el-input>
              <el-button :disabled="queryLoading || graphLoading || !queryForm.question.trim()" @click="useQuestionForGraphSearch">使用当前问题</el-button>
              <el-input-number v-model="graphForm.limit" :min="1" :max="100" :disabled="!canUseGraphSearchControls" />
              <el-button type="primary" :loading="graphLoading" :disabled="!canUseGraphSearchControls || !graphForm.query.trim()" @click="loadGraph">检索图谱</el-button>
            </div>
          </section>

          <section class="graph-summary">
            <div v-for="item in graphSummaryItems" :key="item.label">
              <span>{{ item.label }} · {{ item.scope }}</span>
              <strong>{{ item.value }}</strong>
            </div>
            <div v-if="graphSourceLabel || graphEnhancementStatus" class="graph-source-status">
              <el-tag v-if="graphSourceLabel" size="small" effect="plain" type="success">{{ graphSourceLabel }}</el-tag>
              <span v-if="graphEnhancementStatus">{{ graphEnhancementStatus }}</span>
            </div>
            <div class="type-legend">
              <el-tag v-for="item in graphTypeCounts" :key="item.type" size="small" effect="plain" :type="nodeTypeTag(item.type)">
                {{ nodeTypeLabel(item.type) }} {{ item.count }}
              </el-tag>
            </div>
            <el-segmented
              v-model="graphViewMode"
              class="graph-view-segmented"
              :options="[
                { label: '关系图', value: 'relationship' },
                { label: '分栏视图', value: 'columns' },
              ]"
            />
            <el-button size="small" :icon="Expand" :disabled="!selectedNode" @click="openNodeDetailPanel">节点详情</el-button>
          </section>

          <section class="graph-workspace" :class="{ 'detail-collapsed': nodeDetailCollapsed }" v-loading="graphLoading">
            <div class="graph-main-pane">
              <div class="graph-chart-pane" :class="{ active: graphViewMode === 'relationship' }">
                <VChart
                  v-if="graphNodes.length"
                  class="relationship-chart"
                  :option="knowledgeGraphOption"
                  autoresize
                  @click="handleGraphChartClick"
                />
                <div v-else class="empty-state">
                  <el-icon><Connection /></el-icon>
                  <span>{{ graphEmptyMessage }}</span>
                </div>
              </div>

              <div class="graph-board-pane" :class="{ active: graphViewMode === 'columns' }">
                <div class="graph-board">
                  <div v-for="lane in graphLanes" :key="lane.key" class="graph-lane" :class="`graph-lane--${lane.key}`">
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
                        :class="[`graph-node--${lane.key}`, { active: node.id === selectedNode?.id }]"
                        :title="graphNodeTitle(node)"
                        @click="selectNode(node.id)"
                      >
                        <span>{{ node.label }}</span>
                        <small>{{ nodeTypeLabel(node.type) }}</small>
                      </button>
                      <span v-if="!lane.nodes.length" class="lane-empty">无节点</span>
                    </div>
                  </div>
                  <div v-if="!graphNodes.length" class="empty-state">
                    <el-icon><Connection /></el-icon>
                    <span>{{ graphEmptyMessage }}</span>
                  </div>
                </div>
              </div>
            </div>

            <button
              v-if="nodeDetailCollapsed"
              type="button"
              class="side-restore-button node-restore-button"
              aria-label="展开节点详情"
              @click="openNodeDetailPanel"
            >
              <el-icon><Expand /></el-icon>
              <span>详情</span>
            </button>

            <aside v-else class="node-detail">
              <div class="node-detail-header">
                <h4>{{ selectedNode?.label || '节点详情' }}</h4>
                <div class="node-detail-actions">
                  <el-tag v-if="selectedNode" :type="nodeTypeTag(selectedNode.type)" effect="plain">{{ nodeTypeLabel(selectedNode.type) }}</el-tag>
                  <el-button text size="small" :icon="Fold" @click="nodeDetailCollapsed = true">收起</el-button>
                </div>
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
              <p v-if="selectedNodeSnippet" class="node-snippet">{{ selectedNodeSnippet }}</p>
              <div v-if="selectedNodeAttributes.length" class="node-chip-block">
                <span>属性</span>
                <div>
                  <el-tag v-for="item in selectedNodeAttributes" :key="item" size="small" effect="plain">{{ item }}</el-tag>
                </div>
              </div>
              <div v-if="selectedNodeChunks.length" class="node-chip-block">
                <span>片段</span>
                <div>
                  <el-tag v-for="item in selectedNodeChunks.slice(0, 8)" :key="item" size="small" effect="plain" type="info">{{ item }}</el-tag>
                  <small v-if="selectedNodeChunks.length > 8">+{{ selectedNodeChunks.length - 8 }}</small>
                </div>
              </div>
              <el-descriptions v-if="selectedNodeDetailRows.length" :column="1" size="small" border>
                <el-descriptions-item v-for="item in selectedNodeDetailRows" :key="item.label" :label="item.label">
                  <span class="node-id-text" :title="String(item.value)">{{ item.value }}</span>
                </el-descriptions-item>
              </el-descriptions>
              <details v-if="selectedNodePropertyJson" class="node-raw-block">
                <summary>原始属性</summary>
                <pre class="property-json">{{ selectedNodePropertyJson }}</pre>
              </details>

              <div class="edge-list">
                <h4>关联关系</h4>
                <div v-for="edge in selectedNodeEdges" :key="edge.id" class="edge-item">
                  <span class="edge-node" :title="nodeLabelById(edge.source)">{{ nodeLabelById(edge.source) }}</span>
                  <el-tag size="small" effect="plain">{{ edge.type }}</el-tag>
                  <span class="edge-arrow">-&gt;</span>
                  <span class="edge-node" :title="nodeLabelById(edge.target)">{{ nodeLabelById(edge.target) }}</span>
                </div>
                <span v-if="!selectedNodeEdges.length" class="muted-text">暂无关联关系。</span>
              </div>
            </aside>
          </section>
        </div>
            </el-tab-pane>
          </el-tabs>
      </div>
      </div>
    </section>

    <el-drawer v-model="nodeDetailDrawerVisible" title="节点详情" size="min(420px, 92vw)">
      <template v-if="selectedNode">
        <div class="node-detail drawer-node-detail">
          <div class="node-detail-header">
            <h4>{{ selectedNode.label || '节点详情' }}</h4>
            <div class="node-detail-actions">
              <el-tag :type="nodeTypeTag(selectedNode.type)" effect="plain">{{ nodeTypeLabel(selectedNode.type) }}</el-tag>
              <el-button text size="small" :icon="Close" @click="nodeDetailDrawerVisible = false">关闭</el-button>
            </div>
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
          <p v-if="selectedNodeSnippet" class="node-snippet">{{ selectedNodeSnippet }}</p>
          <div v-if="selectedNodeAttributes.length" class="node-chip-block">
            <span>属性</span>
            <div>
              <el-tag v-for="item in selectedNodeAttributes" :key="item" size="small" effect="plain">{{ item }}</el-tag>
            </div>
          </div>
          <div v-if="selectedNodeChunks.length" class="node-chip-block">
            <span>片段</span>
            <div>
              <el-tag v-for="item in selectedNodeChunks.slice(0, 8)" :key="item" size="small" effect="plain" type="info">{{ item }}</el-tag>
              <small v-if="selectedNodeChunks.length > 8">+{{ selectedNodeChunks.length - 8 }}</small>
            </div>
          </div>
          <el-descriptions v-if="selectedNodeDetailRows.length" :column="1" size="small" border>
            <el-descriptions-item v-for="item in selectedNodeDetailRows" :key="item.label" :label="item.label">
              <span class="node-id-text" :title="String(item.value)">{{ item.value }}</span>
            </el-descriptions-item>
          </el-descriptions>
          <details v-if="selectedNodePropertyJson" class="node-raw-block">
            <summary>原始属性</summary>
            <pre class="property-json">{{ selectedNodePropertyJson }}</pre>
          </details>

          <div class="edge-list">
            <h4>关联关系</h4>
            <div v-for="edge in selectedNodeEdges" :key="edge.id" class="edge-item">
              <span class="edge-node" :title="nodeLabelById(edge.source)">{{ nodeLabelById(edge.source) }}</span>
              <el-tag size="small" effect="plain">{{ edge.type }}</el-tag>
              <span class="edge-arrow">-&gt;</span>
              <span class="edge-node" :title="nodeLabelById(edge.target)">{{ nodeLabelById(edge.target) }}</span>
            </div>
            <span v-if="!selectedNodeEdges.length" class="muted-text">暂无关联关系。</span>
          </div>
        </div>
      </template>
    </el-drawer>
  </div>
</template>

<style scoped>
.knowledge-page {
  display: flex;
  flex-direction: column;
  gap: 16px;
}

:global(.app-main:has(.knowledge-page)) {
  height: calc(100vh - 58px);
  overflow: auto;
}

.knowledge-shell {
  overflow: visible;
}

.knowledge-dock,
.knowledge-header {
  position: sticky;
  top: 0;
  z-index: 12;
  background: rgba(255, 255, 255, 0.96);
  backdrop-filter: blur(10px);
  box-shadow: 0 8px 18px rgba(22, 59, 110, 0.06);
}

.knowledge-dock {
  min-height: 46px;
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
  padding: 8px 14px;
  border-bottom: 1px solid var(--app-border-soft);
  border-radius: var(--app-radius-lg) var(--app-radius-lg) 0 0;
}

.dock-summary,
.dock-actions {
  display: flex;
  align-items: center;
  gap: 8px;
  min-width: 0;
}

.dock-summary {
  flex: 1 1 auto;
}

.dock-summary span {
  color: var(--app-ink-muted);
  font-size: 12px;
  font-weight: 700;
  white-space: nowrap;
}

.dock-summary strong {
  min-width: 0;
  overflow: hidden;
  color: var(--app-ink);
  font-size: 14px;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.dock-actions {
  flex: 0 1 auto;
  justify-content: flex-end;
}

.dock-status {
  max-width: 360px;
  overflow: hidden;
  color: var(--app-ink-muted);
  font-size: 12px;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.knowledge-header {
  align-items: flex-start;
  flex-wrap: wrap;
  gap: 12px 16px;
  border-radius: var(--app-radius-lg) var(--app-radius-lg) 0 0;
}

.panel-subtitle {
  margin: 6px 0 0;
  color: var(--app-ink-muted);
  font-size: 13px;
}

.header-actions,
.dock-summary,
.dock-actions,
.system-overview,
.system-meta,
.system-metrics,
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
  flex: 1 1 560px;
  flex-wrap: wrap;
  justify-content: flex-end;
  gap: 10px 12px;
}

.system-select {
  width: clamp(280px, 34vw, 440px);
  max-width: 100%;
}

.system-option {
  display: grid;
  grid-template-columns: minmax(0, 1fr) auto;
  align-items: flex-start;
  justify-content: space-between;
  gap: 12px;
  min-width: 0;
  width: 100%;
}

:global(.knowledge-system-select-popper .el-select-dropdown__item) {
  height: auto;
  min-height: 76px;
  padding: 12px 14px;
  align-items: flex-start;
  line-height: normal;
}

.system-option :deep(.el-tag) {
  flex: 0 0 auto;
}

.system-option-meta {
  display: flex;
  flex-direction: column;
  gap: 4px;
  min-width: 0;
}

.system-option strong,
.system-option small {
  overflow: hidden;
}

.system-option strong {
  display: -webkit-box;
  color: var(--app-ink);
  font-size: 14px;
  line-height: 1.35;
  -webkit-box-orient: vertical;
  -webkit-line-clamp: 2;
  overflow-wrap: anywhere;
}

.system-option small {
  display: -webkit-box;
  color: var(--app-ink-muted);
  font-size: 12px;
  line-height: 1.55;
  -webkit-box-orient: vertical;
  -webkit-line-clamp: 2;
  white-space: normal;
  overflow-wrap: anywhere;
}

.system-option small,
.status-message {
  color: var(--app-ink-muted);
  font-size: 12px;
}

.status-message {
  flex: 0 1 280px;
  min-width: 0;
  max-width: 260px;
  overflow-wrap: anywhere;
}

.knowledge-body {
  display: flex;
  flex-direction: column;
  gap: 14px;
}

.knowledge-header.landing-header {
  align-items: center;
  padding-block: 10px;
}

.knowledge-query-entry {
  width: min(820px, 100%);
  min-height: 430px;
  display: flex;
  flex-direction: column;
  justify-content: center;
  align-self: center;
  gap: 18px;
  padding: 36px 16px 52px;
}

.entry-heading {
  display: flex;
  align-items: center;
  justify-content: center;
  gap: 10px;
  color: var(--app-ink);
}

.entry-heading .el-icon { color: var(--app-primary-active); font-size: 24px; }
.entry-heading h2 { margin: 0; font-size: 24px; letter-spacing: 0; }
.entry-composer { position: relative; }
.entry-composer :deep(.el-textarea__inner) {
  min-height: 132px !important;
  padding: 18px 112px 18px 18px;
  border-radius: var(--app-radius-md);
  font-size: 15px;
  line-height: 1.7;
  box-shadow: 0 0 0 1px var(--app-border) inset;
}
.entry-composer :deep(.el-textarea__inner:focus) { box-shadow: 0 0 0 1px var(--app-primary-active) inset; }
.entry-submit { position: absolute; right: 14px; bottom: 14px; min-width: 88px; }
.entry-suggestions { display: grid; gap: 10px; }
.entry-suggestion-head { display: flex; align-items: center; justify-content: space-between; gap: 12px; }
.entry-suggestion-head > span { color: var(--app-ink-muted); font-size: 12px; font-weight: 700; }
.entry-suggestion-list { display: flex; flex-wrap: wrap; gap: 8px; }
.entry-suggestion-list button {
  max-width: 100%;
  padding: 8px 11px;
  border: 1px solid var(--app-border-soft);
  border-radius: var(--app-radius-sm);
  background: #fff;
  color: var(--app-ink-body);
  cursor: pointer;
  font: inherit;
  font-size: 12px;
  line-height: 1.45;
  text-align: left;
  overflow-wrap: anywhere;
}
.entry-suggestion-list button:hover,
.entry-suggestion-list button:focus-visible { border-color: var(--app-primary); color: var(--app-primary-active); outline: none; }
.entry-advanced { border-top: 1px solid var(--app-border-soft); border-bottom: 1px solid var(--app-border-soft); }
.entry-advanced-title { display: inline-flex; align-items: center; gap: 7px; color: var(--app-ink-body); font-size: 13px; }
.entry-advanced-grid {
  display: grid;
  grid-template-columns: minmax(0, 1fr) auto auto;
  align-items: end;
  gap: 16px;
  padding-bottom: 14px;
}
.entry-advanced-grid > label { display: grid; gap: 7px; color: var(--app-ink-muted); font-size: 12px; }
.entry-status { color: var(--app-ink-muted); font-size: 13px; text-align: center; }

.system-overview {
  min-height: 76px;
  flex-wrap: wrap;
  justify-content: space-between;
  align-items: flex-start;
  gap: 16px;
  padding: 14px;
  border: 1px solid var(--app-border-soft);
  border-radius: var(--app-radius-sm);
  background: #f8fbff;
}

.system-meta {
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
  flex: 1 1 440px;
  display: grid;
  grid-template-columns: repeat(4, minmax(86px, 1fr));
  gap: 8px;
  min-width: 0;
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

.knowledge-results-shell {
  display: flex;
  flex-direction: column;
  gap: 12px;
}

.result-search-bar {
  display: grid;
  grid-template-columns: minmax(0, 1fr) auto;
  align-items: end;
  gap: 12px;
  padding: 12px;
  border: 1px solid var(--app-border-soft);
  border-radius: var(--app-radius-sm);
  background: #ffffff;
}

.result-search-bar :deep(.el-textarea__inner) {
  min-height: 70px !important;
  line-height: 1.6;
}

.result-search-actions {
  display: flex;
  align-items: center;
  justify-content: flex-end;
  gap: 8px;
}

.inline-query-pane {
  min-height: 0;
}

.inline-control-grid {
  grid-template-columns: minmax(0, 1.4fr) minmax(160px, auto) minmax(180px, 0.8fr);
  align-items: start;
}

.knowledge-workspace-tabs {
  padding: 0 12px 12px;
  border: 1px solid var(--app-border-soft);
  border-radius: var(--app-radius-sm);
  background: #ffffff;
}

.knowledge-workspace-tabs :deep(.el-tabs__header) {
  margin-bottom: 12px;
}

.knowledge-workspace-tabs :deep(.el-tabs__content) {
  overflow: visible;
}

.rag-layout {
  display: grid;
  grid-template-columns: 340px minmax(0, 1fr);
  gap: 16px;
}

.literature-results-layout {
  grid-template-columns: minmax(0, 1fr);
}

.joint-results-layout {
  grid-template-columns: minmax(280px, 320px) minmax(0, 1fr) minmax(420px, 0.92fr);
  align-items: start;
}

.rag-layout.query-collapsed {
  grid-template-columns: 44px minmax(0, 1fr);
}

.joint-results-layout.query-collapsed {
  grid-template-columns: 44px minmax(0, 1fr) minmax(420px, 0.92fr);
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

.answer-pane--streaming {
  border-color: rgba(59, 130, 246, 0.34);
  box-shadow: inset 0 1px 0 rgba(59, 130, 246, 0.08);
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

.pane-toolbar {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 10px;
  margin-bottom: 14px;
}

.pane-toolbar .pane-heading {
  margin-bottom: 0;
}

.pane-toolbar.compact {
  align-items: center;
  margin-bottom: 10px;
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

.streaming-status {
  color: var(--app-primary-active);
  font-weight: 700;
}

.inline-loading-state {
  min-height: 42px;
  display: flex;
  align-items: center;
  padding: 10px 12px;
  border: 1px dashed rgba(59, 130, 246, 0.28);
  border-radius: var(--app-radius-sm);
  background: #f8fbff;
  color: var(--app-ink-muted);
  font-size: 12px;
}

.answer-generation-indicator {
  width: fit-content;
  display: inline-flex;
  align-items: center;
  justify-content: center;
  gap: 8px;
  align-self: center;
  padding: 7px 11px;
  border: 1px solid rgba(59, 130, 246, 0.26);
  border-radius: var(--app-radius-sm);
  background: #eef5ff;
  color: var(--app-primary-active);
  font-size: 12px;
  font-weight: 700;
}

.answer-generation-indicator--centered {
  width: 100%;
  min-height: 150px;
  flex: 1 1 auto;
  border-style: dashed;
  background: #f8fbff;
}

.answer-loading-icon {
  font-size: 18px;
  animation: answer-loading-spin 0.9s linear infinite;
}

@keyframes answer-loading-spin {
  from {
    transform: rotate(0deg);
  }

  to {
    transform: rotate(360deg);
  }
}

.answer-grid {
  display: grid;
  grid-template-columns: minmax(0, 1fr) 280px;
  gap: 14px;
  align-items: start;
}

.rag-layout.citations-collapsed .answer-grid {
  grid-template-columns: minmax(0, 1fr) 44px;
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

.side-restore-button {
  width: 44px;
  min-height: 160px;
  border: 1px solid var(--app-border-soft);
  border-radius: var(--app-radius-sm);
  background: #ffffff;
  color: var(--app-ink-muted);
  cursor: pointer;
  display: inline-flex;
  align-items: center;
  justify-content: center;
  gap: 8px;
  writing-mode: vertical-rl;
  text-orientation: mixed;
  font: inherit;
  font-size: 12px;
  font-weight: 700;
}

.side-restore-button:hover {
  border-color: var(--app-primary);
  color: var(--app-primary-active);
}

.side-restore-button .el-icon {
  writing-mode: horizontal-tb;
}

.query-restore-button {
  min-height: 480px;
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

.joint-graph-panel,
.graph-tab-panel {
  min-width: 0;
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

.graph-summary .graph-source-status {
  flex: 1 1 220px;
  min-width: min(280px, 100%);
  flex-direction: row;
  align-items: center;
  flex-wrap: wrap;
  justify-content: center;
  gap: 6px;
  padding: 8px 10px;
  border: 1px solid #bbf7d0;
  border-radius: var(--app-radius-sm);
  background: #f0fdf4;
}

.graph-source-status span {
  line-height: 1.4;
  text-transform: none;
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

.graph-view-segmented {
  flex: 0 0 auto;
  min-width: 168px;
}

.graph-workspace {
  display: grid;
  grid-template-columns: minmax(0, 1fr) 320px;
  gap: 16px;
}

.joint-graph-panel .graph-workspace,
.graph-tab-panel .graph-workspace {
  grid-template-columns: minmax(0, 1fr);
}

.graph-workspace.detail-collapsed {
  grid-template-columns: minmax(0, 1fr) 44px;
}

.joint-graph-panel .graph-workspace.detail-collapsed,
.graph-tab-panel .graph-workspace.detail-collapsed {
  grid-template-columns: minmax(0, 1fr);
}

.graph-main-pane {
  min-width: 0;
}

.graph-chart-pane,
.graph-board-pane {
  display: none;
}

.graph-chart-pane.active,
.graph-board-pane.active {
  display: block;
}

.graph-chart-pane {
  min-height: clamp(620px, calc(100vh - 340px), 760px);
  border: 1px solid var(--app-border-soft);
  border-radius: var(--app-radius-sm);
  background: #ffffff;
}

.joint-graph-panel .graph-chart-pane,
.graph-tab-panel .graph-chart-pane {
  min-height: clamp(420px, calc(100vh - 360px), 620px);
}

.graph-tab-panel .graph-chart-pane {
  min-height: clamp(560px, calc(100vh - 300px), 760px);
}

.relationship-chart {
  width: 100%;
  height: clamp(620px, calc(100vh - 340px), 760px);
}

.joint-graph-panel .relationship-chart,
.graph-tab-panel .relationship-chart {
  height: clamp(420px, calc(100vh - 360px), 620px);
}

.graph-tab-panel .relationship-chart {
  height: clamp(560px, calc(100vh - 300px), 760px);
}

.graph-board {
  min-height: clamp(620px, calc(100vh - 340px), 760px);
  display: grid;
  grid-template-columns: repeat(5, minmax(0, 1fr));
  gap: 10px;
  padding: 10px;
  border: 1px solid var(--app-border-soft);
  border-radius: var(--app-radius-sm);
  background: #f8fafc;
}

.joint-graph-panel .graph-board,
.graph-tab-panel .graph-board {
  min-height: clamp(420px, calc(100vh - 360px), 620px);
  grid-template-columns: repeat(auto-fit, minmax(168px, 1fr));
}

.graph-lane {
  min-width: 0;
  display: flex;
  flex-direction: column;
  border: 1px solid #e1e8f2;
  border-radius: var(--app-radius-sm);
  background: #ffffff;
}

.graph-lane--materials {
  border-color: #bddfca;
}

.graph-lane--summary {
  border-color: #bfdbfe;
}

.graph-lane--strategies {
  border-color: #bdd7ff;
}

.graph-lane--concepts {
  border-color: #bbf7d0;
}

.graph-lane--properties {
  border-color: #ead1a0;
}

.graph-lane--entities {
  border-color: #d9ccff;
}

.graph-lane--synthesis {
  border-color: #fed7aa;
}

.graph-lane--comparison {
  border-color: #fecaca;
}

.graph-lane--papers {
  border-color: #d8dee8;
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

.graph-lane--materials .graph-lane-header {
  background: #f0f8f2;
  color: #276749;
}

.graph-lane--summary .graph-lane-header {
  background: #eff6ff;
  color: #1d4ed8;
}

.graph-lane--strategies .graph-lane-header {
  background: #f0f6ff;
  color: #1d4f91;
}

.graph-lane--concepts .graph-lane-header {
  background: #ecfdf5;
  color: #047857;
}

.graph-lane--properties .graph-lane-header {
  background: #fff8e8;
  color: #8a5a00;
}

.graph-lane--entities .graph-lane-header {
  background: #f5f1ff;
  color: #6d28d9;
}

.graph-lane--papers .graph-lane-header {
  background: #f6f8fb;
  color: #64748b;
}

.graph-lane--synthesis .graph-lane-header {
  background: #fff7ed;
  color: #c2410c;
}

.graph-lane--comparison .graph-lane-header {
  background: #fef2f2;
  color: #b91c1c;
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
  position: relative;
  width: 100%;
  min-height: 48px;
  border: 1px solid #d4dfec;
  border-radius: var(--app-radius-sm);
  background: #ffffff;
  color: var(--app-ink);
  cursor: pointer;
  display: flex;
  flex-direction: column;
  align-items: flex-start;
  justify-content: center;
  gap: 2px;
  padding: 8px 8px 8px 12px;
  text-align: left;
  box-shadow: 0 8px 16px rgba(15, 23, 42, 0.06);
}

.graph-node::before {
  content: '';
  position: absolute;
  top: 8px;
  bottom: 8px;
  left: 0;
  width: 3px;
  border-radius: 0 3px 3px 0;
  background: #94a3b8;
}

.graph-node--materials::before {
  background: #2f855a;
}

.graph-node--summary::before {
  background: #2563eb;
}

.graph-node--strategies::before {
  background: #2563eb;
}

.graph-node--concepts::before {
  background: #10b981;
}

.graph-node--properties::before {
  background: #b7791f;
}

.graph-node--entities::before {
  background: #7c3aed;
}

.graph-node--synthesis::before {
  background: #f97316;
}

.graph-node--comparison::before {
  background: #ef4444;
}

.graph-node--papers {
  background: #f8fafc;
  box-shadow: none;
}

.graph-node--papers::before {
  background: #94a3b8;
}

.graph-node.active {
  border-color: var(--app-primary);
  box-shadow: 0 0 0 3px rgba(59, 130, 246, 0.14);
}

.graph-node span {
  max-width: 100%;
  display: -webkit-box;
  overflow: hidden;
  line-height: 1.35;
  -webkit-box-orient: vertical;
  -webkit-line-clamp: 2;
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
  min-height: clamp(620px, calc(100vh - 340px), 760px);
  padding: 14px;
  display: flex;
  flex-direction: column;
  gap: 12px;
}

.joint-graph-panel .graph-workspace > .node-detail,
.joint-graph-panel .node-restore-button,
.graph-tab-panel .graph-workspace > .node-detail,
.graph-tab-panel .node-restore-button {
  display: none;
}

.node-detail-header {
  justify-content: space-between;
  gap: 8px;
  min-width: 0;
}

.node-detail-actions {
  display: inline-flex;
  align-items: center;
  justify-content: flex-end;
  gap: 6px;
  flex-wrap: wrap;
}

.node-detail-header h4 {
  min-width: 0;
  overflow-wrap: anywhere;
}

.node-id-text {
  display: block;
  max-width: 100%;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.node-detail :deep(.el-descriptions__cell) {
  min-width: 0;
}

.node-detail :deep(.el-descriptions__content) {
  min-width: 0;
  overflow: hidden;
  overflow-wrap: anywhere;
}

.node-snippet {
  margin: 0;
  padding: 10px;
  border: 1px solid var(--app-border-soft);
  border-radius: var(--app-radius-sm);
  background: #f8fafc;
  color: var(--app-ink-body);
  font-size: 12px;
  line-height: 1.55;
}

.node-chip-block {
  display: flex;
  flex-direction: column;
  gap: 8px;
  padding: 10px;
  border: 1px solid var(--app-border-soft);
  border-radius: var(--app-radius-sm);
  background: #ffffff;
}

.node-chip-block > span,
.node-raw-block summary {
  color: var(--app-ink-muted);
  font-size: 12px;
  font-weight: 700;
}

.node-chip-block > div {
  display: flex;
  flex-wrap: wrap;
  gap: 6px;
}

.node-chip-block small {
  color: var(--app-ink-muted);
  font-size: 12px;
}

.node-raw-block {
  border: 1px solid var(--app-border-soft);
  border-radius: var(--app-radius-sm);
  background: #ffffff;
}

.node-raw-block summary {
  cursor: pointer;
  padding: 9px 10px;
}

.node-raw-block .property-json {
  border-radius: 0 0 var(--app-radius-sm) var(--app-radius-sm);
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
  white-space: pre-wrap;
  word-break: break-word;
}

.drawer-node-detail {
  min-height: 0;
  padding: 0;
  border: 0;
}

.edge-item {
  display: grid;
  grid-template-columns: minmax(0, 1fr) auto auto minmax(0, 1fr);
  gap: 6px;
  min-height: 34px;
  padding: 6px 8px;
  border: 1px solid var(--app-border-soft);
  border-radius: var(--app-radius-sm);
  color: var(--app-ink-body);
  font-size: 12px;
  min-width: 0;
}

.edge-node {
  min-width: 0;
  display: -webkit-box;
  overflow: hidden;
  line-height: 1.35;
  -webkit-box-orient: vertical;
  -webkit-line-clamp: 2;
  overflow-wrap: anywhere;
}

.edge-arrow {
  color: var(--app-ink-muted);
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
  .joint-results-layout,
  .literature-results-layout,
  .graph-workspace {
    grid-template-columns: 1fr;
  }

  .rag-layout.query-collapsed,
  .joint-results-layout.query-collapsed {
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

  .rag-layout.citations-collapsed .answer-grid {
    grid-template-columns: 1fr;
  }

  .side-restore-button {
    width: 100%;
    min-height: 42px;
    writing-mode: horizontal-tb;
  }

  .query-restore-button {
    min-height: 42px;
  }

  .graph-workspace > .node-detail {
    display: none;
  }
}

@media (max-width: 700px) {
  .knowledge-dock,
  .knowledge-header,
  .system-overview,
  .result-search-actions,
  .graph-toolbar,
  .graph-controls,
  .graph-summary {
    align-items: stretch;
    flex-direction: column;
  }

  .dock-summary,
  .dock-actions {
    width: 100%;
    justify-content: space-between;
  }

  .dock-status {
    max-width: none;
  }

  .header-actions {
    flex: 0 0 auto;
    width: 100%;
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

  .result-search-bar,
  .inline-control-grid {
    grid-template-columns: 1fr;
  }

  .result-search-actions {
    align-items: stretch;
  }

  .knowledge-query-entry {
    min-height: 360px;
    padding: 24px 0 36px;
  }

  .entry-advanced-grid {
    grid-template-columns: 1fr;
    align-items: stretch;
  }

  .entry-advanced-grid :deep(.el-segmented__group) {
    display: grid;
    grid-template-columns: repeat(3, minmax(0, 1fr));
  }

  .graph-board {
    grid-template-columns: repeat(2, minmax(0, 1fr));
    min-height: 520px;
  }

  .graph-view-segmented,
  .graph-chart-pane {
    display: none !important;
  }

  .graph-board-pane {
    display: block !important;
  }

  .type-legend {
    justify-content: flex-start;
  }
}

@media (max-width: 420px) {
  .entry-composer :deep(.el-textarea__inner) { padding: 14px 14px 58px; }
  .entry-submit { right: 10px; bottom: 10px; }

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
