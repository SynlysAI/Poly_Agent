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
  getKnowledgeGraph,
  getKnowledgeHealth,
  getKnowledgeSubgraph,
  listKnowledgeSystems,
  queryKnowledgeBase,
} from '../api/polyAgentApi'

const route = useRoute()
const router = useRouter()

const systems = ref([])
const health = ref(null)
const activeModule = ref(route.query.module === 'graph' ? 'graph' : 'rag')
const selectedSystemId = ref('ai4s_fluoropolymer')
const loadingSystems = ref(false)
const queryLoading = ref(false)
const graphLoading = ref(false)
const answer = ref(null)
const graph = ref(null)
const selectedNodeId = ref('')

const queryForm = reactive({
  question: '如何提高氟聚合物介电性能和热稳定性？',
  mode: 'hybrid',
  top_k: 5,
  include_graph_context: true,
})

const graphForm = reactive({
  query: 'fluoropolymer dielectric',
  limit: 30,
})

const selectedSystem = computed(() =>
  systems.value.find((item) => item.system_id === selectedSystemId.value) || systems.value[0] || null,
)

const graphNodes = computed(() => graph.value?.nodes || [])
const graphEdges = computed(() => graph.value?.edges || [])
const graphStats = computed(() => graph.value?.stats || { entity_count: 0, relation_count: 0, document_count: 0 })
const selectedNode = computed(() => graphNodes.value.find((item) => item.id === selectedNodeId.value) || graphNodes.value[0] || null)
const selectedNodeEdges = computed(() =>
  graphEdges.value.filter((item) => item.source === selectedNode.value?.id || item.target === selectedNode.value?.id),
)
const answerBlocks = computed(() => parseMarkdownBlocks(answer.value?.answer || ''))
const systemMetricItems = computed(() => [
  { label: '文档', value: selectedSystem.value?.document_count || graphStats.value.document_count || 0 },
  { label: '实体', value: selectedSystem.value?.entity_count || graphStats.value.entity_count || 0 },
  { label: '关系', value: selectedSystem.value?.relation_count || graphStats.value.relation_count || 0 },
  { label: '运行模式', value: health.value?.configured ? 'LightRAG' : 'Demo' },
])
const graphTypeCounts = computed(() => {
  const counts = {}
  graphNodes.value.forEach((node) => {
    counts[node.type] = (counts[node.type] || 0) + 1
  })
  return Object.entries(counts).map(([type, count]) => ({ type, count }))
})
const topCitations = computed(() => answer.value?.citations?.filter((item) => citationUrl(item)).slice(0, 8) || [])

const nodePositions = computed(() => {
  const nodes = graphNodes.value
  const positions = {}
  if (!nodes.length) return positions
  const lanes = [
    { x: 13, types: ['Material', 'Polymer', 'Monomer'] },
    { x: 35, types: ['Strategy', 'Method'] },
    { x: 58, types: ['Property', 'Application'] },
    { x: 82, types: ['Paper', 'Dataset'] },
  ]
  const laneFor = (node) => lanes.find((lane) => lane.types.includes(node.type)) || lanes[lanes.length - 1]
  lanes.forEach((lane) => {
    const laneNodes = nodes.filter((node) => laneFor(node) === lane)
    const step = laneNodes.length > 1 ? 76 / (laneNodes.length - 1) : 0
    laneNodes.forEach((node, index) => {
      positions[node.id] = {
        x: lane.x,
        y: laneNodes.length === 1 ? 50 : 12 + index * step,
      }
    })
  })
  return positions
})

const visibleEdges = computed(() =>
  graphEdges.value
    .map((edge) => ({
      ...edge,
      sourcePos: nodePositions.value[edge.source],
      targetPos: nodePositions.value[edge.target],
    }))
    .filter((edge) => edge.sourcePos && edge.targetPos),
)

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

function linkSegments(segments) {
  return segments || []
}

watch(activeModule, (module) => {
  router.replace({ query: { ...route.query, module } })
  if (module === 'graph' && !graph.value) {
    loadGraph()
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

function statusTagType(status) {
  if (status === 'ready') return 'success'
  if (status === 'warning') return 'warning'
  return 'danger'
}

function healthLabel() {
  if (!health.value) return '状态检查中'
  if (health.value.configured) return 'LightRAG 已连接'
  return 'Demo 数据可用'
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
    if (systems.value.length && !systems.value.some((item) => item.system_id === selectedSystemId.value)) {
      selectedSystemId.value = systems.value[0].system_id
    }
    health.value = healthData
    await Promise.all([runQuery(), loadGraph()])
  } catch (error) {
    ElMessage.error(getApiErrorMessage(error))
  } finally {
    loadingSystems.value = false
  }
}

async function runQuery() {
  if (!selectedSystemId.value || !queryForm.question.trim()) return
  queryLoading.value = true
  try {
    answer.value = await queryKnowledgeBase({
      system_id: selectedSystemId.value,
      question: queryForm.question,
      mode: queryForm.mode,
      top_k: queryForm.top_k,
      include_graph_context: queryForm.include_graph_context,
    })
    if (answer.value?.graph_context) {
      graph.value = answer.value.graph_context
      selectedNodeId.value = graph.value.nodes?.[0]?.id || ''
    }
  } catch (error) {
    ElMessage.error(getApiErrorMessage(error))
  } finally {
    queryLoading.value = false
  }
}

async function loadGraph() {
  if (!selectedSystemId.value) return
  graphLoading.value = true
  try {
    graph.value = graphForm.query.trim()
      ? await getKnowledgeSubgraph(selectedSystemId.value, { query: graphForm.query, limit: graphForm.limit })
      : await getKnowledgeGraph(selectedSystemId.value)
    selectedNodeId.value = graph.value.nodes?.[0]?.id || ''
  } catch (error) {
    ElMessage.error(getApiErrorMessage(error))
  } finally {
    graphLoading.value = false
  }
}

async function refreshAll() {
  await Promise.all([runQuery(), loadGraph()])
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
          <el-select v-model="selectedSystemId" class="system-select" @change="refreshAll">
            <el-option
              v-for="system in systems"
              :key="system.system_id"
              :label="system.name"
              :value="system.system_id"
            />
          </el-select>
          <el-tag v-if="health" :type="statusTagType(health.status)" effect="plain">
            {{ healthLabel() }}
          </el-tag>
          <el-button :icon="Refresh" @click="refreshAll">刷新</el-button>
        </div>
      </div>

      <div class="panel-body knowledge-body">
        <div class="system-overview">
          <div class="system-meta">
            <el-icon><Collection /></el-icon>
            <div>
              <strong>{{ selectedSystem?.name || 'AI4S 氟聚合物材料体系' }}</strong>
              <small>{{ selectedSystem?.description || '氟聚合物介电、热稳定与 AI4S 设计知识库' }}</small>
            </div>
          </div>
          <div class="system-metrics">
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
                <el-input v-model="queryForm.question" type="textarea" :rows="7" maxlength="2000" show-word-limit />
              </el-form-item>
              <div class="control-grid">
                <el-form-item label="模式">
                  <el-segmented
                    v-model="queryForm.mode"
                    :options="[
                      { label: 'Hybrid', value: 'hybrid' },
                      { label: 'Local', value: 'local' },
                      { label: 'Global', value: 'global' },
                      { label: 'Naive', value: 'naive' },
                      { label: 'Mix', value: 'mix' },
                    ]"
                  />
                </el-form-item>
                <el-form-item label="Top K">
                  <el-input-number v-model="queryForm.top_k" :min="1" :max="20" />
                </el-form-item>
              </div>
              <el-checkbox v-model="queryForm.include_graph_context">返回图谱上下文</el-checkbox>
              <div class="query-actions">
                <el-button type="primary" :loading="queryLoading" :icon="Search" @click="runQuery">检索问答</el-button>
              </div>
            </el-form>
            <div class="query-hints">
              <span>建议检索</span>
              <button type="button" @click="queryForm.question = 'PVDF 氟聚合物如何兼顾介电常数、击穿强度和热稳定性？'">PVDF 介电优化</button>
              <button type="button" @click="queryForm.question = '机器学习如何辅助高温聚合物介电材料筛选？'">AI4S 高温筛选</button>
              <button type="button" @click="queryForm.question = '多层结构和交联策略对储能密度有什么作用？'">结构策略</button>
            </div>
          </section>

          <section class="answer-pane" v-loading="queryLoading">
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
                    <span>{{ queryForm.mode }} · Top {{ queryForm.top_k }}</span>
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
                    <small>{{ shortSource(hit) }}</small>
                    <a v-if="citationUrl(hit)" :href="citationUrl(hit)" target="_blank" rel="noreferrer">DOI / Source</a>
                  </div>
                </article>
              </div>
            </div>
            <div v-else class="empty-state">
              <el-icon><DataAnalysis /></el-icon>
              <span>选择知识体系并输入问题后开始检索。</span>
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
              <el-input v-model="graphForm.query" placeholder="检索实体、论文、性质或方法" clearable @keyup.enter="loadGraph">
                <template #prefix><el-icon><Search /></el-icon></template>
              </el-input>
              <el-input-number v-model="graphForm.limit" :min="1" :max="100" />
              <el-button type="primary" :loading="graphLoading" @click="loadGraph">加载子图</el-button>
            </div>
          </section>

          <section class="graph-summary">
            <div>
              <span>Entities</span>
              <strong>{{ graphStats.entity_count }}</strong>
            </div>
            <div>
              <span>Relations</span>
              <strong>{{ graphStats.relation_count }}</strong>
            </div>
            <div>
              <span>Documents</span>
              <strong>{{ graphStats.document_count }}</strong>
            </div>
            <div class="type-legend">
              <el-tag v-for="item in graphTypeCounts" :key="item.type" size="small" effect="plain" :type="nodeTypeTag(item.type)">
                {{ item.type }} {{ item.count }}
              </el-tag>
            </div>
          </section>

          <section class="graph-workspace" v-loading="graphLoading">
            <div class="graph-canvas">
              <div class="graph-lane-labels" aria-hidden="true">
                <span>Materials</span>
                <span>Strategies</span>
                <span>Properties</span>
                <span>Papers</span>
              </div>
              <svg class="graph-lines" viewBox="0 0 100 100" preserveAspectRatio="none" aria-hidden="true">
                <line
                  v-for="edge in visibleEdges"
                  :key="edge.id"
                  :x1="edge.sourcePos.x"
                  :y1="edge.sourcePos.y"
                  :x2="edge.targetPos.x"
                  :y2="edge.targetPos.y"
                />
              </svg>
              <button
                v-for="node in graphNodes"
                :key="node.id"
                type="button"
                class="graph-node"
                :class="{ active: node.id === selectedNode?.id }"
                :style="{ left: `${nodePositions[node.id]?.x || 50}%`, top: `${nodePositions[node.id]?.y || 50}%` }"
                @click="selectNode(node.id)"
              >
                <span>{{ node.label }}</span>
                <small>{{ node.type }}</small>
              </button>
              <div v-if="!graphNodes.length" class="empty-state">
                <el-icon><Connection /></el-icon>
                <span>暂无图谱节点。</span>
              </div>
            </div>

            <aside class="node-detail">
              <div class="node-detail-header">
                <h4>{{ selectedNode?.label || '节点详情' }}</h4>
                <el-tag v-if="selectedNode" :type="nodeTypeTag(selectedNode.type)" effect="plain">{{ selectedNode.type }}</el-tag>
              </div>
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
  width: 260px;
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
  grid-template-columns: minmax(0, 1fr) 120px;
  gap: 12px;
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
.muted-text {
  color: var(--app-ink-muted);
  font-size: 12px;
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

.graph-canvas {
  position: relative;
  min-height: 560px;
  overflow: hidden;
  border: 1px solid var(--app-border-soft);
  border-radius: var(--app-radius-sm);
  background:
    linear-gradient(90deg, rgba(15, 23, 42, 0.05) 1px, transparent 1px),
    #f8fafc;
  background-size: 25% 100%;
}

.graph-lane-labels {
  position: absolute;
  inset: 10px 14px auto 14px;
  display: grid;
  grid-template-columns: repeat(4, 1fr);
  color: var(--app-ink-subtle);
  font-size: 11px;
  font-weight: 700;
  letter-spacing: 0.06em;
  text-transform: uppercase;
}

.graph-lines {
  position: absolute;
  inset: 0;
  width: 100%;
  height: 100%;
}

.graph-lines line {
  stroke: #9ab0c9;
  stroke-width: 0.35;
}

.graph-node {
  position: absolute;
  transform: translate(-50%, -50%);
  width: 142px;
  min-height: 54px;
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

  .graph-canvas {
    min-height: 520px;
  }

  .graph-node {
    width: 112px;
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
}
</style>
